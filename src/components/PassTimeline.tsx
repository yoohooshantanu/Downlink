"use client";

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

interface PassItem {
  observation_id: string;
  status?: string;
  ground_station?: string;
  station_name?: string;
  start_time?: string;
}

interface PassTimelineProps {
  passes: PassItem[];
  onSelectPass: (obsId: string) => void;
  selectedPassId?: string;
}

function formatPassStart(value: string | undefined): string {
  if (!value) return "-- --:--";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "-- --:--";
  return d.toISOString().slice(5, 16).replace("T", " ");
}

export default function PassTimeline({ passes, onSelectPass, selectedPassId }: PassTimelineProps) {
  if (!passes || passes.length === 0) {
    return (
      <div className="font-data" style={{ fontSize: "11px", color: C.secondary, padding: "8px 0" }}>
        No recent passes recorded.
      </div>
    );
  }

  return (
    <div style={{ width: "100%", overflowX: "auto" }}>
      <div style={{ display: "flex", gap: "4px", minWidth: "max-content" }}>
        {passes.map((pass) => {
          const isSelected = pass.observation_id === selectedPassId;
          const borderColor = pass.status === "good" ? C.green : pass.status === "bad" ? C.secondary : C.orange;

          return (
            <button
              key={pass.observation_id}
              onClick={() => onSelectPass(pass.observation_id)}
              style={{
                width: "120px",
                height: "48px",
                padding: "6px 8px",
                display: "flex",
                flexDirection: "column",
                justifyContent: "center",
                gap: "2px",
                borderRadius: "2px",
                borderTop: isSelected ? `1px solid ${C.blue}` : `1px solid ${C.border}`,
                borderRight: isSelected ? `1px solid ${C.blue}` : `1px solid ${C.border}`,
                borderBottom: isSelected ? `1px solid ${C.blue}` : `1px solid ${C.border}`,
                borderLeft: `3px solid ${borderColor}`,
                backgroundColor: isSelected ? "rgba(56, 139, 253, 0.08)" : "transparent",
                cursor: "pointer",
                transition: "background-color 0.15s",
                textAlign: "left",
                flexShrink: 0,
              }}
              onMouseEnter={(e) => {
                if (!isSelected) e.currentTarget.style.backgroundColor = C.hover;
              }}
              onMouseLeave={(e) => {
                if (!isSelected) e.currentTarget.style.backgroundColor = "transparent";
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span
                  className="font-data"
                  style={{
                    fontSize: "10px",
                    color: isSelected ? C.blue : C.secondary,
                  }}
                >
                  {pass.observation_id}
                </span>
              </div>
              <span
                style={{
                  fontSize: "11px",
                  fontWeight: 600,
                  color: isSelected ? C.primary : C.secondary,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {pass.ground_station || pass.station_name || "GS"}
              </span>
              <span className="font-data" style={{ fontSize: "10px", color: C.secondary }}>
                {formatPassStart(pass.start_time)}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
