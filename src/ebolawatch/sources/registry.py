"""Connector registry. Adding a source means adding a Connector here; nothing
else in the pipeline is source-specific except reference-data handlers."""

from __future__ import annotations

from ..config import Settings
from .base import Connector
from .ecdc import EcdcConnector
from .hdx import HdxCodEbolaConnector
from .news import (
    AfricaCdcConnector,
    ConfiguredFeedsConnector,
    GdeltConnector,
    PromedConnector,
    ReliefWebConnector,
)
from .reference import OverpassTransportConnector, WorldBankPopulationConnector
from .social import FacebookConnector, RedditConnector, TelegramConnector, XConnector, YouTubeConnector
from .statements import OfficialStatementsConnector
from .who_don import WhoDonConnector


def all_connectors(settings: Settings) -> list[Connector]:
    return [
        WhoDonConnector(),
        EcdcConnector(),
        OfficialStatementsConnector(),
        HdxCodEbolaConnector(),
        AfricaCdcConnector(),
        ReliefWebConnector(),
        GdeltConnector(),
        PromedConnector(settings.promed_feed_url),
        ConfiguredFeedsConnector(settings.rss_feeds),
        RedditConnector(),
        YouTubeConnector(),
        XConnector(),
        FacebookConnector(),
        TelegramConnector(),
        WorldBankPopulationConnector(),
        OverpassTransportConnector(),
    ]


def get_connector(key: str, settings: Settings) -> Connector:
    for c in all_connectors(settings):
        if c.info.key == key:
            return c
    raise KeyError(f"unknown source '{key}'")
