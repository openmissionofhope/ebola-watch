import { Link } from "react-router-dom";
import type { SignalCluster, SourceStatus } from "../api";
import { StatusPill } from "../components/Badges";
import { DataTable } from "../components/DataTable";
import { PageHead } from "../components/Layout";
import { Async } from "../components/Status";
import { fmtDate, humanize } from "../format";
import { useApi, useDocumentTitle } from "../hooks";

const OFFICIAL = new Set(["official_international", "official_national"]);

export function EvidencePage() {
  useDocumentTitle("Evidence explorer");
  const sources = useApi<SourceStatus[]>("/sources");
  const signals = useApi<SignalCluster[]>("/signals");
  return (
    <>
      <PageHead title="Evidence explorer" />
      <p className="secondary">
        Which sources inform the assessments, whether they are official, and how unofficial reports were treated. Unofficial reports are paraphrased and
        aggregated: no posts, accounts, witnesses or precise locations are shown. Per-area evidence (official bulletins used, validation status and published
        estimates) is on each <Link to="/regions">regional page</Link>.
      </p>
      <section className="card" aria-labelledby="sig-h">
        <h2 id="sig-h">Unofficial signal clusters</h2>
        <p className="small muted">
          Clusters group reports that appear to describe the same event, across languages. Repeated copies of one report count as one origin. A cluster is
          never converted into a case count, and alerts that rely on unofficial reports require human review before publication.
        </p>
        <Async state={signals}>
          {(rows) => (
            <DataTable
              rows={rows}
              columns={[
                { key: "u", header: "Area (generalised)", render: (r) => (r.unit ? <Link to={`/region/${r.unit.code}`}>{r.unit.name}</Link> : "Unresolved") },
                { key: "s", header: "Summary (paraphrased)", render: (r) => r.summary },
                { key: "v", header: "Status", render: (r) => <span className={`badge ${r.verification === "UNVERIFIED" ? "unverified" : ""}`}>{r.verification === "UNVERIFIED" ? "UNVERIFIED" : humanize(r.verification)}</span> },
                { key: "c", header: "Corroboration", render: (r) => humanize(r.corroboration) },
                { key: "i", header: "Independent origins", render: (r) => r.independent_origins, numeric: true },
                { key: "n", header: "Items", render: (r) => r.items, numeric: true },
                { key: "l", header: "Languages", render: (r) => r.languages.join(", ") || "—" },
                { key: "f", header: "Flags", render: (r) => [r.coordination_suspected && "possible coordinated amplification", r.stale && "old report recirculated", r.is_synthetic && "synthetic"].filter(Boolean).join("; ") || "—" },
                { key: "r", header: "Review", render: (r) => humanize(r.review_status) },
                { key: "d", header: "Last seen", render: (r) => fmtDate(r.last_seen) },
              ]}
              empty="No signal clusters in the last 60 days."
            />
          )}
        </Async>
      </section>
      <Async state={sources}>
        {(rows) => (
          <div className="grid cols-2 section">
            {[true, false].map((official) => (
              <section key={String(official)} className="card" aria-labelledby={`src-${official}`}>
                <h2 id={`src-${official}`}>{official ? "Official sources" : "Unofficial and reference sources"}</h2>
                <DataTable
                  rows={rows.filter((r) => OFFICIAL.has(r.category) === official)}
                  columns={[
                    { key: "n", header: "Source", render: (r) => (r.homepage ? <a href={r.homepage} rel="noopener noreferrer">{r.name}</a> : r.name) },
                    { key: "c", header: "Category", render: (r) => humanize(r.category) },
                    { key: "s", header: "Status", render: (r) => <StatusPill status={r.status} /> },
                    { key: "u", header: "Last success", render: (r) => fmtDate(r.last_success_at) },
                  ]}
                />
              </section>
            ))}
          </div>
        )}
      </Async>
    </>
  );
}
