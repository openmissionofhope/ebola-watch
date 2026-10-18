import { useState } from "react";
import { PageHead } from "../components/Layout";
import { LAYER_LABELS, MapTable, MapView, type LayerKey } from "../charts/MapView";
import { useDocumentTitle } from "../hooks";

const LAYERS: LayerKey[] = ["official", "estimated", "forecast_risk", "surveillance", "transport"];

export function MapPage() {
  useDocumentTitle("Map");
  const [layer, setLayer] = useState<LayerKey>("official");
  const [resolution, setResolution] = useState<0 | 1>(1);
  const [focus, setFocus] = useState<"africa" | "central">("central");
  return (
    <>
      <PageHead title="Map" />
      <p className="secondary">
        Each layer shows one quantity. Official reports, model estimates, forecast risk and surveillance quality are never combined into a single colour.
        Boundaries are simplified; first-level units are shown only for priority countries and nothing finer is published.
      </p>
      <div className="card" style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center", marginBottom: 12 }}>
        <div role="group" aria-label="Map layer" className="segmented">
          {LAYERS.map((l) => (
            <button key={l} type="button" aria-pressed={layer === l} onClick={() => setLayer(l)}>
              {LAYER_LABELS[l]}
            </button>
          ))}
        </div>
        <div role="group" aria-label="Resolution" className="segmented">
          <button type="button" aria-pressed={resolution === 0} onClick={() => setResolution(0)}>Countries</button>
          <button type="button" aria-pressed={resolution === 1} onClick={() => setResolution(1)}>First-level units</button>
        </div>
        <div role="group" aria-label="Extent" className="segmented">
          <button type="button" aria-pressed={focus === "central"} onClick={() => setFocus("central")}>Central & East Africa</button>
          <button type="button" aria-pressed={focus === "africa"} onClick={() => setFocus("africa")}>Africa</button>
        </div>
      </div>
      <MapView layer={layer} resolution={resolution} focus={focus} />
      <p className="small muted" style={{ marginTop: 8 }}>
        Select an area (click, or focus it with Tab and press Enter) to open its regional view. Boundaries: Natural Earth; geoBoundaries (licences in NOTICE).
      </p>
      <MapTable layer={layer} />
    </>
  );
}
