"""ECDC page on the outbreak: official figures between WHO bulletins.

WHO Disease Outbreak News appear about once a fortnight; ECDC updates its page
every weekday with the totals reported by the Democratic Republic of the Congo
and a provincial breakdown. The page is public (robots.txt allows it) and
licensed CC BY 4.0.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from ..config import Settings
from ..domain.enums import ConnectorStatus, SourceCategory
from ..nlp.gazetteer import load_gazetteer
from ..parsing.ecdc import UPDATED_RE, extract, paragraphs
from ..safety.untrusted import normalize, sanitize, strip_markup
from .base import Connector, ConnectorResult, FetchedItem, SourceInfo
from .http import HttpClient, SourceUnavailable

PAGE = "https://www.ecdc.europa.eu/en/ebola-outbreak-democratic-republic-congo-and-uganda"
MAIN_RE = re.compile(r"(?is)<main\b.*?</main>")
TIME_RE = re.compile(r"\bat (\d{1,2})[:.](\d{2})\b")
END_RE = re.compile(r"EU/EEA|\bmodelling\b", re.I)  # the European risk assessment follows the situation summary
MAX_PARAGRAPHS = 20


class EcdcConnector(Connector):
    info = SourceInfo(
        key="ecdc",
        name="ECDC outbreak update",
        institution="European Centre for Disease Prevention and Control",
        category=SourceCategory.OFFICIAL_INTERNATIONAL,
        access_method="public web page, updated every weekday (HTML)",
        homepage=PAGE,
        license="© ECDC, CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/). Figures are extracted from the page text "
                "and reformatted as data.",
        terms_note="Only the situation summary is stored, with a link to the page; statements the page attributes to "
                   "media reports are not extracted.",
        attribution="European Centre for Disease Prevention and Control (ECDC), Ebola disease outbreak page",
    )

    def fetch(self, client: HttpClient, settings: Settings, since: datetime | None = None) -> ConnectorResult:
        try:
            r = client.get(PAGE, headers={"Accept": "text/html"})
        except SourceUnavailable as e:
            return ConnectorResult(ConnectorStatus.UNAVAILABLE, [], str(e))
        item = self.parse(r.text, date.today())
        if item is None:
            return ConnectorResult(ConnectorStatus.PARTIAL, [], "page layout not recognised: no update date found")
        n = len(item.observations)
        return ConnectorResult(ConnectorStatus.OK if n else ConnectorStatus.PARTIAL, [item],
                               f"update of {item.published_at:%Y-%m-%d %H:%M}: {n} figures extracted")

    def parse(self, html: str, today: date) -> FetchedItem | None:
        main = MAIN_RE.search(html)
        # line breaks in the HTML source are not paragraph breaks; the page is
        # cut down to the situation summary before the length-capped sanitising
        paras = paragraphs(normalize(strip_markup(re.sub(r"\s+", " ", main.group(0) if main else html))))
        start = next((i for i, p in enumerate(paras) if UPDATED_RE.search(p)), None)
        if start is None:
            return None
        summary: list[str] = []
        for p in paras[start:start + MAX_PARAGRAPHS]:
            if END_RE.search(p):
                break
            summary.append(p)
        st = sanitize("\n".join(summary))
        text = st.text
        ex = extract(text, today, load_gazetteer())
        if ex.updated_on is None:
            return None
        t = TIME_RE.search(paras[start])
        published = datetime.combine(ex.updated_on, time(int(t.group(1)), int(t.group(2))) if t else time(12),
                                     tzinfo=ZoneInfo("Europe/Stockholm"))
        stamp = published.strftime("%Y-%m-%dT%H:%M")
        return FetchedItem(
            external_id=f"update {stamp}",
            url=PAGE,
            title=f"ECDC: Ebola disease outbreak in the Democratic Republic of the Congo (update {published:%d %B %Y})",
            published_at=published,
            text=text,
            language="en",
            meta={"pathogen": "BDBV" if "bundibugyo" in text.lower() else None, "countries_in_title": ["COD"],
                  "data_as_of": ex.as_of.isoformat() if ex.as_of else None, "skipped": ex.skipped[:10],
                  "safety_flags": list(st.flags)},
            observations=ex.candidates,
            is_official=True,
            content_version=stamp,
        )
