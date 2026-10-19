// Locally rendered SVG map (no tile servers). Five layers from /map/layers,
// each a separate quantity: official burden, estimated burden, forecast risk
// (severity + connectivity tier), surveillance uncertainty, transport corridors.
// Units with data are keyboard-focusable; a table alternative accompanies it.
import { geoArea, geoMercator, geoPath, type GeoPermissibleObjects } from "d3-geo";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { GeoCollection, GeoFeature, MapLayers, MapUnit } from "../api";
import { levelName } from "../components/Badges";
import { DataTable, TableToggle } from "../components/DataTable";
import { ErrorBox } from "../components/Status";
import { fmtDate, fmtInt, humanize } from "../format";
import { useApi, useWidth } from "../hooks";
import { placeName, t, tx } from "../i18n";

export type LayerKey = "official" | "estimated" | "forecast_risk" | "surveillance" | "transport";

export function layerLabel(layer: LayerKey): string {
  const labels: Record<LayerKey, string> = {
    official: t("Official burden"),
    estimated: t("Estimated burden"),
    forecast_risk: t("Forecast risk"),
    surveillance: t("Surveillance uncertainty"),
    transport: t("Transport connectivity"),
  };
  return labels[layer];
}

const BURDEN_BREAKS = [1, 10, 100, 1000, 10000];
const BURDEN_FILLS = ["var(--seq-150)", "var(--seq-250)", "var(--seq-350)", "var(--seq-550)", "var(--seq-650)"];

function burdenLabels(): string[] {
  const range = (a: number, b: number) => `${fmtInt(a)}–${fmtInt(b)}`;
  return [range(1, 9), range(10, 99), range(100, 999), range(1000, 9999), t("{count} or more", { count: fmtInt(10000) })];
}

/** Name of a map unit: countries in the reader's language, sub-national units as published. */
function unitName(code: string, name: string, level: number): string {
  return placeName({ code, name, level });
}

function burdenFill(v: number | null | undefined): string | null {
  if (v === null || v === undefined || v <= 0) return null;
  let i = 0;
  while (i < BURDEN_BREAKS.length - 1 && v >= BURDEN_BREAKS[i + 1]) i++;
  return BURDEN_FILLS[i];
}

const CONF_FILL: Record<string, string> = { low: "var(--seq-550)", moderate: "var(--seq-350)", high: "var(--seq-150)" };
const TIER_FILL: Record<string, string> = { higher: "var(--seq-650)", moderate: "var(--seq-450)", lower: "var(--seq-250)" };

function rewind(f: GeoFeature): GeoFeature {
  // d3-geo treats polygons spherically: an exterior ring with the "wrong"
  // winding covers the rest of the globe. Reverse rings where that happens.
  const area = geoArea(f as unknown as GeoPermissibleObjects);
  if (area <= 2 * Math.PI) return f;
  const g = f.geometry;
  const rev = (rings: number[][][]) => rings.map((r) => [...r].reverse());
  if (g.type === "Polygon") return { ...f, geometry: { ...g, coordinates: rev(g.coordinates as number[][][]) } };
  if (g.type === "MultiPolygon") return { ...f, geometry: { ...g, coordinates: (g.coordinates as number[][][][]).map(rev) } };
  return f;
}

interface FillSpec { fill: string | null; hatch?: boolean; text: string }

const lower = (value: string | null | undefined) => humanize(value).toLocaleLowerCase();

function fillFor(layer: LayerKey, u: MapUnit | undefined, code: string): FillSpec {
  if (!u) return { fill: null, text: t("No data") };
  switch (layer) {
    case "official":
      if (u.official_display) return { fill: BURDEN_FILLS[0], text: t("Confirmed (official): {value} (suppressed small value)", { value: u.official_display }) };
      return u.official_confirmed
        ? {
            fill: burdenFill(u.official_confirmed),
            text: t("Confirmed (official): {value} as of {date}", { value: fmtInt(u.official_confirmed), date: fmtDate(u.official_as_of) }),
          }
        : { fill: null, text: t("No officially reported confirmed cases in the current outbreak (not evidence of zero cases)") };
    case "estimated":
      return u.estimated_total
        ? {
            fill: burdenFill(u.estimated_total.median),
            text: t("Estimated infections (model): {low}–{high} (median {median}; confidence {confidence})", {
              low: fmtInt(u.estimated_total.lower_90),
              high: fmtInt(u.estimated_total.upper_90),
              median: fmtInt(u.estimated_total.median),
              confidence: lower(u.estimated_total.confidence),
            }),
          }
        : { fill: null, text: t("No model estimate (insufficient evidence or no current outbreak data)") };
    case "forecast_risk": {
      if (u.severity_status === "insufficient_information") return { fill: null, hatch: true, text: t("Severity: insufficient information") };
      const lvl = u.severity_level;
      const ct = u.connectivity_tier;
      const tier = ct
        ? `; ${
            ct.robust
              ? t("connectivity to active areas: {tier}", { tier: lower(ct.tier) })
              : t("connectivity to active areas: {tier} (sensitive to assumptions)", { tier: lower(ct.tier) })
          }`
        : "";
      if (lvl === null || lvl === undefined) return { fill: null, text: `${t("Not assessed")}${tier}` };
      return { fill: `var(--sev-${lvl})`, text: `${t("Severity level {level}", { level: lvl })}${tier}` };
    }
    case "surveillance":
      if (u.severity_status === "insufficient_information") return { fill: null, hatch: true, text: t("Insufficient information") };
      if (!u.confidence) return { fill: null, text: t("Not assessed") };
      return {
        fill: CONF_FILL[u.confidence] ?? null,
        text:
          t("Assessment confidence: {confidence}; surveillance evidence: {evidence}", {
            confidence: lower(u.confidence),
            evidence: humanize(u.surveillance_overall),
          }) + (u.underestimation_risk ? `; ${t("risk that severity is underestimated")}` : ""),
      };
    case "transport":
      return { fill: "var(--surface-2)", text: unitName(code, u.name, u.level) };
  }
}

interface Props {
  layer: LayerKey;
  resolution: 0 | 1;
  focus?: "africa" | "central";
  compact?: boolean;
}

export function MapView(props: Props) {
  const g0 = useApi<GeoCollection>("/map/geometry/0");
  const g1 = useApi<GeoCollection>(props.resolution === 1 ? "/map/geometry/1" : null);
  const layers = useApi<MapLayers>("/map/layers");
  const ready = g0.data && layers.data && (props.resolution === 0 || g1.data);
  const err = g0.error || layers.error || g1.error;
  if (err) return <ErrorBox message={err} onRetry={() => { g0.reload(); g1.reload(); layers.reload(); }} />;
  if (!ready) return <div className="map-wrap"><div className="skeleton" style={{ height: props.compact ? 260 : 460 }} /></div>;
  return <MapCanvas {...props} countries={g0.data!} admin1={props.resolution === 1 ? g1.data! : null} layers={layers.data!} />;
}

function MapCanvas({ layer, resolution, focus = "africa", compact, countries, admin1, layers }: Props & { countries: GeoCollection; admin1: GeoCollection | null; layers: MapLayers }) {
  const [ref, width] = useWidth<HTMLDivElement>(800);
  const navigate = useNavigate();
  const [hover, setHover] = useState<{ code: string; name: string; text: string; x: number; y: number } | null>(null);
  const height = Math.round(width * (focus === "central" ? 0.75 : compact ? 0.85 : 0.95));

  const { path, projection, c0, c1 } = useMemo(() => {
    const c0 = countries.features.map(rewind);
    const c1 = admin1 ? admin1.features.map(rewind) : [];
    const box: GeoPermissibleObjects =
      focus === "central"
        ? { type: "MultiPoint", coordinates: [[10, -14], [45, 12]] }
        : { type: "MultiPoint", coordinates: [[-18, -35], [52, 37]] };
    const projection = geoMercator().fitExtent([[8, 8], [width - 8, height - 8]], box);
    return { path: geoPath(projection), projection, c0, c1 };
  }, [countries, admin1, width, height, focus]);

  const admin1Countries = new Set(c1.map((f) => f.properties.iso3));
  // national borders and coastlines, drawn above every fill so they read the same everywhere
  const outlines = useMemo(
    () =>
      c0.map((f) => (
        <path key={`o-${f.properties.code}`} d={path(f as unknown as GeoPermissibleObjects) ?? ""} className="map-country-outline" />
      )),
    [c0, path],
  );
  // the hovered or focused unit is outlined on top, where neighbouring fills and borders cannot cover it
  const highlighted = hover ? [...c1, ...c0].find((f) => f.properties.code === hover.code) : undefined;
  // transport nodes sit on the (rounded) label point of their administrative unit
  const nodeNames = useMemo(() => {
    const m = new Map<string, string>();
    for (const f of [...c0, ...c1]) {
      const [lon, lat] = f.properties.label;
      if (lon !== null && lat !== null) m.set(`${lon},${lat}`, unitName(f.properties.code, f.properties.name, f.properties.level));
    }
    return m;
  }, [c0, c1]);
  const units = layers.units;

  const shape = (f: GeoFeature, cls: string) => {
    const code = f.properties.code;
    const u = units[code];
    const spec = fillFor(layer, u, code);
    const hasData = !!u && (layer === "transport" ? false : spec.fill !== null || spec.hatch);
    const d = path(f as unknown as GeoPermissibleObjects) ?? "";
    const name = unitName(code, f.properties.name, f.properties.level);
    const label = spec.text && spec.text !== name ? `${name}: ${spec.text}` : name;
    const show = (evt: { clientX: number; clientY: number } | null) => {
      const el = ref.current;
      if (!el) return;
      const box = el.getBoundingClientRect();
      let x = box.width / 2;
      let y = 20;
      if (evt) {
        x = evt.clientX - box.left;
        y = evt.clientY - box.top;
      } else if (f.properties.label[0] !== null) {
        const p = projection([f.properties.label[0] as number, f.properties.label[1] as number]);
        if (p) {
          x = (p[0] / width) * box.width;
          y = (p[1] / height) * box.height;
        }
      }
      setHover({ code, name, text: spec.text, x, y });
    };
    return (
      <path
        key={`${cls}-${code}`}
        d={d}
        className={`map-region ${cls}`}
        style={{ fill: spec.hatch ? "url(#map-hatch)" : spec.fill ?? "var(--not-assessed)" }}
        tabIndex={hasData && !compact ? 0 : undefined}
        role={hasData && !compact ? "button" : undefined}
        aria-label={hasData && !compact ? label : undefined}
        onMouseMove={(e) => show(e)}
        onMouseLeave={() => setHover(null)}
        onFocus={() => show(null)}
        onBlur={() => setHover(null)}
        onClick={() => u && u.level <= 1 && (u.official_confirmed || u.severity_level !== null) && navigate(`/region/${code}`)}
        onKeyDown={(e) => {
          if ((e.key === "Enter" || e.key === " ") && u) {
            e.preventDefault();
            navigate(`/region/${code}`);
          }
        }}
      >
        <title>{label}</title>
      </path>
    );
  };

  const markers =
    layer === "forecast_risk" || layer === "surveillance"
      ? [...c0, ...c1]
          .filter((f) => (resolution === 1 ? f.properties.level === 1 || !admin1Countries.has(f.properties.iso3) : f.properties.level === 0))
          .map((f) => ({ f, u: units[f.properties.code] }))
          .filter(({ f, u }) => u && f.properties.label[0] !== null && (layer === "forecast_risk" ? !!u.connectivity_tier : u.underestimation_risk))
      : [];

  return (
    <div className="map-wrap" ref={ref}>
      <svg viewBox={`0 0 ${width} ${height}`} role="group" aria-label={t("Map: {layer}", { layer: layerLabel(layer) })} direction="ltr">
        <defs>
          <pattern id="map-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="6" height="6" style={{ fill: "var(--not-assessed)" }} />
            <line x1="0" y1="0" x2="0" y2="6" style={{ stroke: "var(--sev-insufficient)", strokeWidth: 2 }} />
          </pattern>
        </defs>
        <rect width={width} height={height} style={{ fill: "var(--surface-1)" }} />
        {resolution === 1 &&
          c0.filter((f) => admin1Countries.has(f.properties.iso3)).map((f) => (
            // underlay: fills slivers where first-level boundaries (different source) do not meet the national outline
            <path key={`u-${f.properties.code}`} d={path(f as unknown as GeoPermissibleObjects) ?? ""} style={{ fill: "var(--not-assessed)" }} aria-hidden="true" />
          ))}
        {c0.map((f) => (resolution === 1 && admin1Countries.has(f.properties.iso3) ? null : shape(f, "admin0")))}
        {resolution === 1 && c1.map((f) => shape(f, "admin1"))}
        <g aria-hidden="true">{outlines}</g>
        {highlighted && <path d={path(highlighted as unknown as GeoPermissibleObjects) ?? ""} className="map-highlight" aria-hidden="true" />}
        {layer === "transport" &&
          layers.transport_edges.map((e) => {
            const a = projection(e.line[0] as [number, number]);
            const b = projection(e.line[1] as [number, number]);
            if (!a || !b) return null;
            const off = e.service_status === "suspended" || e.service_status === "non_operational";
            const svc = off ? "svc-off" : e.service_status === "unknown" ? "svc-unknown" : "svc-on";
            return (
              <line key={e.key} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} className={`map-edge mode-${e.mode} ${svc}`}>
                <title>
                  {t("{corridor} — {mode}; service {service}; verification {verification}", {
                    corridor: e.corridor ?? e.key,
                    mode: lower(e.mode),
                    service: humanize(e.service_status),
                    verification: humanize(e.verification),
                  })}
                </title>
              </line>
            );
          })}
        {layer === "transport" &&
          Array.from(new Set(layers.transport_edges.flatMap((e) => e.line.map((p) => p.join(","))))).map((k) => {
            const p = projection(k.split(",").map(Number) as [number, number]);
            if (!p) return null;
            const name = nodeNames.get(k);
            return (
              <g key={k}>
                <circle cx={p[0]} cy={p[1]} r={3} className="map-node" />
                {name && !compact && (
                  <text x={p[0] + 5} y={p[1] - 5} className="map-node-label">{name}</text>
                )}
              </g>
            );
          })}
        {markers.map(({ f, u }) => {
          const p = projection([f.properties.label[0] as number, f.properties.label[1] as number]);
          if (!p) return null;
          if (layer === "forecast_risk") {
            const tier = u.connectivity_tier!;
            return (
              <g key={`m-${f.properties.code}`} aria-hidden="true">
                <circle cx={p[0]} cy={p[1]} r={6} style={{ fill: TIER_FILL[tier.tier], stroke: "var(--surface-1)", strokeWidth: 2 }} />
              </g>
            );
          }
          return (
            <g key={`m-${f.properties.code}`} aria-hidden="true">
              <circle cx={p[0]} cy={p[1]} r={7} style={{ fill: "var(--surface-1)", stroke: "var(--text-primary)", strokeWidth: 1.5 }} />
              <text x={p[0]} y={p[1]} dy="0.35em" textAnchor="middle" style={{ fill: "var(--text-primary)", fontSize: 10, fontWeight: 700 }}>!</text>
            </g>
          );
        })}
      </svg>
      {hover && (
        <div className="chart-tooltip" style={{ left: Math.min(hover.x + 12, (ref.current?.clientWidth ?? width) - 250), top: Math.max(hover.y - 10, 0) }} role="status">
          <strong>{hover.name}</strong>
          {hover.text}
        </div>
      )}
      {!compact && <MapLegend layer={layer} layers={layers} />}
      {compact && <p className="small muted" style={{ margin: "6px 10px" }}>{layerLabel(layer)}: {tx(layers.layers[layer])}</p>}
    </div>
  );
}

function Chip({ fill, hatch }: { fill?: string; hatch?: boolean }) {
  return (
    <span
      className="chip"
      style={hatch ? { background: "repeating-linear-gradient(45deg, var(--sev-insufficient) 0 2px, var(--not-assessed) 2px 5px)" } : { background: fill }}
      aria-hidden="true"
    />
  );
}

export function MapLegend({ layer, layers }: { layer: LayerKey; layers: MapLayers }) {
  const tierLabels: Record<"higher" | "moderate" | "lower", string> = {
    higher: t("Higher connectivity to active areas"),
    moderate: t("Moderate connectivity to active areas"),
    lower: t("Lower connectivity to active areas"),
  };
  return (
    <div className="map-legend">
      <strong>{layerLabel(layer)}</strong> — {tx(layers.layers[layer])}
      {(layer === "official" || layer === "estimated") && (
        <ul className="scale">
          {burdenLabels().map((l, i) => (
            <li key={l}><Chip fill={BURDEN_FILLS[i]} /> <span translate="no">{l}</span></li>
          ))}
          <li><Chip fill="var(--not-assessed)" /> {layer === "official" ? t("None reported (not evidence of zero)") : t("No estimate")}</li>
        </ul>
      )}
      {layer === "estimated" && (
        <p className="small" style={{ margin: "6px 0 0" }}>{t("Model estimates of symptomatic infections, reported or not. They are not confirmed cases.")}</p>
      )}
      {layer === "forecast_risk" && (
        <>
          <ul className="scale">
            {[0, 1, 2, 3, 4].map((l) => (
              <li key={l}><Chip fill={`var(--sev-${l})`} /> {t("Level {n}", { n: l })} · {levelName(l)}</li>
            ))}
            <li><Chip hatch /> {t("Insufficient information")}</li>
            <li><Chip fill="var(--not-assessed)" /> {t("Not assessed")}</li>
          </ul>
          <ul className="scale">
            {(["higher", "moderate", "lower"] as const).map((tier) => (
              <li key={tier}><span className="chip" style={{ background: TIER_FILL[tier], borderRadius: "50%" }} aria-hidden="true" /> {tierLabels[tier]}</li>
            ))}
          </ul>
          <p className="small" style={{ margin: "6px 0 0" }}>
            {t("Connectivity tiers compare areas under scenarios for unverified transport services; they are relative, not probabilities, and are not evidence of transmission.")}
          </p>
        </>
      )}
      {layer === "surveillance" && (
        <ul className="scale">
          <li><Chip fill={CONF_FILL.low} /> {t("Low confidence")}</li>
          <li><Chip fill={CONF_FILL.moderate} /> {t("Moderate confidence")}</li>
          <li><Chip fill={CONF_FILL.high} /> {t("High confidence")}</li>
          <li><Chip hatch /> {t("Insufficient information")}</li>
          <li><span className="chip" style={{ borderRadius: "50%", textAlign: "center", fontSize: 9, lineHeight: "11px", fontWeight: 700 }} aria-hidden="true">!</span> {t("Risk that severity is underestimated")}</li>
        </ul>
      )}
      {layer === "transport" && (
        <>
          <ul className="scale">
            <li><span className="lkey" style={{ borderTopColor: "var(--series-1)" }} /> {t("Road")}</li>
            <li><span className="lkey" style={{ borderTopColor: "var(--series-1)", borderTopStyle: "dotted", borderTopWidth: 3 }} /> {t("Rail")}</li>
            <li><span className="lkey" style={{ borderTopColor: "var(--series-3)" }} /> {t("River or lake")}</li>
            <li><span className="lkey" style={{ borderTopColor: "var(--series-2)" }} /> {t("Air")}</li>
            <li><span className="lkey" style={{ borderTopColor: "var(--axis-muted)" }} /> {t("Informal (regional level only)")}</li>
            <li><span className="lkey" style={{ borderTopColor: "var(--text-secondary)", borderTopStyle: "dashed" }} /> {t("Dashed: passenger service unverified")}</li>
            <li><span className="lkey" style={{ borderTopColor: "var(--axis-muted)", borderTopStyle: "dotted", opacity: 0.7 }} /> {t("Faint dotted: suspended or not operating")}</li>
          </ul>
          {layers.transport_caveats.map((c) => (
            <p key={c} className="small" style={{ margin: "4px 0 0" }}>{tx(c)}</p>
          ))}
        </>
      )}
    </div>
  );
}

export function MapTable({ layer }: { layer: LayerKey }) {
  const layers = useApi<MapLayers>("/map/layers");
  if (!layers.data) return null;
  const rows = Object.entries(layers.data.units)
    .map(([code, u]) => ({ code, u, spec: fillFor(layer, u, code) }))
    .filter((r) => layer === "transport" ? false : r.spec.fill !== null || r.spec.hatch || r.u.severity_level)
    .sort((a, b) => a.u.level - b.u.level || a.u.name.localeCompare(b.u.name));
  if (layer === "transport") {
    return (
      <TableToggle label={t("Show corridors as a table")}>
        <DataTable
          rows={layers.data.transport_edges}
          columns={[
            { key: "c", header: t("Corridor"), render: (e) => e.corridor ?? e.key },
            { key: "m", header: t("Mode"), render: (e) => humanize(e.mode) },
            { key: "s", header: t("Service status"), render: (e) => humanize(e.service_status) },
            { key: "v", header: t("Verification"), render: (e) => humanize(e.verification) },
            { key: "x", header: t("Cross-border"), render: (e) => (e.cross_border ? t("Yes") : t("No")) },
          ]}
        />
      </TableToggle>
    );
  }
  return (
    <TableToggle label={t("Show map data as a table")}>
      <DataTable
        rows={rows}
        columns={[
          { key: "n", header: t("Area"), render: (r) => unitName(r.code, r.u.name, r.u.level) },
          { key: "l", header: t("Level"), render: (r) => (r.u.level === 0 ? t("Country") : t("First-level unit")) },
          { key: "v", header: layerLabel(layer), render: (r) => r.spec.text },
        ]}
      />
    </TableToggle>
  );
}
