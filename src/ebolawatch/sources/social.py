"""Public social-media connectors.

Only public content reachable through the platform's sanctioned API is used.
No connector logs in as a person, joins private groups, scrapes pages against
platform terms, or reads private messages. Author identifiers are converted to
keyed pseudonyms on ingest (used only to tell independent sources from copies)
and are never stored in clear or shown.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from ..config import Settings
from ..domain.enums import ConnectorStatus, SourceCategory
from .base import Connector, ConnectorResult, FetchedItem, SourceInfo, UnsupportedConnector
from .http import HttpClient, SourceUnavailable

SEARCH_TERMS = ["ebola", "bundibugyo", "fièvre hémorragique", "homa ya ebola", "bokono ya ebola"]


def _iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


class RedditConnector(Connector):
    info = SourceInfo(
        key="reddit", name="Reddit public posts", institution="Reddit", category=SourceCategory.SOCIAL_MEDIA,
        access_method="Reddit Data API (OAuth application-only)", homepage="https://www.reddit.com/",
        license="Reddit Data API Terms", terms_note="Requires a registered API client; public posts only.",
        attribution="Public Reddit posts (aggregated, not attributed to users)",
    )

    def configuration_problem(self, settings: Settings):
        if p := super().configuration_problem(settings):
            return p
        if not (settings.reddit_client_id and settings.reddit_client_secret):
            return ConnectorStatus.REQUIRES_CONFIGURATION, "set EW_REDDIT_CLIENT_ID and EW_REDDIT_CLIENT_SECRET for a registered Reddit API client"
        return None

    def fetch(self, client: HttpClient, settings: Settings, since=None) -> ConnectorResult:
        try:
            tok = client.post("https://www.reddit.com/api/v1/access_token", data={"grant_type": "client_credentials"},
                              auth=httpx.BasicAuth(settings.reddit_client_id, settings.reddit_client_secret)).json()["access_token"]
            items = []
            for term in SEARCH_TERMS[:3]:
                data = client.get_json("https://oauth.reddit.com/search", params={"q": term, "sort": "new", "t": "week", "limit": "100"},
                                       headers={"Authorization": f"Bearer {tok}"})
                for ch in data.get("data", {}).get("children", []):
                    d = ch.get("data", {})
                    if d.get("over_18"):
                        continue
                    items.append(FetchedItem(
                        external_id=d.get("name"), url=None, title=d.get("title"),
                        published_at=datetime.fromtimestamp(d.get("created_utc", 0), tz=UTC),
                        text=f"{d.get('title', '')}\n{(d.get('selftext') or '')[:2000]}", platform="reddit",
                        author_id=d.get("author_fullname") or d.get("author"),
                        meta={"community": d.get("subreddit"), "is_crosspost": bool(d.get("crosspost_parent"))},
                    ))
        except (SourceUnavailable, KeyError, ValueError) as e:
            return ConnectorResult(ConnectorStatus.UNAVAILABLE, [], f"Reddit unavailable: {e}")
        return ConnectorResult(ConnectorStatus.OK, items, f"{len(items)} posts")


class YouTubeConnector(Connector):
    info = SourceInfo(
        key="youtube", name="YouTube public videos (titles and descriptions)", institution="Google / YouTube",
        category=SourceCategory.SOCIAL_MEDIA, access_method="YouTube Data API v3 (API key)", homepage="https://www.youtube.com/",
        license="YouTube API Services Terms", terms_note="Metadata only; no video download or transcription.",
        attribution="Public YouTube video metadata (aggregated)",
    )

    LANGS = ["en", "fr", "sw", "ln", "pt", "ar"]

    def configuration_problem(self, settings: Settings):
        if p := super().configuration_problem(settings):
            return p
        if not settings.youtube_api_key:
            return ConnectorStatus.REQUIRES_CONFIGURATION, "set EW_YOUTUBE_API_KEY (YouTube Data API v3)"
        return None

    def fetch(self, client: HttpClient, settings: Settings, since=None) -> ConnectorResult:
        after = (since or datetime.now(UTC) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        items = []
        try:
            for lang in self.LANGS:
                data = client.get_json("https://www.googleapis.com/youtube/v3/search", params={
                    "part": "snippet", "q": "ebola", "type": "video", "order": "date", "maxResults": "50",
                    "publishedAfter": after, "relevanceLanguage": lang, "key": settings.youtube_api_key})
                for it in data.get("items", []):
                    sn = it.get("snippet", {})
                    vid = it.get("id", {}).get("videoId")
                    items.append(FetchedItem(
                        external_id=vid, url=None, title=sn.get("title"), published_at=_iso(sn.get("publishedAt")),
                        text=f"{sn.get('title', '')}\n{sn.get('description', '')}", is_html=True, platform="youtube",
                        author_id=sn.get("channelId"), meta={"relevance_language": lang},
                    ))
        except SourceUnavailable as e:
            return ConnectorResult(ConnectorStatus.UNAVAILABLE, items, f"YouTube unavailable: {e}")
        return ConnectorResult(ConnectorStatus.OK, items, f"{len(items)} videos")


class XConnector(Connector):
    info = SourceInfo(
        key="x", name="X (Twitter) public posts", institution="X Corp.", category=SourceCategory.SOCIAL_MEDIA,
        access_method="X API v2 recent search (bearer token; paid access tier)", homepage="https://x.com/",
        license="X Developer Agreement", terms_note="Recent-search endpoint; public posts only.",
        attribution="Public X posts (aggregated, not attributed to users)",
    )

    def configuration_problem(self, settings: Settings):
        if p := super().configuration_problem(settings):
            return p
        if not settings.x_bearer_token:
            return ConnectorStatus.REQUIRES_CONFIGURATION, "set EW_X_BEARER_TOKEN (X API access tier with recent search)"
        return None

    def fetch(self, client: HttpClient, settings: Settings, since=None) -> ConnectorResult:
        q = "(ebola OR bundibugyo OR \"fièvre hémorragique\") -is:retweet"
        try:
            data = client.get_json("https://api.x.com/2/tweets/search/recent", params={
                "query": q, "max_results": "100", "tweet.fields": "created_at,lang,referenced_tweets,author_id"},
                headers={"Authorization": f"Bearer {settings.x_bearer_token}"})
        except SourceUnavailable as e:
            return ConnectorResult(ConnectorStatus.UNAVAILABLE, [], f"X unavailable: {e}")
        items = [FetchedItem(
            external_id=t["id"], url=None, title=None, published_at=_iso(t.get("created_at")), text=t.get("text"),
            language=t.get("lang"), platform="x", author_id=t.get("author_id"),
            meta={"referenced": [r.get("type") for r in t.get("referenced_tweets", [])]},
        ) for t in data.get("data", [])]
        return ConnectorResult(ConnectorStatus.OK, items, f"{len(items)} posts")


class FacebookConnector(UnsupportedConnector):
    info = SourceInfo(
        key="facebook", name="Facebook public content", institution="Meta", category=SourceCategory.SOCIAL_MEDIA,
        access_method="none available", homepage="https://www.facebook.com/", license=None,
        terms_note=None, attribution=None,
    )
    reason = (
        "No general-purpose public-content search API is available (CrowdTangle was discontinued in 2024; the Meta "
        "Content Library requires approved research access) and automated scraping is prohibited by Meta's terms. "
        "Organisations with approved Content Library access can import aggregated exports through the manual import path."
    )


class TelegramConnector(UnsupportedConnector):
    info = SourceInfo(
        key="telegram", name="Telegram public channels", institution="Telegram", category=SourceCategory.SOCIAL_MEDIA,
        access_method="none enabled", homepage="https://telegram.org/", license=None, terms_note=None, attribution=None,
    )
    reason = (
        "The Bot API cannot read channels unless the bot is added by the channel owner, and the client API requires "
        "logging in as an individual user account; neither is used for unattended monitoring. Channel administrators "
        "who wish to contribute can share exports through the manual import path."
    )
