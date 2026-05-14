"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { fetchSatellites, fetchAnomaliesCount } from "@/lib/api";
import { getFlagEmoji } from "@/lib/utils";

// Color constants — exact spec
const C = {
  bg: "#0a0e14",
  surface: "#0f1419",
  hover: "#141b24",
  border: "#1e2733",
  primary: "#cdd9e5",
  secondary: "#768390",
  blue: "#388bfd",
  green: "#3fb950",
  orange: "#d29922",
  red: "#f85149",
};

export default function SatelliteSelector() {
  const router = useRouter();
  const [satellites, setSatellites] = useState<any[]>([]);
  const [anomalyCounts, setAnomalyCounts] = useState<Record<number, number>>({});
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [telemetryOnly, setTelemetryOnly] = useState(false);

  useEffect(() => {
    async function load() {
      try {
        const data = await fetchSatellites();
        const sats = data.satellites || [];
        setSatellites(sats);

        // Fetch anomaly counts for satellites with telemetry (non-blocking)
        const withTelemetry = sats.filter((s: any) => s.has_telemetry);
        const counts: Record<number, number> = {};
        await Promise.allSettled(
          withTelemetry.map(async (s: any) => {
            const count = await fetchAnomaliesCount(s.norad_id);
            counts[s.norad_id] = count;
          })
        );
        setAnomalyCounts(counts);
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  if (loading) {
    return (
      <div className="flex h-[50vh] items-center justify-center">
        <span className="font-data text-sm animate-pulse" style={{ color: C.secondary }}>
          Loading satellites…
        </span>
      </div>
    );
  }

  // Apply filters
  let filtered = satellites;

  if (telemetryOnly) {
    filtered = filtered.filter((s) => s.has_telemetry);
  }

  if (searchQuery.trim() !== "") {
    const q = searchQuery.toLowerCase();
    filtered = filtered.filter(
      (s) =>
        s.name?.toLowerCase().includes(q) ||
        String(s.norad_id).includes(q) ||
        s.operator?.toLowerCase().includes(q)
    );
  }

  // Sort: telemetry satellites first, then by name
  const sorted = [...filtered].sort((a, b) => {
    if (a.norad_id === 39444) return -1;
    if (b.norad_id === 39444) return 1;
    if (a.has_telemetry && !b.has_telemetry) return -1;
    if (!a.has_telemetry && b.has_telemetry) return 1;
    return 0;
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
      {/* Filter bar — full width input + telemetry toggle */}
      <div className="flex items-center" style={{ gap: "12px" }}>
        <input
          type="text"
          placeholder="Filter by name, NORAD ID, or operator…"
          className="font-data"
          style={{
            flex: 1,
            backgroundColor: "transparent",
            border: `1px solid ${C.border}`,
            borderRadius: "2px",
            padding: "8px 12px",
            fontSize: "13px",
            color: C.primary,
            outline: "none",
          }}
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          onFocus={(e) => (e.target.style.borderColor = C.blue)}
          onBlur={(e) => (e.target.style.borderColor = C.border)}
        />
        <label
          className="flex items-center cursor-pointer select-none"
          style={{ gap: "6px", fontSize: "12px", color: C.secondary, whiteSpace: "nowrap" }}
        >
          <input
            type="checkbox"
            style={{ accentColor: C.blue, width: "12px", height: "12px" }}
            checked={telemetryOnly}
            onChange={(e) => setTelemetryOnly(e.target.checked)}
          />
          Telemetry only
        </label>
      </div>

      {/* Table — no outer card or border */}
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
        <thead>
          <tr
            style={{
              borderBottom: `1px solid ${C.border}`,
              fontSize: "11px",
              color: C.secondary,
              textTransform: "uppercase",
              letterSpacing: "0.05em",
            }}
          >
            <th style={{ textAlign: "left", padding: "8px 12px", fontWeight: 500, width: "80px" }}>
              NORAD ID
            </th>
            <th style={{ textAlign: "left", padding: "8px 12px", fontWeight: 500 }}>Name</th>
            <th
              style={{ textAlign: "left", padding: "8px 12px", fontWeight: 500 }}
              className="hidden md:table-cell"
            >
              Operator
            </th>
            <th style={{ textAlign: "center", padding: "8px 12px", fontWeight: 500, width: "60px" }}>
              Status
            </th>
            <th
              style={{ textAlign: "left", padding: "8px 12px", fontWeight: 500 }}
              className="hidden lg:table-cell"
            >
              Last Contact
            </th>
            <th style={{ textAlign: "right", padding: "8px 12px", fontWeight: 500, width: "72px" }}>
              Params
            </th>
            <th style={{ textAlign: "right", padding: "8px 12px", fontWeight: 500, width: "88px" }}>
              Anomalies
            </th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((sat) => {
            const anomalyCount = anomalyCounts[sat.norad_id] || 0;
            const hasAnomalies = anomalyCount > 0;
            const flag = getFlagEmoji(sat.countries);

            return (
              <tr
                key={sat.norad_id}
                className="group"
                style={{
                  borderBottom: `1px solid ${C.border}`,
                  cursor: "pointer",
                  transition: "background-color 0.15s",
                  borderLeft: hasAnomalies ? `2px solid ${C.red}` : "2px solid transparent",
                }}
                onClick={() => router.push(`/satellite/${sat.norad_id}`)}
                onMouseEnter={(e) =>
                  (e.currentTarget.style.backgroundColor = C.hover)
                }
                onMouseLeave={(e) =>
                  (e.currentTarget.style.backgroundColor = "transparent")
                }
              >
                {/* NORAD ID — monospace blue link */}
                <td
                  className="font-data"
                  style={{ padding: "8px 12px", fontSize: "12px", color: C.blue }}
                >
                  {sat.norad_id}
                </td>

                {/* NAME — semibold, primary if telemetry, secondary if not */}
                <td
                  style={{
                    padding: "8px 12px",
                    fontWeight: 600,
                    fontSize: "13px",
                    color: sat.has_telemetry ? C.primary : C.secondary,
                  }}
                >
                  <span style={{ marginRight: flag ? "6px" : 0 }}>{flag}</span>
                  {sat.name}
                  {hasAnomalies && (
                    <span
                      style={{
                        display: "inline-block",
                        width: "6px",
                        height: "6px",
                        borderRadius: "50%",
                        backgroundColor: C.red,
                        marginLeft: "8px",
                        verticalAlign: "middle",
                      }}
                    />
                  )}
                </td>

                {/* OPERATOR */}
                <td
                  className="hidden md:table-cell"
                  style={{
                    padding: "8px 12px",
                    fontSize: "12px",
                    color: C.secondary,
                    maxWidth: "200px",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {sat.operator || "—"}
                </td>

                {/* STATUS — 12px dot */}
                <td style={{ padding: "8px 12px", textAlign: "center" }}>
                  <span
                    style={{
                      display: "inline-block",
                      width: "8px",
                      height: "8px",
                      borderRadius: "50%",
                      backgroundColor:
                        sat.status === "alive"
                          ? C.green
                          : sat.status === "dead"
                          ? C.red
                          : C.orange,
                    }}
                    title={sat.status || "unknown"}
                  />
                </td>

                {/* LAST CONTACT */}
                <td
                  className="font-data hidden lg:table-cell"
                  style={{ padding: "8px 12px", fontSize: "11px", color: C.secondary }}
                >
                  {sat.fetched_at
                    ? new Date(sat.fetched_at)
                        .toISOString()
                        .slice(0, 19)
                        .replace("T", " ") + "Z"
                    : "—"}
                </td>

                {/* PARAMS */}
                <td
                  className="font-data"
                  style={{
                    padding: "8px 12px",
                    fontSize: "12px",
                    textAlign: "right",
                    color: C.secondary,
                  }}
                >
                  {sat.has_telemetry ? sat.parameter_count : "—"}
                </td>

                {/* ANOMALIES */}
                <td
                  className="font-data"
                  style={{
                    padding: "8px 12px",
                    fontSize: "12px",
                    textAlign: "right",
                    color: hasAnomalies ? C.red : C.secondary,
                    fontWeight: hasAnomalies ? 600 : 400,
                  }}
                >
                  {hasAnomalies ? anomalyCount : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {sorted.length === 0 && (
        <div style={{ textAlign: "center", padding: "32px", fontSize: "13px", color: C.secondary }}>
          No satellites match filters.
        </div>
      )}

      <div className="font-data" style={{ fontSize: "10px", color: C.secondary }}>
        {sorted.length} satellites · {sorted.filter((s) => s.has_telemetry).length} with telemetry
      </div>
    </div>
  );
}
