// R_t of reported cases: median line with 90% band and a reference line at 1.
import { scaleLinear, scaleUtc } from "d3-scale";
import { area, line } from "d3-shape";
import { useState } from "react";
import { DataTable, TableToggle } from "../components/DataTable";
import { fmtDate, fmtNum } from "../format";
import { useWidth } from "../hooks";
import { M, Tooltip, XAxisDates, YGrid, utc } from "./common";

type Row = { week_end: string; median: number; lower_90: number; upper_90: number };

export function RtChart({ rows }: { rows: Row[] }) {
  const [ref, width] = useWidth<HTMLDivElement>(720);
  const height = 220;
  const [hover, setHover] = useState<Row | null>(null);
  if (!rows.length) return <p className="muted">R_t history not available.</p>;
  const pts = rows.map((r) => ({ ...r, d: utc(r.week_end) }));
  const x = scaleUtc().domain([pts[0].d, pts[pts.length - 1].d]).range([M.left, width - M.right]);
  const yMax = Math.max(2, Math.ceil(Math.max(...rows.map((r) => r.upper_90)) * 2) / 2);
  const y = scaleLinear().domain([0, yMax]).range([height - M.bottom, M.top]);
  const band = area<(typeof pts)[number]>().x((d) => x(d.d)).y0((d) => y(d.lower_90)).y1((d) => y(d.upper_90))(pts) ?? "";
  const med = line<(typeof pts)[number]>().x((d) => x(d.d)).y((d) => y(d.median))(pts) ?? "";
  const lastPt = pts[pts.length - 1];
  return (
    <div className="chart" ref={ref}>
      <ul className="legend">
        <li><span className="key line" /> R_t median (reported cases)</li>
        <li><span className="key band90" /> 90% credible interval</li>
        <li><span className="key" style={{ height: 0, borderTop: "1px dashed var(--text-secondary)" }} /> R = 1 (growth threshold)</li>
      </ul>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Reproduction number of reported cases over time">
        <YGrid ticks={y.ticks(4)} y={y} width={width} left={M.left} format={(v) => v.toFixed(1)} />
        <line className="axis-line" x1={M.left} x2={width - M.right} y1={y(0)} y2={y(0)} />
        <XAxisDates ticks={x.ticks(width < 520 ? 4 : 6)} x={x} y0={y(0)} />
        <path className="band-90" d={band} />
        <line className="ref-line" x1={M.left} x2={width - M.right} y1={y(1)} y2={y(1)} />
        <path className="series-line" d={med} />
        <circle className="series-dot" cx={x(lastPt.d)} cy={y(lastPt.median)} r={4} />
        <text className="direct-label" x={x(lastPt.d) - 6} y={y(lastPt.upper_90) - 6} textAnchor="end">
          {fmtNum(lastPt.median)}
        </text>
        {pts.map((p) => (
          <rect key={p.week_end} className="hit" x={x(p.d) - 8} y={M.top} width={16} height={y(0) - M.top} onMouseEnter={() => setHover(p)} onMouseLeave={() => setHover(null)} />
        ))}
        {hover && <line className="hover-line" x1={x(utc(hover.week_end))} x2={x(utc(hover.week_end))} y1={M.top} y2={y(0)} />}
      </svg>
      {hover && (
        <Tooltip x={x(utc(hover.week_end)) * ((ref.current?.clientWidth ?? width) / width)} y={y(hover.median)} width={ref.current?.clientWidth ?? width}>
          <strong>Week ending {fmtDate(hover.week_end)}</strong>
          R_t {fmtNum(hover.median)} (90%: {fmtNum(hover.lower_90)}–{fmtNum(hover.upper_90)})
        </Tooltip>
      )}
      <TableToggle>
        <DataTable
          rows={rows}
          columns={[
            { key: "w", header: "Week ending", render: (r) => fmtDate(r.week_end) },
            { key: "m", header: "Median", render: (r) => fmtNum(r.median), numeric: true },
            { key: "l", header: "90% lower", render: (r) => fmtNum(r.lower_90), numeric: true },
            { key: "u", header: "90% upper", render: (r) => fmtNum(r.upper_90), numeric: true },
          ]}
        />
      </TableToggle>
    </div>
  );
}
