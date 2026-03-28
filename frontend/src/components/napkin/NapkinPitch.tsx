"use client";
import { motion } from "framer-motion";
import PlayerMarker from "./PlayerMarker";
import type { SquadPick } from "@/types/fpl";
import { useFPLStore } from "@/store/fpl.store";

interface NapkinPitchProps {
  picks: SquadPick[];
  livePoints?: Record<number, number>;
  large?: boolean;
  isLiveGw?: boolean;
}

function groupByRole(picks: SquadPick[]) {
  const starters = picks.filter((p) => p.position <= 11).sort((a, b) => a.position - b.position);
  const bench    = picks.filter((p) => p.position > 11).sort((a, b) => a.position - b.position);
  return {
    gk:    starters.filter((p) => p.element_type === 1),
    def:   starters.filter((p) => p.element_type === 2),
    mid:   starters.filter((p) => p.element_type === 3),
    fwd:   starters.filter((p) => p.element_type === 4),
    bench,
  };
}

function PitchRow({
  players,
  livePoints,
  startIndex,
  large,
  isLiveGw,
}: {
  players: SquadPick[];
  livePoints?: Record<number, number>;
  startIndex: number;
  large?: boolean;
  isLiveGw?: boolean;
}) {
  const { selectedPlayerId, setSelectedPlayer } = useFPLStore();
  return (
    <div style={{ display: "flex", justifyContent: "center", alignItems: "center", gap: large ? 16 : 12, flexWrap: "wrap" }}>
      {players.map((pick, i) => (
        <PlayerMarker
          key={pick.player_id}
          pick={pick}
          index={startIndex + i}
          livePoints={livePoints?.[pick.player_id]}
          onSelect={setSelectedPlayer}
          isSelected={selectedPlayerId === pick.player_id}
          large={large}
          isLiveGw={isLiveGw}
        />
      ))}
    </div>
  );
}

function BenchRow({ bench, livePoints, large, isLiveGw }: { bench: SquadPick[]; livePoints?: Record<number, number>; large?: boolean; isLiveGw?: boolean }) {
  const { selectedPlayerId, setSelectedPlayer } = useFPLStore();
  return (
    <div style={{ display: "flex", gap: large ? 14 : 10, justifyContent: "center", alignItems: "center" }}>
      {bench.map((pick, i) => (
        <PlayerMarker
          key={pick.player_id}
          pick={pick}
          index={11 + i}
          isBench
          livePoints={livePoints?.[pick.player_id]}
          onSelect={setSelectedPlayer}
          isSelected={selectedPlayerId === pick.player_id}
          large={large}
          isLiveGw={isLiveGw}
        />
      ))}
    </div>
  );
}

export default function NapkinPitch({ picks, livePoints, large, isLiveGw }: NapkinPitchProps) {
  const { gk, def, mid, fwd, bench } = groupByRole(picks);
  const { squad, freeTransfers, bankMillions, selectedPlayerId, setSelectedPlayer } = useFPLStore();

  const ft      = freeTransfers ?? squad?.free_transfers ?? 0;
  const bankM   = bankMillions ?? (squad ? squad.bank / 10 : 0);

  const ftColor =
    ft >= 3 ? "var(--green)"   :
    ft === 2 ? "var(--amber)"   :
               "var(--text-3)";

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 220, damping: 26 }}
      style={{ width: "100%" }}
    >
      {/* Pitch wrapper */}
      <div
        style={{
          background: "var(--surface)",
          border: "1px solid var(--divider)",
          borderRadius: 16,
          overflow: "hidden",
        }}
      >
        {/* ── Header ─────────────────────────────────────────────── */}
        <div
          style={{
            padding: "14px 18px 12px",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            borderBottom: "1px solid var(--divider)",
          }}
        >
          <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
            <span
              style={{
                fontFamily: "var(--font-display)",
                fontSize: 20,
                fontWeight: 600,
                color: "var(--text-1)",
                letterSpacing: "-0.03em",
              }}
            >
              GW{squad?.gameweek ?? "—"}
            </span>
            {squad?.team_name && (
              <span
                style={{
                  fontFamily: "var(--font-ui)",
                  fontSize: 12,
                  color: "var(--text-3)",
                  letterSpacing: "0.01em",
                }}
              >
                {squad.team_name}
              </span>
            )}
          </div>

          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            {squad?.total_points != null && (
              <span className="badge badge-muted" style={{ fontFamily: "var(--font-data)", fontSize: 11 }}>
                {squad.total_points} pts
              </span>
            )}
            <span
              className="badge"
              style={{
                fontSize: 11,
                color: ftColor,
                background: ft >= 2 ? "rgba(34,197,94,0.08)" : "rgba(255,255,255,0.04)",
                border: `1px solid ${ft >= 2 ? "rgba(34,197,94,0.25)" : "var(--divider)"}`,
                fontFamily: "var(--font-data)",
              }}
            >
              {ft} FT
            </span>
            <span className="badge badge-muted" style={{ fontFamily: "var(--font-data)", fontSize: 11 }}>
              £{bankM.toFixed(1)}m
            </span>
          </div>
        </div>

        {/* ── CSS 3D Pitch — no vector, pure CSS background ─────── */}
        <div
          className="pitch-3d-wrap"
          style={{ margin: "0", borderRadius: 0, position: "relative" }}
          onClick={() => { if (selectedPlayerId != null) setSelectedPlayer(null); }}
        >
          <div className="pitch-ambient-glow" />

          <div className={`pitch-3d-inner${selectedPlayerId != null ? " focused" : ""}`}>
            {/* Pure CSS pitch — no SVG vectors */}
            <div
              style={{
                position: "absolute",
                inset: 0,
                background: "var(--pitch-bg)",
                overflow: "hidden",
              }}
            >
              {/* Alternating mow stripes */}
              {Array.from({ length: 10 }, (_, i) => (
                <div
                  key={i}
                  style={{
                    position: "absolute",
                    left: 0,
                    right: 0,
                    top: `${i * 10}%`,
                    height: "10%",
                    background: i % 2 === 0 ? "rgba(255,255,255,0.025)" : "transparent",
                  }}
                />
              ))}
              {/* Center line */}
              <div style={{ position: "absolute", left: "8%", right: "8%", top: "50%", height: 1, background: "var(--pitch-line)", transform: "translateY(-0.5px)" }} />
              {/* Center circle */}
              <div style={{ position: "absolute", left: "50%", top: "50%", width: 80, height: 80, borderRadius: "50%", border: `1px solid var(--pitch-line)`, transform: "translate(-50%, -50%)" }} />
              {/* Top penalty box */}
              <div style={{ position: "absolute", left: "25%", right: "25%", top: "8%", height: "16%", border: `1px solid var(--pitch-line)`, borderBottom: "none" }} />
              {/* Bottom penalty box */}
              <div style={{ position: "absolute", left: "25%", right: "25%", bottom: "8%", height: "16%", border: `1px solid var(--pitch-line)`, borderTop: "none" }} />
              {/* Outer border */}
              <div style={{ position: "absolute", inset: "8%", border: `1px solid var(--pitch-line)` }} />
            </div>

            {/* Player rows — FWD at top, GK at bottom */}
            <div
              style={{
                position: "relative",
                zIndex: 10,
                display: "flex",
                flexDirection: "column",
                justifyContent: "space-around",
                padding: large ? "36px 16px 28px" : "28px 12px 22px",
                minHeight: large ? 660 : 560,
                gap: large ? 14 : 10,
              }}
            >
              <PitchRow players={fwd} livePoints={livePoints} startIndex={0} large={large} isLiveGw={isLiveGw} />
              <PitchRow players={mid} livePoints={livePoints} startIndex={fwd.length} large={large} isLiveGw={isLiveGw} />
              <PitchRow players={def} livePoints={livePoints} startIndex={fwd.length + mid.length} large={large} isLiveGw={isLiveGw} />
              <PitchRow players={gk}  livePoints={livePoints} startIndex={fwd.length + mid.length + def.length} large={large} isLiveGw={isLiveGw} />
            </div>
          </div>
        </div>

        {/* ── Bench ───────────────────────────────────────────────── */}
        <div
          style={{
            padding: "12px 16px 16px",
            borderTop: "1px dashed rgba(255,255,255,0.08)",
            background: "rgba(255,255,255,0.01)",
          }}
        >
          <p
            style={{
              fontFamily: "var(--font-ui)",
              fontSize: 9,
              fontWeight: 600,
              color: "var(--text-3)",
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              marginBottom: 10,
            }}
          >
            bench
          </p>
          <BenchRow bench={bench} livePoints={livePoints} large={large} isLiveGw={isLiveGw} />
        </div>
      </div>

      {/* ── Position legend ─────────────────────────────────────── */}
      <div
        style={{
          marginTop: 10,
          display: "flex",
          gap: 14,
          justifyContent: "center",
          fontFamily: "var(--font-ui)",
          fontSize: 10,
          color: "var(--text-3)",
          letterSpacing: "0.04em",
        }}
      >
        {[
          ["GK",  "var(--amber)"],
          ["DEF", "var(--green)"],
          ["MID", "rgba(255,255,255,0.5)"],
          ["FWD", "var(--red)"],
        ].map(([label, color]) => (
          <span key={label} style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: "50%",
                background: color,
                display: "inline-block",
                boxShadow: `0 0 6px ${color}`,
              }}
            />
            {label}
          </span>
        ))}
      </div>
    </motion.div>
  );
}
