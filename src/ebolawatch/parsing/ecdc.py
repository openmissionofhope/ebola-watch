"""Extraction of official figures from the ECDC outbreak page.

ECDC updates its page on the outbreak every weekday. It restates the national
totals reported by the Democratic Republic of the Congo, gives one sentence per
affected province, and summarises reports from other countries. The page is
rewritten in place, so each update is stored as a separate document.

Rules, deliberately conservative:

* national totals need a case-definition category ("confirmed") and a date
  (the "data up until" date when given, otherwise the "As of" date);
* provincial sentences do not repeat "confirmed": they are published
  automatically only when they add up exactly to the national totals on the
  same page, which shows they are the complete confirmed breakdown; otherwise
  they are held for review;
* cases in other countries are taken only from explicit ordinals ("a second
  case was reported") in a paragraph about that country, as lower bounds;
* nothing is extracted from a paragraph that relays media reports, and counts
  introduced as "new" or "additional" are increments, not totals.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from ..domain.enums import CaseClass, Metric, TransmissionType, ValueType
from ..nlp.gazetteer import Gazetteer
from ..sources.base import ObservationCandidate
from .textnum import NUM_PATTERN, ORDINAL_WORDS, find_dates, parse_number, sentences
from .who_don import CASES_CUMUL_RE, INCREMENT_CUES, MEDEVAC_RE

N = NUM_PATTERN
COUNTRY = "COD"
UPDATED_RE = re.compile(r"\blast updated on\b", re.I)
AS_OF_RE = re.compile(r"\bas of\b", re.I)
DATA_UNTIL_RE = re.compile(r"\bdata (?:up )?(?:until|to)\b", re.I)
DEATHS_RE = re.compile(rf"(?P<n>{N})\s+(?:related\s+|associated\s+)?deaths?\b", re.I)
CASES_RE = re.compile(rf"(?P<n>{N})\s+(?:confirmed\s+)?cases?\b", re.I)
OVERALL_RE = re.compile(rf"(?P<hz>{N})\s+of\s+(?P<total>{N})\s+health zones\s+(?:are\s+|have been\s+)?(?:currently\s+)?"
                        rf"affected\s+(?:across|in)\s+(?P<prov>{N})\s+provinces", re.I)
MEDIA_RE = re.compile(r"\b(?:media|press)\s+reports?\b|\baccording to (?:the )?(?:media|press)\b|\bnot (?:yet )?(?:been )?officially\b", re.I)
_ORDINAL_ALT = "|".join(w for w in ORDINAL_WORDS if w.isascii())
ORDINAL_CASE_RE = re.compile(rf"\b(?P<ord>{_ORDINAL_ALT})\s+(?:laboratory[- ])?(?:confirmed\s+)?(?P<imported>imported\s+)?"
                             rf"(?:(?:Ebola|Bundibugyo|virus|disease|BVD|EVD)\s+){{0,4}}case\b", re.I)


@dataclass
class EcdcExtraction:
    candidates: list[ObservationCandidate] = field(default_factory=list)
    updated_on: date | None = None
    as_of: date | None = None
    skipped: list[str] = field(default_factory=list)


def _quote(s: str, limit: int = 400) -> str:
    s = " ".join(s.split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _first(rx: re.Pattern, s: str) -> int | None:
    for m in rx.finditer(s):
        if not INCREMENT_CUES.search(s[max(0, m.start() - 40): m.start()]):
            return parse_number(m.group("n"))
    return None


def _date_after(rx: re.Pattern, s: str, reference: date) -> date | None:
    m = rx.search(s)
    if not m:
        return None
    after = [d for start, _, d, _ in find_dates(s, reference) if start >= m.end()]
    return after[0] if after else None


def paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n") if p.strip()]


def extract(text: str, reference: date, g: Gazetteer) -> EcdcExtraction:
    out = EcdcExtraction()
    paras = paragraphs(text)
    for p in paras:
        if UPDATED_RE.search(p):
            out.updated_on = _date_after(UPDATED_RE, p, reference)
            break
    reference = out.updated_on or reference

    national: dict[Metric, tuple[int, str]] = {}
    provinces: dict[str, dict] = {}
    overall: tuple[int, int, int, str] | None = None
    events: list[ObservationCandidate] = []

    for p in paras:
        if MEDIA_RE.search(p):
            out.skipped.append(_quote(p, 160))
            continue
        countries = [m.code for m in g.find(p) if m.level == 0]
        foreign = next((c for c in countries if c != COUNTRY), None)
        if foreign and countries[0] != COUNTRY:
            events.extend(_country_events(p, foreign, reference))
            continue
        for _, sent in sentences(p):
            if out.as_of is None and AS_OF_RE.search(sent):
                out.as_of = _date_after(DATA_UNTIL_RE, sent, reference) or _date_after(AS_OF_RE, sent, reference)
            m = CASES_CUMUL_RE.search(sent)
            if m and not national and COUNTRY in countries and m.group("cls").lower() == "confirmed":
                national[Metric.CASES] = (parse_number(m.group("n")), sent)
                deaths = _first(DEATHS_RE, sent[m.end():])
                if deaths is not None:
                    national[Metric.DEATHS] = (deaths, sent)
                continue
            if (o := OVERALL_RE.search(sent)) and overall is None:
                overall = (parse_number(o.group("hz")), parse_number(o.group("total")), parse_number(o.group("prov")), sent)
                continue
            units = {m.code for m in g.find(sent) if m.level == 1 and g.country_of(m.code) == COUNTRY}
            if len(units) != 1:
                continue
            (unit,) = units
            cases = _first(CASES_RE, sent)
            if cases is None or unit in provinces:
                continue
            provinces[unit] = {"cases": cases, "deaths": _first(DEATHS_RE, sent), "quote": sent}

    if out.as_of is None or Metric.CASES not in national:
        out.skipped.append("national confirmed total or its date not found; nothing extracted")
        return out
    as_of = out.as_of

    def emit(region: str, metric: Metric, value: int, quote: str, confidence: str = "high", notes=None, **kw) -> None:
        out.candidates.append(ObservationCandidate(region, metric, kw.pop("case_class", CaseClass.CONFIRMED),
                                                   kw.pop("value_type", ValueType.CUMULATIVE), kw.pop("as_of", as_of), value,
                                                   quote=_quote(quote), extraction_method="text_pattern",
                                                   confidence=confidence, notes=list(notes or []), **kw))

    for metric, (value, quote) in national.items():
        emit(COUNTRY, metric, value, quote)
    if overall:
        hz, total, prov, quote = overall
        if hz is not None:
            emit(COUNTRY, Metric.AFFECTED_ADMIN2, hz, quote, attributes={"unit": "health_zone", "denominator": total})
        if prov is not None:
            emit(COUNTRY, Metric.AFFECTED_ADMIN1, prov, quote, attributes={"unit": "province"})

    if provinces:
        sum_cases = sum(v["cases"] for v in provinces.values())
        has_deaths = all(v["deaths"] is not None for v in provinces.values())
        sum_deaths = sum(v["deaths"] or 0 for v in provinces.values())
        complete = sum_cases == national[Metric.CASES][0] and (
            Metric.DEATHS not in national or (has_deaths and sum_deaths == national[Metric.DEATHS][0]))
        if complete:
            conf, notes = "high", ["provincial figures add up to the national confirmed totals on the same page"]
        else:
            conf, notes = "low", [f"provincial cases add up to {sum_cases}, not the national total "
                                  f"{national[Metric.CASES][0]}: case category not established"]
        for unit, v in provinces.items():
            emit(unit, Metric.CASES, v["cases"], v["quote"], conf, notes)
            if v["deaths"] is not None:
                emit(unit, Metric.DEATHS, v["deaths"], v["quote"], conf, notes)

    out.candidates.extend(events)
    return out


def _country_events(paragraph: str, country: str, reference: date) -> list[ObservationCandidate]:
    """Explicit ordinal case statements ("a second case was reported") in a paragraph about one country."""
    if MEDEVAC_RE.search(paragraph):
        return []
    found: list[ObservationCandidate] = []
    for _, sent in sentences(paragraph):
        for m in ORDINAL_CASE_RE.finditer(sent):
            n = ORDINAL_WORDS[m.group("ord").lower()]
            dates = find_dates(sent, reference)
            if not dates:
                continue
            when = dates[0][2]
            transmission = TransmissionType.IMPORTED if m.group("imported") else TransmissionType.ALL
            found.append(ObservationCandidate(
                country, Metric.CASES, CaseClass.CONFIRMED, ValueType.CUMULATIVE, when, n, transmission=transmission,
                quote=_quote(sent), extraction_method="text_pattern", confidence="medium",
                notes=["narrative statement; value is a lower bound (at least this many cases)"]))
    return found
