"""Modelling stage: build series from the database, run models, assess severity,
persist estimates/forecasts/assessments, and raise major-change alerts."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, timedelta

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db.models import (
    Alert,
    Estimate,
    Forecast,
    ModelRun,
    Observation,
    Outbreak,
    Region,
    SeverityAssessment,
    Source,
    TransportEdge,
    TransportNode,
)
from ..domain.enums import Confidence
from ..epi.model import RegionInputs, RegionModelOutput, forecast_confidence, run_region
from ..epi.parameters import MODEL_VERSION, load_mobility
from ..epi.series import CumulativeSeries, build_cumulative
from ..nlp.gazetteer import load_gazetteer
from ..review.queue import enqueue
from ..severity.classify import SEVERITY_VERSION, SeverityInputs, classify, load_thresholds
from ..severity.surveillance import SurveillanceInputs, assess
from ..transport.network import EdgeSpec, build_graph

PUBLISHABLE = ("auto_validated", "verified")
TEXT_EXTRACTED = ("who_don", "ecdc")  # figures read from narrative text


def _rows(session: Session, region_ids: list[int], metric: str, case_class: str, transmission: str = "all",
          value_type: str = "cumulative", outbreak_id: int | None = None) -> list[dict]:
    q = (select(Observation, Source.key).join(Source, Observation.source_id == Source.id)
         .where(Observation.region_id.in_(region_ids), Observation.metric == metric, Observation.case_class == case_class,
                Observation.transmission == transmission, Observation.value_type == value_type))
    if outbreak_id is not None:
        q = q.where(Observation.outbreak_id == outbreak_id)
    return [{"as_of": o.as_of, "value": o.value, "source_key": k, "published_at": o.published_at, "id": o.id,
             "validation_status": o.validation_status, "region_id": o.region_id, "attributes": o.attributes,
             "period_start": o.period_start, "extraction_method": o.extraction_method, "is_synthetic": o.is_synthetic}
            for o, k in session.execute(q)]


def series_for(session: Session, region: Region, metric: str = "cases", case_class: str = "confirmed",
               outbreak_id: int | None = None) -> CumulativeSeries:
    """Cumulative series for one unit, restricted to one outbreak when given
    (series from different outbreaks must never be concatenated)."""
    if outbreak_id is None:
        ob = active_outbreak(session, region.iso3, date.today())
        outbreak_id = ob.id if ob else -1
    direct = _rows(session, [region.id], metric, case_class, outbreak_id=outbreak_id)
    s = build_cumulative(direct)
    if region.level == 1:
        hz_ids = [r.id for r in session.scalars(select(Region).where(Region.parent_id == region.id, Region.level == 2))]
        if hz_ids:
            hz = [r for r in _rows(session, hz_ids, metric, case_class, outbreak_id=outbreak_id) if r["validation_status"] in PUBLISHABLE]
            # sum the latest value of each health zone per date (dates where >= 1 zone reports)
            by_date: dict[date, dict[int, float]] = {}
            for r in sorted(hz, key=lambda r: (r["as_of"], r["id"])):
                by_date.setdefault(r["as_of"], {})[r["region_id"]] = r["value"]
            summed = [{"as_of": d, "value": sum(v.values()), "source_key": "hdx_cod_ebola", "published_at": None, "id": 0,
                       "validation_status": "auto_validated"} for d, v in by_date.items()]
            agg = build_cumulative(summed)
            if len(agg.points) > len(s.points):
                return agg
    return s


ACTIVE_SILENCE_DAYS = 120


def _last_linked(session: Session, outbreak_id: int) -> date | None:
    return session.scalar(select(Observation.as_of).where(Observation.outbreak_id == outbreak_id,
                                                          Observation.validation_status.in_(PUBLISHABLE))
                          .order_by(Observation.as_of.desc()).limit(1))


def active_outbreak(session: Session, iso3: str, today: date) -> Outbreak | None:
    """The current outbreak in a country: declared, and either ended within the
    last 42 days or not ended with official reports in the last 120 days."""
    best = None
    for o in session.scalars(_in_scope(select(Outbreak).where(Outbreak.primary_iso3 == iso3))):
        if o.declared_on is None or o.declared_on > today:
            continue
        if o.ended_on is not None:
            ok = o.ended_on >= today - timedelta(days=42)
        else:
            last = _last_linked(session, o.id)
            ok = (last is not None and last >= today - timedelta(days=ACTIVE_SILENCE_DAYS)) or (
                not o.key.startswith("AUTO-") and o.declared_on >= today - timedelta(days=ACTIVE_SILENCE_DAYS))
        if ok and (best is None or o.declared_on > best.declared_on):
            best = o
    return best


def latest_outbreak(session: Session, iso3: str) -> Outbreak | None:
    return session.scalars(_in_scope(select(Outbreak).where(Outbreak.primary_iso3 == iso3)).order_by(Outbreak.declared_on.desc())).first()


def _in_scope(q):
    """Only outbreaks of the current epidemic (declared on or after ``epidemic_start``)."""
    return q.where(Outbreak.declared_on >= get_settings().epidemic_start)


def pathogen_for(session: Session, iso3: str, today: date) -> tuple[str, Outbreak | None]:
    ob = active_outbreak(session, iso3, today) or latest_outbreak(session, iso3)
    return (ob.pathogen if ob else "unknown_orthoebolavirus"), ob


def _cases_in_window(s: CumulativeSeries, days: int) -> float | None:
    if not s.points:
        return None
    end = s.last_date
    start = end - timedelta(days=days)
    v_end = s.last_value
    v_start = s.value_at(start)
    if v_start is None:
        v_start = 0.0 if start < s.points[0].as_of else s.points[0].value
    return max(v_end - v_start, 0.0)


def _days_since_increase(s: CumulativeSeries, today: date) -> int | None:
    last = None
    for a, b in zip(s.points, s.points[1:], strict=False):
        if b.value > a.value:
            last = b.as_of
    if last is None and s.points and s.points[0].value > 0:
        last = s.points[0].as_of
    return (today - last).days if last else None


def _latest_obs(session: Session, region_id: int, metric: str) -> Observation | None:
    q = (select(Observation).where(Observation.region_id == region_id, Observation.metric == metric,
                                   Observation.validation_status.in_(PUBLISHABLE)).order_by(Observation.as_of.desc(), Observation.id.desc()))
    return session.scalars(q).first()


def run_models(session: Session, today: date | None = None, n_sims: int = 2000) -> list[ModelRun]:
    today = today or date.today()
    g = load_gazetteer()
    regions = list(session.scalars(select(Region).where(Region.level <= 1)))
    by_code = {r.code: r for r in regions}
    calibration = _latest_calibration(session)
    runs: list[ModelRun] = []
    outputs: dict[str, RegionModelOutput] = {}
    for region in regions:
        outbreak = active_outbreak(session, region.iso3, today)
        if outbreak is None:
            continue
        cases = series_for(session, region, outbreak_id=outbreak.id)
        if not cases.points:
            continue
        deaths = series_for(session, region, "deaths", "confirmed", outbreak_id=outbreak.id)
        probable = series_for(session, region, "cases", "probable", outbreak_id=outbreak.id)
        pathogen = outbreak.pathogen
        units = []
        if region.level == 0:
            units = [(r["as_of"], r["value"]) for r in _rows(session, [region.id], "affected_admin2_units", "confirmed", outbreak_id=outbreak.id)
                     if r["validation_status"] in PUBLISHABLE]
        exported = 0
        mobility = None
        if region.level == 0:
            exported = _exported_cases(session, region, outbreak)
            mobility = next((m for m in load_mobility() if region.code in (m.get("source_units") or []) or
                             any(g.country_of(u) == region.code for u in (m.get("source_units") or []))), None)
        inp = RegionInputs(region.code, pathogen, cases, deaths, probable, affected_units=sorted(set(units)),
                           exported_cases=exported, mobility=mobility, today=today)
        out = run_region(inp, n_sims=n_sims)
        outputs[region.code] = out
        runs.append(_persist(session, region, out, calibration, any(p.source_key in TEXT_EXTRACTED for p in cases.points[-3:])))
    session.flush()
    assess_all(session, regions, by_code, outputs, today)
    return runs


def _exported_cases(session: Session, origin: Region, outbreak: Outbreak | None) -> int:
    """Imported cases reported by other countries during the outbreak (medevac excluded)."""
    if outbreak is None:
        return 0
    q = (select(Observation, Region).join(Region, Observation.region_id == Region.id)
         .where(Observation.transmission == "imported", Observation.metric == "cases", Region.iso3 != origin.iso3,
                Observation.validation_status.in_(PUBLISHABLE)))
    best: dict[str, float] = {}
    for o, r in session.execute(q):
        if outbreak.declared_on and o.as_of < outbreak.declared_on - timedelta(days=30):
            continue
        best[r.iso3] = max(best.get(r.iso3, 0), o.value)  # max, not sum: repeated mentions are the same cases
    return int(sum(best.values()))


def _latest_calibration(session: Session) -> dict | None:
    run = session.scalars(select(ModelRun).where(ModelRun.model_name == "backtest", ModelRun.is_synthetic.is_(False))
                          .order_by(ModelRun.run_at.desc())).first()
    return (run.diagnostics or {}).get("summary") if run else None


def _persist(session: Session, region: Region, out: RegionModelOutput, calibration: dict | None, text_extracted: bool) -> ModelRun:
    diag = {
        "reasons": out.reasons, "weekly": out.weekly, "growth": out.growth, "model_comparison": out.model_comparison,
        "rt": None if out.rt is None or out.rt.insufficient else {
            "median": out.rt.median, "lower_90": out.rt.lower_90, "upper_90": out.rt.upper_90, "lower_50": out.rt.lower_50,
            "upper_50": out.rt.upper_50, "p_above_one": out.rt.p_above_one, "dispersion": out.rt.dispersion,
            "window_weeks": out.rt.window_weeks, "history": out.rt.history},
        "rt_reason": out.rt.reason if out.rt and out.rt.insufficient else None,
        "burden": [b.as_dict() for b in out.burden], "burden_headline": out.burden_headline,
        "recent_infections": out.recent_infections, "nowcast_reported": out.nowcast_reported,
        "expansion": asdict(out.expansion) if out.expansion else None, "data_age_days": out.data_age_days,
        "weeks_of_data": out.weeks_of_data, "text_extracted_inputs": text_extracted,
    }
    run = ModelRun(model_name="region_model", model_version=MODEL_VERSION, data_as_of=out.data_as_of, region_id=region.id,
                   status=out.status, parameters=json.loads(json.dumps(out.parameters, default=str)), inputs_hash=out.inputs_hash,
                   diagnostics=json.loads(json.dumps(diag, default=_np_default)))
    session.add(run)
    session.flush()
    h = out.burden_headline
    period_end = out.data_as_of
    session.add(Estimate(
        model_run_id=run.id, region_id=region.id, quantity="cumulative_symptomatic_infections", method="headline",
        period_end=period_end, median=h.get("median"), lower_90=h.get("lower_90"), upper_90=h.get("upper_90"),
        confidence=h.get("confidence") or "low", insufficient=bool(h.get("insufficient")),
        reason=h.get("message") if h.get("insufficient") else None,
        assumptions=[a for b in out.burden for a in b.assumptions][:12], details={"disagreement": h.get("disagreement"),
                                                                                 "primary_method": h.get("primary_method")}))
    for b in out.burden:
        session.add(Estimate(model_run_id=run.id, region_id=region.id, quantity=b.quantity, method=b.method, period_end=period_end,
                             median=b.median, lower_90=b.lower_90, upper_90=b.upper_90, lower_50=b.lower_50, upper_50=b.upper_50,
                             confidence="na", insufficient=b.insufficient, reason=b.reason, assumptions=b.assumptions,
                             details=json.loads(json.dumps({"diagnostics": b.diagnostics, "ascertainment": b.ascertainment}, default=_np_default))))
    if out.recent_infections:
        ri = out.recent_infections
        session.add(Estimate(model_run_id=run.id, region_id=region.id, quantity="recent_symptomatic_infections_14d", method="renewal_projection",
                             period_start=period_end - timedelta(days=14) if period_end else None, period_end=period_end,
                             median=ri["median"], lower_90=ri["lower_90"], upper_90=ri["upper_90"], lower_50=ri["lower_50"],
                             upper_50=ri["upper_50"], confidence="low" if (h.get("confidence") in (None, "low")) else "moderate",
                             assumptions=[ri["method"], ri["note"]]))
    if out.rt and not out.rt.insufficient:
        session.add(Estimate(model_run_id=run.id, region_id=region.id, quantity="rt_reported_cases", method="cori_weekly",
                             period_end=period_end, median=out.rt.median, lower_90=out.rt.lower_90, upper_90=out.rt.upper_90,
                             lower_50=out.rt.lower_50, upper_50=out.rt.upper_50, confidence="moderate",
                             assumptions=["R_t of reported cases; changes in ascertainment also change this quantity",
                                          "Serial interval transferred from EVD estimates with widened uncertainty"]))
    if out.nowcast_reported:
        nc = out.nowcast_reported
        session.add(Estimate(model_run_id=run.id, region_id=region.id, quantity="nowcast_reported_cumulative", method="renewal_projection",
                             period_end=date.fromisoformat(nc["as_of"]), median=nc["median"], lower_90=nc["lower_90"], upper_90=nc["upper_90"],
                             confidence="moderate" if nc["gap_days"] <= 7 else "low", assumptions=[nc["note"]]))
    for f in out.forecasts + out.infection_forecasts:
        session.add(Forecast(model_run_id=run.id, region_id=region.id, data_as_of=out.data_as_of, horizon_days=f.horizon_days,
                             scenario=f.scenario, target=f.target, quantiles=f.quantiles,
                             p_continued_transmission=f.p_continued_transmission,
                             p_geographic_expansion=(out.expansion.p_new_unit.get(f.horizon_days) if out.expansion and not out.expansion.insufficient and out.expansion.p_new_unit else None),
                             confidence=forecast_confidence(f.horizon_days, out.data_age_days, out.weeks_of_data, out.rt, calibration),
                             is_scenario=f.is_scenario))
    if not out.forecasts:
        session.add(Forecast(model_run_id=run.id, region_id=region.id, data_as_of=out.data_as_of or date.today(), horizon_days=0,
                             scenario="baseline", target="new_reported_confirmed", quantiles={}, confidence="low",
                             insufficient=True, reason="; ".join(out.reasons) or "insufficient data for numerical forecasting"))
    return run


def _np_default(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.ndarray):
        return None
    if isinstance(o, date):
        return o.isoformat()
    return str(o)


def assess_all(session: Session, regions: list[Region], by_code: dict[str, Region], outputs: dict[str, RegionModelOutput], today: date) -> list[SeverityAssessment]:
    th = load_thresholds()
    g = load_gazetteer()
    start = get_settings().epidemic_start
    # Activity map for connectivity-based WATCH (current outbreaks only)
    active_units = {code: (_cases_in_window(series_for(session, by_code[code]), 21) or 0) for code in outputs}
    graph = _transport_graph(session)
    results = []
    previous = {a.region_id: a for a in _latest_assessments(session)}
    first_dates = _first_confirmed_admin1(session, today)
    for region in regions:
        if region.level == 0 and not region.priority and region.code not in outputs and not _in_africa(region):
            if not session.scalar(select(Observation.id).where(Observation.region_id == region.id).limit(1)):
                continue
        out = outputs.get(region.code)
        current = active_outbreak(session, region.iso3, today)
        last_ob = current or latest_outbreak(session, region.iso3)
        cases = series_for(session, region, outbreak_id=last_ob.id) if last_ob else CumulativeSeries([])
        imported = [o.as_of for o in session.scalars(select(Observation).where(
            Observation.region_id == region.id, Observation.transmission == "imported", Observation.as_of >= start,
            Observation.validation_status.in_(PUBLISHABLE)))]
        q_latest = select(Observation).where(Observation.region_id == region.id, Observation.validation_status.in_(PUBLISHABLE))
        if last_ob:
            q_latest = q_latest.where((Observation.outbreak_id == last_ob.id) |
                                      ((Observation.transmission == "imported") & (Observation.as_of >= start)))
        else:
            q_latest = q_latest.where(Observation.as_of >= start)
        latest_any = session.scalars(q_latest.order_by(Observation.as_of.desc())).first()
        end_obs = session.scalars(select(Observation).where(Observation.region_id == region.id, Observation.metric == "outbreak_end_declared",
                                                           Observation.as_of >= start, Observation.validation_status.in_(PUBLISHABLE))
                                  .order_by(Observation.as_of.desc())).first()
        end_date = (last_ob.ended_on if last_ob and last_ob.ended_on else None) or (end_obs.as_of if end_obs else None)
        if end_date and cases.last_date and end_date < cases.last_date:
            end_date = None  # cases reported after the declaration: a new chain, not ended
        ever = bool(cases.points and (cases.last_value or 0) > 0)
        historical = bool(ever and current is None and cases.last_date and (today - cases.last_date).days > 365)
        local21 = _cases_in_window(cases, 21) if ever else (0.0 if latest_any else None)
        local42 = _cases_in_window(cases, 42) if ever else (0.0 if latest_any else None)
        if end_date:
            local21 = local42 = 0.0
        elif ever and cases.last_date and (today - cases.last_date).days > th["windows"]["stale_data_days"]:
            local21 = local42 = None  # no current data: recent activity is unknown, not zero
        if ever and imported and not _has_local(session, region):
            local21 = local42 = 0.0  # only imported cases are known: they are not local transmission
        zero = session.scalars(select(Observation).where(Observation.region_id == region.id, Observation.metric == "cases",
                                                        Observation.value_type == "incident", Observation.value == 0, Observation.as_of >= start,
                                                        Observation.validation_status.in_(PUBLISHABLE)).order_by(Observation.as_of.desc())).first()
        days_since = _days_since_increase(cases, today) if ever else None
        if zero and zero.period_start and days_since is not None:
            days_since = max(days_since, (today - zero.period_start).days)
        data_as_of = max([d for d in [cases.last_date, latest_any.as_of if latest_any else None, zero.as_of if zero else None,
                                      end_date] if d], default=None)
        new21, new42 = _new_admin1(region, first_dates, today, g)
        connected = _connected_sources(region, graph, active_units, by_code, th, g) if (not ever or (local21 or 0) == 0 or historical) else []
        sq = _surveillance(session, region, out, today)
        clusters = _independent_signal_origins(session, region)
        x = SeverityInputs(
            region_code=region.code, today=today, data_as_of=data_as_of, ever_confirmed=ever and not historical,
            local_cases_21d=local21, local_cases_42d=local42, days_since_last_increase=days_since,
            outbreak_end_declared_on=end_date, imported_case_dates=sorted(set(imported)),
            p_rt_above_1=out.rt.p_above_one if out and out.rt and not out.rt.insufficient else None,
            rt_median=out.rt.median if out and out.rt and not out.rt.insufficient else None,
            new_admin1_21d=new21, new_admin1_42d=new42, independent_signal_origins=clusters[0], signals_reviewed=clusters[1],
            connected_active_sources=sorted(connected), surveillance=sq,
            model_disagreement=bool(out and (out.model_comparison.get("substantial_disagreement") or
                                            ((out.burden_headline.get("disagreement") or {}).get("substantial")))),
            burden_upper_90=out.burden_headline.get("upper_90") if out else None,
            data_from_text_extraction=bool(cases.points and cases.points[-1].source_key in TEXT_EXTRACTED),
            historical_last_report=cases.last_date if historical else None,
        )
        if region.level == 0:
            x.exported_case_dates = _exported_case_dates(session, region)
            x.transit_cases = _transit_cases(session, region)
        res = classify(x, th)
        sa = SeverityAssessment(region_id=region.id, data_as_of=data_as_of, status=res.status.value, level=res.level,
                                confidence=res.confidence.value, underestimation_risk=res.underestimation_risk,
                                triggers=json.loads(json.dumps(res.triggers, default=str)),
                                explanation=res.explanation, surveillance=sq | {"confidence_reasons": res.confidence_reasons},
                                model_version=SEVERITY_VERSION)
        session.add(sa)
        session.flush()
        results.append(sa)
        _change_alerts(session, region, sa, previous.get(region.id), res)
    return results


def _exported_case_dates(session: Session, origin: Region) -> list[date]:
    """Dates of confirmed cases reported by other countries with travel from ``origin``."""
    q = (select(Observation).where(Observation.transmission == "imported", Observation.metric == "cases",
                                   Observation.validation_status.in_(PUBLISHABLE)))
    return sorted({o.as_of for o in session.scalars(q) if (o.attributes or {}).get("origin_iso3") == origin.iso3})


def _transit_cases(session: Session, through: Region) -> list[tuple[date, str]]:
    """(travel date, country of diagnosis) of confirmed cases reported elsewhere that travelled through ``through``.

    Several sources may describe the same case: reports from one country of
    diagnosis with travel dates within a week of each other count once.
    """
    q = (select(Observation, Region).join(Region, Observation.region_id == Region.id)
         .where(Observation.transmission == "imported", Observation.metric == "cases",
                Observation.validation_status.in_(PUBLISHABLE), Region.iso3 != through.iso3))
    found: dict[str, list[date]] = {}
    for o, r in session.execute(q):
        a = o.attributes or {}
        if through.iso3 not in (a.get("transit_iso3") or []):
            continue
        when = date.fromisoformat(a["travel_date"]) if a.get("travel_date") else o.as_of
        dates = found.setdefault(r.name, [])
        if all(abs((when - d).days) > 7 for d in dates):
            dates.append(when)
    return sorted((d, name) for name, dates in found.items() for d in dates)


def _connected_sources(region: Region, graph, active_units: dict, by_code: dict, th: dict, g) -> list[str]:
    """Active areas directly connected to this unit (for a country: to any of its admin-1 units)."""
    own = {region.code}
    if region.level == 0:
        own |= {n for n in graph.nodes if g.country_of(n) == region.code}
    out = set()
    for node in own:
        if node not in graph:
            continue
        for nb in graph.neighbors(node):
            if nb in own or g.country_of(nb) == g.country_of(region.code) and region.level == 0:
                continue
            if active_units.get(nb, 0) >= th["watch"]["connectivity_min_source_cases_21d"] and \
                    graph[node][nb]["weight"] >= th["watch"]["connectivity_min_edge_weight"]:
                out.add(by_code[nb].name if nb in by_code else nb)
    return sorted(out)


def _in_africa(region: Region) -> bool:
    lat, lon = region.centroid_lat, region.centroid_lon
    return lat is not None and -36 <= lat <= 38 and -20 <= lon <= 55


def _has_local(session: Session, region: Region) -> bool:
    """True if total reported cases exceed the imported subset."""
    tot = series_for(session, region)
    imp = build_cumulative(_rows(session, [region.id], "cases", "confirmed", transmission="imported"))
    return bool(tot.last_value and (tot.last_value - (imp.last_value or 0)) > 0)


def _first_confirmed_admin1(session: Session, today: date) -> dict[str, date]:
    """First confirmed-case date per admin-1 unit within each country's current outbreak."""
    out: dict[str, date] = {}
    active_ids = [o.id for o in (active_outbreak(session, iso3, today) for iso3 in
                                 {r for r in session.scalars(select(Outbreak.primary_iso3))}) if o]
    q = (select(Observation, Region).join(Region, Observation.region_id == Region.id)
         .where(Observation.metric == "cases", Observation.case_class == "confirmed", Observation.value > 0,
                Observation.value_type == "cumulative", Observation.validation_status.in_(PUBLISHABLE), Region.level >= 1,
                Observation.outbreak_id.in_(active_ids or [-1])))
    g = load_gazetteer()
    for o, r in session.execute(q):
        code = r.code if r.level == 1 else g.parents.get(r.code)
        if code and (code not in out or o.as_of < out[code]):
            out[code] = o.as_of
    return out


def _new_admin1(region: Region, first: dict[str, date], today: date, g) -> tuple[int, int]:
    if region.level != 0:
        return 0, 0
    mine = [d for code, d in first.items() if g.country_of(code) == region.code]
    if len(mine) <= 1:
        return 0, 0
    earliest = min(mine)
    later = [d for d in mine if d > earliest]
    return sum((today - d).days <= 21 for d in later), sum((today - d).days <= 42 for d in later)


def _transport_graph(session: Session):
    nodes = {n.id: n.key for n in session.scalars(select(TransportNode))}
    edges = [EdgeSpec(e.key, nodes[e.from_node_id], nodes[e.to_node_id], e.mode, e.service_status, e.physical_status,
                      e.verification, e.cross_border, e.corridor) for e in session.scalars(select(TransportEdge))]
    return build_graph(edges, "partial")


def _surveillance(session: Session, region: Region, out: RegionModelOutput | None, today: date) -> dict:
    contacts = _latest_obs(session, region.id, "contacts_seen")
    community = _latest_obs(session, region.id, "community_deaths")
    asc = None
    if out:
        db = next((b for b in out.burden if b.method == "deaths_backcalculation" and not b.insufficient), None)
        asc = db.ascertainment if db else None
    suspected = series_for(session, region, "cases", "suspected") if out else None
    cases = series_for(session, region) if out else None
    x = SurveillanceInputs(
        today=today, data_as_of=out.data_as_of if out else None,
        mean_reporting_interval_days=(out.weekly.get("mean_recent_reporting_interval_days") if out else None),
        contacts_seen=contacts.value if contacts else None,
        contacts_listed=(contacts.attributes or {}).get("denominator") if contacts else None,
        community_deaths=community.value if community else None,
        deaths_denominator=(community.attributes or {}).get("denominator") if community else None,
        ascertainment_median=asc["median"] if asc else None,
        source_discrepancies=len(cases.discrepancies) if cases else 0, downward_revisions=len(cases.revisions) if cases else 0,
        suspected_cases=suspected.last_value if suspected and suspected.points else None,
        confirmed_cases=cases.last_value if cases else None,
    )
    return assess(x)


def _independent_signal_origins(session: Session, region: Region) -> tuple[int, bool]:
    from ..db.models import SignalCluster

    g = load_gazetteer()
    best, reviewed = 0, False
    for cl in session.scalars(select(SignalCluster).where(SignalCluster.region_id.is_not(None),
                                                          SignalCluster.status != "reviewed_not_credible")):
        reg = session.get(Region, cl.region_id)
        if reg is None:
            continue
        unit = reg.code
        if unit != region.code and g.country_of(unit) != region.code:
            continue
        if cl.assessment not in ("Possible emerging outbreak signal.", "Independent reports suggest official reporting may be incomplete."):
            continue
        if cl.n_independent_origins > best:
            best, reviewed = cl.n_independent_origins, cl.status == "reviewed_credible"
    return best, reviewed


def _latest_assessments(session: Session) -> list[SeverityAssessment]:
    latest: dict[int, SeverityAssessment] = {}
    for a in session.scalars(select(SeverityAssessment).order_by(SeverityAssessment.assessed_at)):
        latest[a.region_id] = a
    return list(latest.values())


def _change_alerts(session: Session, region: Region, new: SeverityAssessment, old: SeverityAssessment | None, res) -> None:
    lvl_old = old.level if old else None
    if old is not None and new.level == lvl_old and new.status == old.status:
        return
    if old is None and (new.level or 0) < 2:
        return
    kind = "severity_change"
    msg = f"Severity for {region.name}: {res.level_name}"
    if old is not None:
        msg += f" (previously {'level ' + str(lvl_old) if lvl_old is not None else old.status.replace('_', ' ')})"
    codes = {t["code"] for t in res.triggers}
    if "lab_confirmed_expansion" in codes:
        kind, msg = "lab_confirmed_expansion", f"Laboratory-confirmed geographic expansion: {region.name}. " + msg
    if "imported_case" in codes:
        kind = "imported_case"
    relies_unofficial = codes <= {"unverified_signals", "connectivity"} and bool(codes)
    key = f"severity:{region.code}:{new.status}:{new.level}:{new.data_as_of}"
    if session.scalar(select(Alert).where(Alert.dedupe_key == key)):
        return
    high_impact = (new.level or 0) >= 3
    a = Alert(region_id=region.id, kind=kind, message=msg, severity_level=new.level, confidence=new.confidence,
              evidence={"triggers": new.triggers, "explanation": new.explanation}, relies_on_unofficial=relies_unofficial,
              review_status="not_required" if not relies_unofficial else "pending", published=not relies_unofficial,
              dedupe_key=key)
    if a.published:
        from ..db.base import utcnow

        a.published_at = utcnow()
    session.add(a)
    session.flush()
    if relies_unofficial or (high_impact and new.confidence == Confidence.LOW.value):
        enqueue(session, "alert", a.id, "major change alert" + (" relying on unofficial evidence" if relies_unofficial else " with low confidence"),
                priority=1)
