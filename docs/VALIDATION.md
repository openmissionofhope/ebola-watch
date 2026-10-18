# Validation and evaluation

Results below were produced on **2026-10-18** with model `ew-epi-1.0.0`. They
are reproducible with the commands shown. Negative results are reported as
computed.

## 1. Automated tests

`pytest` → **67 passed** (offline; synthetic data only).
`pytest -m live` → **3 passed** (WHO Disease Outbreak News, World Bank,
OpenStreetMap Overpass, contacted live).

The 20 required scenarios:

| # | Scenario | Test |
|---|---|---|
| 1 | Official reporting delayed by two weeks | `test_epi.py::test_scenario_01_two_week_reporting_delay_widens_nowcast` |
| 2 | Government reports zero while lab-confirmed cases are documented elsewhere | `test_scenarios.py::test_scenario_02_zero_report_while_lab_confirmed_case_detected_elsewhere` |
| 3 | Rumour spread through 100 reposts | `test_nlp_evidence.py::test_scenario_03_rumour_with_100_reposts_is_one_origin` |
| 4 | Several genuinely independent sources report the same concern | `test_nlp_evidence.py::test_scenario_04_independent_sources_raise_possible_emerging_signal`, `test_scenarios.py::test_scenario_04_unofficial_alert_requires_human_review_before_publication` |
| 5 | French and Lingala posts describe the same event | `test_nlp_evidence.py::test_scenario_05_french_and_lingala_posts_link_to_same_event` |
| 6 | Untranslated local-language report with ambiguous terms | `test_nlp_evidence.py::test_scenario_06_ambiguous_low_resource_language_escalates_to_review` |
| 7 | Outdated report reposted as new | `test_nlp_evidence.py::test_scenario_07_outdated_report_reposted_is_stale` |
| 8 | Imported case without sustained local transmission | `test_scenarios.py::test_scenario_08_imported_case_without_local_transmission` |
| 9 | Railway exists but is not operational | `test_transport.py::test_scenario_09_...` |
| 10 | River without verified passenger connection | `test_transport.py::test_scenario_10_...` |
| 11 | Ferry service stops operating | `test_transport.py::test_scenario_11_ferry_stops_operating` |
| 12 | Region with no recent surveillance data | `test_scenarios.py::test_scenario_12_region_without_recent_surveillance_is_insufficient_information` |
| 13 | Observations insufficient for numerical forecasting | `test_epi.py::test_scenario_13_insufficient_observations_for_forecasting`, `test_api.py::test_insufficient_evidence_is_explicit_in_api` |
| 14 | Model assumptions produce sharply different projections | `test_epi.py::test_scenario_14_disagreeing_models_are_shown_not_averaged` |
| 15 | Authorities revise historical totals | `test_scenarios.py::test_scenario_15_revised_historical_totals_are_kept_not_overwritten` |
| 16 | Source contains malicious instructions for the AI pipeline | `test_scenarios.py::test_scenario_16_malicious_instructions_in_a_source_are_inert`, `test_safety_privacy.py::test_untrusted_text_is_normalised_and_flagged` |
| 17 | API user tries to reconstruct suppressed geography | `test_api.py::test_scenario_17_suppressed_geography_cannot_be_reconstructed`, `test_safety_privacy.py::test_small_area_and_complementary_suppression` |
| 18 | User requests medicine recommendations | `test_api.py::test_scenario_18_medicine_request_is_declined_with_referral` |
| 19 | User requests patient identities | `test_api.py::test_scenario_19_patient_identity_request_is_refused` |
| 20 | Coordinated misinformation campaign | `test_nlp_evidence.py::test_scenario_20_coordinated_campaign_does_not_manufacture_corroboration` |

Other tests cover extraction, Rt recovery on a synthetic outbreak with known R,
mortality back-calculation recovering a known ascertainment, interval coverage
on synthetic backtests, WIS, small-outbreak extinction, connectors against
mocked HTTP (including 403/429 handling and XML entity attacks), manual import
validation, report content, retention, API roles and security headers, and the
optional translator with a stub client.

Database migrations were applied to SQLite and to PostgreSQL 16 + PostGIS 3.4
(Docker); the full pipeline ran on PostGIS and a spatial query
(`ST_Contains`) returned the expected province. `alembic check` reports no
drift between models and migrations.

## 2. Extraction accuracy against an independent source

WHO bulletin figures extracted by `parsing/who_don.py` were compared with the
structured HDX/INRB dataset (an independent transcription of national
situation reports) for the 2026 DRC Bundibugyo outbreak:

* **National confirmed cases and deaths: 20 of 20 overlapping dates match
  exactly** (6 June – 6 October 2026).
* Province totals (Ituri, Nord-Kivu) agree with sums of health-zone values
  within 0–2% (differences reflect provincial versus health-zone aggregation and
  three unmatched health-zone names).

## 3. Forecast backtesting

Weekly forecast origins; forecasts of new reported confirmed cases; observed
values from the later series.

### Real outbreak — DRC 2026, WHO bulletins only (default configuration)

| Horizon | n | 50% coverage | 90% coverage | Mean WIS | Median relative bias |
|---|---|---|---|---|---|
| 7 days | 6 | 0.67 | 0.83 | 93 | −9% |
| 14 days | 5 | 0.60 | 0.80 | 214 | −8% |
| 28 days | 5 | 0.60 | 1.00 | 512 | −9% |

### Real outbreak — DRC 2026, with daily national data (HDX, acknowledged)

| Horizon | n | 50% coverage | 90% coverage | Median relative bias |
|---|---|---|---|---|
| 7 days | 15 | 0.80 | 1.00 | −10% |
| 14 days | 14 | 0.71 | 1.00 | −9% |
| 28 days | 12 | 0.75 | 1.00 | −11% |

### Synthetic outbreaks (known truth; labelled SYNTHETIC)

| Scenario | 7-day 50% / 90% | 14-day 50% / 90% | 28-day 50% / 90% |
|---|---|---|---|
| 1 — growth then decline | 0.78 / 1.00 | 0.73 / 1.00 | 0.60 / 1.00 |
| 2 — sustained growth (R = 1.3) | 0.52 / 1.00 | 0.64 / 0.95 | 0.55 / 1.00 |
| 3 — slow decline (R = 0.9) | 0.70 / 1.00 | 0.64 / 0.95 | 0.60 / 0.95 |

### Interpretation

* Evaluation sets are small (5–23 origins per horizon); the dashboard marks
  real-data results as "too few evaluated forecasts for a calibration
  judgement".
* With daily data, intervals are **conservative** (90% coverage 1.0, 50%
  coverage 0.7–0.8): wider than necessary. With fortnightly bulletins only,
  coverage is close to nominal at 7–14 days but the model **under-predicted
  during the rapid growth of July 2026** (the 15 July origin's 14-day forecast
  missed high).
* Medians are biased low by about 10% on the real series.
* Geographic-expansion (newly affected health zones within 14 days): one
  evaluable origin in the default configuration (Brier 0.004) — not yet
  informative.
* Calibration of the R random-walk SD (σ ∈ {0.03 … 0.2}) changed 14-day mean WIS
  by less than 7% and did not change coverage; σ = 0.12 was kept.

## 4. Burden estimates — plausibility checks

For the DRC (6 October 2026; 8,728 confirmed cases, 4,205 confirmed deaths),
the mortality-based method estimates **10,800–31,800** cumulative symptomatic
infections (median ≈ 17,400; ascertainment ≈ 50%, 90% interval 27–81%). Fewer
than 1% of Monte Carlo draws were inconsistent with the data. The estimate is
driven mainly by the IFR prior (20–50%) and the death-ascertainment prior
(50–95%); it should be read as "roughly one to three times the confirmed count",
not as a precise figure.

For comparison, Imperial College London estimated "approximately 400 to 900
cases" by 20 May 2026 (values over 1,000 not excluded) when 516 suspected and 8
confirmed cases had been reported — a different method at a much earlier stage;
it is stored for reference, pending quote verification.

On a synthetic outbreak with known 50% ascertainment, the method's 90% interval
contained both the true infection total and the true ascertainment
(`test_epi.py::test_deaths_backcalculation_recovers_ascertainment`).

## 5. Event-based surveillance on real news (2026-10-18)

With GDELT news (en, fr, sw, pt, ar), the system:

* grouped 53 Kenyan items (33 independent origins) reporting a **second**
  confirmed case in Kenya — one more than the official data then held — and
  raised "Independent reports suggest official reporting may be incomplete" as
  an **unpublished alert awaiting review**;
* classified Madagascar preparedness news (a traveller intercepted at screening)
  as surveillance activity rather than a case report;
* attributed a headline about DRC totals and a Kenyan case to the DRC without
  carrying DRC totals over to Kenya.

Detection lead time and false-alert rates cannot be measured yet (no labelled
history of reviewed signals and outcomes).

## Reproduce

```bash
.venv/bin/pytest && .venv/bin/pytest -m live
.venv/bin/ebolawatch init-db && .venv/bin/ebolawatch run
curl -s localhost:8000/api/v1/evaluation | jq
```
