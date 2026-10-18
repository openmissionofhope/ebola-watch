import { Link } from "react-router-dom";
import { STATIC, type Overview, type RegionSummary } from "../api";
import { AskBox } from "../components/AskBox";
import { ConfidenceBadge, KindTag, SeverityBadge } from "../components/Badges";
import { DataTable } from "../components/DataTable";
import { PageHead } from "../components/Layout";
import { Async, INSUFFICIENT } from "../components/Status";
import { MapView } from "../charts/MapView";
import { fmtDate, fmtDateTime, fmtInt, rangeText } from "../format";
import { useApi, useDocumentTitle } from "../hooks";

export function OverviewPage() {
  useDocumentTitle("Overview");
  const ov = useApi<Overview>("/overview");
  return (
    <Async state={ov} lines={8}>
      {(d) => (
        <>
          <PageHead title="Current situation">
            <p className="small muted">
              Latest model run {fmtDateTime(d.latest_model_run)} · model {d.model_version}
            </p>
          </PageHead>
          <section aria-labelledby="regions-h">
            <h2 id="regions-h" className="visually-hidden">Assessed areas</h2>
            <div className="grid cols-2">
              {d.regions.map((r) => (
                <RegionCard key={r.region.code} s={r} />
              ))}
            </div>
            {!d.regions.length && <p className="muted">No areas currently have reported Ebola cases or an elevated assessment.</p>}
          </section>

          <div className="grid cols-2 section">
            <section className="card" aria-labelledby="map-h">
              <div className="card-head">
                <h2 id="map-h">Severity and connectivity</h2>
                <Link to="/map">Open full map</Link>
              </div>
              <MapView layer="forecast_risk" resolution={0} focus="central" compact />
            </section>
            <section className="card" aria-labelledby="sev-h">
              <h2 id="sev-h">Severity assessments</h2>
              <p className="small muted">Severity and confidence are separate: a severe situation can be assessed with low confidence, and vice versa.</p>
              <DataTable
                rows={d.map
                  .filter((m) => (m.severity_level ?? 0) >= 1 || m.severity_status === "insufficient_information")
                  .sort((a, b) => (b.severity_level ?? 2.5) - (a.severity_level ?? 2.5))}
                columns={[
                  { key: "n", header: "Area", render: (m) => <Link to={`/region/${m.code}`}>{m.name}</Link> },
                  { key: "s", header: "Severity", render: (m) => <SeverityBadge level={m.severity_level} status={m.severity_status} /> },
                  { key: "c", header: "Confidence", render: (m) => <ConfidenceBadge confidence={m.confidence} /> },
                ]}
                empty="No area is above level 0."
              />
            </section>
          </div>

          <div className="grid cols-2 section">
            <section className="card" aria-labelledby="alerts-h">
              <h2 id="alerts-h">Published alerts</h2>
              {d.alerts.length ? (
                <ul className="plain">
                  {d.alerts.map((a, i) => (
                    <li key={a.id ?? `r${i}`}>
                      <div className="dims">
                        {a.retracted ? <span className="badge">Retracted</span> : a.severity_level !== undefined && a.severity_level !== null && <SeverityBadge level={a.severity_level} />}
                        {a.relies_on_unofficial && <span className="badge unverified">Relies on unofficial reports{a.reviewed ? " · human-reviewed" : ""}</span>}
                        <span className="small muted">{fmtDateTime(a.created_at)}</span>
                      </div>
                      <p style={{ margin: "4px 0" }}>{a.message}</p>
                      {a.evidence?.triggers && a.evidence.triggers.length > 0 && (
                        <ul className="trigger-list small">
                          {a.evidence.triggers.map((t) => (
                            <li key={t.code}>{t.text}</li>
                          ))}
                        </ul>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted">No published alerts.</p>
              )}
            </section>
            <section className="card" aria-labelledby="dev-h">
              <h2 id="dev-h">Latest official developments</h2>
              <ul className="plain">
                {d.developments.map((dv, i) => (
                  <li key={i}>
                    <KindTag kind="official" /> <span className="small muted">{fmtDate(dv.published_at)} · {dv.source}</span>
                    <div>{dv.url ? <a href={dv.url} rel="noopener noreferrer">{dv.title}</a> : dv.title}</div>
                  </li>
                ))}
              </ul>
            </section>
          </div>

          {!STATIC && (
            <section className="card section" aria-labelledby="ask-h">
              <h2 id="ask-h">Ask about the data</h2>
              <AskBox compact />
            </section>
          )}
        </>
      )}
    </Async>
  );
}

function RegionCard({ s }: { s: RegionSummary }) {
  const oc = s.official.confirmed_cases;
  const od = s.official.confirmed_deaths;
  const imp = s.official.imported_cases;
  const est = s.estimated_total;
  return (
    <article className="card region-card" aria-labelledby={`rc-${s.region.code}`}>
      <div className="card-head">
        <h3 id={`rc-${s.region.code}`} style={{ margin: 0 }}>
          <Link to={`/region/${s.region.code}`}>{s.region.name}</Link>
        </h3>
        {s.is_synthetic && <span className="badge synthetic">SYNTHETIC</span>}
      </div>
      {s.outbreak && <p className="small muted" style={{ margin: 0 }}>{s.outbreak.name}{s.outbreak.ended_on ? ` · declared over ${fmtDate(s.outbreak.ended_on)}` : ""}</p>}
      <div className="dims">
        <SeverityBadge level={s.severity.level} status={s.severity.status} label={s.severity.label} />
        <ConfidenceBadge confidence={s.severity.confidence} />
      </div>
      {s.severity.underestimation_risk && (
        <p className="small" style={{ margin: 0 }}>
          <span aria-hidden="true">⚠ </span>Incomplete surveillance creates a credible risk that severity is underestimated.
        </p>
      )}
      <div className="grid tiles">
        <div>
          <div className="tile-label">Official confirmed cases</div>
          {oc ? <div className="tile-value">{fmtInt(oc.value)}</div> : <p className="secondary" style={{ margin: "2px 0" }}>None reported in the current outbreak</p>}
          {oc && <div className="tile-sub">As of {fmtDate(oc.as_of)} · {oc.source}</div>}
          {oc && Date.now() - Date.parse(oc.as_of) > 365 * 86_400_000 && <div className="tile-sub">Figure from a previous outbreak, not current transmission.</div>}
          {od && <div className="tile-sub">Confirmed deaths {fmtInt(od.value)}</div>}
          {imp && <div className="tile-sub">Imported confirmed (subset): {fmtInt(imp.value)}</div>}
        </div>
        <div>
          <div className="tile-label">Estimated total (model)</div>
          {est && !est.insufficient ? (
            <>
              <div className="tile-value">{rangeText(est.lower_90, est.upper_90)}</div>
              <div className="tile-sub">90% interval · estimate confidence {est.confidence}</div>
            </>
          ) : (
            <p className="insufficient small" style={{ margin: 0 }}>{INSUFFICIENT}</p>
          )}
        </div>
      </div>
      <p className="small muted" style={{ margin: 0 }}>{s.severity.explanation}</p>
      <dl className="kv small">
        <dt>Data as of</dt>
        <dd>{fmtDate(s.data_as_of)}</dd>
        <dt>Latest update</dt>
        <dd>{fmtDateTime(s.latest_update ?? s.severity.assessed_at)}</dd>
        <dt>Model</dt>
        <dd>{s.model_version}</dd>
      </dl>
    </article>
  );
}
