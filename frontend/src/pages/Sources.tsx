import { API_DOCS_URL, downloadUrl, STATIC, type SourceStatus } from "../api";
import { StatusPill } from "../components/Badges";
import { DataTable } from "../components/DataTable";
import { PageHead } from "../components/Layout";
import { Async } from "../components/Status";
import { fmtDateTime, humanize } from "../format";
import { useApi, useDocumentTitle } from "../hooks";
import { T, t } from "../i18n";

export function SourcesPage() {
  useDocumentTitle(t("Sources"));
  const s = useApi<SourceStatus[]>("/sources");
  return (
    <>
      <PageHead title={t("Data sources and connector status")} />
      <p className="secondary">
        {t(
          "Every connector reports its real status. When a source is unavailable or needs credentials, no substitute data are generated. Platforms without a lawful automated access path are listed as unsupported.",
        )}
      </p>
      <p className="small muted">{t("Source names, access methods, licences and technical status messages are shown in English, as published by each source.")}</p>
      <Async state={s}>
        {(rows) => (
          <div className="card">
            <DataTable
              rows={rows}
              columns={[
                {
                  key: "n",
                  header: t("Source"),
                  render: (r) => (
                    <span lang="en">
                      <strong>{r.name}</strong>
                      {r.institution && <div className="small muted">{r.institution}</div>}
                    </span>
                  ),
                },
                { key: "c", header: t("Category"), render: (r) => humanize(r.category) },
                { key: "a", header: t("Access"), render: (r) => <span lang="en">{r.access_method}</span> },
                {
                  key: "s",
                  header: t("Status"),
                  render: (r) => (
                    <>
                      <StatusPill status={r.status} />
                      {r.status_message && (
                        <div className="small muted" style={{ marginTop: 4 }} lang="en">
                          {r.status_message}
                        </div>
                      )}
                    </>
                  ),
                },
                { key: "l", header: t("Licence and terms"), render: (r) => <span lang="en">{[r.license, r.terms_note].filter(Boolean).join(" · ") || "—"}</span> },
                { key: "t", header: t("Last attempt / success"), render: (r) => `${fmtDateTime(r.last_attempt_at)} / ${fmtDateTime(r.last_success_at)}` },
              ]}
            />
          </div>
        )}
      </Async>
      <section className="card section" aria-labelledby="dl-h">
        <h2 id="dl-h">{t("Download the data")}</h2>
        <p className="secondary">
          {t("Aggregated tables with the same publication policy as the dashboard: countries and first-level units only, with small-area suppression.")}
        </p>
        <ul>
          <li>
            <T
              k="{link}: official counts, estimated totals, severity and confidence."
              link={
                <a href={downloadUrl("/export/summaries.csv")} download>
                  {t("Summaries by area (CSV)")}
                </a>
              }
            />
          </li>
          <li>
            <T
              k="{link}: official counts with suppression applied."
              link={
                <a href={downloadUrl("/export/subnational.csv")} download>
                  {t("First-level units (CSV)")}
                </a>
              }
            />
          </li>
          <li>
            {STATIC ? (
              <T k="Every page's data as JSON files: {link}." link={<a href={API_DOCS_URL}>{t("how the data files are organised")}</a>} />
            ) : (
              <T k="The full public API: {link}." link={<a href={API_DOCS_URL}>{t("API documentation")}</a>} />
            )}
          </li>
        </ul>
        <p className="small muted">{t("Downloaded files are in English.")}</p>
      </section>
    </>
  );
}
