"""Severity and confidence classification.

Severity (levels 0-4, or *insufficient information*) and confidence (low /
moderate / high) are computed independently. Severity is driven by evidence
of transmission, never by the country or perceived institutional quality.
A data void is reported as insufficient information, not as high severity;
when incomplete surveillance plausibly hides transmission, an explicit
*underestimation risk* flag is raised instead.

Every level carries the list of triggers that produced it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

from ..config import get_settings
from ..domain.enums import Confidence, SeverityStatus

LEVEL_NAMES = {0: "NO CURRENT EVIDENCE", 1: "WATCH", 2: "ELEVATED", 3: "HIGH", 4: "CRITICAL"}
LEVEL_DESCRIPTIONS = {
    0: "No reliable evidence of current transmission. This does not necessarily establish zero cases.",
    1: "Potential concern or weak early signals. No established outbreak, or insufficient evidence for a stronger warning.",
    2: "Credible evidence of meaningful outbreak risk, limited transmission, or significant surveillance concerns.",
    3: "Established outbreak with substantial transmission, credible geographic expansion, or clearly worsening indicators.",
    4: "Severe, sustained or rapidly expanding outbreak with high burden or substantial risk of further growth.",
}
SEVERITY_VERSION = "ew-severity-1.1.0"


@lru_cache
def load_thresholds(data_dir: str | None = None) -> dict:
    base = Path(data_dir) if data_dir else get_settings().data_dir
    return yaml.safe_load((base / "severity" / "thresholds.yaml").read_text())


@dataclass
class SeverityInputs:
    region_code: str
    today: date
    data_as_of: date | None  # latest official observation for this unit
    ever_confirmed: bool
    local_cases_21d: float | None  # confirmed cases reported in the last 21 days (None = unknown)
    local_cases_42d: float | None
    days_since_last_increase: int | None
    outbreak_end_declared_on: date | None = None
    imported_case_dates: list[date] = field(default_factory=list)
    p_rt_above_1: float | None = None
    rt_median: float | None = None
    new_admin1_21d: int = 0
    new_admin1_42d: int = 0
    independent_signal_origins: int = 0
    signals_reviewed: bool = False
    connected_active_sources: list[str] = field(default_factory=list)
    surveillance: dict = field(default_factory=dict)  # from surveillance.assess
    model_disagreement: bool = False
    burden_upper_90: float | None = None
    data_from_text_extraction: bool = False
    historical_last_report: date | None = None  # last report of an outbreak that ended long ago
    exported_case_dates: list[date] = field(default_factory=list)  # confirmed elsewhere after travel from here
    transit_cases: list[tuple[date, str]] = field(default_factory=list)  # (travel date, country of diagnosis) of cases that travelled through here


@dataclass
class SeverityResult:
    status: SeverityStatus
    level: int | None
    level_name: str
    confidence: Confidence
    underestimation_risk: bool
    triggers: list[dict]
    explanation: str
    confidence_reasons: list[str]


def classify(x: SeverityInputs, thresholds: dict | None = None) -> SeverityResult:
    t = thresholds or load_thresholds()
    w = t["windows"]
    triggers: list[dict] = []
    age = (x.today - x.data_as_of).days if x.data_as_of else None
    c21 = x.local_cases_21d or 0
    level: int | None = 0

    def trig(code: str, text: str, evidence: dict | None = None, lvl: int | None = None):
        triggers.append({"code": code, "level": lvl, "text": text, "evidence": evidence or {}})

    ended = x.outbreak_end_declared_on and (x.data_as_of is None or x.outbreak_end_declared_on >= x.data_as_of - _days(1)) and c21 == 0
    stale = x.ever_confirmed and not ended and (age is None or age > w["stale_data_days"])
    if stale:
        status = SeverityStatus.INSUFFICIENT_INFORMATION
        level = None
        trig("stale_data", f"Previously affected area with no official update for {age if age is not None else 'an unknown number of'} days; current status cannot be assessed.",
             {"data_as_of": x.data_as_of.isoformat() if x.data_as_of else None})
    else:
        status = SeverityStatus.ASSESSED
        cr, hi, el, wa = t["critical"], t["high"], t["elevated"], t["watch"]
        # CRITICAL
        if c21 >= cr["sustained_cases_21d"]:
            level = 4
            trig("sustained_high_incidence", f"{c21:,.0f} confirmed cases reported in the last 21 days (threshold {cr['sustained_cases_21d']}).", {"cases_21d": c21}, 4)
        if c21 >= cr["growth_cases_21d"] and (x.p_rt_above_1 or 0) >= cr["growth_p_rt_above_1"]:
            level = 4
            trig("rapid_growth", f"Probability that R_t of reported cases exceeds 1 is {x.p_rt_above_1:.0%} with {c21:,.0f} cases in 21 days.", {"p_rt_above_1": x.p_rt_above_1}, 4)
        if x.new_admin1_42d >= cr["expansion_new_admin1_42d"] and c21 >= cr["expansion_min_cases_21d"]:
            level = 4
            trig("rapid_expansion", f"{x.new_admin1_42d} newly affected first-level areas in 42 days with {c21:,.0f} recent cases.", {"new_admin1_42d": x.new_admin1_42d}, 4)
        # HIGH
        if level < 3:
            if c21 >= hi["cases_21d"]:
                level = 3
                trig("established_transmission", f"{c21:,.0f} confirmed cases in the last 21 days (threshold {hi['cases_21d']}).", {"cases_21d": c21}, 3)
            if x.new_admin1_21d >= hi["new_admin1_21d"] and c21 > 0:
                level = 3
                trig("lab_confirmed_expansion", "Laboratory-confirmed cases reported in a newly affected first-level area in the last 21 days.", {"new_admin1_21d": x.new_admin1_21d}, 3)
            if (x.p_rt_above_1 or 0) >= hi["p_rt_above_1"] and c21 >= hi["p_rt_min_cases_21d"]:
                level = 3
                trig("growing", f"R_t of reported cases likely above 1 (probability {x.p_rt_above_1:.0%}).", {"p_rt_above_1": x.p_rt_above_1}, 3)
        # ELEVATED
        if level < 2:
            if c21 >= el["min_local_cases_21d"]:
                level = 2
                trig("limited_transmission", f"{c21:,.0f} confirmed case(s) in the last 21 days.", {"cases_21d": c21}, 2)
            recent_imports = [d for d in x.imported_case_dates if (x.today - d).days <= el["imported_case_days"]]
            if recent_imports and c21 == 0:
                level = 2
                trig("imported_case", "Laboratory-confirmed imported case(s) in the last 21 days without evidence of sustained local transmission.",
                     {"imported_case_dates": [d.isoformat() for d in recent_imports]}, 2)
            exported = [d for d in x.exported_case_dates if (x.today - d).days <= el["imported_case_days"] * 2]
            if exported and c21 == 0:
                level = 2
                trig("exported_case_without_local_report",
                     "Laboratory-confirmed case(s) detected elsewhere after travel from this area while official local reports show "
                     "no recent cases: transmission may be going undetected.", {"exported_case_dates": [d.isoformat() for d in exported]}, 2)
            transits = sorted((d, where) for d, where in x.transit_cases if 0 <= (x.today - d).days <= el["transit_case_days"])
            if transits:
                level = 2
                latest = transits[-1][0].isoformat()
                places = ", ".join(sorted({where for _, where in transits}))
                if len(transits) == 1:
                    lead = f"A laboratory-confirmed case travelled through this country on {latest} before diagnosis in {places}"
                elif len(transits) == 2:  # each instance named
                    (d1, w1), (d2, w2) = transits
                    lead = (f"Two laboratory-confirmed cases travelled through this country in the last {el['transit_case_days']} days "
                            f"before diagnosis elsewhere: one on {d1.isoformat()} (diagnosed in {w1}) and one on {d2.isoformat()} "
                            f"(diagnosed in {w2})")
                else:
                    lead = (f"{len(transits)} laboratory-confirmed cases travelled through this country in the last "
                            f"{el['transit_case_days']} days (latest on {latest}) before diagnosis in {places}")
                trig("confirmed_case_transit", f"{lead}. This shows a route by which cases leave "
                     "the outbreak area; it is not evidence of local transmission.",
                     {"transits": [{"travel_date": d.isoformat(), "diagnosed_in": w} for d, w in transits]}, 2)
        # WATCH
        if level < 1:
            if x.ever_confirmed and not ended and (x.local_cases_42d or 0) > 0:
                level = 1
                trig("countdown", "No confirmed cases in the last 21 days, but cases within 42 days (end-of-outbreak countdown not complete).", {}, 1)
            if [d for d in x.imported_case_dates if (x.today - d).days <= wa["imported_case_days"]]:
                level = 1
                trig("recent_import", "Imported case within the last 42 days.", {}, 1)
            if x.independent_signal_origins >= wa["min_independent_signal_origins"]:
                level = 1
                trig("unverified_signals", f"{x.independent_signal_origins} independent unofficial reports of a possible outbreak"
                     + ("" if x.signals_reviewed else " (pending human review)") + "; not confirmed.", {}, 1)
            if x.connected_active_sources:
                level = 1
                trig("connectivity", "Broad transport connectivity to an area with active transmission ("
                     + ", ".join(x.connected_active_sources) + "). This reflects vulnerability, not evidence of transmission.", {}, 1)
        if ended and level == 0:
            trig("outbreak_declared_over", f"End of outbreak declared on {x.outbreak_end_declared_on}.", {}, 0)
        if x.historical_last_report and level == 0:
            trig("historical_outbreak", f"Previous outbreak; last official report {x.historical_last_report}.", {}, 0)

    # Confidence (independent of severity)
    reasons: list[str] = []
    score = 3
    if age is None:
        score = 1
        reasons.append("no official data for this area")
    elif age > 14:
        score = min(score, 1)
        reasons.append(f"latest official data are {age} days old")
    elif age > 7:
        score = min(score, 2)
        reasons.append(f"latest official data are {age} days old")
    sq = x.surveillance or {}
    concerns = [c for c in sq.get("concerns", [])]
    if concerns:
        score = min(score, 2 if len(concerns) == 1 else 1)
        reasons.extend(concerns)
    if x.model_disagreement:
        score = min(score, 1)
        reasons.append("models disagree substantially")
    if x.data_from_text_extraction:
        score = min(score, 2)
        reasons.append("figures machine-extracted from narrative bulletins")
    if level == 1 and any(tg["code"] == "unverified_signals" for tg in triggers):
        score = min(score, 1)
        reasons.append("level based on unofficial reports")
    if not x.ever_confirmed and age is None:
        reasons.append("absence of reports is not evidence of absence of cases")
    robust = any(tg["code"] in ("sustained_high_incidence", "established_transmission") and
                 (tg["evidence"].get("cases_21d") or 0) >= 2 * (t["critical"]["sustained_cases_21d"] if tg["code"] == "sustained_high_incidence"
                                                               else t["high"]["cases_21d"]) for tg in triggers)
    if robust and age is not None and age <= 14 and score < 2:
        score = 2
        reasons.append("level rests on official confirmed counts well above the threshold; under-reporting would raise, not lower, severity")
    confidence = {3: Confidence.HIGH, 2: Confidence.MODERATE, 1: Confidence.LOW}[max(score, 1)]

    under = bool(concerns) or (stale and x.ever_confirmed) or any(tg["code"] == "exported_case_without_local_report" for tg in triggers)
    if under:
        reasons.append("incomplete surveillance creates a credible risk that severity is underestimated")

    name = LEVEL_NAMES[level] if level is not None else "INSUFFICIENT INFORMATION"
    if status == SeverityStatus.INSUFFICIENT_INFORMATION:
        expl = "Insufficient information to assess current severity. " + triggers[0]["text"]
    else:
        main = [tg["text"] for tg in triggers if tg.get("level") == level]
        expl = f"{name}: " + " ".join(main + [LEVEL_DESCRIPTIONS[level]] if (level == 0 or not main) else main)
    return SeverityResult(status, level, name, confidence, under, triggers, expl, reasons)


def _days(n: int):
    from datetime import timedelta

    return timedelta(days=n)
