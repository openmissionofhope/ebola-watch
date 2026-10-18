import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import type { ComparisonRow, Evidence, ForecastRow, OfficialSeries, RegionSummary, Subnational, TransportContext } from "../api";
import { ConfidenceBadge, KindTag, SeverityBadge } from "../components/Badges";
import { DataTable, TableToggle } from "../components/DataTable";
import { Async, Insufficient } from "../components/Status";
import { EstimateTile, OfficialTile, SimpleTile } from "../components/Tiles";
import { ComparisonChart } from "../charts/EvalCharts";
import { CumulativeChart } from "../charts/CumulativeChart";
import { RtChart } from "../charts/RtChart";
import { WeeklyBars } from "../charts/WeeklyBars";
import { fmtDate, fmtDateTime, fmtInt, fmtNum, fmtPct, humanize } from "../format";
import { useApi, useDocumentTitle } from "../hooks";
import { T, fmtNumber, placeName, t, tx } from "../i18n";

const SCENARIOS = ["improving", "baseline", "deteriorating"] as const;

/** A number as published (keeps its decimals), in the reader's language. */
function localNum(v: number): string {
  const decimals = (String(v).split(".")[1] ?? "").length;
  return fmtNumber(v, Math.min(decimals, 3));
}

export function RegionDetailPage() {
  const { code = "" } = useParams();
  const summary = useApi<RegionSummary>(`/regions/${encodeURIComponent(code)}/summary`);
  useDocumentTitle(summary.data ? placeName(summary.data.region) : code);
  return <Async state={summary} lines={10}>{(s) => <Detail s={s} />}</Async>;
}

function Detail({ s }: { s: RegionSummary }) {
  const code = s.region.code;
  const series = useApi<OfficialSeries>(`/regions/${code}/official-series`);
  const [scenario, setScenario] = useState<(typeof SCENARIOS)[number]>("baseline");
  const fc = s.forecasts;
  const fcRows: ForecastRow[] | null = fc && !fc.insufficient ? fc.targets?.new_reported_confirmed?.[scenario] ?? null : null;
  const disagreement = s.model_disagreement?.substantial || fc?.comparison?.substantial_disagreement;
  const sev = s.severity;
  const name = placeName(s.region);
  return (
    <>
      <nav aria-label={t("Breadcrumb")} className="small"><Link to="/regions">{t("Regions")}</Link> / {name}</nav>
      <div className="page-head" style={{ marginTop: 6 }}>
        <h1>{name}</h1>
        {s.is_synthetic && <span className="badge synthetic">{t("SYNTHETIC DATA")}</span>}
      </div>
      {s.outbreak && (
        <p className="secondary" style={{ marginTop: -6 }}>
          {tx(s.outbreak.name)} · {t("declared {date}", { date: fmtDate(s.outbreak.declared_on) })}
          {s.outbreak.ended_on ? ` · ${t("declared over {date}", { date: fmtDate(s.outbreak.ended_on) })}` : ""}
          {s.outbreak.auto_registered && ` · ${t("auto-registered from bulletins (pending verification)")}`}
        </p>
      )}

      <section className="card" aria-labelledby="sev-h">
        <div className="card-head">
          <h2 id="sev-h">{t("Assessment")}</h2>
          <span className="small muted">
            {t("Data as of {date} · updated {updated} · model {model}", {
              date: fmtDate(s.data_as_of),
              updated: fmtDateTime(s.latest_update ?? sev.assessed_at),
              model: s.model_version,
            })}
          </span>
        </div>
        <div className="dims">
          <SeverityBadge level={sev.level} status={sev.status} label={sev.label} />
          <ConfidenceBadge confidence={sev.confidence} />
        </div>
        {sev.underestimation_risk && (
          <div className="callout warn"><span aria-hidden="true">⚠ </span>{t("Incomplete surveillance creates a credible risk that severity is underestimated.")}</div>
        )}
        <p style={{ marginTop: 8 }}>{tx(sev.explanation)}</p>
        {sev.description && <p className="small muted">{tx(sev.description)}</p>}
        <div className="grid cols-2">
          <div>
            <h3>{t("Evidence that triggered this level")}</h3>
            {sev.triggers.length ? (
              <ul className="trigger-list">{sev.triggers.map((trg, i) => <li key={i}>{tx(trg.text)}</li>)}</ul>
            ) : (
              <p className="small muted">{t("No triggers: no reliable evidence of current transmission.")}</p>
            )}
          </div>
          <div>
            <h3>{t("What limits confidence")}</h3>
            {sev.confidence_reasons && sev.confidence_reasons.length ? (
              <ul className="trigger-list">{sev.confidence_reasons.map((r, i) => <li key={i}>{tx(r)}</li>)}</ul>
            ) : (
              <p className="small muted">{t("No specific limitations recorded.")}</p>
            )}
          </div>
        </div>
      </section>

      <section className="section" aria-labelledby="known-h">
        <h2 id="known-h">{t("What is officially reported")}</h2>
        <div className="grid tiles">
          <OfficialTile label={t("Confirmed cases")} value={s.official.confirmed_cases} />
          <OfficialTile label={t("Confirmed deaths")} value={s.official.confirmed_deaths} />
          <OfficialTile label={t("Probable cases")} value={s.official.probable_cases} />
          <OfficialTile label={t("Suspected cases")} value={s.official.suspected_cases} />
          {s.official.imported_cases && <OfficialTile label={t("Imported confirmed cases (subset)")} value={s.official.imported_cases} />}
        </div>
      </section>

      <section className="section" aria-labelledby="est-h">
        <h2 id="est-h">{t("What is estimated")}</h2>
        <p className="small muted">{t("Model-based quantities. They are not confirmed cases and are shown separately from official reports.")}</p>
        <div className="grid tiles">
          <EstimateTile label={t("Estimated cumulative symptomatic infections")} est={s.estimated_total} />
          <EstimateTile label={t("Estimated new infections, last 14 days")} est={s.recent_incidence} />
          <EstimateTile label={t("Nowcast: reported cases to date")} est={s.nowcast_reported} />
          <EstimateTile label={t("R_t of reported cases")} est={s.rt} digits={2} />
          {s.ascertainment?.identifiable ? (
            <SimpleTile kind="estimate" label={t("Reporting completeness")} value={`${fmtPct(s.ascertainment.lower_90)}–${fmtPct(s.ascertainment.upper_90)}`}
              sub={`${t("Median {value}", { value: fmtPct(s.ascertainment.median) })} · ${tx(s.ascertainment.method)}`} />
          ) : (
            <div className="tile kind-estimate"><KindTag kind="estimate" /><div className="tile-label">{t("Reporting completeness")}</div>
              <p className="insufficient small" style={{ margin: 0 }}>{t("Not identifiable from available data.")}</p></div>
          )}
        </div>
        {disagreement && (
          <div className="callout danger" role="note">
            <strong>{t("Models disagree substantially.")}</strong> {t("The range shown spans both methods rather than averaging them.")}
            {s.model_disagreement && (
              <span>
                {" "}
                {t("Medians: {list}.", {
                  list: Object.entries(s.model_disagreement.medians).map(([k, v]) => `${humanize(k)} ${fmtInt(v)}`).join("; "),
                })}
              </span>
            )}
            {fc?.comparison?.substantial_disagreement && (
              <span>
                {" "}
                {t("28-day forecast: renewal model median {renewal} vs log-linear model {loglinear}.", {
                  renewal: fmtInt(fc.comparison.renewal_median),
                  loglinear: fmtInt(fc.comparison.loglinear_median),
                })}
              </span>
            )}
          </div>
        )}
        {s.model_reasons && s.model_reasons.length > 0 && (
          <div className="callout"><strong>{t("Model limitations:")}</strong> {s.model_reasons.map((r) => tx(r)).join("; ")}</div>
        )}
      </section>

      <section className="card section" aria-labelledby="tl-h">
        <div className="card-head">
          <h2 id="tl-h">{t("Epidemiological timeline")}</h2>
          {fc && !fc.insufficient && (
            <div role="group" aria-label={t("Forecast scenario")} className="segmented">
              {SCENARIOS.map((sc) => (
                <button key={sc} type="button" aria-pressed={scenario === sc} onClick={() => setScenario(sc)}>{humanize(sc)}</button>
              ))}
            </div>
          )}
        </div>
        {/* keyed by scenario: replaced rather than edited in place, so page translators re-translate it */}
        {fc && !fc.insufficient && fc.scenario_definitions && (
          <p className="small muted" key={scenario}>
            {t("Scenario “{name}”: {definition}. Horizons beyond 28 days are scenarios driven by assumptions, not predictions.", {
              name: humanize(scenario),
              definition: tx(fc.scenario_definitions[scenario]),
            })}
          </p>
        )}
        {fc?.insufficient && <Insufficient text={fc.message ? tx(fc.message) : undefined} reason={fc.reason} />}
        <Async state={series}>
          {(ser) => (
            <>
              <h3>{t("Cumulative reported confirmed cases")}</h3>
              {ser.revisions.length > 0 && (
                <p className="small">{t("Official totals were revised {n} time(s); see the table view.", { n: fmtInt(ser.revisions.length) })}</p>
              )}
              <CumulativeChart key={scenario} points={ser.points} forecast={fcRows} scenario={scenario} estimate={s.estimated_total} nowcast={s.nowcast_reported} />
              {ser.observations_pending_review > 0 && (
                <p className="small muted">
                  {t("{n} extracted value(s) are awaiting human review and are not shown.", { n: fmtInt(ser.observations_pending_review) })}
                </p>
              )}
            </>
          )}
        </Async>
        {s.weekly && s.weekly.week_ends.length > 0 && (
          <>
            <h3 className="section">{t("Weekly reported confirmed cases")}</h3>
            <WeeklyBars weeks={s.weekly.week_ends} counts={s.weekly.reported_confirmed} interpolated={s.weekly.interpolated_days} />
            <p className="small muted">
              {t("Mean interval between official reports in the last six weeks: {days} days.", { days: fmtNum(s.weekly.mean_recent_reporting_interval_days, 1) })}
            </p>
          </>
        )}
        {s.rt_history && s.rt_history.length > 0 && (
          <>
            <h3 className="section">{t("Reproduction number of reported cases (R_t)")}</h3>
            <p className="small muted">{t("R_t of reported cases also changes when case detection changes. Values above 1 indicate growth of reported cases.")}</p>
            <RtChart rows={s.rt_history} />
          </>
        )}
      </section>

      {fc && !fc.insufficient && <ForecastTables s={s} />}

      <section className="card section" aria-labelledby="exp-h">
        <h2 id="exp-h">{t("Geographic expansion")}</h2>
        {s.expansion && !s.expansion.insufficient ? (
          <>
            <p>
              {t("Newly affected {unit}: about {rate} per week recently (90%: {lower}–{upper}).", {
                unit: tx(s.expansion.unit),
                rate: fmtNum(s.expansion.weekly_rate_median, 2),
                lower: fmtNum(s.expansion.weekly_rate_90?.[0], 2),
                upper: fmtNum(s.expansion.weekly_rate_90?.[1], 2),
              })}
            </p>
            <DataTable
              rows={Object.entries(s.expansion.p_new_unit ?? {}).map(([h, p]) => ({ h, p, e: s.expansion?.expected_new_units?.[h] }))}
              columns={[
                { key: "h", header: t("Horizon (days)"), render: (r) => fmtInt(Number(r.h)), numeric: true },
                { key: "p", header: t("Probability of ≥1 newly affected unit ({unit})", { unit: tx(s.expansion.unit) }), render: (r) => fmtPct(r.p), numeric: true },
                { key: "e", header: t("Expected new units (90%)"), render: (r) => (r.e ? `${fmtInt(r.e.median)} (${fmtInt(r.e.lower_90)}–${fmtInt(r.e.upper_90)})` : "—"), numeric: true },
              ]}
            />
            <p className="small muted">
              {tx(s.expansion.method)}. {t("Where expansion may occur is described under transport context, as a relative ranking.")}
            </p>
          </>
        ) : (
          <Insufficient reason={s.expansion?.reason ?? t("No series of affected administrative units is available for this area.")} />
        )}
      </section>

      <Surveillance s={s} />
      <Assumptions s={s} />
      {s.region.level === 0 && <SubnationalSection code={code} />}
      <TransportSection code={code} />
      <ComparisonSection code={code} />
      <EvidenceSection code={code} />
    </>
  );
}

function ForecastTables({ s }: { s: RegionSummary }) {
  const targets = s.forecasts?.targets ?? {};
  const label: Record<string, string> = {
    new_reported_confirmed: t("Additional reported confirmed cases"),
    new_symptomatic_infections: t("Additional symptomatic infections (model-based, includes unreported)"),
  };
  return (
    <section className="card section" aria-labelledby="fc-h">
      <h2 id="fc-h">{t("Forecasts and scenarios")}</h2>
      <p className="small muted">
        {t("Issued {issued} from data as of {date}. Intervals are 50% and 90% prediction intervals. Horizons over 28 days are labelled scenarios.", {
          issued: fmtDateTime(s.forecasts?.issued_at),
          date: fmtDate(s.forecasts?.data_as_of),
        })}
      </p>
      {Object.entries(targets).map(([target, byScenario]) => (
        <div key={target} className="section">
          <h3>{label[target] ?? humanize(target)}</h3>
          <DataTable
            rows={(byScenario.baseline ?? []).map((b) => ({ b, imp: byScenario.improving?.find((x) => x.horizon_days === b.horizon_days), det: byScenario.deteriorating?.find((x) => x.horizon_days === b.horizon_days) }))}
            columns={[
              { key: "h", header: t("Horizon"), render: (r) => t("{n} days", { n: fmtInt(r.b.horizon_days) }), numeric: true },
              { key: "k", header: t("Type"), render: (r) => (r.b.is_scenario ? <KindTag kind="scenario" /> : <KindTag kind="forecast" />) },
              { key: "b", header: t("Current conditions: median (90%)"), render: (r) => `${fmtInt(r.b.median)} (${fmtInt(r.b.lower_90)}–${fmtInt(r.b.upper_90)})`, numeric: true },
              { key: "i", header: t("Improving (90%)"), render: (r) => (r.imp ? `${fmtInt(r.imp.lower_90)}–${fmtInt(r.imp.upper_90)}` : "—"), numeric: true },
              { key: "d", header: t("Deteriorating (90%)"), render: (r) => (r.det ? `${fmtInt(r.det.lower_90)}–${fmtInt(r.det.upper_90)}` : "—"), numeric: true },
              { key: "p", header: t("P(continued transmission)"), render: (r) => fmtPct(r.b.p_continued_transmission), numeric: true },
              { key: "c", header: t("Confidence"), render: (r) => humanize(r.b.confidence) },
            ]}
          />
        </div>
      ))}
    </section>
  );
}

function Surveillance({ s }: { s: RegionSummary }) {
  const sq = s.surveillance;
  return (
    <section className="card section" aria-labelledby="sq-h">
      <h2 id="sq-h">{t("Surveillance quality")}</h2>
      <p>
        <T
          k="Overall evidence base: {level}. This rates the available observations, not the country."
          level={<strong>{humanize(sq?.overall ?? "insufficient_information")}</strong>}
        />
      </p>
      <DataTable
        rows={sq?.indicators ?? []}
        columns={[
          { key: "l", header: t("Indicator"), render: (i) => tx(i.label) },
          { key: "v", header: t("Value"), render: (i) => (i.value === null ? t("Unknown") : i.key.match(/followup|community|ascertainment/) ? fmtPct(i.value) : localNum(i.value)), numeric: true },
          { key: "s", header: t("Assessment"), render: (i) => humanize(i.status) },
          { key: "n", header: t("Note"), render: (i) => tx(i.note) },
        ]}
        empty={t("No indicators available.")}
      />
    </section>
  );
}

type Param = { source?: string; status?: string; range?: number[]; mean?: number; sd?: number; mean_range?: number[] };

function paramValue(v: Param): string {
  if (v.range) return `${localNum(v.range[0])}–${localNum(v.range[1])}`;
  if (v.mean === undefined) return "—";
  const base = v.sd ? t("mean {mean}, sd {sd}", { mean: localNum(v.mean), sd: localNum(v.sd) }) : t("mean {mean}", { mean: localNum(v.mean) });
  return v.mean_range
    ? `${base} (${t("mean range {lower}–{upper}", { lower: localNum(v.mean_range[0]), upper: localNum(v.mean_range[1]) })})`
    : base;
}

function Assumptions({ s }: { s: RegionSummary }) {
  const params = (s.parameters ?? {}) as Record<string, Param | unknown>;
  const paramRows = Object.entries(params)
    .filter(([, v]) => v && typeof v === "object" && "source" in (v as object))
    .map(([k, v]) => ({ k, v: v as Param }));
  return (
    <section className="card section" aria-labelledby="as-h">
      <h2 id="as-h">{t("Methods and assumptions")}</h2>
      {(s.burden_methods ?? []).map((b) => (
        <div key={b.method} className="section">
          <h3>{humanize(b.method)}</h3>
          {b.insufficient ? (
            <Insufficient reason={b.reason} />
          ) : (
            <p>
              {b.method === "reported_floor"
                ? t("Reported floor: {range} (median {median})", { range: `${fmtInt(b.lower_90)}–${fmtInt(b.upper_90)}`, median: fmtInt(b.median) })
                : t("Estimate: {range} (median {median})", { range: `${fmtInt(b.lower_90)}–${fmtInt(b.upper_90)}`, median: fmtInt(b.median) })}
              {b.ascertainment && (
                <> · {t("implied reporting completeness {range}", { range: `${fmtPct(b.ascertainment.lower_90)}–${fmtPct(b.ascertainment.upper_90)}` })}</>
              )}
            </p>
          )}
          {b.assumptions.length > 0 && <ul className="trigger-list small">{b.assumptions.map((a) => <li key={a}>{tx(a)}</li>)}</ul>}
        </div>
      ))}
      {paramRows.length > 0 && (
        <TableToggle label={t("Show model parameters and their sources")}>
          <DataTable
            rows={paramRows}
            columns={[
              { key: "k", header: t("Parameter"), render: (r) => humanize(r.k) },
              { key: "v", header: t("Value"), render: (r) => paramValue(r.v) },
              { key: "st", header: t("Status"), render: (r) => humanize(r.v.status) },
              { key: "s", header: t("Source"), render: (r) => <span lang="en">{r.v.source}</span> },
            ]}
          />
        </TableToggle>
      )}
    </section>
  );
}

function SubnationalSection({ code }: { code: string }) {
  const sub = useApi<Subnational>(`/regions/${code}/subnational`);
  return (
    <section className="card section" aria-labelledby="sub-h">
      <h2 id="sub-h">{t("First-level administrative units")}</h2>
      <Async state={sub}>
        {(d) => (
          <>
            <DataTable
              rows={d.cells}
              columns={[
                { key: "n", header: t("Unit"), render: (c) => (c.region_code.includes(":") ? c.region_name : <Link to={`/region/${c.region_code}`}>{c.region_name}</Link>) },
                { key: "v", header: t("Official confirmed (latest)"), render: (c) => c.display ?? "—", numeric: true },
                { key: "s", header: t("Note"), render: (c) => (c.suppressed ? t("Suppressed to protect small populations") : c.notes.map((n) => tx(n)).join("; ")) },
              ]}
              empty={t("No sub-national official figures are available at a publishable resolution.")}
            />
            <p className="small muted">{tx(d.note)}</p>
          </>
        )}
      </Async>
    </section>
  );
}

function TransportSection({ code }: { code: string }) {
  const tc = useApi<TransportContext>(`/regions/${code}/transport`);
  return (
    <section className="card section" aria-labelledby="tr-h">
      <h2 id="tr-h">{t("Transport connectivity context")}</h2>
      <Async state={tc}>
        {(d) => (
          <>
            <ul className="trigger-list small">{d.caveats.map((c) => <li key={c}>{tx(c)}</li>)}</ul>
            <h3 className="section">{t("Relative connectivity to areas with active transmission")}</h3>
            <DataTable
              rows={d.introduction_ranking.slice(0, 12)}
              columns={[
                { key: "n", header: t("Area"), render: (r) => r.name },
                { key: "t", header: t("Tier"), render: (r) => humanize(r.tier) },
                { key: "r", header: t("Robust to assumptions"), render: (r) => (r.robust ? t("Yes") : t("No — ranking changes across scenarios")) },
                { key: "p", header: t("Broad path"), render: (r) => r.path_names.join(" → ") },
                { key: "m", header: t("Modes"), render: (r) => r.path_modes.map(humanize).join(", ") || "—" },
                { key: "u", header: t("Unverified links"), render: (r) => fmtPct(r.share_unverified_links), numeric: true },
                { key: "km", header: t("Straight-line km"), render: (r) => fmtInt(r.straight_line_km_from_nearest_source), numeric: true },
              ]}
              empty={t("No ranking: no active transmission sources or no corridor data.")}
            />
            <TableToggle label={t("Show {n} corridors touching this area", { n: fmtInt(d.edges.length) })}>
              <DataTable
                rows={d.edges}
                columns={[
                  { key: "c", header: t("Corridor"), render: (e) => e.corridor ?? e.key },
                  { key: "m", header: t("Mode"), render: (e) => humanize(e.mode) },
                  { key: "p", header: t("Infrastructure"), render: (e) => humanize(e.physical_status) },
                  { key: "s", header: t("Passenger service"), render: (e) => humanize(e.service_status) },
                  { key: "v", header: t("Verification"), render: (e) => humanize(e.verification) },
                  {
                    key: "n",
                    header: t("Notes"),
                    render: (e) => [e.seasonal_note, e.disruption_note, e.notes].filter(Boolean).map((n) => tx(n)).join(" ") || "—",
                  },
                ]}
              />
            </TableToggle>
          </>
        )}
      </Async>
    </section>
  );
}

function ComparisonSection({ code }: { code: string }) {
  const cmp = useApi<ComparisonRow[]>(`/regions/${code}/forecast-comparison`);
  return (
    <section className="card section" aria-labelledby="cmp-h">
      <h2 id="cmp-h">{t("Earlier forecasts compared with what was reported")}</h2>
      <Async state={cmp}>
        {(rows) => (
          <>
            <ComparisonChart rows={rows} />
            <TableToggle>
              <DataTable
                rows={rows}
                columns={[
                  { key: "o", header: t("Forecast from"), render: (r) => fmtDate(r.origin_date ?? r.data_as_of) },
                  { key: "src", header: t("Type"), render: (r) => (r.source === "backtest" ? t("Retrospective (backtest)") : t("Issued forecast")) },
                  { key: "h", header: t("Horizon (days)"), render: (r) => fmtInt(r.horizon_days), numeric: true },
                  { key: "m", header: t("Median"), render: (r) => fmtInt(r.median), numeric: true },
                  { key: "i", header: t("90% interval"), render: (r) => `${fmtInt(r.lower_90)}–${fmtInt(r.upper_90)}`, numeric: true },
                  { key: "ob", header: t("Observed"), render: (r) => (r.observed === null || r.observed === undefined ? t("Not yet known") : fmtInt(r.observed)), numeric: true },
                ]}
              />
            </TableToggle>
          </>
        )}
      </Async>
    </section>
  );
}

function EvidenceSection({ code }: { code: string }) {
  const ev = useApi<Evidence>(`/regions/${code}/evidence`);
  return (
    <section className="card section" aria-labelledby="ev-h">
      <h2 id="ev-h">{t("Evidence")}</h2>
      <Async state={ev}>
        {(d) => (
          <div className="grid cols-2">
            <div>
              <h3>{t("Official sources used")}</h3>
              <ul className="plain">
                {d.official_sources.slice(0, 12).map((o, i) => (
                  <li key={i}>
                    {o.official ? <KindTag kind="official" /> : <KindTag kind="unverified" />}{" "}
                    <span className="small muted">{fmtDate(o.published_at)} · <span lang="en">{o.source}</span></span>
                    <div lang="en">{o.url ? <a href={o.url} rel="noopener noreferrer">{o.title}</a> : o.title}</div>
                  </li>
                ))}
              </ul>
              <p className="small muted">
                {t("Observation validation: {list}", {
                  list: Object.entries(d.observation_validation).map(([k, v]) => `${humanize(k)} ${fmtInt(v)}`).join(" · "),
                })}
              </p>
            </div>
            <div>
              <h3>{t("Unofficial signals (aggregated)")}</h3>
              {d.unofficial_signals.length ? (
                <ul className="plain">
                  {d.unofficial_signals.map((x) => (
                    <li key={x.id}>
                      <span className="badge unverified">{x.verification === "UNVERIFIED" ? t("UNVERIFIED") : humanize(x.verification)}</span>{" "}
                      <span className="small muted">
                        {fmtDate(x.last_seen)} · {t("independent origins {n}", { n: x.independent_origins })}
                      </span>
                      <p style={{ margin: "4px 0 0" }}>{tx(x.summary)}</p>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted small">{t("No unofficial signal clusters for this area.")}</p>
              )}
              {d.published_estimates.length > 0 && (
                <>
                  <h3 className="section">{t("Published external estimates")}</h3>
                  <ul className="plain">
                    {d.published_estimates.map((p, i) => (
                      <li key={i}>
                        <p style={{ margin: 0 }} lang="en">{p.statement}</p>
                        <p className="small muted" style={{ margin: 0 }}>
                          <span lang="en">{p.citation}</span> ({humanize(p.validation_status)})
                          {p.url && <> · <a href={p.url} rel="noopener noreferrer">{t("source")}</a></>}
                        </p>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          </div>
        )}
      </Async>
    </section>
  );
}
