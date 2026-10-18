"""Relational schema.

Design rules enforced here:

* Observations are append-only. A revision is a new row pointing at the row it
  supersedes; nothing is overwritten. Observation period (``as_of`` /
  ``period_start``..``period_end``) is stored separately from publication and
  retrieval timestamps.
* No table stores patient identities, individual travel histories, contact
  lists, or social-media handles. Authors of public posts are reduced to a keyed
  pseudonym used only for duplicate/coordination detection and never exposed.
* Raw external text is minimised (PII-redacted) and carries a retention deadline.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, utcnow


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    institution: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(32))
    access_method: Mapped[str] = mapped_column(String(64))
    homepage: Mapped[str | None] = mapped_column(String(512))
    license: Mapped[str | None] = mapped_column(String(255))
    terms_note: Mapped[str | None] = mapped_column(Text)
    attribution: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="unknown")
    status_message: Mapped[str | None] = mapped_column(Text)
    last_attempt_at: Mapped[datetime | None]
    last_success_at: Mapped[datetime | None]
    # Historical performance is only filled in from validation data (see
    # evidence.reliability); until then it stays empty rather than guessed.
    performance: Mapped[dict] = mapped_column(default=dict)


class ConnectorRun(Base):
    __tablename__ = "connector_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_key: Mapped[str] = mapped_column(String(64), index=True)
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None]
    status: Mapped[str] = mapped_column(String(32))
    items_fetched: Mapped[int] = mapped_column(default=0)
    items_new: Mapped[int] = mapped_column(default=0)
    message: Mapped[str | None] = mapped_column(Text)


class Region(Base):
    __tablename__ = "regions"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)  # ISO3, ISO3-ADM1 slug, or pcode
    name: Mapped[str] = mapped_column(String(255))
    level: Mapped[int] = mapped_column(Integer)  # 0 country, 1 first-level admin, 2 health zone
    iso3: Mapped[str] = mapped_column(String(3), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("regions.id"))
    population: Mapped[int | None]
    population_year: Mapped[int | None]
    population_source: Mapped[str | None] = mapped_column(String(255))
    centroid_lat: Mapped[float | None] = mapped_column(Float)
    centroid_lon: Mapped[float | None] = mapped_column(Float)
    geometry: Mapped[dict | None]  # simplified GeoJSON geometry (public-safe resolution)
    aliases: Mapped[list] = mapped_column(default=list)
    priority: Mapped[bool] = mapped_column(Boolean, default=False)

    parent: Mapped[Region | None] = relationship(remote_side=[id])


class Outbreak(Base):
    __tablename__ = "outbreaks"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    pathogen: Mapped[str] = mapped_column(String(32))
    declared_on: Mapped[date | None] = mapped_column(Date)
    ended_on: Mapped[date | None] = mapped_column(Date)
    primary_iso3: Mapped[str | None] = mapped_column(String(3))
    notes: Mapped[str | None] = mapped_column(Text)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)


class Document(Base):
    """A retrieved item (bulletin, article, post). Content is untrusted data."""

    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("source_id", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(255))
    url: Mapped[str | None] = mapped_column(String(1024))
    title: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(16))
    published_at: Mapped[datetime | None]
    retrieved_at: Mapped[datetime] = mapped_column(default=utcnow)
    content_hash: Mapped[str] = mapped_column(String(64))
    # PII-redacted, length-limited text. Deleted after ``retain_text_until``.
    text_minimized: Mapped[str | None] = mapped_column(Text)
    retain_text_until: Mapped[datetime | None]
    author_pseudonym: Mapped[str | None] = mapped_column(String(64))  # keyed HMAC; never exposed
    platform: Mapped[str | None] = mapped_column(String(32))
    safety_flags: Mapped[list] = mapped_column(default=list)
    meta: Mapped[dict] = mapped_column(default=dict)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)

    source: Mapped[Source] = relationship()


class DataVintage(Base):
    """One published version of a dataset (a bulletin, a sitrep, a CSV snapshot)."""

    __tablename__ = "data_vintages"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    label: Mapped[str] = mapped_column(String(255))
    published_at: Mapped[datetime | None]
    retrieved_at: Mapped[datetime] = mapped_column(default=utcnow)
    content_hash: Mapped[str] = mapped_column(String(64))


class Observation(Base):
    """An officially reported epidemiological quantity. Append-only."""

    __tablename__ = "observations"
    __table_args__ = (
        Index("ix_obs_series", "region_id", "metric", "case_class", "value_type", "as_of"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    outbreak_id: Mapped[int | None] = mapped_column(ForeignKey("outbreaks.id"))
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id"), index=True)
    metric: Mapped[str] = mapped_column(String(32))
    case_class: Mapped[str] = mapped_column(String(16))
    value_type: Mapped[str] = mapped_column(String(16))
    transmission: Mapped[str] = mapped_column(String(16), default="all")
    # Observation period: cumulative values use ``as_of``; incident values use the period.
    as_of: Mapped[date] = mapped_column(Date)
    period_start: Mapped[date | None] = mapped_column(Date)
    value: Mapped[float] = mapped_column(Float)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    vintage_id: Mapped[int | None] = mapped_column(ForeignKey("data_vintages.id"))
    published_at: Mapped[datetime | None]
    retrieved_at: Mapped[datetime] = mapped_column(default=utcnow)
    citation: Mapped[str | None] = mapped_column(Text)
    quote: Mapped[str | None] = mapped_column(Text)  # short supporting excerpt from an official source
    extraction_method: Mapped[str] = mapped_column(String(32))  # structured | text_pattern | manual
    validation_status: Mapped[str] = mapped_column(String(32))
    validation_notes: Mapped[list] = mapped_column(default=list)
    attributes: Mapped[dict] = mapped_column(default=dict)  # e.g. denominator, unit
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("observations.id"))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    region: Mapped[Region] = relationship()
    source: Mapped[Source] = relationship()


class Signal(Base):
    """A claim extracted from one unofficial or official document."""

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    cluster_id: Mapped[int | None] = mapped_column(ForeignKey("signal_clusters.id"), index=True)
    origin_group: Mapped[str] = mapped_column(String(64), index=True)  # near-duplicate family
    languages: Mapped[list] = mapped_column(default=list)
    claim_type: Mapped[str] = mapped_column(String(32))
    report_kind: Mapped[str] = mapped_column(String(32))
    relevance: Mapped[str] = mapped_column(String(16))  # likely | ambiguous | unlikely
    event_date: Mapped[date | None] = mapped_column(Date)
    event_date_basis: Mapped[str | None] = mapped_column(String(64))
    published_at: Mapped[datetime | None]
    region_id: Mapped[int | None] = mapped_column(ForeignKey("regions.id"))
    location_precision: Mapped[str | None] = mapped_column(String(16))  # country | admin1 | admin2
    counts_claimed: Mapped[dict] = mapped_column(default=dict)
    features: Mapped[dict] = mapped_column(default=dict)  # interpretable evidence features
    concept_signature: Mapped[list] = mapped_column(default=list)
    fingerprint: Mapped[list] = mapped_column(default=list)  # MinHash signature
    translation_quality: Mapped[str] = mapped_column(String(16), default="not_needed")
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    review_reasons: Mapped[list] = mapped_column(default=list)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    document: Mapped[Document] = relationship()


class SignalCluster(Base):
    """An event-level grouping of signals that appear to describe the same claim."""

    __tablename__ = "signal_clusters"

    id: Mapped[int] = mapped_column(primary_key=True)
    cluster_key: Mapped[str] = mapped_column(String(64), index=True, default="")
    region_id: Mapped[int | None] = mapped_column(ForeignKey("regions.id"))
    claim_type: Mapped[str] = mapped_column(String(32))
    summary: Mapped[str] = mapped_column(Text)  # paraphrased, aggregated, non-identifying
    first_seen: Mapped[datetime | None]
    last_seen: Mapped[datetime | None]
    event_window_start: Mapped[date | None] = mapped_column(Date)
    event_window_end: Mapped[date | None] = mapped_column(Date)
    n_documents: Mapped[int] = mapped_column(default=0)
    n_origins: Mapped[int] = mapped_column(default=0)
    n_independent_origins: Mapped[int] = mapped_column(default=0)
    languages: Mapped[list] = mapped_column(default=list)
    corroboration: Mapped[str] = mapped_column(String(48))
    assessment: Mapped[str] = mapped_column(Text)
    coordination_suspected: Mapped[bool] = mapped_column(Boolean, default=False)
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="open")
    evidence: Mapped[dict] = mapped_column(default=dict)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class ModelRun(Base):
    __tablename__ = "model_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    model_name: Mapped[str] = mapped_column(String(64))
    model_version: Mapped[str] = mapped_column(String(32))
    run_at: Mapped[datetime] = mapped_column(default=utcnow)
    data_as_of: Mapped[date | None] = mapped_column(Date)
    region_id: Mapped[int | None] = mapped_column(ForeignKey("regions.id"))
    status: Mapped[str] = mapped_column(String(32))  # ok | insufficient_data | failed
    parameters: Mapped[dict] = mapped_column(default=dict)
    inputs_hash: Mapped[str | None] = mapped_column(String(64))
    diagnostics: Mapped[dict] = mapped_column(default=dict)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)


class Estimate(Base):
    __tablename__ = "estimates"

    id: Mapped[int] = mapped_column(primary_key=True)
    model_run_id: Mapped[int] = mapped_column(ForeignKey("model_runs.id"), index=True)
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id"), index=True)
    quantity: Mapped[str] = mapped_column(String(48))
    method: Mapped[str] = mapped_column(String(64))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    median: Mapped[float | None] = mapped_column(Float)
    lower_90: Mapped[float | None] = mapped_column(Float)
    upper_90: Mapped[float | None] = mapped_column(Float)
    lower_50: Mapped[float | None] = mapped_column(Float)
    upper_50: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[str] = mapped_column(String(16))
    insufficient: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str | None] = mapped_column(Text)
    assumptions: Mapped[list] = mapped_column(default=list)
    details: Mapped[dict] = mapped_column(default=dict)


class Forecast(Base):
    __tablename__ = "forecasts"

    id: Mapped[int] = mapped_column(primary_key=True)
    model_run_id: Mapped[int] = mapped_column(ForeignKey("model_runs.id"), index=True)
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id"), index=True)
    issued_at: Mapped[datetime] = mapped_column(default=utcnow)
    data_as_of: Mapped[date] = mapped_column(Date)
    horizon_days: Mapped[int]
    scenario: Mapped[str] = mapped_column(String(32))
    target: Mapped[str] = mapped_column(String(48))  # new_reported_confirmed | new_infections
    quantiles: Mapped[dict] = mapped_column(default=dict)  # {"0.05": .., "0.25": .., ...}
    p_continued_transmission: Mapped[float | None] = mapped_column(Float)
    p_geographic_expansion: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[str] = mapped_column(String(16))
    is_scenario: Mapped[bool] = mapped_column(Boolean, default=False)
    insufficient: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str | None] = mapped_column(Text)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)


class ForecastEvaluation(Base):
    __tablename__ = "forecast_evaluations"

    id: Mapped[int] = mapped_column(primary_key=True)
    evaluation_run: Mapped[str] = mapped_column(String(64), index=True)
    region_code: Mapped[str] = mapped_column(String(64))
    dataset: Mapped[str] = mapped_column(String(128))  # e.g. "who_don:COD:2026" or "synthetic:..."
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    origin_date: Mapped[date] = mapped_column(Date)
    horizon_days: Mapped[int]
    observed: Mapped[float] = mapped_column(Float)
    median: Mapped[float] = mapped_column(Float)
    lower_50: Mapped[float] = mapped_column(Float)
    upper_50: Mapped[float] = mapped_column(Float)
    lower_90: Mapped[float] = mapped_column(Float)
    upper_90: Mapped[float] = mapped_column(Float)
    wis: Mapped[float] = mapped_column(Float)
    pit: Mapped[float | None] = mapped_column(Float)
    model_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class SeverityAssessment(Base):
    __tablename__ = "severity_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id"), index=True)
    assessed_at: Mapped[datetime] = mapped_column(default=utcnow)
    data_as_of: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32))
    level: Mapped[int | None]
    confidence: Mapped[str] = mapped_column(String(16))
    underestimation_risk: Mapped[bool] = mapped_column(Boolean, default=False)
    triggers: Mapped[list] = mapped_column(default=list)
    explanation: Mapped[str] = mapped_column(Text)
    surveillance: Mapped[dict] = mapped_column(default=dict)
    model_version: Mapped[str] = mapped_column(String(32))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    region_id: Mapped[int | None] = mapped_column(ForeignKey("regions.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    kind: Mapped[str] = mapped_column(String(48))
    message: Mapped[str] = mapped_column(Text)
    severity_level: Mapped[int | None]
    confidence: Mapped[str] = mapped_column(String(16))
    evidence: Mapped[dict] = mapped_column(default=dict)
    relies_on_unofficial: Mapped[bool] = mapped_column(Boolean, default=False)
    review_status: Mapped[str] = mapped_column(String(32), default="pending")
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    published_at: Mapped[datetime | None]
    retracted: Mapped[bool] = mapped_column(Boolean, default=False)
    retraction_note: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(String(128), index=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)


class SituationReport(Base):
    __tablename__ = "situation_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))  # daily | weekly | major_change | country | multicountry
    scope: Mapped[list] = mapped_column(default=list)  # region codes
    generated_at: Mapped[datetime] = mapped_column(default=utcnow)
    data_as_of: Mapped[date | None] = mapped_column(Date)
    title: Mapped[str] = mapped_column(String(255))
    content_md: Mapped[str] = mapped_column(Text)
    content: Mapped[dict] = mapped_column(default=dict)
    model_version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="published")
    retraction_note: Mapped[str | None] = mapped_column(Text)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)


class TransportNode(Base):
    __tablename__ = "transport_nodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(32))  # region_hub | city | border_area
    region_id: Mapped[int | None] = mapped_column(ForeignKey("regions.id"))
    iso3: Mapped[str] = mapped_column(String(3))
    lat: Mapped[float] = mapped_column(Float)  # generalised (rounded) coordinates
    lon: Mapped[float] = mapped_column(Float)


class TransportEdge(Base):
    __tablename__ = "transport_edges"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(128), unique=True)
    from_node_id: Mapped[int] = mapped_column(ForeignKey("transport_nodes.id"))
    to_node_id: Mapped[int] = mapped_column(ForeignKey("transport_nodes.id"))
    mode: Mapped[str] = mapped_column(String(16))
    corridor: Mapped[str | None] = mapped_column(String(255))
    cross_border: Mapped[bool] = mapped_column(Boolean, default=False)
    physical_status: Mapped[str] = mapped_column(String(16))
    service_status: Mapped[str] = mapped_column(String(32))
    verification: Mapped[str] = mapped_column(String(16))
    verified_on: Mapped[date | None] = mapped_column(Date)
    sources: Mapped[list] = mapped_column(default=list)
    seasonal_note: Mapped[str | None] = mapped_column(Text)
    disruption_note: Mapped[str | None] = mapped_column(Text)
    travel_time_h: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class TransportStatusChange(Base):
    """Append-only history of transport edge status changes (e.g. ferry suspended)."""

    __tablename__ = "transport_status_changes"

    id: Mapped[int] = mapped_column(primary_key=True)
    edge_id: Mapped[int] = mapped_column(ForeignKey("transport_edges.id"))
    changed_at: Mapped[datetime] = mapped_column(default=utcnow)
    old_status: Mapped[str] = mapped_column(String(32))
    new_status: Mapped[str] = mapped_column(String(32))
    evidence: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(64))


class LiteratureEstimate(Base):
    """Published external estimates (e.g. modelling groups), stored with citation."""

    __tablename__ = "literature_estimates"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    region_code: Mapped[str] = mapped_column(String(64))
    quantity: Mapped[str] = mapped_column(String(48))
    as_of: Mapped[date] = mapped_column(Date)
    lower: Mapped[float | None] = mapped_column(Float)
    upper: Mapped[float | None] = mapped_column(Float)
    central: Mapped[float | None] = mapped_column(Float)
    statement: Mapped[str] = mapped_column(Text)
    citation: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(1024))
    validation_status: Mapped[str] = mapped_column(String(32))


class ReviewItem(Base):
    __tablename__ = "review_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_type: Mapped[str] = mapped_column(String(32))  # alert | observation | signal | cluster | correction | model_run | transport_edge
    item_id: Mapped[int]
    reason: Mapped[str] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(default=2)  # 1 high .. 3 low
    status: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    resolved_at: Mapped[datetime | None]
    resolved_by: Mapped[str | None] = mapped_column(String(64))
    resolution_note: Mapped[str | None] = mapped_column(Text)


class ErrorReport(Base):
    """Public correction requests from communities or organisations. No PII required."""

    __tablename__ = "error_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    submitted_at: Mapped[datetime] = mapped_column(default=utcnow)
    organisation: Mapped[str | None] = mapped_column(String(255))
    target_type: Mapped[str] = mapped_column(String(32))
    target_ref: Mapped[str | None] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    resolution: Mapped[str | None] = mapped_column(Text)


class Correction(Base):
    """Public, non-sensitive record of a correction or retraction."""

    __tablename__ = "corrections"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[int]
    action: Mapped[str] = mapped_column(String(32))  # correction | retraction | revision
    public_note: Mapped[str] = mapped_column(Text)
    error_report_id: Mapped[int | None] = mapped_column(ForeignKey("error_reports.id"))


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16))
    key_prefix: Mapped[str] = mapped_column(String(12), index=True)
    key_hash: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    revoked_at: Mapped[datetime | None]
    last_used_at: Mapped[datetime | None]


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(default=dict)
