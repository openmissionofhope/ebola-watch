import { API_DOCS_URL, downloadUrl, STATIC, type SourceStatus } from "../api";
import { StatusPill } from "../components/Badges";
import { DataTable } from "../components/DataTable";
import { PageHead } from "../components/Layout";
import { Async } from "../components/Status";
import { fmtDateTime, humanize } from "../format";
import { useApi, useDocumentTitle } from "../hooks";

export function SourcesPage() {
  useDocumentTitle("Sources");
  const s = useApi<SourceStatus[]>("/sources");
  return (
    <>
      <PageHead title="Data sources and connector status" />
      <p className="secondary">
        Every connector reports its real status. When a source is unavailable or needs credentials, no substitute data are generated. Platforms without a
        lawful automated access path are listed as unsupported.
      </p>
      <Async state={s}>
        {(rows) => (
          <div className="card">
            <DataTable
              rows={rows}
              columns={[
                { key: "n", header: "Source", render: (r) => (<><strong>{r.name}</strong>{r.institution && <div className="small muted">{r.institution}</div>}</>) },
                { key: "c", header: "Category", render: (r) => humanize(r.category) },
                { key: "a", header: "Access", render: (r) => r.access_method },
                { key: "s", header: "Status", render: (r) => (<><StatusPill status={r.status} />{r.status_message && <div className="small muted" style={{ marginTop: 4 }}>{r.status_message}</div>}</>) },
                { key: "l", header: "Licence and terms", render: (r) => [r.license, r.terms_note].filter(Boolean).join(" · ") || "—" },
                { key: "t", header: "Last attempt / success", render: (r) => `${fmtDateTime(r.last_attempt_at)} / ${fmtDateTime(r.last_success_at)}` },
              ]}
            />
          </div>
        )}
      </Async>
      <section className="card section" aria-labelledby="dl-h">
        <h2 id="dl-h">Download the data</h2>
        <p className="secondary">
          Aggregated tables with the same publication policy as the dashboard: countries and first-level units only, with small-area suppression.
        </p>
        <ul>
          <li><a href={downloadUrl("/export/summaries.csv")} download>Summaries by area (CSV)</a>: official counts, estimated totals, severity and confidence.</li>
          <li><a href={downloadUrl("/export/subnational.csv")} download>First-level units (CSV)</a>: official counts with suppression applied.</li>
          <li>
            {STATIC ? "Every page's data as JSON files: " : "The full public API: "}
            <a href={API_DOCS_URL}>{STATIC ? "how the data files are organised" : "API documentation"}</a>.
          </li>
        </ul>
      </section>
    </>
  );
}
