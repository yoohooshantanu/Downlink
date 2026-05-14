"use client";

interface AnomalyPanelProps {
  anomalies: any[];
}

export default function AnomalyPanel({ anomalies }: AnomalyPanelProps) {
  if (!anomalies || anomalies.length === 0) {
    return null; // No anomalies = no section shown
  }

  return (
    <div className="space-y-0">
      {anomalies.slice(0, 10).map((anomaly, idx) => (
        <div 
          key={idx}
          className="flex items-center justify-between border-l-2 border-l-[var(--color-status-error)] bg-[#1c1017] px-3 py-1.5 text-xs"
          style={{ borderBottom: '1px solid #30363d' }}
        >
          <div className="flex items-center space-x-3">
            <span className="text-foreground font-medium">{anomaly.parameter_name}</span>
            <span className="font-mono text-[var(--color-status-error)]">
              {anomaly.value.toFixed(2)}
            </span>
            <span className="text-muted-foreground">
              vs μ {anomaly.mean.toFixed(2)}
            </span>
            <span className="font-mono text-muted-foreground">
              {anomaly.deviation_sigma}σ
            </span>
          </div>
          <span className="font-mono text-muted-foreground text-[10px]">
            {new Date(anomaly.timestamp).toISOString().slice(11, 19)}Z
          </span>
        </div>
      ))}
    </div>
  );
}
