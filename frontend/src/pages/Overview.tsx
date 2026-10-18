import { Link } from "react-router-dom";
import { STATIC, type Overview, type RegionSummary } from "../api";
import { AskBox } from "../components/AskBox";
import { ConfidenceBadge, KindTag, SeverityBadge } from "../components/Badges";
import { DataTable } from "../components/DataTable";
import { PageHead } from "../components/Layout";
import { Async } from "../components/Status";
import { MapView } from "../charts/MapView";
import { fmtDate, fmtDateTime, fmtInt, humanize, rangeText } from "../format";
import { useApi, useDocumentTitle } from "../hooks";
import { placeName, t, tx } from "../i18n";

export function OverviewPage() {
  useDocumentTitle(t("Overview"));
  const ov = useApi<Overview>("/overview");
  return (
    <Async state={ov} lines={8}>
      {(d) => (
        <>
          <PageHead title={t("Current situation")}>
            <p className="small muted">
              {t("Latest model run {when} · model {version}", { when: fmtDateTime(d.latest_model_run), version: d.model_version })}
            </p>
          </PageHead>
          <section aria-labelledby="regions-h">
            <h2 id="regions-h" className="visually-hidden">{t("Assessed areas")}</h2>
            <div className="grid cols-2">
              {d.regions.map((r) => (
                <RegionCard key={r.region.code} s={r} />
              ))}
            </div>
            {!d.regions.length && <p className="muted">{t("No areas currently have reported Ebola cases or an elevated assessment.")}</p>}
          </section>

          <div className="grid cols-2 section">
            <section className="card" aria-labelledby="map-h">
              <div className="card-head">
                <h2 id="map-h">{t("Severity and connectivity")}</h2>
                <Link to="/map">{t("Open full map")}</Link>
              </div>
              <MapView layer="forecast_risk" resolution={0} focus="central" compact />
            </section>
            <section className="card" aria-labelledby="sev-h">
              <h2 id="sev-h">{t("Severity assessments")}</h2>
              <p className="small muted">{t("Severity and confidence are separate: a severe situation can be assessed with low confidence, and vice versa.")}</p>
              <DataTable
                rows={d.map
                  .filter((m) => (m.severity_level ?? 0) >= 1 || m.severity_status === "insufficient_information")
                  .sort((a, b) => (b.severity_level ?? 2.5) - (a.severity_level ?? 2.5))}
                columns={[
                  { key: "n", header: t("Area"), render: (m) => <Link to={`/region/${m.code}`}>{placeName(m)}</Link> },
                  { key: "s", header: t("Severity"), render: (m) => <SeverityBadge level={m.severity_level} status={m.severity_status} /> },
                  { key: "c", header: t("Confidence"), render: (m) => <ConfidenceBadge confidence={m.confidence} /> },
                ]}
                empty={t("No area is above level 0.")}
              />
            </section>
          </div>

          <div className="grid cols-2 section">
            <section className="card" aria-labelledby="alerts-h">
              <h2 id="alerts-h">{t("Published alerts")}</h2>
              {d.alerts.length ? (
                <ul className="plain">
                  {d.alerts.map((a, i) => (
                    <li key={a.id ?? `r${i}`}>
                      <div className="dims">
                        {a.retracted ? <span className="badge">{t("Retracted")}</span> : a.severity_level !== undefined && a.severity_level !== null && <SeverityBadge level={a.severity_level} />}
                        {a.relies_on_unofficial && (
                          <span className="badge unverified">
                            {a.reviewed ? t("Relies on unofficial reports · human-reviewed") : t("Relies on unofficial reports")}
                          </span>
                        )}
                        <span className="small muted" translate="no">{fmtDateTime(a.created_at)}</span>
                      </div>
                      <p style={{ margin: "4px 0" }}>{tx(a.message)}</p>
                      {a.evidence?.triggers && a.evidence.triggers.length > 0 && (
                        <ul className="trigger-list small">
                          {a.evidence.triggers.map((tr) => (
                            <li key={tr.code}>{tx(tr.text)}</li>
                          ))}
                        </ul>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted">{t("No published alerts.")}</p>
              )}
            </section>
            <section className="card" aria-labelledby="dev-h">
              <h2 id="dev-h">{t("Latest official developments")}</h2>
              <ul className="plain">
                {d.developments.map((dv, i) => (
                  <li key={i}>
                    <KindTag kind="official" /> <span className="small muted">{fmtDate(dv.published_at)} · <span lang="en">{dv.source}</span></span>
                    <div lang="en">{dv.url ? <a href={dv.url} rel="noopener noreferrer">{dv.title}</a> : dv.title}</div>
                  </li>
                ))}
              </ul>
            </section>
          </div>

          {!STATIC && (
            <section className="card section" aria-labelledby="ask-h">
              <h2 id="ask-h">{t("Ask about the data")}</h2>
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
          <Link to={`/region/${s.region.code}`}>{placeName(s.region)}</Link>
        </h3>
        {s.is_synthetic && <span className="badge synthetic">{t("SYNTHETIC")}</span>}
      </div>
      {s.outbreak && (
        <p className="small muted" style={{ margin: 0 }}>
          {tx(s.outbreak.name)}
          {s.outbreak.ended_on ? ` · ${t("declared over {date}", { date: fmtDate(s.outbreak.ended_on) })}` : ""}
        </p>
      )}
      <div className="dims">
        <SeverityBadge level={s.severity.level} status={s.severity.status} label={s.severity.label} />
        <ConfidenceBadge confidence={s.severity.confidence} />
      </div>
      {s.severity.underestimation_risk && (
        <p className="small" style={{ margin: 0 }}>
          <span aria-hidden="true">⚠ </span>
          {t("Incomplete surveillance creates a credible risk that severity is underestimated.")}
        </p>
      )}
      <div className="grid tiles">
        <div>
          <div className="tile-label">{t("Official confirmed cases")}</div>
          {oc ? (
            <div className="tile-value" translate="no">{fmtInt(oc.value)}</div>
          ) : (
            <p className="secondary" style={{ margin: "2px 0" }}>{t("None reported in the current outbreak")}</p>
          )}
          {oc && (
            <div className="tile-sub">
              {t("As of {date}", { date: fmtDate(oc.as_of) })} · <span lang="en">{oc.source}</span>
            </div>
          )}
          {oc && Date.now() - Date.parse(oc.as_of) > 365 * 86_400_000 && (
            <div className="tile-sub">{t("Figure from a previous outbreak, not current transmission.")}</div>
          )}
          {od && <div className="tile-sub">{t("Confirmed deaths {count}", { count: fmtInt(od.value) })}</div>}
          {imp && <div className="tile-sub">{t("Imported confirmed (subset): {count}", { count: fmtInt(imp.value) })}</div>}
        </div>
        <div>
          <div className="tile-label">{t("Estimated total (model)")}</div>
          {est && !est.insufficient ? (
            <>
              <div className="tile-value" translate="no">{rangeText(est.lower_90, est.upper_90)}</div>
              <div className="tile-sub">
                {t("90% interval · estimate confidence {confidence}", { confidence: humanize(est.confidence).toLocaleLowerCase() })}
              </div>
            </>
          ) : (
            <p className="insufficient small" style={{ margin: 0 }}>{t("Insufficient evidence for a reliable numerical estimate.")}</p>
          )}
        </div>
      </div>
      <p className="small muted" style={{ margin: 0 }}>{tx(s.severity.explanation)}</p>
      <dl className="kv small">
        <dt>{t("Data as of")}</dt>
        <dd translate="no">{fmtDate(s.data_as_of)}</dd>
        <dt>{t("Latest update")}</dt>
        <dd translate="no">{fmtDateTime(s.latest_update ?? s.severity.assessed_at)}</dd>
        <dt>{t("Model")}</dt>
        <dd translate="no">{s.model_version}</dd>
      </dl>
    </article>
  );
}
