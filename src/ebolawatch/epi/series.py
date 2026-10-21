"""Construction of analysis-ready series from vintaged official observations.

* For every observation date the most recent *publishable* vintage wins
  (verified or auto-validated; pending, disputed and retracted rows are excluded).
* Downward revisions of cumulative totals are kept and flagged, never smoothed
  away silently.
* Irregular cumulative reports are converted to weekly incidence by
  distributing each reporting interval's increment uniformly over its days. The
  number of interpolated days is reported so models can widen uncertainty.
* A missing report is *not* a zero: weeks after the last observation are
  absent, not zero-filled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np


@dataclass(frozen=True)
class Point:
    as_of: date
    value: float
    source_key: str
    published_at: object | None = None
    observation_id: int | None = None
    validation_status: str = "auto_validated"


@dataclass
class CumulativeSeries:
    points: list[Point]  # sorted, one per date
    revisions: list[dict] = field(default_factory=list)
    discrepancies: list[dict] = field(default_factory=list)

    @property
    def last_date(self) -> date | None:
        return self.points[-1].as_of if self.points else None

    @property
    def last_value(self) -> float | None:
        return self.points[-1].value if self.points else None

    def value_at(self, d: date) -> float | None:
        """Linear interpolation between observed points; None outside the observed range."""
        if not self.points or d < self.points[0].as_of or d > self.points[-1].as_of:
            return None
        for a, b in zip(self.points, self.points[1:], strict=False):
            if a.as_of <= d <= b.as_of:
                span = (b.as_of - a.as_of).days
                if span == 0:
                    return b.value
                return a.value + (b.value - a.value) * (d - a.as_of).days / span
        return self.points[-1].value

    def truncated(self, until: date) -> CumulativeSeries:
        return CumulativeSeries([p for p in self.points if p.as_of <= until], self.revisions, self.discrepancies)


# When several sources give a value for the same date, the first listed is used.
SOURCE_PRIORITY = ["manual", "official_statements", "hdx_cod_ebola", "who_don", "ecdc"]


def source_rank(source_key: str, source_priority: list[str] | None = None) -> int:
    order = source_priority or SOURCE_PRIORITY
    return order.index(source_key) if source_key in order else len(order)


def build_cumulative(rows: list[dict], source_priority: list[str] | None = None) -> CumulativeSeries:
    """rows: dicts with as_of, value, source_key, published_at, id, validation_status, supersedes_id.

    Later vintages of the same (source, as_of) replace earlier ones; when several
    sources report the same date, the highest-priority source is used and the
    disagreement is recorded.
    """
    by_src_date: dict[tuple[str, date], dict] = {}
    for r in rows:
        if r.get("validation_status") not in ("auto_validated", "verified"):
            continue
        k = (r["source_key"], r["as_of"])
        prev = by_src_date.get(k)
        if prev is None or _newer(r, prev):
            by_src_date[k] = r
    by_date: dict[date, list[dict]] = {}
    for (_, d), r in by_src_date.items():
        by_date.setdefault(d, []).append(r)

    points: list[Point] = []
    discrepancies = []
    for d in sorted(by_date):
        cands = sorted(by_date[d], key=lambda r: (0 if r.get("validation_status") == "verified" else 1, source_rank(r["source_key"], source_priority)))
        best = cands[0]
        others = [c for c in cands[1:] if abs(c["value"] - best["value"]) > max(2, 0.03 * best["value"])]
        if others:
            discrepancies.append({"as_of": d.isoformat(), "used": {best["source_key"]: best["value"]},
                                  "other": {o["source_key"]: o["value"] for o in others}})
        points.append(Point(d, float(best["value"]), best["source_key"], best.get("published_at"), best.get("id"), best.get("validation_status")))

    revisions = []
    for a, b in zip(points, points[1:], strict=False):
        if b.value < a.value:
            revisions.append({"from": a.as_of.isoformat(), "to": b.as_of.isoformat(), "change": b.value - a.value,
                              "note": "cumulative total decreased (reclassification or correction by the reporting authority)"})
    return CumulativeSeries(points, revisions, discrepancies)


def _newer(a: dict, b: dict) -> bool:
    pa, pb = a.get("published_at"), b.get("published_at")
    if pa and pb and pa != pb:
        return pa > pb
    return (a.get("id") or 0) > (b.get("id") or 0)


@dataclass
class WeeklyIncidence:
    week_ends: list[date]
    counts: np.ndarray  # float, may be fractional due to interval apportioning
    interpolated_days: np.ndarray  # per week: days not directly bounded by reports within 3 days
    max_gap_days: int

    def __len__(self) -> int:
        return len(self.week_ends)


def weekly_incidence(series: CumulativeSeries, end: date | None = None) -> WeeklyIncidence:
    """Weekly incidence ending on ``end`` (default: last observation date).

    Downward revisions are absorbed by clipping daily increments at zero within the
    interval where they occur (the revision itself is reported separately).
    """
    pts = series.points
    if len(pts) < 2:
        return WeeklyIncidence([], np.zeros(0), np.zeros(0), 0)
    end = end or pts[-1].as_of
    start = pts[0].as_of
    n_days = (end - start).days
    daily = np.zeros(n_days)
    interp = np.zeros(n_days)
    max_gap = 0
    for a, b in zip(pts, pts[1:], strict=False):
        if a.as_of >= end:
            break
        span = (min(b.as_of, end) - a.as_of).days
        full_span = (b.as_of - a.as_of).days
        if full_span <= 0:
            continue
        max_gap = max(max_gap, full_span)
        inc = max(b.value - a.value, 0.0) / full_span
        i0 = (a.as_of - start).days
        daily[i0:i0 + span] = inc
        if full_span > 3:
            interp[i0:i0 + span] = 1
    n_weeks = n_days // 7
    if n_weeks == 0:
        return WeeklyIncidence([], np.zeros(0), np.zeros(0), max_gap)
    offset = n_days - n_weeks * 7
    d = daily[offset:].reshape(n_weeks, 7)
    it = interp[offset:].reshape(n_weeks, 7)
    week_ends = [start + timedelta(days=offset + 7 * (i + 1)) for i in range(n_weeks)]
    return WeeklyIncidence(week_ends, d.sum(axis=1), it.sum(axis=1), max_gap)
