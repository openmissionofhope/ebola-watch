import type { Estimate, OfficialValue } from "../api";
import { fmtDate, fmtInt, fmtNum, rangeText } from "../format";
import { t, tx } from "../i18n";
import { ConfidenceBadge, KindTag } from "./Badges";
import { Insufficient } from "./Status";

export function OfficialTile({ label, value }: { label: string; value: OfficialValue | null | undefined }) {
  return (
    <div className="tile kind-official">
      <KindTag kind="official" />
      <div className="tile-label">{label}</div>
      {value ? (
        <>
          <div className="tile-value" translate="no">{fmtInt(value.value)}</div>
          <div className="tile-sub">
            {t("As of {date}", { date: fmtDate(value.as_of) })} · <span lang="en">{value.source}</span>
            {value.extraction_method === "text_pattern" && ` · ${t("machine-extracted from bulletin text")}`}
            {value.is_synthetic && ` · ${t("SYNTHETIC")}`}
          </div>
        </>
      ) : (
        <div className="tile-sub">{t("Not reported. A missing report is not a zero-case report.")}</div>
      )}
    </div>
  );
}

export function EstimateTile({ label, est, kind = "estimate", digits = 0 }: { label: string; est: Estimate | undefined; kind?: "estimate" | "forecast"; digits?: number }) {
  const ok = est && !est.insufficient && est.median !== undefined;
  const f = (v: number | null | undefined) => (digits ? fmtNum(v, digits) : fmtInt(v));
  return (
    <div className={`tile kind-${kind}`}>
      <KindTag kind={kind} />
      <div className="tile-label">{label}</div>
      {ok ? (
        <>
          <div className="tile-value" translate="no">{digits ? `${f(est!.lower_90)}–${f(est!.upper_90)}` : rangeText(est!.lower_90, est!.upper_90)}</div>
          <div className="tile-sub">
            {t("Median {value}", { value: f(est!.median) })} · {est!.interval ? tx(est!.interval) : t("90% interval")}
            {est!.period_end && ` · ${t("to {date}", { date: fmtDate(est!.period_end) })}`}
          </div>
          {est!.confidence && est!.confidence !== "na" && (
            <div style={{ marginTop: 6 }}>
              <ConfidenceBadge confidence={est!.confidence} prefix={t("Estimate confidence")} />
            </div>
          )}
        </>
      ) : (
        <Insufficient reason={est?.reason} />
      )}
    </div>
  );
}

export function SimpleTile({ label, value, sub, kind }: { label: string; value: string; sub?: string; kind?: "official" | "estimate" | "forecast" }) {
  return (
    <div className={`tile ${kind ? `kind-${kind}` : ""}`}>
      {kind && <KindTag kind={kind} />}
      <div className="tile-label">{label}</div>
      <div className="tile-value">{value}</div>
      {sub && <div className="tile-sub">{sub}</div>}
    </div>
  );
}
