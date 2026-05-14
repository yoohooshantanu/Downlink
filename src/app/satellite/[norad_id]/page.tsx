"use client";

import React, { useEffect, useState, useMemo } from "react";
import Link from "next/link";

import AnomalyPanel from "@/components/AnomalyPanel";
import PassTimeline from "@/components/PassTimeline";
import AIQueryBox from "@/components/AIQueryBox";
import TelemetryChart from "@/components/TelemetryChart";
import { fetchSatelliteDetail, fetchAnomalies, fetchTrend } from "@/lib/api";
import { getFlagEmoji } from "@/lib/utils";

/**
 * Tiny sparkline component — renders a simple SVG line chart
 * for the last ~10 values of a parameter.
 */
function Sparkline({ values, color = "#58a6ff" }: { values: number[]; color?: string }) {
  if (!values || values.length < 2) return null;
  const w = 48, h = 16;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const points = values.map((v, i) => {
    const x = (i / (values.length - 1)) * w;
    const y = h - ((v - min) / range) * h;
    return `${x},${y}`;
  }).join(" ");

  return (
    <svg width={w} height={h} className="flex-shrink-0" viewBox={`0 0 ${w} ${h}`}>
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/**
 * Trend arrow — only shown when change exceeds 2% over last 10 readings.
 * Up green triangle, down red triangle, nothing below 2%.
 */
function TrendArrow({ direction, percentChange }: { direction?: string; percentChange?: number }) {
  if (!direction || !percentChange) return null;
  const absChange = Math.abs(percentChange);
  if (absChange < 2) return null; // Below 2% = show nothing

  if (direction === "increasing") {
    return (
      <span className="text-[var(--color-status-ok)]" title={`+${percentChange}%`}>
        ▲
      </span>
    );
  }
  if (direction === "decreasing") {
    return (
      <span className="text-[var(--color-status-error)]" title={`${percentChange}%`}>
        ▼
      </span>
    );
  }
  return null;
}

export default function OpsView({ params }: { params: Promise<{ norad_id: string }> }) {
  const resolvedParams = React.use(params);
  const noradId = parseInt(resolvedParams.norad_id, 10);
  
  const [data, setData] = useState<any>(null);
  const [anomalies, setAnomalies] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  
  const [selectedPass, setSelectedPass] = useState<string | undefined>();
  const [selectedParam, setSelectedParam] = useState<string | undefined>();

  useEffect(() => {
    let mounted = true;

    async function load(showLoading = true) {
      if (showLoading && !data) setLoading(true);
      try {
        const [detail, anomalyData] = await Promise.all([
          fetchSatelliteDetail(noradId),
          fetchAnomalies(noradId)
        ]);

        if (!mounted) return;

        setData(detail);
        setAnomalies(anomalyData.anomalies || []);
        
        // Auto-select first parameter if available
        if (detail.parameters && detail.parameters.length > 0 && !selectedParam) {
          setSelectedParam(detail.parameters[0]);
        }
        
      } catch (err) {
        console.error("Failed backend data refresh:", err);
      } finally {
        if (mounted) setLoading(false);
      }
    }
    
    load(true);

    const intervalId = setInterval(() => {
      load(false);
    }, 15000);

    return () => {
      mounted = false;
      clearInterval(intervalId);
    };
  }, [noradId]);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <span className="text-sm text-muted-foreground font-mono animate-pulse">
          Connecting to NORAD {noradId}...
        </span>
      </div>
    );
  }

  const sat = data?.satellite;
  const flag = getFlagEmoji(sat?.countries);
  const lastContact = sat?.fetched_at 
    ? new Date(sat.fetched_at).toISOString().slice(0, 19).replace('T', ' ') + 'Z' 
    : "—";

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {/* Compact top header bar */}
      <header className="border-b border-border bg-card px-4 py-2 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center space-x-4">
          <Link href="/" className="flex items-center space-x-2 text-xs text-muted-foreground hover:text-foreground transition-colors">
            <img src="/logo.png" alt="Orbitwatch Logo" className="w-4 h-auto" />
            <span>← Back</span>
          </Link>
          <div className="h-4 border-l border-border" />
          <span className="text-sm font-semibold text-foreground">
            {flag && <span className="mr-2">{flag}</span>}
            {sat?.name || "Unknown"}
          </span>
          <span className="font-mono text-xs text-[var(--color-accent-blue)]">{noradId}</span>
          <span
            className={`inline-block h-2 w-2 rounded-full ${
              sat?.status === "alive" ? "bg-[var(--color-status-ok)]" :
              sat?.status === "dead" ? "bg-[var(--color-status-error)]" :
              "bg-[var(--color-status-warn)]"
            }`}
            title={sat?.status || "unknown"}
          />
          {sat?.operator && (
            <>
              <div className="h-4 border-l border-border" />
              <span className="text-xs text-muted-foreground">{sat.operator}</span>
            </>
          )}
        </div>
        <span className="text-[10px] font-mono text-muted-foreground">
          Last contact: {lastContact}
        </span>
      </header>

      {/* Main content — two-column layout */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left column — 65% */}
        <div className="flex-[65] flex flex-col min-w-0 border-r border-border">
          
          {/* Pass timeline */}
          <div className="border-b border-border px-4 py-2">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">
                Observations
              </span>
              <span className="text-[10px] font-mono text-muted-foreground">
                {data?.recent_passes?.length || 0} passes
              </span>
            </div>
            <PassTimeline 
              passes={data?.recent_passes || []} 
              onSelectPass={(id) => setSelectedPass(id)}
              selectedPassId={selectedPass}
            />
          </div>

          {/* Anomaly inline warnings — above the chart */}
          {anomalies.length > 0 && (
            <div className="border-b border-border">
              <AnomalyPanel anomalies={anomalies} />
            </div>
          )}

          {/* AI Query Box */}
          <div className="border-b border-border px-4 py-3">
            <AIQueryBox noradId={noradId} />
          </div>

          {/* Parameter chart — takes remaining height */}
          <div className="flex-1 flex flex-col px-4 py-3 min-h-0">
            <div className="flex items-center space-x-3 mb-2">
              <select 
                className="bg-card border border-border rounded px-2 py-1 text-xs font-mono text-foreground focus:outline-none focus:border-[var(--color-accent-blue)] transition-colors"
                value={selectedParam}
                onChange={(e) => setSelectedParam(e.target.value)}
              >
                {data?.parameters?.map((p: string) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
            </div>
            
            <div className="flex-1 min-h-[280px]">
              {selectedParam ? (
                <TelemetryChart noradId={noradId} parameter={selectedParam} lastN={50} />
              ) : (
                <div className="text-xs text-muted-foreground font-mono py-4">
                  No parameters available
                </div>
              )}
            </div>
          </div>



        </div>

        {/* Right column — 35% — Parameter list */}
        <div className="flex-[35] flex flex-col min-w-0 overflow-hidden">
          <div className="px-4 py-2 border-b border-border flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">
              Parameters
            </span>
            <span className="text-[10px] font-mono text-muted-foreground">
              {data?.parameter_count || 0}
            </span>
          </div>
          
          <div className="flex-1 overflow-y-auto">
            {data?.parameters?.map((p: string) => {
              const summary = data?.parameter_summaries?.[p];
              const isActive = selectedParam === p;
              
              // Build tiny sparkline from last/first values if we have them
              // We use the trend data to approximate sparkline values
              const sparkValues = summary ? [
                summary.first_value || 0,
                ((summary.first_value || 0) + (summary.last_value || 0)) / 2,
                summary.last_value || 0
              ] : [];

              return (
                <button
                  key={p}
                  onClick={() => setSelectedParam(p)}
                  className={`w-full text-left flex items-center px-4 py-2 text-xs transition-colors border-b border-border ${
                    isActive 
                      ? "bg-[#1c2128] border-l-2 border-l-[var(--color-accent-blue)]" 
                      : "hover:bg-[#1c2128] border-l-2 border-l-transparent"
                  }`}
                >
                  <span className="flex-1 truncate text-foreground min-w-0 pr-2">
                    {p}
                  </span>
                  
                  {/* Current value in monospace */}
                  {summary?.last_value != null && (
                    <span className="font-mono text-[11px] text-muted-foreground mr-2 flex-shrink-0">
                      {summary.last_value.toFixed(2)}
                    </span>
                  )}
                  
                  {/* Trend arrow — only if >2% change */}
                  <span className="text-[10px] mr-2 flex-shrink-0 w-3 text-center">
                    <TrendArrow 
                      direction={summary?.direction} 
                      percentChange={summary?.percent_change} 
                    />
                  </span>
                  
                  {/* Sparkline */}
                  <Sparkline 
                    values={sparkValues}
                    color={isActive ? "#58a6ff" : "#7d8590"}
                  />
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
