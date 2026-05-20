"use client";

import { useState } from "react";
import { submitAIQuery, type AIQueryResponse, type AIAnomaly } from "@/lib/api";
import TelemetryChart from "./TelemetryChart";

interface AIQueryBoxProps {
  noradId: number;
}

const EXAMPLE_QUERIES = [
  "Battery voltage trend last 10 passes",
  "Any anomalies in the last 24 hours?",
  "What happened recently?",
  "Compare solar current morning vs evening",
];

function formatPercent(value: number | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "N/A";
  return `${(value * 100).toFixed(0)}%`;
}

export default function AIQueryBox({ noradId }: AIQueryBoxProps) {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AIQueryResponse | null>(null);

  const handleSubmit = async (e?: React.FormEvent, customQuery?: string) => {
    e?.preventDefault();
    const q = customQuery || query;
    if (!q.trim()) return;

    setLoading(true);
    setResult(null);
    setQuery(q);

    try {
      const data = await submitAIQuery(noradId, q);
      setResult(data);
    } catch (err) {
      console.error(err);
      setResult({
        answer_text: "Analysis request failed.",
        chart_data: false,
        anomalies_flagged: [],
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-2">
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">
        Telemetry Query
      </span>
      
      <form onSubmit={handleSubmit} className="flex space-x-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Query telemetry trends, anomalies, or pass behavior..."
          className="flex-1 bg-card border border-border rounded px-3 py-1.5 text-xs font-mono placeholder:text-muted-foreground focus:outline-none focus:border-[var(--color-accent-blue)] transition-colors"
          disabled={loading}
        />
        <button
          type="submit"
          disabled={loading || !query.trim()}
          className="px-3 py-1.5 text-xs bg-[#21262d] border border-border rounded text-foreground hover:bg-[#30363d] disabled:opacity-40 transition-colors"
        >
          {loading ? "..." : "Analyze"}
        </button>
      </form>

      {/* Example queries */}
      <div className="flex flex-wrap gap-1">
        {EXAMPLE_QUERIES.map((q, i) => (
          <button
            key={i}
            onClick={() => handleSubmit(undefined, q)}
            disabled={loading}
            className="text-[10px] text-muted-foreground border border-border rounded px-2 py-0.5 hover:text-foreground hover:border-[var(--color-accent-blue)]/30 transition-colors"
          >
            {q}
          </button>
        ))}
      </div>

      {/* Result */}
      {loading && (
        <div className="text-xs text-muted-foreground font-mono py-3 animate-pulse">
          Running analysis...
        </div>
      )}

      {result && !loading && (
        <div className="space-y-3">
          <div className="border border-border rounded bg-card px-3 py-2 text-xs text-foreground whitespace-pre-wrap font-mono leading-relaxed">
            {result.answer_text}
          </div>

          {(result.confidence || result.provenance) && (
            <details className="border border-border rounded bg-[#0f1419] px-3 py-2">
              <summary className="text-[10px] text-muted-foreground font-mono cursor-pointer">
                Analysis details
              </summary>
              <div className="mt-2 space-y-1">
                {result.confidence && (
                  <div className="text-[10px] text-muted-foreground font-mono">
                    Score {formatPercent(result.confidence.confidence_score)} |
                    Coverage {formatPercent(result.confidence.data_coverage)} |
                    {` ${result.confidence.reason}`}
                  </div>
                )}
                {result.provenance && (
                  <div className="text-[10px] text-muted-foreground font-mono">
                    {result.provenance.model_used} | {result.provenance.model_stage} |
                    {` ${result.provenance.intent} | v${result.provenance.prompt_version}`}
                    {result.cache_hit ? " | cached" : ""}
                  </div>
                )}
              </div>
            </details>
          )}

          {result.chart_data && result.intent?.parameter_name && (
            <TelemetryChart 
              noradId={noradId} 
              parameter={result.intent.parameter_name} 
              lastN={100}
              pollingEnabled={false}
              compact
            />
          )}
          
          {!result.chart_data && result.anomalies_flagged && result.anomalies_flagged.length > 0 && (
            <div className="space-y-0">
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium mb-1">
                Flagged Deviations
              </div>
              {result.anomalies_flagged.slice(0, 5).map((a: AIAnomaly, i: number) => (
                <div
                  key={i}
                  className="flex items-center space-x-3 border-l-2 border-l-[var(--color-status-error)] bg-[#1c1017] px-3 py-1 text-xs"
                  style={{ borderBottom: '1px solid #30363d' }}
                >
                  <span className="font-medium text-foreground">{a.parameter_name}</span>
                  <span className="font-mono text-[var(--color-status-error)]">{a.value?.toFixed?.(2) ?? "N/A"}</span>
                  <span className="text-muted-foreground">vs μ {a.mean?.toFixed?.(2) ?? "N/A"}</span>
                  <span className="text-muted-foreground font-mono text-[10px]">{a.severity}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
