"""Standalone print documents (HTML and PDF) for generator results."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment

from planner.core.plan import Plan
from planner.generators import base
from planner.generators.render import build_environment, render_fragment

STATIC_DIR = Path(__file__).parent / "static"


def print_css(page_size: str = "Letter") -> str:
    css = (STATIC_DIR / "print.css").read_text(encoding="utf-8")
    return css.replace("__PAGE__", "A4" if page_size.lower() == "a4" else "letter")


def print_document(
    plan: Plan,
    gen: base.Generator,
    result: base.GeneratorResult,
    page_size: str = "Letter",
    env: Environment | None = None,
) -> str:
    """A complete HTML page, styled for print, that works as a file on its own."""
    env = env or build_environment()
    body = render_fragment(result, plan, env)
    title = f"{plan.event.name}: {gen.title}"
    tmpl = env.from_string(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>{{ title }}</title><style>{{ css }}</style></head>"
        '<body class="doc">{{ body }}</body></html>'
    )
    return tmpl.render(title=title, css=print_css(page_size), body=_safe(body))


def _safe(html: str) -> object:
    from markupsafe import Markup

    return Markup(html)


def html_to_pdf(html: str) -> bytes:
    from weasyprint import HTML

    return HTML(string=html).write_pdf() or b""
