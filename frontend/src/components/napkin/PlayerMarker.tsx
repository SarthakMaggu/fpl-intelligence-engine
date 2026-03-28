"use client";
import { useRef, useState, useCallback, useEffect } from "react";
import { createPortal } from "react-dom";
import { motion, AnimatePresence } from "framer-motion";
import { formatCost } from "@/lib/fdr";
import type { SquadPick } from "@/types/fpl";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface PlayerHistory {
  avg_minutes_last5: number;
  starts_last5: number;
  rotation_risk: "LOW" | "MEDIUM" | "HIGH" | "UNKNOWN";
  manager_note: string | null;
  gw_history: { gw: number; minutes: number; points: number }[];
}

const ROTATION_COLOR: Record<string, string> = {
  LOW:     "var(--green)",
  MEDIUM:  "var(--amber)",
  HIGH:    "var(--red)",
  UNKNOWN: "var(--text-3)",
};

const POS_CONFIG: Record<number, {
  ringClass: string;
  glowColor: string;
  gradientFrom: string;
  gradientTo: string;
  label: string;
}> = {
  1: {
    ringClass: "prediction-ring prediction-ring-amber",
    glowColor: "rgba(245,158,11,0.60)",
    gradientFrom: "rgba(245,158,11,0.28)",
    gradientTo: "rgba(245,158,11,0.08)",
    label: "GK",
  },
  2: {
    ringClass: "prediction-ring prediction-ring-green",
    glowColor: "rgba(34,197,94,0.55)",
    gradientFrom: "rgba(34,197,94,0.25)",
    gradientTo: "rgba(34,197,94,0.06)",
    label: "DEF",
  },
  3: {
    ringClass: "prediction-ring prediction-ring-white",
    glowColor: "rgba(255,255,255,0.28)",
    gradientFrom: "rgba(255,255,255,0.16)",
    gradientTo: "rgba(255,255,255,0.04)",
    label: "MID",
  },
  4: {
    ringClass: "prediction-ring prediction-ring-red",
    glowColor: "rgba(239,68,68,0.55)",
    gradientFrom: "rgba(239,68,68,0.25)",
    gradientTo: "rgba(239,68,68,0.06)",
    label: "FWD",
  },
};

interface PlayerMarkerProps {
  pick: SquadPick;
  index: number;
  isBench?: boolean;
  livePoints?: number;
  onSelect?: (id: number | null) => void;
  isSelected?: boolean;
  large?: boolean;
  /** True when the current GW is underway (deadline passed, not finished).
   *  In this state, status='s'/'u' means suspended for the NEXT GW (not this one),
   *  so we don't dim or label the player as SUSP on the live pitch. */
  isLiveGw?: boolean;
}

const POPUP_W = 228;
const POPUP_H = 350;

export default function PlayerMarker({
  pick,
  index,
  isBench = false,
  livePoints,
  onSelect,
  isSelected,
  large = false,
  isLiveGw = false,
}: PlayerMarkerProps) {
  const pos     = POS_CONFIG[pick.element_type] ?? POS_CONFIG[3];
  const nodeSize = isBench ? (large ? 46 : 38) : (large ? 76 : 62);
  const injured    = pick.status === "i" || pick.status === "d";
  const suspended  = pick.status === "s" || pick.status === "u";
  // During a live GW, status='s'/'u' = suspended for the NEXT game (not this one).
  // Maguire got a red card in GW31 → he played GW31, suspended for GW32.
  // Don't dim or label SUSP while GW31 is live — his GW31 prediction stands.
  const suspendedForDisplay = suspended && !isLiveGw;
  const opacity    = pick.has_blank_gw || suspendedForDisplay ? 0.45 : isBench ? 0.65 : 1;

  const xptsNum   = pick.predicted_xpts_next ?? 0;
  const xptsValue = suspendedForDisplay
    ? "SUSP"
    : pick.predicted_xpts_next != null
      ? pick.predicted_xpts_next.toFixed(1)
      : "—";

  const xptsColor =
    isBench                      ? "var(--text-3)" :
    pick.has_blank_gw            ? "var(--text-3)" :
    suspendedForDisplay          ? "var(--text-3)" :
    xptsNum >= 6.0               ? "var(--green)"  :
    xptsNum >= 4.0               ? "var(--amber)"  :
                                   "var(--text-2)";

  const nodeRef = useRef<HTMLDivElement>(null);
  // popupAnchor is viewport coords — calculated on click, used by the portal popup
  const [popupAnchor, setPopupAnchor] = useState<{ top: number; left: number } | null>(null);
  const [history, setHistory] = useState<PlayerHistory | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [isMounted, setIsMounted] = useState(false);

  useEffect(() => { setIsMounted(true); }, []);

  // Fetch element-summary history when player is selected
  useEffect(() => {
    if (!isSelected || !pick.player_id) return;
    setHistoryLoading(true);
    fetch(`${API}/api/players/${pick.player_id}/history`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => d && setHistory(d))
      .catch(() => {})
      .finally(() => setHistoryLoading(false));
  }, [isSelected, pick.player_id]);

  // When deselected externally, clear anchor so old position doesn't persist
  useEffect(() => {
    if (!isSelected) setPopupAnchor(null);
  }, [isSelected]);

  const handleClick = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    if (!isSelected && nodeRef.current) {
      // Get the node's bounding box in viewport coordinates
      // NOTE: getBoundingClientRect() works correctly even under CSS transforms
      const rect = nodeRef.current.getBoundingClientRect();
      const vw = window.innerWidth;
      const vh = window.innerHeight;

      // Vertical: prefer above node, fall back below
      let top: number;
      const spaceAbove = rect.top;
      if (spaceAbove >= POPUP_H + 12) {
        top = rect.top - POPUP_H - 8;
      } else {
        top = rect.bottom + 8;
        if (top + POPUP_H > vh - 10) top = vh - POPUP_H - 10;
      }
      // Clamp top to always be on-screen
      if (top < 8) top = 8;

      // Horizontal: center on node, clamp to viewport
      let left = rect.left + rect.width / 2 - POPUP_W / 2;
      if (left < 8) left = 8;
      if (left + POPUP_W > vw - 8) left = vw - POPUP_W - 8;

      setPopupAnchor({ top, left });
    } else if (isSelected) {
      setPopupAnchor(null);
    }
    onSelect?.(isSelected ? null : pick.player_id);
  }, [isSelected, onSelect, pick.player_id]);

  // Popup content — rendered via portal to escape CSS transform stacking context
  const popup = isMounted && isSelected && popupAnchor && createPortal(
    <AnimatePresence>
      <motion.div
        key={`popup-${pick.player_id}`}
        initial={{ opacity: 0, y: 8, scale: 0.92 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 4, scale: 0.96 }}
        transition={{ type: "spring", stiffness: 420, damping: 28 }}
        className="insight-card"
        style={{
          position: "fixed",
          top: popupAnchor.top,
          left: popupAnchor.left,
          width: POPUP_W,
          zIndex: 99999,
          padding: "14px 14px 12px",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Top accent line */}
        <div style={{
          position: "absolute",
          top: 0,
          left: 20,
          right: 20,
          height: 1,
          background: `linear-gradient(90deg, transparent, ${pos.glowColor} 50%, transparent)`,
        }} />

        {/* Header row: name + team badge */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
          <div style={{ fontFamily: "var(--font-display)", fontSize: 16, fontWeight: 600, color: "var(--text-1)", letterSpacing: "-0.03em", lineHeight: 1.1 }}>
            {pick.web_name}
          </div>
          {pick.team_code && (
            <img
              src={`https://resources.premierleague.com/premierleague/badges/25/t${pick.team_code}.png`}
              alt={pick.team_short_name ?? ""}
              width={22} height={22}
              style={{ objectFit: "contain", opacity: 0.8 }}
              onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
            />
          )}
        </div>

        {/* xPts + FDR */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: 10 }}>
          <div>
            <div style={{ fontFamily: "var(--font-data)", fontSize: 32, fontWeight: 600, color: xptsColor, letterSpacing: "-0.04em", lineHeight: 1 }}>
              {xptsValue}
            </div>
            <div style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)", letterSpacing: "0.1em", textTransform: "uppercase", marginTop: 3 }}>
              xPts next GW
            </div>
          </div>

          {pick.fdr_next != null && (() => {
            // fdr_next = 0 means blank GW (no fixture this gameweek)
            if (pick.fdr_next === 0) {
              return (
                <div style={{ textAlign: "center" }}>
                  <div style={{ display: "inline-flex", alignItems: "center", padding: "4px 9px", borderRadius: 7, background: "rgba(255,255,255,0.04)", color: "var(--text-3)", fontFamily: "var(--font-ui)", fontSize: 11, fontWeight: 600, letterSpacing: "0.06em" }}>
                    BGW
                  </div>
                  <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--text-3)", letterSpacing: "0.06em", marginTop: 2 }}>NO FIXTURE</div>
                </div>
              );
            }
            const fdrColors: Record<number, { bg: string; color: string }> = {
              1: { bg: "rgba(34,197,94,0.20)",   color: "var(--green)" },
              2: { bg: "rgba(34,197,94,0.12)",   color: "var(--green)" },
              3: { bg: "rgba(255,255,255,0.08)", color: "var(--text-2)" },
              4: { bg: "rgba(245,158,11,0.15)",  color: "var(--amber)" },
              5: { bg: "rgba(239,68,68,0.18)",   color: "var(--red)"   },
            };
            const fc = fdrColors[pick.fdr_next] ?? fdrColors[3];
            return (
              <div style={{ textAlign: "center" }}>
                <div style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "4px 9px", borderRadius: 7, background: fc.bg, color: fc.color, fontFamily: "var(--font-data)", fontSize: 16, fontWeight: 700, letterSpacing: "-0.02em" }}>
                  {pick.fdr_next}
                  <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, opacity: 0.8, fontWeight: 600 }}>
                    {pick.is_home_next != null ? (pick.is_home_next ? "H" : "A") : ""}
                  </span>
                </div>
                <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--text-3)", letterSpacing: "0.06em", marginTop: 2 }}>FDR</div>
              </div>
            );
          })()}
        </div>

        {/* Form sparkline + price */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 3 }}>
            {(() => {
              const trend   = pick.form_trend;
              const heights = trend === "rising"  ? [5, 7, 10] : trend === "falling" ? [10, 7, 5] : [7, 7, 7];
              const color   = trend === "rising"  ? "var(--green)" : trend === "falling" ? "var(--red)" : "var(--text-3)";
              const arrow   = trend === "rising"  ? "↑" : trend === "falling" ? "↓" : "→";
              return (
                <>
                  {heights.map((h, i) => (
                    <div key={i} style={{ width: 4, height: h, borderRadius: 2, background: color, opacity: trend ? (0.5 + i * 0.2) : 0.3 }} />
                  ))}
                  <span style={{ fontFamily: "var(--font-ui)", fontSize: 10, color, marginLeft: 3, lineHeight: 1 }}>
                    {trend ? arrow : "—"}
                  </span>
                </>
              );
            })()}
          </div>
          <span style={{ fontFamily: "var(--font-data)", fontSize: 12, fontWeight: 600, color: "var(--text-2)", letterSpacing: "-0.02em" }}>
            {formatCost(pick.now_cost)}
          </span>
        </div>

        {/* Divider */}
        <div style={{ height: 1, background: "var(--divider)", marginBottom: 8 }} />

        {/* Minutes + Rotation Risk */}
        {historyLoading && (
          <div style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)", marginBottom: 8 }}>Loading minutes…</div>
        )}
        {history && !historyLoading && (
          <div style={{ marginBottom: 8 }}>
            <div style={{ display: "flex", alignItems: "flex-end", gap: 3, marginBottom: 5 }}>
              {(history.gw_history.slice(-5)).map((g, i) => {
                const pct = Math.min(g.minutes / 90, 1);
                const barColor = pct >= 0.88 ? "var(--green)" : pct >= 0.45 ? "var(--amber)" : "var(--red)";
                return (
                  <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }}>
                    <div style={{ width: 7, height: Math.max(pct * 28, 2), borderRadius: 2, background: barColor, opacity: 0.85 }} />
                    <span style={{ fontFamily: "var(--font-data)", fontSize: 7, color: "var(--text-3)" }}>{g.gw}</span>
                  </div>
                );
              })}
              <div style={{ marginLeft: 4, display: "flex", flexDirection: "column", gap: 1 }}>
                <span style={{ fontFamily: "var(--font-data)", fontSize: 11, fontWeight: 700, color: "var(--text-1)" }}>
                  {history.avg_minutes_last5}<span style={{ fontSize: 8, color: "var(--text-3)", marginLeft: 2 }}>avg min</span>
                </span>
                <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)" }}>{history.starts_last5}/5 starts</span>
              </div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <span style={{
                fontFamily: "var(--font-ui)", fontSize: 8, fontWeight: 700,
                color: ROTATION_COLOR[history.rotation_risk],
                background: `${ROTATION_COLOR[history.rotation_risk]}18`,
                border: `1px solid ${ROTATION_COLOR[history.rotation_risk]}33`,
                borderRadius: 999, padding: "1px 6px", letterSpacing: "0.06em",
              }}>
                {history.rotation_risk} ROTATION RISK
              </span>
            </div>
            {history.manager_note && (
              <div style={{ marginTop: 5, fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)", lineHeight: 1.4, fontStyle: "italic" }}>
                {history.manager_note}
              </div>
            )}
          </div>
        )}

        {/* Status badges */}
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
          {pick.has_double_gw && <span className="badge badge-amber" style={{ fontSize: 8 }}>DGW</span>}
          {pick.has_blank_gw && <span className="badge badge-muted" style={{ fontSize: 8 }}>blank</span>}
          {injured && (
            <span className="badge badge-neg" style={{ fontSize: 8 }}>
              {pick.status === "i" ? "injured" : "doubt"}
            </span>
          )}
          {suspended && (
            <span className="badge badge-neg" style={{ fontSize: 8 }}>
              {isLiveGw ? "susp next GW" : "suspended"}
            </span>
          )}
          {pick.suspension_risk && !suspended && <span className="badge badge-amber" style={{ fontSize: 8 }}>⚠ susp risk</span>}
          {pick.points_per_game != null && (
            <span className="badge badge-muted" style={{ fontSize: 8 }}>{Number(pick.points_per_game).toFixed(1)} ppg</span>
          )}
        </div>

        {pick.news && (
          <div style={{ marginTop: 8, paddingTop: 8, borderTop: "1px solid var(--divider)", fontSize: 10, color: "var(--text-3)", lineHeight: 1.45, fontFamily: "var(--font-ui)" }}>
            {pick.news.slice(0, 72)}
          </div>
        )}
      </motion.div>
    </AnimatePresence>,
    document.body
  );

  return (
    <>
      {popup}
      <motion.div
        ref={nodeRef}
        custom={index}
        initial={{ opacity: 0, scale: 0.6 }}
        animate={{ opacity, scale: 1 }}
        transition={{
          delay: index * 0.032,
          type: "spring",
          stiffness: 360,
          damping: 22,
        }}
        whileHover={{ scale: 1.11, y: -3, transition: { type: "spring", stiffness: 500, damping: 20 } }}
        whileTap={{ scale: 0.94 }}
        className="relative flex flex-col items-center cursor-pointer select-none"
        style={{ width: nodeSize + 16 }}
        onClick={handleClick}
      >
        {/* Captain / VC badge */}
        {(pick.is_captain || pick.is_vice_captain) && (
          <div
            className={pick.is_captain ? "captain-pulse" : undefined}
            style={{
              position: "absolute",
              top: -6,
              right: -2,
              width: 22,
              height: 22,
              borderRadius: "50%",
              background: pick.is_captain ? "var(--amber)" : "rgba(255,255,255,0.25)",
              border: "2px solid rgba(255,255,255,0.95)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 11,
              fontWeight: 700,
              color: pick.is_captain ? "#000" : "var(--text-1)",
              fontFamily: "var(--font-display)",
              letterSpacing: "0.02em",
              zIndex: 20,
              boxShadow: pick.is_captain
                ? "0 0 18px rgba(245,158,11,0.85), 0 0 6px rgba(245,158,11,0.5)"
                : "0 2px 8px rgba(0,0,0,0.6)",
            }}
          >
            {pick.is_captain ? "C" : "V"}
          </div>
        )}

        {/* Live points badge */}
        {livePoints !== undefined && (
          <motion.div
            key={livePoints}
            initial={{ scale: 1.5, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ type: "spring", stiffness: 500 }}
            style={{
              position: "absolute",
              top: -4,
              left: 0,
              width: 16,
              height: 16,
              borderRadius: "50%",
              background: livePoints > 0 ? "var(--green)" : "rgba(255,255,255,0.1)",
              border: "1.5px solid rgba(255,255,255,0.7)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 8,
              fontWeight: 700,
              color: livePoints > 0 ? "#000" : "var(--text-3)",
              fontFamily: "var(--font-data)",
              zIndex: 20,
            }}
          >
            {livePoints}
          </motion.div>
        )}

        {/* DGW pulse dot */}
        {pick.has_double_gw && (
          <div style={{ position: "absolute", top: 2, left: 3, width: 6, height: 6, borderRadius: "50%", background: "var(--amber)", boxShadow: "0 0 8px var(--amber)", zIndex: 20 }} />
        )}

        {/* Player node */}
        <div
          className="player-node"
          style={{
            width: nodeSize,
            height: nodeSize,
            background: pick.has_blank_gw
              ? "rgba(255,255,255,0.04)"
              : `radial-gradient(circle at 40% 35%, ${pos.gradientFrom}, ${pos.gradientTo})`,
            border: `1.5px solid ${
              isSelected
                ? "rgba(255,255,255,0.7)"
                : injured
                ? "rgba(239,68,68,0.6)"
                : pick.has_blank_gw
                ? "rgba(255,255,255,0.08)"
                : `${pos.glowColor}`
            }`,
            boxShadow: isSelected
              ? `0 0 0 3px rgba(255,255,255,0.35), 0 0 44px ${pos.glowColor}`
              : injured
              ? "0 0 24px rgba(239,68,68,0.55)"
              : `0 0 32px ${pos.glowColor}`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            transition: "border-color 180ms, box-shadow 180ms",
            overflow: "hidden",
          }}
        >
          {!isBench && !pick.has_blank_gw && (
            <span className={pos.ringClass} style={{ width: nodeSize + 12, height: nodeSize + 12 }} />
          )}
          {injured && (
            <svg style={{ position: "absolute", inset: 0, width: "100%", height: "100%", opacity: 0.6 }} viewBox="0 0 40 40">
              <line x1="13" y1="13" x2="27" y2="27" stroke="var(--red)" strokeWidth="2" strokeLinecap="round" />
              <line x1="27" y1="13" x2="13" y2="27" stroke="var(--red)" strokeWidth="2" strokeLinecap="round" />
            </svg>
          )}
          {pick.team_code && !isBench && (
            <img
              src={`https://resources.premierleague.com/premierleague/badges/25/t${pick.team_code}.png`}
              alt={pick.team_short_name ?? ""}
              width={24} height={24}
              style={{ position: "absolute", bottom: 6, right: 6, objectFit: "contain", opacity: 0.75, zIndex: 2, flexShrink: 0 }}
              onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
            />
          )}
          <span style={{
            fontFamily: "var(--font-ui)",
            fontSize: isBench ? 9 : 11,
            fontWeight: 600,
            color: pick.has_blank_gw ? "var(--text-3)" : "var(--text-1)",
            textAlign: "center",
            lineHeight: 1.1,
            maxWidth: nodeSize - 6,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
            display: "block",
            padding: "0 4px",
            position: "relative",
            zIndex: 1,
            letterSpacing: "-0.02em",
          }}>
            {pick.web_name}
          </span>
        </div>

        {/* xPts label */}
        <div style={{
          fontFamily: suspendedForDisplay ? "var(--font-ui)" : "var(--font-data)",
          fontSize: isBench ? 9 : suspendedForDisplay ? 10 : 13,
          fontWeight: suspendedForDisplay ? 600 : 700,
          color: xptsColor,
          marginTop: 5,
          textAlign: "center",
          letterSpacing: suspendedForDisplay ? "0.04em" : "-0.03em",
        }}>
          {xptsValue}
        </div>
      </motion.div>
    </>
  );
}
