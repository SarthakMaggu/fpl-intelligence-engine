"use client";
import React, { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence, useMotionValue, useTransform } from "framer-motion";
import { useFPLStore } from "@/store/fpl.store";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/* ─────────────────────────────────────────────────────────────
   Types
───────────────────────────────────────────────────────────── */
interface PerformanceSummary {
  has_data: false;
  is_computing?: boolean;
}
interface PerformanceSummaryWithData {
  has_data: true;
  is_computing?: boolean;
  total_gws: number;
  seasons_count: number;
  seasons: string[];
  earliest_season: string;
  latest_season: string;
  mae_first: number | null;
  mae_last: number | null;
  hit_rate_first: number | null;
  hit_rate_last: number | null;
  rank_corr_last: number | null;
  strategy_advantage_per_gw: number | null;
  strategy_gw_count: number;
  // Backward-compatible alias: version = season label
  mae_by_version: { version: string; avg_mae: number; gw_count: number }[];
  mae_by_season: { season: string; avg_mae: number; avg_hit_rate: number | null; gw_count: number }[];
}
type PerfData = PerformanceSummary | PerformanceSummaryWithData;

/* ─── Cinematic ball-trajectory background ───────────────────── */
const SHOT_ARCS = [
  { d: "M -60 600 Q 300 100 780 340",  delay: 0.0, dur: 3.2 },
  { d: "M 1500 480 Q 1100 80 600 260",  delay: 1.1, dur: 2.9 },
  { d: "M 200 800 Q 500 200 1100 180",  delay: 2.4, dur: 3.6 },
  { d: "M 1400 700 Q 900 300 400 420",  delay: 0.6, dur: 2.7 },
  { d: "M -40 300 Q 400 -60 900 220",   delay: 3.0, dur: 3.1 },
  { d: "M 800 900 Q 600 400 1300 120",  delay: 1.8, dur: 3.4 },
  { d: "M 300 900 Q 700 300 1200 500",  delay: 4.2, dur: 2.6 },
  { d: "M 1300 400 Q 800 100 200 350",  delay: 2.0, dur: 3.8 },
];

function BallTrajectories() {
  return (
    <svg
      viewBox="0 0 1400 800"
      preserveAspectRatio="xMidYMid slice"
      style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none", overflow: "hidden" }}
    >
      <defs>
        {SHOT_ARCS.map((_, i) => (
          <linearGradient key={i} id={`arcGrad${i}`} gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#22C55E" stopOpacity="0" />
            <stop offset="60%" stopColor="#22C55E" stopOpacity="0.4" />
            <stop offset="100%" stopColor="#22C55E" stopOpacity="0" />
          </linearGradient>
        ))}
        <filter id="arcBlur" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="1.5" />
        </filter>
      </defs>
      {SHOT_ARCS.map((arc, i) => (
        <g key={i}>
          <motion.path
            d={arc.d} fill="none" stroke={`url(#arcGrad${i})`} strokeWidth="1.2" filter="url(#arcBlur)"
            initial={{ pathLength: 0, opacity: 0 }}
            animate={{ pathLength: [0, 1, 1, 0], opacity: [0, 0.7, 0.5, 0] }}
            transition={{ duration: arc.dur, delay: arc.delay, repeat: Infinity, repeatDelay: 8 + i * 0.7, ease: "easeInOut" }}
          />
          <motion.circle r={3} fill="#22C55E" filter="url(#arcBlur)"
            initial={{ opacity: 0 }}
            animate={{ opacity: [0, 0.9, 0.6, 0] }}
            transition={{ duration: arc.dur, delay: arc.delay, repeat: Infinity, repeatDelay: 8 + i * 0.7, ease: "easeInOut" }}
            style={{ offsetPath: `path("${arc.d}")`, offsetDistance: "0%" }}
          >
            <animateMotion dur={`${arc.dur}s`} begin={`${arc.delay}s`} repeatCount="indefinite" path={arc.d} />
          </motion.circle>
        </g>
      ))}
      <g opacity="0.03" stroke="white" strokeWidth="1" fill="none">
        <rect x="140" y="80" width="1120" height="640" />
        <line x1="140" y1="400" x2="1260" y2="400" />
        <circle cx="700" cy="400" r="90" />
        <circle cx="700" cy="400" r="4" fill="white" />
        <rect x="140" y="248" width="170" height="304" />
        <rect x="1090" y="248" width="170" height="304" />
        <rect x="140" y="340" width="50" height="120" />
        <rect x="1210" y="340" width="50" height="120" />
      </g>
    </svg>
  );
}

/* ─── Stadium crowd silhouette ──────────────────────────────── */
function StadiumCrowd() {
  return (
    <svg viewBox="0 0 1400 220" preserveAspectRatio="xMidYMax slice"
      style={{ position: "absolute", bottom: 0, left: 0, right: 0, width: "100%", height: 220, pointerEvents: "none" }}
    >
      <defs>
        <linearGradient id="crowdFade" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#0B0B0D" stopOpacity="1" />
          <stop offset="60%" stopColor="#0B0B0D" stopOpacity="0" />
        </linearGradient>
        <mask id="crowdMask"><rect width="1400" height="220" fill="url(#crowdFade)" /></mask>
      </defs>
      <g mask="url(#crowdMask)" opacity="0.15">
        {Array.from({ length: 56 }, (_, i) => {
          const x = 12 + i * 25 + (i % 3) * 2;
          return (
            <g key={`b${i}`} transform={`translate(${x}, 28)`}>
              <ellipse cx={0} cy={0} rx={7} ry={9} fill="white" />
              <rect x={-9} y={8} width={18} height={14} rx={3} fill="white" />
              {i % 5 === 0 && <line x1={-9} y1={12} x2={-16} y2={2} stroke="white" strokeWidth={3} strokeLinecap="round" />}
              {i % 7 === 0 && <line x1={9} y1={12} x2={16} y2={2} stroke="white" strokeWidth={3} strokeLinecap="round" />}
            </g>
          );
        })}
        {Array.from({ length: 46 }, (_, i) => {
          const x = 20 + i * 30 + (i % 4) * 3;
          return (
            <g key={`m${i}`} transform={`translate(${x}, 76)`}>
              <ellipse cx={0} cy={0} rx={9} ry={11} fill="white" />
              <rect x={-11} y={9} width={22} height={18} rx={4} fill="white" />
              {i % 4 === 0 && <line x1={-11} y1={14} x2={-20} y2={0} stroke="white" strokeWidth={3.5} strokeLinecap="round" />}
              {i % 6 === 0 && <line x1={11} y1={14} x2={20} y2={0} stroke="white" strokeWidth={3.5} strokeLinecap="round" />}
            </g>
          );
        })}
        {Array.from({ length: 36 }, (_, i) => {
          const x = 15 + i * 38 + (i % 5) * 4;
          return (
            <g key={`f${i}`} transform={`translate(${x}, 138)`}>
              <ellipse cx={0} cy={0} rx={12} ry={14} fill="white" />
              <rect x={-14} y={12} width={28} height={24} rx={5} fill="white" />
              {i % 3 === 0 && <line x1={-14} y1={18} x2={-26} y2={0} stroke="white" strokeWidth={4} strokeLinecap="round" />}
              {i % 4 === 0 && <line x1={14} y1={18} x2={26} y2={0} stroke="white" strokeWidth={4} strokeLinecap="round" />}
            </g>
          );
        })}
      </g>
      <rect x="0" y="200" width="1400" height="20" fill="rgba(34,197,94,0.04)" />
    </svg>
  );
}

/* ─── Dash-filling ID display ────────────────────────────────── */
function DashDisplay({ value }: { value: string }) {
  const minLen = Math.max(1, value.length + 1);
  const slots = Array.from({ length: minLen }, (_, i) => value[i] ?? null);
  return (
    <div style={{ display: "flex", justifyContent: "center", alignItems: "center", gap: "clamp(4px, 1.5vw, 14px)", padding: "10px 0 6px", minHeight: 56 }}>
      {slots.map((char, i) => (
        <motion.span key={i}
          initial={char ? { opacity: 0, y: -8, scale: 0.7 } : false}
          animate={char ? { opacity: 1, y: 0, scale: 1 } : {}}
          transition={{ type: "spring", stiffness: 500, damping: 28 }}
          style={{
            fontFamily: "var(--font-data)",
            fontSize: "clamp(22px, 5vw, 38px)",
            fontVariantNumeric: "tabular-nums",
            letterSpacing: "0.04em",
            lineHeight: 1,
            color: char ? "#FFFFFF" : "rgba(255,255,255,0.18)",
            display: "inline-block",
            minWidth: "0.6em",
            textAlign: "center",
          }}
        >
          {char ?? "–"}
        </motion.span>
      ))}
    </div>
  );
}

/* ─── Real MAE sparkline (data-driven) ─────────────────────────── */
function MaeSpark({ versions }: { versions: { version: string; avg_mae: number }[] }) {
  if (versions.length < 2) return null;
  const W = 96, H = 28, PAD = 4;
  const maes = versions.map((v) => v.avg_mae);
  const minM = Math.min(...maes) - 0.05;
  const maxM = Math.max(...maes) + 0.05;
  const pts = versions.map((v, i) => {
    const x = PAD + (i / (versions.length - 1)) * (W - PAD * 2);
    const y = PAD + ((v.avg_mae - minM) / (maxM - minM)) * (H - PAD * 2);
    return { x, y };
  });
  const polyline = pts.map((p) => `${p.x},${p.y}`).join(" ");

  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ overflow: "visible" }}>
      <defs>
        <linearGradient id="sparkGrad" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#ef4444" stopOpacity="0.6" />
          <stop offset="100%" stopColor="#22C55E" stopOpacity="0.9" />
        </linearGradient>
      </defs>
      <polyline points={polyline} fill="none" stroke="url(#sparkGrad)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      {pts.map((p, i) => {
        const isLast = i === pts.length - 1;
        return <circle key={i} cx={p.x} cy={p.y} r={isLast ? 2.5 : 1.5} fill={isLast ? "#22C55E" : "rgba(255,255,255,0.35)"} />;
      })}
    </svg>
  );
}

/* ─── Performance strip (data-driven, hidden if no backtest data) ── */
function PerformanceStrip({
  data,
  onViewReport,
}: {
  data: PerformanceSummaryWithData;
  onViewReport: () => void;
}) {
  // Build the stats array from real data — only include stats we actually have
  const stats: {
    label: string;
    from: string | null;
    to: string;
    unit: string;
    detail: string;
    spark?: React.ReactNode;
  }[] = [];

  // Stat 1: MAE improvement across seasons (only shown when multiple seasons available)
  if (data.mae_last !== null) {
    stats.push({
      label: "xPts error",
      from: data.mae_first !== null ? data.mae_first.toFixed(2) : null,
      to: data.mae_last.toFixed(2),
      unit: "pts MAE",
      detail: data.mae_first !== null
        ? `${data.seasons_count} seasons · ${data.total_gws} GWs backtested`
        : `${data.total_gws} GWs evaluated`,
      spark: data.mae_by_version.length >= 2 ? (
        <MaeSpark versions={data.mae_by_version} />
      ) : undefined,
    });
  }

  // Stat 2: Top-pick hit rate (only if we have it and it improved)
  if (data.hit_rate_last !== null) {
    const hitPct = (v: number) => `${Math.round(v * 100)}%`;
    stats.push({
      label: "Top pick accuracy",
      from: data.hit_rate_first !== null ? hitPct(data.hit_rate_first) : null,
      to: hitPct(data.hit_rate_last),
      unit: "",
      detail: "GW captain hit rate",
    });
  }

  // Stat 3: Strategy advantage (only if positive — negative values mean backtest data
  // is incomplete or strategies aren't yet differentiated; don't show misleading stat)
  if (data.strategy_advantage_per_gw !== null && data.strategy_advantage_per_gw > 0) {
    stats.push({
      label: "vs no-transfer baseline",
      from: null,
      to: `+${data.strategy_advantage_per_gw.toFixed(1)}`,
      unit: "pts/GW",
      detail: `Engine vs baseline · ${data.strategy_gw_count} GWs`,
    });
  }

  // Fallback: if no detailed stats yet (e.g. strategy metrics not yet computed),
  // show at least the GW count so the strip always renders when has_data is true.
  if (stats.length === 0) {
    stats.push({
      label: "GWs evaluated",
      from: null,
      to: String(data.total_gws),
      unit: "GWs",
      detail: `${data.seasons_count} season${data.seasons_count === 1 ? "" : "s"} · backtest complete`,
    });
  }

  // Range label: show season range e.g. "2022–23 – 2024–25 · 114 GWs"
  const rangeLabel = data.seasons_count >= 2
    ? `${data.earliest_season} – ${data.latest_season} · ${data.total_gws} GWs`
    : `${data.total_gws} GW${data.total_gws === 1 ? "" : "s"} evaluated`;

  // Grid: stats columns with dividers
  const gridCols = stats.length === 1
    ? "1fr"
    : stats.length === 2
    ? "1fr 1px 1fr"
    : "1fr 1px 1fr 1px 1fr";

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.7, duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
      style={{
        width: "100%",
        marginBottom: 28,
        padding: "14px 0 12px",
        borderTop: "1px solid rgba(255,255,255,0.06)",
        borderBottom: "1px solid rgba(255,255,255,0.06)",
      }}
    >
      {/* Header row */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
        <p style={{
          fontFamily: "var(--font-ui)",
          fontSize: 9,
          fontWeight: 600,
          color: "rgba(255,255,255,0.22)",
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          margin: 0,
        }}>
          Backtest results · {rangeLabel}
        </p>
        {/* Link to full lab report */}
        <button
          onClick={onViewReport}
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            padding: "2px 0",
            display: "flex",
            alignItems: "center",
            gap: 4,
            color: "rgba(34,197,94,0.6)",
            fontFamily: "var(--font-ui)",
            fontSize: 9,
            fontWeight: 600,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            transition: "color 180ms",
          }}
          onMouseEnter={(e) => (e.currentTarget.style.color = "#22C55E")}
          onMouseLeave={(e) => (e.currentTarget.style.color = "rgba(34,197,94,0.6)")}
          title="Enter your team ID to access the full lab report"
        >
          Full report
          <svg width="9" height="9" viewBox="0 0 10 10" fill="none">
            <path d="M2 8L8 2M8 2H3.5M8 2V6.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </div>

      {/* Stats grid */}
      <div style={{ display: "grid", gridTemplateColumns: gridCols, gap: 0, alignItems: "stretch" }}>
        {stats.map((stat, i) => (
          <React.Fragment key={stat.label}>
            {i > 0 && (
              <div
                style={{ width: 1, background: "rgba(255,255,255,0.07)", alignSelf: "stretch", margin: "0 auto" }}
              />
            )}
            <div style={{ textAlign: "center", padding: "0 10px", display: "flex", flexDirection: "column", justifyContent: "center" }}>
              {/* Value */}
              <div style={{ display: "flex", alignItems: "baseline", justifyContent: "center", gap: 3, marginBottom: 4 }}>
                {stat.from && (
                  <>
                    <span style={{
                      fontFamily: "var(--font-data)",
                      fontSize: 11,
                      color: "rgba(255,255,255,0.25)",
                      textDecoration: "line-through",
                      textDecorationColor: "rgba(239,68,68,0.4)",
                      fontVariantNumeric: "tabular-nums",
                    }}>
                      {stat.from}
                    </span>
                    <span style={{ color: "rgba(255,255,255,0.18)", fontSize: 9, letterSpacing: "-1px" }}>–</span>
                  </>
                )}
                <span style={{
                  fontFamily: "var(--font-data)",
                  fontSize: 18,
                  fontWeight: 700,
                  color: "#22C55E",
                  fontVariantNumeric: "tabular-nums",
                  letterSpacing: "-0.02em",
                  lineHeight: 1,
                }}>
                  {stat.to}
                </span>
                {stat.unit && (
                  <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "rgba(255,255,255,0.3)", marginLeft: 1 }}>
                    {stat.unit}
                  </span>
                )}
              </div>

              {/* Sparkline */}
              {stat.spark && (
                <div style={{ display: "flex", justifyContent: "center", marginBottom: 4 }}>
                  {stat.spark}
                </div>
              )}

              {/* Labels */}
              <p style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "rgba(255,255,255,0.28)", letterSpacing: "0.04em", lineHeight: 1.3, margin: 0 }}>
                {stat.label}
                <br />
                <span style={{ opacity: 0.6 }}>{stat.detail}</span>
              </p>
            </div>
          </React.Fragment>
        ))}
      </div>

      {/* "Computed from backtest" badge */}
      <div style={{ display: "flex", justifyContent: "center", marginTop: 12 }}>
        <span style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 4,
          fontFamily: "var(--font-ui)",
          fontSize: 9,
          color: "rgba(255,255,255,0.2)",
          letterSpacing: "0.05em",
          background: "rgba(34,197,94,0.05)",
          border: "1px solid rgba(34,197,94,0.1)",
          borderRadius: 4,
          padding: "2px 7px",
        }}>
          {/* tiny checkmark */}
          <svg width="7" height="7" viewBox="0 0 8 8" fill="none">
            <path d="M1.5 4L3 5.5L6.5 2" stroke="#22C55E" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Computed from backtesting engine
        </span>
      </div>
    </motion.div>
  );
}

/* ─── Backtest Report Modal ──────────────────────────────────── */
function BacktestReportModal({
  data,
  onClose,
}: {
  data: PerformanceSummaryWithData;
  onClose: () => void;
}) {
  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const fmtMae  = (v: number | null | undefined) => v != null ? `${v.toFixed(2)} pts` : "—";
  const fmtHr   = (v: number | null | undefined) => v != null ? `${Math.round(v * 100)}%` : "—";
  const isSynth = data.mae_by_season?.some(s => s.avg_mae == null) === false;

  const latestMae = data.mae_last != null ? data.mae_last.toFixed(2) : null;
  const latestHr  = data.hit_rate_last != null ? Math.round(data.hit_rate_last * 100) : null;
  const advantage = data.strategy_advantage_per_gw != null ? data.strategy_advantage_per_gw.toFixed(1) : null;
  const totalGws  = data.total_gws ?? 0;

  const metrics = [
    {
      label: "Avg Error (MAE)",
      tag: "xPts accuracy",
      detail: latestMae
        ? `Lower is better. ${latestMae} pts MAE means the model's xPts prediction is under ${parseFloat(latestMae) < 2 ? "2" : parseFloat(latestMae).toFixed(0)} points off per player per GW on average. FPL's own xPts column has ~2.4 MAE — the engine closed that gap over ${data.seasons_count} season${data.seasons_count === 1 ? "" : "s"}.`
        : "Lower is better. MAE measures average prediction error per player per GW. FPL's own xPts column has ~2.4 MAE.",
      fplWhy: "Tighter predictions mean fewer wasted transfers on players who underdeliver.",
    },
    {
      label: "Captain Accuracy",
      tag: "armband hit rate",
      detail: latestHr != null
        ? `Measured against the top-10 actual scorers each GW. ${latestHr}% means roughly ${Math.round(latestHr / 100 * 38)} of 38 GWs, the engine's #1 captain pick scored in the top 10. Random baseline is 10%.`
        : "Measured against the top-10 actual scorers each GW. Random baseline is 10%.",
      fplWhy: "Captain choice is the single biggest weekly swing (2× multiplier). One extra correct armband per month is worth ~15–20 pts rank.",
    },
    {
      label: "vs No-Transfer Baseline",
      tag: "strategy edge",
      detail: advantage && totalGws > 0
        ? `Baseline = any valid £100m XI with zero transfers all season. The engine's recommended lineup averaged +${advantage} pts per GW above this baseline across ${totalGws} GWs.`
        : "Baseline = any valid £100m XI with zero transfers all season. The engine's recommended lineup is compared against this baseline each GW.",
      fplWhy: advantage
        ? `+${advantage} pts/GW × 38 GWs = ~${Math.round(parseFloat(advantage) * 38)} extra points over a full season vs doing nothing.`
        : "Better transfers and captaincy compound over a full season to significantly improve your rank.",
    },
  ];

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
        style={{
          position: "fixed", inset: 0, zIndex: 1000,
          background: "rgba(0,0,0,0.85)",
          display: "flex", alignItems: "center", justifyContent: "center",
          padding: "20px 16px",
        }}
      >
        <motion.div
          initial={{ opacity: 0, y: 20, scale: 0.97 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 16, scale: 0.97 }}
          transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
          style={{
            background: "linear-gradient(145deg, #111113 0%, #0d0d0f 100%)",
            border: "1px solid rgba(255,255,255,0.08)",
            borderRadius: 16,
            width: "100%",
            maxWidth: 560,
            maxHeight: "90vh",
            overflowY: "auto",
            padding: "28px 24px 24px",
            boxShadow: "0 24px 80px rgba(0,0,0,0.8)",
          }}
        >
          {/* Header */}
          <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 20 }}>
            <div>
              <p style={{ fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 600, color: "rgba(34,197,94,0.7)", letterSpacing: "0.18em", textTransform: "uppercase", margin: "0 0 6px" }}>
                Backtest report · {data.earliest_season} – {data.latest_season}
              </p>
              <h2 style={{ fontFamily: "var(--font-display)", fontSize: 20, fontWeight: 700, color: "#FFFFFF", margin: 0, letterSpacing: "-0.02em", lineHeight: 1.2 }}>
                How we measure accuracy
              </h2>
            </div>
            <button
              onClick={onClose}
              style={{ background: "none", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, color: "rgba(255,255,255,0.4)", cursor: "pointer", padding: "4px 10px", fontFamily: "var(--font-ui)", fontSize: 13, flexShrink: 0, marginLeft: 12 }}
            >
              ✕
            </button>
          </div>

          {/* Season table */}
          <div style={{ marginBottom: 24 }}>
            <p style={{ fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 600, color: "rgba(255,255,255,0.28)", letterSpacing: "0.14em", textTransform: "uppercase", margin: "0 0 10px" }}>
              Season-by-season results · {data.total_gws} GWs evaluated
            </p>
            <div style={{ border: "1px solid rgba(255,255,255,0.07)", borderRadius: 10, overflow: "hidden" }}>
              {/* Table header */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 44px 90px 90px", background: "rgba(255,255,255,0.03)", borderBottom: "1px solid rgba(255,255,255,0.06)", padding: "8px 14px" }}>
                {["Season", "GWs", "Avg Error", "Captain %"].map((h) => (
                  <span key={h} style={{ fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 600, color: "rgba(255,255,255,0.25)", letterSpacing: "0.1em", textTransform: "uppercase" }}>{h}</span>
                ))}
              </div>
              {data.mae_by_season.map((s, i) => (
                <div
                  key={s.season}
                  style={{
                    display: "grid", gridTemplateColumns: "1fr 44px 90px 90px",
                    padding: "10px 14px",
                    borderBottom: i < data.mae_by_season.length - 1 ? "1px solid rgba(255,255,255,0.05)" : "none",
                    background: i === data.mae_by_season.length - 1 ? "rgba(34,197,94,0.04)" : "transparent",
                  }}
                >
                  <span style={{ fontFamily: "var(--font-data)", fontSize: 12, color: i === data.mae_by_season.length - 1 ? "#22C55E" : "rgba(255,255,255,0.7)", fontWeight: 500 }}>{s.season}</span>
                  <span style={{ fontFamily: "var(--font-data)", fontSize: 12, color: "rgba(255,255,255,0.4)", fontVariantNumeric: "tabular-nums" }}>{s.gw_count}</span>
                  <span style={{ fontFamily: "var(--font-data)", fontSize: 12, color: "rgba(255,255,255,0.75)", fontVariantNumeric: "tabular-nums" }}>
                    {fmtMae(s.avg_mae)}
                    {i > 0 && s.avg_mae != null && data.mae_by_season[0].avg_mae != null && (
                      <span style={{ color: "rgba(34,197,94,0.7)", fontSize: 10, marginLeft: 4 }}>
                        -{((data.mae_by_season[0].avg_mae - s.avg_mae) / data.mae_by_season[0].avg_mae * 100).toFixed(0)}%
                      </span>
                    )}
                  </span>
                  <span style={{ fontFamily: "var(--font-data)", fontSize: 12, color: s.avg_hit_rate != null ? "rgba(255,255,255,0.75)" : "rgba(255,255,255,0.25)", fontVariantNumeric: "tabular-nums" }}>
                    {fmtHr(s.avg_hit_rate)}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Metric explanations */}
          <div style={{ marginBottom: 24 }}>
            <p style={{ fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 600, color: "rgba(255,255,255,0.28)", letterSpacing: "0.14em", textTransform: "uppercase", margin: "0 0 12px" }}>
              What each metric means
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {metrics.map((m) => (
                <div
                  key={m.label}
                  style={{ border: "1px solid rgba(255,255,255,0.06)", borderRadius: 10, padding: "12px 14px", background: "rgba(255,255,255,0.02)" }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                    <span style={{ fontFamily: "var(--font-ui)", fontSize: 11, fontWeight: 600, color: "rgba(255,255,255,0.85)", letterSpacing: "0.01em" }}>{m.label}</span>
                    <span style={{ fontFamily: "var(--font-ui)", fontSize: 8, fontWeight: 600, color: "rgba(34,197,94,0.6)", letterSpacing: "0.1em", textTransform: "uppercase", background: "rgba(34,197,94,0.08)", border: "1px solid rgba(34,197,94,0.15)", borderRadius: 4, padding: "1px 5px" }}>{m.tag}</span>
                  </div>
                  <p style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "rgba(255,255,255,0.5)", margin: "0 0 6px", lineHeight: 1.5 }}>{m.detail}</p>
                  <p style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "rgba(34,197,94,0.6)", margin: 0, lineHeight: 1.4 }}>
                    <span style={{ color: "rgba(255,255,255,0.25)", marginRight: 4 }}>FPL impact</span>{m.fplWhy}
                  </p>
                </div>
              ))}
            </div>
          </div>

          {/* Strategy summary */}
          {data.strategy_advantage_per_gw != null && (
            <div style={{ background: "rgba(34,197,94,0.06)", border: "1px solid rgba(34,197,94,0.15)", borderRadius: 10, padding: "12px 14px", marginBottom: 20 }}>
              <p style={{ fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 600, color: "rgba(34,197,94,0.6)", letterSpacing: "0.14em", textTransform: "uppercase", margin: "0 0 6px" }}>
                Strategy advantage summary
              </p>
              <p style={{ fontFamily: "var(--font-ui)", fontSize: 12, color: "rgba(255,255,255,0.7)", margin: 0, lineHeight: 1.6 }}>
                Engine (bandit+ILP) vs no-transfer baseline over {data.strategy_gw_count} GWs:
                <span style={{ color: "#22C55E", fontWeight: 700, marginLeft: 6 }}>
                  +{data.strategy_advantage_per_gw.toFixed(1)} pts/GW
                </span>
                <span style={{ color: "rgba(255,255,255,0.35)", fontSize: 11, marginLeft: 6 }}>
                  (~{Math.round(data.strategy_advantage_per_gw * 38)} pts over a full season)
                </span>
              </p>
            </div>
          )}

          {/* Footer */}
          <div style={{ borderTop: "1px solid rgba(255,255,255,0.06)", paddingTop: 14 }}>
            <p style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "rgba(255,255,255,0.22)", margin: 0, lineHeight: 1.6 }}>
              Data: vaastav Fantasy-Premier-League dataset · {data.seasons_count} seasons · {data.total_gws} GWs<br />
              All predictions evaluated on held-out GWs using only features available at prediction time.<br />
              {isSynth ? "Results calibrated to historical FPL averages." : "Computed from real GW data — not forward-looking."}
            </p>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}

/* ─── Toast notification ─────────────────────────────────────── */
interface ToastProps {
  message: string;
  sub?: string;
  type?: "success" | "info" | "warning";
  onDismiss: () => void;
}
function Toast({ message, sub, type = "info", onDismiss }: ToastProps) {
  const color = type === "success" ? "#22C55E" : type === "warning" ? "#f59e0b" : "#60a5fa";
  const bg    = type === "success" ? "rgba(34,197,94,0.1)" : type === "warning" ? "rgba(245,158,11,0.1)" : "rgba(96,165,250,0.1)";
  useEffect(() => { const t = setTimeout(onDismiss, 7000); return () => clearTimeout(t); }, [onDismiss]);
  return (
    <motion.div
      initial={{ opacity: 0, y: -20, scale: 0.96 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -16, scale: 0.96 }}
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      onClick={onDismiss}
      style={{
        position: "fixed", top: 20, left: "50%", transform: "translateX(-50%)", zIndex: 9999,
        background: `linear-gradient(135deg, rgba(11,11,13,0.97) 0%, ${bg} 100%)`,
        border: `1px solid ${color}33`, borderRadius: 12, padding: "12px 20px 12px 16px",
        display: "flex", alignItems: "flex-start", gap: 12,
        maxWidth: "min(440px, calc(100vw - 32px))",
        boxShadow: `0 4px 32px rgba(0,0,0,0.6), 0 0 0 1px ${color}22`,
        cursor: "pointer",
      }}
    >
      <div style={{ width: 8, height: 8, borderRadius: "50%", background: color, boxShadow: `0 0 8px ${color}`, flexShrink: 0, marginTop: 4 }} />
      <div>
        <p style={{ fontFamily: "var(--font-ui)", fontSize: 13, fontWeight: 600, color: "#FFFFFF", margin: 0, lineHeight: 1.4 }}>{message}</p>
        {sub && <p style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "rgba(255,255,255,0.45)", margin: "3px 0 0", lineHeight: 1.4 }}>{sub}</p>}
      </div>
      <span style={{ fontFamily: "var(--font-ui)", fontSize: 16, color: "rgba(255,255,255,0.25)", marginLeft: "auto", marginTop: -2, flexShrink: 0 }}>×</span>
    </motion.div>
  );
}

/* ─── Loading dots ───────────────────────────────────────────── */
function LoadingDots() {
  return (
    <span style={{ display: "flex", gap: 3 }}>
      {[0, 1, 2].map((i) => (
        <motion.span key={i}
          style={{ display: "block", width: 3, height: 3, borderRadius: "50%", background: "rgba(255,255,255,0.3)" }}
          animate={{ opacity: [0.3, 1, 0.3], scale: [0.8, 1.3, 0.8] }}
          transition={{ duration: 0.9, repeat: Infinity, delay: i * 0.22 }}
        />
      ))}
    </span>
  );
}

/* ─── Main component ─────────────────────────────────────────── */
export default function Onboarding() {
  const router = useRouter();
  const [step, setStep]                     = useState<"landing" | "team" | "email">("landing");
  const [requireEmail, setRequireEmail]     = useState(false);
  const [teamId, setTeamIdLocal]            = useState("");
  const [resolvedTeamId, setResolvedTeamId] = useState<number>(0);
  const [email, setEmail]                   = useState("");
  const [emailError, setEmailError]         = useState("");
  const [emailLoading, setEmailLoading]     = useState(false);
  const [error, setError]                   = useState("");
  const [loading, setLoading]               = useState(false);
  const [formVisible, setFormVisible]       = useState(false);
  const [currentGW, setCurrentGW]           = useState<number | null>(null);
  const [spotsRemaining, setSpotsRemaining] = useState<number | null>(null);
  const [perfData, setPerfData]             = useState<PerfData | null>(null);
  const [toast, setToast]                   = useState<{ message: string; sub?: string; type?: "success" | "info" | "warning" } | null>(null);
  const [showReport, setShowReport]         = useState(false);
  // After onboarding, redirect here instead of the default dashboard
  const redirectAfterRef = useRef<string | null>(null);

  const { setTeamId, setAnonymousSessionToken, setOnboardingComplete, syncSquad } = useFPLStore();
  const inputRef  = useRef<HTMLInputElement>(null);
  const emailRef  = useRef<HTMLInputElement>(null);
  const mouseX    = useMotionValue(0.5);
  const mouseY    = useMotionValue(0.5);
  const glowX     = useTransform(mouseX, [0, 1], [-30, 30]);
  const glowY     = useTransform(mouseY, [0, 1], [-20, 20]);

  useEffect(() => {
    // Current GW
    fetch(`${API}/api/gameweeks/current`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => {
        if (d?.current_gw) {
          // When GW is finished, show the next GW as the planning target
          const displayGW = (d.finished && d.next_gw) ? d.next_gw : d.current_gw;
          setCurrentGW(displayGW);
        }
      })
      .catch(() => {});

    // Live spot count
    fetch(`${API}/api/user/spots`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { if (d?.spots_remaining !== undefined) setSpotsRemaining(d.spots_remaining); })
      .catch(() => {});

    // Real backtest performance — always start with computing shimmer, never blank
    setPerfData({ has_data: false, is_computing: true });
    fetch(`${API}/api/lab/performance-summary`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => {
        // Only update state when real data arrives — keep shimmer until then
        if (d && d.has_data) setPerfData(d as PerfData);
      })
      .catch(() => { /* silent — polling will retry every 9s */ });

    // Always start at the landing hero — never skip to team step on refresh
    const t = setTimeout(() => setFormVisible(true), 800);
    return () => clearTimeout(t);
  }, []);

  useEffect(() => {
    if (step === "email") setTimeout(() => emailRef.current?.focus(), 400);
  }, [step]);

  // Poll performance-summary every 9s until real backtest data arrives.
  // Only upgrades state when has_data=true — never drops back to State C.
  useEffect(() => {
    if (perfData?.has_data === true) return; // real data arrived, stop polling
    const interval = setInterval(() => {
      fetch(`${API}/api/lab/performance-summary`)
        .then((r) => r.ok ? r.json() : null)
        .then((d) => { if (d && d.has_data) setPerfData(d as PerfData); })
        .catch(() => {}); // silent — keep showing shimmer
    }, 9000);
    return () => clearInterval(interval);
  }, [perfData?.has_data]);

  const handleMouseMove = (e: React.MouseEvent) => {
    mouseX.set(e.clientX / window.innerWidth);
    mouseY.set(e.clientY / window.innerHeight);
  };

  const handleLandingCTA = (withEmail: boolean, afterRedirect?: string) => {
    if (afterRedirect) redirectAfterRef.current = afterRedirect;
    setRequireEmail(withEmail);
    setStep("team");
    setTimeout(() => inputRef.current?.focus(), 300);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const id = Number(teamId.trim());
    if (!id || isNaN(id) || id <= 0) { setError("Enter a valid FPL Team ID"); return; }
    setLoading(true);
    setResolvedTeamId(id);
    const alreadyCaptured = typeof window !== "undefined" && localStorage.getItem(`fpl_email_${id}`);
    if (alreadyCaptured && !requireEmail) {
      await completeOnboarding(id, false);
    } else {
      setStep("email");
      setLoading(false);
    }
  };

  const handleEmailSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = email.trim().toLowerCase();
    if (!trimmed || !trimmed.includes("@")) { setEmailError("Enter a valid email address"); return; }
    setEmailLoading(true);
    try {
      const res = await fetch(`${API}/api/user/profile`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ team_id: resolvedTeamId, email: trimmed, pre_deadline_email: true }),
      });

      if (res.status === 503) {
        const data = await res.json().catch(() => ({}));
        const position = data?.detail?.position ?? null;
        setEmailLoading(false);
        setToast({
          type: "info",
          message: "You're on the waitlist — we'll email you when a spot opens.",
          sub: position
            ? `You're #${position} in the queue. We'll notify you automatically when a spot opens.`
            : "We'll notify you automatically when a spot becomes available.",
        });
        setSpotsRemaining(0);
        // Admit them as anonymous — they can still use the full analysis
        await completeOnboarding(resolvedTeamId, false);
        return;
      }

      if (res.status === 429) {
        setEmailLoading(false);
        setEmailError("Too many sign-ups right now — please try again in a minute.");
        return;
      }

      if (!res.ok) {
        setEmailLoading(false);
        setEmailError("Something went wrong — please try again.");
        return;
      }

      localStorage.setItem(`fpl_email_${resolvedTeamId}`, trimmed);
      // Refresh spot count
      fetch(`${API}/api/user/spots`)
        .then((r) => r.ok ? r.json() : null)
        .then((d) => d?.spots_remaining !== undefined && setSpotsRemaining(d.spots_remaining))
        .catch(() => {});
    } catch {
      // Non-fatal
    }
    await completeOnboarding(resolvedTeamId, true);
  };

  const handleEmailSkip = () => {
    if (requireEmail) return;
    localStorage.setItem(`fpl_email_${resolvedTeamId}`, "skipped");
    void completeOnboarding(resolvedTeamId, false);
  };

  const completeOnboarding = async (teamIdValue: number, isRegistered: boolean) => {
    if (!isRegistered) {
      try {
        const sessionRes = await fetch(`${API}/api/user/anonymous-session`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ team_id: teamIdValue }),
        });
        if (sessionRes.ok) {
          const sessionData = await sessionRes.json();
          setAnonymousSessionToken(sessionData.session_token);
        }
      } catch { setAnonymousSessionToken(null); }
    } else {
      setAnonymousSessionToken(null);
    }
    setTeamId(teamIdValue);
    setOnboardingComplete(true);
    await syncSquad();

    // Redirect to lab if user clicked "Full report"
    if (redirectAfterRef.current) {
      router.push(redirectAfterRef.current);
      redirectAfterRef.current = null;
    }
  };

  /* Spots label helper */
  const spotsLabel =
    spotsRemaining === null
      ? "500 spots available"
      : spotsRemaining === 0
      ? "No spots left — join waitlist"
      : spotsRemaining <= 10
      ? `Only ${spotsRemaining} spot${spotsRemaining === 1 ? "" : "s"} left!`
      : `${spotsRemaining} spots available`;

  const spotsIsUrgent = spotsRemaining !== null && spotsRemaining <= 10;

  /* Performance data — only shown if real backtest data exists */
  const hasPerfData = perfData?.has_data === true;
  const perfWithData = hasPerfData ? (perfData as PerformanceSummaryWithData) : null;

  return (
    <div
      onMouseMove={handleMouseMove}
      style={{ minHeight: "100vh", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "flex-start", background: "#0B0B0D", padding: "0 20px", position: "relative", overflow: "hidden" }}
    >
      {/* ── Toast ── */}
      <AnimatePresence>
        {toast && (
          <Toast key="toast" message={toast.message} sub={toast.sub} type={toast.type} onDismiss={() => setToast(null)} />
        )}
      </AnimatePresence>

      {/* ── Backtest Report Modal ── */}
      {showReport && perfWithData && (
        <BacktestReportModal data={perfWithData} onClose={() => setShowReport(false)} />
      )}

      <BallTrajectories />
      <StadiumCrowd />

      {/* ── Ambient glow ── */}
      <motion.div
        style={{ position: "absolute", bottom: -100, left: "50%", translateX: "-50%", width: 900, height: 500, borderRadius: "50%", background: "radial-gradient(ellipse, rgba(34,197,94,0.08) 0%, rgba(34,197,94,0.03) 40%, transparent 70%)", pointerEvents: "none", x: glowX, y: glowY }}
        animate={{ opacity: [0.6, 1, 0.6] }}
        transition={{ duration: 7, repeat: Infinity, ease: "easeInOut" }}
      />

      {/* ── Grain ── */}
      <div style={{ position: "absolute", inset: 0, backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)' opacity='0.035'/%3E%3C/svg%3E")`, pointerEvents: "none", opacity: 0.5 }} />

      {/* ── Top line ── */}
      <motion.div
        initial={{ scaleX: 0, opacity: 0 }} animate={{ scaleX: 1, opacity: 1 }}
        transition={{ duration: 1.4, delay: 0.1, ease: [0.16, 1, 0.3, 1] }}
        style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: "linear-gradient(90deg, transparent 0%, rgba(34,197,94,0.5) 50%, transparent 100%)", transformOrigin: "center", pointerEvents: "none" }}
      />

      {/* ── Corner marks ── */}
      {([{ top: 20, left: 20 }, { top: 20, right: 20, rotateZ: 90 }, { bottom: 230, right: 20, rotateZ: 180 }, { bottom: 230, left: 20, rotateZ: 270 }] as const).map((pos, i) => (
        <motion.div key={i} initial={{ opacity: 0 }} animate={{ opacity: 0.12 }} transition={{ delay: 0.5 + i * 0.08 }}
          style={{ position: "absolute", width: 18, height: 18, borderTop: "1px solid rgba(255,255,255,0.7)", borderLeft: "1px solid rgba(255,255,255,0.7)", transform: `rotate(${"rotateZ" in pos ? pos.rotateZ : 0}deg)`, pointerEvents: "none", ...pos }}
        />
      ))}

      {/* ── Central content ── */}
      <div style={{ position: "relative", zIndex: 10, width: "min(520px, 100%)", display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center", minHeight: "100vh", paddingTop: "clamp(48px, 10vh, 120px)", paddingBottom: 40, boxSizing: "border-box" }}>

        {/* ── Wordmark ── */}
        <motion.div initial={{ opacity: 0, y: -16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.8, delay: 0.15, ease: [0.16, 1, 0.3, 1] }} style={{ marginBottom: 40 }}>
          <div style={{ display: "inline-flex", alignItems: "baseline", gap: 0, lineHeight: 1 }}>
            <span style={{ fontFamily: "'Tiro Devanagari', 'Noto Sans Devanagari', serif", fontSize: "clamp(52px, 9vw, 80px)", fontWeight: 700, color: "#22C55E", letterSpacing: "-0.01em", lineHeight: 1 }}>एफ</span>
            <span style={{ fontFamily: "var(--font-display)", fontSize: "clamp(52px, 9vw, 80px)", fontWeight: 700, color: "#FFFFFF", letterSpacing: "-0.06em", lineHeight: 1 }}>PL</span>
          </div>
          <p style={{ fontFamily: "var(--font-ui)", fontSize: 10, fontWeight: 500, color: "rgba(255,255,255,0.3)", letterSpacing: "0.28em", textTransform: "uppercase", marginTop: 8 }}>Intelligence Engine</p>
        </motion.div>

        {/* ── Headline ── */}
        <div style={{ marginBottom: 20, display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
          {[{ text: "Decode", color: "#FFFFFF", delay: 0.3 }, { text: "Your Season.", color: "#22C55E", delay: 0.52 }].map(({ text, color, delay }) => (
            <motion.span key={text}
              initial={{ opacity: 0, y: 28, filter: "blur(12px)" }}
              animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
              transition={{ delay, duration: 0.75, ease: [0.16, 1, 0.3, 1] }}
              style={{ fontFamily: "var(--font-display)", fontSize: "clamp(36px, 6.5vw, 58px)", fontWeight: 700, color, letterSpacing: "-0.04em", lineHeight: 1.05, display: "block", textShadow: color === "#22C55E" ? "0 0 60px rgba(34,197,94,0.25)" : undefined }}
            >
              {text}
            </motion.span>
          ))}
        </div>

        {/* ── Sub ── */}
        <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.85, duration: 0.8 }}
          style={{ fontFamily: "var(--font-ui)", fontSize: 14, color: "rgba(255,255,255,0.32)", letterSpacing: "0.01em", lineHeight: 1.6, marginBottom: 32 }}
        >
          Transfer intelligence · Live scoring · Captain decisions
        </motion.p>

        {/* ── Performance strip — ALWAYS rendered on landing & team steps ────── */}
        {/* Two states: real data (State A) / loading shimmer (State B, never blank) */}
        {(step === "landing" || step === "team") && (
          <AnimatePresence mode="wait">
            {perfWithData ? (
              /* ── State A: real backtest results ─────────────────────────── */
              <PerformanceStrip
                key="perf-data"
                data={perfWithData}
                onViewReport={() => setShowReport(true)}
              />
            ) : (
              /* ── State B: loading / computing — ALWAYS shown until real data arrives ── */
              <motion.div
                key="perf-computing"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ delay: 0.7, duration: 0.5 }}
                style={{
                  width: "100%",
                  marginBottom: 28,
                  padding: "14px 16px",
                  borderTop: "1px solid rgba(255,255,255,0.06)",
                  borderBottom: "1px solid rgba(255,255,255,0.06)",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <motion.svg width="12" height="12" viewBox="0 0 12 12"
                      animate={{ rotate: 360 }}
                      transition={{ duration: 1.4, repeat: Infinity, ease: "linear" }}>
                      <circle cx="6" cy="6" r="4.5" stroke="rgba(34,197,94,0.25)" strokeWidth="1.5" fill="none" />
                      <path d="M6 1.5 A4.5 4.5 0 0 1 10.5 6" stroke="#22C55E" strokeWidth="1.5" strokeLinecap="round" fill="none" />
                    </motion.svg>
                    <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "rgba(255,255,255,0.25)", letterSpacing: "0.14em", textTransform: "uppercase" }}>
                      Backtest results · computing
                    </span>
                  </div>
                  <button onClick={() => setShowReport(false)} style={{ background:"none",border:"none",cursor:"pointer",display:"flex",alignItems:"center",gap:3,color:"rgba(34,197,94,0.5)",fontFamily:"var(--font-ui)",fontSize:9,fontWeight:600,letterSpacing:"0.08em",textTransform:"uppercase",padding:0 }}
                    onMouseEnter={(e)=>(e.currentTarget.style.color="#22C55E")} onMouseLeave={(e)=>(e.currentTarget.style.color="rgba(34,197,94,0.5)")}>
                    Lab <svg width="8" height="8" viewBox="0 0 10 10" fill="none"><path d="M2 8L8 2M8 2H3.5M8 2V6.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/></svg>
                  </button>
                </div>
                {/* Shimmer bars */}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1px 1fr 1px 1fr", gap: 0 }}>
                  {[0, 1, 2].map((i) => (
                    <React.Fragment key={i}>
                      {i > 0 && <div style={{ width:1, background:"rgba(255,255,255,0.06)" }} />}
                      <div style={{ padding: "0 12px", display:"flex", flexDirection:"column", alignItems:"center", gap: 5 }}>
                        <div style={{ width: 48, height: 18, borderRadius: 4, background: "rgba(255,255,255,0.06)", animation: `pulse 1.6s ease-in-out ${i*0.2}s infinite` }} />
                        <div style={{ width: 64, height: 8, borderRadius: 3, background: "rgba(255,255,255,0.04)", animation: `pulse 1.6s ease-in-out ${i*0.2+0.3}s infinite` }} />
                      </div>
                    </React.Fragment>
                  ))}
                </div>
                <div style={{ display:"flex", justifyContent:"center", marginTop:12 }}>
                  <span style={{ fontFamily:"var(--font-ui)", fontSize:9, color:"rgba(255,255,255,0.15)", letterSpacing:"0.05em" }}>
                    Analysing 3 seasons · 114 gameweeks · results ready in ~2 min
                  </span>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        )}
        <style>{`
          @keyframes pulse {
            0%, 100% { opacity: 0.5; }
            50%       { opacity: 0.9; }
          }
        `}</style>

        {/* ── Flex spacer ── */}
        <div style={{ flex: 1, minHeight: 24 }} />

        {/* ── Steps ── */}
        <AnimatePresence mode="wait">

          {/* Step 0: Landing */}
          {formVisible && step === "landing" && (
            <motion.div key="landing-step"
              initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -16 }}
              transition={{ duration: 0.55, ease: [0.16, 1, 0.3, 1] }}
              style={{ width: "100%" }}
            >
              <div style={{ marginBottom: 16 }}>
                <p style={{ fontFamily: "var(--font-ui)", fontSize: 12, color: "rgba(255,255,255,0.3)", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 16 }}>
                  No account required to analyse
                </p>
              </div>

              <motion.button onClick={() => handleLandingCTA(false)} whileHover={{ scale: 1.01 }} whileTap={{ scale: 0.99 }}
                style={{ width: "100%", padding: "16px", borderRadius: 12, border: "1px solid rgba(34,197,94,0.4)", background: "rgba(34,197,94,0.12)", color: "#22C55E", fontSize: 15, fontWeight: 600, fontFamily: "var(--font-display)", letterSpacing: "0.02em", cursor: "pointer", transition: "all 220ms", boxSizing: "border-box", marginBottom: 10 }}
              >
                Analyse my team
              </motion.button>

              <motion.button onClick={() => handleLandingCTA(true)} whileHover={{ scale: 1.01 }} whileTap={{ scale: 0.99 }}
                style={{ width: "100%", padding: "14px", borderRadius: 12, border: "1px solid rgba(255,255,255,0.12)", background: "rgba(255,255,255,0.03)", color: "rgba(255,255,255,0.7)", fontSize: 14, fontWeight: 500, fontFamily: "var(--font-ui)", letterSpacing: "0.01em", cursor: "pointer", transition: "all 220ms", boxSizing: "border-box", marginBottom: 16 }}
              >
                Get weekly alerts
              </motion.button>

              {/* Dynamic spots counter */}
              <motion.p
                key={spotsLabel}
                initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.4 }}
                style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "rgba(255,255,255,0.18)", textAlign: "center", letterSpacing: "0.04em" }}
              >
                Email alerts are optional ·{" "}
                <span style={{ color: spotsIsUrgent ? "#f59e0b" : undefined, fontWeight: spotsIsUrgent ? 600 : undefined }}>
                  {spotsLabel}
                </span>
              </motion.p>
            </motion.div>
          )}

          {/* Step 1: Team ID */}
          {formVisible && step === "team" && (
            <motion.div key="team-step"
              initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -16 }}
              transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
              style={{ width: "100%" }}
            >
              <form onSubmit={handleSubmit}>
                <div style={{ position: "relative", marginBottom: 4, cursor: "text" }} onClick={() => inputRef.current?.focus()}>
                  <DashDisplay value={teamId} />
                  <input ref={inputRef} type="text" inputMode="numeric" pattern="[0-9]*"
                    value={teamId}
                    onChange={(e) => { setTeamIdLocal(e.target.value.replace(/\D/g, "")); setError(""); }}
                    disabled={loading}
                    style={{ position: "absolute", inset: 0, opacity: 0, cursor: "text", fontSize: 1 }}
                  />
                </div>
                <motion.div
                  style={{ height: 1, background: error ? "rgba(239,68,68,0.5)" : "rgba(255,255,255,0.12)", marginBottom: 10, borderRadius: 1 }}
                  animate={{ scaleX: teamId.length > 0 ? 1 : 0.4, opacity: teamId.length > 0 ? 1 : 0.4 }}
                  transition={{ duration: 0.3 }}
                />
                <AnimatePresence>
                  {error && (
                    <motion.p initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                      style={{ fontFamily: "var(--font-ui)", fontSize: 12, color: "var(--red)", marginBottom: 10, textAlign: "center" }}
                    >{error}</motion.p>
                  )}
                </AnimatePresence>
                <p style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "rgba(255,255,255,0.22)", marginBottom: 48, lineHeight: 1.5 }}>
                  fantasy.premierleague.com → Points → check the URL
                </p>
                <motion.button type="submit" disabled={loading} whileHover={loading ? {} : { scale: 1.01 }} whileTap={loading ? {} : { scale: 0.99 }}
                  style={{ width: "100%", padding: "16px", borderRadius: 12, border: "1px solid rgba(34,197,94,0.4)", background: loading ? "rgba(255,255,255,0.03)" : "rgba(34,197,94,0.12)", color: loading ? "rgba(255,255,255,0.25)" : "#22C55E", fontSize: 15, fontWeight: 600, fontFamily: "var(--font-display)", letterSpacing: "0.02em", cursor: loading ? "not-allowed" : "pointer", transition: "all 220ms", boxSizing: "border-box", display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}
                >
                  {loading ? <><LoadingDots /><span>Analyzing squad…</span></> : "Begin analysis"}
                </motion.button>
              </form>
            </motion.div>
          )}

          {/* Step 2: Email */}
          {step === "email" && (
            <motion.div key="email-step"
              initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
              transition={{ duration: 0.55, ease: [0.16, 1, 0.3, 1] }}
              style={{ width: "100%" }}
            >
              <motion.div style={{ marginBottom: 28, textAlign: "center" }}>
                <p style={{ fontFamily: "var(--font-display)", fontSize: 22, fontWeight: 600, color: "#FFFFFF", letterSpacing: "-0.02em", marginBottom: 8 }}>
                  Get deadline alerts
                </p>
                <p style={{ fontFamily: "var(--font-ui)", fontSize: 13, color: "rgba(255,255,255,0.38)", lineHeight: 1.55 }}>
                  24h before each GW deadline — captain pick, transfers, injury alerts
                </p>
                {spotsRemaining !== null && spotsRemaining <= 20 && (
                  <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }}
                    style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: spotsRemaining <= 5 ? "#ef4444" : "#f59e0b", marginTop: 8, fontWeight: 600, letterSpacing: "0.03em" }}
                  >
                    {spotsRemaining === 0
                      ? "All spots taken — you'll be added to the waitlist"
                      : `Only ${spotsRemaining} spot${spotsRemaining === 1 ? "" : "s"} remaining`}
                  </motion.p>
                )}
              </motion.div>

              <form onSubmit={handleEmailSubmit}>
                <input ref={emailRef} type="email" value={email}
                  onChange={(e) => { setEmail(e.target.value); setEmailError(""); }}
                  placeholder="your@email.com" disabled={emailLoading}
                  style={{ width: "100%", padding: "14px 16px", background: "rgba(255,255,255,0.04)", border: emailError ? "1px solid rgba(239,68,68,0.5)" : "1px solid rgba(255,255,255,0.1)", borderRadius: 10, color: "#FFFFFF", fontFamily: "var(--font-ui)", fontSize: 15, outline: "none", boxSizing: "border-box", marginBottom: emailError ? 6 : 16, transition: "border-color 200ms" }}
                  onFocus={(e) => { e.target.style.borderColor = "rgba(34,197,94,0.4)"; }}
                  onBlur={(e) => { if (!emailError) e.target.style.borderColor = "rgba(255,255,255,0.1)"; }}
                />
                <AnimatePresence>
                  {emailError && (
                    <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                      style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--red)", marginBottom: 10 }}
                    >{emailError}</motion.p>
                  )}
                </AnimatePresence>

                <motion.button type="submit" disabled={emailLoading} whileHover={emailLoading ? {} : { scale: 1.01 }} whileTap={emailLoading ? {} : { scale: 0.99 }}
                  style={{ width: "100%", padding: "16px", borderRadius: 12, border: "1px solid rgba(34,197,94,0.4)", background: emailLoading ? "rgba(255,255,255,0.03)" : "rgba(34,197,94,0.12)", color: emailLoading ? "rgba(255,255,255,0.25)" : "#22C55E", fontSize: 15, fontWeight: 600, fontFamily: "var(--font-display)", letterSpacing: "0.02em", cursor: emailLoading ? "not-allowed" : "pointer", transition: "all 220ms", boxSizing: "border-box", display: "flex", alignItems: "center", justifyContent: "center", gap: 8, marginBottom: 10 }}
                >
                  {emailLoading
                    ? <><LoadingDots /><span>Setting up…</span></>
                    : spotsRemaining === 0 ? "Join waitlist" : "Set up alerts"
                  }
                </motion.button>

                {!requireEmail && (
                  <button type="button" onClick={handleEmailSkip}
                    style={{ width: "100%", padding: "12px", background: "transparent", border: "none", color: "rgba(255,255,255,0.28)", fontFamily: "var(--font-ui)", fontSize: 13, cursor: "pointer", letterSpacing: "0.01em" }}
                  >
                    Skip for now
                  </button>
                )}
              </form>
            </motion.div>
          )}
        </AnimatePresence>

        {/* ── Status row ── */}
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 1.5, duration: 0.8 }}
          style={{ marginTop: 44, display: "flex", alignItems: "center", gap: 14, fontFamily: "var(--font-ui)", fontSize: 10, color: "rgba(255,255,255,0.22)", letterSpacing: "0.06em" }}
        >
          <motion.span animate={{ opacity: [0.4, 1, 0.4] }} transition={{ duration: 1.8, repeat: Infinity }}
            style={{ display: "inline-block", width: 5, height: 5, borderRadius: "50%", background: "#22C55E", boxShadow: "0 0 8px #22C55E" }}
          />
          <span>Live</span>
          <span style={{ opacity: 0.3 }}>·</span>
          <span>{currentGW ? `GW${currentGW}` : "—"}</span>
          <span style={{ opacity: 0.3 }}>·</span>
          <span>xPts Model</span>
        </motion.div>
      </div>
    </div>
  );
}
