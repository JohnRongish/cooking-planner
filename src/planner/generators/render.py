"""Jinja environment shared by the web layer and by tests/CLI."""

from __future__ import annotations

from collections.abc import Sequence
from fractions import Fraction
from pathlib import Path

from jinja2 import BaseLoader, ChoiceLoader, Environment, FileSystemLoader, select_autoescape

from planner.core import units as u
from planner.generators import base


def _fmt_qty(amount: Fraction, unit: str) -> str:
    return u.format_quantity(amount, unit)


class _RegistryLoader(BaseLoader):
    """Finds templates in every registered generator's folder, looked up at load time so
    a generator registered after the environment was built still works."""

    def get_source(self, environment, template):  # type: ignore[no-untyped-def]
        return FileSystemLoader([str(p) for p in base.template_dirs()]).get_source(
            environment, template
        )


def build_environment(extra_dirs: Sequence[Path] = ()) -> Environment:
    env = Environment(
        loader=ChoiceLoader([FileSystemLoader([str(p) for p in extra_dirs]), _RegistryLoader()]),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["amount"] = u.format_amount
    env.filters["qty"] = _fmt_qty
    return env


def render_fragment(
    result: base.GeneratorResult, plan: object, env: Environment | None = None
) -> str:
    env = env or build_environment()
    return env.get_template(result.template).render(data=result.data, plan=plan)
