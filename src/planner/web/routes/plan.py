"""Generate-plan pages: one tab per registered generator, print view, PDF, CSV."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from planner.core.plan import Plan, build_plan
from planner.generators import base
from planner.generators.render import render_fragment
from planner.storage.repo import Repository
from planner.web.common import get_cfg, get_repo, render
from planner.web.printing import html_to_pdf, print_css, print_document

router = APIRouter()


def load_plan(repo: Repository, event_id: str) -> Plan:
    ev = repo.get("events", event_id)
    if ev is None:
        raise HTTPException(404, "event not found")
    ings, recs, kits = repo.catalog()
    kitchen = kits.get(ev.kitchen_profile_id)
    if kitchen is None:
        raise HTTPException(409, f"kitchen profile {ev.kitchen_profile_id!r} no longer exists")
    return build_plan(ev, recipes=recs, ingredients=ings, kitchen=kitchen)


def _gen(gen_id: str) -> base.Generator:
    gen = base.get(gen_id)
    if gen is None:
        raise HTTPException(404, f"no generator {gen_id!r}")
    return gen


def _page(request: Request, page: str) -> str:
    chosen = page or get_cfg(request).page_size
    return "A4" if chosen.lower() == "a4" else "Letter"


@router.get("/print.css")
def css(request: Request, page: str = "") -> Response:
    return Response(print_css(_page(request, page)), media_type="text/css")


@router.get("/events/{eid}/plan")
def plan_index(eid: str, page: str = "") -> Response:
    first = base.all_generators()
    if not first:
        raise HTTPException(404, "no generators registered")
    return RedirectResponse(
        f"/events/{eid}/plan/{first[0].id}" + (f"?page={page}" if page else ""), status_code=303
    )


@router.get("/events/{eid}/plan/{gen_id}", response_class=HTMLResponse)
def plan_tab(
    request: Request, eid: str, gen_id: str, page: str = "", repo: Repository = Depends(get_repo)
) -> Response:
    gen = _gen(gen_id)
    plan = load_plan(repo, eid)
    size = _page(request, page)
    result = gen.generate(plan, base.GenOptions(page_size=size))
    fragment = render_fragment(result, plan, request.app.state.env)
    return render(
        request,
        "pages/plan.html",
        event=plan.event,
        gen=gen,
        fragment=fragment,
        has_csv=result.csv is not None,
        page=size,
        eid=eid,
        warnings=plan.all_warnings,
        conflicts=plan.conflicts,
    )


@router.get("/events/{eid}/plan/{gen_id}/print", response_class=HTMLResponse)
def plan_print(
    request: Request, eid: str, gen_id: str, page: str = "", repo: Repository = Depends(get_repo)
) -> Response:
    gen = _gen(gen_id)
    plan = load_plan(repo, eid)
    size = _page(request, page)
    result = gen.generate(plan, base.GenOptions(page_size=size))
    return HTMLResponse(print_document(plan, gen, result, size, request.app.state.env))


@router.get("/events/{eid}/plan/{gen_id}/pdf")
def plan_pdf(
    request: Request, eid: str, gen_id: str, page: str = "", repo: Repository = Depends(get_repo)
) -> Response:
    gen = _gen(gen_id)
    plan = load_plan(repo, eid)
    size = _page(request, page)
    result = gen.generate(plan, base.GenOptions(page_size=size))
    pdf = html_to_pdf(print_document(plan, gen, result, size, request.app.state.env))
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{eid}-{gen_id}.pdf"'},
    )


@router.get("/events/{eid}/plan/{gen_id}/csv")
def plan_csv(
    request: Request, eid: str, gen_id: str, repo: Repository = Depends(get_repo)
) -> Response:
    gen = _gen(gen_id)
    plan = load_plan(repo, eid)
    result = gen.generate(plan, base.GenOptions())
    if result.csv is None:
        raise HTTPException(404, "this output has no CSV")
    return Response(
        result.csv(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{eid}-{result.csv_filename}"'},
    )
