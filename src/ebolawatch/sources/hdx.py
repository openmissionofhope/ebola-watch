"""OCHA Humanitarian Data Exchange (CKAN API).

``hdx_cod_ebola`` reads the OCHA DRC dataset "République démocratique du Congo :
Cas et Décès d'Ebola" (CC BY), which consolidates national and health-zone
figures transcribed from the government (INSP/COUSP) situation reports by
INRB-UMIE. The upstream producers ask to be contacted before epidemiological
data are used in analyses ahead of their own publication, so this connector
requires explicit operator acknowledgement (see docs/DATA_SOURCES.md).

Health-zone rows are used for modelling and expansion analysis; public outputs
aggregate them to province level under the publication policy.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime

from ..config import Settings
from ..domain.enums import CaseClass, ConnectorStatus, Metric, SourceCategory, ValueType
from ..nlp.gazetteer import load_gazetteer
from .base import Connector, ConnectorResult, FetchedItem, ObservationCandidate, SourceInfo
from .http import HttpClient, SourceUnavailable

CKAN = "https://data.humdata.org/api/3/action/package_show"
DATASET = "republique-democratique-du-congo-cas-et-deces-d-ebola"

MEASURES = {"cases": Metric.CASES, "deaths": Metric.DEATHS, "contacts": Metric.CONTACTS_LISTED}
CLASSES = {"confirmed": CaseClass.CONFIRMED, "suspected": CaseClass.SUSPECTED, "probable": CaseClass.PROBABLE, "": CaseClass.NOT_APPLICABLE}


class HdxCodEbolaConnector(Connector):
    info = SourceInfo(
        key="hdx_cod_ebola",
        name="HDX: DRC Ebola cases and deaths (national and health-zone)",
        institution="OCHA DRC / COUSP-RDC; transcription by INRB-UMIE",
        category=SourceCategory.OFFICIAL_NATIONAL,
        access_method="HDX CKAN API + CSV resource",
        homepage=f"https://data.humdata.org/dataset/{DATASET}",
        license="CC BY 4.0 (HDX); upstream repository MIT with a pre-publication contact request",
        terms_note=(
            "Upstream data producers (INRB/INSP) request contact before using the epidemiological data "
            "prior to their publication. Enable only after reviewing and honouring that request."
        ),
        attribution="COUSP-RDC / INSP situation reports; INRB-UMIE BDBV2026-Data; OCHA DRC via HDX",
        requires_acknowledgement=True,
    )

    def fetch(self, client: HttpClient, settings: Settings, since: datetime | None = None) -> ConnectorResult:
        g = load_gazetteer(str(settings.data_dir))
        try:
            pkg = client.get_json(CKAN, params={"id": DATASET})["result"]
            res = next((r for r in pkg["resources"] if (r.get("format") or "").upper() == "CSV"), None)
            if res is None:
                return ConnectorResult(ConnectorStatus.UNAVAILABLE, [], "dataset has no CSV resource")
            raw = client.get(res["url"]).text
        except (SourceUnavailable, KeyError) as e:
            return ConnectorResult(ConnectorStatus.UNAVAILABLE, [], f"HDX unavailable: {e}")

        modified = res.get("last_modified") or pkg.get("metadata_modified")
        candidates, unmatched = parse_rows(raw, g)
        item = FetchedItem(
            external_id=f"{DATASET}:{modified}",
            url=f"https://data.humdata.org/dataset/{DATASET}",
            title=pkg.get("title"),
            published_at=_dt(modified),
            text=None,
            meta={"resource_url": res["url"], "unmatched_locations": sorted(unmatched)[:50], "rows": len(candidates)},
            observations=candidates,
            is_official=True,
            content_version=modified,
        )
        msg = f"{len(candidates)} observations parsed"
        if unmatched:
            msg += f"; {len(unmatched)} location names not matched to the health-zone gazetteer (skipped)"
        return ConnectorResult(ConnectorStatus.OK, [item], msg)


def _dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_rows(raw: str, g) -> tuple[list[ObservationCandidate], set[str]]:
    out: list[ObservationCandidate] = []
    unmatched: set[str] = set()
    reader = csv.DictReader(io.StringIO(raw.lstrip("﻿")))
    for row in reader:
        metric = MEASURES.get((row.get("measure") or "").strip())
        if metric is None or (row.get("time_period") or "").strip() != "cumulative":
            continue
        try:
            value = float(row["value"])
            as_of = date.fromisoformat(row["reference_date"][:10])
        except (KeyError, ValueError):
            continue
        cls = CLASSES.get((row.get("case_classification") or "").strip(), None)
        if cls is None:
            continue
        level = (row.get("location_level") or "").strip()
        if level == "0":
            region = (row.get("location_country") or "COD").strip()
        elif level == "3":
            region = None
            for name in (row.get("location_name_source"), row.get("location_name")):
                if name and (region := g.health_zone(name.strip())):
                    break
            if region is None:
                unmatched.add((row.get("location_name") or "?").strip())
                continue
        else:
            continue
        notes = [f"source: {row.get('source')}"] if row.get("source") else []
        if row.get("data_quality_flag"):
            notes.append(f"quality flag: {row['data_quality_flag']}")
        if row.get("notes"):
            notes.append(row["notes"][:300])
        out.append(ObservationCandidate(
            region_ref=region, metric=metric, case_class=cls, value_type=ValueType.CUMULATIVE,
            as_of=as_of, value=value, extraction_method="structured", confidence="high", notes=notes,
            region_level_hint=0 if level == "0" else 2,
        ))
    return out, unmatched
