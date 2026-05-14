"use client";

import { useState, useEffect } from "react";
import SatelliteSelector from "@/components/SatelliteSelector";

function UTCClock() {
  const [time, setTime] = useState("");

  useEffect(() => {
    function tick() {
      const now = new Date();
      setTime(now.toISOString().slice(0, 19) + "Z");
    }
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <span className="font-data text-xs" style={{ color: "#768390" }}>
      {time}
    </span>
  );
}

export default function Home() {
  return (
    <main className="min-h-screen" style={{ backgroundColor: "#0a0e14" }}>
      {/* Header */}
      <header
        className="px-6 py-3 flex items-center justify-between"
        style={{ borderBottom: "1px solid #1e2733", backgroundColor: "#0f1419" }}
      >
        <div className="flex items-center" style={{ gap: "10px" }}>
          <img src="/logo.png" alt="Orbitwatch Logo" style={{ width: "24px", height: "auto" }} />
          <span
            className="text-sm tracking-tight"
            style={{ color: "#cdd9e5", fontWeight: 600 }}
          >
            Orbitwatch
          </span>
          <span className="text-xs" style={{ color: "#768390" }}>
            Ground Station Telemetry
          </span>
        </div>

        <div className="flex items-center" style={{ gap: "12px" }}>
          <UTCClock />
          <div className="flex items-center" style={{ gap: "6px" }}>
            <span
              className="pulse-live"
              style={{
                display: "inline-block",
                width: "6px",
                height: "6px",
                borderRadius: "50%",
                backgroundColor: "#3fb950",
              }}
            />
            <span className="text-xs" style={{ color: "#768390" }}>
              SatNOGS LIVE
            </span>
          </div>
        </div>
      </header>

      <div className="px-6 py-4">
        <SatelliteSelector />
      </div>
    </main>
  );
}
