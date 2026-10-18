"""Helpers that create SYNTHETIC records directly in the test database."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from ebolawatch.db.models import Document, Observation, Outbreak, Region, Source
from ebolawatch.domain.enums import SourceCategory
from ebolawatch.sources.base import FetchedItem


def source(session, key: str = "test_official", category: SourceCategory = SourceCategory.OFFICIAL_NATIONAL) -> Source:
    s = session.scalar(select(Source).where(Source.key == key))
    if s is None:
        s = Source(key=key, name=f"SYNTHETIC {key}", category=category.value, access_method="test", status="ok", attribution=f"SYNTHETIC {key}")
        session.add(s)
        session.flush()
    return s


def region(session, code: str) -> Region:
    return session.scalar(select(Region).where(Region.code == code))


def outbreak(session, iso3: str, declared: date, pathogen: str = "BDBV", ended: date | None = None, key: str | None = None) -> Outbreak:
    ob = Outbreak(key=key or f"TEST-{iso3}-{declared}", name=f"SYNTHETIC {iso3}", pathogen=pathogen, primary_iso3=iso3,
                  declared_on=declared, ended_on=ended, is_synthetic=True)
    session.add(ob)
    session.flush()
    return ob


def add_series(session, code: str, start: date, cumulative: list[float], *, metric="cases", case_class="confirmed",
               step_days=7, outbreak_id=None, src=None, status="verified", transmission="all") -> list[Observation]:
    src = src or source(session)
    reg = region(session, code)
    out = []
    for i, v in enumerate(cumulative):
        d = start + timedelta(days=step_days * i)
        o = Observation(region_id=reg.id, metric=metric, case_class=case_class, value_type="cumulative", transmission=transmission,
                        as_of=d, value=float(v), source_id=src.id, published_at=datetime(d.year, d.month, d.day, tzinfo=UTC),
                        extraction_method="structured", validation_status=status, outbreak_id=outbreak_id, is_synthetic=True,
                        citation="SYNTHETIC test data")
        session.add(o)
        out.append(o)
    session.flush()
    return out


def post(external_id: str, text: str, published: datetime, author: str | None = None, platform: str = "x",
         language: str | None = None, meta: dict | None = None) -> FetchedItem:
    return FetchedItem(external_id=external_id, url=f"https://example.invalid/{external_id}", title=None, published_at=published,
                       text=text, platform=platform, author_id=author, language=language, meta=meta or {}, is_synthetic=True)


def doc_count(session) -> int:
    return len(list(session.scalars(select(Document))))
