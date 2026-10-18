"""News and humanitarian-report connectors: GDELT, ReliefWeb, Africa CDC, ProMED,
and operator-configured RSS/Atom feeds (e.g. local newspapers, radio stations).

Only titles, short descriptions, dates and links are collected. Full article
text is not scraped: it is unnecessary for signal detection and raises
copyright and data-minimisation concerns.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

from defusedxml import ElementTree as SafeET

from ..config import Settings
from ..domain.enums import ConnectorStatus, SourceCategory
from .base import Connector, ConnectorResult, FetchedItem, SourceInfo
from .http import HttpClient, SourceUnavailable

GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"

# GDELT source-language names -> ISO 639 codes. GDELT machine-translates many
# languages; queries are in English and in the source language where useful.
GDELT_QUERIES = {
    "english": ("en", '(ebola OR bundibugyo OR "hemorrhagic fever" OR "haemorrhagic fever")'),
    "french": ("fr", '(ebola OR bundibugyo OR "fièvre hémorragique")'),
    "swahili": ("sw", "(ebola OR homa)"),
    "portuguese": ("pt", '(ebola OR "febre hemorrágica")'),
    "arabic": ("ar", "(ebola OR إيبولا)"),
}


def _gdelt_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


class GdeltConnector(Connector):
    info = SourceInfo(
        key="gdelt_doc",
        name="GDELT DOC 2.0 news search",
        institution="The GDELT Project",
        category=SourceCategory.NEWS,
        access_method="GDELT DOC 2.0 API (<= 1 request / 5 s)",
        homepage="https://www.gdeltproject.org/",
        license="Open; citation required",
        terms_note="Article titles and links only; publishers retain rights to article content.",
        attribution="The GDELT Project",
    )

    def __init__(self, languages: dict | None = None, timespan: str = "3d"):
        self.languages = languages or GDELT_QUERIES
        self.timespan = timespan

    def fetch(self, client: HttpClient, settings: Settings, since=None) -> ConnectorResult:
        items: list[FetchedItem] = []
        errors: list[str] = []
        for lang_name, (code, query) in self.languages.items():
            params = {"query": f"{query} sourcelang:{lang_name}", "mode": "artlist", "format": "json",
                      "maxrecords": "75", "timespan": self.timespan, "sort": "datedesc"}
            try:
                data = client.get_json(GDELT, params=params)
            except SourceUnavailable as e:
                errors.append(f"{lang_name}: {e}")
                continue
            for a in (data or {}).get("articles", []):
                url = a.get("url")
                if not url:
                    continue
                items.append(FetchedItem(
                    external_id=hashlib.sha256(url.encode()).hexdigest()[:32],
                    url=url, title=a.get("title"), published_at=_gdelt_dt(a.get("seendate")),
                    text=a.get("title"), language=code, platform="news",
                    meta={"domain": a.get("domain"), "source_country": a.get("sourcecountry"), "gdelt_language": a.get("language")},
                ))
        if errors and not items:
            return ConnectorResult(ConnectorStatus.UNAVAILABLE, [], "; ".join(errors))
        status = ConnectorStatus.PARTIAL if errors else ConnectorStatus.OK
        return ConnectorResult(status, items, f"{len(items)} articles" + (f"; errors: {'; '.join(errors)}" if errors else ""))


RELIEFWEB = "https://api.reliefweb.int/v2/reports"


class ReliefWebConnector(Connector):
    info = SourceInfo(
        key="reliefweb",
        name="ReliefWeb reports",
        institution="UN OCHA ReliefWeb",
        category=SourceCategory.HUMANITARIAN,
        access_method="ReliefWeb API v2 (requires a pre-approved appname)",
        homepage="https://reliefweb.int/",
        license="Varies by publishing organisation; see each report",
        terms_note="ReliefWeb requires API users to request an approved appname.",
        attribution="ReliefWeb (UN OCHA) and the originating organisations",
    )

    def configuration_problem(self, settings: Settings):
        if p := super().configuration_problem(settings):
            return p
        if not settings.reliefweb_appname:
            return ConnectorStatus.REQUIRES_CONFIGURATION, "set EW_RELIEFWEB_APPNAME to an appname approved by ReliefWeb"
        return None

    def fetch(self, client: HttpClient, settings: Settings, since=None) -> ConnectorResult:
        since = since or datetime.now(UTC) - timedelta(days=14)
        body = {
            "query": {"value": "ebola OR bundibugyo", "operator": "OR"},
            "filter": {"field": "date.created", "value": {"from": since.strftime("%Y-%m-%dT%H:%M:%S+00:00")}},
            "fields": {"include": ["title", "date.original", "source.name", "url_alias", "language.code", "body"]},
            "sort": ["date.created:desc"], "limit": 100,
        }
        try:
            data = client.post(RELIEFWEB, params={"appname": settings.reliefweb_appname}, json=body).json()
        except (SourceUnavailable, ValueError) as e:
            return ConnectorResult(ConnectorStatus.UNAVAILABLE, [], str(e))
        items = []
        for row in data.get("data", []):
            f = row.get("fields", {})
            items.append(FetchedItem(
                external_id=str(row.get("id")), url=f.get("url_alias"), title=f.get("title"),
                published_at=_iso(f.get("date", {}).get("original")),
                text=(f.get("title") or "") + "\n" + (f.get("body") or "")[:3000],
                language=(f.get("language") or [{}])[0].get("code"),
                platform="reliefweb", meta={"publishers": [s.get("name") for s in f.get("source", [])]},
            ))
        return ConnectorResult(ConnectorStatus.OK, items, f"{len(items)} reports")


def _iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_feed(xml_text: str) -> list[dict]:
    """Parse RSS 2.0 or Atom safely (defusedxml blocks entity-expansion attacks)."""
    root = SafeET.fromstring(xml_text.encode() if isinstance(xml_text, str) else xml_text)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out = []
    for it in root.iter("item"):
        out.append({
            "title": (it.findtext("title") or "").strip(), "link": (it.findtext("link") or "").strip(),
            "summary": (it.findtext("description") or "").strip(), "published": it.findtext("pubDate"),
            "id": it.findtext("guid") or it.findtext("link"),
        })
    for it in root.iter("{http://www.w3.org/2005/Atom}entry"):
        link = it.find("a:link", ns)
        out.append({
            "title": (it.findtext("a:title", default="", namespaces=ns)).strip(),
            "link": link.get("href") if link is not None else "",
            "summary": (it.findtext("a:summary", default="", namespaces=ns) or it.findtext("a:content", default="", namespaces=ns)).strip(),
            "published": it.findtext("a:updated", default=None, namespaces=ns) or it.findtext("a:published", default=None, namespaces=ns),
            "id": it.findtext("a:id", default=None, namespaces=ns),
        })
    return out


def _feed_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return parsedate_to_datetime(s)
    except (TypeError, ValueError):
        return _iso(s)


class FeedConnector(Connector):
    """Generic RSS/Atom connector for operator-configured feeds."""

    def __init__(self, key: str, name: str, urls: list[str], category: SourceCategory, institution: str | None = None,
                 homepage: str | None = None, official: bool = False, keyword_filter: tuple[str, ...] = ()):
        self.info = SourceInfo(key=key, name=name, institution=institution, category=category, access_method="RSS/Atom feed",
                               homepage=homepage, license="Publisher terms apply", terms_note="Titles, summaries and links only.",
                               attribution=name)
        self.urls = urls
        self.official = official
        self.keyword_filter = tuple(k.lower() for k in keyword_filter)

    def fetch(self, client: HttpClient, settings: Settings, since=None) -> ConnectorResult:
        items, errors = [], []
        for url in self.urls:
            try:
                entries = parse_feed(client.get(url).text)
            except SourceUnavailable as e:
                errors.append(f"{url}: {e}")
                continue
            except SafeET.ParseError as e:
                errors.append(f"{url}: unparseable feed ({e})")
                continue
            except Exception as e:  # defusedxml raises on forbidden constructs
                errors.append(f"{url}: rejected unsafe feed ({e.__class__.__name__})")
                continue
            for en in entries:
                text = f"{en['title']}\n{en['summary']}"
                if self.keyword_filter and not any(k in text.lower() for k in self.keyword_filter):
                    continue
                ext = hashlib.sha256((en.get("id") or en["link"] or en["title"]).encode()).hexdigest()[:32]
                items.append(FetchedItem(external_id=ext, url=en["link"] or None, title=en["title"],
                                         published_at=_feed_dt(en.get("published")), text=text, is_html=True,
                                         platform="feed", is_official=self.official))
        if errors and not items:
            return ConnectorResult(ConnectorStatus.UNAVAILABLE, [], "; ".join(errors))
        return ConnectorResult(ConnectorStatus.PARTIAL if errors else ConnectorStatus.OK, items,
                               f"{len(items)} feed entries" + (f"; errors: {'; '.join(errors)}" if errors else ""))


class AfricaCdcConnector(FeedConnector):
    def __init__(self):
        super().__init__("africa_cdc", "Africa CDC news and epidemic intelligence", ["https://africacdc.org/feed/"],
                         SourceCategory.OFFICIAL_INTERNATIONAL, institution="Africa Centres for Disease Control and Prevention",
                         homepage="https://africacdc.org/", official=True,
                         keyword_filter=("ebola", "bundibugyo", "hemorrhagic", "haemorrhagic", "hémorragique"))


class PromedConnector(FeedConnector):
    def __init__(self, url: str | None):
        super().__init__("promed", "ProMED", [url] if url else [], SourceCategory.NEWS,
                         institution="International Society for Infectious Diseases", homepage="https://www.promedmail.org/",
                         keyword_filter=("ebola", "bundibugyo", "hemorrhagic", "haemorrhagic", "vhf"))

    def configuration_problem(self, settings: Settings):
        if p := super().configuration_problem(settings):
            return p
        if not self.urls:
            return (ConnectorStatus.REQUIRES_CONFIGURATION,
                    "ProMED content requires a subscription; set EW_PROMED_FEED_URL to a feed your organisation is licensed to use")
        return None


class ConfiguredFeedsConnector(FeedConnector):
    def __init__(self, urls: list[str]):
        super().__init__("local_feeds", "Operator-configured local news and radio feeds", urls, SourceCategory.NEWS,
                         keyword_filter=("ebola", "bundibugyo", "hémorragique", "hemorrhagic", "homa", "bokono", "fièvre", "maladie", "ugonjwa"))

    def configuration_problem(self, settings: Settings):
        if p := super().configuration_problem(settings):
            return p
        if not self.urls:
            return ConnectorStatus.REQUIRES_CONFIGURATION, "set EW_RSS_FEEDS to a comma-separated list of lawful public RSS/Atom feeds"
        return None
