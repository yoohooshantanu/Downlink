"use client";

import { useEffect, useState, useMemo } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceDot,
  ReferenceLine,
} from "recharts";
import { fetchTelemetry, fetchTrend } from "@/lib/api";

interface TelemetryChartProps {
  noradId: number;
  parameter: string;
  lastN?: number;
  pollingEnabled?: boolean;
  compact?: boolean;
}

interface TelemetryPoint {
  timestamp: string;
  value: number;
}

interface TrendAnomaly {
  parameter_name?: string;
  value?: number;
  mean?: number;
  deviation_sigma?: number;
  severity?: string;
  timestamp?: string;
}

interface TelemetryResponse {
  values?: unknown[];
  is_simulated?: boolean;
}

interface TrendResponse {
  trend?: {
    direction?: string;
    percent_change?: number;
  };
  anomalies?: TrendAnomaly[];
}

function toTelemetryPoint(input: unknown): TelemetryPoint | null {
  if (!input || typeof input !== "object") return null;
  const obj = input as Record<string, unknown>;
  const timestamp = typeof obj.timestamp === "string" ? obj.timestamp : "";
  const numeric = typeof obj.value === "number" ? obj.value : Number(obj.value);
  if (!timestamp || !Number.isFinite(numeric)) return null;
  return { timestamp, value: numeric };
}

export default function TelemetryChart({
  noradId,
  parameter,
  lastN = 100,
  pollingEnabled = true,
  compact = false,
}: TelemetryChartProps) {
  const [data, setData] = useState<TelemetryPoint[]>([]);
  const [anomalies, setAnomalies] = useState<TrendAnomaly[]>([]);
  const [loading, setLoading] = useState(true);
  const [isSimulated, setIsSimulated] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);

  useEffect(() => {
    let mounted = true;

    async function loadData(showLoading = true) {
      if (showLoading && data.length === 0) setLoading(true);
      try {
        const [telemResRaw, trendResRaw] = await Promise.all([
          fetchTelemetry(noradId, parameter, Math.max(lastN, 50)),
          fetchTrend(noradId, parameter)
        ]);
        const telemRes = telemResRaw as TelemetryResponse;
        const trendRes = trendResRaw as TrendResponse;

        if (!mounted) return;

        // Sort chronologically for charting
        const rawValues = Array.isArray(telemRes.values) ? telemRes.values : [];
        const sortedData = rawValues
          .map(toTelemetryPoint)
          .filter((v): v is TelemetryPoint => v !== null)
          .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
        
        setData(sortedData);
        setAnomalies(Array.isArray(trendRes.anomalies) ? trendRes.anomalies : []);
        setIsSimulated(Boolean(telemRes.is_simulated));
        setLoadError(null);
      } catch (err) {
        console.error("Failed to poll telemetry:", err);
        if (mounted) setLoadError("Telemetry refresh failed. Showing latest available data.");
      } finally {
        if (mounted) setLoading(false);
      }
    }

    loadData(true);

    let intervalId: ReturnType<typeof setInterval> | undefined;
    if (pollingEnabled) {
      intervalId = setInterval(() => {
        if (document.visibilityState !== "visible") return;
        loadData(false);
      }, 10000);
    }

    return () => {
      mounted = false;
      if (intervalId) clearInterval(intervalId);
    };
  }, [noradId, parameter, lastN, pollingEnabled, refreshTick]);

  // Compute Y-axis domain with 10% padding and historical mean
  const { yDomain, historicalMean } = useMemo(() => {
    if (data.length === 0) return { yDomain: [0, 1] as [number, number], historicalMean: 0 };
    
    const values = data.map((d) => d.value).filter((v) => Number.isFinite(v));
    if (values.length === 0) return { yDomain: [0, 1] as [number, number], historicalMean: 0 };
    
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || Math.abs(max) * 0.1 || 1;
    const padding = range * 0.1;
    const mean = values.reduce((a: number, b: number) => a + b, 0) / values.length;
    
    return {
      yDomain: [min - padding, max + padding] as [number, number],
      historicalMean: mean,
    };
  }, [data]);

  // Create lookup for anomalies by timestamp
  const anomalyMap = useMemo(() => {
    const map = new Map<string, TrendAnomaly>();
    anomalies.forEach((a) => {
      if (typeof a.timestamp === "string") map.set(a.timestamp, a);
    });
    return map;
  }, [anomalies]);

  if (loading) {
    return (
      <div className="flex h-64 w-full items-center justify-center text-sm text-muted-foreground font-mono">
        Loading telemetry...
      </div>
    );
  }

  if (data.length === 0 && loadError) {
    return (
      <div className="flex h-64 w-full flex-col items-center justify-center gap-3 text-sm text-muted-foreground font-mono">
        <span>{loadError}</span>
        <button
          type="button"
          onClick={() => {
            setLoading(true);
            setRefreshTick((v) => v + 1);
          }}
          className="rounded border border-border px-3 py-1 text-xs text-foreground hover:bg-[#1c2128]"
        >
          Retry
        </button>
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div className="flex h-64 w-full items-center justify-center text-sm text-muted-foreground font-mono">
        No data for "{parameter}"
      </div>
    );
  }

  const formatTime = (isoString: string) => {
    const d = new Date(isoString);
    return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
  };

  return (
    <div className="w-full">
      {/* No large title — the dropdown parameter selector IS the label */}
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] font-mono text-muted-foreground">
          {data.length} readings
        </span>
        {compact && (
          <span className="text-[10px] font-mono text-[var(--color-accent-blue)]">
            AI Focus Chart
          </span>
        )}
      </div>

      {loadError && (
        <div className="bg-amber-900/20 text-amber-500 text-[11px] px-3 py-2 rounded-md flex items-center mb-3 border border-amber-900/50 font-mono">
          <span>{loadError}</span>
        </div>
      )}

      {isSimulated && (
        <div className="bg-amber-900/20 text-amber-500 text-[11px] px-3 py-2 rounded-md flex items-center mb-3 border border-amber-900/50 font-mono">
          <span className="mr-2">⚠️</span>
          <span><strong>Simulator Active:</strong> SatNOGS API rate limited. Displaying synthetic procedural telemetry.</span>
        </div>
      )}

      <div className={`${compact ? "h-44" : "h-72"} w-full`}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#21262d" vertical={false} />
            <XAxis 
              dataKey="timestamp" 
              tickFormatter={formatTime}
              stroke="#7d8590" 
              fontSize={10}
              fontFamily="var(--font-mono), monospace"
              tickMargin={8} 
              interval="preserveStartEnd"
              minTickGap={30}
            />
            <YAxis 
              domain={yDomain}
              stroke="#7d8590" 
              fontSize={10}
              fontFamily="var(--font-mono), monospace"
              tickFormatter={(v) => v.toFixed(2)}
              width={56}
            />
            <Tooltip 
              contentStyle={{ 
                backgroundColor: '#161b22', 
                borderColor: '#30363d', 
                borderRadius: '4px',
                fontSize: '11px',
                fontFamily: 'var(--font-mono), monospace',
              }}
              labelFormatter={(label) => {
                const d = new Date(String(label));
                if (Number.isNaN(d.getTime())) return "Invalid timestamp";
                return `${d.toISOString().slice(0, 19).replace("T", " ")}Z`;
              }}
              formatter={(value) => {
                const numeric = typeof value === "number" ? value : Number(value);
                return [Number.isFinite(numeric) ? numeric.toFixed(4) : "N/A", parameter];
              }}
            />
            
            {/* Historical mean reference line */}
            <ReferenceLine 
              y={historicalMean} 
              stroke="#7d8590" 
              strokeDasharray="4 4" 
              strokeWidth={1}
            />
            
            <Line 
              type="monotone" 
              dataKey="value" 
              stroke="#58a6ff" 
              strokeWidth={1.5}
              dot={false}
              activeDot={{ r: 3, fill: "#58a6ff", stroke: "#0d1117", strokeWidth: 1 }}
            />
            
            {/* Anomaly markers */}
            {data.map((entry, index) => {
              const anomaly = anomalyMap.get(entry.timestamp);
              if (anomaly) {
                return (
                  <ReferenceDot 
                    key={`anomaly-${index}`}
                    x={entry.timestamp} 
                    y={entry.value} 
                    r={3} 
                    fill="#f85149" 
                    stroke="#0d1117" 
                    strokeWidth={1}
                  />
                );
              }
              return null;
            })}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
