"""Ingredient catalog and kitchen profile editors."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import ValidationError

from planner.core.models import Ingredient, KitchenProfile
from planner.core.units import known_units
from planner.storage.repo import Repository
from planner.web import forms
from planner.web.common import get_repo, redirect, render

router = APIRouter()

SECTIONS = ["produce", "meat", "dairy", "bakery", "dry goods", "canned", "frozen", "spices",
            "condiments", "other"]  # fmt: skip


# ----------------------------------------------------------------------------- ingredients


@router.get("/ingredients", response_class=HTMLResponse)
def list_ingredients(
    request: Request, q: str = "", section: str = "", repo: Repository = Depends(get_repo)
) -> Response:
    items = repo.ingredients()
    if q:
        items = [i for i in items if q.lower() in i.name.lower() or q.lower() in i.id]
    if section:
        items = [i for i in items if i.store_section == section]
    sections = sorted({i.store_section for i in repo.ingredients()})
    return render(
        request,
        "pages/ingredients.html",
        ingredients=items,
        q=q,
        section=section,
        sections=sections,
    )


def _ing_ctx(state: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"f": state, "units": known_units(), "sections": SECTIONS, **extra}


@router.get("/ingredients/new", response_class=HTMLResponse)
def new_ingredient(request: Request) -> Response:
    return render(
        request,
        "pages/ingredient_form.html",
        **_ing_ctx(forms.ingredient_to_form(None), is_new=True, action="/ingredients", errors=[]),
    )


@router.get("/ingredients/_row/pack", response_class=HTMLResponse)
def pack_row(request: Request, i: str = "0") -> Response:
    env = request.app.state.env
    tmpl = env.from_string('{% import "pages/_rows.html" as r %}{{ r.pack_row(row, units) }}')
    return HTMLResponse(
        tmpl.render(row={"idx": i, "label": "", "size": "", "unit": "lb"}, units=known_units())
    )


def _save_ingredient(
    request: Request,
    repo: Repository,
    state: dict[str, Any],
    existing: Ingredient | None,
    is_new: bool,
) -> Response:
    errors: list[str] = []
    ing = None
    try:
        data = forms.ingredient_data_from_state(state, existing)
        if existing is not None:
            data["id"] = existing.id
        ing = Ingredient.model_validate(data)
        if is_new and repo.exists("ingredients", ing.id):
            errors.append(f"An ingredient with id {ing.id!r} already exists")
    except ValidationError as exc:
        errors.extend(forms.format_validation_error(exc))
    if errors or ing is None:
        return render(
            request,
            "pages/ingredient_form.html",
            status_code=422,
            **_ing_ctx(
                state,
                is_new=is_new,
                errors=errors,
                action="/ingredients"
                if is_new
                else f"/ingredients/{existing.id if existing else ''}",
            ),
        )
    repo.upsert(ing)
    return redirect(f"/ingredients/{ing.id}/edit", "Ingredient saved")


@router.post("/ingredients", response_class=HTMLResponse)
async def create_ingredient(request: Request, repo: Repository = Depends(get_repo)) -> Response:
    state = forms.ingredient_form_state(await request.form())  # type: ignore[arg-type]
    return _save_ingredient(request, repo, state, None, True)


@router.get("/ingredients/{iid}/edit", response_class=HTMLResponse)
def edit_ingredient(request: Request, iid: str, repo: Repository = Depends(get_repo)) -> Response:
    ing = repo.get("ingredients", iid)
    if ing is None:
        raise HTTPException(404, "ingredient not found")
    used = [r.name for r in repo.recipes_using_ingredient(iid)]
    return render(
        request,
        "pages/ingredient_form.html",
        **_ing_ctx(
            forms.ingredient_to_form(ing),
            is_new=False,
            action=f"/ingredients/{iid}",
            errors=[],
            used_in=used,
        ),
    )


@router.post("/ingredients/{iid}", response_class=HTMLResponse)
async def update_ingredient(
    request: Request, iid: str, repo: Repository = Depends(get_repo)
) -> Response:
    existing = repo.get("ingredients", iid)
    if existing is None:
        raise HTTPException(404, "ingredient not found")
    state = forms.ingredient_form_state(await request.form())  # type: ignore[arg-type]
    return _save_ingredient(request, repo, state, existing, False)


@router.post("/ingredients/{iid}/delete")
def delete_ingredient(iid: str, repo: Repository = Depends(get_repo)) -> Response:
    used = repo.recipes_using_ingredient(iid)
    if used:
        return redirect("/ingredients", f"Cannot delete: used by recipe {used[0].name!r}")
    repo.delete("ingredients", iid)
    return redirect("/ingredients", "Ingredient deleted")


# ----------------------------------------------------------------------------- kitchens


@router.get("/kitchens", response_class=HTMLResponse)
def list_kitchens(request: Request, repo: Repository = Depends(get_repo)) -> Response:
    return render(request, "pages/kitchens.html", kitchens=repo.kitchens())


def _kit_ctx(state: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"f": state, **extra}


@router.get("/kitchens/new", response_class=HTMLResponse)
def new_kitchen(request: Request) -> Response:
    return render(
        request,
        "pages/kitchen_form.html",
        **_kit_ctx(forms.kitchen_to_form(None), is_new=True, action="/kitchens", errors=[]),
    )


@router.get("/kitchens/_row/equipment", response_class=HTMLResponse)
def equipment_row(request: Request, i: str = "0") -> Response:
    env = request.app.state.env
    tmpl = env.from_string('{% import "pages/_rows.html" as r %}{{ r.equip_row(row) }}')
    return HTMLResponse(
        tmpl.render(row={"idx": i, "type": "", "count": "1", "capacity": "", "label": ""})
    )


def _save_kitchen(
    request: Request,
    repo: Repository,
    state: dict[str, Any],
    existing: KitchenProfile | None,
    is_new: bool,
) -> Response:
    errors: list[str] = []
    kitchen = None
    try:
        data = forms.kitchen_data_from_state(state, existing)
        if existing is not None:
            data["id"] = existing.id
        kitchen = KitchenProfile.model_validate(data)
        if is_new and repo.exists("kitchens", kitchen.id):
            errors.append(f"A kitchen with id {kitchen.id!r} already exists")
    except forms.FormError as exc:
        errors.extend(exc.messages)
    except ValidationError as exc:
        errors.extend(forms.format_validation_error(exc))
    if errors or kitchen is None:
        return render(
            request,
            "pages/kitchen_form.html",
            status_code=422,
            **_kit_ctx(
                state,
                is_new=is_new,
                errors=errors,
                action="/kitchens" if is_new else f"/kitchens/{existing.id if existing else ''}",
            ),
        )
    repo.upsert(kitchen)
    return redirect(f"/kitchens/{kitchen.id}/edit", "Kitchen saved")


@router.post("/kitchens", response_class=HTMLResponse)
async def create_kitchen(request: Request, repo: Repository = Depends(get_repo)) -> Response:
    state = forms.kitchen_form_state(await request.form())  # type: ignore[arg-type]
    return _save_kitchen(request, repo, state, None, True)


@router.get("/kitchens/{kid}/edit", response_class=HTMLResponse)
def edit_kitchen(request: Request, kid: str, repo: Repository = Depends(get_repo)) -> Response:
    k = repo.get("kitchens", kid)
    if k is None:
        raise HTTPException(404, "kitchen not found")
    return render(
        request,
        "pages/kitchen_form.html",
        **_kit_ctx(forms.kitchen_to_form(k), is_new=False, action=f"/kitchens/{kid}", errors=[]),
    )


@router.post("/kitchens/{kid}", response_class=HTMLResponse)
async def update_kitchen(
    request: Request, kid: str, repo: Repository = Depends(get_repo)
) -> Response:
    existing = repo.get("kitchens", kid)
    if existing is None:
        raise HTTPException(404, "kitchen not found")
    state = forms.kitchen_form_state(await request.form())  # type: ignore[arg-type]
    return _save_kitchen(request, repo, state, existing, False)


@router.post("/kitchens/{kid}/delete")
def delete_kitchen(kid: str, repo: Repository = Depends(get_repo)) -> Response:
    used = repo.events_using_kitchen(kid)
    if used:
        return redirect("/kitchens", f"Cannot delete: used by event {used[0].name!r}")
    repo.delete("kitchens", kid)
    return redirect("/kitchens", "Kitchen deleted")
