"""WHO Disease Outbreak News (public JSON API used by who.int).

Items are official bulletins. Figures are machine-extracted from the narrative
with :mod:`ebolawatch.parsing.who_don` and routed through validation; the
supporting sentence is kept as a quote with the DON identifier for citation.
"""

from __future__ import annotations

from datetime import date, datetime

from ..config import Settings
from ..domain.enums import ConnectorStatus, SourceCategory
from ..nlp.gazetteer import load_gazetteer
from ..parsing.who_don import extract
from ..safety.untrusted import sanitize
from .base import Connector, ConnectorResult, FetchedItem, SourceInfo
from .http import HttpClient, SourceUnavailable

API = "https://www.who.int/api/news/diseaseoutbreaknews"
ITEM_URL = "https://www.who.int/emergencies/disease-outbreak-news/item/{slug}"
FILTER = (
    "contains(Title,'Ebola') or contains(Title,'Bundibugyo') or contains(Title,'Sudan virus') "
    "or contains(Title,'ebolavirus') or contains(Title,'Taï Forest')"
)
TEXT_FIELDS = ("Summary", "Overview", "Epidemiology")


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


class WhoDonConnector(Connector):
    info = SourceInfo(
        key="who_don",
        name="WHO Disease Outbreak News",
        institution="World Health Organization",
        category=SourceCategory.OFFICIAL_INTERNATIONAL,
        access_method="public JSON API (who.int/api/news/diseaseoutbreaknews)",
        homepage="https://www.who.int/emergencies/disease-outbreak-news",
        license="© WHO. Reproduced extracts with attribution for non-commercial public-health use.",
        terms_note="Only short supporting quotes and extracted figures are stored, with links to the original bulletin.",
        attribution="World Health Organization, Disease Outbreak News",
    )

    def __init__(self, page_size: int = 50, max_items: int = 400):
        self.page_size = page_size
        self.max_items = max_items

    def fetch(self, client: HttpClient, settings: Settings, since: datetime | None = None) -> ConnectorResult:
        g = load_gazetteer(str(settings.data_dir))
        items: list[FetchedItem] = []
        skip = 0
        try:
            while skip < self.max_items:
                params = {
                    "$top": str(self.page_size),
                    "$skip": str(skip),
                    "$orderby": "PublicationDateAndTime desc",
                    "$filter": FILTER,
                }
                data = client.get_json(API, params=params)
                rows = data.get("value", []) if isinstance(data, dict) else []
                if not rows:
                    break
                stop = False
                for row in rows:
                    item = self._to_item(row, g)
                    if item is None:
                        continue
                    modified = _parse_dt(row.get("LastModified")) or item.published_at
                    if since and modified and modified < since:
                        stop = True
                        break
                    items.append(item)
                if stop or len(rows) < self.page_size:
                    break
                skip += self.page_size
        except SourceUnavailable as e:
            status = ConnectorStatus.PARTIAL if items else ConnectorStatus.UNAVAILABLE
            return ConnectorResult(status, items, str(e))
        return ConnectorResult(ConnectorStatus.OK, items, f"{len(items)} bulletins retrieved")

    def _to_item(self, row: dict, g) -> FetchedItem | None:
        title = sanitize(row.get("Title") or row.get("OverrideTitle") or "").text
        don_id = row.get("DonId") or row.get("Id")
        if not don_id or not title:
            return None
        published = _parse_dt(row.get("PublicationDateAndTime")) or _parse_dt(row.get("PublicationDate"))
        parts = []
        flags: set[str] = set()
        for f in TEXT_FIELDS:
            st = sanitize(row.get(f) or "", is_html=True)
            if st.text:
                parts.append(st.text)
                flags.update(st.flags)
        text = "\n\n".join(parts)
        pub_date = published.date() if published else date.today()
        extraction = extract(title, text, pub_date, g)
        for c in extraction.candidates:
            c.notes.append(f"WHO DON {don_id}")
        slug = row.get("UrlName") or don_id
        return FetchedItem(
            external_id=str(don_id),
            url=ITEM_URL.format(slug=slug),
            title=title,
            published_at=published,
            text=text,
            language="en",
            meta={
                "don_id": don_id,
                "last_modified": row.get("LastModified"),
                "stated_cfr_percent": extraction.stated_cfr,
                "countries_in_title": extraction.primary_countries,
                "safety_flags": sorted(flags),
            },
            observations=extraction.candidates,
            is_official=True,
            content_version=row.get("LastModified"),
        )
