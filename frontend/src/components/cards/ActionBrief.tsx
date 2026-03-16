"use client";
import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { CheckCircle, XCircle, Zap, ArrowLeftRight, User, Shield, TrendingUp } from "lucide-react";
import type { PriorityAction, PriorityActions, ActionType, ActionUrgency } from "@/types/fpl";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── Colors per action type ─────────────────────────────────────────────────
const TYPE_COLOR: Record<ActionType | string, string> = {
  captain:    "var(--amber)",
  transfer:   "var(--green)",
  injury:     "var(--red)",
  chip:       "var(--blue)",
  double_gw:  "var(--amber)",
  bench_swap: "var(--green)",
};

const TYPE_ICON: Record<ActionType | string, React.ElementType> = {
  captain:    User,
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

// ── Single action card ──────────────────────────────────────────────────────
function ActionCard({
  action,
  teamId,
  gameweek,
  onDone,
  onSkip,
  isBest,
}: {
  action: PriorityAction;
  teamId: number | null;
  gameweek: number;
  onDone: () => void;
  onSkip: () => void;
  isBest?: boolean;
}) {
  const [logging, setLogging] = useState<"done" | "skip" | null>(null);
  const color = TYPE_COLOR[action.type] || "var(--text-2)";
  const Icon = TYPE_ICON[action.type] || Zap;

  const logDecision = async (followed: boolean) => {
    setLogging(followed ? "done" : "skip");
    try {
      // Create decision log entry
      const createRes = await fetch(`${API}/api/decisions/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          team_id: teamId || 0,
          gameweek_id: gameweek,
          decision_type: action.decision_type,
          recommended_option: action.recommended_option,
          expected_points: action.impact_value,
          reasoning: action.reasoning,
        }),
      });
      if (createRes.ok) {
        const created = await createRes.json();
        // Immediately patch with user choice
        await fetch(`${API}/api/decisions/${created.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            user_choice: followed ? action.recommended_option : "SKIPPED",
            decision_followed: followed,
          }),
        });
      }
    } catch { /* silent — UI still updates optimistically */ }
    // Optimistic update
    if (followed) onDone();
    else onSkip();
  };

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, x: -20, height: 0, marginBottom: 0, padding: 0 }}
      transition={{ type: "spring", stiffness: 300, damping: 28 }}
      style={{
        background: isBest
          ? `rgba(${color === "var(--red)" ? "239,68,68" : color === "var(--amber)" ? "245,158,11" : color === "var(--blue)" ? "59,130,246" : "34,197,94"}, 0.08)`
          : `rgba(${color === "var(--red)" ? "239,68,68" : color === "var(--amber)" ? "245,158,11" : color === "var(--blue)" ? "59,130,246" : "34,197,94"}, 0.04)`,
        border: isBest ? `1px solid ${color}55` : `1px solid ${color}26`,
        borderLeft: `3px solid ${color}`,
        borderRadius: 10,
        padding: "10px 12px",
        marginBottom: 8,
        position: "relative",
        overflow: "hidden",
        boxShadow: isBest ? `0 0 24px ${color}18` : undefined,
      }}
    >
      {/* BEST PLAY watermark */}
      {isBest && (
        <div style={{
          position: "absolute", inset: 0, display: "flex", alignItems: "center",
          justifyContent: "flex-end", paddingRight: 12, pointerEvents: "none", opacity: 0.05,
        }}>
          <span style={{ fontFamily: "var(--font-display)", fontSize: 56, fontWeight: 700, color, whiteSpace: "nowrap", letterSpacing: "-0.03em" }}>BEST</span>
        </div>
      )}

      {/* Priority + Type header */}
      <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 6 }}>
        <span
          style={{
            fontFamily: "var(--font-data)",
            fontSize: 10,
            fontWeight: 700,
            color: color,
            minWidth: 14,
          }}
        >
          {action.priority}
        </span>
        <Icon size={11} strokeWidth={2} style={{ color, flexShrink: 0 }} />
        {isBest && (
          <span style={{
            fontFamily: "var(--font-ui)", fontSize: 8, fontWeight: 700,
            color, background: `${color}22`, border: `1px solid ${color}44`,
            borderRadius: 999, padding: "1px 6px", letterSpacing: "0.08em",
          }}>BEST PLAY</span>
        )}
        <span
          style={{
            fontFamily: "var(--font-ui)",
            fontSize: 9,
            fontWeight: 700,
            color: URGENCY_COLOR[action.urgency],
            letterSpacing: "0.1em",
            textTransform: "uppercase",
          }}
        >
          {URGENCY_LABEL[action.urgency]}
        </span>
        {/* Impact */}
        <div style={{ marginLeft: "auto", textAlign: "right", flexShrink: 0 }}>
          <span
            style={{
              fontFamily: "var(--font-data)",
              fontSize: 14,
              fontWeight: 700,
              color,
              letterSpacing: "-0.03em",
            }}
          >
            +{action.impact_value}
          </span>
          <span
            style={{
              fontFamily: "var(--font-ui)",
              fontSize: 8,
              color: "var(--text-3)",
              marginLeft: 3,
            }}
          >
            {action.impact_label}
          </span>
        </div>
      </div>

      {(action.confidence_score != null || action.risk_profile) && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 6 }}>
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
      <div
        style={{
          fontFamily: "var(--font-ui)",
          fontSize: 13,
          fontWeight: 600,
          color: "var(--text-1)",
          letterSpacing: "-0.01em",
          marginBottom: 4,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {action.label}
      </div>

      {/* Reasoning */}
      <div
        style={{
          fontFamily: "var(--font-ui)",
          fontSize: 10,
          color: "var(--text-3)",
          lineHeight: 1.35,
          marginBottom: 9,
          overflow: "hidden",
          display: "-webkit-box",
          WebkitLineClamp: 2,
          WebkitBoxOrient: "vertical",
        }}
      >
        {action.explanation_summary || action.reasoning}
      </div>

      {/* DONE / SKIP buttons */}
      <div style={{ display: "flex", gap: 6 }}>
        <motion.button
          whileHover={{ scale: 1.03 }}
          whileTap={{ scale: 0.97 }}
          disabled={logging !== null}
          onClick={() => logDecision(true)}
          style={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 5,
            padding: "5px 0",
            borderRadius: 7,
            border: "1px solid rgba(34,197,94,0.3)",
            background: logging === "done" ? "rgba(34,197,94,0.15)" : "rgba(34,197,94,0.06)",
            color: "var(--green)",
            fontFamily: "var(--font-ui)",
            fontSize: 10,
            fontWeight: 600,
            cursor: logging !== null ? "default" : "pointer",
            letterSpacing: "0.06em",
            transition: "all 150ms",
          }}
        >
          <CheckCircle size={10} />
          {logging === "done" ? "LOGGED" : "DONE"}
        </motion.button>

        <motion.button
          whileHover={{ scale: 1.03 }}
          whileTap={{ scale: 0.97 }}
          disabled={logging !== null}
          onClick={() => logDecision(false)}
          style={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 5,
            padding: "5px 0",
            borderRadius: 7,
            border: "1px solid var(--divider)",
            background: logging === "skip" ? "rgba(255,255,255,0.05)" : "transparent",
            color: logging === "skip" ? "var(--text-2)" : "var(--text-3)",
            fontFamily: "var(--font-ui)",
            fontSize: 10,
            fontWeight: 600,
            cursor: logging !== null ? "default" : "pointer",
            letterSpacing: "0.06em",
            transition: "all 150ms",
          }}
        >
          <XCircle size={10} />
          {logging === "skip" ? "NOTED" : "SKIP"}
        </motion.button>
      </div>
    </motion.div>
  );
}

// ── localStorage helpers — persist dismissed per gameweek ──────────────────
const STORAGE_KEY = "fpl_brief_dismissed";

function loadDismissed(gameweek: number): Set<number> {
  try {
    const raw = typeof window !== "undefined" ? localStorage.getItem(STORAGE_KEY) : null;
    if (!raw) return new Set();
    const parsed = JSON.parse(raw) as Record<string, number[]>;
    return new Set(parsed[String(gameweek)] ?? []);
  } catch {
    return new Set();
  }
}

function saveDismissed(gameweek: number, dismissed: Set<number>) {
  try {
    const raw = typeof window !== "undefined" ? localStorage.getItem(STORAGE_KEY) : null;
    const parsed: Record<string, number[]> = raw ? JSON.parse(raw) : {};
    parsed[String(gameweek)] = Array.from(dismissed);
    // Prune old GWs (keep only last 3)
    const keys = Object.keys(parsed).map(Number).sort((a, b) => b - a);
    keys.slice(3).forEach(k => delete parsed[String(k)]);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(parsed));
  } catch { /* silent */ }
}

// ── Main ActionBrief component ─────────────────────────────────────────────
export default function ActionBrief({
  brief,
  teamId,
}: {
  brief: PriorityActions;
  teamId: number | null;
}) {
  const [dismissed, setDismissed] = useState<Set<number>>(() => loadDismissed(brief.gameweek));

  const dismiss = (priority: number) => {
    setDismissed(prev => {
      const next = new Set(prev).add(priority);
      saveDismissed(brief.gameweek, next);
      return next;
    });
  };

  const visible = brief.actions.filter((a) => !dismissed.has(a.priority));

  if (visible.length === 0) {
    return (
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        style={{
          padding: "14px 16px",
          textAlign: "center",
          color: "var(--text-3)",
          fontFamily: "var(--font-ui)",
          fontSize: 11,
        }}
      >
        ✓ All actions logged for GW{brief.gameweek}
      </motion.div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, x: -16 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ type: "spring", stiffness: 240, damping: 26 }}
      className="glass"
      style={{ borderRadius: 16, padding: "14px 14px 10px", marginBottom: 10 }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 12,
        }}
      >
        <div>
          <span
            style={{
              fontFamily: "var(--font-display)",
              fontSize: 16,
              fontWeight: 600,
              color: "var(--text-1)",
              letterSpacing: "-0.02em",
            }}
          >
            GW{brief.gameweek} Brief
          </span>
          <span
            style={{
              display: "block",
              fontFamily: "var(--font-ui)",
              fontSize: 9,
              color: "var(--text-3)",
              marginTop: 1,
              letterSpacing: "0.06em",
              textTransform: "uppercase",
            }}
          >
            {brief.free_transfers} free transfer{brief.free_transfers !== 1 ? "s" : ""} · {visible.length} action{visible.length !== 1 ? "s" : ""}
          </span>
        </div>
        <span
          style={{
            fontFamily: "var(--font-ui)",
            fontSize: 9,
            fontWeight: 600,
            color: "var(--text-3)",
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            padding: "3px 8px",
            border: "1px solid var(--divider)",
            borderRadius: 999,
          }}
        >
          priority
        </span>
      </div>

      {/* Action cards */}
      <AnimatePresence mode="popLayout">
        {visible.map((action, idx) => (
          <ActionCard
            key={action.priority}
            action={action}
            teamId={teamId}
            gameweek={brief.gameweek}
            onDone={() => dismiss(action.priority)}
            onSkip={() => dismiss(action.priority)}
            isBest={idx === 0}
          />
        ))}
      </AnimatePresence>
    </motion.div>
  );
}
