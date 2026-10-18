import type { Estimate, OfficialValue } from "../api";
import { fmtDate, fmtInt, rangeText } from "../format";
import { ConfidenceBadge, KindTag } from "./Badges";
import { Insufficient } from "./Status";

export function OfficialTile({ label, value }: { label: string; value: OfficialValue | null | undefined }) {
  return (
    <div className="tile kind-official">
      <KindTag kind="official" />
      <div className="tile-label">{label}</div>
      {value ? (
        <>
          <div className="tile-value">{fmtInt(value.value)}</div>
          <div className="tile-sub">
            As of {fmtDate(value.as_of)} · {value.source}
            {value.extraction_method === "text_pattern" && " · machine-extracted from bulletin text"}
            {value.is_synthetic && " · SYNTHETIC"}
          </div>
        </>
      ) : (
        <div className="tile-sub">Not reported. A missing report is not a zero-case report.</div>
      )}
    </div>
  );
}

export function EstimateTile({ label, est, kind = "estimate", digits = 0 }: { label: string; est: Estimate | undefined; kind?: "estimate" | "forecast"; digits?: number }) {
  const ok = est && !est.insufficient && est.median !== undefined;
  const f = (v: number | null | undefined) => (digits ? (v ?? NaN).toFixed(digits) : fmtInt(v));
  return (
    <div className={`tile kind-${kind}`}>
      <KindTag kind={kind} />
      <div className="tile-label">{label}</div>
      {ok ? (
        <>
          <div className="tile-value">{digits ? `${f(est!.lower_90)}–${f(est!.upper_90)}` : rangeText(est!.lower_90, est!.upper_90)}</div>
          <div className="tile-sub">
            Median {f(est!.median)} · {est!.interval || "90% interval"}
            {est!.period_end && ` · to ${fmtDate(est!.period_end)}`}
          </div>
          {est!.confidence && est!.confidence !== "na" && (
            <div style={{ marginTop: 6 }}>
              <ConfidenceBadge confidence={est!.confidence} prefix="Estimate confidence" />
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
