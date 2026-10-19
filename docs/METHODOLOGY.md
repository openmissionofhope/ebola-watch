# Scientific methodology

Ebola Watch answers one question: *given everything we know, and everything we
know we may be missing, how much Ebola probably exists, and how much might
exist in the coming weeks?* This document describes how each number is
produced, what it assumes, and when the system declines to produce one.

Model version: `ew-epi-1.0.0`. Parameters version: see
`data/parameters/pathogens.yaml` (`version`). Every stored model run records
both, the parameters used, and a hash of its inputs.

## 1. Categories are never combined

Each quantity has its own field in the database, API and dashboard:

| Category | Source | Example field |
|---|---|---|
| Laboratory-confirmed cases / deaths | official bulletins | `official.confirmed_cases` |
| Official probable cases / deaths | official bulletins | `official.probable_cases` |
| Official suspected cases / deaths | official bulletins | `official.suspected_cases` |
| Imported cases (subset of a country's reported cases) | official bulletins | `official.imported_cases` |
| Medically evacuated patients | official bulletins | stored with `transmission=medevac`, excluded from local counts and exportation inference |
| Unverified outbreak signals | public media, social media | `/signals` (paraphrased clusters) |
| Estimated cumulative symptomatic infections | model | `estimated_total` |
| Estimated recent (14-day) symptomatic infections | model | `recent_incidence` |
| Forecast additional reported cases / infections | model | `forecasts.targets.*` |
| Forecast geographic expansion | model | `expansion` |
| Data-quality uncertainty | indicators | `surveillance.indicators` |

Model estimates are labelled as such everywhere and are never added to
reported counts. Unverified signals never contribute to case numbers.

## 2. Official data: provenance, vintages, revisions

* Every observation stores the source, the observation date (`as_of`, or a
  period for incident values), the publication date, the retrieval time, the
  jurisdiction, the case-definition category, the data vintage, a citation and
  (for text-extracted figures) the supporting sentence.
* Observations are **append-only**. When a source revises a value for the same
  date, a new row is stored that `supersedes` the old one. Revisions larger than
  5% are held for human review.
* Series are built per **outbreak** (an outbreak registry with cited
  declaration and end dates; unlisted outbreaks found in WHO bulletins are
  auto-registered *for review*). Series from different outbreaks are never
  concatenated.
* For each date, the latest publishable vintage wins (verified >
  auto-validated; pending, disputed and retracted rows are excluded). When
  several sources report the same date, a source-priority order is used and
  the disagreement is recorded and shown.
* **A missing report is not a zero.** Weeks after the last report are absent,
  not zero-filled. Only explicit official statements ("no new cases since…")
  are stored as zeros.

### Extraction from bulletins

WHO Disease Outbreak News items are prose. The extractor
(`parsing/who_don.py`) emits a figure only when a sentence states a cumulative
count with a case category and a date. It deliberately skips increments
("additional", "new", "weekly", "in the last 24 hours"), figures for single
health zones, and narrative figures without a date. Multi-country totals are
split only when the text states the component, and any derived remainder is
routed to review. Consistency checks include deaths ≤ cases, sub-national ≤
national, and agreement between computed and stated case-fatality ratios.

The ECDC page (`parsing/ecdc.py`) states the national confirmed totals with a
"data up until" date, then one sentence per province without repeating
"confirmed". Provincial figures are published automatically only when they
add up exactly to the national cases and deaths on the same page, which shows
they are the complete confirmed breakdown; otherwise they go to review.
Paragraphs that relay media reports are skipped, and cases in other countries
are taken only from explicit ordinals ("the first confirmed imported case",
"a second case") as lower bounds. When WHO and ECDC report the same date, the
WHO figure is used and any disagreement is recorded.

### Weekly incidence

Irregular cumulative reports are converted to weekly incidence by spreading
each reporting interval's increment uniformly over its days. Weeks built from
intervals longer than three days are marked as interpolated, and when recent
reports are more than a week apart the R_t posterior is widened by the ratio
(mean interval / 7): smoothed data carry less information than they appear to.

## 3. Reporting delay and nowcasting

Three distinct delays are handled separately:

1. **Publication delay** (observation date → today). The baseline renewal
   simulation is run forward from the last observation to today to produce a
   *nowcast of cumulative reported cases*, with an interval that widens with the
   gap (tested: a two-week delay gives a wider interval than a one-day delay,
   and unpublished cases are projected rather than assumed to be zero).
2. **Infection → report delay** (incubation, mean 11.4 days, range 2–21; plus
   onset-to-report, an explicit assumption of 3–10 days). Infections in the last
   two weeks are mostly not yet reported; *recent symptomatic infections* are
   estimated as the cases projected to be reported over the next delay window,
   divided by the estimated ascertainment fraction.
3. **Backfill of data already published** (revisions). Handled by vintages;
   where onset-dated series with multiple vintages become available, a
   reporting-triangle nowcast can be added (not yet implemented; see
   LIMITATIONS).

## 4. Reproduction number of reported cases

R_t is estimated with the Cori et al. (2013) gamma-conjugate method on weekly
incidence and a weekly-discretised serial interval (gamma, mean 15.3 days, SD
9.3; WHO Ebola Response Team, NEJM 2014 — an Ebola-virus estimate *transferred*
to other species with the mean drawn from 13–17.5 days). Posteriors are mixed
over serial-interval draws and widened by the observed Pearson dispersion of
one-step-ahead predictions. Prior: Gamma(shape 1, scale 5). The window is two
weeks, extended to four or six for small outbreaks before R_t is declared
unidentifiable (< 10 cases in the window).

R_t of *reported* cases moves when ascertainment changes as well as when
transmission changes. This caveat accompanies every R_t value.

## 5. Estimating true epidemic size

No method multiplies reported counts by an assumed under-reporting factor for
"weak surveillance". Under-ascertainment is inferred from evidence or not at all.

### 5.1 Mortality-based back-calculation (primary method)

Reported deaths are generally better ascertained than cases. Let D(t) be
cumulative reported deaths (same case category as the cases), p_D the fraction
of fatal symptomatic infections that appear in those deaths, IFR the fatality
ratio among all symptomatic infections, and d the mean onset-to-death delay.
Symptomatic infections with onset by t − d are approximately
D(t) / (p_D · IFR). Comparing this with cases reported by the corresponding
date gives the ascertainment fraction ρ, applied to cases reported by t:

    N(t) ≈ C(t) / ρ,   ρ = C(t − d + r) / [D(t) / (p_D · IFR)]

Monte Carlo over 4,000 draws of the priors:

| Parameter | Prior | Status |
|---|---|---|
| IFR, Bundibugyo virus | 20–50% (Beta matched to the range) | assumption; brackets the 30–50% reported-case CFR range cited by WHO (DON 2026-DON602) and allows for missed mild illness |
| IFR, Ebola virus / Sudan virus | 30–70% / 30–65% | assumption; refine with outbreak-specific estimates |
| p_D (death ascertainment) | uniform 50–95% | assumption |
| d (onset → death, mean) | 7–12 days | assumption informed by EVD literature |
| r (onset → report, mean) | 3–10 days | assumption |

Draws in which the assumptions imply fewer infections than reported cases are
counted (`fraction_draws_inconsistent`); ρ is capped at 1 in those draws, and if
most draws are inconsistent the estimate carries a warning that the priors do
not fit the outbreak. A single fixed CFR is never used across species.

The estimate is **insufficient** with fewer than 20 reported deaths or fewer
than three reports.

### 5.2 Exportation-based inference

Confirmed cases detected after travel to places with strong surveillance
(excluding medically evacuated patients) give an independent estimate:

    N ≈ X / (V / P · T · p_detect)

with X the exported cases (Jeffreys gamma posterior), V daily travellers from
the catchment, P its population, T the detection window and p_detect the
destination's detection probability. **No travel volumes ship with the
software.** Until an operator adds a sourced catchment entry to
`data/parameters/mobility_scenarios.yaml`, the method reports insufficient
evidence. The assumption that infected people travel like everyone else is
listed (it is likely violated, since illness reduces travel).

### 5.3 Floors and published estimates

Confirmed + probable reported cases form a floor, not an estimate. Published
estimates by other groups (e.g. Imperial College London's 20 May 2026 estimate
for the Bundibugyo outbreak) are stored verbatim with citation and shown for
comparison, pending reviewer verification of the quote.

### 5.4 Combining methods and showing disagreement

The headline is never an average of disagreeing models. With one usable
method, the headline is that method's 90% interval (floored at reported
cases). When two methods' 90% intervals do not overlap, the headline is the
envelope of both, confidence is set to low, and the disagreement is displayed.

Estimate confidence: **high** only with two agreeing methods, ≥ 8 weeks of data
and data ≤ 7 days old; **low** with data > 14 days old, interval ratio > 4,
> 20% inconsistent draws, or model disagreement; otherwise **moderate**.

## 6. Forecasting

### Model A — renewal / branching simulation (primary)

    R_{w+1} = R_w · exp(drift + σ ε),  ε ~ N(0,1),  σ = 0.12/week
    I_w ~ NegBin(mean = R_w Λ_w, size = k)

σ is a default checked by backtesting (`epi.backtest.calibrate_sigma`): on the
2026 DRC series, 14-day mean WIS varied little across σ = 0.03–0.2 and 90%
coverage was 1.0 throughout, so the default was kept (it mainly widens the
long-horizon scenarios). R_0 of the simulation is drawn from the R_t posterior. For small infectiousness
(Λ < 50) the offspring dispersion k = 0.3 (assumption reflecting
superspreading) is scaled by Λ, so small outbreaks can go extinct in
simulation and the **probability of continued transmission** is informative.
Otherwise k is the observation-level dispersion estimated from the data.

Horizons: 7, 14, 21, 28, 42, 56 and 84 days. Beyond 28 days results are
labelled **scenarios**: assumptions about response and surveillance dominate
them. Three scenarios are always produced:

| Scenario | Drift in R |
|---|---|
| Improving containment | R × 0.9 per week for four weeks, then held (× 0.66) |
| Continuation of current conditions | no drift |
| Deteriorating surveillance and response | R × 1.1 per week for four weeks, then held (× 1.46) |

Simulated R is capped at 3.0, above reproduction numbers reported for Ebola
outbreaks, so scenario tails cannot run away.

Targets are new *reported* confirmed cases (verifiable and backtested) and new
*symptomatic infections* (reported forecast shifted by the infection-to-report
delay and divided by the ascertainment draws).

### Model B — log-linear trend (comparison)

A weighted log-linear fit to the last six weeks, extrapolated with parameter
and Poisson noise. If the 28-day medians differ by more than a factor of two or
the 90% intervals do not overlap, `substantial_disagreement` is reported.

### Insufficient data

No numerical forecast is produced with fewer than four weeks of data, fewer
than ten cumulative cases, data older than 28 days, or an unidentifiable R_t.
The output then reads "Available observations are insufficient for numerical
forecasting."

### Geographic expansion

*Within an outbreak*: newly affected units (e.g. health zones) per week follow a
Poisson rate with a Gamma(0.5 + k, exposure) posterior from the last six weeks
of official affected-unit counts, giving P(≥ 1 newly affected unit) per horizon.

*Between areas*: see §8 (transport). Results are a relative, scenario-based
ranking, not probabilities.

## 7. Evaluation

`epi/backtest.py` refits the model at weekly origins using only data observed
up to each origin and scores 7-, 14- and 28-day forecasts of new reported cases
against what was later reported: 50% and 90% interval coverage, weighted
interval score (Bracher et al. 2021), median relative bias, MAE and a PIT
histogram. Expansion forecasts are scored with the Brier score. Evaluations run
on (a) the real official series of each current outbreak and (b) synthetic
outbreaks with known truth, which are labelled SYNTHETIC. Observed targets are
interpolated only between reports at most 16 days apart; others are skipped.

Results are stored and shown at `/evaluation` and in the dashboard, including
poor results. The current numbers and their interpretation are in
`VALIDATION.md`.

Detection lead time and false-positive alert rates require a history of
reviewed signal clusters with later official outcomes; until that history
exists the dashboard says "not yet estimable" rather than inventing a figure.

## 8. Transport connectivity

Connectivity is not transmission. Ebola spreads by direct contact with the body
fluids of symptomatic or deceased people; nobody transmits before symptoms, and
incubation is 2–21 days. Travel matters because a person in the incubation
period or early illness can move between areas.

The network (`transport/network.py`) links administrative units by corridor
edges for roads, rail, rivers, lakes, air and coarse informal movement. Each
edge records physical status (documented / unverified), service status
(operational / intermittent / seasonal / suspended / non-operational /
unknown), verification level, sources and seasonal or disruption notes.
OpenStreetMap checks can document that infrastructure is mapped; they never
establish that a passenger service runs.

Edge weight = mode propensity × service factor. Mode propensities (road 1.0,
rail 0.6, river 0.5, lake 0.4, air 0.3, informal 0.3) are relative scenario
weights, not measured volumes. Suspended and non-operational services weigh 0.
**Unknown** services are evaluated under three scenarios (closed 0, partial
0.3, open 1.0); unknown service on unverified infrastructure is halved.

Effective distance (Brockmann & Helbing, 2013) is d_ij = 1 − log P_ij along the
shortest path, with P_ij the share of i's connectivity going to j. Each
non-affected unit receives a relative introduction score Σ I_i exp(−d_ij),
weighted by recent reported incidence in active units, normalised so the top
unit = 1, reported per scenario with its rank range, tier, the share of
unverified links on its best path and the straight-line distance for
comparison. A unit whose rank moves by more than two places across scenarios is
marked as sensitive to assumptions.

## 9. Event-based surveillance

See `ARCHITECTURE.md` §NLP for the pipeline. Key epidemiological rules:

* Keyword matches alone never create an Ebola claim. "Several people are ill"
  without Ebola or haemorrhagic-fever context is an illness cluster; named
  alternative explanations (cholera, malaria, measles, poisoning…) are recorded;
  negation ("it is not Ebola") and satire are detected.
* Near-duplicate posts are one origin. Independence requires a first-hand,
  professional or official origin, a distinct author, and no coordination flag.
* Social-media volume is never converted into case counts. Many reposts of one
  claim are an *information event*.
* When independent reports describe more cases than official data currently
  hold, the assessment is "Independent reports suggest official reporting may be
  incomplete" — an alert that is published only after human review.

## 10. References

* WHO. Ebola disease fact sheet (24 April 2025).
* WHO Ebola Response Team. Ebola virus disease in West Africa — the first 9
  months of the epidemic and forward projections. NEJM 2014;371:1481–95.
* Cori A, Ferguson NM, Fraser C, Cauchemez S. A new framework and software to
  estimate time-varying reproduction numbers during epidemics. Am J Epidemiol
  2013;178:1505–12.
* Bracher J, Ray EL, Gneiting T, Reich NG. Evaluating epidemic forecasts in an
  interval format. PLoS Comput Biol 2021;17:e1008618.
* Brockmann D, Helbing D. The hidden geometry of complex, network-driven
  contagion phenomena. Science 2013;342:1337–42.
* Nishiura H, et al. Early epidemiological assessment of the virulence of
  emerging infectious diseases: a case study of an influenza pandemic. PLoS ONE
  2009;4:e6852 (delay-adjusted fatality ratios).
* McCabe R, et al. Estimation of the size of the outbreak of Ebola disease caused
  by Bundibugyo virus in the Democratic Republic of the Congo, 20 May 2026
  update. MRC Centre for Global Infectious Disease Analysis, Imperial College
  London.
* WHO Disease Outbreak News, 2026-DON602 to 2026-DON619.
