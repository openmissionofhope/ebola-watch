import { Link, useParams } from "react-router-dom";
import { downloadUrl, type ReportDetail, type ReportListItem } from "../api";
import { DataTable } from "../components/DataTable";
import { PageHead } from "../components/Layout";
import { Markdown } from "../components/Markdown";
import { Async } from "../components/Status";
import { fmtDate, fmtDateTime, humanize } from "../format";
import { useApi, useDocumentTitle } from "../hooks";
import { t, tx } from "../i18n";

export function ReportsPage() {
  useDocumentTitle(t("Situation reports"));
  const reps = useApi<ReportListItem[]>("/reports");
  return (
    <>
      <PageHead title={t("Situation reports")} />
      <p className="secondary">
        {t(
          "Automatically generated from published data. Each report separates what is known, what is estimated, what has changed, what may happen next, and how uncertain it is.",
        )}
      </p>
      <Async state={reps}>
        {(rows) => (
          <div className="card">
            <DataTable
              rows={rows}
              columns={[
                { key: "t", header: t("Report"), render: (r) => <Link to={`/reports/${r.id}`}>{tx(r.title)}</Link> },
                { key: "k", header: t("Type"), render: (r) => humanize(r.kind) },
                { key: "g", header: t("Generated"), render: (r) => fmtDateTime(r.generated_at) },
                { key: "d", header: t("Data as of"), render: (r) => fmtDate(r.data_as_of) },
                { key: "s", header: t("Status"), render: (r) => humanize(r.status) + (r.is_synthetic ? ` · ${t("SYNTHETIC")}` : "") },
              ]}
              empty={t("No reports have been published yet.")}
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
  useDocumentTitle(rep.data?.title ? tx(rep.data.title) : t("Report"));
  return (
    <Async state={rep}>
      {(r) => (
        <article className="card">
          <nav className="small" aria-label={t("Breadcrumb")}>
            <Link to="/reports">{t("Reports")}</Link> / {tx(r.title)}
          </nav>
          <p className="small muted">
            {t("Generated {when}", { when: fmtDateTime(r.generated_at) })} ·{" "}
            <a href={downloadUrl(`/reports/${r.id}.md`)}>{t("Download Markdown (English)")}</a>
          </p>
          {r.is_synthetic && <div className="banner synthetic">{t("This report contains SYNTHETIC data.")}</div>}
          {r.status === "retracted" ? (
            <div className="callout danger">
              <strong>{t("Retracted.")}</strong> {tx(r.retraction_note)}
            </div>
          ) : (
            r.markdown && <Markdown source={r.markdown} />
          )}
        </article>
      )}
    </Async>
  );
}
