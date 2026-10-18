"""Constrained question answering over published data.

No language model is involved: questions are scope-checked, mapped to a region
and a quantity, and answered from the same public read models as the
dashboard. Out-of-scope and harmful requests are refused by
:mod:`ebolawatch.safety.scope` before any data access.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import views
from ..db.models import Region
from ..nlp.gazetteer import load_gazetteer
from ..safety.scope import DISCLAIMER, classify_request

QUANTITIES = [
    ("forecast", re.compile(r"\b(forecast|predict|projection|next (week|month)|coming weeks|prévision|utabiri)\b", re.I)),
    ("estimate", re.compile(r"\b(estimat\w*|actual|true|real|unreported|hidden|really|réel|halisi)\b", re.I)),
    ("severity", re.compile(r"\b(severity|risk level|warning|alert level|how bad|gravité)\b", re.I)),
    ("rt", re.compile(r"\b(rt|r_t|reproduction|growing|declining|trend)\b", re.I)),
    ("surveillance", re.compile(r"\b(surveillance|reporting|completeness|data quality|blind spot)\b", re.I)),
    ("deaths", re.compile(r"\b(deaths?|died|dead|décès|vifo)\b", re.I)),
    ("cases", re.compile(r"\b(cases?|infections?|cas|wagonjwa|visa)\b", re.I)),
]


def answer(session: Session, question: str) -> dict:
    decision = classify_request(question)
    if not decision.allowed:
        return {"answered": False, "intent": decision.intent.value, "message": decision.message, "disclaimer": DISCLAIMER}
    g = load_gazetteer()
    places = g.find(question)
    region = None
    if places:
        best = sorted(places, key=lambda m: (-m.level, m.start))[0]
        code = best.code if best.level <= 1 else (g.admin1_of(best.code) or g.country_of(best.code))
        region = session.scalar(select(Region).where(Region.code == code))
    if region is None:
        ov = views.overview(session)
        top = [f"{r['region']['name']}: {r['severity']['label']}" for r in ov["regions"][:6]]
        return {"answered": True, "intent": "overview", "message": "Current assessments: " + "; ".join(top) if top else
                "No assessed areas yet.", "disclaimer": DISCLAIMER}
    kind = next((k for k, rx in QUANTITIES if rx.search(question)), "cases")
    s = views.region_summary(session, region, detail=(kind == "forecast"))
    name = region.name
    if kind in ("cases", "deaths"):
        key = "confirmed_cases" if kind == "cases" else "confirmed_deaths"
        o = s["official"].get(key)
        msg = (f"{name}: {o['value']:,.0f} officially reported confirmed {kind} as of {o['as_of']} ({o['source']})."
               if o else f"No official confirmed {kind} are recorded for {name}. A missing report is not evidence of zero cases.")
        est = s.get("estimated_total") or {}
        if kind == "cases" and not est.get("insufficient") and est.get("median") is not None:
            msg += f" Model-based estimate of cumulative symptomatic infections: {est['lower_90']:,}–{est['upper_90']:,} (confidence {est['confidence']})."
    elif kind == "estimate":
        est = s.get("estimated_total") or {}
        msg = (f"{name}: estimated cumulative symptomatic infections {est['lower_90']:,}–{est['upper_90']:,} (median {est['median']:,}; "
               f"90% interval; confidence {est['confidence']}). This is a model estimate, not a count of confirmed cases."
               if not est.get("insufficient") else f"{name}: {views.INSUFFICIENT}")
    elif kind == "forecast":
        fc = s.get("forecasts") or {}
        if fc.get("insufficient") or not fc:
            msg = f"{name}: Available observations are insufficient for numerical forecasting."
        else:
            base = fc["targets"]["new_reported_confirmed"]["baseline"]
            r28 = next((r for r in base if r["horizon_days"] == 28), base[0])
            msg = (f"{name}: under current conditions, {r28['lower_90']:,}–{r28['upper_90']:,} additional reported confirmed cases over "
                   f"{r28['horizon_days']} days (median {r28['median']:,}; confidence {r28['confidence']}). Forecasts are uncertain.")
    elif kind == "severity":
        sev = s["severity"]
        msg = f"{name}: {sev['label']} (confidence {sev.get('confidence') or 'n/a'}). {sev.get('explanation', '')}"
    elif kind == "rt":
        rt = s.get("rt") or {}
        msg = (f"{name}: R_t of reported cases {rt['median']} (90% interval {rt['lower_90']}–{rt['upper_90']})."
               if not rt.get("insufficient") else f"{name}: R_t is not identifiable from available data.")
    else:
        sq = s.get("surveillance") or {}
        msg = f"{name}: surveillance evidence rated '{sq.get('overall', 'insufficient_information')}'. " + "; ".join(sq.get("concerns", []))
    return {"answered": True, "intent": f"data:{kind}", "region": views.region_ref(region), "message": msg, "disclaimer": DISCLAIMER}
