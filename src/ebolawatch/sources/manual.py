"""Manual import of official figures transcribed by reviewers (e.g. from PDF
situation reports that have no machine-readable form).

CSV columns:
    region, metric, case_class, value_type, as_of, value
optional:
    period_start, transmission, citation, url, quote, published_at, notes

Imported rows carry ``extraction_method=manual``. They are stored as
``verified`` only when the importer is a named reviewer; otherwise they enter
the review queue.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime

from ..domain.enums import CaseClass, Metric, TransmissionType, ValueType
from .base import FetchedItem, ObservationCandidate

REQUIRED = {"region", "metric", "case_class", "value_type", "as_of", "value"}


class ManualImportError(ValueError):
    pass


def parse_manual_csv(text: str, document_id: str, citation: str | None = None) -> FetchedItem:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    missing = REQUIRED - set(reader.fieldnames or [])
    if missing:
        raise ManualImportError(f"missing columns: {', '.join(sorted(missing))}")
    obs: list[ObservationCandidate] = []
    for i, row in enumerate(reader, start=2):
        try:
            value = float(row["value"])
            if value < 0:
                raise ValueError("negative value")
            c = ObservationCandidate(
                region_ref=row["region"].strip(),
                metric=Metric(row["metric"].strip()),
                case_class=CaseClass(row["case_class"].strip()),
                value_type=ValueType(row["value_type"].strip()),
                as_of=date.fromisoformat(row["as_of"].strip()),
                value=value,
                transmission=TransmissionType((row.get("transmission") or "all").strip()),
                period_start=date.fromisoformat(row["period_start"]) if row.get("period_start") else None,
                quote=(row.get("quote") or None),
                extraction_method="manual",
                confidence="high",
                notes=[n for n in [row.get("notes"), row.get("citation") or citation, row.get("url")] if n],
            )
        except (ValueError, KeyError) as e:
            raise ManualImportError(f"row {i}: {e}") from e
        obs.append(c)
    published = None
    return FetchedItem(external_id=document_id, url=None, title=citation or document_id, published_at=published,
                       text=None, observations=obs, is_official=True,
                       meta={"imported_at": datetime.now().isoformat(timespec="seconds"), "rows": len(obs)})
