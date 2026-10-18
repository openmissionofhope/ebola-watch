"""Surveillance-quality assessment from observable indicators.

Each indicator is reported with its value, source and interpretation. The
overall rating describes the *evidence base*, not the country: an indicator
that is unavailable is "unknown", never assumed poor.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .classify import load_thresholds


@dataclass
class SurveillanceInputs:
    today: date
    data_as_of: date | None
    mean_reporting_interval_days: float | None
    contacts_seen: float | None = None
    contacts_listed: float | None = None
    community_deaths: float | None = None
    deaths_denominator: float | None = None
    ascertainment_median: float | None = None
    ascertainment_interval: tuple[float, float] | None = None
    source_discrepancies: int = 0
    downward_revisions: int = 0
    suspected_cases: float | None = None
    confirmed_cases: float | None = None


def assess(x: SurveillanceInputs, thresholds: dict | None = None) -> dict:
    t = (thresholds or load_thresholds())["surveillance"]
    ind = []
    concerns: list[str] = []

    def add(key, label, value, status, note):
        ind.append({"key": key, "label": label, "value": value, "status": status, "note": note})

    if x.data_as_of:
        age = (x.today - x.data_as_of).days
        st = "adequate" if age <= 7 else "concern" if age <= 14 else "serious_concern"
        add("data_age_days", "Days since latest official data", age, st, "Reporting delay between observation and today")
        if age > t["reporting_gap_concern_days"]:
            concerns.append(f"official data are {age} days old")
    else:
        add("data_age_days", "Days since latest official data", None, "unknown", "No official data")
    if x.mean_reporting_interval_days is not None:
        st = "adequate" if x.mean_reporting_interval_days <= 3 else "limited" if x.mean_reporting_interval_days <= 8 else "sparse"
        add("reporting_interval", "Mean interval between official reports (days)", round(x.mean_reporting_interval_days, 1), st,
            "Sparse reporting limits nowcasting precision")
        # Sudden change in reporting: the current silence is much longer than the usual interval
        if x.data_as_of:
            silence = (x.today - x.data_as_of).days
            if silence > max(2 * x.mean_reporting_interval_days, 7) + 2:
                add("reporting_pause", "Days without an update vs usual interval", f"{silence} vs {x.mean_reporting_interval_days:.0f}",
                    "concern", "Reporting appears to have paused relative to its usual frequency")
                concerns.append(f"official reporting paused: {silence} days without an update (usual interval about "
                                f"{x.mean_reporting_interval_days:.0f} days)")
    if x.contacts_seen is not None and x.contacts_listed:
        cov = x.contacts_seen / x.contacts_listed
        st = "adequate" if cov >= t["contact_followup_target"] else "concern" if cov >= t["contact_followup_concern"] else "serious_concern"
        add("contact_followup", "Contacts followed up", round(cov, 3), st, f"Response target {t['contact_followup_target']:.0%}")
        if cov < t["contact_followup_concern"]:
            concerns.append(f"contact follow-up {cov:.0%} below {t['contact_followup_concern']:.0%}")
    else:
        add("contact_followup", "Contacts followed up", None, "unknown", "Not reported")
    if x.community_deaths is not None and x.deaths_denominator:
        share = x.community_deaths / x.deaths_denominator
        st = "concern" if share >= t["community_deaths_concern"] else "adequate"
        add("community_deaths", "Share of deaths occurring in the community", round(share, 3), st,
            "Deaths outside treatment centres indicate late detection")
        if share >= t["community_deaths_concern"]:
            concerns.append(f"{share:.0%} of recent deaths occurred in the community (late detection)")
    else:
        add("community_deaths", "Share of deaths occurring in the community", None, "unknown", "Not reported")
    if x.ascertainment_median is not None:
        st = "concern" if x.ascertainment_median < t["ascertainment_concern"] else "adequate"
        add("ascertainment", "Estimated case ascertainment (mortality-based)", round(x.ascertainment_median, 3), st,
            "Model estimate; see burden assumptions")
        if x.ascertainment_median < t["ascertainment_concern"]:
            concerns.append(f"estimated case ascertainment about {x.ascertainment_median:.0%}")
    if x.source_discrepancies:
        add("source_discrepancies", "Dates where official sources disagree", x.source_discrepancies, "concern", "See evidence explorer")
    if x.downward_revisions:
        add("revisions", "Downward revisions of cumulative totals", x.downward_revisions, "note", "Reclassification or correction")
    if x.suspected_cases and x.confirmed_cases:
        add("suspected_vs_confirmed", "Suspected cases per confirmed case", round(x.suspected_cases / x.confirmed_cases, 2), "note",
            "Large backlogs of suspected cases can indicate testing constraints")

    known = [i for i in ind if i["status"] != "unknown"]
    if not known:
        overall = "insufficient_information"
    elif sum(i["status"] == "serious_concern" for i in ind) or len(concerns) >= 2:
        overall = "serious_concerns"
    elif concerns or any(i["status"] == "concern" for i in ind):
        overall = "concerns"
    else:
        overall = "adequate"
    return {"overall": overall, "indicators": ind, "concerns": concerns}
