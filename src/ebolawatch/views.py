"""Public read models.

Every public output channel (API, dashboard, exports, reports, alerts) is built
from these functions so that the publication policy is applied identically
everywhere:

* only publishable observations (auto-validated or verified) appear;
* resolution is capped at first-level administrative units, with small-area and
  complementary suppression;
* unofficial signals are paraphrased, generalised to admin-1/country, and never
  linked to individual posts or accounts;
* model outputs always carry data date, model version, confidence and the
  "insufficient evidence" state where applicable;
* synthetic data are labelled.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db.models import (
    Alert,
    Correction,
    Document,
    Estimate,
    Forecast,
    ForecastEvaluation,
    LiteratureEstimate,
    ModelRun,
    Observation,
    Region,
    SeverityAssessment,
    SignalCluster,
    Source,
    TransportEdge,
    TransportNode,
)
from .domain.enums import OFFICIAL_CATEGORIES, SourceCategory
from .epi.parameters import MODEL_VERSION
from .epi.series import source_rank
from .privacy.policy import Policy, PublicCell, apply_suppression
from .safety.scope import DISCLAIMER
from .severity.classify import LEVEL_DESCRIPTIONS, LEVEL_NAMES

PUBLISHABLE = ("auto_validated", "verified")
INSUFFICIENT = "Insufficient evidence for a reliable numerical estimate."


def _iso(d) -> str | None:
    return d.isoformat() if d else None


def region_ref(r: Region) -> dict:
    return {"code": r.code, "name": r.name, "level": r.level, "iso3": r.iso3}


def public_regions(session: Session) -> list[Region]:
    return list(session.scalars(select(Region).where(Region.level <= Policy.from_settings().max_admin_level).order_by(Region.level, Region.name)))


def current_outbreak(session: Session, region: Region):
    from .pipeline.modeling import active_outbreak, latest_outbreak

    return active_outbreak(session, region.iso3, date.today()) or latest_outbreak(session, region.iso3)


def outbreak_view(ob) -> dict | None:
    if ob is None:
        return None
    return {"key": ob.key, "name": ob.name, "pathogen": ob.pathogen, "declared_on": _iso(ob.declared_on), "ended_on": _iso(ob.ended_on),
            "auto_registered": ob.key.startswith("AUTO-"), "citation": ob.notes}


def latest_official(session: Session, region: Region, metric: str, case_class: str, transmission: str = "all",
                    outbreak_id: int | None = None) -> dict | None:
    """Latest publishable cumulative value. Jurisdiction totals are scoped to the
    current (or most recent) outbreak; imported cases to the last 12 months."""
    q = (select(Observation, Source).join(Source, Observation.source_id == Source.id)
         .where(Observation.region_id == region.id, Observation.metric == metric, Observation.case_class == case_class,
                Observation.transmission == transmission, Observation.value_type == "cumulative",
                Observation.validation_status.in_(PUBLISHABLE))
         .order_by(Observation.as_of.desc(), Observation.published_at.desc(), Observation.id.desc()))
    if transmission == "all":
        if outbreak_id is None:
            ob = current_outbreak(session, region)
            outbreak_id = ob.id if ob else -1
        q = q.where(Observation.outbreak_id == outbreak_id)
    else:
        q = q.where(Observation.as_of >= date.today() - timedelta(days=365))
    rows = session.execute(q.limit(20)).all()
    if not rows:
        return None
    # for the latest date, the source the series uses (see epi.series.SOURCE_PRIORITY)
    o, s = min((r for r in rows if r[0].as_of == rows[0][0].as_of),
               key=lambda r: (r[0].validation_status != "verified", source_rank(r[1].key)))
    return {"value": o.value, "as_of": _iso(o.as_of), "source": s.name, "source_key": s.key, "citation": o.citation,
            "published_at": _iso(o.published_at), "validation_status": o.validation_status,
            "extraction_method": o.extraction_method, "is_synthetic": o.is_synthetic}


def _latest_run(session: Session, region: Region) -> ModelRun | None:
    return session.scalars(select(ModelRun).where(ModelRun.region_id == region.id, ModelRun.model_name == "region_model")
                           .order_by(ModelRun.run_at.desc(), ModelRun.id.desc())).first()


def _latest_severity(session: Session, region: Region) -> SeverityAssessment | None:
    return session.scalars(select(SeverityAssessment).where(SeverityAssessment.region_id == region.id)
                           .order_by(SeverityAssessment.assessed_at.desc(), SeverityAssessment.id.desc())).first()


def severity_view(sa: SeverityAssessment | None) -> dict:
    if sa is None:
        return {"status": "not_assessed", "level": None, "label": "NOT ASSESSED", "confidence": None,
                "explanation": "This area has not been assessed.", "triggers": []}
    return {
        "status": sa.status, "level": sa.level,
        "label": LEVEL_NAMES.get(sa.level, "INSUFFICIENT INFORMATION") if sa.level is not None else "INSUFFICIENT INFORMATION",
        "description": LEVEL_DESCRIPTIONS.get(sa.level) if sa.level is not None else
        "Insufficient information to assess current severity. A data void is not evidence of either absence or intensity of transmission.",
        "confidence": sa.confidence, "underestimation_risk": sa.underestimation_risk, "explanation": sa.explanation,
        "triggers": [{"code": t["code"], "text": t["text"], "level": t.get("level")} for t in sa.triggers or []],
        "confidence_reasons": (sa.surveillance or {}).get("confidence_reasons", []),
        "assessed_at": _iso(sa.assessed_at), "data_as_of": _iso(sa.data_as_of), "model_version": sa.model_version,
        "is_synthetic": sa.is_synthetic,
    }


def _estimates(session: Session, run: ModelRun) -> dict[tuple[str, str], Estimate]:
    return {(e.quantity, e.method): e for e in session.scalars(select(Estimate).where(Estimate.model_run_id == run.id))}


def _est_view(e: Estimate | None, label: str) -> dict:
    if e is None:
        return {"label": label, "insufficient": True, "message": INSUFFICIENT}
    if e.insufficient or e.median is None:
        return {"label": label, "insufficient": True, "message": INSUFFICIENT, "reason": e.reason}
    rnd = (lambda v: round(v, 2)) if e.quantity.startswith("rt_") else (lambda v: round(v))
    return {"label": label, "insufficient": False, "median": rnd(e.median), "lower_90": rnd(e.lower_90), "upper_90": rnd(e.upper_90),
            "lower_50": rnd(e.lower_50) if e.lower_50 is not None else None,
            "upper_50": rnd(e.upper_50) if e.upper_50 is not None else None,
            "interval": "90% credible interval", "confidence": e.confidence, "method": e.method,
            "period_start": _iso(e.period_start), "period_end": _iso(e.period_end), "assumptions": e.assumptions,
            "details": e.details}


def forecasts_view(session: Session, run: ModelRun) -> dict:
    rows = list(session.scalars(select(Forecast).where(Forecast.model_run_id == run.id).order_by(Forecast.horizon_days)))
    if not rows or all(f.insufficient for f in rows):
        reason = next((f.reason for f in rows if f.insufficient), None)
        return {"insufficient": True, "message": "Available observations are insufficient for numerical forecasting.", "reason": reason}
    out: dict = {"insufficient": False, "data_as_of": _iso(run.data_as_of), "issued_at": _iso(run.run_at), "targets": {}}
    for f in rows:
        if f.insufficient:
            continue
        t = out["targets"].setdefault(f.target, {})
        t.setdefault(f.scenario, []).append({
            "horizon_days": f.horizon_days, "median": round(f.quantiles["0.5"]),
            "lower_90": round(f.quantiles["0.05"]), "upper_90": round(f.quantiles["0.95"]),
            "lower_50": round(f.quantiles["0.25"]), "upper_50": round(f.quantiles["0.75"]),
            "p_continued_transmission": f.p_continued_transmission, "p_new_affected_unit": f.p_geographic_expansion,
            "confidence": f.confidence, "is_scenario": f.is_scenario,
            "label": "scenario (assumption-driven, not a prediction)" if f.is_scenario else "forecast",
        })
    out["scenario_definitions"] = {
        "improving": "R_t of reported cases declines ~10% per week for four weeks, then holds (improving containment)",
        "baseline": "continuation of current conditions (R_t random walk without drift)",
        "deteriorating": "R_t rises ~10% per week for four weeks, then holds (deteriorating surveillance and response)",
    }
    out["comparison"] = (run.diagnostics or {}).get("model_comparison")
    return out


def region_summary(session: Session, region: Region, detail: bool = False) -> dict:
    run = _latest_run(session, region)
    sa = _latest_severity(session, region)
    ob = current_outbreak(session, region)
    official = {
        "confirmed_cases": latest_official(session, region, "cases", "confirmed"),
        "probable_cases": latest_official(session, region, "cases", "probable"),
        "suspected_cases": latest_official(session, region, "cases", "suspected"),
        "confirmed_deaths": latest_official(session, region, "deaths", "confirmed"),
        "probable_deaths": latest_official(session, region, "deaths", "probable"),
        "imported_cases": latest_official(session, region, "cases", "confirmed", "imported"),
    }
    out: dict = {
        "region": region_ref(region), "outbreak": outbreak_view(ob), "official": official, "severity": severity_view(sa),
        "model_version": MODEL_VERSION, "is_synthetic": any((v or {}).get("is_synthetic") for v in official.values()),
    }
    if run:
        est = _estimates(session, run)
        diag = run.diagnostics or {}
        out.update({
            "data_as_of": _iso(run.data_as_of), "latest_update": _iso(run.run_at), "model_run_id": run.id,
            "model_status": run.status, "model_reasons": diag.get("reasons", []),
            "estimated_total": _est_view(est.get(("cumulative_symptomatic_infections", "headline")),
                                         "Estimated cumulative symptomatic infections (reported and unreported)"),
            "recent_incidence": _est_view(est.get(("recent_symptomatic_infections_14d", "renewal_projection")),
                                          "Estimated new symptomatic infections, last 14 days"),
            "rt": _est_view(est.get(("rt_reported_cases", "cori_weekly")), "Reproduction number of reported cases (R_t)"),
            "nowcast_reported": _est_view(est.get(("nowcast_reported_cumulative", "renewal_projection")),
                                          "Projected cumulative reported confirmed cases to date (reporting-delay nowcast)"),
            "ascertainment": _ascertainment(est),
            "model_disagreement": (est.get(("cumulative_symptomatic_infections", "headline")).details or {}).get("disagreement")
            if est.get(("cumulative_symptomatic_infections", "headline")) else None,
            "expansion": _expansion_view(diag.get("expansion")),
            "surveillance": (sa.surveillance if sa else {}),
            "growth": diag.get("growth"),
        })
        if detail:
            out["forecasts"] = forecasts_view(session, run)
            out["weekly"] = diag.get("weekly")
            out["rt_history"] = (diag.get("rt") or {}).get("history")
            out["burden_methods"] = [_burden_method(b) for b in diag.get("burden", [])]
            out["parameters"] = run.parameters
    else:
        out.update({"data_as_of": sa and _iso(sa.data_as_of), "estimated_total": {"insufficient": True, "message": INSUFFICIENT,
                    "reason": "no official case series for this area"}, "surveillance": (sa.surveillance if sa else {})})
    return out


def _burden_method(b: dict) -> dict:
    keep = ("method", "quantity", "insufficient", "reason", "median", "lower_90", "upper_90", "lower_50", "upper_50", "ascertainment", "assumptions", "diagnostics")
    d = {k: b.get(k) for k in keep}
    for k in ("median", "lower_90", "upper_90", "lower_50", "upper_50"):
        if d.get(k) is not None:
            d[k] = round(d[k])
    return d


def _ascertainment(est) -> dict:
    e = est.get(("cumulative_symptomatic_infections", "deaths_backcalculation"))
    if not e or e.insufficient:
        return {"identifiable": False, "message": "Reporting completeness is not identifiable from available data."}
    a = (e.details or {}).get("ascertainment")
    if not a:
        return {"identifiable": False, "message": "Reporting completeness is not identifiable from available data."}
    return {"identifiable": True, "median": round(a["median"], 2), "lower_90": round(a["lower_90"], 2), "upper_90": round(a["upper_90"], 2),
            "method": "mortality-based back-calculation", "note": "Fraction of symptomatic infections that appear as reported confirmed cases"}


def _expansion_view(x: dict | None) -> dict | None:
    if not x:
        return None
    if x.get("insufficient"):
        return {"insufficient": True, "reason": x.get("reason")}
    return {"insufficient": False, "unit": x["unit"], "weekly_rate_median": round(x["weekly_rate_median"], 2),
            "weekly_rate_90": [round(v, 2) for v in x["weekly_rate_90"]],
            "p_new_unit": {str(k): round(v, 2) for k, v in (x.get("p_new_unit") or {}).items()},
            "expected_new_units": x.get("expected_new_units"),
            "method": "Poisson-gamma model of newly affected units from the outbreak's recent record"}


def overview(session: Session) -> dict:
    regions = [r for r in public_regions(session)]
    sev = {}
    for r in regions:
        sa = _latest_severity(session, r)
        if sa:
            sev[r.id] = sa
    def _current(r: Region) -> bool:
        if r.id in sev and ((sev[r.id].level or 0) >= 1 or sev[r.id].status != "assessed"):
            return True
        oc = latest_official(session, r, "cases", "confirmed")
        # historical outbreaks (last report > 1 year ago) are not shown as current areas
        return bool(oc and oc["as_of"] and (date.today() - date.fromisoformat(oc["as_of"])).days <= 365)

    shown = [r for r in regions if r.level == 0 and _current(r)]
    summaries = [region_summary(session, r) for r in shown]
    summaries.sort(key=lambda s: (-(s["severity"]["level"] if s["severity"]["level"] is not None else 2.5), s["region"]["name"]))
    assessed = [{"code": r.code, "name": r.name, "level": r.level, "severity_level": sev[r.id].level if r.id in sev else None,
                 "severity_status": sev[r.id].status if r.id in sev else "not_assessed",
                 "confidence": sev[r.id].confidence if r.id in sev else None} for r in regions]
    syn = session.scalar(select(func.count(Observation.id)).where(Observation.is_synthetic.is_(True))) or 0
    last_run = session.scalars(select(ModelRun).order_by(ModelRun.run_at.desc())).first()
    return {
        "disclaimer": DISCLAIMER, "generated_at": _iso(date.today()), "model_version": MODEL_VERSION,
        "latest_model_run": _iso(last_run.run_at) if last_run else None,
        "contains_synthetic_data": syn > 0, "regions": summaries, "map": assessed,
        "alerts": alerts_public(session, limit=10), "developments": latest_developments(session),
    }


def latest_developments(session: Session, limit: int = 10) -> list[dict]:
    q = (select(Document, Source).join(Source, Document.source_id == Source.id)
         .where(Source.category.in_([c.value for c in OFFICIAL_CATEGORIES])).order_by(Document.published_at.desc()).limit(limit))
    return [{"title": d.title, "published_at": _iso(d.published_at), "source": s.name, "url": d.url, "official": True,
             "is_synthetic": d.is_synthetic} for d, s in session.execute(q) if d.title]


def alerts_public(session: Session, limit: int = 50) -> list[dict]:
    q = select(Alert, Region).outerjoin(Region, Alert.region_id == Region.id).where(Alert.published.is_(True)).order_by(Alert.created_at.desc()).limit(limit)
    out = []
    for a, r in session.execute(q):
        out.append({"id": a.id, "created_at": _iso(a.created_at), "region": region_ref(r) if r and r.level <= 1 else None,
                    "kind": a.kind, "message": a.message, "severity_level": a.severity_level, "confidence": a.confidence,
                    "relies_on_unofficial": a.relies_on_unofficial, "reviewed": a.review_status == "approved",
                    "evidence": _alert_evidence(a), "retracted": a.retracted, "is_synthetic": a.is_synthetic})
    for c in session.scalars(select(Correction).where(Correction.target_type == "alert").order_by(Correction.created_at.desc()).limit(10)):
        out.append({"id": None, "created_at": _iso(c.created_at), "kind": "retraction", "message": c.public_note, "retracted": True})
    return out


def _alert_evidence(a: Alert) -> dict:
    ev = a.evidence or {}
    return {"triggers": [{"code": t.get("code"), "text": t.get("text")} for t in ev.get("triggers", [])],
            "summary": ev.get("summary"), "independent_origins": ev.get("independent_origins"), "explanation": ev.get("explanation")}


def official_series(session: Session, region: Region, metric: str, case_class: str) -> dict:
    ob = current_outbreak(session, region)
    q = (select(Observation, Source).join(Source, Observation.source_id == Source.id)
         .where(Observation.region_id == region.id, Observation.metric == metric, Observation.case_class == case_class,
                Observation.value_type == "cumulative", Observation.transmission == "all",
                Observation.outbreak_id == (ob.id if ob else -1),
                Observation.validation_status.in_(PUBLISHABLE)).order_by(Observation.as_of, Observation.id))
    points, revisions = [], []
    seen: dict[tuple[str, date], dict] = {}
    for o, s in session.execute(q):
        key = (s.key, o.as_of)
        if key in seen:
            revisions.append({"as_of": _iso(o.as_of), "source": s.name, "previous": seen[key]["value"], "revised": o.value,
                              "revised_published_at": _iso(o.published_at)})
        seen[key] = {"as_of": _iso(o.as_of), "value": o.value, "source": s.name, "source_key": s.key, "published_at": _iso(o.published_at),
                     "citation": o.citation, "validation_status": o.validation_status, "is_synthetic": o.is_synthetic}
    points = sorted(seen.values(), key=lambda p: (p["as_of"], p["source_key"]))
    pending = session.scalar(select(func.count(Observation.id)).where(Observation.region_id == region.id, Observation.metric == metric,
                                                                      Observation.validation_status == "pending_review")) or 0
    return {"region": region_ref(region), "outbreak": outbreak_view(ob), "metric": metric, "case_class": case_class, "points": points,
            "revisions": revisions, "observations_pending_review": pending,
            "note": "Observation dates (as_of) are separate from publication dates. Missing dates are not zero reports."}


def subnational(session: Session, country: Region, metric: str = "cases", case_class: str = "confirmed") -> list[dict]:
    """Admin-1 table for a country with the publication policy applied."""
    from .pipeline.modeling import series_for

    cells = []
    for r in session.scalars(select(Region).where(Region.parent_id == country.id, Region.level == 1)):
        s = series_for(session, r, metric, case_class)
        if not s.points:
            continue
        cells.append(PublicCell(r.code, r.name, 1, country.code, r.population, s.last_value))
    out = apply_suppression(cells)
    return [c.as_dict() | {"as_of": None} for c in out]


def signals_public(session: Session, region: Region | None = None, limit: int = 50) -> list[dict]:
    from .nlp.gazetteer import load_gazetteer

    g = load_gazetteer()
    q = select(SignalCluster, Region).outerjoin(Region, SignalCluster.region_id == Region.id).order_by(SignalCluster.last_seen.desc()).limit(500)
    out = []
    for cl, r in session.execute(q):
        if cl.status == "reviewed_not_credible":
            continue
        unit = None
        if r is not None:
            code = r.code if r.level <= 1 else g.parents.get(r.code, r.iso3)
            unit_reg = session.scalar(select(Region).where(Region.code == code))
            unit = region_ref(unit_reg) if unit_reg else None
        if region is not None and (unit is None or (unit["code"] != region.code and unit["iso3"] != region.code)):
            continue
        out.append({
            "id": cl.id, "unit": unit, "claim": cl.claim_type, "assessment": cl.assessment, "corroboration": cl.corroboration,
            "summary": _paraphrase(cl, unit), "first_seen": _iso(cl.first_seen.date() if cl.first_seen else None),
            "last_seen": _iso(cl.last_seen.date() if cl.last_seen else None),
            "independent_origins": _bucket(cl.n_independent_origins), "items": _bucket(cl.n_documents),
            "languages": cl.languages, "coordination_suspected": cl.coordination_suspected, "stale": cl.stale,
            "review_status": cl.status,
            "verification": ("official" if (cl.evidence or {}).get("official_documents", 0) >= cl.n_documents else
                             "consistent with official data" if cl.corroboration == "official_confirmed" else "UNVERIFIED"),
            "is_synthetic": cl.is_synthetic,
        })
        if len(out) >= limit:
            break
    return out


def _bucket(n: int) -> str:
    return "0" if not n else "1" if n == 1 else "2-4" if n < 5 else "5-19" if n < 20 else "20+"


def _paraphrase(cl: SignalCluster, unit: dict | None) -> str:
    from .domain.enums import ClaimType
    from .evidence.assess import CLAIM_PHRASES

    where = f"in {unit['name']}" if unit else "in an unresolved location"
    phrase = CLAIM_PHRASES.get(ClaimType(cl.claim_type), "a health event")
    ev = cl.evidence or {}
    n_official = ev.get("official_documents", 0) or 0
    if n_official and n_official >= cl.n_documents:
        who = "Official bulletins describe"
    elif n_official:
        who = "Official bulletins and public reports describe"
    elif cl.corroboration == "official_confirmed":
        who = "Public reports, consistent with official data, describe"
    else:
        who = "Unverified public reports describe"
    return f"{who} {phrase} {where}. {cl.assessment}"


def evidence(session: Session, region: Region) -> dict:
    docs = session.execute(
        select(Document, Source).join(Source, Document.source_id == Source.id)
        .join(Observation, Observation.document_id == Document.id)
        .where(Observation.region_id == region.id).distinct().order_by(Document.published_at.desc()).limit(50)).all()
    status_counts = dict(session.execute(select(Observation.validation_status, func.count()).where(Observation.region_id == region.id)
                                         .group_by(Observation.validation_status)).all())
    lit = [{"statement": e.statement, "citation": e.citation, "url": e.url, "as_of": _iso(e.as_of), "lower": e.lower, "upper": e.upper,
            "validation_status": e.validation_status} for e in session.scalars(select(LiteratureEstimate).where(LiteratureEstimate.region_code == region.code))]
    run = _latest_run(session, region)
    return {
        "region": region_ref(region),
        "official_sources": [{"title": d.title, "source": s.name, "category": s.category, "published_at": _iso(d.published_at),
                              "url": d.url, "official": SourceCategory(s.category) in OFFICIAL_CATEGORIES} for d, s in docs],
        "observation_validation": status_counts,
        "unofficial_signals": signals_public(session, region),
        "published_estimates": lit,
        "assumptions": (run.parameters if run else None),
        "last_updated": _iso(run.run_at) if run else None,
    }


def sources_status(session: Session) -> list[dict]:
    return [{"key": s.key, "name": s.name, "institution": s.institution, "category": s.category, "access_method": s.access_method,
             "license": s.license, "terms_note": s.terms_note, "status": s.status, "status_message": s.status_message,
             "last_attempt_at": _iso(s.last_attempt_at), "last_success_at": _iso(s.last_success_at), "homepage": s.homepage}
            for s in session.scalars(select(Source).order_by(Source.category, Source.key))]


def transport_context(session: Session, region: Region | None = None) -> dict:
    from .nlp.gazetteer import load_gazetteer
    from .pipeline.modeling import _cases_in_window, series_for
    from .transport.network import EdgeSpec, introduction_ranking

    g = load_gazetteer()
    nodes = {n.id: n for n in session.scalars(select(TransportNode))}
    edges = list(session.scalars(select(TransportEdge)))
    codes = {region.code} if region else None
    if region is not None and region.level == 0:
        codes = {region.code} | {k for k in (n.key for n in nodes.values()) if g.country_of(k) == region.code}
    edge_rows = []
    for e in edges:
        a, b = nodes[e.from_node_id], nodes[e.to_node_id]
        if codes and a.key not in codes and b.key not in codes:
            continue
        edge_rows.append({"key": e.key, "from": {"code": a.key, "name": a.name}, "to": {"code": b.key, "name": b.name},
                          "mode": e.mode, "corridor": e.corridor, "cross_border": e.cross_border,
                          "physical_status": e.physical_status, "service_status": e.service_status, "verification": e.verification,
                          "verified_on": _iso(e.verified_on), "seasonal_note": e.seasonal_note, "disruption_note": e.disruption_note,
                          "notes": e.notes, "sources": e.sources,
                          "line": [[a.lon, a.lat], [b.lon, b.lat]]})
    specs = [EdgeSpec(e.key, nodes[e.from_node_id].key, nodes[e.to_node_id].key, e.mode, e.service_status, e.physical_status,
                      e.verification, e.cross_border, e.corridor) for e in edges]
    weights = {}
    for n in nodes.values():
        reg = session.scalar(select(Region).where(Region.code == n.key))
        if reg:
            s = series_for(session, reg)
            if s.points:
                w = _cases_in_window(s, 21) or 0
                if w > 0:
                    weights[n.key] = w
    # prefer admin-1 sources over their own country node to avoid double counting
    for k in list(weights):
        if len(k) == 3 and any(g.country_of(o) == k for o in weights if o != k):
            weights.pop(k)
    coords = {n.key: (n.lat, n.lon) for n in nodes.values()}
    ranking = introduction_ranking(specs, weights, coords) if weights else []
    name = {n.key: n.name for n in nodes.values()}
    for r in ranking:
        r["name"] = name.get(r["unit"], r["unit"])
        r["path_names"] = [name.get(p, p) for p in r["path"]]
    if codes:
        ranking = [r for r in ranking if r["unit"] in codes or any(p in codes for p in r["path"][:1])]
    return {
        "edges": edge_rows, "introduction_ranking": ranking[:25], "sources_of_risk": {k: round(v) for k, v in weights.items()},
        "caveats": [
            "Connectivity is not transmission: Ebola spreads through direct contact with symptomatic or deceased people.",
            "Relative scores compare areas under scenarios for services whose operation is unverified (closed / partial / open); "
            "they are not probabilities and no passenger volumes are assumed.",
            "Corridors are generalised to administrative units; no routes, crossings or facilities are shown.",
        ],
    }


def evaluation(session: Session) -> dict:
    runs = list(session.scalars(select(ModelRun).where(ModelRun.model_name == "backtest").order_by(ModelRun.run_at.desc()).limit(20)))
    latest: dict[str, ModelRun] = {}
    for r in runs:
        ds = (r.diagnostics or {}).get("dataset")
        if ds and ds not in latest:
            latest[ds] = r
    return {
        "model_version": MODEL_VERSION,
        "datasets": [{"dataset": ds, "is_synthetic": r.is_synthetic, "run_at": _iso(r.run_at), "summary": (r.diagnostics or {}).get("summary"),
                      "expansion": (r.diagnostics or {}).get("expansion"), "notes": (r.diagnostics or {}).get("notes", []),
                      "label": "SYNTHETIC (known truth; calibration check)" if r.is_synthetic else "Official data (real outbreak)"}
                     for ds, r in latest.items()],
        "detection_performance": {"status": "not yet estimable",
                                  "reason": "requires a history of reviewed signal clusters with later official outcomes"},
        "note": "Negative results are shown as computed. Coverage below nominal indicates overconfident intervals.",
    }


def forecast_comparison(session: Session, region: Region) -> list[dict]:
    """Past baseline forecasts of new reported cases vs what was later reported."""
    from .pipeline.modeling import series_for

    s = series_for(session, region)
    out = []
    q = (select(Forecast).where(Forecast.region_id == region.id, Forecast.scenario == "baseline", Forecast.target == "new_reported_confirmed",
                                Forecast.insufficient.is_(False), Forecast.horizon_days.in_((7, 14, 28))).order_by(Forecast.issued_at.desc()).limit(300))
    for f in session.scalars(q):
        base = s.value_at(f.data_as_of)
        tgt = s.value_at(f.data_as_of + timedelta(days=f.horizon_days))
        observed = (tgt - base) if (base is not None and tgt is not None) else None
        out.append({"issued_at": _iso(f.issued_at), "data_as_of": _iso(f.data_as_of), "horizon_days": f.horizon_days,
                    "median": round(f.quantiles["0.5"]), "lower_90": round(f.quantiles["0.05"]), "upper_90": round(f.quantiles["0.95"]),
                    "observed": round(observed) if observed is not None else None,
                    "within_90": (f.quantiles["0.05"] <= observed <= f.quantiles["0.95"]) if observed is not None else None})
    seen, uniq = set(), []
    for r in out:
        k = (r["data_as_of"], r["horizon_days"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    evals = [{"origin_date": _iso(e.origin_date), "horizon_days": e.horizon_days, "observed": round(e.observed), "median": round(e.median),
              "lower_90": round(e.lower_90), "upper_90": round(e.upper_90), "source": "backtest"}
             for e in session.scalars(select(ForecastEvaluation).where(ForecastEvaluation.region_code == region.code)
                                      .order_by(ForecastEvaluation.created_at.desc(), ForecastEvaluation.origin_date).limit(60))]
    return uniq + evals


def map_geometry(session: Session, level: int) -> dict:
    """Simplified boundaries (public-safe resolution) for the dashboard map."""
    level = min(level, Policy.from_settings().max_admin_level)
    feats = []
    for r in session.scalars(select(Region).where(Region.level == level, Region.geometry.is_not(None))):
        if level == 0 and not (r.priority or _africa_or_near(r)):
            continue
        feats.append({"type": "Feature", "properties": {"code": r.code, "name": r.name, "iso3": r.iso3, "level": r.level,
                                                        "label": [r.centroid_lon, r.centroid_lat]},
                      "geometry": r.geometry})
    return {"type": "FeatureCollection", "features": feats,
            "attribution": "Boundaries: Natural Earth (public domain); geoBoundaries gbOpen (per-country licences, see NOTICE)"}


def _africa_or_near(r: Region) -> bool:
    lat, lon = r.centroid_lat, r.centroid_lon
    return lat is not None and -40 <= lat <= 40 and -25 <= lon <= 60


def map_layers(session: Session) -> dict:
    """Per-unit values for the map layers. Each layer is a separate field; nothing is combined."""
    tc = transport_context(session)
    tiers = {r["unit"]: {"tier": r["tier"], "robust": r["robust"]} for r in tc["introduction_ranking"]}
    units = {}
    for r in public_regions(session):
        sa = _latest_severity(session, r)
        oc = latest_official(session, r, "cases", "confirmed")
        run = _latest_run(session, r)
        est = None
        if run:
            e = _estimates(session, run).get(("cumulative_symptomatic_infections", "headline"))
            if e and not e.insufficient and e.median is not None:
                est = {"median": round(e.median), "lower_90": round(e.lower_90), "upper_90": round(e.upper_90), "confidence": e.confidence}
        if not (sa or oc or est or r.code in tiers):
            continue
        units[r.code] = {
            "name": r.name, "level": r.level,
            "official_confirmed": oc["value"] if oc else None, "official_as_of": oc["as_of"] if oc else None,
            "estimated_total": est,
            "severity_level": sa.level if sa else None, "severity_status": sa.status if sa else "not_assessed",
            "confidence": sa.confidence if sa else None, "underestimation_risk": sa.underestimation_risk if sa else False,
            "surveillance_overall": (sa.surveillance or {}).get("overall") if sa else None,
            "connectivity_tier": tiers.get(r.code),
        }
    # subnational official values pass through suppression before publication
    for c in session.scalars(select(Region).where(Region.level == 0, Region.priority.is_(True))):
        for cell in subnational(session, c):
            u = units.get(cell["region_code"])
            if u is not None and cell["suppressed"]:
                u["official_confirmed"] = None
                u["official_display"] = cell["display"]
    edges = [{"key": e["key"], "mode": e["mode"], "service_status": e["service_status"], "verification": e["verification"],
              "cross_border": e["cross_border"], "corridor": e["corridor"], "line": e["line"]} for e in tc["edges"]]
    return {"units": units, "transport_edges": edges, "transport_caveats": tc["caveats"],
            "layers": {
                "official": "Officially reported confirmed cases (current outbreak)",
                "estimated": "Estimated cumulative symptomatic infections (model; 90% interval)",
                "forecast_risk": "Severity level and relative connectivity to active areas (scenario-based, not a probability)",
                "surveillance": "Assessment confidence and surveillance-quality concerns",
                "transport": "Generalised multimodal corridors between administrative units",
            }}
