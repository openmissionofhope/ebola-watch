// Cumulative reported confirmed cases (official), with the forecast fan
// (cumulative = last official value + forecast new cases) and the model's
// estimated cumulative infections drawn as a separate, labelled range marker.
// One y-axis: all quantities are counts of people.
import { scaleLinear, scaleUtc } from "d3-scale";
import { line as d3line, area as d3area } from "d3-shape";
import { useMemo, useState } from "react";
import type { Estimate, ForecastRow, SeriesPoint } from "../api";
import { DataTable, TableToggle } from "../components/DataTable";
import { fmtDate, fmtInt } from "../format";
import { useWidth } from "../hooks";
import { HatchDefs, M, Tooltip, XAxisDates, YGrid, addDays, niceMax, utc } from "./common";

interface Props {
  points: SeriesPoint[];
  forecast: ForecastRow[] | null;
  scenario: string;
  estimate?: Estimate;
  nowcast?: Estimate;
}

interface FanPoint { date: Date; h: number; median: number; l90: number; u90: number; l50: number; u50: number; scenario: boolean }

export function CumulativeChart({ points, forecast, scenario, estimate, nowcast }: Props) {
  const [ref, width] = useWidth<HTMLDivElement>(720);
  const height = Math.max(260, Math.min(380, width * 0.5));
  const [hover, setHover] = useState<{ x: number; y: number; html: JSX.Element } | null>(null);

  const pts = useMemo(() => points.map((p) => ({ date: utc(p.as_of), value: p.value, p })), [points]);
  const last = pts[pts.length - 1];
  const fan: FanPoint[] = useMemo(() => {
    if (!forecast || !last) return [];
    const base = last.value;
    const start: FanPoint = { date: last.date, h: 0, median: base, l90: base, u90: base, l50: base, u50: base, scenario: false };
    return [start, ...forecast.map((f) => ({
      date: addDays(last.date, f.horizon_days), h: f.horizon_days, median: base + f.median, l90: base + f.lower_90,
      u90: base + f.upper_90, l50: base + f.lower_50, u50: base + f.upper_50, scenario: f.is_scenario,
    }))];
  }, [forecast, last]);

  if (!pts.length) return <p className="muted">No official series available.</p>;

  const estOk = estimate && !estimate.insufficient && estimate.upper_90 !== undefined;
  const ncOk = nowcast && !nowcast.insufficient && nowcast.upper_90 !== undefined;
  const xEnd = fan.length ? fan[fan.length - 1].date : last.date;
  const x = scaleUtc().domain([pts[0].date, xEnd]).range([M.left, width - M.right]);
  const yMax = niceMax(Math.max(last.value, ...fan.map((f) => f.u90), estOk ? estimate!.upper_90! : 0, ncOk ? nowcast!.upper_90! : 0) * 1.05);
  const y = scaleLinear().domain([0, yMax]).range([height - M.bottom, M.top]);
  const yt = y.ticks(5);
  const xt = x.ticks(width < 520 ? 4 : 7);

  const officialLine = d3line<{ date: Date; value: number }>().x((d) => x(d.date)).y((d) => y(d.value))(pts) ?? "";
  const forecastPart = fan.filter((f) => !f.scenario);
  const scenarioPart = fan.filter((f, i) => f.scenario || (fan[i + 1]?.scenario ?? false));
  const band = (lo: (f: FanPoint) => number, hi: (f: FanPoint) => number) => (arr: FanPoint[]) =>
    d3area<FanPoint>().x((d) => x(d.date)).y0((d) => y(lo(d))).y1((d) => y(hi(d)))(arr) ?? "";
  const b90 = band((f) => f.l90, (f) => f.u90);
  const b50 = band((f) => f.l50, (f) => f.u50);
  const medLine = (arr: FanPoint[]) => d3line<FanPoint>().x((d) => x(d.date)).y((d) => y(d.median))(arr) ?? "";

  const onMove = (e: React.MouseEvent<SVGRectElement>) => {
    const box = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
    const px = ((e.clientX - box.left) / box.width) * width;
    const all = [
      ...pts.map((p) => ({ date: p.date, kind: "official" as const, p })),
      ...fan.slice(1).map((f) => ({ date: f.date, kind: "forecast" as const, f })),
    ];
    let best = all[0];
    for (const a of all) if (Math.abs(x(a.date) - px) < Math.abs(x(best.date) - px)) best = a;
    const html =
      best.kind === "official" ? (
        <>
          <strong>Official: {fmtInt(best.p.value)} confirmed (cumulative)</strong>
          As of {fmtDate(best.p.p.as_of)} · {best.p.p.source}
        </>
      ) : (
        <>
          <strong>
            {best.f.scenario ? "Scenario" : "Forecast"} +{best.f.h} days ({scenario})
          </strong>
          Cumulative median {fmtInt(best.f.median)}
          <br />
          90% interval {fmtInt(best.f.l90)}–{fmtInt(best.f.u90)}
        </>
      );
    setHover({ x: x(best.date), y: e.clientY - box.top, html });
  };

  return (
    <div className="chart" ref={ref}>
      <ul className="legend" aria-label="Legend">
        <li><span className="key dot" style={{ background: "var(--text-primary)" }} /> Official cumulative confirmed (reported)</li>
        {fan.length > 0 && <li><span className="key dash" /> Forecast median ({scenario})</li>}
        {fan.length > 0 && <li><span className="key band50" /> 50% interval</li>}
        {fan.length > 0 && <li><span className="key band90" /> 90% interval</li>}
        {scenarioPart.length > 0 && <li><span className="key scenario" /> Beyond 28 days: scenario, not a prediction</li>}
        {estOk && <li><span className="key range" /> Estimated cumulative infections (model, 90%)</li>}
        {ncOk && <li><span className="key range" style={{ borderTopStyle: "dotted" }} /> Nowcast of reported cases to date</li>}
      </ul>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Cumulative reported confirmed cases with forecast intervals and model estimate">
        <HatchDefs id="hatch-scenario" />
        <YGrid ticks={yt} y={y} width={width} left={M.left} />
        <line className="axis-line" x1={M.left} x2={width - M.right} y1={y(0)} y2={y(0)} />
        <XAxisDates ticks={xt} x={x} y0={y(0)} />
        {forecastPart.length > 1 && (
          <>
            <path className="band-90" d={b90(forecastPart)} />
            <path className="band-50" d={b50(forecastPart)} />
            <path className="series-line" d={medLine(forecastPart)} strokeDasharray="5 4" />
          </>
        )}
        {scenarioPart.length > 1 && (
          <>
            <path d={b90(scenarioPart)} fill="url(#hatch-scenario)" />
            <path className="series-line" d={medLine(scenarioPart)} strokeDasharray="2 4" />
            <text className="direct-label" x={x(scenarioPart[scenarioPart.length - 1].date) - 4} y={y(scenarioPart[scenarioPart.length - 1].l90) + 14} textAnchor="end">
              scenario
            </text>
          </>
        )}
        <path d={officialLine} fill="none" stroke="var(--text-secondary)" strokeWidth={1.5} />
        {pts.map((p) => (
          <circle key={p.p.as_of} cx={x(p.date)} cy={y(p.value)} r={4} fill="var(--text-primary)" stroke="var(--surface-1)" strokeWidth={2} />
        ))}
        {estOk && (
          <g>
            <line className="est-range" x1={x(last.date) + 8} x2={x(last.date) + 8} y1={y(estimate!.lower_90!)} y2={y(estimate!.upper_90!)} />
            <line className="est-cap" x1={x(last.date) + 3} x2={x(last.date) + 13} y1={y(estimate!.lower_90!)} y2={y(estimate!.lower_90!)} />
            <line className="est-cap" x1={x(last.date) + 3} x2={x(last.date) + 13} y1={y(estimate!.upper_90!)} y2={y(estimate!.upper_90!)} />
            <circle cx={x(last.date) + 8} cy={y(estimate!.median!)} r={4} fill="var(--surface-1)" stroke="var(--text-primary)" strokeWidth={2} />
            {width - M.right - (x(last.date) + 18) >= 230 ? (
              <text className="direct-label" x={x(last.date) + 18} y={y(estimate!.upper_90!)} dy="0.9em">
                Estimated infections (model) {fmtInt(estimate!.lower_90)}–{fmtInt(estimate!.upper_90)}
              </text>
            ) : (
              <text className="direct-label" x={x(last.date) + 2} y={y(estimate!.upper_90!) - 6} textAnchor="end">
                Estimated infections (model)
              </text>
            )}
          </g>
        )}
        {ncOk && nowcast!.period_end && (
          <g>
            <line x1={x(utc(nowcast!.period_end))} x2={x(utc(nowcast!.period_end))} y1={y(nowcast!.lower_90!)} y2={y(nowcast!.upper_90!)} stroke="var(--text-primary)" strokeWidth={2} strokeDasharray="1 2" />
            <rect x={x(utc(nowcast!.period_end)) - 4} y={y(nowcast!.median!) - 4} width={8} height={8} transform={`rotate(45 ${x(utc(nowcast!.period_end))} ${y(nowcast!.median!)})`} fill="var(--surface-1)" stroke="var(--text-primary)" strokeWidth={2} />
          </g>
        )}
        <text className="direct-label" x={x(last.date)} y={y(last.value) - 10} textAnchor="end">
          {fmtInt(last.value)} reported
        </text>
        {hover && <line className="hover-line" x1={hover.x} x2={hover.x} y1={M.top} y2={y(0)} />}
        <rect className="hit" x={M.left} y={M.top} width={width - M.left - M.right} height={y(0) - M.top} onMouseMove={onMove} onMouseLeave={() => setHover(null)} />
      </svg>
      {hover && <Tooltip x={(hover.x / width) * (ref.current?.clientWidth ?? width)} y={hover.y} width={ref.current?.clientWidth ?? width}>{hover.html}</Tooltip>}
      <TableToggle>
        <DataTable
          caption="Official cumulative confirmed cases"
          rows={points}
          columns={[
            { key: "d", header: "Observation date", render: (r) => fmtDate(r.as_of) },
            { key: "v", header: "Cumulative confirmed", render: (r) => fmtInt(r.value), numeric: true },
            { key: "s", header: "Source", render: (r) => r.source },
            { key: "p", header: "Published", render: (r) => fmtDate(r.published_at) },
            { key: "st", header: "Validation", render: (r) => r.validation_status.replace(/_/g, " ") },
          ]}
        />
        {forecast && (
          <DataTable
            caption={`Forecast of additional reported confirmed cases (${scenario})`}
            rows={forecast}
            columns={[
              { key: "h", header: "Horizon (days)", render: (r) => r.horizon_days, numeric: true },
              { key: "k", header: "Type", render: (r) => (r.is_scenario ? "Scenario" : "Forecast") },
              { key: "m", header: "Median", render: (r) => fmtInt(r.median), numeric: true },
              { key: "i50", header: "50% interval", render: (r) => `${fmtInt(r.lower_50)}–${fmtInt(r.upper_50)}`, numeric: true },
              { key: "i90", header: "90% interval", render: (r) => `${fmtInt(r.lower_90)}–${fmtInt(r.upper_90)}`, numeric: true },
              { key: "c", header: "Confidence", render: (r) => r.confidence },
            ]}
          />
        )}
      </TableToggle>
    </div>
  );
}
