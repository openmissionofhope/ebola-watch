"""Connector interface.

A connector fetches items from one source and reports an honest status. It
never fabricates replacement data when a source is unavailable: it returns an
empty item list with status ``unavailable`` / ``requires_configuration`` /
``unsupported`` and an explanatory message.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime

from ..config import Settings
from ..domain.enums import (
    CaseClass,
    ConnectorStatus,
    Metric,
    SourceCategory,
    TransmissionType,
    ValueType,
)
from .http import HttpClient


@dataclass
class ObservationCandidate:
    """An official figure parsed from a source, before geocoding and validation."""

    region_ref: str  # region code or resolvable name
    metric: Metric
    case_class: CaseClass
    value_type: ValueType
    as_of: date
    value: float
    transmission: TransmissionType = TransmissionType.ALL
    period_start: date | None = None
    quote: str | None = None
    extraction_method: str = "structured"
    confidence: str = "high"  # high | medium | low (extraction confidence, not epidemiological)
    notes: list[str] = field(default_factory=list)
    region_level_hint: int | None = None
    parent_ref: str | None = None
    attributes: dict = field(default_factory=dict)


@dataclass
class FetchedItem:
    external_id: str
    url: str | None
    title: str | None
    published_at: datetime | None
    text: str | None  # untrusted raw text; sanitised + redacted before storage
    is_html: bool = False
    language: str | None = None
    platform: str | None = None
    author_id: str | None = None  # pseudonymised immediately on ingest, never stored
    meta: dict = field(default_factory=dict)
    observations: list[ObservationCandidate] = field(default_factory=list)
    is_official: bool = False
    is_synthetic: bool = False
    content_version: str | None = None  # e.g. LastModified; a change creates a new vintage


@dataclass
class ConnectorResult:
    status: ConnectorStatus
    items: list[FetchedItem] = field(default_factory=list)
    message: str = ""


@dataclass(frozen=True)
class SourceInfo:
    key: str
    name: str
    institution: str | None
    category: SourceCategory
    access_method: str
    homepage: str | None
    license: str | None
    terms_note: str | None
    attribution: str | None
    requires_acknowledgement: bool = False


class Connector(ABC):
    info: SourceInfo

    def configuration_problem(self, settings: Settings) -> tuple[ConnectorStatus, str] | None:
        """Return a status if the connector cannot run with the current configuration."""
        if self.info.key in settings.disabled_sources:
            return ConnectorStatus.DISABLED, "disabled by operator configuration"
        if self.info.requires_acknowledgement and self.info.key not in settings.source_acknowledgements:
            return (
                ConnectorStatus.REQUIRES_ACKNOWLEDGEMENT,
                f"data-use conditions apply; review docs/DATA_SOURCES.md and add '{self.info.key}' to "
                "EW_SOURCE_ACKNOWLEDGEMENTS to enable",
            )
        return None

    @abstractmethod
    def fetch(self, client: HttpClient, settings: Settings, since: datetime | None = None) -> ConnectorResult: ...


class UnsupportedConnector(Connector):
    """A platform with no lawful, sanctioned automated read path for this use."""

    reason: str = ""

    def configuration_problem(self, settings: Settings):
        return ConnectorStatus.UNSUPPORTED, self.reason

    def fetch(self, client, settings, since=None) -> ConnectorResult:
        return ConnectorResult(ConnectorStatus.UNSUPPORTED, [], self.reason)
