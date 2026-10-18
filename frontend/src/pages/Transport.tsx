import type { TransportContext } from "../api";
import { DataTable } from "../components/DataTable";
import { PageHead } from "../components/Layout";
import { Async } from "../components/Status";
import { MapView } from "../charts/MapView";
import { fmtInt, fmtPct, humanize } from "../format";
import { useApi, useDocumentTitle } from "../hooks";

export function TransportPage() {
  useDocumentTitle("Transport connectivity");
  const tc = useApi<TransportContext>("/transport");
  return (
    <>
      <PageHead title="Transport connectivity" />
      <p className="secondary">
        A corridor-level, multimodal connectivity model between administrative units. It supports broad geographic risk assessment only: no routes, crossings,
        stations, ports or facilities are shown, and no individual movement is modelled. Most passenger services are recorded as unverified; the model treats them
        as scenarios (closed, partial, open) rather than as operating.
      </p>
      <MapView layer="transport" resolution={1} focus="central" />
      <Async state={tc}>
        {(d) => (
          <>
            <section className="card section">
              <h2>Caveats</h2>
              <ul className="trigger-list">{d.caveats.map((c) => <li key={c}>{c}</li>)}</ul>
              <p className="small muted">Active sources used for the ranking (confirmed cases in the last 21 days): {Object.entries(d.sources_of_risk).map(([k, v]) => `${k} ${fmtInt(v)}`).join(", ") || "none"}.</p>
            </section>
            <section className="card section">
              <h2>Relative connectivity to areas with active transmission</h2>
              <DataTable
                rows={d.introduction_ranking}
                columns={[
                  { key: "n", header: "Area", render: (r) => r.name },
                  { key: "t", header: "Tier", render: (r) => humanize(r.tier) },
                  { key: "s", header: "Score (closed / partial / open)", render: (r) => ["closed", "partial", "open"].map((k) => (r.relative_score[k] ?? 0).toFixed(2)).join(" / "), numeric: true },
                  { key: "r", header: "Robust", render: (r) => (r.robust ? "Yes" : "No") },
                  { key: "p", header: "Broad path", render: (r) => r.path_names.join(" → ") },
                  { key: "u", header: "Unverified links", render: (r) => fmtPct(r.share_unverified_links), numeric: true },
                  { key: "e", header: "Effective distance", render: (r) => (r.effective_distance ?? "—").toString(), numeric: true },
                  { key: "k", header: "Straight-line km", render: (r) => fmtInt(r.straight_line_km_from_nearest_source), numeric: true },
                ]}
                empty="No active transmission sources."
              />
              <p className="small muted">Scores are normalised so the most connected area under each scenario scores 1. They are not probabilities.</p>
            </section>
            <section className="card section">
              <h2>Corridors</h2>
              <DataTable
                rows={d.edges}
                columns={[
                  { key: "c", header: "Corridor", render: (e) => e.corridor ?? e.key },
                  { key: "f", header: "Between", render: (e) => `${e.from.name} – ${e.to.name}` },
                  { key: "m", header: "Mode", render: (e) => humanize(e.mode) },
                  { key: "p", header: "Infrastructure", render: (e) => humanize(e.physical_status) },
                  { key: "s", header: "Passenger service", render: (e) => humanize(e.service_status) },
                  { key: "v", header: "Verification", render: (e) => humanize(e.verification) },
                  { key: "src", header: "Sources", render: (e) => e.sources.join("; ") || "—" },
                ]}
              />
            </section>
          </>
        )}
      </Async>
    </>
  );
}
