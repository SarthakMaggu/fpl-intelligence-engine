"use client";
import React, { useState } from "react";
import { motion } from "framer-motion";
import { ArrowLeftRight, Shield, Zap, TrendingUp } from "lucide-react";
import type { PriorityAction, PriorityActions, ActionType, ActionUrgency } from "@/types/fpl";

// ── Colors per action type ─────────────────────────────────────────────────
const TYPE_COLOR: Record<ActionType | string, string> = {
  captain:    "var(--amber)",
  transfer:   "var(--green)",
  injury:     "var(--red)",
  chip:       "var(--blue)",
  double_gw:  "var(--amber)",
  bench_swap: "var(--green)",
};

const TYPE_ICON: Partial<Record<ActionType | string, React.ElementType>> = {
  transfer:   ArrowLeftRight,
  injury:     Shield,
  chip:       Zap,
  double_gw:  TrendingUp,
  bench_swap: ArrowLeftRight,
};

const URGENCY_LABEL: Record<ActionUrgency, string> = {
  HIGH:   "MUST DO",
  MEDIUM: "CONSIDER",
  LOW:    "OPTIONAL",
};

const URGENCY_COLOR: Record<ActionUrgency, string> = {
  HIGH:   "var(--red)",
  MEDIUM: "var(--amber)",
  LOW:    "var(--text-3)",
};

// ── Team badge — small club crest ─────────────────────────────────────────
function TeamBadge({ code, size = 14 }: { code: number; size?: number }) {
  return (
    <img
      src={`https://resources.premierleague.com/premierleague/badges/25/t${code}.png`}
      alt=""
      width={size} height={size}
      style={{ objectFit: "contain", flexShrink: 0 }}
      onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
    />
  );
}

// ── Single action card — READ ONLY ─────────────────────────────────────────
function ActionCard({
  action,
  isBest,
}: {
  action: PriorityAction;
  isBest?: boolean;
}) {
  const color = TYPE_COLOR[action.type] || "var(--text-2)";
  const Icon = TYPE_ICON[action.type] ?? null;
  const isTransfer = action.type === "transfer" || action.type === "bench_swap";

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: -6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 300, damping: 28 }}
      style={{
        background: "rgba(255,255,255,0.025)",
        border: "1px solid var(--divider)",
        borderLeft: `3px solid ${color}`,
        borderRadius: 10,
        padding: "9px 11px",
        marginBottom: 7,
        position: "relative",
        overflow: "hidden",
      }}
    >
      {/* BEST PLAY watermark */}
      {isBest && (
        <div style={{
          position: "absolute", inset: 0, display: "flex", alignItems: "center",
          justifyContent: "flex-end", paddingRight: 12, pointerEvents: "none", opacity: 0.04,
        }}>
          <span style={{ fontFamily: "var(--font-display)", fontSize: 52, fontWeight: 700, color, whiteSpace: "nowrap", letterSpacing: "-0.03em" }}>BEST</span>
        </div>
      )}

      {/* Header row: priority · icon · logos · urgency · impact */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 5 }}>
        {/* Priority number */}
        <span style={{ fontFamily: "var(--font-data)", fontSize: 10, fontWeight: 700, color, minWidth: 12, flexShrink: 0 }}>
          {action.priority}
        </span>

        {/* Type icon */}
        {Icon && <Icon size={11} strokeWidth={2} style={{ color, flexShrink: 0 }} />}

        {/* Team badges — for transfers show OUT → IN; for others show single badge */}
        {isTransfer && action.player_out_team_code && action.team_code ? (
          <div style={{ display: "flex", alignItems: "center", gap: 3, flexShrink: 0 }}>
            <TeamBadge code={action.player_out_team_code} />
            <span style={{ fontSize: 8, color: "var(--text-3)" }}>→</span>
            <TeamBadge code={action.team_code} />
          </div>
        ) : isTransfer && (action.player_out_team_code || action.team_code) ? (
          <TeamBadge code={(action.player_out_team_code || action.team_code)!} />
        ) : !isTransfer && action.team_code ? (
          <TeamBadge code={action.team_code} />
        ) : null}

        {/* BEST PLAY badge */}
        {isBest && (
          <span style={{
            fontFamily: "var(--font-ui)", fontSize: 8, fontWeight: 700,
            color, background: `${color}1a`, border: `1px solid ${color}33`,
            borderRadius: 999, padding: "1px 5px", letterSpacing: "0.07em", flexShrink: 0,
          }}>BEST</span>
        )}

        {/* Urgency */}
        <span style={{
          fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 700,
          color: URGENCY_COLOR[action.urgency], letterSpacing: "0.08em",
          textTransform: "uppercase", flexShrink: 0,
        }}>
          {URGENCY_LABEL[action.urgency]}
        </span>

        {/* Impact — pushed right */}
        <div style={{ marginLeft: "auto", textAlign: "right", flexShrink: 0 }}>
          <span style={{ fontFamily: "var(--font-data)", fontSize: 13, fontWeight: 700, color, letterSpacing: "-0.03em" }}>
            +{action.impact_value}
          </span>
          <span style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--text-3)", marginLeft: 2 }}>
            {action.impact_label}
          </span>
        </div>
      </div>

      {/* Confidence / risk badges */}
      {(action.confidence_score != null || action.risk_profile) && (
        <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginBottom: 5 }}>
          {action.confidence_score != null && (
            <span className="badge badge-muted" style={{ fontSize: 9 }}>
              {action.confidence_score}% conf
            </span>
          )}
          {action.risk_profile && (
            <span className="badge badge-muted" style={{ fontSize: 9 }}>
              {action.risk_profile.replace(/_/g, " ")}
            </span>
          )}
        </div>
      )}

      {/* Label */}
      <div style={{
        fontFamily: "var(--font-ui)", fontSize: 13, fontWeight: 600,
        color: "var(--text-1)", letterSpacing: "-0.01em", marginBottom: 3,
        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
      }}>
        {action.label}
      </div>

      {/* Reasoning */}
      <div style={{
        fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-3)",
        lineHeight: 1.35, overflow: "hidden",
        display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
      }}>
        {action.explanation_summary || action.reasoning}
      </div>
    </motion.div>
  );
}

// ── Main ActionBrief component ─────────────────────────────────────────────
export default function ActionBrief({
  brief,
}: {
  brief: PriorityActions;
  teamId: number | null;
}) {
  // GW is underway — squad locked, no actions possible
  if (brief.gw_state === "underway") {
    return (
      <motion.div
        initial={{ opacity: 0, x: -16 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ type: "spring", stiffness: 240, damping: 26 }}
        className="glass"
        style={{ borderRadius: 14, padding: "14px 14px 12px", marginBottom: 10 }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--amber)", display: "inline-block", flexShrink: 0 }} />
          <span style={{ fontFamily: "var(--font-display)", fontSize: 15, fontWeight: 600, color: "var(--text-1)", letterSpacing: "-0.02em" }}>
            GW{brief.gameweek} Underway
          </span>
        </div>
        <p style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-3)", lineHeight: 1.55, margin: 0 }}>
          Squad locked · fixtures in play · no transfers or changes possible.<br />
          Check the <strong style={{ color: "var(--text-2)" }}>Live Score</strong> tab for real-time points.
        </p>
      </motion.div>
    );
  }

  if (!brief.actions.length) return null;

  return (
    <motion.div
      initial={{ opacity: 0, x: -16 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ type: "spring", stiffness: 240, damping: 26 }}
      className="glass"
      style={{ borderRadius: 14, padding: "12px 12px 8px", marginBottom: 10 }}
    >
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <div>
          <span style={{
            fontFamily: "var(--font-display)", fontSize: 15, fontWeight: 600,
            color: "var(--text-1)", letterSpacing: "-0.02em",
          }}>
            GW{brief.gameweek} Brief
          </span>
          <span style={{
            display: "block", fontFamily: "var(--font-ui)", fontSize: 9,
            color: "var(--text-3)", marginTop: 1, letterSpacing: "0.06em",
            textTransform: "uppercase",
          }}>
            {brief.free_transfers} FT · {brief.actions.length} action{brief.actions.length !== 1 ? "s" : ""}
          </span>
        </div>
        <span style={{
          fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 600,
          color: "var(--text-3)", letterSpacing: "0.12em", textTransform: "uppercase",
          padding: "2px 7px", border: "1px solid var(--divider)", borderRadius: 999,
        }}>
          priority
        </span>
      </div>

      {/* Action cards */}
      <div>
        {brief.actions.map((action, idx) => (
          <ActionCard key={action.priority} action={action} isBest={idx === 0} />
        ))}
      </div>
    </motion.div>
  );
}
