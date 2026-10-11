"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from planner.config import AppConfig
from planner.generators import base
from planner.generators.render import build_environment
from planner.storage.db import make_engine, run_migrations
from planner.web import auth
from planner.web.common import STATIC_DIR, TEMPLATE_DIR, VERSION
from planner.web.routes import catalog, data, events, plan, recipes


def prepare_data_dir(cfg: AppConfig) -> None:
    """Create the data folders, failing with a readable hint if they are not writable."""
    try:
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        cfg.export_dir.mkdir(parents=True, exist_ok=True)
        probe = cfg.data_dir / ".write-test"
        probe.write_text("ok")
        probe.unlink()
    except OSError as exc:
        raise SystemExit(
            f"Cannot write to the data folder {cfg.data_dir}: {exc}. "
            "Give the user the app runs as (uid 568 in the Docker image) write access to it; "
            "on TrueNAS SCALE check the dataset's ACL."
        ) from exc


def create_app(config: AppConfig | None = None) -> FastAPI:
    cfg = config or AppConfig.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        app.state.engine.dispose()

    app = FastAPI(
        title="Event Kitchen Planner",
        version=VERSION,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    app.state.cfg = cfg
    base.discover()
    app.state.env = build_environment([TEMPLATE_DIR])
    prepare_data_dir(cfg)
    run_migrations(cfg.db_url)  # at startup, so a fresh empty /data is migrated before serving
    app.state.engine = make_engine(cfg.db_url)
    if cfg.password:
        auth.install(app, cfg.password)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    for r in (data.router, plan.router, recipes.router, catalog.router, events.router):
        app.include_router(r)
    return app
