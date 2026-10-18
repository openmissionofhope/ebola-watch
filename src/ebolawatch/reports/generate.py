"""Automated situation reports.

Reports are assembled exclusively from the public read models in
:mod:`ebolawatch.views`, so they inherit the same suppression and labelling
rules as the API. They contain no clinical recommendations and never state a
number the database does not hold: missing quantities are written as
"insufficient evidence".
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import views
from ..db.models import Region, SituationReport
from ..epi.parameters import MODEL_VERSION
from ..safety.scope import DISCLAIMER

KINDS = ("daily", "weekly", "major_change", "country", "multicountry")


def _n(v) -> str:
    return f"{v:,.0f}" if isinstance(v, (int, float)) else "not reported"


def _official_line(label: str, o: dict | None) -> str:
    if not o:
        return f"- {label}: not reported"
    flag = " (machine-extracted from official text)" if o.get("extraction_method") == "text_pattern" else ""
    syn = " [SYNTHETIC]" if o.get("is_synthetic") else ""
    return f"- {label}: {_n(o['value'])} (as of {o['as_of']}; {o['source']}){flag}{syn}"


def _est_line(label: str, e: dict | None) -> str:
    if not e or e.get("insufficient"):
        return f"- {label}: {views.INSUFFICIENT}"
    return f"- {label}: {_n(e['lower_90'])}–{_n(e['upper_90'])} (median {_n(e['median'])}; 90% interval; confidence {e.get('confidence')})"


def _fc_line(fc: dict, horizon: int) -> str:
    if not fc or fc.get("insufficient"):
        return f"- {horizon}-day: Available observations are insufficient for numerical forecasting."
    base = (fc["targets"].get("new_reported_confirmed") or {}).get("baseline") or []
    row = next((r for r in base if r["horizon_days"] == horizon), None)
    if not row:
        return f"- {horizon}-day: not available"
    tag = " — SCENARIO, not a prediction" if row["is_scenario"] else ""
    sc = ""
    for name in ("improving", "deteriorating"):
        alt = next((r for r in (fc["targets"]["new_reported_confirmed"].get(name) or []) if r["horizon_days"] == horizon), None)
        if alt and row["is_scenario"]:
            sc += f"; {name}: {_n(alt['lower_90'])}–{_n(alt['upper_90'])}"
    return (f"- {horizon}-day: {_n(row['lower_90'])}–{_n(row['upper_90'])} additional reported confirmed cases "
            f"(median {_n(row['median'])}; confidence {row['confidence']}){tag}{sc}")


def region_section(session: Session, region: Region) -> tuple[str, dict]:
    s = views.region_summary(session, region, detail=True)
    sev = s["severity"]
    lines = [f"## {region.name}", ""]
    lines += [f"**OVERALL SEVERITY:** {sev['label']}" + (f" (level {sev['level']})" if sev.get("level") is not None else ""),
              f"**SURVEILLANCE CONFIDENCE:** {(sev.get('confidence') or 'n/a').upper()}"]
    if sev.get("underestimation_risk"):
        lines.append("**Note:** incomplete surveillance creates a credible risk that severity is underestimated.")
    lines += ["", f"Data currency: {s.get('data_as_of') or 'no official data'}", "", "### What is known (official reports)"]
    o = s["official"]
    lines += [_official_line("Confirmed cases", o["confirmed_cases"]), _official_line("Confirmed deaths", o["confirmed_deaths"]),
              _official_line("Probable cases", o["probable_cases"]), _official_line("Suspected cases", o["suspected_cases"])]
    if o.get("imported_cases"):
        lines.append(_official_line("Imported confirmed cases (subset)", o["imported_cases"]))
    lines += ["", "### What is estimated (model-based; not confirmed cases)"]
    lines += [_est_line("Estimated cumulative symptomatic infections", s.get("estimated_total")),
              _est_line("Estimated new symptomatic infections, last 14 days", s.get("recent_incidence")),
              _est_line("Reporting-delay nowcast of cumulative reported cases", s.get("nowcast_reported"))]
    asc = s.get("ascertainment") or {}
    lines.append(f"- Reporting completeness: {asc['median']:.0%} ({asc['lower_90']:.0%}–{asc['upper_90']:.0%})" if asc.get("identifiable")
                 else "- Reporting completeness: not identifiable from available data")
    rt = s.get("rt")
    if rt and not rt.get("insufficient"):
        lines.append(f"- R_t of reported cases: {rt['median']:.2f} (90% interval {rt['lower_90']:.2f}–{rt['upper_90']:.2f}); "
                     "changes in case ascertainment also affect this quantity")
    dis = s.get("model_disagreement")
    if dis and dis.get("substantial"):
        lines.append("- **Models disagree substantially**; the range shown spans both methods.")
    fc = s.get("forecasts")
    lines += ["", "### What may happen next (forecasts and scenarios)"] + [_fc_line(fc, h) for h in (7, 28, 84)]
    exp = s.get("expansion")
    lines += ["", "### Geographic expansion"]
    if exp and not exp.get("insufficient"):
        lines.append(f"- Newly affected {exp['unit']}: about {exp['weekly_rate_median']} per week recently; probability of at least one newly "
                     f"affected unit within 14 days: {exp['p_new_unit'].get('14', 0):.0%}.")
    else:
        lines.append("- Insufficient evidence for a quantitative expansion assessment.")
    tc = views.transport_context(session, region)
    lines += ["", "### Transport connectivity (broad, aggregated)"]
    top = [r for r in tc["introduction_ranking"] if r["tier"] in ("higher", "moderate")][:5]
    if top:
        for r in top:
            lines.append(f"- {r['name']}: {r['tier']} relative connectivity to active areas (modes: {', '.join(r['path_modes']) or 'n/a'}; "
                         f"{'robust' if r['robust'] else 'sensitive'} to assumptions about unverified services)")
    else:
        lines.append("- No connectivity ranking (no active transmission sources or no corridor data).")
    lines.append("- " + tc["caveats"][0])
    sig = views.signals_public(session, region, limit=5)
    lines += ["", "### Unverified signals (aggregated)"]
    lines += [f"- {x['summary']} (independent origins: {x['independent_origins']}; status: {x['review_status']})" for x in sig] or \
        ["- None currently assessed for this area."]
    lines += ["", "### Major uncertainties"]
    unc = list(dict.fromkeys((sev.get("confidence_reasons") or []) + (s.get("model_reasons") or [])))
    lines += [f"- {u}" for u in unc] or ["- See methodology for standing limitations."]
    lines += ["", "### Severity explanation", sev.get("explanation", "")]
    for t in sev.get("triggers", []):
        lines.append(f"- {t['text']}")
    return "\n".join(lines), s


def generate(session: Session, kind: str, scope: list[str] | None = None, today: date | None = None, publish: bool = True) -> SituationReport:
    if kind not in KINDS:
        raise ValueError(f"unknown report kind {kind}")
    today = today or date.today()
    ov = views.overview(session)
    if scope:
        regions = [r for r in session.scalars(select(Region).where(Region.code.in_(scope)))]
    else:
        codes = [x["region"]["code"] for x in ov["regions"]]
        regions = [r for r in session.scalars(select(Region).where(Region.code.in_(codes)))]
        regions.sort(key=lambda r: codes.index(r.code))
    if kind == "country" and len(regions) != 1:
        raise ValueError("country report requires exactly one region in scope")
    title = {"daily": "Daily regional summary", "weekly": "Weekly outbreak report", "major_change": "Major-change alert summary",
             "country": f"Country assessment: {regions[0].name}" if regions else "Country assessment",
             "multicountry": "Multi-country assessment"}[kind]
    as_of = max((s.get("data_as_of") or "" for s in ov["regions"]), default="") or None
    head = ["# EBOLA WATCH", f"## {title.upper()}", "", f"Reporting date: {today.isoformat()}",
            f"Data currency: latest official data {as_of or 'not available'}", f"Model version: {MODEL_VERSION}", ""]
    if ov["contains_synthetic_data"]:
        head += ["> **SYNTHETIC DATA PRESENT — this report includes synthetic test data and does not describe a real outbreak.**", ""]
    body, content = [], {"regions": []}
    if kind == "major_change":
        alerts = [a for a in ov["alerts"] if a.get("kind") != "retraction"][:20]
        body += ["## Published alerts"] + [f"- {a['created_at']}: {a['message']}" for a in alerts] or ["- No published alerts."]
        content["alerts"] = alerts
    for r in regions:
        text, s = region_section(session, r)
        body += [text, ""]
        content["regions"].append(s)
    tail = ["## Important new evidence (official)"]
    tail += [f"- {d['published_at']}: {d['title']} ({d['source']})" for d in ov["developments"][:8]] or ["- None"]
    tail += ["", "## Sources", "Official figures are attributed above with their publication and observation dates. "
             "Unofficial signals are paraphrased and aggregated; individual posts and accounts are never cited.", "",
             "## Disclaimer", DISCLAIMER]
    md = "\n".join(head + body + tail)
    rep = SituationReport(kind=kind, scope=[r.code for r in regions], data_as_of=date.fromisoformat(as_of) if as_of else None,
                          title=title, content_md=md, content=_jsonable(content), model_version=MODEL_VERSION,
                          status="published" if publish else "draft", is_synthetic=ov["contains_synthetic_data"])
    session.add(rep)
    session.flush()
    return rep


def _jsonable(x):
    import json

    return json.loads(json.dumps(x, default=str))
