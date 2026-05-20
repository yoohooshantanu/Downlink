"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import AnomalyPanel from "@/components/AnomalyPanel";
import PassTimeline from "@/components/PassTimeline";
import PassSummaryCard from "@/components/PassSummaryCard";
import AIQueryBox from "@/components/AIQueryBox";
import TelemetryChart from "@/components/TelemetryChart";
import { fetchSatelliteDetail, fetchAnomalies, fetchPassSummary, type PassSummaryResponse } from "@/lib/api";
import { getFlagEmoji } from "@/lib/utils";

type ParameterSummary = {
  first_value?: number;
  last_value?: number;
  direction?: string;
  percent_change?: number;
};

type SatelliteDetailPayload = {
  satellite?: {
    name?: string;
    countries?: string;
    status?: string;
    operator?: string;
    fetched_at?: string;
  };
  parameters?: string[];
  parameter_summaries?: Record<string, ParameterSummary>;
  recent_passes?: Array<{
    observation_id: string;
    status?: string;
    ground_station?: string;
    station_name?: string;
    start_time?: string;
  }>;
  parameter_count?: number;
};

type AnomalyItem = {
  parameter_name?: string;
  value?: number;
  mean?: number;
  deviation_sigma?: number;
  timestamp?: string;
};

function formatUtc(value: string | undefined): string {
  if (!value) return "-";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "-";
  return `${d.toISOString().slice(0, 19).replace("T", " ")}Z`;
}

function safeFixed(value: number | undefined, digits: number): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "N/A";
  return value.toFixed(digits);
}

function Sparkline({ values, color = "#58a6ff" }: { values: number[]; color?: string }) {
  if (!values || values.length < 2) return null;
  const w = 48;
  const h = 16;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const points = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * w;
      const y = h - ((v - min) / range) * h;
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <svg width={w} height={h} className="flex-shrink-0" viewBox={`0 0 ${w} ${h}`}>
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function TrendArrow({ direction, percentChange }: { direction?: string; percentChange?: number }) {
  if (!direction || typeof percentChange !== "number") return null;
  const absChange = Math.abs(percentChange);
  if (absChange < 2) return null;

  if (direction === "increasing") {
    return (
      <span className="text-[var(--color-status-ok)]" title={`+${percentChange}%`}>
        ↑
      </span>
    );
  }
  if (direction === "decreasing") {
    return (
      <span className="text-[var(--color-status-error)]" title={`${percentChange}%`}>
        ↓
      </span>
    );
  }
  return null;
}

export default function OpsView({ params }: { params: Promise<{ norad_id: string }> }) {
  const resolvedParams = React.use(params);
  const rawNoradId = resolvedParams.norad_id;
  const noradId = Number(rawNoradId);
  const hasValidNoradId = /^\d+$/.test(rawNoradId) && Number.isInteger(noradId) && noradId > 0;

  const [data, setData] = useState<SatelliteDetailPayload | null>(null);
  const [anomalies, setAnomalies] = useState<AnomalyItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);

  const [selectedPass, setSelectedPass] = useState<string | undefined>();
  const [selectedParam, setSelectedParam] = useState<string | undefined>();

  const [passSummary, setPassSummary] = useState<PassSummaryResponse | null>(null);
  const [loadingPass, setLoadingPass] = useState(false);

  useEffect(() => {
    if (!hasValidNoradId) {
      setLoading(false);
      setRefreshError("Invalid NORAD ID.");
      setData(null);
      return;
    }

    setSelectedPass(undefined);
    setSelectedParam(undefined);
    setPassSummary(null);
    setData(null);
    setAnomalies([]);
    setRefreshError(null);
    setLoading(true);
  }, [hasValidNoradId, noradId]);

  useEffect(() => {
    let mounted = true;

    async function loadPass() {
      if (!hasValidNoradId) {
        setPassSummary(null);
        setLoadingPass(false);
        return;
      }

      if (!selectedPass) {
        setPassSummary(null);
        setLoadingPass(false);
        return;
      }

      setPassSummary(null);
      setLoadingPass(true);
      try {
        const summary = await fetchPassSummary(noradId, selectedPass);
        if (mounted) setPassSummary(summary);
      } catch (err) {
        console.error("Failed to load pass summary", err);
        if (mounted) setPassSummary(null);
      } finally {
        if (mounted) setLoadingPass(false);
      }
    }

    loadPass();

    return () => {
      mounted = false;
    };
  }, [hasValidNoradId, noradId, selectedPass]);

  useEffect(() => {
    if (!selectedPass || !data?.recent_passes) return;
    const stillExists = data.recent_passes.some((pass) => pass.observation_id === selectedPass);
    if (!stillExists) {
      setSelectedPass(undefined);
      setPassSummary(null);
    }
  }, [data?.recent_passes, selectedPass]);

  useEffect(() => {
    let mounted = true;

    async function load(showLoading = true) {
      if (!hasValidNoradId) {
        if (mounted) setLoading(false);
        return;
      }

      if (showLoading) setLoading(true);
      try {
        const [detail, anomalyData] = await Promise.all([fetchSatelliteDetail(noradId), fetchAnomalies(noradId)]);
        if (!mounted) return;

        setData(detail);
        setAnomalies(anomalyData.anomalies || []);
        setRefreshError(null);

        setSelectedParam((prev) => {
          const params = detail.parameters || [];
          if (prev && params.includes(prev)) return prev;
          return params.length > 0 ? params[0] : undefined;
        });
      } catch (err) {
        console.error("Failed backend data refresh:", err);
        if (mounted) {
          setRefreshError("Unable to refresh satellite data. Automatic polling will continue.");
        }
      } finally {
        if (mounted) setLoading(false);
      }
    }

    load(true);

    const intervalId = setInterval(() => {
      if (document.visibilityState !== "visible") return;
      load(false);
    }, 15000);

    return () => {
      mounted = false;
      clearInterval(intervalId);
    };
  }, [hasValidNoradId, noradId, refreshTick]);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <span className="text-sm text-muted-foreground font-mono animate-pulse">Connecting to NORAD {noradId}...</span>
      </div>
    );
  }

  if (!hasValidNoradId) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background px-4">
        <div className="max-w-xl rounded border border-border bg-card p-4 text-sm text-muted-foreground">
          <div className="mb-2">Invalid satellite identifier: "{rawNoradId}".</div>
          <Link href="/" className="text-xs text-foreground underline underline-offset-4">
            Back to satellite list
          </Link>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background px-4">
        <div className="max-w-xl rounded border border-border bg-card p-4 text-sm text-muted-foreground">
          <div className="mb-3">Failed to load satellite telemetry view.</div>
          <button
            type="button"
            onClick={() => setRefreshTick((v) => v + 1)}
            className="rounded border border-border px-3 py-1 text-xs text-foreground hover:bg-[#1c2128]"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  const sat = data.satellite;
  const flag = getFlagEmoji(sat?.countries);
  const lastContact = formatUtc(sat?.fetched_at);

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <header className="border-b border-border bg-card px-4 py-2 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center space-x-4">
          <Link href="/" className="flex items-center space-x-2 text-xs text-muted-foreground hover:text-foreground transition-colors">
            <ArrowLeft className="h-3.5 w-3.5" />
            <span>Back</span>
          </Link>
          <div className="h-4 border-l border-border" />
          <span className="text-sm font-semibold text-foreground">
            {flag && <span className="mr-2">{flag}</span>}
            {sat?.name || "Unknown"}
          </span>
          <span className="font-mono text-xs text-[var(--color-accent-blue)]">{noradId}</span>
          <span
            className={`inline-block h-2 w-2 rounded-full ${
              sat?.status === "alive"
                ? "bg-[var(--color-status-ok)]"
                : sat?.status === "dead"
                  ? "bg-[var(--color-status-error)]"
                  : "bg-[var(--color-status-warn)]"
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
        <span className="text-[10px] font-mono text-muted-foreground">Last contact: {lastContact}</span>
      </header>

      {refreshError && (
        <div className="border-b border-amber-700/50 bg-amber-900/20 px-4 py-2 text-xs text-amber-400">{refreshError}</div>
      )}

      <div className="flex-1 flex overflow-hidden">
        <div className="flex-[65] flex flex-col min-w-0 border-r border-border">
          <div className="border-b border-border px-4 py-2">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">Observations</span>
              <span className="text-[10px] font-mono text-muted-foreground">{data.recent_passes?.length || 0} passes</span>
            </div>
            <PassTimeline
              passes={data.recent_passes || []}
              onSelectPass={(id) => {
                setPassSummary(null);
                setSelectedPass(id);
              }}
              selectedPassId={selectedPass}
            />
          </div>

          {selectedPass && (
            <div className="border-b border-border p-4">
              <PassSummaryCard summary={passSummary} loading={loadingPass} />
            </div>
          )}

          {anomalies.length > 0 && (
            <div className="border-b border-border">
              <AnomalyPanel anomalies={anomalies} />
            </div>
          )}

          <div className="border-b border-border px-4 py-3">
            <AIQueryBox noradId={noradId} />
          </div>

          <div className="flex-1 flex flex-col px-4 py-3 min-h-0">
            <div className="flex-1 min-h-[280px]">
              {selectedParam ? (
                <TelemetryChart noradId={noradId} parameter={selectedParam} lastN={50} />
              ) : (
                <div className="text-xs text-muted-foreground font-mono py-4">No parameters available</div>
              )}
            </div>
          </div>
        </div>

        <div className="flex-[35] flex flex-col min-w-0 overflow-hidden">
          <div className="px-4 py-2 border-b border-border flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">Parameters</span>
            <span className="text-[10px] font-mono text-muted-foreground">{data.parameter_count || 0}</span>
          </div>

          <div className="flex-1 overflow-y-auto">
            {data.parameters?.map((p: string) => {
              const summary = data.parameter_summaries?.[p];
              const isActive = selectedParam === p;
              const firstValue = typeof summary?.first_value === "number" ? summary.first_value : 0;
              const lastValue = typeof summary?.last_value === "number" ? summary.last_value : 0;
              const sparkValues = summary ? [firstValue, (firstValue + lastValue) / 2, lastValue] : [];

              return (
                <button
                  key={p}
                  onClick={() => setSelectedParam(p)}
                  className={`w-full text-left flex items-center px-4 py-2 text-xs transition-colors border-b border-border ${
                    isActive ? "bg-[#1c2128] border-l-2 border-l-[var(--color-accent-blue)]" : "hover:bg-[#1c2128] border-l-2 border-l-transparent"
                  }`}
                >
                  <span className="flex-1 truncate text-foreground min-w-0 pr-2">{p}</span>

                  {typeof summary?.last_value === "number" && (
                    <span className="font-mono text-[11px] text-muted-foreground mr-2 flex-shrink-0">{safeFixed(summary.last_value, 2)}</span>
                  )}

                  <span className="text-[10px] mr-2 flex-shrink-0 w-3 text-center">
                    <TrendArrow direction={summary?.direction} percentChange={summary?.percent_change} />
                  </span>

                  <Sparkline values={sparkValues} color={isActive ? "#58a6ff" : "#7d8590"} />
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
