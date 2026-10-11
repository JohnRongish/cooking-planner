from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import ValidationError

from planner.core.models import Event
from planner.core.plan import build_plan, validate_event
from planner.core.units import known_units
from planner.storage.repo import Repository
from planner.web import forms
from planner.web.common import get_repo, redirect, render

router = APIRouter()


def _ctx(repo: Repository, state: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "f": state,
        "kitchens": repo.kitchens(),
        "recipe_choices": [(r.id, r.name) for r in repo.recipes()],
        "ingredients": sorted(repo.ingredients(), key=lambda i: i.name.lower()),
        "units": known_units(),
        **extra,
    }


@router.get("/events", response_class=HTMLResponse)
def list_events(request: Request, repo: Repository = Depends(get_repo)) -> Response:
    kitchens = {k.id: k.name for k in repo.kitchens()}
    return render(request, "pages/events.html", events=repo.events(), kitchens=kitchens)


@router.get("/events/new", response_class=HTMLResponse)
def new_event(request: Request, repo: Repository = Depends(get_repo)) -> Response:
    kitchens = repo.kitchens()
    state = forms.event_to_form(None, kitchens[0].id if kitchens else "")
    return render(
        request,
        "pages/event_form.html",
        **_ctx(repo, state, is_new=True, action="/events", errors=[]),
    )


@router.get("/events/_row/{kind}", response_class=HTMLResponse)
def event_row(
    request: Request, kind: str, i: str = "0", repo: Repository = Depends(get_repo)
) -> Response:
    env = request.app.state.env
    ctx = _ctx(repo, {})
    if kind == "meal":
        row = {
            "idx": i,
            "day": "0",
            "label": "",
            "serve_time": "18:00",
            "headcount": "",
            "portion_factor": "1",
            "splits": "",
            "recipe_ids": [],
        }
        src = "{{ r.meal_row(row, recipe_choices) }}"
    elif kind == "pantry":
        row = {"idx": i, "ingredient_id": "", "quantity": "", "unit": "lb"}
        src = "{{ r.pantry_row(row, ingredients, units) }}"
    else:
        raise HTTPException(404)
    tmpl = env.from_string('{% import "pages/_rows.html" as r %}' + src)
    return HTMLResponse(tmpl.render(row=row, **ctx))


def _build(state: dict[str, Any], existing: Event | None) -> Event:
    return Event.model_validate(forms.event_data_from_state(state, existing))


@router.post("/events/_validate", response_class=HTMLResponse)
async def validate(request: Request, repo: Repository = Depends(get_repo)) -> Response:
    """Live validation fragment for the event builder (HTMX)."""
    state = forms.event_form_state(await request.form())  # type: ignore[arg-type]
    warnings: list[Any] = []
    errors: list[str] = []
    try:
        ev = _build(state, None)
        ings, recs, kits = repo.catalog()
        kitchen = kits.get(ev.kitchen_profile_id)
        warnings = validate_event(ev, recs, ings, kitchen)
        if kitchen is not None and not any(w.level == "error" for w in warnings):
            plan = build_plan(ev, recipes=recs, ingredients=ings, kitchen=kitchen)
            seen = {w.message for w in warnings}
            warnings += [w for w in plan.all_warnings if w.message not in seen]
    except forms.FormError as exc:
        errors = exc.messages
    except ValidationError as exc:
        errors = forms.format_validation_error(exc)
    return render(request, "pages/_validation.html", warnings=warnings, errors=errors)


def _save(
    request: Request, repo: Repository, state: dict[str, Any], existing: Event | None, is_new: bool
) -> Response:
    errors: list[str] = []
    ev = None
    try:
        data = forms.event_data_from_state(state, existing)
        if existing is not None:
            data["id"] = existing.id
        ev = Event.model_validate(data)
        if is_new and repo.exists("events", ev.id):
            errors.append(f"An event with id {ev.id!r} already exists")
        if not repo.exists("kitchens", ev.kitchen_profile_id):
            errors.append(f"Kitchen profile {ev.kitchen_profile_id!r} does not exist")
    except forms.FormError as exc:
        errors.extend(exc.messages)
    except ValidationError as exc:
        errors.extend(forms.format_validation_error(exc))
    if errors or ev is None:
        return render(
            request,
            "pages/event_form.html",
            status_code=422,
            **_ctx(
                repo,
                state,
                is_new=is_new,
                errors=errors,
                action="/events" if is_new else f"/events/{existing.id if existing else ''}",
            ),
        )
    repo.upsert(ev)
    return redirect(f"/events/{ev.id}/edit", "Event saved")


@router.post("/events", response_class=HTMLResponse)
async def create_event(request: Request, repo: Repository = Depends(get_repo)) -> Response:
    state = forms.event_form_state(await request.form())  # type: ignore[arg-type]
    return _save(request, repo, state, None, True)


@router.get("/events/{eid}/edit", response_class=HTMLResponse)
def edit_event(request: Request, eid: str, repo: Repository = Depends(get_repo)) -> Response:
    ev = repo.get("events", eid)
    if ev is None:
        raise HTTPException(404, "event not found")
    return render(
        request,
        "pages/event_form.html",
        **_ctx(
            repo,
            forms.event_to_form(ev),
            is_new=False,
            action=f"/events/{eid}",
            errors=[],
            event_id=eid,
        ),
    )


@router.post("/events/{eid}", response_class=HTMLResponse)
async def update_event(
    request: Request, eid: str, repo: Repository = Depends(get_repo)
) -> Response:
    existing = repo.get("events", eid)
    if existing is None:
        raise HTTPException(404, "event not found")
    state = forms.event_form_state(await request.form())  # type: ignore[arg-type]
    return _save(request, repo, state, existing, False)


@router.post("/events/{eid}/duplicate")
def duplicate_event(eid: str, repo: Repository = Depends(get_repo)) -> Response:
    ev = repo.get("events", eid)
    if ev is None:
        raise HTTPException(404, "event not found")
    n, new_id = 1, f"{eid}-copy"
    while repo.exists("events", new_id):
        n += 1
        new_id = f"{eid}-copy-{n}"
    repo.upsert(ev.model_copy(update={"id": new_id, "name": f"{ev.name} (copy)"}))
    return redirect(f"/events/{new_id}/edit", "Event duplicated")


@router.post("/events/{eid}/delete")
def delete_event(eid: str, repo: Repository = Depends(get_repo)) -> Response:
    repo.delete("events", eid)
    return redirect("/events", "Event deleted")
