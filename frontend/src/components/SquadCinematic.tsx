"use client";
import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import type { SquadPick } from "@/types/fpl";

interface SquadCinematicProps {
  squad: SquadPick[];
  teamName?: string | null;
  totalPoints?: number | null;
  onDismiss: () => void;
}

export default function SquadCinematic({
  squad,
  teamName,
  totalPoints,
  onDismiss,
}: SquadCinematicProps) {
  const [phase, setPhase] = useState<"enter" | "hold" | "exit">("enter");

  const captain = squad.find((p) => p.is_captain);
  const topXpts = [...squad]
    .filter((p) => p.position <= 11)
    .sort((a, b) => (b.predicted_xpts_next ?? 0) - (a.predicted_xpts_next ?? 0))[0];

  const hero = captain ?? topXpts ?? squad[0];
  const xpts = hero?.predicted_xpts_next;

  useEffect(() => {
    const t1 = setTimeout(() => setPhase("hold"), 400);
    const t2 = setTimeout(() => setPhase("exit"), 3400);
    const t3 = setTimeout(onDismiss, 4000);
    return () => { clearTimeout(t1); clearTimeout(t2); clearTimeout(t3); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <AnimatePresence>
      {phase !== "exit" && (
        <motion.div
          key="cinematic"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.45 }}
          onClick={onDismiss}
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 9999,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            cursor: "pointer",
            overflow: "hidden",
            background: "rgba(0,0,0,0.92)",
          }}
        >
          {/* Broadcast green radial glow */}
          <div style={{
            position: "absolute", inset: 0, pointerEvents: "none",
            background: "radial-gradient(ellipse 70% 60% at 50% 50%, rgba(34,197,94,0.18) 0%, transparent 70%)",
          }} />

          {/* Scan lines overlay */}
          <div style={{
            position: "absolute", inset: 0, pointerEvents: "none", opacity: 0.04,
            backgroundImage: "repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(255,255,255,1) 2px, rgba(255,255,255,1) 4px)",
          }} />

          {/* Corner brackets — broadcast style */}
          {[
            { top: 32, left: 32, borderTop: "2px solid rgba(34,197,94,0.6)", borderLeft: "2px solid rgba(34,197,94,0.6)" },
            { top: 32, right: 32, borderTop: "2px solid rgba(34,197,94,0.6)", borderRight: "2px solid rgba(34,197,94,0.6)" },
            { bottom: 32, left: 32, borderBottom: "2px solid rgba(34,197,94,0.6)", borderLeft: "2px solid rgba(34,197,94,0.6)" },
            { bottom: 32, right: 32, borderBottom: "2px solid rgba(34,197,94,0.6)", borderRight: "2px solid rgba(34,197,94,0.6)" },
          ].map((s, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, scale: 1.3 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: 0.15 + i * 0.05, duration: 0.4 }}
              style={{ position: "absolute", width: 28, height: 28, ...s }}
            />
          ))}

          {/* Content */}
          <div style={{
            position: "relative", zIndex: 1,
            display: "flex", flexDirection: "column", alignItems: "center", gap: 0,
            textAlign: "center", padding: "0 24px",
          }}>
            {/* Kicker */}
            <motion.p
              initial={{ opacity: 0, y: -12 }}
              animate={{ opacity: phase === "hold" ? 1 : 0, y: phase === "hold" ? 0 : -12 }}
              transition={{ duration: 0.5 }}
              style={{
                fontFamily: "var(--font-ui)", fontSize: 10, fontWeight: 700,
                color: "var(--green)", letterSpacing: "0.24em",
                textTransform: "uppercase", marginBottom: 20,
              }}
            >
              {teamName ?? "Your Squad"} · Squad Loaded
            </motion.p>

            {/* Ball */}
            <motion.div
              initial={{ scale: 0, rotate: -180 }}
              animate={{ scale: 1, rotate: 0 }}
              transition={{ type: "spring", stiffness: 280, damping: 18, delay: 0.1 }}
              style={{ fontSize: 72, lineHeight: 1, marginBottom: 20, filter: "drop-shadow(0 0 32px rgba(34,197,94,0.6))" }}
            >
              ⚽
            </motion.div>

            {/* Captain tag */}
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: phase === "hold" ? 0.55 : 0 }}
              transition={{ duration: 0.4, delay: 0.2 }}
              style={{
                fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 700,
                color: "var(--amber)", letterSpacing: "0.18em",
                textTransform: "uppercase", marginBottom: 8,
              }}
            >
              {captain ? "Your Captain" : "Top Pick"}
            </motion.div>

            {/* Player name — huge display */}
            <motion.h1
              initial={{ opacity: 0, scale: 0.7, y: 20 }}
              animate={{ opacity: phase === "hold" ? 1 : 0, scale: phase === "hold" ? 1 : 0.7, y: phase === "hold" ? 0 : 20 }}
              transition={{ type: "spring", stiffness: 260, damping: 20, delay: 0.18 }}
              style={{
                fontFamily: "var(--font-display)",
                fontSize: "clamp(48px, 12vw, 96px)",
                fontWeight: 700,
                color: "var(--text-1)",
                letterSpacing: "-0.04em",
                lineHeight: 0.92,
                margin: 0,
                marginBottom: 18,
              }}
            >
              {hero?.web_name ?? "Squad"}
            </motion.h1>

            {/* xPts */}
            {xpts != null && (
              <motion.div
                initial={{ opacity: 0, x: -24 }}
                animate={{ opacity: phase === "hold" ? 1 : 0, x: phase === "hold" ? 0 : -24 }}
                transition={{ duration: 0.5, delay: 0.32 }}
                style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 14 }}
              >
                <span style={{
                  fontFamily: "var(--font-data)", fontSize: 48, fontWeight: 700,
                  color: "var(--green)", letterSpacing: "-0.04em", lineHeight: 1,
                }}>
                  {xpts.toFixed(1)}
                </span>
                <span style={{
                  fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-3)",
                  letterSpacing: "0.1em", textTransform: "uppercase",
                }}>
                  xPts
                </span>
              </motion.div>
            )}

            {/* Points pill */}
            {totalPoints != null && (
              <motion.div
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: phase === "hold" ? 0.7 : 0, y: phase === "hold" ? 0 : 12 }}
                transition={{ duration: 0.4, delay: 0.42 }}
                style={{
                  fontFamily: "var(--font-data)", fontSize: 13, fontWeight: 600,
                  color: "var(--text-3)", letterSpacing: "-0.02em",
                }}
              >
                {totalPoints} pts overall
              </motion.div>
            )}

            {/* Team badge */}
            {hero?.team_code && (
              <motion.img
                src={`https://resources.premierleague.com/premierleague/badges/25/t${hero.team_code}.png`}
                alt=""
                initial={{ opacity: 0 }}
                animate={{ opacity: phase === "hold" ? 0.35 : 0 }}
                transition={{ duration: 0.5, delay: 0.5 }}
                style={{ width: 36, height: 36, objectFit: "contain", marginTop: 18 }}
                onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
              />
            )}
          </div>

          {/* Dismiss hint */}
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: phase === "hold" ? 0.3 : 0 }}
            transition={{ delay: 1.2, duration: 0.4 }}
            style={{
              position: "absolute", bottom: 24,
              fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-3)",
              letterSpacing: "0.1em", textTransform: "uppercase",
            }}
          >
            tap to continue
          </motion.p>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
