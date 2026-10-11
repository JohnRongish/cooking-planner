from __future__ import annotations

from pathlib import Path

import pytest

from planner import cli
from planner.cli import SEED_DIR


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANNER_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def test_seed_export_import_cycle(env, capsys):
    assert cli.main(["seed"]) == 0
    assert "seeded" in capsys.readouterr().out
    assert cli.main(["export", str(env / "out")]) == 0
    assert (env / "out" / "recipes.yaml").exists()
    assert cli.main(["export", str(env / "outj"), "--format", "json"]) == 0
    assert (env / "outj" / "recipes.json").exists()
    assert cli.main(["import", str(env / "out"), "--replace"]) == 0
    assert "imported" in capsys.readouterr().out
    assert cli.main(["migrate"]) == 0


def test_import_error_exit_code(env, capsys):
    bad = env / "bad.yaml"
    bad.write_text("schema_version: 1\nrecipes:\n  - {id: Bad Id, name: x, base_servings: 1}\n")
    assert cli.main(["import", str(bad)]) == 2
    assert "Bad Id" in capsys.readouterr().err


def test_plan_command_writes_outputs(env, capsys):
    out = env / "plan-out"
    code = cli.main(
        [
            "plan",
            str(SEED_DIR / "events.yaml"),
            "--data",
            str(SEED_DIR),
            "--event-id",
            "backpacking-trip",
            "--out",
            str(out),
            "--pdf",
            "--strict",
        ]
    )
    assert code == 0
    for name in ("shopping.html", "timeline.html", "recipes.html", "shopping.csv", "timeline.csv"):
        assert (out / name).exists(), name
    assert (out / "recipes.pdf").read_bytes().startswith(b"%PDF")
    assert "Plan for" in capsys.readouterr().out


def test_plan_from_standalone_bundle_and_db(env, capsys):
    one = env / "bundle.yaml"
    from planner.storage import portability as pt

    b = pt.load_path(SEED_DIR)
    b.events = [e for e in b.events if e.id == "backpacking-trip"]
    from planner.storage.db import make_engine, run_migrations  # noqa: F401

    # a full bundle file works on its own
    one.write_text(_bundle_text(b))
    assert cli.main(["plan", str(one)]) == 0
    # an event-only file uses the catalog from the database
    assert cli.main(["seed"]) == 0
    ev = env / "event.yaml"
    ev.write_text((SEED_DIR / "events.yaml").read_text())
    assert cli.main(["plan", str(ev), "--event-id", "backpacking-trip"]) == 0
    with pytest.raises(SystemExit):
        cli.main(["plan", str(ev), "--event-id", "nope"])
    with pytest.raises(SystemExit):
        cli.main(["plan", str(ev), "--event-id", "backpacking-trip", "--kitchen", "nope"])
    capsys.readouterr()


def _bundle_text(b) -> str:
    docs = {"schema_version": 1, "kind": "planner-bundle"}
    for k in ("ingredients", "recipes", "kitchens", "events"):
        docs[k] = [m.model_dump(mode="json") for m in getattr(b, k)]
    from planner.storage.portability import dump_yaml

    return dump_yaml(docs)


def test_strict_flag_returns_1_on_conflict(env):
    p = Path(env / "e.yaml")
    from planner.storage import portability as pt

    b = pt.load_path(SEED_DIR)
    ev = next(e for e in b.events if e.id == "fall-camp-weekend")
    tiny = next(k for k in b.kitchens if k.id == "backpacking")
    ev = ev.model_copy(update={"kitchen_profile_id": tiny.id})
    b.events = [ev]
    p.write_text(_bundle_text(b))
    assert cli.main(["plan", str(p), "--strict"]) == 1
    assert cli.main(["plan", str(p)]) == 0
