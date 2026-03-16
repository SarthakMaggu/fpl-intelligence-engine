"use client";
import { useEffect, useRef } from "react";
import { motion } from "framer-motion";
import { useFPLStore } from "@/store/fpl.store";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000/ws/live";

export default function LiveScoreOverlay() {
  const { liveSquad, updateLiveScore, fetchLiveScore } = useFPLStore();
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    fetchLiveScore();

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data);
        if (msg.event === "live:score_update" && msg.data) {
          updateLiveScore(msg.data);
        }
      } catch {}
    };

    ws.onerror = () => {
      const interval = setInterval(fetchLiveScore, 60_000);
      return () => clearInterval(interval);
    };

    return () => { ws.close(); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!liveSquad) return null;

  const starters = liveSquad.squad.filter((p) => p.multiplier > 0);
  const bench    = liveSquad.squad.filter((p) => p.multiplier === 0);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>

      {/* ── Total points hero ─────────────────────────────────────── */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ type: "spring", stiffness: 240, damping: 26 }}
        className="glass"
        style={{
          borderRadius: 16, padding: "22px 24px",
          display: "flex", justifyContent: "space-between", alignItems: "center",
          position: "relative", overflow: "hidden",
        }}
      >
        {/* Background watermark */}
        <div style={{
          position: "absolute", inset: 0, display: "flex",
          alignItems: "center", paddingLeft: 20, pointerEvents: "none", opacity: 0.03,
        }}>
          <span style={{
            fontFamily: "var(--font-display)", fontSize: 100, fontWeight: 700,
            color: "var(--green)", letterSpacing: "-0.04em", whiteSpace: "nowrap",
          }}>LIVE</span>
        </div>

        <div style={{ position: "relative", zIndex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
            <span style={{
              width: 7, height: 7, borderRadius: "50%",
              background: "var(--green)", display: "inline-block",
              boxShadow: "0 0 10px var(--green)", animation: "captain-pulse 2s ease-in-out infinite",
            }} />
            <span style={{
              fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 600,
              color: "var(--green)", letterSpacing: "0.14em", textTransform: "uppercase",
            }}>
              GW{liveSquad.gameweek} · live
            </span>
          </div>
          <span style={{
            fontFamily: "var(--font-ui)", fontSize: 13, color: "var(--text-3)",
          }}>
            Total points
          </span>
        </div>

        <motion.div
          key={liveSquad.total_live_points}
          initial={{ scale: 1.15 }}
          animate={{ scale: 1 }}
          transition={{ type: "spring", stiffness: 400, damping: 22 }}
          style={{ textAlign: "right", position: "relative", zIndex: 1 }}
        >
          <span style={{
            display: "block",
            fontFamily: "var(--font-data)",
            fontSize: 72,
            fontWeight: 600,
            color: "var(--green)",
            letterSpacing: "-0.04em",
            lineHeight: 0.9,
          }}>
            {liveSquad.total_live_points}
          </span>
          <span style={{
            fontSize: 10, color: "var(--text-3)",
            fontFamily: "var(--font-ui)", letterSpacing: "0.1em", textTransform: "uppercase",
          }}>
            pts
          </span>
        </motion.div>
      </motion.div>

      {/* ── Starters grid ─────────────────────────────────────────── */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ type: "spring", stiffness: 220, damping: 26, delay: 0.1 }}
        className="glass"
        style={{ borderRadius: 14, padding: "16px 16px 14px" }}
      >
        <p style={{
          fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 600,
          color: "var(--text-3)", letterSpacing: "0.12em", textTransform: "uppercase",
          marginBottom: 10,
        }}>
          Starting XI
        </p>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {starters.map((p, i) => (
            <motion.div
              key={p.player_id}
              layout
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.03, type: "spring", stiffness: 300 }}
              style={{
                display: "flex", justifyContent: "space-between", alignItems: "center",
                padding: "9px 12px",
                background: p.is_captain
                  ? "rgba(245,158,11,0.06)"
                  : p.playing
                  ? "rgba(34,197,94,0.04)"
                  : "rgba(255,255,255,0.02)",
                border: `1px solid ${p.is_captain ? "rgba(245,158,11,0.22)" : "var(--divider)"}`,
                borderRadius: 10,
              }}
            >
              {/* Left: badge + captain marker + name + stats */}
              <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                {p.team_code && (
                  <img
                    src={`https://resources.premierleague.com/premierleague/badges/25/t${p.team_code}.png`}
                    alt="" width={16} height={16} style={{ objectFit: "contain", flexShrink: 0, opacity: 0.85 }}
                    onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                  />
                )}
                <div style={{ minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                    {p.is_captain && (
                      <span style={{ fontFamily: "var(--font-display)", fontSize: 9, fontWeight: 700, color: "var(--amber)" }}>
                        {p.multiplier === 3 ? "TC" : "C"}
                      </span>
                    )}
                    {p.is_vice_captain && !p.is_captain && (
                      <span style={{ fontFamily: "var(--font-display)", fontSize: 9, fontWeight: 700, color: "var(--text-3)" }}>V</span>
                    )}
                    <span style={{ fontSize: 12, fontWeight: 500, color: p.playing ? "var(--text-1)" : "var(--text-3)", fontFamily: "var(--font-ui)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {p.web_name}
                    </span>
                  </div>
                  {/* Mini stats row */}
                  {(p.minutes > 0 || p.goals > 0 || p.assists > 0 || p.bonus > 0) && (
                    <div style={{ display: "flex", alignItems: "center", gap: 5, marginTop: 2 }}>
                      {p.minutes > 0 && (
                        <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)" }}>{p.minutes}&apos;</span>
                      )}
                      {p.goals > 0 && (
                        <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--green)", fontWeight: 600 }}>⚽ {p.goals}</span>
                      )}
                      {p.assists > 0 && (
                        <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--blue)", fontWeight: 600 }}>🅰 {p.assists}</span>
                      )}
                      {p.bonus > 0 && (
                        <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--amber)", fontWeight: 600 }}>+{p.bonus}b</span>
                      )}
                    </div>
                  )}
                </div>
              </div>
              {/* Right: points */}
              <motion.span
                key={p.effective_points}
                initial={{ scale: 1.3, color: "var(--green)" }}
                animate={{ scale: 1, color: p.effective_points > 0 ? "var(--text-1)" : "var(--text-3)" }}
                transition={{ type: "spring", stiffness: 400 }}
                style={{ fontFamily: "var(--font-data)", fontSize: 15, fontWeight: 600, letterSpacing: "-0.02em", flexShrink: 0 }}
              >
                {p.effective_points}
              </motion.span>
            </motion.div>
          ))}
        </div>
      </motion.div>

      {/* ── Bench ─────────────────────────────────────────────────── */}
      {bench.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ type: "spring", stiffness: 220, damping: 26, delay: 0.2 }}
          className="glass"
          style={{ borderRadius: 14, padding: "14px 16px 12px" }}
        >
          <p style={{
            fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 600,
            color: "var(--text-3)", letterSpacing: "0.12em", textTransform: "uppercase",
            marginBottom: 8,
          }}>
            Bench
          </p>
          <div style={{ display: "flex", gap: 6 }}>
            {bench.map((p) => (
              <div
                key={p.player_id}
                style={{
                  flex: 1, padding: "8px 10px",
                  background: "rgba(255,255,255,0.02)", border: "1px solid var(--divider)",
                  borderRadius: 10, textAlign: "center",
                }}
              >
                {p.team_code && (
                  <img
                    src={`https://resources.premierleague.com/premierleague/badges/25/t${p.team_code}.png`}
                    alt="" width={14} height={14} style={{ objectFit: "contain", opacity: 0.7, marginBottom: 4 }}
                    onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                  />
                )}
                <div style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-3)", marginBottom: 4, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.web_name}</div>
                <div style={{ fontFamily: "var(--font-data)", fontSize: 14, fontWeight: 600, color: "var(--text-2)", letterSpacing: "-0.02em" }}>{p.live_points}</div>
              </div>
            ))}
          </div>
        </motion.div>
      )}
    </div>
  );
}
