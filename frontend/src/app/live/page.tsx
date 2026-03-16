"use client";
import { useEffect } from "react";
import BottomDock from "@/components/BottomDock";
import LiveScoreOverlay from "@/components/live/LiveScoreOverlay";
import { useFPLStore } from "@/store/fpl.store";

export default function LivePage() {
  const { fetchLiveScore, liveSquad } = useFPLStore();

  useEffect(() => {
    fetchLiveScore();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)" }}>
      <main style={{ maxWidth: 720, margin: "0 auto", padding: "32px 20px 96px", display: "flex", flexDirection: "column", gap: 16 }}>

        <div>
          <h1 style={{ fontFamily: "var(--font-display)", fontSize: "clamp(26px, 4vw, 40px)", fontWeight: 700, color: "var(--text-1)", letterSpacing: "-0.04em" }}>
            Live Scoring
          </h1>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 6 }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--green)", display: "inline-block", boxShadow: "0 0 8px var(--green)" }} />
            <p style={{ fontSize: 11, color: "var(--text-3)", fontFamily: "var(--font-ui)" }}>
              Updates every 60s during active gameweek
            </p>
          </div>
        </div>

        {liveSquad && liveSquad.live_data_available ? (
          <LiveScoreOverlay />
        ) : (
          <div
            className="glass"
            style={{ borderRadius: 16, padding: "56px 20px", textAlign: "center" }}
          >
            <div style={{ height: 2, width: 32, background: "var(--divider)", margin: "0 auto 16px", borderRadius: 999 }} />
            <p style={{ fontFamily: "var(--font-display)", fontSize: 15, fontWeight: 600, color: "var(--text-2)", letterSpacing: "-0.02em" }}>
              {liveSquad ? "Fixtures not started" : "Not live yet"}
            </p>
            <p style={{ fontSize: 11, color: "var(--text-3)", fontFamily: "var(--font-ui)", marginTop: 6 }}>
              {liveSquad
                ? `GW${liveSquad.gameweek} fixtures haven't kicked off yet. Live scoring will appear once matches begin.`
                : "Activates when gameweek fixtures kick off. Sync your squad first."}
            </p>
          </div>
        )}
      </main>
      <BottomDock />
    </div>
  );
}
