"""Generator protocol and registry.

A generator turns a ``Plan`` into a ``GeneratorResult``: a data structure plus the
name of a Jinja template that renders it (and optionally a CSV). Registering is one
line at the bottom of the generator module; the web UI lists whatever is registered.
See docs/ADDING_A_GENERATOR.md.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from planner.core.plan import Plan

DEFAULT_TEMPLATE_DIR = Path(__file__).parent / "templates"


@dataclass
class GenOptions:
    page_size: str = "Letter"
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class GeneratorResult:
    data: Any  # whatever the template needs; dataclasses and plain dicts both work
    template: str  # template file name, found in DEFAULT_TEMPLATE_DIR or the generator's dir
    csv: Callable[[], str] | None = None
    csv_filename: str = "export.csv"


@runtime_checkable
class Generator(Protocol):
    id: str  # url slug, unique
    title: str  # tab title
    description: str
    order: int  # tab order, lower first
    template_dir: Path | None  # extra template folder, or None to use the default one

    def generate(self, plan: Plan, options: GenOptions) -> GeneratorResult: ...


class DuplicateGenerator(ValueError):
    pass


_REGISTRY: dict[str, Generator] = {}


def register(gen: Generator) -> Generator:
    existing = _REGISTRY.get(gen.id)
    if existing is not None and existing is not gen:
        raise DuplicateGenerator(f"generator id {gen.id!r} is already registered")
    _REGISTRY[gen.id] = gen
    return gen


def unregister(gen_id: str) -> None:
    _REGISTRY.pop(gen_id, None)


def get(gen_id: str) -> Generator | None:
    return _REGISTRY.get(gen_id)


def all_generators() -> list[Generator]:
    return sorted(_REGISTRY.values(), key=lambda g: (g.order, g.id))


def template_dirs() -> list[Path]:
    dirs = [DEFAULT_TEMPLATE_DIR]
    for g in all_generators():
        if g.template_dir is not None and g.template_dir not in dirs:
            dirs.append(g.template_dir)
    return dirs


def discover() -> list[str]:
    """Import every public module in ``planner.generators`` so it can register itself.

    Modules and packages whose name starts with ``_`` (such as ``_stubs``) are skipped.
    """
    import planner.generators as pkg

    loaded: list[str] = []
    for mod in pkgutil.iter_modules(pkg.__path__):
        if mod.name.startswith("_") or mod.name == "base":
            continue
        importlib.import_module(f"{pkg.__name__}.{mod.name}")
        loaded.append(mod.name)
    return sorted(loaded)
