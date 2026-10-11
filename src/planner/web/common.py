"""Shared web plumbing: per-request DB session, template rendering, flash messages."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment
from sqlmodel import Session

from planner.config import AppConfig
from planner.generators import base
from planner.storage.repo import Repository

TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"
VERSION = "0.1.0"


def get_cfg(request: Request) -> AppConfig:
    cfg: AppConfig = request.app.state.cfg
    return cfg


def get_repo(request: Request) -> Iterator[Repository]:
    with Session(request.app.state.engine) as session:
        yield Repository(session)


def render(request: Request, template: str, status_code: int = 200, **ctx: Any) -> HTMLResponse:
    env: Environment = request.app.state.env
    cfg = get_cfg(request)
    html = env.get_template(template).render(
        request=request,
        cfg=cfg,
        generators=base.all_generators(),
        msg=request.query_params.get("msg", ""),
        path=request.url.path,
        version=VERSION,
        **ctx,
    )
    return HTMLResponse(html, status_code=status_code)


def redirect(url: str, msg: str | None = None) -> RedirectResponse:
    if msg:
        url += ("&" if "?" in url else "?") + "msg=" + quote(msg)
    return RedirectResponse(url, status_code=303)
