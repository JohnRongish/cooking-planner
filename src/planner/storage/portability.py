"""Plain YAML/JSON import and export. Users are never locked into the database."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from planner.core.models import (
    SCHEMA_VERSION,
    Event,
    Ingredient,
    KitchenProfile,
    Recipe,
)
from planner.storage.repo import KINDS, Repository

KIND_ORDER = ["ingredients", "recipes", "kitchens", "events"]
FILE_NAMES = {k: f"{k}.yaml" for k in KIND_ORDER}


class ImportError_(ValueError):
    """Raised with a readable list of problems; nothing is written."""


@dataclass
class Bundle:
    ingredients: list[Ingredient] = field(default_factory=list)
    recipes: list[Recipe] = field(default_factory=list)
    kitchens: list[KitchenProfile] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {k: len(getattr(self, k)) for k in KIND_ORDER}

    def merge(self, other: Bundle) -> None:
        for k in KIND_ORDER:
            getattr(self, k).extend(getattr(other, k))


def dump_yaml(data: Any) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)


def load_text(text: str) -> Any:
    return yaml.safe_load(text)  # YAML is a superset of JSON


def export_bundle(repo: Repository) -> dict[str, Any]:
    out: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "kind": "planner-bundle"}
    for k in KIND_ORDER:
        out[k] = [m.model_dump(mode="json") for m in sorted(repo.all_of(k), key=lambda m: m.id)]
    return out


def export_to_dir(repo: Repository, path: Path, fmt: str = "yaml") -> list[Path]:
    """One file per kind: ``recipes.yaml`` etc."""
    path.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for k in KIND_ORDER:
        items = [m.model_dump(mode="json") for m in sorted(repo.all_of(k), key=lambda m: m.id)]
        doc = {"schema_version": SCHEMA_VERSION, "kind": k, k: items}
        f = path / f"{k}.{fmt}"
        f.write_text(_serialize(doc, fmt), encoding="utf-8")
        written.append(f)
    return written


def _serialize(doc: Any, fmt: str) -> str:
    if fmt == "json":
        import json

        return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    return dump_yaml(doc)


def bundle_text(repo: Repository, fmt: str = "yaml") -> str:
    return _serialize(export_bundle(repo), fmt)


def _detect_single(doc: dict[str, Any]) -> str | None:
    if "meals" in doc and "kitchen_profile_id" in doc:
        return "events"
    if "base_servings" in doc:
        return "recipes"
    if "equipment_inventory" in doc:
        return "kitchens"
    if "store_section" in doc or "purchase_packs" in doc:
        return "ingredients"
    return None


def parse_document(doc: Any, source: str = "document") -> Bundle:
    """Validate a parsed YAML/JSON document into models. Collects every problem."""
    errors: list[str] = []
    bundle = Bundle()
    if not isinstance(doc, dict):
        raise ImportError_(f"{source}: expected a mapping at the top level")
    if "schema_version" in doc:
        version = doc["schema_version"]
        if not isinstance(version, int) or version < 1 or version > SCHEMA_VERSION:
            raise ImportError_(
                f"{source}: unsupported schema_version {version!r} (this version reads "
                f"up to {SCHEMA_VERSION})"
            )
        content = {k: doc[k] for k in KIND_ORDER if k in doc}
        unknown = set(doc) - set(KIND_ORDER) - {"schema_version", "kind"}
        if unknown:
            errors.append(f"{source}: unknown top-level keys {sorted(unknown)}")
    else:
        single = _detect_single(doc)
        if single is None:
            raise ImportError_(f"{source}: missing schema_version and not a recognisable item")
        content = {single: [doc]}
    for kind, items in content.items():
        model, _ = KINDS[kind]
        if items is None:
            continue
        if not isinstance(items, list):
            errors.append(f"{source}: {kind} must be a list")
            continue
        for n, item in enumerate(items):
            try:
                getattr(bundle, kind).append(model.model_validate(item))
            except ValidationError as exc:
                ident = item.get("id", f"#{n + 1}") if isinstance(item, dict) else f"#{n + 1}"
                for e in exc.errors():
                    loc = ".".join(str(x) for x in e["loc"])
                    errors.append(f"{source}: {kind[:-1]} {ident}: {loc}: {e['msg']}")
    if errors:
        raise ImportError_("\n".join(errors))
    return bundle


def load_path(path: Path) -> Bundle:
    """Load a file or a directory of YAML/JSON files into a validated bundle."""
    files: list[Path]
    if path.is_dir():
        files = sorted(p for p in path.iterdir() if p.suffix in (".yaml", ".yml", ".json"))
        if not files:
            raise ImportError_(f"{path}: no .yaml/.yml/.json files found")
    elif path.exists():
        files = [path]
    else:
        raise ImportError_(f"{path}: not found")
    bundle = Bundle()
    errors: list[str] = []
    for f in files:
        try:
            doc = load_text(f.read_text(encoding="utf-8"))
            bundle.merge(parse_document(doc, f.name))
        except yaml.YAMLError as exc:
            errors.append(f"{f.name}: invalid YAML/JSON: {exc}")
        except ImportError_ as exc:
            errors.append(str(exc))
    if errors:
        raise ImportError_("\n".join(errors))
    return bundle


def import_bundle(repo: Repository, bundle: Bundle, replace: bool = False) -> dict[str, int]:
    """Write a validated bundle in one transaction (upsert by id, or replace everything)."""
    try:
        if replace:
            repo.wipe(commit=False)
        for k in KIND_ORDER:
            for m in getattr(bundle, k):
                repo.upsert(m, commit=False)
        repo.s.commit()
    except Exception:
        repo.s.rollback()
        raise
    return bundle.counts()


def import_text(repo: Repository, text: str, replace: bool = False) -> dict[str, int]:
    try:
        doc = load_text(text)
    except yaml.YAMLError as exc:
        raise ImportError_(f"invalid YAML/JSON: {exc}") from exc
    return import_bundle(repo, parse_document(doc), replace)
