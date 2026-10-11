from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlmodel import Session

from planner.core.plan import build_plan
from planner.storage import portability as pt
from planner.storage.db import make_engine, run_migrations
from planner.storage.repo import Repository

FIXTURE = Path(__file__).parent / "fixtures" / "sample_bundle.yaml"


def load(repo: Repository) -> None:
    pt.import_bundle(repo, pt.load_path(FIXTURE))


def plan_summary(repo: Repository):
    ings, recipes, kitchens = repo.catalog()
    ev = repo.get("events", "demo")
    plan = build_plan(
        ev, recipes=recipes, ingredients=ings, kitchen=kitchens[ev.kitchen_profile_id]
    )
    return [(s.instance.key, s.start, s.end, s.stations) for s in plan.schedule.steps], [
        (pr.recipe.id, pr.servings, [(ln.ingredient_id, ln.needed) for ln in pr.lines])
        for pr in plan.planned_recipes()
    ]


def test_migrations_create_tables_and_are_idempotent(db_url):
    run_migrations(db_url)  # second run is a no-op
    engine = make_engine(db_url)
    with Session(engine) as s:
        assert Repository(s).count("recipes") == 0
    engine.dispose()


def test_crud(repo):
    load(repo)
    assert repo.count("recipes") == 1 and repo.exists("recipes", "rice-and-onions")
    r = repo.get("recipes", "rice-and-onions")
    assert r.extras == {"future_field": [1, 2, 3]}
    assert [x.id for x in repo.recipes(tag="vegetarian")] == ["rice-and-onions"]
    assert repo.recipes(tag="veg") == []  # whole-tag matching
    assert [x.id for x in repo.recipes(q="onions")] == ["rice-and-onions"]
    assert repo.recipe_tags() == ["bulk", "vegetarian"]
    assert [r.id for r in repo.recipes_using_ingredient("onion")] == ["rice-and-onions"]
    assert [e.id for e in repo.events_using_recipe("rice-and-onions")] == ["demo"]
    assert [e.id for e in repo.events_using_kitchen("tiny")] == ["demo"]
    assert repo.delete("recipes", "rice-and-onions") is True
    assert repo.delete("recipes", "rice-and-onions") is False
    assert repo.get("recipes", "nope") is None
    assert [i.id for i in repo.ingredients()] == ["rice", "onion"]  # ordered by name
    assert [k.id for k in repo.kitchens()] == ["tiny"]
    assert [e.id for e in repo.events()] == ["demo"]


def test_upsert_replaces(repo):
    load(repo)
    r = repo.get("recipes", "rice-and-onions")
    repo.upsert(r.model_copy(update={"name": "Renamed"}))
    assert repo.get("recipes", "rice-and-onions").name == "Renamed"
    assert repo.count("recipes") == 1


@pytest.mark.parametrize("fmt", ["yaml", "json"])
def test_export_wipe_import_gives_identical_plan(repo, tmp_path, fmt):
    load(repo)
    before = plan_summary(repo)
    exported = pt.export_to_dir(repo, tmp_path / "out", fmt)
    assert {p.name for p in exported} == {f"{k}.{fmt}" for k in pt.KIND_ORDER}
    repo.wipe()
    assert repo.count("recipes") == 0
    pt.import_bundle(repo, pt.load_path(tmp_path / "out"))
    assert plan_summary(repo) == before


def test_single_bundle_round_trip_is_stable(repo):
    load(repo)
    text1 = pt.bundle_text(repo)
    repo.wipe()
    pt.import_text(repo, text1)
    assert pt.bundle_text(repo) == text1
    data = json.loads(pt.bundle_text(repo, "json"))
    assert data["schema_version"] == 1 and data["kind"] == "planner-bundle"


def test_replace_import_wipes_other_rows(repo):
    load(repo)
    doc = {"schema_version": 1, "ingredients": [{"id": "salt", "name": "Salt"}]}
    pt.import_bundle(repo, pt.parse_document(doc), replace=True)
    assert [i.id for i in repo.ingredients()] == ["salt"]
    assert repo.count("recipes") == 0


def test_import_errors_are_collected_and_nothing_written(repo):
    doc = {
        "schema_version": 1,
        "ingredients": [{"id": "Bad Id", "name": "x"}, {"id": "ok", "name": "ok"}],
        "recipes": [{"id": "r", "name": "R", "base_servings": 0}],
        "bogus": [],
    }
    with pytest.raises(pt.ImportError_) as e:
        pt.parse_document(doc, "x.yaml")
    msg = str(e.value)
    assert "Bad Id" in msg and "base_servings" in msg and "unknown top-level keys" in msg
    assert repo.count("ingredients") == 0


def test_schema_version_checks():
    with pytest.raises(pt.ImportError_, match="unsupported schema_version"):
        pt.parse_document({"schema_version": 99})
    with pytest.raises(pt.ImportError_, match="not a recognisable"):
        pt.parse_document({"hello": 1})
    with pytest.raises(pt.ImportError_, match="mapping"):
        pt.parse_document([1])
    with pytest.raises(pt.ImportError_, match="must be a list"):
        pt.parse_document({"schema_version": 1, "recipes": {"a": 1}})
    assert pt.parse_document({"schema_version": 1, "recipes": None}).recipes == []


def test_bare_entities_are_detected():
    ev = {
        "id": "e",
        "name": "E",
        "kitchen_profile_id": "k",
        "start_date": "2025-01-01",
        "meals": [],
    }
    assert len(pt.parse_document(ev).events) == 1
    assert len(pt.parse_document({"id": "r", "name": "R", "base_servings": 2}).recipes) == 1
    assert len(pt.parse_document({"id": "k", "name": "K", "equipment_inventory": []}).kitchens) == 1
    assert (
        len(pt.parse_document({"id": "i", "name": "I", "store_section": "dairy"}).ingredients) == 1
    )


def test_load_path_errors(tmp_path):
    with pytest.raises(pt.ImportError_, match="not found"):
        pt.load_path(tmp_path / "missing.yaml")
    (tmp_path / "empty").mkdir()
    with pytest.raises(pt.ImportError_, match="no .yaml"):
        pt.load_path(tmp_path / "empty")
    bad = tmp_path / "bad.yaml"
    bad.write_text("a: [unclosed", encoding="utf-8")
    with pytest.raises(pt.ImportError_, match="invalid YAML"):
        pt.load_path(bad)
    with pytest.raises(pt.ImportError_, match="invalid YAML"):
        pt.import_text(Repository.__new__(Repository), "a: [unclosed")


def test_json_files_are_read(tmp_path, repo):
    d = tmp_path / "j"
    d.mkdir()
    (d / "x.json").write_text(
        json.dumps({"schema_version": 1, "ingredients": [{"id": "salt", "name": "Salt"}]})
    )
    bundle = pt.load_path(d)
    assert bundle.counts()["ingredients"] == 1
    assert pt.import_bundle(repo, bundle)["ingredients"] == 1


def test_failed_import_rolls_back(repo, monkeypatch):
    load(repo)
    bundle = pt.parse_document({"schema_version": 1, "ingredients": [{"id": "a", "name": "A"}]})

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(repo, "upsert", boom)
    with pytest.raises(RuntimeError):
        pt.import_bundle(repo, bundle, replace=True)
    assert repo.count("recipes") == 1  # wipe was rolled back
