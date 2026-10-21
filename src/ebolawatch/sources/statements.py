"""Official statements transcribed into ``data/official/statements.yaml``.

Ministries of health and WHO regional offices announce confirmed cases in
press releases and briefings, often a day or more before ECDC or a WHO Disease
Outbreak News restates them. Each entry in the file records one such statement:
who made it, a link, a verbatim quote, and the figures it gives. The file is
public and versioned with the code, so every figure can be traced to the commit
that added it; a corrected figure is a new entry (a later vintage), never an
edit that hides the earlier one.

Imported cases may carry travel details as attributes:
``origin_iso3`` (where infection most likely occurred), ``transit_iso3``
(countries travelled through) and ``travel_date``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime

import yaml

from ..config import Settings
from ..domain.enums import CaseClass, ConnectorStatus, Metric, SourceCategory, TransmissionType, ValueType
from .base import Connector, ConnectorResult, FetchedItem, ObservationCandidate, SourceInfo
from .http import HttpClient

FILE = "official/statements.yaml"
REQUIRED = ("id", "published_on", "authority", "title", "url", "citation", "observations")
ATTRIBUTES = {"origin_iso3", "transit_iso3", "travel_date"}


class StatementError(ValueError):
    pass


def _date(v, what: str) -> date:
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v))
    except ValueError as e:
        raise StatementError(f"{what}: not a date ({v!r})") from e


def _attributes(raw: dict | None) -> dict:
    raw = raw or {}
    unknown = set(raw) - ATTRIBUTES
    if unknown:
        raise StatementError(f"unknown attributes: {', '.join(sorted(unknown))}")
    out: dict = {}
    if raw.get("origin_iso3"):
        out["origin_iso3"] = str(raw["origin_iso3"]).upper()
    if raw.get("transit_iso3"):
        out["transit_iso3"] = [str(c).upper() for c in raw["transit_iso3"]]
    if raw.get("travel_date"):
        out["travel_date"] = _date(raw["travel_date"], "travel_date").isoformat()
    return out


def parse_statement(s: dict) -> FetchedItem:
    missing = [k for k in REQUIRED if not s.get(k)]
    if missing:
        raise StatementError(f"missing {', '.join(missing)}")
    published = _date(s["published_on"], "published_on")
    references = [str(r) for r in s.get("references") or []]
    obs = []
    for i, o in enumerate(s["observations"], start=1):
        try:
            value = float(o["value"])
            if value < 0:
                raise StatementError("negative value")
            obs.append(ObservationCandidate(
                region_ref=str(o["region"]).strip(), metric=Metric(o["metric"]),
                case_class=CaseClass(o.get("case_class", "confirmed")), value_type=ValueType(o.get("value_type", "cumulative")),
                as_of=_date(o["as_of"], "as_of"), value=value, transmission=TransmissionType(o.get("transmission", "all")),
                quote=o.get("quote") or s.get("quote"), extraction_method="transcribed", confidence="high",
                notes=[str(n) for n in o.get("notes") or []] + [f"see also {r}" for r in references],
                attributes=_attributes(o.get("attributes")),
            ))
        except (KeyError, ValueError, TypeError) as e:
            raise StatementError(f"observation {i}: {e}") from e
    version = hashlib.sha256(json.dumps(s, sort_keys=True, default=str).encode()).hexdigest()[:16]
    text = "\n".join(t for t in [s.get("quote"), *(s.get("context") or [])] if t)
    return FetchedItem(
        external_id=str(s["id"]), url=str(s["url"]), title=str(s["title"]),
        published_at=datetime.combine(published, datetime.min.time(), tzinfo=UTC), text=text or None, language="en",
        meta={"authority": s["authority"], "citation": s["citation"], "pathogen": s.get("pathogen"), "references": references},
        observations=obs, is_official=True, content_version=version,
    )


class OfficialStatementsConnector(Connector):
    info = SourceInfo(
        key="official_statements",
        name="Official statements (transcribed)",
        institution=None,
        category=SourceCategory.OFFICIAL_NATIONAL,
        access_method="statements by ministries of health and WHO offices, transcribed into data/official/statements.yaml",
        homepage="https://github.com/openmissionofhope/ebola-watch/blob/main/data/official/statements.yaml",
        license="Figures and short quotes from the cited statements, with links; see each entry.",
        terms_note="Each entry names the authority, links to the statement and quotes it; corrections are added as new entries.",
        attribution="Official statement",
    )

    def fetch(self, client: HttpClient, settings: Settings, since: datetime | None = None) -> ConnectorResult:
        path = settings.data_dir / FILE
        if not path.exists():
            return ConnectorResult(ConnectorStatus.OK, [], "no statements file")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        items, errors = [], []
        for s in data.get("statements") or []:
            try:
                items.append(parse_statement(s))
            except StatementError as e:
                errors.append(f"{s.get('id', '?')}: {e}")
        msg = f"{len(items)} statements" + (f"; rejected: {'; '.join(errors)}" if errors else "")
        return ConnectorResult(ConnectorStatus.PARTIAL if errors else ConnectorStatus.OK, items, msg)
