import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { Overview } from "../api";
import { ConfidenceBadge, SeverityBadge } from "../components/Badges";
import { DataTable } from "../components/DataTable";
import { PageHead } from "../components/Layout";
import { Async } from "../components/Status";
import { fmtInt } from "../format";
import { useApi, useDocumentTitle } from "../hooks";
import { placeName, t } from "../i18n";

export function RegionsPage() {
  useDocumentTitle(t("Regions"));
  const ov = useApi<Overview>("/overview");
  const [q, setQ] = useState("");
  const [onlyNotable, setOnlyNotable] = useState(true);
  return (
    <>
      <PageHead title={t("Regions")} />
      <p className="secondary">
        {t("Countries and first-level administrative units. Select an area for its epidemiological timeline, estimates, forecasts and evidence.")}
      </p>
      <div className="card" style={{ marginBottom: 12 }}>
        <div className="field">
          <label htmlFor="region-filter">{t("Filter by name")}</label>
          <input id="region-filter" type="text" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <label style={{ fontWeight: 400 }}>
          <input type="checkbox" checked={onlyNotable} onChange={(e) => setOnlyNotable(e.target.checked)} />{" "}
          {t("Only areas above level 0 or with insufficient information")}
        </label>
      </div>
      <Async state={ov}>
        {(d) => <RegionTable d={d} q={q} onlyNotable={onlyNotable} />}
      </Async>
    </>
  );
}

function RegionTable({ d, q, onlyNotable }: { d: Overview; q: string; onlyNotable: boolean }) {
  const rows = useMemo(
    () =>
      d.map
        .filter((m) => m.severity_status !== "not_assessed")
        .filter((m) => !onlyNotable || (m.severity_level ?? 1) >= 1 || m.severity_status === "insufficient_information")
        // match the published name and the name shown in the reader's language
        .filter((m) => `${m.name} ${placeName(m)}`.toLowerCase().includes(q.toLowerCase()))
        .sort((a, b) => a.level - b.level || (b.severity_level ?? 2.5) - (a.severity_level ?? 2.5) || placeName(a).localeCompare(placeName(b))),
    [d, q, onlyNotable],
  );
  return (
    <div className="card">
      <DataTable
        caption={rows.length === 1 ? t("1 area") : t("{count} areas", { count: fmtInt(rows.length) })}
        rows={rows}
        columns={[
          { key: "n", header: t("Area"), render: (m) => <Link to={`/region/${m.code}`}>{placeName(m)}</Link> },
          { key: "l", header: t("Level"), render: (m) => (m.level === 0 ? t("Country") : t("First-level unit")) },
          { key: "s", header: t("Severity"), render: (m) => <SeverityBadge level={m.severity_level} status={m.severity_status} /> },
          { key: "c", header: t("Confidence"), render: (m) => <ConfidenceBadge confidence={m.confidence} /> },
        ]}
        empty={t("No matching areas.")}
      />
    </div>
  );
}
