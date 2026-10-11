"""Shopping list: merge across meals, subtract pantry, round up to purchasable packs.

Pack rounding (documented in docs/ADDING_A_GENERATOR.md and DECISIONS D41): for each
ingredient we try every combination of its pack sizes that covers the need (the count
of the smallest pack is derived, the others are enumerated up to the need) and keep
the combination with the lowest score ``leftover / need + packs / 20``. Ties go to
fewer packs, then to the larger packs. At most four pack sizes are considered, a
smaller pack is never used in a quantity that already covers the next larger one, and
for big counts only those near the exact fit are tried.
"""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from planner.core import units as u
from planner.core.models import Ingredient, PackSize
from planner.core.plan import Plan
from planner.generators import base

SECTION_ORDER = [
    "produce", "meat", "dairy", "bakery", "dry goods", "canned", "frozen",
    "spices", "condiments", "other",
]  # fmt: skip
MAX_PACK_SIZES = 4
PACK_PENALTY = Fraction(1, 20)
_SMALL = 12  # try every count up to this; above it only counts near the exact fit


@dataclass(frozen=True)
class PackChoice:
    counts: tuple[tuple[str, int, Fraction], ...]  # (label, count, size in base units)
    total: Fraction
    leftover: Fraction

    @property
    def n_packs(self) -> int:
        return sum(c for _, c, _ in self.counts)


def _candidate_counts(remaining: Fraction, size: Fraction, top: int) -> list[int]:
    """Counts worth trying: all small ones, plus those near the exact fit when ``top`` is big."""
    if top <= _SMALL:
        return list(range(top + 1))
    lo = max(0, math.floor(remaining / size) - 2)
    return sorted(set(range(_SMALL + 1)) | set(range(lo, top + 1)))


def choose_packs(need: Fraction, packs: Sequence[tuple[str, Fraction]]) -> PackChoice | None:
    """Pick pack counts covering ``need`` with the least waste and fewest packs."""
    if need <= 0 or not packs:
        return None
    sizes = sorted(packs, key=lambda p: (-p[1], p[0]))[:MAX_PACK_SIZES]
    best: tuple[tuple[Fraction, int, tuple[int, ...]], tuple[int, ...]] | None = None

    def consider(counts: tuple[int, ...]) -> None:
        nonlocal best
        total = sum((c * s[1] for c, s in zip(counts, sizes, strict=True)), Fraction(0))
        if total < need:
            return
        n = sum(counts)
        score = (total - need) / need + PACK_PENALTY * n
        key = (score, n, tuple(-c for c in counts))
        if best is None or key < best[0]:
            best = (key, counts)

    def rec(idx: int, remaining: Fraction, acc: tuple[int, ...]) -> None:
        size = sizes[idx][1]
        if idx == len(sizes) - 1:
            consider((*acc, max(0, math.ceil(remaining / size))))
            return
        remaining = max(remaining, Fraction(0))
        top = math.ceil(remaining / size)
        if idx > 0:  # a count that already covers the next larger pack is never better than it
            top = min(top, math.ceil(sizes[idx - 1][1] / size))
        for c in _candidate_counts(remaining, size, top):
            rec(idx + 1, remaining - c * size, (*acc, c))

    rec(0, need, ())
    if best is None:  # pragma: no cover - last size always covers
        return None
    counts = best[1]
    chosen = tuple((s[0], c, s[1]) for c, s in zip(counts, sizes, strict=True) if c > 0)
    total = sum((c * size for _, c, size in chosen), Fraction(0))
    return PackChoice(chosen, total, total - need)


@dataclass(frozen=True)
class ShoppingLine:
    ingredient_id: str
    name: str
    section: str
    family: str
    needed_base: Fraction  # needed in recipes (after merging, before trim)
    purchase_base: Fraction  # after trim yield, minus pantry
    pantry_base: Fraction
    packs: PackChoice | None
    needed: str
    to_buy: str
    pantry: str
    pack_text: str
    leftover: str
    used_in: str
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ShoppingSection:
    name: str
    lines: tuple[ShoppingLine, ...]


@dataclass
class ShoppingData:
    sections: list[ShoppingSection] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def lines(self) -> list[ShoppingLine]:
        return [ln for s in self.sections for ln in s.lines]


@dataclass
class _Entry:
    amount: Fraction
    unit: str
    used_in: str


def _section_key(name: str) -> tuple[int, str]:
    low = name.lower()
    return (SECTION_ORDER.index(low), low) if low in SECTION_ORDER else (len(SECTION_ORDER), low)


def _pick_family(ing: Ingredient | None, entries: list[_Entry]) -> str:
    if ing is not None and ing.purchase_packs:
        return u.family_of(ing.purchase_packs[0].unit)
    if (
        ing is not None
        and ing.density_g_per_ml is not None
        and any(u.family_of(e.unit) in (u.MASS, u.VOLUME) for e in entries)
    ):
        return u.MASS
    return u.family_of(entries[0].unit)


def _density(ing: Ingredient | None) -> Fraction | None:
    return ing.density_g_per_ml if ing is not None else None


def _to_family(amount: Fraction, unit: str, family: str, ing: Ingredient | None) -> Fraction:
    return u.convert_to_family(amount, unit, family, _density(ing))


def _pack_sizes(ing: Ingredient, family: str, warnings: list[str]) -> list[tuple[str, Fraction]]:
    out: list[tuple[str, Fraction]] = []
    for p in ing.purchase_packs:
        try:
            out.append((_pack_label(p), _to_family(p.size, p.unit, family, ing)))
        except u.UnitError as exc:
            warnings.append(f"{ing.name}: pack {p.label!r} ignored ({exc})")
    return out


def _pack_label(p: PackSize) -> str:
    return p.label


def build_shopping(plan: Plan) -> ShoppingData:
    system = plan.settings.units
    data = ShoppingData()
    entries: dict[str, list[_Entry]] = {}
    for pr in plan.planned_recipes():
        who = pr.recipe.name
        for ln in pr.lines:
            if ln.needed > 0:
                entries.setdefault(ln.ingredient_id, []).append(_Entry(ln.needed, ln.unit, who))

    pantry: dict[str, list[tuple[Fraction, str]]] = {}
    for p in plan.event.pantry_on_hand:
        pantry.setdefault(p.ingredient_id, []).append((p.quantity, p.unit))

    lines: list[ShoppingLine] = []
    for iid in sorted(entries):
        ing = plan.ingredients.get(iid)
        name = ing.name if ing is not None else iid
        if ing is None:
            data.warnings.append(f"{iid}: not in the ingredient catalog (no packs or sections)")
        elist = entries[iid]
        family = _pick_family(ing, elist)
        groups: dict[str, list[tuple[Fraction, _Entry]]] = {}
        for e in elist:
            try:
                groups.setdefault(family, []).append((_to_family(e.amount, e.unit, family, ing), e))
            except u.UnitError as exc:
                own = u.family_of(e.unit)
                groups.setdefault(own, []).append((e.amount * u.get_unit(e.unit).factor, e))
                data.warnings.append(
                    f"{name}: {u.format_quantity(e.amount, e.unit)} ({e.used_in}) cannot be merged "
                    f"with the other amounts: {exc}"
                )
        for fam in [family] + sorted(g for g in groups if g != family):
            if fam not in groups:
                continue
            members = groups[fam]
            needed = sum((b for b, _ in members), Fraction(0))
            trim = ing.trim_yield if ing is not None else None
            purchase = needed / trim if trim else needed
            pantry_base = Fraction(0)
            if fam == family:
                for amt, unit in pantry.get(iid, []):
                    try:
                        pantry_base += _to_family(amt, unit, fam, ing)
                    except u.UnitError as exc:
                        data.warnings.append(f"{name}: pantry amount ignored ({exc})")
            net = max(Fraction(0), purchase - pantry_base)
            notes: list[str] = []
            if trim:
                notes.append(f"{trim * 100:.0f}% usable after trimming")
            if fam != family:
                notes.append("different unit type; could not merge")
            choice = None
            if ing is not None and ing.purchase_packs and fam == family and net > 0:
                sizes = _pack_sizes(ing, fam, data.warnings)
                choice = choose_packs(net, sizes)
            elif net > 0 and not (ing and ing.purchase_packs):
                notes.append("no pack sizes in catalog")
            used = ", ".join(sorted({e.used_in for _, e in members}))
            lines.append(
                ShoppingLine(
                    ingredient_id=iid,
                    name=name,
                    section=(ing.store_section if ing else "other") or "other",
                    family=fam,
                    needed_base=needed,
                    purchase_base=net,
                    pantry_base=pantry_base,
                    packs=choice,
                    needed=u.format_base(needed, fam, system),
                    to_buy=_to_buy_text(net, fam, choice, system),
                    pantry=u.format_base(pantry_base, fam, system) if pantry_base > 0 else "",
                    pack_text=_pack_text(choice, fam, system),
                    leftover=u.format_base(choice.leftover, fam, system)
                    if choice and choice.leftover > 0
                    else "",
                    used_in=used,
                    notes=tuple(notes),
                )
            )

    by_section: dict[str, list[ShoppingLine]] = {}
    for line in lines:
        by_section.setdefault(line.section, []).append(line)
    for sec in sorted(by_section, key=_section_key):
        data.sections.append(
            ShoppingSection(sec, tuple(sorted(by_section[sec], key=lambda x: (x.name, x.family))))
        )
    for pm in plan.meals:
        for diet, n in sorted(pm.unserved.items()):
            data.notes.append(
                f"{pm.title}: {n} x {diet} have no suitable dish; add a variant recipe or "
                "substitute for them."
            )
    data.warnings = sorted(set(data.warnings))
    return data


def _to_buy_text(net: Fraction, family: str, choice: PackChoice | None, system: str) -> str:
    if net <= 0:
        return "none (covered by pantry)"
    if choice is not None:
        return u.format_base(choice.total - choice.leftover, family, system)
    # No pack data: round up to a friendly step so the number is usable at the store
    amount, unit = u.humanize(net, family, system)
    step = Fraction(1) if u.is_count(family) else Fraction(1, 8)
    return u.format_quantity(u.ceil_to(amount, step), unit)


def _pack_text(choice: PackChoice | None, family: str, system: str) -> str:
    if choice is None:
        return ""
    parts = [
        f"{count} x {label} ({u.format_base(size, family, system)})"
        for label, count, size in choice.counts
    ]
    return " + ".join(parts)


def shopping_csv(data: ShoppingData) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(
        [
            "section",
            "ingredient",
            "needed_in_recipe",
            "to_purchase",
            "packs",
            "leftover",
            "used_in",
            "notes",
        ]
    )
    for sec in data.sections:
        for ln in sec.lines:
            w.writerow(
                [
                    sec.name,
                    ln.name,
                    ln.needed,
                    ln.to_buy,
                    ln.pack_text,
                    ln.leftover,
                    ln.used_in,
                    "; ".join(ln.notes),
                ]
            )
    return buf.getvalue()


class ShoppingGenerator:
    id = "shopping"
    title = "Shopping list"
    description = "Merged, pantry-adjusted, rounded up to purchasable packs, by store section."
    order = 10
    template_dir: Path | None = None

    def generate(self, plan: Plan, options: base.GenOptions) -> base.GeneratorResult:
        data = build_shopping(plan)
        return base.GeneratorResult(
            data, "shopping.html", csv=lambda: shopping_csv(data), csv_filename="shopping.csv"
        )


base.register(ShoppingGenerator())
