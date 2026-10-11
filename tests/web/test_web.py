from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from planner.config import AppConfig
from planner.generators import base
from planner.web.app import create_app
from tests.generators.example_generator import register_example


def make_client(tmp_path: Path, **cfg) -> TestClient:
    app = create_app(AppConfig(data_dir=tmp_path / "data", **cfg))
    return TestClient(app, follow_redirects=False)


@pytest.fixture()
def client(tmp_path: Path):
    with make_client(tmp_path) as c:
        yield c


@pytest.fixture()
def seeded(client: TestClient):
    r = client.post("/seed")
    assert r.status_code == 303
    return client


def test_health_and_empty_dashboard(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    page = client.get("/")
    assert page.status_code == 200 and "Load demo data" in page.text
    assert client.get("/static/app.css").status_code == 200
    assert client.get("/static/htmx.min.js").status_code == 200


def test_all_list_pages_render_with_seed(seeded):
    for url, needle in [
        ("/", "Fall Camp Weekend"),
        ("/recipes", "Beef chili"),
        ("/ingredients", "Yellow onion"),
        ("/kitchens", "Camp kitchen"),
        ("/events", "Fall Camp Weekend"),
        ("/data", "Export"),
        ("/recipes?tag=backpacking", "Oatmeal"),
        ("/recipes?q=chili", "Beef chili"),
        ("/ingredients?section=produce&q=onion", "Yellow onion"),
    ]:
        r = seeded.get(url)
        assert r.status_code == 200, url
        assert needle in r.text, url
    assert "Peanut butter" not in seeded.get("/recipes?tag=bulk&q=oatmeal").text


def test_recipe_filters_exclude(seeded):
    page = seeded.get("/recipes?tag=no-cook").text
    assert "Sandwich bar" in page and "Beef chili" not in page


def recipe_form(**over):
    base_form = {
        "name": "Test soup",
        "base_servings": "10",
        "tags": "bulk, soup",
        "diets": "vegetarian",
        "max_batch_servings": "40",
        "ing_idx": ["a", "b"],
        "ing_ingredient_id_a": "onion",
        "ing_quantity_a": "2",
        "ing_unit_a": "lb",
        "ing_scaling_a": "linear",
        "ing_prep_note_a": "diced",
        "ing_ingredient_id_b": "eggs",
        "ing_quantity_b": "2",
        "ing_unit_b": "each",
        "ing_scaling_b": "stepped",
        "ing_step_size_b": "1",
        "st_idx": ["0", "1"],
        "st_title_0": "Chop",
        "st_duration_min_0": "15",
        "st_equipment_0": "prep_table",
        "st_time_scaling_0": "sqrt",
        "st_title_1": "Simmer",
        "st_duration_min_1": "40",
        "st_active_min_1": "10",
        "st_depends_on_1": "chop",
        "st_equipment_1": "burner, pot@4",
        "st_hold_min_1": "140",
        "st_hold_minutes_1": "120",
        "st_cooked_1": "on",
        "st_can_parallelize_0": "on",
        "st_can_parallelize_1": "on",
        "st_per_batch_1": "",
    }
    base_form.update(over)
    return base_form


def test_recipe_create_edit_duplicate_delete(seeded):
    r = seeded.post("/recipes", data=recipe_form())
    assert r.status_code == 303 and r.headers["location"].startswith("/recipes/test-soup/edit")
    page = seeded.get("/recipes/test-soup/edit")
    assert page.status_code == 200
    assert "Simmer" in page.text and "pot@4" in page.text and "sqrt" in page.text
    # edit: rename and add a note
    form = recipe_form(name="Test soup v2", description="better")
    assert seeded.post("/recipes/test-soup", data=form).status_code == 303
    assert "Test soup v2" in seeded.get("/recipes").text
    # duplicate
    r = seeded.post("/recipes/test-soup/duplicate")
    assert r.headers["location"].startswith("/recipes/test-soup-copy/edit")
    assert (
        seeded.post("/recipes/test-soup/duplicate")
        .headers["location"]
        .startswith("/recipes/test-soup-copy-2/edit")
    )
    # downloads
    assert "base_servings" in seeded.get("/recipes/test-soup.yaml").text
    assert seeded.get("/recipes/test-soup.json").json()["schema_version"] == 1
    assert seeded.get("/recipes/test-soup.xml").status_code == 404
    # delete
    assert seeded.post("/recipes/test-soup-copy/delete").status_code == 303
    assert seeded.get("/recipes/test-soup-copy/edit").status_code == 404
    assert seeded.get("/recipes/test-soup").status_code == 303


def test_recipe_validation_errors_rerender_with_input(seeded):
    bad = recipe_form(ing_ingredient_id_a="ghost", variants="vegetarian=missing-recipe")
    r = seeded.post("/recipes", data=bad)
    assert r.status_code == 422
    assert "not in the catalog" in r.text and "does not exist" in r.text
    assert "Test soup" in r.text  # the entered values are kept
    r = seeded.post("/recipes", data=recipe_form(st_duration_min_0="abc"))
    assert r.status_code == 422 and "not a whole number" in r.text
    r = seeded.post("/recipes", data=recipe_form(st_depends_on_1="nope"))
    assert r.status_code == 422 and "unknown step" in r.text
    r = seeded.post("/recipes", data=recipe_form(base_servings="0"))
    assert r.status_code == 422 and "base_servings" in r.text
    r = seeded.post("/recipes", data=recipe_form(st_depends_on_1="simmer"))
    assert r.status_code == 422 and "itself" in r.text
    r = seeded.post("/recipes", data=recipe_form(name="Beef chili", id="chili"))
    assert r.status_code == 422 and "already exists" in r.text
    r = seeded.post("/recipes", data=recipe_form(st_equipment_1="!!"))
    assert r.status_code == 422 and "cannot read equipment" in r.text
    assert seeded.post("/recipes", data=recipe_form(variants="oops")).status_code == 422


def test_recipe_in_use_cannot_be_deleted(seeded):
    r = seeded.post("/recipes/chili/delete")
    assert "Cannot%20delete" in r.headers["location"]
    assert seeded.get("/recipes/chili/edit").status_code == 200


def test_row_partials(seeded):
    assert 'name="ing_ingredient_id_n1"' in seeded.get("/recipes/_row/ingredient?i=n1").text
    assert 'name="st_title_n2"' in seeded.get("/recipes/_row/step?i=n2").text
    assert seeded.get("/recipes/_row/other").status_code == 404
    assert 'name="pk_size_x"' in seeded.get("/ingredients/_row/pack?i=x").text
    assert 'name="eq_type_x"' in seeded.get("/kitchens/_row/equipment?i=x").text
    assert 'name="ml_label_x"' in seeded.get("/events/_row/meal?i=x").text
    assert 'name="pa_quantity_x"' in seeded.get("/events/_row/pantry?i=x").text
    assert seeded.get("/events/_row/zzz").status_code == 404


def test_ingredient_crud(seeded):
    form = {
        "name": "Test flour",
        "store_section": "dry goods",
        "density_g_per_ml": "0.5",
        "trim_yield": "",
        "allergens": "wheat",
        "diet_flags": "vegan",
        "shelf_stable": "on",
        "pk_idx": ["0"],
        "pk_label_0": "25 lb bag",
        "pk_size_0": "25",
        "pk_unit_0": "lb",
    }
    r = seeded.post("/ingredients", data=form)
    assert r.status_code == 303
    page = seeded.get("/ingredients/test-flour/edit")
    assert "25 lb bag" in page.text and "wheat" in page.text
    assert (
        seeded.post("/ingredients/test-flour", data={**form, "name": "Renamed"}).status_code == 303
    )
    assert "Renamed" in seeded.get("/ingredients").text
    assert seeded.post("/ingredients", data=form).status_code in (303, 422)
    dup = seeded.post("/ingredients", data={**form, "id": "test-flour"})
    assert dup.status_code == 422 and "already exists" in dup.text
    bad = seeded.post("/ingredients", data={**form, "name": "Bad", "trim_yield": "7"})
    assert bad.status_code == 422 and "trim_yield" in bad.text
    assert seeded.post("/ingredients/test-flour/delete").status_code == 303
    assert seeded.get("/ingredients/test-flour/edit").status_code == 404
    assert "Cannot%20delete" in seeded.post("/ingredients/onion/delete").headers["location"]
    assert seeded.get("/ingredients/new").status_code == 200
    assert seeded.post("/ingredients/ghost", data=form).status_code == 404


def test_kitchen_crud(seeded):
    form = {
        "name": "Garage kitchen",
        "max_cooks": "3",
        "supports_tags": "bulk",
        "work_start": "07:00",
        "work_end": "21:00",
        "eq_idx": ["0", "1"],
        "eq_type_0": "burner",
        "eq_count_0": "2",
        "eq_type_1": "pot",
        "eq_count_1": "1",
        "eq_capacity_1": "20",
    }
    r = seeded.post("/kitchens", data=form)
    assert r.status_code == 303
    page = seeded.get("/kitchens/garage-kitchen/edit")
    assert "Garage kitchen" in page.text and 'value="20"' in page.text
    assert (
        seeded.post("/kitchens/garage-kitchen", data={**form, "max_cooks": "4"}).status_code == 303
    )
    bad = seeded.post("/kitchens", data={**form, "name": "Bad", "work_start": "23:00"})
    assert bad.status_code == 422 and "work_start" in bad.text
    bad = seeded.post("/kitchens", data={**form, "name": "Bad2", "eq_count_0": "x"})
    assert bad.status_code == 422
    assert seeded.post("/kitchens", data={**form, "id": "garage-kitchen"}).status_code == 422
    assert seeded.post("/kitchens/garage-kitchen/delete").status_code == 303
    assert "Cannot%20delete" in seeded.post("/kitchens/camp-kitchen/delete").headers["location"]
    assert seeded.get("/kitchens/new").status_code == 200
    assert seeded.get("/kitchens/ghost/edit").status_code == 404


def event_form(**over):
    f = {
        "name": "Test trip",
        "kitchen_profile_id": "backpacking",
        "start_date": "2025-08-01",
        "days": "2",
        "notes": "",
        "ml_idx": ["0"],
        "ml_day_0": "0",
        "ml_label_0": "dinner",
        "ml_serve_time_0": "19:00",
        "ml_headcount_0": "6",
        "ml_portion_factor_0": "1",
        "ml_splits_0": "",
        "ml_recipes_0": ["couscous-veg"],
        "pa_idx": ["0"],
        "pa_ingredient_id_0": "salt",
        "pa_quantity_0": "1",
        "pa_unit_0": "lb",
    }
    f.update(over)
    return f


def test_event_builder_and_validation(seeded):
    r = seeded.post("/events", data=event_form())
    assert r.status_code == 303
    page = seeded.get("/events/test-trip/edit")
    assert "Test trip" in page.text and "couscous-veg" in page.text
    # live validation: profile mismatch warning for a backpacking-only recipe on the camp kitchen
    seeded.post(
        "/recipes",
        data=recipe_form(name="Trail mix only", tags="backpacking-only", id="trail-only"),
    )
    v = seeded.post(
        "/events/_validate",
        data=event_form(kitchen_profile_id="camp-kitchen", ml_recipes_0=["trail-only"]),
    )
    assert v.status_code == 200 and "backpacking-only" in v.text
    ok = seeded.post("/events/_validate", data=event_form())
    assert "Looks good" in ok.text or "Heads up" in ok.text
    bad = seeded.post("/events/_validate", data=event_form(ml_headcount_0="0"))
    assert "Fix these first" in bad.text
    # conflicts show up while editing: 120 people on the backpacking stove
    conflict = seeded.post(
        "/events/_validate", data=event_form(ml_headcount_0="120", ml_recipes_0=["chili"])
    )
    assert "problem" in conflict.text
    # unknown recipe is an error
    unk = seeded.post("/events/_validate", data=event_form(ml_recipes_0=["nope"]))
    assert "unknown recipe" in unk.text
    # save errors
    assert (
        seeded.post("/events", data=event_form(kitchen_profile_id="ghost", name="X")).status_code
        == 422
    )
    assert seeded.post("/events", data=event_form(ml_splits_0="oops", name="Y")).status_code == 422
    assert seeded.post("/events", data=event_form(id="test-trip")).status_code == 422
    assert seeded.post("/events/test-trip", data=event_form(name="Renamed trip")).status_code == 303
    assert "Renamed trip" in seeded.get("/events").text
    r = seeded.post("/events/test-trip/duplicate")
    assert r.headers["location"].startswith("/events/test-trip-copy/edit")
    assert seeded.post("/events/test-trip-copy/delete").status_code == 303
    assert seeded.get("/events/new").status_code == 200
    assert seeded.get("/events/ghost/edit").status_code == 404
    assert seeded.post("/events/ghost", data=event_form()).status_code == 404


def test_plan_tabs_print_pdf_csv(seeded):
    base_url = "/events/fall-camp-weekend/plan"
    r = seeded.get(base_url)
    assert r.status_code == 303 and r.headers["location"].endswith("/plan/shopping")
    for gen, needle in [
        ("shopping", "Shopping list"),
        ("timeline", "Timeline"),
        ("recipes", "Make 3 batches of ~40 servings"),
    ]:
        page = seeded.get(f"{base_url}/{gen}")
        assert page.status_code == 200 and needle in page.text, gen
        assert "Print view" in page.text and "Download PDF" in page.text
        assert "Shopping list</a>" in page.text and "Recipe sheets</a>" in page.text
        printed = seeded.get(f"{base_url}/{gen}/print")
        assert printed.status_code == 200 and "@page" in printed.text and needle in printed.text
    assert "size: letter" in seeded.get(f"{base_url}/shopping/print").text
    assert "size: A4" in seeded.get(f"{base_url}/shopping/print?page=A4").text
    assert "size: A4" in seeded.get("/print.css?page=a4").text
    pdf = seeded.get(f"{base_url}/shopping/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert pdf.headers["content-type"] == "application/pdf"
    csv = seeded.get(f"{base_url}/shopping/csv")
    assert csv.status_code == 200 and csv.text.startswith("section,ingredient")
    assert seeded.get(f"{base_url}/recipes/csv").status_code == 404  # no CSV for sheets
    assert seeded.get(f"{base_url}/nothing").status_code == 404
    assert seeded.get("/events/ghost/plan/shopping").status_code == 404


def test_plan_page_shows_conflicts_banner(seeded):
    seeded.post(
        "/events",
        data=event_form(
            kitchen_profile_id="backpacking",
            ml_headcount_0="120",
            ml_recipes_0=["chili"],
            name="Too big",
        ),
    )
    page = seeded.get("/events/too-big/plan/timeline")
    assert page.status_code == 200 and "conflict" in page.text.lower()


def test_plan_with_missing_kitchen_is_a_clear_error(seeded):
    seeded.post("/events", data=event_form(name="Orphan"))
    seeded.app.state.engine  # noqa: B018
    from sqlmodel import Session

    from planner.storage.repo import Repository

    with Session(seeded.app.state.engine) as s:
        Repository(s).delete("kitchens", "backpacking")
    assert seeded.get("/events/orphan/plan/shopping").status_code == 409


def test_import_export_via_web(seeded):
    y = seeded.get("/export.yaml")
    assert y.status_code == 200 and "schema_version: 1" in y.text
    assert seeded.get("/export.json").json()["kind"] == "planner-bundle"
    assert seeded.get("/export.csv").status_code == 404
    # replace with a tiny file
    tiny = b"schema_version: 1\ningredients:\n  - {id: salt, name: Salt}\n"
    r = seeded.post("/import", files={"file": ("x.yaml", tiny)}, data={"replace": "1"})
    assert r.status_code == 303
    assert (
        "Salt" in seeded.get("/ingredients").text
        and "Beef chili" not in seeded.get("/recipes").text
    )
    # restore from the export we took
    r = seeded.post("/import", files={"file": ("all.yaml", y.content)}, data={"replace": "1"})
    assert r.status_code == 303
    assert "Beef chili" in seeded.get("/recipes").text
    bad = seeded.post(
        "/import", files={"file": ("bad.yaml", b"schema_version: 1\nrecipes:\n - {id: X}\n")}
    )
    assert bad.status_code == 422 and "Import failed" in bad.text
    assert seeded.post("/seed", data={"replace": "1"}).status_code == 303


def test_generator_registered_by_a_test_appears_without_other_changes(tmp_path):
    gen = register_example()
    try:
        with make_client(tmp_path) as c:
            c.post("/seed")
            plan = "/events/fall-camp-weekend/plan"
            page = c.get(f"{plan}/shopping")
            assert "Head counts" in page.text  # tab appears automatically
            tab = c.get(f"{plan}/headcount")
            assert tab.status_code == 200 and "Total served: 840" in tab.text
            assert "Friday dinner: 120" in c.get(f"{plan}/headcount/print").text
            assert c.get(f"{plan}/headcount/csv").text.startswith("meal,people")
            assert c.get(f"{plan}/headcount/pdf").content.startswith(b"%PDF")
    finally:
        base.unregister(gen.id)
    with make_client(tmp_path / "again") as c:
        c.post("/seed")
        assert "Head counts" not in c.get("/events/fall-camp-weekend/plan/shopping").text


def test_password_protection(tmp_path):
    with make_client(tmp_path, password="s3cret") as c:
        assert c.get("/healthz").status_code == 200  # always open
        assert c.get("/static/app.css").status_code == 200
        r = c.get("/recipes")
        assert r.status_code == 303 and r.headers["location"].startswith("/login?next=")
        hx = c.get("/recipes", headers={"HX-Request": "true"})
        assert hx.status_code == 401 and hx.headers["HX-Redirect"] == "/login"
        assert "Log in" in c.get("/login").text
        bad = c.post("/login", data={"password": "nope", "next": "/"})
        assert bad.status_code == 401 and "Wrong password" in bad.text
        ok = c.post("/login", data={"password": "s3cret", "next": "/recipes"})
        assert ok.status_code == 303 and ok.headers["location"] == "/recipes"
        assert c.get("/recipes").status_code == 200
        evil = c.post("/login", data={"password": "s3cret", "next": "//evil.example"})
        assert evil.headers["location"] == "/"
        assert c.post("/logout").status_code == 303
        assert c.get("/recipes").status_code == 303


def test_forged_cookie_rejected(tmp_path):
    with make_client(tmp_path, password="pw") as c:
        c.cookies.set("planner_session", "forged")
        assert c.get("/recipes").status_code == 303


def test_login_without_password_configured(client):
    r = client.post("/login", data={"password": "", "next": "/"})
    assert r.status_code == 303


def test_fresh_empty_data_dir_is_migrated_at_startup(tmp_path):
    data = tmp_path / "fresh" / "data"
    assert not data.exists()
    with make_client(tmp_path / "fresh") as c:
        assert c.get("/healthz").status_code == 200
    assert (tmp_path / "fresh" / "data" / "planner.db").exists()
    assert data.exists()
