import { Link } from "react-router-dom";
import type { SignalCluster, SourceStatus } from "../api";
import { StatusPill } from "../components/Badges";
import { DataTable } from "../components/DataTable";
import { PageHead } from "../components/Layout";
import { Async } from "../components/Status";
import { fmtDate, humanize } from "../format";
import { useApi, useDocumentTitle } from "../hooks";
import { T, placeName, t, tx } from "../i18n";

const OFFICIAL = new Set(["official_international", "official_national"]);

export function EvidencePage() {
  useDocumentTitle(t("Evidence explorer"));
  const sources = useApi<SourceStatus[]>("/sources");
  const signals = useApi<SignalCluster[]>("/signals");
  return (
    <>
      <PageHead title={t("Evidence explorer")} />
      <p className="secondary">
        <T
          k="Which sources inform the assessments, whether they are official, and how unofficial reports were treated. Unofficial reports are paraphrased and aggregated: no posts, accounts, witnesses or precise locations are shown. Per-area evidence (official bulletins used, validation status and published estimates) is on each {link}."
          link={<Link to="/regions">{t("regional page")}</Link>}
        />
      </p>
      <section className="card" aria-labelledby="sig-h">
        <h2 id="sig-h">{t("Unofficial signal clusters")}</h2>
        <p className="small muted">
          {t(
            "Clusters group reports that appear to describe the same event, across languages. Repeated copies of one report count as one origin. A cluster is never converted into a case count, and alerts that rely on unofficial reports require human review before publication.",
          )}
        </p>
        <Async state={signals}>
          {(rows) => (
            <DataTable
              rows={rows}
              columns={[
                { key: "u", header: t("Area (generalised)"), render: (r) => (r.unit ? <Link to={`/region/${r.unit.code}`}>{placeName(r.unit)}</Link> : t("Unresolved")) },
                { key: "s", header: t("Summary (paraphrased)"), render: (r) => tx(r.summary) },
                {
                  key: "v",
                  header: t("Status"),
                  render: (r) => (
                    <span className={`badge ${r.verification === "UNVERIFIED" ? "unverified" : ""}`}>
                      {r.verification === "UNVERIFIED" ? t("UNVERIFIED") : humanize(r.verification)}
                    </span>
                  ),
                },
                { key: "c", header: t("Corroboration"), render: (r) => humanize(r.corroboration) },
                { key: "i", header: t("Independent origins"), render: (r) => r.independent_origins, numeric: true },
                { key: "n", header: t("Items"), render: (r) => r.items, numeric: true },
                { key: "l", header: t("Languages"), render: (r) => <span translate="no">{r.languages.join(", ") || "—"}</span> },
                {
                  key: "f",
                  header: t("Flags"),
                  render: (r) =>
                    [
                      r.coordination_suspected && t("possible coordinated amplification"),
                      r.stale && t("old report recirculated"),
                      r.is_synthetic && t("synthetic"),
                    ]
                      .filter(Boolean)
                      .join("; ") || "—",
                },
                { key: "r", header: t("Review"), render: (r) => humanize(r.review_status) },
                { key: "d", header: t("Last seen"), render: (r) => <span translate="no">{fmtDate(r.last_seen)}</span> },
              ]}
              empty={t("No signal clusters in the last 60 days.")}
            />
          )}
        </Async>
      </section>
      <Async state={sources}>
        {(rows) => (
          <div className="grid cols-2 section">
            {[true, false].map((official) => (
              <section key={String(official)} className="card" aria-labelledby={`src-${official}`}>
                <h2 id={`src-${official}`}>{official ? t("Official sources") : t("Unofficial and reference sources")}</h2>
                <DataTable
                  rows={rows.filter((r) => OFFICIAL.has(r.category) === official)}
                  columns={[
                    {
                      key: "n",
                      header: t("Source"),
                      render: (r) => <span lang="en">{r.homepage ? <a href={r.homepage} rel="noopener noreferrer">{r.name}</a> : r.name}</span>,
                    },
                    { key: "c", header: t("Category"), render: (r) => humanize(r.category) },
                    { key: "s", header: t("Status"), render: (r) => <StatusPill status={r.status} /> },
                    { key: "u", header: t("Last success"), render: (r) => <span translate="no">{fmtDate(r.last_success_at)}</span> },
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
