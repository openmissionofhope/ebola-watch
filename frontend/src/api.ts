// Typed client for the Ebola Watch API (same origin; CSP connect-src 'self').
//
// A static build (VITE_STATIC=1, for hosting without a server) reads the same
// responses from files written by `ebolawatch export-static`:
// GET /api/v1/<path> -> <base>data/<path>.json

import { t, tx } from "./i18n";

export const STATIC = import.meta.env.VITE_STATIC === "1";
export const BASE = import.meta.env.BASE_URL;
export const ERROR_REPORT_URL =
  import.meta.env.VITE_ERROR_REPORT_URL || "https://github.com/openmissionofhope/ebola-watch/issues/new?template=data-error.yml";

function endpoint(path: string): string {
  return STATIC ? `${BASE}data${path}.json` : `/api/v1${path}`;
}

/** URL of a downloadable file: report Markdown (`/reports/<id>.md`) or a CSV export (`/export/<name>.csv`). */
export function downloadUrl(path: string): string {
  if (STATIC) return `${BASE}data${path}`;
  const md = /^\/reports\/(\d+)\.md$/.exec(path);
  return md ? `/api/v1/reports/${md[1]}?format=markdown` : `/api/v1${path}`;
}

/** Interactive API documentation, or the description of the static data files. */
export const API_DOCS_URL = STATIC ? "https://github.com/openmissionofhope/ebola-watch/blob/main/docs/API.md#static-data-files" : "/api/docs";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function messageFor(status: number, detail: string | undefined): string {
  if (STATIC && status === 404) return t("This information is not part of the published snapshot.");
  if (status === 429) return t("The service is limiting requests right now. Please wait a moment and try again.");
  if (status === 401) return t("A valid API key is required.");
  if (status === 403) return t("Your API key does not have permission for this action.");
  if (status === 404) return detail ? tx(detail) : t("Not found at a publishable resolution.");
  if (status >= 500) return t("The server could not complete the request. Please try again later.");
  return detail ? tx(detail) : t("Request failed (HTTP {status}).", { status });
}

async function parse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail: string | undefined;
    try {
      const body = await res.json();
      detail = typeof body?.detail === "string" ? body.detail : undefined;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, messageFor(res.status, detail));
  }
  return (await res.json()) as T;
}

export async function getJSON<T>(path: string, apiKey?: string, signal?: AbortSignal): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (apiKey) headers["X-API-Key"] = apiKey;
  const res = await fetch(endpoint(path), { headers, signal, credentials: "omit" });
  return parse<T>(res);
}

export async function postJSON<T>(path: string, body: unknown, apiKey?: string): Promise<T> {
  if (STATIC) throw new ApiError(405, t("This is a published snapshot: it does not accept submissions."));
  const headers: Record<string, string> = { "Content-Type": "application/json", Accept: "application/json" };
  if (apiKey) headers["X-API-Key"] = apiKey;
  const res = await fetch(`/api/v1${path}`, { method: "POST", headers, body: JSON.stringify(body), credentials: "omit" });
  return parse<T>(res);
}

export async function getText(path: string): Promise<string> {
  const res = await fetch(downloadUrl(path), { credentials: "omit" });
  if (!res.ok) throw new ApiError(res.status, messageFor(res.status, undefined));
  return res.text();
}

// ---------------------------------------------------------------- types

export interface RegionRef { code: string; name: string; level: number; iso3: string }

export interface OfficialValue {
  value: number;
  as_of: string;
  source: string;
  source_key: string;
  citation: string | null;
  published_at: string | null;
  validation_status: string;
  extraction_method: string;
  is_synthetic: boolean;
}

export interface Estimate {
  label: string;
  insufficient: boolean;
  message?: string;
  reason?: string | null;
  median?: number;
  lower_90?: number;
  upper_90?: number;
  lower_50?: number | null;
  upper_50?: number | null;
  interval?: string;
  confidence?: string;
  method?: string;
  period_start?: string | null;
  period_end?: string | null;
  assumptions?: string[];
  details?: { disagreement?: Disagreement | null; primary_method?: string } & Record<string, unknown>;
}

export interface Disagreement {
  methods: string[];
  intervals_overlap: boolean;
  medians: Record<string, number>;
  substantial: boolean;
}

export interface Trigger { code: string; text: string; level: number | null }

export interface Severity {
  status: string;
  level: number | null;
  label: string;
  description?: string;
  confidence: string | null;
  underestimation_risk?: boolean;
  explanation: string;
  triggers: Trigger[];
  confidence_reasons?: string[];
  assessed_at?: string;
  data_as_of?: string | null;
  model_version?: string;
  is_synthetic?: boolean;
}

export interface Indicator { key: string; label: string; value: number | null; status: string; note: string }
export interface Surveillance { overall?: string; indicators?: Indicator[]; concerns?: string[]; confidence_reasons?: string[] }

export interface ForecastRow {
  horizon_days: number;
  median: number;
  lower_90: number;
  upper_90: number;
  lower_50: number;
  upper_50: number;
  p_continued_transmission: number | null;
  p_new_affected_unit: number | null;
  confidence: string;
  is_scenario: boolean;
  label: string;
}

export interface Forecasts {
  insufficient: boolean;
  message?: string;
  reason?: string | null;
  data_as_of?: string;
  issued_at?: string;
  targets?: Record<string, Record<string, ForecastRow[]>>;
  scenario_definitions?: Record<string, string>;
  comparison?: {
    compared: boolean;
    horizon_days?: number;
    renewal_median?: number;
    loglinear_median?: number;
    ratio?: number;
    intervals_overlap?: boolean;
    substantial_disagreement?: boolean;
    reason?: string;
  } | null;
}

export interface Expansion {
  insufficient: boolean;
  reason?: string;
  unit?: string;
  weekly_rate_median?: number;
  weekly_rate_90?: number[];
  p_new_unit?: Record<string, number>;
  expected_new_units?: Record<string, { lower_90: number; median: number; upper_90: number }>;
  method?: string;
}

export interface BurdenMethod {
  method: string;
  quantity: string;
  insufficient: boolean;
  reason: string | null;
  median: number | null;
  lower_90: number | null;
  upper_90: number | null;
  lower_50: number | null;
  upper_50: number | null;
  ascertainment: Record<string, number> | null;
  assumptions: string[];
  diagnostics: Record<string, unknown>;
}

export interface Outbreak {
  key: string;
  name: string;
  pathogen: string;
  declared_on: string | null;
  ended_on: string | null;
  auto_registered: boolean;
  citation: string | null;
}

export interface RegionSummary {
  region: RegionRef;
  outbreak?: Outbreak | null;
  official: Record<string, OfficialValue | null>;
  severity: Severity;
  model_version: string;
  is_synthetic: boolean;
  data_as_of?: string | null;
  latest_update?: string | null;
  model_status?: string;
  model_reasons?: string[];
  estimated_total?: Estimate;
  recent_incidence?: Estimate;
  rt?: Estimate;
  nowcast_reported?: Estimate;
  ascertainment?: { identifiable: boolean; message?: string; median?: number; lower_90?: number; upper_90?: number; method?: string; note?: string };
  model_disagreement?: Disagreement | null;
  expansion?: Expansion | null;
  surveillance?: Surveillance;
  growth?: { weekly_log_growth: number; se: number; doubling_or_halving_weeks: number | null; direction: string } | null;
  forecasts?: Forecasts;
  weekly?: { week_ends: string[]; reported_confirmed: number[]; interpolated_days: number[]; max_reporting_gap_days: number; mean_recent_reporting_interval_days?: number };
  rt_history?: { week_end: string; median: number; lower_90: number; upper_90: number }[] | null;
  burden_methods?: BurdenMethod[];
  parameters?: Record<string, unknown>;
}

export interface Alert {
  id: number | null;
  created_at: string;
  region?: RegionRef | null;
  kind: string;
  message: string;
  severity_level?: number | null;
  confidence?: string;
  relies_on_unofficial?: boolean;
  reviewed?: boolean;
  evidence?: { triggers?: { code: string; text: string }[]; summary?: string | null; independent_origins?: number | null; explanation?: string | null };
  retracted: boolean;
  is_synthetic?: boolean;
}

export interface Development { title: string; published_at: string | null; source: string; url: string | null; official: boolean; is_synthetic: boolean }

export interface MapEntry { code: string; name: string; level: number; severity_level: number | null; severity_status: string; confidence: string | null }

export interface Overview {
  disclaimer: string;
  generated_at: string;
  model_version: string;
  latest_model_run: string | null;
  contains_synthetic_data: boolean;
  regions: RegionSummary[];
  map: MapEntry[];
  alerts: Alert[];
  developments: Development[];
}

export interface Meta {
  name: string;
  organisation: string;
  website: string;
  version: string;
  model_version: string;
  disclaimer: string;
  contains_synthetic_data: boolean;
  latest_model_run: string | null;
  publication_policy: { max_admin_level: number; min_cell_count: number; min_subnational_population: number };
  static?: boolean;
  snapshot_generated_at?: string;
}

export interface SeriesPoint { as_of: string; value: number; source: string; source_key: string; published_at: string | null; citation: string | null; validation_status: string; is_synthetic: boolean }
export interface OfficialSeries {
  region: RegionRef;
  outbreak?: Outbreak | null;
  metric: string;
  case_class: string;
  points: SeriesPoint[];
  revisions: { as_of: string; source: string; previous: number; revised: number; revised_published_at: string | null }[];
  observations_pending_review: number;
  note: string;
}

export interface Cell { region_code: string; region_name: string; level: number; parent_code: string | null; value: number | null; suppressed: boolean; display: string | null; notes: string[] }
export interface Subnational { region: RegionRef; cells: Cell[]; note: string }

export interface TransportEdge {
  key: string;
  from: { code: string; name: string };
  to: { code: string; name: string };
  mode: string;
  corridor: string | null;
  cross_border: boolean;
  physical_status: string;
  service_status: string;
  verification: string;
  verified_on: string | null;
  seasonal_note: string | null;
  disruption_note: string | null;
  notes: string | null;
  sources: string[];
  line: number[][];
}

export interface RankingRow {
  unit: string;
  name: string;
  relative_score: Record<string, number>;
  rank: Record<string, number | null>;
  effective_distance: number | null;
  straight_line_km_from_nearest_source: number | null;
  path: string[];
  path_names: string[];
  path_modes: string[];
  share_unverified_links: number | null;
  rank_range: number[] | null;
  tier: string;
  robust: boolean;
}

export interface TransportContext { edges: TransportEdge[]; introduction_ranking: RankingRow[]; sources_of_risk: Record<string, number>; caveats: string[] }

export interface SignalCluster {
  id: number;
  unit: RegionRef | null;
  claim: string;
  assessment: string;
  corroboration: string;
  summary: string;
  first_seen: string | null;
  last_seen: string | null;
  independent_origins: string;
  items: string;
  languages: string[];
  coordination_suspected: boolean;
  stale: boolean;
  review_status: string;
  verification: string;
  is_synthetic: boolean;
}

export interface Evidence {
  region: RegionRef;
  official_sources: { title: string; source: string; category: string; published_at: string | null; url: string | null; official: boolean }[];
  observation_validation: Record<string, number>;
  unofficial_signals: SignalCluster[];
  published_estimates: { statement: string; citation: string; url: string | null; as_of: string | null; lower: number | null; upper: number | null; validation_status: string }[];
  assumptions: Record<string, unknown> | null;
  last_updated: string | null;
}

export interface ComparisonRow {
  issued_at?: string;
  data_as_of?: string;
  origin_date?: string;
  horizon_days: number;
  median: number;
  lower_90: number;
  upper_90: number;
  observed: number | null;
  within_90?: boolean | null;
  source?: string;
}

export interface HorizonEval {
  n: number;
  coverage_50: number;
  coverage_90: number;
  mean_wis: number;
  mae: number;
  median_relative_bias: number;
  pit_histogram_5bins: number[];
  calibration_note: string;
}
export interface EvalDataset {
  dataset: string;
  is_synthetic: boolean;
  run_at: string;
  summary: { n: number; by_horizon?: Record<string, HorizonEval> } | null;
  expansion: { horizon_days?: number; n?: number; brier?: number | null; base_rate?: number | null } | null;
  notes: string[];
  label: string;
}
export interface Evaluation { model_version: string; datasets: EvalDataset[]; detection_performance: { status: string; reason: string }; note: string }

export interface SourceStatus {
  key: string;
  name: string;
  institution: string | null;
  category: string;
  access_method: string;
  license: string | null;
  terms_note: string | null;
  status: string;
  status_message: string | null;
  last_attempt_at: string | null;
  last_success_at: string | null;
  homepage: string | null;
}

export interface ReportListItem { id: number; kind: string; title: string; generated_at: string; data_as_of: string | null; scope: string[]; status: string; is_synthetic: boolean }
export interface ReportDetail { id: number; kind: string; title: string; generated_at: string; status: string; retraction_note: string | null; markdown: string | null; is_synthetic: boolean }

export interface MapUnit {
  name: string;
  level: number;
  official_confirmed: number | null;
  official_display?: string;
  official_as_of: string | null;
  estimated_total: { median: number; lower_90: number; upper_90: number; confidence: string } | null;
  severity_level: number | null;
  severity_status: string;
  confidence: string | null;
  underestimation_risk: boolean;
  surveillance_overall: string | null;
  connectivity_tier: { tier: string; robust: boolean } | null;
}
export interface MapLayers {
  units: Record<string, MapUnit>;
  transport_edges: { key: string; mode: string; service_status: string; verification: string; cross_border: boolean; corridor: string | null; line: number[][] }[];
  transport_caveats: string[];
  layers: Record<string, string>;
}

export interface GeoFeature {
  type: "Feature";
  properties: { code: string; name: string; iso3: string; level: number; label: [number | null, number | null] };
  geometry: GeoJSON.Geometry;
}
export interface GeoCollection { type: "FeatureCollection"; features: GeoFeature[]; attribution: string }

export interface QueryAnswer { answered: boolean; intent: string; message: string; region?: RegionRef; disclaimer: string }

export interface ReviewItem { id: number; item_type: string; item_id: number; reason: string; priority: number; created_at: string; status: string }
export interface AdminAlert { id: number; kind: string; message: string; review_status: string; published: boolean; relies_on_unofficial: boolean; evidence: Record<string, unknown> }
