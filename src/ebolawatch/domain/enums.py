"""Controlled vocabularies shared across the system.

Keeping categories explicit (rather than free text) is what lets the system
refuse to silently combine confirmed, probable, suspected, unverified and
modelled quantities.
"""

from __future__ import annotations

from enum import StrEnum


class Pathogen(StrEnum):
    EBOV = "EBOV"  # Orthoebolavirus zairense (Ebola virus)
    SUDV = "SUDV"  # Sudan virus
    BDBV = "BDBV"  # Bundibugyo virus
    TAFV = "TAFV"  # Tai Forest virus
    UNKNOWN = "unknown_orthoebolavirus"


class Metric(StrEnum):
    CASES = "cases"
    DEATHS = "deaths"
    RECOVERIES = "recoveries"
    COMMUNITY_DEATHS = "community_deaths"
    CONTACTS_LISTED = "contacts_listed"
    CONTACTS_SEEN = "contacts_seen"
    AFFECTED_ADMIN1 = "affected_admin1_units"  # e.g. provinces with >=1 confirmed case
    AFFECTED_ADMIN2 = "affected_admin2_units"  # e.g. health zones with >=1 confirmed case
    OUTBREAK_END_DECLARED = "outbreak_end_declared"


class CaseClass(StrEnum):
    CONFIRMED = "confirmed"
    PROBABLE = "probable"
    SUSPECTED = "suspected"
    NOT_APPLICABLE = "na"


class ValueType(StrEnum):
    CUMULATIVE = "cumulative"
    INCIDENT = "incident"


class TransmissionType(StrEnum):
    # All cases reported by the jurisdiction, whatever their origin (the usual
    # form of official totals). IMPORTED is a subset of ALL.
    ALL = "all"
    LOCAL = "local"  # explicitly locally acquired
    IMPORTED = "imported"
    # Medically evacuated / repatriated patients are reported by the receiving
    # country but are not local cases and carry no exportation signal.
    MEDEVAC = "medevac"
    UNKNOWN = "unknown"


class ValidationStatus(StrEnum):
    AUTO_VALIDATED = "auto_validated"  # machine-extracted, internal consistency checks passed
    PENDING_REVIEW = "pending_review"  # machine-extracted with ambiguity or failed checks
    VERIFIED = "verified"  # human reviewer confirmed against the cited source
    DISPUTED = "disputed"
    RETRACTED = "retracted"


PUBLISHABLE_VALIDATION = {ValidationStatus.AUTO_VALIDATED, ValidationStatus.VERIFIED}


class SourceCategory(StrEnum):
    OFFICIAL_INTERNATIONAL = "official_international"  # WHO, Africa CDC
    OFFICIAL_NATIONAL = "official_national"  # ministries, national public-health institutes
    HUMANITARIAN = "humanitarian"
    RESEARCH = "research"
    NEWS = "news"
    SOCIAL_MEDIA = "social_media"
    COMMUNITY = "community"
    REFERENCE = "reference"  # population, boundaries, transport


OFFICIAL_CATEGORIES = {SourceCategory.OFFICIAL_INTERNATIONAL, SourceCategory.OFFICIAL_NATIONAL}


class ConnectorStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"  # source down, blocked, or rate-limited
    REQUIRES_CONFIGURATION = "requires_configuration"  # credentials / approved app id needed
    REQUIRES_ACKNOWLEDGEMENT = "requires_acknowledgement"  # operator must accept data-use terms
    UNSUPPORTED = "unsupported"  # no lawful automated access path
    DISABLED = "disabled"
    ERROR = "error"


class ReportKind(StrEnum):
    """What kind of speech act a collected report is."""

    OFFICIAL_ANNOUNCEMENT = "official_announcement"
    PROFESSIONAL_REPORTING = "professional_reporting"
    FIRSTHAND_OBSERVATION = "firsthand_observation"
    SECONDARY_REPORTING = "secondary_reporting"
    REPOST = "repost"
    RUMOR = "rumor"
    SATIRE = "satire"
    MISINFORMATION = "misinformation"  # contradicted by reliable evidence
    SUSPECTED_MANIPULATION = "suspected_manipulation"
    UNCLEAR = "unclear"


class ClaimType(StrEnum):
    EBOLA_CASES = "ebola_cases"
    VHF_CLUSTER = "vhf_cluster"
    UNEXPLAINED_DEATHS = "unexplained_deaths"
    ILLNESS_CLUSTER = "illness_cluster"
    SUSPECTED_OUTBREAK = "suspected_outbreak"
    SURVEILLANCE_ACTIVITY = "surveillance_activity"
    GENERAL_DISCUSSION = "general_discussion"
    NOT_RELEVANT = "not_relevant"


EPIDEMIOLOGICAL_CLAIMS = {
    ClaimType.EBOLA_CASES,
    ClaimType.VHF_CLUSTER,
    ClaimType.UNEXPLAINED_DEATHS,
    ClaimType.ILLNESS_CLUSTER,
    ClaimType.SUSPECTED_OUTBREAK,
}


class Corroboration(StrEnum):
    UNCORROBORATED = "uncorroborated"
    SINGLE_ORIGIN_AMPLIFIED = "single_origin_amplified"  # many copies of one origin
    INDEPENDENT_UNOFFICIAL = "independent_unofficial"  # >=2 independent unofficial origins
    PROFESSIONAL_CORROBORATED = "professional_corroborated"
    OFFICIAL_CONFIRMED = "official_confirmed"
    CONTRADICTED = "contradicted_by_reliable_evidence"


class SignalAssessment(StrEnum):
    POSSIBLE_EMERGING = "Possible emerging outbreak signal."
    OFFICIAL_MAY_BE_INCOMPLETE = "Independent reports suggest official reporting may be incomplete."
    INSUFFICIENT_EVIDENCE = "Insufficient evidence to establish Ebola transmission."
    LAB_CONFIRMED_EXPANSION = "Laboratory-confirmed geographic expansion."
    INFORMATION_EVENT = "Information event: claims are circulating without epidemiological corroboration."
    STALE_RECIRCULATION = "Outdated report recirculated as if current."
    COORDINATED_AMPLIFICATION = "Possible coordinated amplification; not treated as independent evidence."
    CONSISTENT_WITH_OFFICIAL = "Consistent with officially reported transmission."


class Confidence(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class SeverityStatus(StrEnum):
    ASSESSED = "assessed"
    INSUFFICIENT_INFORMATION = "insufficient_information"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_MORE_INFO = "needs_more_info"


class Role(StrEnum):
    ANALYST = "analyst"  # read restricted (non-public) aggregates
    REVIEWER = "reviewer"  # approve/reject review items
    ADMIN = "admin"  # manage keys, sources, corrections


ROLE_RANK = {Role.ANALYST: 1, Role.REVIEWER: 2, Role.ADMIN: 3}


class TransportMode(StrEnum):
    ROAD = "road"
    RAIL = "rail"
    AIR = "air"
    RIVER = "river"
    LAKE = "lake"
    INFORMAL = "informal"  # coarse cross-border pedestrian / informal movement


class PhysicalStatus(StrEnum):
    DOCUMENTED = "documented"  # infrastructure documented (e.g. mapped in OSM)
    UNVERIFIED = "unverified"


class ServiceStatus(StrEnum):
    OPERATIONAL = "operational"  # verified passenger service
    INTERMITTENT = "intermittent"  # verified but irregular
    SEASONAL = "seasonal"
    SUSPENDED = "suspended"
    NON_OPERATIONAL = "non_operational"
    UNKNOWN = "unknown"


class VerificationLevel(StrEnum):
    OFFICIAL = "official"  # transport authority / operator publication
    SECONDARY = "secondary"  # published research, reputable reporting
    MAPPED_ONLY = "mapped_only"  # geometry exists in open map data; service not verified
    UNVERIFIED = "unverified"
