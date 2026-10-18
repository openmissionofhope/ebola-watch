import { useState } from "react";
import { PageHead } from "../components/Layout";
import { MapTable, MapView, layerLabel, type LayerKey } from "../charts/MapView";
import { useDocumentTitle } from "../hooks";
import { t } from "../i18n";

const LAYERS: LayerKey[] = ["official", "estimated", "forecast_risk", "surveillance", "transport"];

export function MapPage() {
  useDocumentTitle(t("Map"));
  const [layer, setLayer] = useState<LayerKey>("official");
  const [resolution, setResolution] = useState<0 | 1>(1);
  const [focus, setFocus] = useState<"africa" | "central">("central");
  return (
    <>
      <PageHead title={t("Map")} />
      <p className="secondary">
        {t(
          "Each layer shows one quantity. Official reports, model estimates, forecast risk and surveillance quality are never combined into a single colour. Boundaries are simplified; first-level units are shown only for priority countries and nothing finer is published.",
        )}
      </p>
      <div className="card" style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center", marginBottom: 12 }}>
        <div role="group" aria-label={t("Map layer")} className="segmented">
          {LAYERS.map((l) => (
            <button key={l} type="button" aria-pressed={layer === l} onClick={() => setLayer(l)}>
              {layerLabel(l)}
            </button>
          ))}
        </div>
        <div role="group" aria-label={t("Resolution")} className="segmented">
          <button type="button" aria-pressed={resolution === 0} onClick={() => setResolution(0)}>{t("Countries")}</button>
          <button type="button" aria-pressed={resolution === 1} onClick={() => setResolution(1)}>{t("First-level units")}</button>
        </div>
        <div role="group" aria-label={t("Extent")} className="segmented">
          <button type="button" aria-pressed={focus === "central"} onClick={() => setFocus("central")}>{t("Central & East Africa")}</button>
          <button type="button" aria-pressed={focus === "africa"} onClick={() => setFocus("africa")}>{t("Africa")}</button>
        </div>
      </div>
      <MapView layer={layer} resolution={resolution} focus={focus} />
      <p className="small muted" style={{ marginTop: 8 }}>
        {t(
          "Select an area (click, or focus it with Tab and press Enter) to open its regional view. Boundaries: Natural Earth; geoBoundaries (licences in NOTICE).",
        )}
      </p>
      <MapTable layer={layer} />
    </>
  );
}
