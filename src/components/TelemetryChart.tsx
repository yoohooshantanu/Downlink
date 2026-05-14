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
}

export default function TelemetryChart({ noradId, parameter, lastN = 100 }: TelemetryChartProps) {
  const [data, setData] = useState<any[]>([]);
  const [trend, setTrend] = useState<any>(null);
  const [anomalies, setAnomalies] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;

    async function loadData(showLoading = true) {
      if (showLoading && data.length === 0) setLoading(true);
      try {
        const [telemRes, trendRes] = await Promise.all([
          fetchTelemetry(noradId, parameter, Math.max(lastN, 50)),
          fetchTrend(noradId, parameter)
        ]);

        if (!mounted) return;

        // Sort chronologically for charting
        const sortedData = [...telemRes.values].sort((a: any, b: any) => 
          new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
        );
        
        setData(sortedData);
        setTrend(trendRes.trend);
        setAnomalies(trendRes.anomalies || []);
      } catch (err) {
        console.error("Failed to poll telemetry:", err);
      } finally {
        if (mounted) setLoading(false);
      }
    }

    loadData(true);

    const intervalId = setInterval(() => {
      loadData(false);
    }, 10000);

    return () => {
      mounted = false;
      clearInterval(intervalId);
    };
  }, [noradId, parameter, lastN]);

  // Compute Y-axis domain with 10% padding and historical mean
  const { yDomain, historicalMean } = useMemo(() => {
    if (data.length === 0) return { yDomain: [0, 1] as [number, number], historicalMean: 0 };
    
    const values = data.map((d: any) => d.value).filter((v: number) => v != null && !isNaN(v));
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
    const map = new Map();
    anomalies.forEach((a) => map.set(a.timestamp, a));
    return map;
  }, [anomalies]);

  if (loading) {
    return (
      <div className="flex h-64 w-full items-center justify-center text-sm text-muted-foreground font-mono">
        Loading telemetry...
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
      </div>

      <div className="h-72 w-full">
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
              labelFormatter={(label) => new Date(label).toISOString().slice(0, 19).replace('T', ' ') + 'Z'}
              formatter={(value: number) => [value.toFixed(4), parameter]}
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
            {data.map((entry: any, index: number) => {
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
