import { Link, useParams } from "react-router-dom";
import { downloadUrl, type ReportDetail, type ReportListItem } from "../api";
import { DataTable } from "../components/DataTable";
import { PageHead } from "../components/Layout";
import { Markdown } from "../components/Markdown";
import { Async } from "../components/Status";
import { fmtDate, fmtDateTime, humanize } from "../format";
import { useApi, useDocumentTitle } from "../hooks";

export function ReportsPage() {
  useDocumentTitle("Situation reports");
  const reps = useApi<ReportListItem[]>("/reports");
  return (
    <>
      <PageHead title="Situation reports" />
      <p className="secondary">Automatically generated from published data. Each report separates what is known, what is estimated, what has changed, what may happen next, and how uncertain it is.</p>
      <Async state={reps}>
        {(rows) => (
          <div className="card">
            <DataTable
              rows={rows}
              columns={[
                { key: "t", header: "Report", render: (r) => <Link to={`/reports/${r.id}`}>{r.title}</Link> },
                { key: "k", header: "Type", render: (r) => humanize(r.kind) },
                { key: "g", header: "Generated", render: (r) => fmtDateTime(r.generated_at) },
                { key: "d", header: "Data as of", render: (r) => fmtDate(r.data_as_of) },
                { key: "s", header: "Status", render: (r) => humanize(r.status) + (r.is_synthetic ? " · SYNTHETIC" : "") },
              ]}
              empty="No reports have been published yet."
            />
          </div>
        )}
      </Async>
    </>
  );
}

export function ReportViewPage() {
  const { id = "" } = useParams();
  const rep = useApi<ReportDetail>(`/reports/${encodeURIComponent(id)}`);
  useDocumentTitle(rep.data?.title ?? "Report");
  return (
    <Async state={rep}>
      {(r) => (
        <article className="card">
          <nav className="small" aria-label="Breadcrumb"><Link to="/reports">Reports</Link> / {r.title}</nav>
          <p className="small muted">Generated {fmtDateTime(r.generated_at)} · <a href={downloadUrl(`/reports/${r.id}.md`)}>Download Markdown</a></p>
          {r.is_synthetic && <div className="banner synthetic">This report contains SYNTHETIC data.</div>}
          {r.status === "retracted" ? (
            <div className="callout danger"><strong>Retracted.</strong> {r.retraction_note}</div>
          ) : (
            r.markdown && <Markdown source={r.markdown} />
          )}
        </article>
      )}
    </Async>
  );
}
