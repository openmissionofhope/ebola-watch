// Forecast evaluation: interval coverage against nominal levels (small
// multiples, one per interval), PIT histogram, and forecast-vs-observed.
import { scaleBand, scaleLinear } from "d3-scale";
import { useState } from "react";
import type { ComparisonRow, HorizonEval } from "../api";
import { fmtDate, fmtInt, fmtPct } from "../format";
import { useWidth } from "../hooks";
import { t } from "../i18n";
import { M, Tooltip, YGrid, niceMax } from "./common";

export function CoverageChart({ byHorizon, which }: { byHorizon: Record<string, HorizonEval>; which: 50 | 90 }) {
  const [ref, width] = useWidth<HTMLDivElement>(320);
  const height = 180;
  const hs = Object.keys(byHorizon).sort((a, b) => +a - +b);
  const nominal = which / 100;
  const x = scaleBand<string>().domain(hs).range([M.left, width - M.right]).paddingInner(0.35);
  const y = scaleLinear().domain([0, 1]).range([height - M.bottom, M.top]);
  const bw = Math.min(x.bandwidth(), 24);
  return (
    <div className="chart" ref={ref} dir="ltr">
      <ul className="legend">
        <li><span className="key" style={{ background: "var(--series-1)" }} /> {t("Observed coverage")}</li>
        <li><span className="key" style={{ height: 0, borderTop: "1px dashed var(--text-secondary)" }} /> {t("Nominal {level}%", { level: which })}</li>
      </ul>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={t("Observed coverage of {level}% intervals by forecast horizon versus nominal {level}%", { level: which })}
      >
        <YGrid ticks={[0, 0.25, 0.5, 0.75, 1]} y={y} width={width} left={M.left} format={(v) => `${Math.round(v * 100)}%`} />
        {hs.map((h) => {
          const v = byHorizon[h][which === 50 ? "coverage_50" : "coverage_90"];
          const x0 = (x(h) ?? 0) + (x.bandwidth() - bw) / 2;
          const top = y(v);
          const r = Math.min(4, y(0) - top);
          return (
            <g key={h}>
              <path d={`M${x0},${y(0)} V${top + r} Q${x0},${top} ${x0 + r},${top} H${x0 + bw - r} Q${x0 + bw},${top} ${x0 + bw},${top + r} V${y(0)} Z`} className="bar" />
              <text className="direct-label" x={x0 + bw / 2} y={top - 4} textAnchor="middle">{fmtPct(v)}</text>
              <text className="tick-label" x={x0 + bw / 2} y={y(0) + 16} textAnchor="middle">{t("{days} d", { days: h })}</text>
            </g>
          );
        })}
        <line className="ref-line" x1={M.left} x2={width - M.right} y1={y(nominal)} y2={y(nominal)} />
        <line className="axis-line" x1={M.left} x2={width - M.right} y1={y(0)} y2={y(0)} />
      </svg>
    </div>
  );
}

export function PitChart({ bins }: { bins: number[] }) {
  const [ref, width] = useWidth<HTMLDivElement>(320);
  const height = 160;
  const total = bins.reduce((a, b) => a + b, 0);
  const labels = ["0–0.2", "0.2–0.4", "0.4–0.6", "0.6–0.8", "0.8–1"];
  const x = scaleBand<string>().domain(labels).range([M.left, width - M.right]).paddingInner(0.2);
  const y = scaleLinear().domain([0, niceMax(Math.max(...bins, total / 5) * 1.2)]).range([height - M.bottom, M.top]);
  const bw = Math.min(x.bandwidth(), 24);
  return (
    <div className="chart" ref={ref} dir="ltr">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={t("PIT histogram; a calibrated forecast gives roughly equal bars")}>
        <YGrid ticks={y.ticks(3)} y={y} width={width} left={M.left} format={(v) => `${v}`} />
        {bins.map((b, i) => {
          const x0 = (x(labels[i]) ?? 0) + (x.bandwidth() - bw) / 2;
          const top = y(b);
          const r = Math.min(4, Math.max(0, y(0) - top));
          return (
            <g key={i}>
              <path d={`M${x0},${y(0)} V${top + r} Q${x0},${top} ${x0 + r},${top} H${x0 + bw - r} Q${x0 + bw},${top} ${x0 + bw},${top + r} V${y(0)} Z`} className="bar" />
              <text className="tick-label" x={x0 + bw / 2} y={y(0) + 16} textAnchor="middle">{labels[i]}</text>
            </g>
          );
        })}
        {total > 0 && <line className="ref-line" x1={M.left} x2={width - M.right} y1={y(total / 5)} y2={y(total / 5)} />}
        <line className="axis-line" x1={M.left} x2={width - M.right} y1={y(0)} y2={y(0)} />
      </svg>
    </div>
  );
}

export function ComparisonChart({ rows }: { rows: ComparisonRow[] }) {
  const [ref, width] = useWidth<HTMLDivElement>(720);
  const [hover, setHover] = useState<number | null>(null);
  const withObs = rows.filter((r) => r.observed !== null && r.observed !== undefined);
  if (!withObs.length) return <p className="muted small">{t("No earlier forecast has a later observation to compare with yet.")}</p>;
  const keys = withObs.map((r) => `${r.origin_date ?? r.data_as_of} +${r.horizon_days}d`);
  const height = Math.max(160, 26 * withObs.length + M.top + M.bottom);
  const left = 130;
  const xMax = niceMax(Math.max(...withObs.map((r) => Math.max(r.upper_90, r.observed ?? 0))) * 1.05);
  const x = scaleLinear().domain([0, xMax]).range([left, width - M.right]);
  const y = scaleBand<string>().domain(keys).range([M.top, height - M.bottom]).paddingInner(0.4);
  return (
    <div className="chart" ref={ref} dir="ltr">
      <ul className="legend">
        <li><span className="key" style={{ height: 0, borderTop: "2px solid var(--series-1)" }} /> {t("Forecast 90% interval")}</li>
        <li><span className="key dot" /> {t("Forecast median")}</li>
        <li><span className="key" style={{ width: 10, height: 10, transform: "rotate(45deg)", background: "var(--text-primary)" }} /> {t("Later reported (observed)")}</li>
      </ul>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={t("Earlier forecasts compared with later reported counts")}>
        {x.ticks(5).map((tick) => (
          <g key={tick}>
            <line className="grid-line" x1={x(tick)} x2={x(tick)} y1={M.top} y2={height - M.bottom} />
            <text className="tick-label" x={x(tick)} y={height - M.bottom + 16} textAnchor="middle">{fmtInt(tick)}</text>
          </g>
        ))}
        {withObs.map((r, i) => {
          const cy = (y(keys[i]) ?? 0) + y.bandwidth() / 2;
          const inside = (r.observed ?? 0) >= r.lower_90 && (r.observed ?? 0) <= r.upper_90;
          return (
            <g key={keys[i]} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <text className="tick-label" x={left - 8} y={cy} dy="0.32em" textAnchor="end">{keys[i]}</text>
              <line x1={x(r.lower_90)} x2={x(r.upper_90)} y1={cy} y2={cy} stroke="var(--series-1)" strokeWidth={2} strokeLinecap="round" />
              <circle cx={x(r.median)} cy={cy} r={4} className="series-dot" />
              <rect x={x(r.observed ?? 0) - 4} y={cy - 4} width={8} height={8} transform={`rotate(45 ${x(r.observed ?? 0)} ${cy})`} fill="var(--text-primary)" stroke="var(--surface-1)" strokeWidth={1.5} />
              {!inside && <text className="direct-label" x={width - M.right} y={cy} dy="0.32em" textAnchor="end">{t("outside 90%")}</text>}
              <rect className="hit" x={left} y={cy - y.bandwidth()} width={width - left - M.right} height={y.bandwidth() * 2} />
            </g>
          );
        })}
      </svg>
      {hover !== null && (
        <Tooltip x={x(withObs[hover].median) * ((ref.current?.clientWidth ?? width) / width)} y={(y(keys[hover]) ?? 0)} width={ref.current?.clientWidth ?? width}>
          <strong>
            {t("Forecast from {date} (+{days} days)", {
              date: fmtDate(withObs[hover].origin_date ?? withObs[hover].data_as_of),
              days: withObs[hover].horizon_days,
            })}
          </strong>
          {t("Median {median}; 90% {lower}–{upper}", {
            median: fmtInt(withObs[hover].median),
            lower: fmtInt(withObs[hover].lower_90),
            upper: fmtInt(withObs[hover].upper_90),
          })}
          <br />
          {t("Observed {value}", { value: fmtInt(withObs[hover].observed) })}
        </Tooltip>
      )}
    </div>
  );
}
