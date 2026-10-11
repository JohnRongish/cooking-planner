"""``planner`` command line: export, import, seed, migrate, plan, serve."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from sqlmodel import Session

from planner.config import AppConfig
from planner.core.models import Event, Ingredient, KitchenProfile, Recipe
from planner.core.plan import Plan, build_plan
from planner.generators import base
from planner.generators.render import build_environment
from planner.storage import portability as pt
from planner.storage.db import make_engine, run_migrations
from planner.storage.repo import Repository

SEED_DIR = Path(__file__).parent / "seed"


def _open(cfg: AppConfig) -> tuple[Session, Repository]:
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    run_migrations(cfg.db_url)
    engine = make_engine(cfg.db_url)
    session = Session(engine)
    return session, Repository(session)


def seed_database(repo: Repository, replace: bool = False) -> dict[str, int]:
    """Load the bundled demo recipes, kitchens and events."""
    return pt.import_bundle(repo, pt.load_path(SEED_DIR), replace=replace)


def plan_from_bundle(
    bundle: pt.Bundle, event_id: str | None = None, kitchen_id: str | None = None
) -> Plan:
    if not bundle.events:
        raise SystemExit("no event found")
    ev: Event | None = None
    if event_id is None:
        ev = bundle.events[0]
    else:
        ev = next((e for e in bundle.events if e.id == event_id), None)
        if ev is None:
            raise SystemExit(f"event {event_id!r} not found")
    kitchens = {k.id: k for k in bundle.kitchens}
    kid = kitchen_id or ev.kitchen_profile_id
    if kid not in kitchens:
        raise SystemExit(f"kitchen profile {kid!r} not found")
    ings: dict[str, Ingredient] = {i.id: i for i in bundle.ingredients}
    recs: dict[str, Recipe] = {r.id: r for r in bundle.recipes}
    kitchen: KitchenProfile = kitchens[kid]
    return build_plan(ev, recipes=recs, ingredients=ings, kitchen=kitchen)


def cmd_plan(args: argparse.Namespace, cfg: AppConfig) -> int:
    from planner.web.printing import html_to_pdf, print_document

    bundle = pt.Bundle()
    for src in args.data or []:
        bundle.merge(pt.load_path(Path(src)))
    event_bundle = pt.load_path(Path(args.event))
    if args.data:
        # the event file only supplies events; catalog data comes from --data
        bundle.events.extend(event_bundle.events)
    elif event_bundle.recipes or event_bundle.kitchens:
        bundle = event_bundle
    else:
        session, repo = _open(cfg)
        with session:
            ings, recs, kits = repo.catalog()
        bundle.ingredients, bundle.recipes = list(ings.values()), list(recs.values())
        bundle.kitchens = list(kits.values())
        bundle.events = event_bundle.events
    plan = plan_from_bundle(bundle, args.event_id, args.kitchen)
    base.discover()
    out = Path(args.out) if args.out else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    env = build_environment()
    for gen in base.all_generators():
        result = gen.generate(plan, base.GenOptions(page_size=cfg.page_size))
        html = print_document(plan, gen, result, cfg.page_size, env)
        if out:
            (out / f"{gen.id}.html").write_text(html, encoding="utf-8")
            if args.pdf:
                (out / f"{gen.id}.pdf").write_bytes(html_to_pdf(html))
            if result.csv:
                (out / result.csv_filename).write_text(result.csv(), encoding="utf-8")
    print(
        f"Plan for {plan.event.name!r}: {len(plan.meals)} meals, "
        f"{len(plan.schedule.steps)} scheduled steps"
    )
    for w in plan.all_warnings:
        print(f"  [{w.level}] {w.message}")
    if out:
        print(f"Wrote outputs to {out}/")
    return 1 if plan.conflicts and args.strict else 0


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="planner", description="Event Kitchen Planner")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("export", help="write recipes, ingredients, kitchens, events to a folder")
    p.add_argument("dir")
    p.add_argument("--format", choices=["yaml", "json"], default="yaml")

    p = sub.add_parser("import", help="load YAML/JSON files (or a folder) into the database")
    p.add_argument("path")
    p.add_argument("--replace", action="store_true", help="wipe the database first")

    p = sub.add_parser("seed", help="load the bundled demo data")
    p.add_argument("--replace", action="store_true")

    sub.add_parser("migrate", help="apply database migrations")

    p = sub.add_parser("plan", help="generate all outputs for an event file")
    p.add_argument("event", help="event YAML/JSON (or a full bundle)")
    p.add_argument("--data", action="append", help="catalog files/folders to use instead of the DB")
    p.add_argument("--event-id")
    p.add_argument("--kitchen", help="override the kitchen profile id")
    p.add_argument("--out", help="folder for HTML/CSV (and PDF with --pdf)")
    p.add_argument("--pdf", action="store_true")
    p.add_argument("--strict", action="store_true", help="exit 1 if the plan has conflicts")

    p = sub.add_parser("serve", help="run the web app")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int)

    args = ap.parse_args(argv)
    cfg = AppConfig.from_env()
    try:
        if args.cmd == "plan":
            return cmd_plan(args, cfg)
        if args.cmd == "serve":
            import uvicorn

            uvicorn.run(
                "planner.web.app:create_app",
                factory=True,
                host=args.host,
                port=args.port or cfg.port,
                log_level="info",
            )
            return 0
        session, repo = _open(cfg)
        with session:
            if args.cmd == "export":
                files = pt.export_to_dir(repo, Path(args.dir), args.format)
                print("wrote " + ", ".join(str(f) for f in files))
            elif args.cmd == "import":
                counts = pt.import_bundle(repo, pt.load_path(Path(args.path)), args.replace)
                print("imported", counts)
            elif args.cmd == "seed":
                print("seeded", seed_database(repo, args.replace))
            elif args.cmd == "migrate":
                print("database is up to date")
    except pt.ImportError_ as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
