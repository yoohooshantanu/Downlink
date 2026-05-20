/**
 * API client to interact with the FastAPI backend.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "/api";

export interface AIConfidence {
  confidence_score: number;
  data_coverage: number;
  reason: string;
}

export interface AIProvenance {
  prompt_version: string;
  model_used: string;
  model_stage: string;
  intent: string;
  data_hash: string;
  data_points_used: number;
  parameters_used: string[];
  time_window_start?: string | null;
  time_window_end?: string | null;
}

export interface AIQueryResponse {
  answer_text: string;
  intent?: { parameter_name?: string | null };
  chart_data: boolean;
  anomalies_flagged: AIAnomaly[];
  confidence?: AIConfidence;
  provenance?: AIProvenance;
  cache_hit?: boolean;
}

export interface AIAnomaly {
  parameter_name: string;
  value: number;
  mean: number;
  deviation_sigma?: number;
  severity?: string;
  timestamp?: string;
}

export interface PassParameterSummary {
  pass_mean?: number;
  mean?: number;
  historical_mean?: number;
  current?: number;
  pct_change?: number;
  vs_historical?: string;
  anomaly_flag?: boolean;
}

export interface PassSummaryResponse {
  status: string;
  pass_duration?: number;
  summary_text: string;
  parameters?: Record<string, PassParameterSummary>;
  confidence?: AIConfidence;
  provenance?: AIProvenance;
}

export async function fetchSatellites() {
  const res = await fetch(`${API_BASE}/satellites`, { cache: 'no-store' });
  if (!res.ok) throw new Error("Failed to fetch satellites");
  return res.json();
}

export async function fetchSatelliteDetail(noradId: number) {
  const res = await fetch(`${API_BASE}/satellites/${noradId}`, { cache: 'no-store' });
  if (!res.ok) throw new Error("Failed to fetch satellite detail");
  return res.json();
}

export async function fetchTelemetry(noradId: number, parameter?: string, lastN: number = 100) {
  const searchParams = new URLSearchParams();
  if (parameter) searchParams.append("parameter", parameter);
  searchParams.append("last_n", lastN.toString());
  
  const qs = searchParams.toString();
  const url = `${API_BASE}/satellites/${noradId}/telemetry?${qs}`;
  
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error("Failed to fetch telemetry");
  return res.json();
}

export async function fetchAnomalies(noradId: number) {
  const res = await fetch(`${API_BASE}/satellites/${noradId}/anomalies`, { cache: 'no-store' });
  if (!res.ok) throw new Error("Failed to fetch anomalies");
  return res.json();
}

export async function fetchTrend(noradId: number, parameter: string) {
  const res = await fetch(`${API_BASE}/satellites/${noradId}/trend/${parameter}`, { cache: 'no-store' });
  if (!res.ok) throw new Error("Failed to fetch trend");
  return res.json();
}

export async function submitAIQuery(noradId: number, query: string): Promise<AIQueryResponse> {
  const res = await fetch(`${API_BASE}/satellites/${noradId}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });
  if (!res.ok) throw new Error("Failed to submit query");
  return res.json();
}

export async function fetchPassSummary(noradId: number, obsId: string): Promise<PassSummaryResponse> {
  const res = await fetch(`${API_BASE}/satellites/${noradId}/observations/${obsId}/summary`, { cache: 'no-store' });
  if (!res.ok) throw new Error("Failed to fetch pass summary");
  return res.json();
}
