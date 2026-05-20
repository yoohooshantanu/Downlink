"use client";

interface AnomalyPanelProps {
  anomalies: Array<{
    parameter_name?: string;
    value?: number;
    mean?: number;
    deviation_sigma?: number;
    timestamp?: string;
  }>;
}

function formatNumber(value: number | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "N/A";
  return value.toFixed(2);
}

function formatTime(value: string | undefined): string {
  if (!value) return "--:--:--Z";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "--:--:--Z";
  return `${d.toISOString().slice(11, 19)}Z`;
}

export default function AnomalyPanel({ anomalies }: AnomalyPanelProps) {
  if (!anomalies || anomalies.length === 0) {
    return null;
  }

  return (
    <div className="space-y-0">
      {anomalies.slice(0, 10).map((anomaly, idx) => (
        <div
          key={idx}
          className="flex items-center justify-between border-l-2 border-l-[var(--color-status-error)] bg-[#1c1017] px-3 py-1.5 text-xs"
          style={{ borderBottom: "1px solid #30363d" }}
        >
          <div className="flex items-center space-x-3">
            <span className="text-foreground font-medium">{anomaly.parameter_name || "unknown_parameter"}</span>
            <span className="font-mono text-[var(--color-status-error)]">{formatNumber(anomaly.value)}</span>
            <span className="text-muted-foreground">vs μ {formatNumber(anomaly.mean)}</span>
            <span className="font-mono text-muted-foreground">
              {typeof anomaly.deviation_sigma === "number" ? `${anomaly.deviation_sigma}σ` : "N/A"}
            </span>
          </div>
          <span className="font-mono text-muted-foreground text-[10px]">{formatTime(anomaly.timestamp)}</span>
        </div>
      ))}
    </div>
  );
}
