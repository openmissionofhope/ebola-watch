# Severity and confidence

Severity and confidence are **separate dimensions**. An area can be
`HIGH / LOW confidence`, `ELEVATED / HIGH confidence`, or have the status
`INSUFFICIENT INFORMATION`. Thresholds live in `data/severity/thresholds.yaml`
(version `2026.10.1`); the classifier is `severity/classify.py`
(`ew-severity-1.0.0`). Every assessment stores the triggers that produced it,
and every alert reproduces them.

Severity is driven only by evidence about transmission. It is never set from
the country, its institutions, population characteristics or perceived
reporting quality.

## Natural-history anchors

| Window | Basis |
|---|---|
| 21 days | maximum incubation period (WHO fact sheet: 2–21 days) |
| 42 days | two incubation periods; WHO criterion for declaring an outbreak over |
| 28 days | data older than this cannot describe current transmission |

## Levels

| Level | Name | Triggered when (any of) |
|---|---|---|
| 4 | CRITICAL | ≥ 300 confirmed cases in 21 days (≈ 100/week sustained for three weeks) · ≥ 50 cases in 21 days with P(R_t > 1) ≥ 0.9 · ≥ 2 newly affected first-level areas in 42 days with ≥ 100 cases in 21 days |
| 3 | HIGH | ≥ 20 confirmed cases in 21 days · laboratory-confirmed cases in a newly affected first-level area in 21 days · P(R_t > 1) ≥ 0.75 with ≥ 5 cases in 21 days |
| 2 | ELEVATED | ≥ 1 confirmed local case in 21 days · laboratory-confirmed imported case within 21 days without local transmission · confirmed case detected elsewhere after travel from this area while local reports show no recent cases |
| 1 | WATCH | cases within 42 days but none in 21 (end-of-outbreak countdown) · imported case within 42 days · ≥ 2 independent unofficial reports of a possible outbreak (pending or after review) · direct corridor connectivity (weight ≥ 0.25 in the partial scenario) to an area with ≥ 20 cases in 21 days |
| 0 | NO CURRENT EVIDENCE | none of the above. *This does not necessarily establish zero cases.* |
| — | INSUFFICIENT INFORMATION | a previously affected area (last report within a year, no end declaration) without official data for more than 28 days |

### Rationale for the numbers

* **20 cases / 21 days (HIGH)**: an outbreak producing roughly one confirmed case
  a day across an incubation period has escaped single-chain containment; this
  is above the size of most historical Ebola introductions that were contained
  early.
* **300 cases / 21 days (CRITICAL)**: sustained incidence of about 100 confirmed
  cases a week is in the range of the largest Ebola epidemics on record and
  stresses isolation, contact-tracing and burial capacity anywhere.
* **P(R_t > 1) thresholds**: growth evidence matters more than size for small
  outbreaks; 0.75 and 0.9 are conventional "likely" and "very likely" cut-offs.
* **Imported cases** are ELEVATED for one incubation period (contacts under
  follow-up; secondary cases possible), then WATCH until 42 days.
* **Unofficial signals** can raise an area to WATCH at most. They never
  produce ELEVATED or higher on their own.
* **Connectivity** WATCH describes vulnerability, and says so in its text.

### Validation status

These thresholds are expert-set and anchored in natural history; they have
not been statistically validated against outcomes. Ebola Watch evaluates them
retrospectively by applying them to past official series (the level trajectory
is reproducible from stored assessments) and by tests that pin the behaviour
for each scenario. Changing a threshold changes the version string.

## Confidence

Confidence starts high and is lowered by:

| Condition | Result |
|---|---|
| No official data for the area | low ("absence of reports is not evidence of absence of cases") |
| Latest official data > 14 days old | low |
| Latest official data 8–14 days old | at most moderate |
| One surveillance concern | at most moderate |
| Two or more surveillance concerns | low |
| Models disagree substantially | low |
| Figures machine-extracted from narrative bulletins | at most moderate |
| Level based on unofficial reports | low |

Surveillance concerns come from observable indicators
(`severity/surveillance.py`): contact follow-up below 80%, half or more of
recent deaths occurring in the community, estimated case ascertainment below
60%, and official data older than 14 days. Unreported indicators are
"unknown", never assumed poor.

**Robustness floor.** When the level rests on official confirmed counts at least
twice the threshold and data are ≤ 14 days old, confidence is at least moderate:
under-reporting would raise severity, not lower it.

## Underestimation risk

`underestimation_risk` is set when surveillance concerns exist, when a
previously affected area has gone silent, or when a case was detected
elsewhere after travel from an area reporting none. The dashboard then states:
"incomplete surveillance creates a credible risk that severity is
underestimated." A data void is reported as *insufficient information*, never
as high severity.

## Alerts

* Severity changes based on official data are published automatically, with
  their triggers, and low-confidence HIGH/CRITICAL changes are queued for
  review.
* Any alert that relies on unofficial reports is held for human review and
  published only after approval.
* Retractions keep a public, non-sensitive correction record.
