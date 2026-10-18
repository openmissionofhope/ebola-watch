// Weekly reported confirmed cases. Weeks whose counts were apportioned from
// reports spaced more than a few days apart are drawn in a lighter step and
// flagged in the tooltip and table (the interpolation is a modelling input,
// not an observation).
import { scaleBand, scaleLinear } from "d3-scale";
import { useState } from "react";
import { DataTable, TableToggle } from "../components/DataTable";
import { fmtDate, fmtInt } from "../format";
import { useWidth } from "../hooks";
import { M, Tooltip, YGrid, niceMax } from "./common";

export function WeeklyBars({ weeks, counts, interpolated }: { weeks: string[]; counts: number[]; interpolated: number[] }) {
  const [ref, width] = useWidth<HTMLDivElement>(720);
  const height = 220;
  const [hover, setHover] = useState<number | null>(null);
  if (!weeks.length) return <p className="muted">No weekly series available.</p>;
  const x = scaleBand<string>().domain(weeks).range([M.left, width - M.right]).paddingInner(0.25);
  const y = scaleLinear().domain([0, niceMax(Math.max(...counts) * 1.08)]).range([height - M.bottom, M.top]);
  const bw = Math.min(x.bandwidth(), 24);
  const anyInterp = interpolated.some((d) => d > 3);
  const labelEvery = Math.ceil(weeks.length / (width < 520 ? 4 : 8));
  return (
    <div className="chart" ref={ref}>
      <ul className="legend">
        {interpolated.some((d) => d <= 3) && <li><span className="key" style={{ background: "var(--series-1)" }} /> Weekly reported confirmed cases</li>}
        {anyInterp && <li><span className="key" style={{ background: "var(--seq-250)" }} /> Weekly count apportioned from less frequent reports</li>}
      </ul>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Weekly reported confirmed cases">
        <YGrid ticks={y.ticks(4)} y={y} width={width} left={M.left} />
        {weeks.map((w, i) => {
          const x0 = (x(w) ?? 0) + (x.bandwidth() - bw) / 2;
          const h = Math.max(0, y(0) - y(counts[i]));
          const r = Math.min(4, bw / 2, h);
          const top = y(counts[i]);
          const path = `M${x0},${y(0)} V${top + r} Q${x0},${top} ${x0 + r},${top} H${x0 + bw - r} Q${x0 + bw},${top} ${x0 + bw},${top + r} V${y(0)} Z`;
          return (
            <g key={w}>
              <path d={path} className={`bar${interpolated[i] > 3 ? " interp" : ""}`} />
              <rect className="hit" x={x(w)} y={M.top} width={x.bandwidth()} height={y(0) - M.top} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} />
              {i % labelEvery === 0 && (
                <text className="tick-label" x={(x(w) ?? 0) + x.bandwidth() / 2} y={y(0) + 16} textAnchor="middle">
                  {new Date(`${w}T00:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" })}
                </text>
              )}
            </g>
          );
        })}
        <line className="axis-line" x1={M.left} x2={width - M.right} y1={y(0)} y2={y(0)} />
      </svg>
      {hover !== null && (
        <Tooltip x={(x(weeks[hover]) ?? 0) * ((ref.current?.clientWidth ?? width) / width)} y={y(counts[hover])} width={ref.current?.clientWidth ?? width}>
          <strong>Week ending {fmtDate(weeks[hover])}</strong>
          {fmtInt(counts[hover])} reported confirmed cases
          {interpolated[hover] > 3 && <><br />Apportioned across a reporting interval</>}
        </Tooltip>
      )}
      <TableToggle>
        <DataTable
          rows={weeks.map((w, i) => ({ w, c: counts[i], d: interpolated[i] }))}
          columns={[
            { key: "w", header: "Week ending", render: (r) => fmtDate(r.w) },
            { key: "c", header: "Reported confirmed cases", render: (r) => fmtInt(r.c), numeric: true },
            { key: "d", header: "Apportioned days", render: (r) => r.d, numeric: true },
          ]}
        />
      </TableToggle>
    </div>
  );
}
