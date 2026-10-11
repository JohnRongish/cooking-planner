from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import ValidationError

from planner.core.models import Recipe
from planner.core.units import known_units
from planner.storage import portability as pt
from planner.storage.repo import Repository
from planner.web import forms
from planner.web.common import get_repo, redirect, render

router = APIRouter()


def _form_ctx(repo: Repository, state: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "f": state,
        "ingredients": sorted(repo.ingredients(), key=lambda i: i.name.lower()),
        "units": known_units(),
        "recipe_choices": [(r.id, r.name) for r in repo.recipes()],
        **extra,
    }


@router.get("/recipes", response_class=HTMLResponse)
def list_recipes(
    request: Request, tag: str = "", q: str = "", repo: Repository = Depends(get_repo)
) -> Response:
    return render(
        request,
        "pages/recipes.html",
        recipes=repo.recipes(tag=tag or None, q=q or None),
        tags=repo.recipe_tags(),
        tag=tag,
        q=q,
    )


@router.get("/recipes/new", response_class=HTMLResponse)
def new_recipe(request: Request, repo: Repository = Depends(get_repo)) -> Response:
    return render(
        request,
        "pages/recipe_form.html",
        **_form_ctx(repo, forms.recipe_to_form(None), is_new=True, action="/recipes", errors=[]),
    )


@router.get("/recipes/_row/{kind}", response_class=HTMLResponse)
def recipe_row(
    request: Request, kind: str, i: str = "0", repo: Repository = Depends(get_repo)
) -> Response:
    if kind not in ("ingredient", "step"):
        raise HTTPException(404)
    env = request.app.state.env
    ctx = _form_ctx(repo, {})
    blank_ing = {"idx": i, "ingredient_id": "", "quantity": "", "unit": "each", "prep_note": "",
                 "scaling": "linear", "step_size": ""}  # fmt: skip
    blank_step = {k: "" for k in forms.STEP_FIELDS} | {
        "idx": i, "time_scaling": "none", "duration_min": "10", "cooked": False,
        "can_parallelize": True,
    }  # fmt: skip
    tmpl = env.from_string(
        '{% import "pages/_rows.html" as r %}'
        + (
            "{{ r.ing_row(row, ingredients, units) }}"
            if kind == "ingredient"
            else "{{ r.step_row(row) }}"
        )
    )
    html = tmpl.render(row=blank_ing if kind == "ingredient" else blank_step, **ctx)
    return HTMLResponse(html)


def _save(
    request: Request, repo: Repository, state: dict[str, Any], existing: Recipe | None, is_new: bool
) -> Response:
    errors: list[str] = []
    recipe: Recipe | None = None
    try:
        data = forms.recipe_data_from_state(state, existing)
        if existing is not None:
            data["id"] = existing.id
        recipe = Recipe.model_validate(data)
        if is_new and repo.exists("recipes", recipe.id):
            errors.append(f"A recipe with id {recipe.id!r} already exists")
        for diet, vid in recipe.variants.items():
            if not repo.exists("recipes", vid):
                errors.append(f"Variant for {diet!r}: recipe {vid!r} does not exist")
        for ri in recipe.ingredients:
            if not repo.exists("ingredients", ri.ingredient_id):
                errors.append(f"Ingredient {ri.ingredient_id!r} is not in the catalog")
    except forms.FormError as exc:
        errors.extend(exc.messages)
    except ValidationError as exc:
        errors.extend(forms.format_validation_error(exc))
    if errors or recipe is None:
        return render(
            request,
            "pages/recipe_form.html",
            status_code=422,
            **_form_ctx(
                repo,
                state,
                is_new=is_new,
                action="/recipes" if is_new else f"/recipes/{existing.id if existing else ''}",
                errors=errors,
            ),
        )
    repo.upsert(recipe)
    return redirect(f"/recipes/{recipe.id}/edit", "Recipe saved")


@router.post("/recipes", response_class=HTMLResponse)
async def create_recipe(request: Request, repo: Repository = Depends(get_repo)) -> Response:
    state = forms.recipe_form_state(await request.form())  # type: ignore[arg-type]
    return _save(request, repo, state, None, True)


@router.get("/recipes/{rid}/edit", response_class=HTMLResponse)
def edit_recipe(request: Request, rid: str, repo: Repository = Depends(get_repo)) -> Response:
    r = repo.get("recipes", rid)
    if r is None:
        raise HTTPException(404, "recipe not found")
    used = [e.name for e in repo.events_using_recipe(rid)]
    return render(
        request,
        "pages/recipe_form.html",
        **_form_ctx(
            repo,
            forms.recipe_to_form(r),
            is_new=False,
            action=f"/recipes/{rid}",
            errors=[],
            used_in=used,
        ),
    )


@router.get("/recipes/{rid}.{fmt}")
def download_recipe(rid: str, fmt: str, repo: Repository = Depends(get_repo)) -> Response:
    r = repo.get("recipes", rid)
    if r is None or fmt not in ("yaml", "json"):
        raise HTTPException(404)
    doc = r.model_dump(mode="json")
    if fmt == "json":
        import json

        body, mime = json.dumps({"schema_version": 1, **doc}, indent=2), "application/json"
    else:
        body, mime = pt.dump_yaml({"schema_version": 1, **doc}), "text/yaml"
    return Response(
        body,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{rid}.{fmt}"'},
    )


@router.get("/recipes/{rid}")
def view_recipe(rid: str) -> Response:
    return redirect(f"/recipes/{rid}/edit")


@router.post("/recipes/{rid}", response_class=HTMLResponse)
async def update_recipe(
    request: Request, rid: str, repo: Repository = Depends(get_repo)
) -> Response:
    existing = repo.get("recipes", rid)
    if existing is None:
        raise HTTPException(404, "recipe not found")
    state = forms.recipe_form_state(await request.form())  # type: ignore[arg-type]
    return _save(request, repo, state, existing, False)


@router.post("/recipes/{rid}/duplicate")
def duplicate_recipe(rid: str, repo: Repository = Depends(get_repo)) -> Response:
    r = repo.get("recipes", rid)
    if r is None:
        raise HTTPException(404, "recipe not found")
    n, new_id = 1, f"{rid}-copy"
    while repo.exists("recipes", new_id):
        n += 1
        new_id = f"{rid}-copy-{n}"
    repo.upsert(r.model_copy(update={"id": new_id, "name": f"{r.name} (copy)"}))
    return redirect(f"/recipes/{new_id}/edit", "Recipe duplicated")


@router.post("/recipes/{rid}/delete")
def delete_recipe(rid: str, repo: Repository = Depends(get_repo)) -> Response:
    used = repo.events_using_recipe(rid)
    if used:
        return redirect("/recipes", f"Cannot delete: used by event {used[0].name!r}")
    repo.delete("recipes", rid)
    return redirect("/recipes", "Recipe deleted")
