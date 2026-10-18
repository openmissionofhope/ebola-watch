import type { TransportContext } from "../api";
import { DataTable } from "../components/DataTable";
import { PageHead } from "../components/Layout";
import { Async } from "../components/Status";
import { MapView } from "../charts/MapView";
import { fmtInt, fmtNum, fmtPct, humanize } from "../format";
import { useApi, useDocumentTitle } from "../hooks";
import { placeName, t, tx } from "../i18n";

export function TransportPage() {
  useDocumentTitle(t("Transport connectivity"));
  const tc = useApi<TransportContext>("/transport");
  return (
    <>
      <PageHead title={t("Transport connectivity")} />
      <p className="secondary">
        {t(
          "A corridor-level, multimodal connectivity model between administrative units. It supports broad geographic risk assessment only: no routes, crossings, stations, ports or facilities are shown, and no individual movement is modelled. Most passenger services are recorded as unverified; the model treats them as scenarios (closed, partial, open) rather than as operating.",
        )}
      </p>
      <MapView layer="transport" resolution={1} focus="central" />
      <Async state={tc}>
        {(d) => (
          <>
            <section className="card section">
              <h2>{t("Caveats")}</h2>
              <ul className="trigger-list">{d.caveats.map((c) => <li key={c}>{tx(c)}</li>)}</ul>
              <p className="small muted">
                {t("Active sources used for the ranking (confirmed cases in the last 21 days): {sources}.", {
                  sources: Object.entries(d.sources_of_risk).map(([k, v]) => `${k} ${fmtInt(v)}`).join(", ") || t("none"),
                })}
              </p>
            </section>
            <section className="card section">
              <h2>{t("Relative connectivity to areas with active transmission")}</h2>
              <DataTable
                rows={d.introduction_ranking}
                columns={[
                  { key: "n", header: t("Area"), render: (r) => placeName({ code: r.unit, name: r.name }) },
                  { key: "t", header: t("Tier"), render: (r) => humanize(r.tier) },
                  {
                    key: "s",
                    header: t("Score (closed / partial / open)"),
                    render: (r) => ["closed", "partial", "open"].map((k) => fmtNum(r.relative_score[k] ?? 0, 2)).join(" / "),
                    numeric: true,
                  },
                  { key: "r", header: t("Robust"), render: (r) => (r.robust ? t("Yes") : t("No")) },
                  { key: "p", header: t("Broad path"), render: (r) => r.path_names.join(" → ") },
                  { key: "u", header: t("Unverified links"), render: (r) => fmtPct(r.share_unverified_links), numeric: true },
                  { key: "e", header: t("Effective distance"), render: (r) => (r.effective_distance === null ? "—" : fmtNum(r.effective_distance, 2)), numeric: true },
                  { key: "k", header: t("Straight-line km"), render: (r) => fmtInt(r.straight_line_km_from_nearest_source), numeric: true },
                ]}
                empty={t("No active transmission sources.")}
              />
              <p className="small muted">{t("Scores are normalised so the most connected area under each scenario scores 1. They are not probabilities.")}</p>
            </section>
            <section className="card section">
              <h2>{t("Corridors")}</h2>
              <DataTable
                rows={d.edges}
                columns={[
                  { key: "c", header: t("Corridor"), render: (e) => e.corridor ?? e.key },
                  { key: "f", header: t("Between"), render: (e) => `${placeName(e.from)} – ${placeName(e.to)}` },
                  { key: "m", header: t("Mode"), render: (e) => humanize(e.mode) },
                  { key: "p", header: t("Infrastructure"), render: (e) => humanize(e.physical_status) },
                  { key: "s", header: t("Passenger service"), render: (e) => humanize(e.service_status) },
                  { key: "v", header: t("Verification"), render: (e) => humanize(e.verification) },
                  { key: "src", header: t("Sources"), render: (e) => <span lang="en">{e.sources.join("; ") || "—"}</span> },
                ]}
              />
            </section>
          </>
        )}
      </Async>
    </>
  );
}
