import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import type { ComparisonRow, Evidence, ForecastRow, OfficialSeries, RegionSummary, Subnational, TransportContext } from "../api";
import { ConfidenceBadge, KindTag, SeverityBadge } from "../components/Badges";
import { DataTable, TableToggle } from "../components/DataTable";
import { Async, INSUFFICIENT, Insufficient } from "../components/Status";
import { EstimateTile, OfficialTile, SimpleTile } from "../components/Tiles";
import { ComparisonChart } from "../charts/EvalCharts";
import { CumulativeChart } from "../charts/CumulativeChart";
import { RtChart } from "../charts/RtChart";
import { WeeklyBars } from "../charts/WeeklyBars";
import { fmtDate, fmtDateTime, fmtInt, fmtNum, fmtPct, humanize } from "../format";
import { useApi, useDocumentTitle } from "../hooks";

const SCENARIOS = ["improving", "baseline", "deteriorating"] as const;

export function RegionDetailPage() {
  const { code = "" } = useParams();
  const summary = useApi<RegionSummary>(`/regions/${encodeURIComponent(code)}/summary`);
  useDocumentTitle(summary.data?.region.name ?? code);
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
  return (
    <>
      <nav aria-label="Breadcrumb" className="small"><Link to="/regions">Regions</Link> / {s.region.name}</nav>
      <div className="page-head" style={{ marginTop: 6 }}>
        <h1>{s.region.name}</h1>
        {s.is_synthetic && <span className="badge synthetic">SYNTHETIC DATA</span>}
      </div>
      {s.outbreak && (
        <p className="secondary" style={{ marginTop: -6 }}>
          {s.outbreak.name} · declared {fmtDate(s.outbreak.declared_on)}
          {s.outbreak.ended_on ? ` · declared over ${fmtDate(s.outbreak.ended_on)}` : ""}
          {s.outbreak.auto_registered && " · auto-registered from bulletins (pending verification)"}
        </p>
      )}

      <section className="card" aria-labelledby="sev-h">
        <div className="card-head">
          <h2 id="sev-h">Assessment</h2>
          <span className="small muted">Data as of {fmtDate(s.data_as_of)} · updated {fmtDateTime(s.latest_update ?? sev.assessed_at)} · model {s.model_version}</span>
        </div>
        <div className="dims">
          <SeverityBadge level={sev.level} status={sev.status} label={sev.label} />
          <ConfidenceBadge confidence={sev.confidence} />
        </div>
        {sev.underestimation_risk && (
          <div className="callout warn"><span aria-hidden="true">⚠ </span>Incomplete surveillance creates a credible risk that severity is underestimated.</div>
        )}
        <p style={{ marginTop: 8 }}>{sev.explanation}</p>
        {sev.description && <p className="small muted">{sev.description}</p>}
        <div className="grid cols-2">
          <div>
            <h3>Evidence that triggered this level</h3>
            {sev.triggers.length ? (
              <ul className="trigger-list">{sev.triggers.map((t, i) => <li key={i}>{t.text}</li>)}</ul>
            ) : (
              <p className="small muted">No triggers: no reliable evidence of current transmission.</p>
            )}
          </div>
          <div>
            <h3>What limits confidence</h3>
            {sev.confidence_reasons && sev.confidence_reasons.length ? (
              <ul className="trigger-list">{sev.confidence_reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
            ) : (
              <p className="small muted">No specific limitations recorded.</p>
            )}
          </div>
        </div>
      </section>

      <section className="section" aria-labelledby="known-h">
        <h2 id="known-h">What is officially reported</h2>
        <div className="grid tiles">
          <OfficialTile label="Confirmed cases" value={s.official.confirmed_cases} />
          <OfficialTile label="Confirmed deaths" value={s.official.confirmed_deaths} />
          <OfficialTile label="Probable cases" value={s.official.probable_cases} />
          <OfficialTile label="Suspected cases" value={s.official.suspected_cases} />
          {s.official.imported_cases && <OfficialTile label="Imported confirmed cases (subset)" value={s.official.imported_cases} />}
        </div>
      </section>

      <section className="section" aria-labelledby="est-h">
        <h2 id="est-h">What is estimated</h2>
        <p className="small muted">Model-based quantities. They are not confirmed cases and are shown separately from official reports.</p>
        <div className="grid tiles">
          <EstimateTile label="Estimated cumulative symptomatic infections" est={s.estimated_total} />
          <EstimateTile label="Estimated new infections, last 14 days" est={s.recent_incidence} />
          <EstimateTile label="Nowcast: reported cases to date" est={s.nowcast_reported} />
          <EstimateTile label="R_t of reported cases" est={s.rt} digits={2} />
          {s.ascertainment?.identifiable ? (
            <SimpleTile kind="estimate" label="Reporting completeness" value={`${fmtPct(s.ascertainment.lower_90)}–${fmtPct(s.ascertainment.upper_90)}`}
              sub={`Median ${fmtPct(s.ascertainment.median)} · ${s.ascertainment.method}`} />
          ) : (
            <div className="tile kind-estimate"><KindTag kind="estimate" /><div className="tile-label">Reporting completeness</div>
              <p className="insufficient small" style={{ margin: 0 }}>Not identifiable from available data.</p></div>
          )}
        </div>
        {disagreement && (
          <div className="callout danger" role="note">
            <strong>Models disagree substantially.</strong> The range shown spans both methods rather than averaging them.
            {s.model_disagreement && (
              <span> Medians: {Object.entries(s.model_disagreement.medians).map(([k, v]) => `${humanize(k)} ${fmtInt(v)}`).join("; ")}.</span>
            )}
            {fc?.comparison?.substantial_disagreement && (
              <span> 28-day forecast: renewal model median {fmtInt(fc.comparison.renewal_median)} vs log-linear model {fmtInt(fc.comparison.loglinear_median)}.</span>
            )}
          </div>
        )}
        {s.model_reasons && s.model_reasons.length > 0 && (
          <div className="callout"><strong>Model limitations:</strong> {s.model_reasons.join("; ")}</div>
        )}
      </section>

      <section className="card section" aria-labelledby="tl-h">
        <div className="card-head">
          <h2 id="tl-h">Epidemiological timeline</h2>
          {fc && !fc.insufficient && (
            <div role="group" aria-label="Forecast scenario" className="segmented">
              {SCENARIOS.map((sc) => (
                <button key={sc} type="button" aria-pressed={scenario === sc} onClick={() => setScenario(sc)}>{humanize(sc)}</button>
              ))}
            </div>
          )}
        </div>
        {fc && !fc.insufficient && fc.scenario_definitions && (
          <p className="small muted">Scenario “{humanize(scenario)}”: {fc.scenario_definitions[scenario]}. Horizons beyond 28 days are scenarios driven by assumptions, not predictions.</p>
        )}
        {fc?.insufficient && <Insufficient text={fc.message} reason={fc.reason} />}
        <Async state={series}>
          {(ser) => (
            <>
              <h3>Cumulative reported confirmed cases</h3>
              {ser.revisions.length > 0 && <p className="small">Official totals were revised {ser.revisions.length} time(s); see the table view.</p>}
              <CumulativeChart points={ser.points} forecast={fcRows} scenario={scenario} estimate={s.estimated_total} nowcast={s.nowcast_reported} />
              {ser.observations_pending_review > 0 && (
                <p className="small muted">{ser.observations_pending_review} extracted value(s) are awaiting human review and are not shown.</p>
              )}
            </>
          )}
        </Async>
        {s.weekly && s.weekly.week_ends.length > 0 && (
          <>
            <h3 className="section">Weekly reported confirmed cases</h3>
            <WeeklyBars weeks={s.weekly.week_ends} counts={s.weekly.reported_confirmed} interpolated={s.weekly.interpolated_days} />
            <p className="small muted">Mean interval between official reports in the last six weeks: {fmtNum(s.weekly.mean_recent_reporting_interval_days, 1)} days.</p>
          </>
        )}
        {s.rt_history && s.rt_history.length > 0 && (
          <>
            <h3 className="section">Reproduction number of reported cases (R_t)</h3>
            <p className="small muted">R_t of reported cases also changes when case detection changes. Values above 1 indicate growth of reported cases.</p>
            <RtChart rows={s.rt_history} />
          </>
        )}
      </section>

      {fc && !fc.insufficient && <ForecastTables s={s} />}

      <section className="card section" aria-labelledby="exp-h">
        <h2 id="exp-h">Geographic expansion</h2>
        {s.expansion && !s.expansion.insufficient ? (
          <>
            <p>
              Newly affected {s.expansion.unit}: about {fmtNum(s.expansion.weekly_rate_median, 2)} per week recently (90%: {fmtNum(s.expansion.weekly_rate_90?.[0], 2)}–
              {fmtNum(s.expansion.weekly_rate_90?.[1], 2)}).
            </p>
            <DataTable
              rows={Object.entries(s.expansion.p_new_unit ?? {}).map(([h, p]) => ({ h, p, e: s.expansion?.expected_new_units?.[h] }))}
              columns={[
                { key: "h", header: "Horizon (days)", render: (r) => r.h, numeric: true },
                { key: "p", header: `Probability of ≥1 newly affected ${s.expansion.unit?.replace(/s$/, "")}`, render: (r) => fmtPct(r.p), numeric: true },
                { key: "e", header: "Expected new units (90%)", render: (r) => (r.e ? `${fmtInt(r.e.median)} (${fmtInt(r.e.lower_90)}–${fmtInt(r.e.upper_90)})` : "—"), numeric: true },
              ]}
            />
            <p className="small muted">{s.expansion.method}. Where expansion may occur is described under transport context, as a relative ranking.</p>
          </>
        ) : (
          <Insufficient reason={s.expansion?.reason ?? "No series of affected administrative units is available for this area."} />
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
    new_reported_confirmed: "Additional reported confirmed cases",
    new_symptomatic_infections: "Additional symptomatic infections (model-based, includes unreported)",
  };
  return (
    <section className="card section" aria-labelledby="fc-h">
      <h2 id="fc-h">Forecasts and scenarios</h2>
      <p className="small muted">
        Issued {fmtDateTime(s.forecasts?.issued_at)} from data as of {fmtDate(s.forecasts?.data_as_of)}. Intervals are 50% and 90% prediction intervals.
        Horizons over 28 days are labelled scenarios.
      </p>
      {Object.entries(targets).map(([t, byScenario]) => (
        <div key={t} className="section">
          <h3>{label[t] ?? humanize(t)}</h3>
          <DataTable
            rows={(byScenario.baseline ?? []).map((b) => ({ b, imp: byScenario.improving?.find((x) => x.horizon_days === b.horizon_days), det: byScenario.deteriorating?.find((x) => x.horizon_days === b.horizon_days) }))}
            columns={[
              { key: "h", header: "Horizon", render: (r) => `${r.b.horizon_days} days`, numeric: true },
              { key: "k", header: "Type", render: (r) => (r.b.is_scenario ? <KindTag kind="scenario" /> : <KindTag kind="forecast" />) },
              { key: "b", header: "Current conditions: median (90%)", render: (r) => `${fmtInt(r.b.median)} (${fmtInt(r.b.lower_90)}–${fmtInt(r.b.upper_90)})`, numeric: true },
              { key: "i", header: "Improving (90%)", render: (r) => (r.imp ? `${fmtInt(r.imp.lower_90)}–${fmtInt(r.imp.upper_90)}` : "—"), numeric: true },
              { key: "d", header: "Deteriorating (90%)", render: (r) => (r.det ? `${fmtInt(r.det.lower_90)}–${fmtInt(r.det.upper_90)}` : "—"), numeric: true },
              { key: "p", header: "P(continued transmission)", render: (r) => fmtPct(r.b.p_continued_transmission), numeric: true },
              { key: "c", header: "Confidence", render: (r) => r.b.confidence },
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
      <h2 id="sq-h">Surveillance quality</h2>
      <p>Overall evidence base: <strong>{humanize(sq?.overall ?? "insufficient_information")}</strong>. This rates the available observations, not the country.</p>
      <DataTable
        rows={sq?.indicators ?? []}
        columns={[
          { key: "l", header: "Indicator", render: (i) => i.label },
          { key: "v", header: "Value", render: (i) => (i.value === null ? "Unknown" : i.key.match(/followup|community|ascertainment/) ? fmtPct(i.value) : String(i.value)), numeric: true },
          { key: "s", header: "Assessment", render: (i) => humanize(i.status) },
          { key: "n", header: "Note", render: (i) => i.note },
        ]}
        empty="No indicators available."
      />
    </section>
  );
}

function Assumptions({ s }: { s: RegionSummary }) {
  const params = (s.parameters ?? {}) as Record<string, { source?: string; status?: string; range?: number[]; mean?: number; sd?: number; mean_range?: number[] } | unknown>;
  const paramRows = Object.entries(params)
    .filter(([, v]) => v && typeof v === "object" && "source" in (v as object))
    .map(([k, v]) => ({ k, v: v as { source?: string; status?: string; range?: number[]; mean?: number; sd?: number; mean_range?: number[] } }));
  return (
    <section className="card section" aria-labelledby="as-h">
      <h2 id="as-h">Methods and assumptions</h2>
      {(s.burden_methods ?? []).map((b) => (
        <div key={b.method} className="section">
          <h3>{humanize(b.method)}</h3>
          {b.insufficient ? (
            <Insufficient text={INSUFFICIENT} reason={b.reason} />
          ) : (
            <p>
              {b.method === "reported_floor" ? "Reported floor" : "Estimate"}: {fmtInt(b.lower_90)}–{fmtInt(b.upper_90)} (median {fmtInt(b.median)})
              {b.ascertainment && <> · implied reporting completeness {fmtPct(b.ascertainment.lower_90)}–{fmtPct(b.ascertainment.upper_90)}</>}
            </p>
          )}
          {b.assumptions.length > 0 && <ul className="trigger-list small">{b.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>}
        </div>
      ))}
      {paramRows.length > 0 && (
        <TableToggle label="Show model parameters and their sources">
          <DataTable
            rows={paramRows}
            columns={[
              { key: "k", header: "Parameter", render: (r) => humanize(r.k) },
              { key: "v", header: "Value", render: (r) => (r.v.range ? `${r.v.range[0]}–${r.v.range[1]}` : r.v.mean !== undefined ? `mean ${r.v.mean}${r.v.sd ? `, sd ${r.v.sd}` : ""}${r.v.mean_range ? ` (mean range ${r.v.mean_range[0]}–${r.v.mean_range[1]})` : ""}` : "—") },
              { key: "st", header: "Status", render: (r) => humanize(r.v.status) },
              { key: "s", header: "Source", render: (r) => r.v.source },
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
      <h2 id="sub-h">First-level administrative units</h2>
      <Async state={sub}>
        {(d) => (
          <>
            <DataTable
              rows={d.cells}
              columns={[
                { key: "n", header: "Unit", render: (c) => (c.region_code.includes(":") ? c.region_name : <Link to={`/region/${c.region_code}`}>{c.region_name}</Link>) },
                { key: "v", header: "Official confirmed (latest)", render: (c) => c.display ?? "—", numeric: true },
                { key: "s", header: "Note", render: (c) => (c.suppressed ? "Suppressed to protect small populations" : c.notes.join("; ")) },
              ]}
              empty="No sub-national official figures are available at a publishable resolution."
            />
            <p className="small muted">{d.note}</p>
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
      <h2 id="tr-h">Transport connectivity context</h2>
      <Async state={tc}>
        {(d) => (
          <>
            <ul className="trigger-list small">{d.caveats.map((c) => <li key={c}>{c}</li>)}</ul>
            <h3 className="section">Relative connectivity to areas with active transmission</h3>
            <DataTable
              rows={d.introduction_ranking.slice(0, 12)}
              columns={[
                { key: "n", header: "Area", render: (r) => r.name },
                { key: "t", header: "Tier", render: (r) => humanize(r.tier) },
                { key: "r", header: "Robust to assumptions", render: (r) => (r.robust ? "Yes" : "No — ranking changes across scenarios") },
                { key: "p", header: "Broad path", render: (r) => r.path_names.join(" → ") },
                { key: "m", header: "Modes", render: (r) => r.path_modes.map(humanize).join(", ") || "—" },
                { key: "u", header: "Unverified links", render: (r) => fmtPct(r.share_unverified_links), numeric: true },
                { key: "km", header: "Straight-line km", render: (r) => fmtInt(r.straight_line_km_from_nearest_source), numeric: true },
              ]}
              empty="No ranking: no active transmission sources or no corridor data."
            />
            <TableToggle label={`Show ${d.edges.length} corridors touching this area`}>
              <DataTable
                rows={d.edges}
                columns={[
                  { key: "c", header: "Corridor", render: (e) => e.corridor ?? e.key },
                  { key: "m", header: "Mode", render: (e) => humanize(e.mode) },
                  { key: "p", header: "Infrastructure", render: (e) => humanize(e.physical_status) },
                  { key: "s", header: "Passenger service", render: (e) => humanize(e.service_status) },
                  { key: "v", header: "Verification", render: (e) => humanize(e.verification) },
                  { key: "n", header: "Notes", render: (e) => [e.seasonal_note, e.disruption_note, e.notes].filter(Boolean).join(" ") || "—" },
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
      <h2 id="cmp-h">Earlier forecasts compared with what was reported</h2>
      <Async state={cmp}>
        {(rows) => (
          <>
            <ComparisonChart rows={rows} />
            <TableToggle>
              <DataTable
                rows={rows}
                columns={[
                  { key: "o", header: "Forecast from", render: (r) => fmtDate(r.origin_date ?? r.data_as_of) },
                  { key: "src", header: "Type", render: (r) => (r.source === "backtest" ? "Retrospective (backtest)" : "Issued forecast") },
                  { key: "h", header: "Horizon (days)", render: (r) => r.horizon_days, numeric: true },
                  { key: "m", header: "Median", render: (r) => fmtInt(r.median), numeric: true },
                  { key: "i", header: "90% interval", render: (r) => `${fmtInt(r.lower_90)}–${fmtInt(r.upper_90)}`, numeric: true },
                  { key: "ob", header: "Observed", render: (r) => (r.observed === null || r.observed === undefined ? "Not yet known" : fmtInt(r.observed)), numeric: true },
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
      <h2 id="ev-h">Evidence</h2>
      <Async state={ev}>
        {(d) => (
          <div className="grid cols-2">
            <div>
              <h3>Official sources used</h3>
              <ul className="plain">
                {d.official_sources.slice(0, 12).map((o, i) => (
                  <li key={i}>
                    {o.official ? <KindTag kind="official" /> : <KindTag kind="unverified" />} <span className="small muted">{fmtDate(o.published_at)} · {o.source}</span>
                    <div>{o.url ? <a href={o.url} rel="noopener noreferrer">{o.title}</a> : o.title}</div>
                  </li>
                ))}
              </ul>
              <p className="small muted">
                Observation validation: {Object.entries(d.observation_validation).map(([k, v]) => `${humanize(k)} ${v}`).join(" · ")}
              </p>
            </div>
            <div>
              <h3>Unofficial signals (aggregated)</h3>
              {d.unofficial_signals.length ? (
                <ul className="plain">
                  {d.unofficial_signals.map((x) => (
                    <li key={x.id}>
                      <span className="badge unverified">{x.verification === "UNVERIFIED" ? "UNVERIFIED" : humanize(x.verification)}</span>{" "}
                      <span className="small muted">{fmtDate(x.last_seen)} · independent origins {x.independent_origins}</span>
                      <p style={{ margin: "4px 0 0" }}>{x.summary}</p>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted small">No unofficial signal clusters for this area.</p>
              )}
              {d.published_estimates.length > 0 && (
                <>
                  <h3 className="section">Published external estimates</h3>
                  <ul className="plain">
                    {d.published_estimates.map((p, i) => (
                      <li key={i}>
                        <p style={{ margin: 0 }}>{p.statement}</p>
                        <p className="small muted" style={{ margin: 0 }}>
                          {p.citation} ({humanize(p.validation_status)}){p.url && <> · <a href={p.url} rel="noopener noreferrer">source</a></>}
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
