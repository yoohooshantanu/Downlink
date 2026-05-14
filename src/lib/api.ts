/**
 * API client to interact with the FastAPI backend.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "/api";

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

export async function fetchAnomaliesCount(noradId: number): Promise<number> {
  try {
    const res = await fetch(`${API_BASE}/satellites/${noradId}/anomalies`, { cache: 'no-store' });
    if (!res.ok) return 0;
    const data = await res.json();
    return data.count || 0;
  } catch {
    return 0;
  }
}

export async function fetchTrend(noradId: number, parameter: string) {
  const res = await fetch(`${API_BASE}/satellites/${noradId}/trend/${parameter}`, { cache: 'no-store' });
  if (!res.ok) throw new Error("Failed to fetch trend");
  return res.json();
}

export async function submitAIQuery(noradId: number, query: string) {
  const res = await fetch(`${API_BASE}/satellites/${noradId}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });
  if (!res.ok) throw new Error("Failed to submit query");
  return res.json();
}
