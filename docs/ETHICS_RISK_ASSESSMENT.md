# Ethical risk assessment

Ebola Watch studies people at one of the most frightening moments of their
lives. This assessment lists foreseeable harms, the controls that are
*implemented in code* (with the file that enforces them), and the residual
risks that remain. It follows the spirit of the WHO guidelines on ethical
issues in public-health surveillance (2017) and WHO guidance on social
listening.

Assessment date: 2026-10-18. Review it whenever a source, output channel or
model changes.

## 1. Scope boundaries enforced by design

| Commitment | Enforcement |
|---|---|
| Not a medical service; no treatment, medicine, vaccine, dosage or diagnostic advice | `safety/scope.py` classifies every question; clinical and personal-symptom requests receive a referral and no data. Disclaimer on every page, API description, report and export. Tested (scenario 18). |
| No patient, contact, witness or user identification | No table holds identities, contact lists, travel histories or household data (`db/models.py`). Identity requests are refused (scenario 19). |
| No individual tracking or targeting | Tracking and operational-targeting requests refused; transport analysis works on administrative units only. |
| Untrusted text cannot control the system | `safety/untrusted.py` sanitises all fetched text and flags instruction-like content; no code path derives configuration, thresholds or publication decisions from text; the optional LLM translator receives text inside an untrusted-data block, returns schema-validated JSON and is never used for decisions (scenario 16). |

## 2. Harm analysis

| Risk | Who is harmed | Controls in code | Residual risk |
|---|---|---|---|
| **Privacy harm** from republishing public posts | posters, people named in posts | PII redaction before storage (names after cues, phones, e-mails, handles, ID numbers, exact ages) — `privacy/redaction.py`; authors stored only as keyed HMAC pseudonyms; social-post URLs not stored; post text never published (clusters are paraphrased) — `views.signals_public`; 30-day retention of social text — `pipeline/run.apply_retention` | Heuristic name detection misses some names; mitigated because stored text is never published and expires |
| **Re-identification of small areas** | patients, households, villages | Public resolution capped at first-level units; small-area roll-up, small-count (`<5`) and complementary suppression — `privacy/policy.py`; no endpoint serves health-zone data; query guard throttles enumeration of filter combinations — `privacy/query_guard.py` (scenario 17) | Official bulletins already publish health-zone names; we do not amplify them at finer resolution |
| **Stigmatisation of communities** | ethnic, religious, linguistic, national groups; refugees and displaced people | No demographic, ethnic, religious or nationality variables anywhere in the models; severity depends only on transmission evidence; mobility represented only as corridors between administrative units; wording reviewed to avoid blaming travellers | Users can still draw stigmatising conclusions from maps; mitigated by caveats on connectivity ("not transmission", "vulnerability") |
| **Targeting of responders, facilities or patients** | health workers, treatment centres, burial teams | No facility, team, patient-transfer or route-level data are collected or displayed; transport corridors are generalised to administrative units; operational-targeting questions refused | Corridor data could in principle inform movement restrictions; they contain nothing not on public maps |
| **Misinformation amplification** | public | Near-duplicate collapse, independence requirement, coordination detection, staleness detection, fabricated-official-announcement handling (official attribution without an official document is not corroboration); unverified material labelled UNVERIFIED; alerts relying on unofficial reports require human approval (scenarios 3, 7, 20) | Sophisticated, diverse fabricated campaigns could pass heuristics; human review is the backstop |
| **False reassurance** | public, responders | "Absence of reports is not evidence of absence" stated in Level 0 text; insufficient-information status for silent areas; underestimation-risk flag; zero is only stored when an official source states it | Areas with no surveillance and no signals appear as Level 0 with low confidence |
| **Unnecessary panic** | public | Calibrated intervals, scenario labelling beyond 28 days, no sensational wording, severity separated from confidence, connectivity watch explained as vulnerability | Large headline estimates may still alarm; methodology is linked from every estimate |
| **Misuse of forecasts** (e.g. to justify border closures or discrimination) | travellers, displaced people | Forecasts labelled as uncertain; connectivity scores are relative and non-probabilistic; no individual-level outputs | Cannot be prevented technically; documented in LIMITATIONS and the licence (COSL §4.8/§4.9 prohibit surveillance and coercive uses) |
| **Fabricated statistics** | everyone | Numbers appear only from stored observations or models; "Insufficient evidence for a reliable numerical estimate." and "insufficient for numerical forecasting" are first-class outputs; synthetic data flagged end to end and refused in production | Extraction errors from narrative bulletins: consistency checks + review queue; quotes stored for verification |
| **Upstream data producers' interests** | national institutes, researchers | Courtesy conditions enforced by `requires_acknowledgement` (HDX/INRB data off by default); attribution on every figure | Operators who acknowledge without contacting producers |
| **Security compromise** | everyone | Secrets only from environment; production refuses default secrets and SQLite; API keys stored as HMAC; role checks; audit log of administrative actions; rate limits; request-size limits; CSP and security headers; defusedxml for feeds; read-only containers with dropped capabilities | Single-instance in-memory rate limiting; a shared limiter is recommended behind a proxy |

## 3. Publication review before release

Before publishing new outputs, the operator should confirm:

1. Does the output reveal anything finer than first-level administrative units?
2. Does it include any text taken verbatim from a social-media post?
3. Could it be used to locate a patient, responder, facility or household?
4. Does it name or imply a community, ethnicity, nationality or religion as a
   risk factor?
5. Is every number traceable to an official observation or a model run, with
   its uncertainty and data date?
6. Is unofficial information labelled unverified, and has any alert that relies
   on it been reviewed by a person?

Where a risk is material, the output is aggregated further, delayed, suppressed
or withheld.

## 4. Human oversight

Review is required for: alerts relying on unofficial reports, low-confidence
HIGH/CRITICAL changes, machine-extracted figures with ambiguity or failed
checks, source corrections larger than 5%, auto-registered outbreaks,
injection-flagged or low-resource-language signals, and public error reports.
Decisions, retractions and transport-status changes are audit-logged
(`review/queue.py`). Communities and organisations can report errors through
the dashboard or `POST /api/v1/error-reports`; reports are stored without
personal data and reviewed by people.

Without a server (GitHub Pages deployment), GitHub processes some of this data:
the database is stored encrypted in a private repository; reviewers see
redacted source excerpts in private issue comments, which are deleted after the
raw-content retention period; only aggregate outputs are published. Public
error reports are GitHub issues and therefore public, so the form warns against
including personal information. The public site has no input fields, which
removes the query-reconstruction and question-answering attack surface.

Translations can distort meaning. The dashboard's machine-assisted
translations carry a notice and a one-click link to the authoritative English
version until a native speaker has reviewed them; figures are never passed
through translation (numbers are formatted, not translated, and are marked
`translate="no"` for browser translators); severity levels, confidence and the
distinction between official, estimated and unverified figures use fixed
glossary terms; and anything without a reviewed template stays in English
rather than being guessed (docs/TRANSLATION.md).

## 5. Licence and use restrictions

The software is released under the Christian Open Source License (COSL) 1.0,
which prohibits, among other uses, mass surveillance and population profiling
(§4.8), intelligence and military use (§4.6–4.7) and coercion (§4.9). Ebola
Watch's architecture — aggregate statistics only, no individual tracking, no
profiling of groups — is designed to stay within those terms. Operators should
nevertheless obtain their own legal advice on whether a particular deployment
(for example, at scale over public social media) is consistent with COSL §4.8
and with local data-protection law.

## 6. Known gaps

* Lexicons for most priority languages are drafts awaiting native-speaker review;
  until then those languages are routed to people rather than analysed.
* Image and screenshot forensics are not implemented; "screenshot of an official
  letter" claims are treated as unverified text.
* Detection lead time and false-positive rates cannot yet be measured.
