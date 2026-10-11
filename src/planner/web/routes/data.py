"""Dashboard, import/export, seed, login."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, Response

from planner.storage import portability as pt
from planner.storage.repo import Repository
from planner.web import auth
from planner.web.common import get_cfg, get_repo, redirect, render

router = APIRouter()


@router.get("/healthz")
def healthz(request: Request) -> Response:
    from sqlalchemy import text

    with request.app.state.engine.connect() as conn:
        conn.execute(text("select 1"))
    return Response('{"status":"ok"}', media_type="application/json")


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, repo: Repository = Depends(get_repo)) -> Response:
    counts = {k: repo.count(k) for k in pt.KIND_ORDER}
    return render(request, "pages/dashboard.html", counts=counts, events=repo.events())


@router.get("/data", response_class=HTMLResponse)
def data_page(request: Request, repo: Repository = Depends(get_repo)) -> Response:
    counts = {k: repo.count(k) for k in pt.KIND_ORDER}
    return render(request, "pages/data.html", counts=counts, errors=[])


@router.get("/export.{fmt}")
def export_all(fmt: str, repo: Repository = Depends(get_repo)) -> Response:
    if fmt not in ("yaml", "json"):
        return Response(status_code=404)
    mime = "application/json" if fmt == "json" else "text/yaml"
    return Response(
        pt.bundle_text(repo, fmt),
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="planner-export.{fmt}"'},
    )


@router.post("/import", response_class=HTMLResponse)
async def import_file(
    request: Request,
    file: UploadFile,
    replace: str = Form(""),
    repo: Repository = Depends(get_repo),
) -> Response:
    raw = (await file.read()).decode("utf-8", errors="replace")
    try:
        counts = pt.import_text(repo, raw, replace=bool(replace))
    except pt.ImportError_ as exc:
        c = {k: repo.count(k) for k in pt.KIND_ORDER}
        return render(
            request, "pages/data.html", status_code=422, counts=c, errors=str(exc).splitlines()
        )
    summary = ", ".join(f"{n} {k}" for k, n in counts.items() if n)
    return redirect("/data", f"Imported {summary or 'nothing'}")


@router.post("/seed")
def seed(replace: str = Form(""), repo: Repository = Depends(get_repo)) -> Response:
    from planner.cli import seed_database

    seed_database(repo, replace=bool(replace))
    return redirect("/", "Demo data loaded")


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = "/") -> Response:
    return render(request, "pages/login.html", next=next, error="")


@router.post("/login", response_class=HTMLResponse)
def login(request: Request, password: str = Form(""), next: str = Form("/")) -> Response:
    cfg = get_cfg(request)
    if cfg.password is None or auth.password_ok(password, cfg.password):
        resp = redirect(next if next.startswith("/") and not next.startswith("//") else "/")
        if cfg.password:
            resp.set_cookie(
                auth.COOKIE,
                auth.make_token(cfg.password),
                max_age=auth.MAX_AGE,
                httponly=True,
                samesite="lax",
            )
        return resp
    return render(request, "pages/login.html", status_code=401, next=next, error="Wrong password")


@router.post("/logout")
def logout() -> Response:
    resp = redirect("/login")
    resp.delete_cookie(auth.COOKIE)
    return resp
