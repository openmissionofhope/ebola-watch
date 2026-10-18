"""Publication policy applied identically to every output channel.

Every public response (API, dashboard, exports, alerts, reports) is built from
:class:`PublicCell` rows that have passed through :func:`apply_suppression`.
The rules are:

1. **Resolution cap.** Public outputs never go below ``public_max_admin_level``
   (default: first-level administrative division). Finer units are used
   internally for modelling only.
2. **Small-area rule.** A sub-national cell whose population is unknown or below
   ``min_public_subnational_population`` is not published on its own: it is
   rolled up into an "other areas" cell of its parent, or into the parent itself.
3. **Small-count rule.** Sub-national values in ``1..k-1`` (k =
   ``min_public_cell_count``) are shown as ``<k`` when the area is small.
4. **Complementary suppression.** If a parent total is published and exactly one
   child is suppressed, the next-smallest child is suppressed too, so the hidden
   value cannot be recovered by subtraction.

Country-level values are always published: they are the coarsest unit and the
values are already public in official bulletins.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace

from ..config import get_settings


@dataclass(frozen=True)
class PublicCell:
    region_code: str
    region_name: str
    level: int
    parent_code: str | None
    population: int | None
    value: float | None
    suppressed: bool = False
    display: str | None = None  # e.g. "<5"
    notes: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return {
            "region_code": self.region_code,
            "region_name": self.region_name,
            "level": self.level,
            "parent_code": self.parent_code,
            "value": None if self.suppressed else self.value,
            "suppressed": self.suppressed,
            "display": self.display if self.suppressed else _fmt(self.value),
            "notes": list(self.notes),
        }


def _fmt(v: float | None) -> str | None:
    if v is None:
        return None
    return f"{v:,.0f}"


@dataclass(frozen=True)
class Policy:
    min_cell_count: int
    min_population: int
    max_admin_level: int

    @classmethod
    def from_settings(cls) -> Policy:
        s = get_settings()
        return cls(s.min_public_cell_count, s.min_public_subnational_population, s.public_max_admin_level)

    def is_small_area(self, cell: PublicCell) -> bool:
        return cell.level > 0 and (cell.population is None or cell.population < self.min_population)


def apply_suppression(cells: list[PublicCell], policy: Policy | None = None, parent_totals_published: bool = True) -> list[PublicCell]:
    policy = policy or Policy.from_settings()
    k = policy.min_cell_count

    # 1. Resolution cap + 2. small-area roll-up
    kept: list[PublicCell] = []
    rolled: dict[str, list[PublicCell]] = defaultdict(list)
    for c in cells:
        if c.level > policy.max_admin_level or (c.level > 0 and policy.is_small_area(c) and c.level > 1):
            rolled[c.parent_code or "?"].append(c)
        else:
            kept.append(c)
    for parent, group in rolled.items():
        total = sum(c.value or 0 for c in group if c.value is not None)
        kept.append(
            PublicCell(
                region_code=f"{parent}:other",
                region_name="Other areas (aggregated)",
                level=min(c.level for c in group),
                parent_code=parent,
                population=None,
                value=total,
                notes=(f"aggregate of {len(group)} finer units",),
            )
        )

    # 3. small-count rule
    out: list[PublicCell] = []
    for c in kept:
        if c.level > 0 and c.value is not None and 0 < c.value < k and (policy.is_small_area(c) or c.region_code.endswith(":other")):
            out.append(replace(c, suppressed=True, display=f"<{k}", notes=c.notes + ("small count suppressed",)))
        else:
            out.append(c)

    # 4. complementary suppression within each parent group
    if parent_totals_published:
        by_parent: dict[str | None, list[int]] = defaultdict(list)
        for i, c in enumerate(out):
            if c.level > 0:
                by_parent[c.parent_code].append(i)
        for _, idxs in by_parent.items():
            suppressed = [i for i in idxs if out[i].suppressed]
            if len(suppressed) == 1:
                candidates = sorted(
                    (i for i in idxs if not out[i].suppressed and out[i].value is not None),
                    key=lambda i: out[i].value,
                )
                if candidates:
                    j = candidates[0]
                    out[j] = replace(out[j], suppressed=True, display="suppressed", notes=out[j].notes + ("complementary suppression",))
    return out


def generalize_level(level: int, policy: Policy | None = None) -> int:
    policy = policy or Policy.from_settings()
    return min(level, policy.max_admin_level)
