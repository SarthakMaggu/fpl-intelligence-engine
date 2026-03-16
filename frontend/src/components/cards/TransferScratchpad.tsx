"use client";
import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { CheckCircle2, AlertTriangle, Cpu, Info, ArrowRightLeft } from "lucide-react";
import type { TransferSuggestion, OptimalSquad, BenchSwap } from "@/types/fpl";
import type { BenchStrategy } from "@/store/fpl.store";

interface Props {
  suggestions: TransferSuggestion[];
  freeTransfers: number;
  bankMillions: number;
  optimalSquad?: OptimalSquad | null;
  benchStrategies?: BenchStrategy[];
}

function Divider() {
  return <div style={{ height: 1, background: "var(--divider)", margin: "14px 0" }} />;
}

const REC_CONFIG = {
  MAKE:     { color: "var(--green)",  bg: "rgba(34,197,94,0.08)",   border: "rgba(34,197,94,0.25)",   label: "MAKE IT"  },
  CONSIDER: { color: "var(--amber)",  bg: "rgba(245,158,11,0.08)",  border: "rgba(245,158,11,0.25)",  label: "CONSIDER" },
  HOLD:     { color: "var(--text-3)", bg: "rgba(255,255,255,0.04)", border: "var(--divider)",          label: "HOLD"     },
} as const;

const POS_LABEL: Record<number, string> = { 1: "GK", 2: "DEF", 3: "MID", 4: "FWD" };

export default function TransferScratchpad({ suggestions, freeTransfers, bankMillions, optimalSquad, benchStrategies = [] }: Props) {
  const top = suggestions.slice(0, 2);
  const [showIlpInfo, setShowIlpInfo] = useState(false);

  const ftColor = freeTransfers >= 3 ? "var(--green)" : freeTransfers === 2 ? "var(--amber)" : "var(--text-3)";

  // Pair ILP transfers_out with transfers_in by index (real squad changes)
  const ilpMoves = optimalSquad
    ? optimalSquad.transfers_out.map((out, i) => ({
        out,
        inn: optimalSquad.transfers_in[i] ?? null,
      })).filter(m => m.inn)
    : [];

  // Free bench↔XI swaps (no transfer cost)
  const benchSwaps: BenchSwap[] = optimalSquad?.bench_swaps ?? [];

  return (
    <motion.div
      initial={{ opacity: 0, x: 24 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ type: "spring", stiffness: 240, damping: 26, delay: 0.15 }}
      className="glass"
      style={{ borderRadius: 16, overflow: "hidden", position: "relative" }}
    >
      {/* Ambient glow — top left */}
      <div
        style={{
          position: "absolute",
          top: -60,
          left: -60,
          width: 160,
          height: 160,
          borderRadius: "50%",
          background: "radial-gradient(circle, rgba(59,130,246,0.05) 0%, transparent 70%)",
          pointerEvents: "none",
        }}
      />

      {/* ── Header ──────────────────────────────────────────────── */}
      <div
        style={{
          padding: "16px 18px 14px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          borderBottom: "1px solid var(--divider)",
          position: "relative",
          zIndex: 1,
        }}
      >
        <span
          style={{
            fontFamily: "var(--font-display)",
            fontSize: 18,
            fontWeight: 600,
            color: "var(--text-1)",
            letterSpacing: "-0.03em",
          }}
        >
          Transfers
        </span>

        <div style={{ display: "flex", gap: 6 }}>
          <span
            className="badge"
            style={{
              fontSize: 11,
              color: ftColor,
              background: freeTransfers >= 2 ? "rgba(34,197,94,0.08)" : "rgba(255,255,255,0.04)",
              border: `1px solid ${freeTransfers >= 2 ? "rgba(34,197,94,0.25)" : "var(--divider)"}`,
              fontFamily: "var(--font-data)",
            }}
          >
            {freeTransfers} FT
          </span>
          <span className="badge badge-muted" style={{ fontSize: 11, fontFamily: "var(--font-data)" }}>
            £{bankMillions.toFixed(1)}m
          </span>
        </div>
      </div>

      {/* ── Body ────────────────────────────────────────────────── */}
      <div style={{ padding: "14px 18px 18px", position: "relative", zIndex: 1 }}>

        {/* ── Greedy suggestions ──────────────────────────────── */}
        {top.length === 0 && !optimalSquad && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            style={{ textAlign: "center", padding: "24px 0", fontFamily: "var(--font-ui)" }}
          >
            <CheckCircle2 size={22} style={{ color: "var(--green)", margin: "0 auto 10px", display: "block" }} />
            <div
              style={{
                fontFamily: "var(--font-display)",
                fontSize: 14,
                fontWeight: 600,
                color: "var(--text-2)",
                letterSpacing: "-0.01em",
              }}
            >
              Squad looks solid
            </div>
            <div style={{ fontSize: 11, color: "var(--text-3)", marginTop: 3 }}>
              No transfers recommended
            </div>
          </motion.div>
        )}

        <AnimatePresence>
          {top.map((s, i) => {
            const rec = REC_CONFIG[s.recommendation as keyof typeof REC_CONFIG] ?? REC_CONFIG.HOLD;
            const gainVal = s.xpts_gain_3gw ?? 0;
            const gainColor =
              gainVal >= 2   ? "var(--green)" :
              gainVal >= 0.5 ? "var(--amber)" :
                               "var(--text-3)";
            const confPct = Math.min(100, Math.max(0, (gainVal / 5) * 100));

            return (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.12 + 0.3, type: "spring", stiffness: 300, damping: 26 }}
              >
                {/* Recommendation label + gain */}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                    <span
                      style={{
                        fontFamily: "var(--font-display)",
                        fontSize: 11,
                        fontWeight: 700,
                        color: rec.color,
                        letterSpacing: "0.06em",
                      }}
                    >
                      {rec.label}
                    </span>
                    {s.confidence_score != null && (
                      <span className="badge badge-muted" style={{ fontSize: 9 }}>
                        {s.confidence_score}% conf
                      </span>
                    )}
                    {s.risk_profile && (
                      <span className="badge badge-muted" style={{ fontSize: 9 }}>
                        {s.risk_profile.replace(/_/g, " ")}
                      </span>
                    )}
                    {s.differential_signal && (
                      <span className="badge badge-amber" style={{ fontSize: 9 }}>
                        differential
                      </span>
                    )}
                  </div>
                  <span
                    style={{
                      fontFamily: "var(--font-data)",
                      fontSize: 18,
                      fontWeight: 600,
                      color: gainColor,
                      letterSpacing: "-0.03em",
                    }}
                  >
                    +{gainVal.toFixed(1)} xP
                  </span>
                </div>

                {/* Confidence bar */}
                <div className="confidence-bar" style={{ marginBottom: 12 }}>
                  <div
                    style={{
                      height: "100%",
                      width: `${confPct}%`,
                      background: rec.color,
                      borderRadius: 2,
                      transition: "width 600ms var(--ease-out)",
                    }}
                  />
                </div>

                {/* OUT → IN */}
                <div style={{ display: "flex", alignItems: "stretch", gap: 8, marginBottom: 8 }}>
                  {/* OUT */}
                  <PlayerCell
                    label="out"
                    name={s.player_out_name}
                    xpts={s.player_out_xpts}
                    news={s.player_out_news}
                    teamCode={s.player_out_team_code}
                    teamName={s.player_out_team_name}
                    accent="red"
                  />

                  <div style={{ display: "flex", alignItems: "center" }}>
                    <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                      <path d="M2 6h8M7 3l3 3-3 3" stroke="var(--text-3)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </div>

                  {/* IN */}
                  <PlayerCell
                    label="in"
                    name={s.player_in_name}
                    xpts={s.player_in_xpts}
                    news={s.player_in_news}
                    teamCode={s.player_in_team_code}
                    teamName={s.player_in_team_name}
                    accent="green"
                  />
                </div>

                {s.transfer_cost > 0 && (
                  <div style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--red)", marginBottom: 4 }}>
                    −{s.transfer_cost}pt hit
                  </div>
                )}

                {(s.explanation_summary || s.reasoning) && (
                  <div style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-3)", lineHeight: 1.5 }}>
                    {s.explanation_summary || s.reasoning}
                  </div>
                )}

                {i < top.length - 1 && <Divider />}
              </motion.div>
            );
          })}
        </AnimatePresence>

        {/* ── Bench → Transfer → XI Strategies ────────────────── */}
        {benchStrategies.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.4, type: "spring", stiffness: 260, damping: 28 }}
          >
            {top.length > 0 && <Divider />}

            {/* Section header */}
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 10 }}>
              <ArrowRightLeft size={12} style={{ color: "var(--amber)" }} />
              <span
                style={{
                  fontFamily: "var(--font-display)",
                  fontSize: 11,
                  fontWeight: 700,
                  color: "var(--amber)",
                  letterSpacing: "0.06em",
                }}
              >
                BENCH STRATEGY
              </span>
              <span
                style={{
                  fontFamily: "var(--font-ui)",
                  fontSize: 10,
                  color: "var(--text-3)",
                  marginLeft: 2,
                }}
              >
                sell bench · buy XI upgrade
              </span>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {benchStrategies.map((s, i) => (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: 0.45 + i * 0.08, type: "spring", stiffness: 340, damping: 28 }}
                  style={{
                    background: "rgba(245,158,11,0.04)",
                    border: "1px solid rgba(245,158,11,0.15)",
                    borderRadius: 10,
                    padding: "10px 11px",
                  }}
                >
                  {/* Three-way chain: SELL bench → BUY new → SWAP XI out */}
                  <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: 7 }}>
                    {/* Sell bench player */}
                    <BenchChip
                      label="SELL"
                      name={s.bench_out.web_name}
                      xpts={s.bench_out.predicted_xpts_next}
                      teamCode={s.bench_out.team_code}
                      accent="red"
                    />

                    <svg width="10" height="10" viewBox="0 0 12 12" fill="none" style={{ flexShrink: 0 }}>
                      <path d="M2 6h8M7 3l3 3-3 3" stroke="var(--text-3)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>

                    {/* Buy new player */}
                    <BenchChip
                      label="BUY"
                      name={s.transfer_in.web_name}
                      xpts={s.transfer_in.predicted_xpts_next}
                      teamCode={s.transfer_in.team_code}
                      accent="green"
                    />

                    <svg width="10" height="10" viewBox="0 0 12 12" fill="none" style={{ flexShrink: 0 }}>
                      <path d="M2 6h8M7 3l3 3-3 3" stroke="var(--text-3)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>

                    {/* XI player moved to bench */}
                    <BenchChip
                      label="→BENCH"
                      name={s.xi_swap_out.web_name}
                      xpts={s.xi_swap_out.predicted_xpts_next}
                      teamCode={s.xi_swap_out.team_code}
                      accent="neutral"
                    />
                  </div>

                  {/* Stats row */}
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <span
                        style={{
                          fontFamily: "var(--font-data)",
                          fontSize: 13,
                          fontWeight: 600,
                          color: "var(--amber)",
                          letterSpacing: "-0.02em",
                        }}
                      >
                        +{s.xi_gain.toFixed(1)} xP
                      </span>
                      <span style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-3)" }}>
                        XI gain
                      </span>
                    </div>
                    <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                      <span
                        style={{
                          fontFamily: "var(--font-data)",
                          fontSize: 10,
                          color: "var(--text-3)",
                        }}
                      >
                        £{s.cost_millions.toFixed(1)}m cost
                      </span>
                      {s.hit_cost_pts > 0 && (
                        <span
                          className="badge"
                          style={{
                            fontSize: 9,
                            color: "var(--red)",
                            background: "rgba(239,68,68,0.08)",
                            border: "1px solid rgba(239,68,68,0.2)",
                            fontFamily: "var(--font-data)",
                          }}
                        >
                          −{s.hit_cost_pts}pt hit
                        </span>
                      )}
                      {s.hit_cost_pts === 0 && (
                        <span
                          className="badge"
                          style={{
                            fontSize: 9,
                            color: "var(--green)",
                            background: "rgba(34,197,94,0.06)",
                            border: "1px solid rgba(34,197,94,0.18)",
                            fontFamily: "var(--font-data)",
                          }}
                        >
                          Free
                        </span>
                      )}
                    </div>
                  </div>
                </motion.div>
              ))}
            </div>
          </motion.div>
        )}

        {/* ── ILP Optimal Plan ─────────────────────────────────── */}
        {optimalSquad && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.5, type: "spring", stiffness: 260, damping: 28 }}
          >
            {top.length > 0 && <Divider />}

            {/* ILP section header */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: 12,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <Cpu size={13} style={{ color: "var(--blue)" }} />
                <span
                  style={{
                    fontFamily: "var(--font-display)",
                    fontSize: 11,
                    fontWeight: 700,
                    color: "var(--blue)",
                    letterSpacing: "0.06em",
                  }}
                >
                  ILP OPTIMAL
                </span>
                <button
                  onClick={() => setShowIlpInfo(v => !v)}
                  style={{
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    padding: 0,
                    display: "flex",
                    alignItems: "center",
                    color: showIlpInfo ? "var(--blue)" : "var(--text-3)",
                  }}
                  title="What is ILP Optimal?"
                >
                  <Info size={12} />
                </button>
              </div>
              <div style={{ display: "flex", gap: 5, alignItems: "center" }}>
                <span
                  style={{
                    fontFamily: "var(--font-data)",
                    fontSize: 12,
                    color: "var(--text-2)",
                    letterSpacing: "-0.02em",
                  }}
                >
                  {optimalSquad.total_xpts.toFixed(1)} xP
                </span>
                {optimalSquad.point_deduction > 0 ? (
                  <span
                    className="badge"
                    style={{
                      fontSize: 10,
                      color: "var(--red)",
                      background: "rgba(239,68,68,0.08)",
                      border: "1px solid rgba(239,68,68,0.22)",
                      fontFamily: "var(--font-data)",
                    }}
                  >
                    −{optimalSquad.point_deduction}pt
                  </span>
                ) : (
                  <span
                    className="badge"
                    style={{
                      fontSize: 10,
                      color: "var(--green)",
                      background: "rgba(34,197,94,0.08)",
                      border: "1px solid rgba(34,197,94,0.22)",
                      fontFamily: "var(--font-data)",
                    }}
                  >
                    No hit
                  </span>
                )}
              </div>
            </div>

            {/* ILP info panel */}
            <AnimatePresence>
              {showIlpInfo && (
                <motion.div
                  key="ilp-info"
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.22, ease: "easeInOut" }}
                  style={{ overflow: "hidden", marginBottom: 10 }}
                >
                  <div
                    style={{
                      padding: "10px 12px",
                      background: "rgba(59,130,246,0.06)",
                      border: "1px solid rgba(59,130,246,0.18)",
                      borderRadius: 10,
                      fontFamily: "var(--font-ui)",
                      fontSize: 11,
                      color: "var(--text-2)",
                      lineHeight: 1.6,
                    }}
                  >
                    <div style={{ fontWeight: 600, color: "var(--blue)", marginBottom: 5, letterSpacing: "0.02em" }}>
                      Integer Linear Programming
                    </div>
                    ILP treats the transfer problem as a maths optimisation. It maximises{" "}
                    <span style={{ color: "var(--text-1)", fontFamily: "var(--font-data)", fontSize: 10 }}>
                      Σ xPts × xi
                    </span>{" "}
                    for your starting XI subject to constraints: budget, formation (3-5-2 etc.), position limits, and
                    transfer cost penalties. Unlike greedy (best single swap), ILP evaluates{" "}
                    <em>all possible combinations at once</em> and returns the globally optimal squad — the one that
                    scores the most expected points next GW, net of any hit.
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* ILP transfer rows — empty state when squad is already optimal */}
            {ilpMoves.length === 0 && benchSwaps.length === 0 && (
              <div
                style={{
                  padding: "10px 12px",
                  background: "rgba(34,197,94,0.04)",
                  border: "1px solid rgba(34,197,94,0.15)",
                  borderRadius: 10,
                  fontFamily: "var(--font-ui)",
                  fontSize: 11,
                  color: "var(--text-2)",
                  marginBottom: 8,
                }}
              >
                ✓ Squad is already optimal — no changes needed
              </div>
            )}
            {/* Real transfers (sell/buy with possible hit cost) */}
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {ilpMoves.map(({ out, inn }, i) => (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: 0.55 + i * 0.07, type: "spring", stiffness: 340, damping: 28 }}
                  style={{ display: "flex", flexDirection: "column", gap: 5 }}
                >
                  {/* Main transfer row: OUT → IN */}
                  <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                    {/* OUT — with bench tag if it's a bench player being sold */}
                    <ILPPlayerChip
                      name={out.web_name}
                      pos={out.element_type}
                      xpts={out.predicted_xpts_next}
                      teamCode={out.team_code}
                      accent="red"
                      isBench={out.is_bench_player}
                    />

                    <svg width="10" height="10" viewBox="0 0 12 12" fill="none" style={{ flexShrink: 0 }}>
                      <path d="M2 6h8M7 3l3 3-3 3" stroke="var(--text-3)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>

                    {/* IN — show XI/bench placement route */}
                    <ILPPlayerChip
                      name={inn!.web_name}
                      pos={inn!.element_type}
                      xpts={inn!.predicted_xpts_next}
                      teamCode={inn!.team_code}
                      accent="green"
                      routeLabel={inn!.is_xi_player === false ? "bench" : "XI"}
                    />
                  </div>

                  {/* Displacement chain: if incoming player goes to XI and displaces a starter */}
                  {inn!.displaces && (
                    <div style={{ display: "flex", alignItems: "center", gap: 5, paddingLeft: 16 }}>
                      <div style={{
                        width: 1, height: 14, background: "var(--divider)",
                        marginRight: 2, flexShrink: 0,
                      }} />
                      <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)", flexShrink: 0 }}>
                        displaces
                      </span>
                      <ILPPlayerChip
                        name={inn!.displaces.web_name}
                        pos={inn!.displaces.element_type}
                        xpts={inn!.displaces.predicted_xpts_next}
                        teamCode={inn!.displaces.team_code}
                        accent="red"
                        label="→ bench"
                      />
                    </div>
                  )}
                </motion.div>
              ))}
            </div>

            {/* Free bench↔XI swaps (no transfer cost) */}
            {benchSwaps.length > 0 && (
              <motion.div
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.6, type: "spring", stiffness: 300, damping: 28 }}
                style={{ marginTop: ilpMoves.length > 0 ? 10 : 0 }}
              >
                {/* Sub-header */}
                <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: 7 }}>
                  <ArrowRightLeft size={11} style={{ color: "var(--green)" }} />
                  <span
                    style={{
                      fontFamily: "var(--font-display)",
                      fontSize: 10,
                      fontWeight: 700,
                      color: "var(--green)",
                      letterSpacing: "0.06em",
                    }}
                  >
                    FREE SWAPS
                  </span>
                  <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)" }}>
                    no transfer cost
                  </span>
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {benchSwaps.map((swap, i) => (
                    <motion.div
                      key={i}
                      initial={{ opacity: 0, x: -4 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: 0.62 + i * 0.06, type: "spring", stiffness: 340, damping: 28 }}
                      style={{ display: "flex", alignItems: "center", gap: 7 }}
                    >
                      {/* Bench player moving into XI */}
                      <ILPPlayerChip
                        name={swap.from_bench.web_name}
                        pos={swap.from_bench.element_type}
                        xpts={swap.from_bench.predicted_xpts_next}
                        teamCode={swap.from_bench.team_code}
                        accent="green"
                        label="↑ XI"
                      />

                      {/* Swap arrows (bidirectional) */}
                      <svg width="12" height="12" viewBox="0 0 14 14" fill="none" style={{ flexShrink: 0 }}>
                        <path d="M2 4h10M9 2l3 2-3 2M12 10H2M5 8l-3 2 3 2" stroke="var(--green)" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>

                      {/* XI player moving to bench */}
                      <ILPPlayerChip
                        name={swap.to_bench.web_name}
                        pos={swap.to_bench.element_type}
                        xpts={swap.to_bench.predicted_xpts_next}
                        teamCode={swap.to_bench.team_code}
                        accent="red"
                        label="→ bench"
                      />
                    </motion.div>
                  ))}
                </div>
              </motion.div>
            )}

            {/* Captain recommendation */}
            {optimalSquad.captain && (
              <div
                style={{
                  marginTop: 10,
                  padding: "7px 10px",
                  background: "rgba(245,158,11,0.07)",
                  border: "1px solid rgba(245,158,11,0.18)",
                  borderRadius: 8,
                  display: "flex",
                  alignItems: "center",
                  gap: 7,
                }}
              >
                <span
                  style={{
                    fontFamily: "var(--font-display)",
                    fontSize: 10,
                    fontWeight: 700,
                    color: "var(--amber)",
                    letterSpacing: "0.08em",
                  }}
                >
                  C
                </span>
                <span
                  style={{
                    fontFamily: "var(--font-ui)",
                    fontSize: 12,
                    color: "var(--text-2)",
                  }}
                >
                  {optimalSquad.captain.web_name}
                </span>
                <span
                  style={{
                    fontFamily: "var(--font-data)",
                    fontSize: 11,
                    color: "var(--amber)",
                    marginLeft: "auto",
                  }}
                >
                  {(optimalSquad.captain.predicted_xpts_next ?? 0).toFixed(1)} xP
                </span>
              </div>
            )}

            <div
              style={{
                marginTop: 8,
                fontFamily: "var(--font-ui)",
                fontSize: 10,
                color: "var(--text-3)",
                lineHeight: 1.5,
              }}
            >
              {ilpMoves.length === 0
                ? `ILP optimal — ${optimalSquad.formation} · squad looks good, check bench swaps in Strategy`
                : `Globally optimal via ILP — ${optimalSquad.formation} · ${optimalSquad.transfers_needed} transfer${optimalSquad.transfers_needed !== 1 ? "s" : ""}`
              }
            </div>
          </motion.div>
        )}
      </div>
    </motion.div>
  );
}

/* ── Sub-components ─────────────────────────────────────────────────────── */

function PlayerCell({
  label,
  name,
  xpts,
  news,
  accent,
  teamCode,
  teamName,
}: {
  label: string;
  name: string;
  xpts: number;
  news?: string | null;
  accent: "red" | "green";
  teamCode?: number | null;
  teamName?: string | null;
}) {
  const clr = accent === "red" ? "var(--red)" : "var(--green)";
  const bg = accent === "red" ? "rgba(239,68,68,0.06)" : "rgba(34,197,94,0.06)";
  const border = accent === "red" ? "rgba(239,68,68,0.18)" : "rgba(34,197,94,0.18)";

  return (
    <div
      style={{
        flex: 1,
        background: bg,
        border: `1px solid ${border}`,
        borderRadius: 10,
        padding: "10px 11px",
      }}
    >
      {/* Label row */}
      <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: 5 }}>
        <p style={{ fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 600, color: clr, letterSpacing: "0.1em", textTransform: "uppercase", margin: 0 }}>
          {label}
        </p>
        {teamCode && (
          <img
            src={`https://resources.premierleague.com/premierleague/badges/25/t${teamCode}.png`}
            alt={teamName ?? ""}
            width={13} height={13}
            style={{ objectFit: "contain", opacity: 0.75, flexShrink: 0 }}
            onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
          />
        )}
        {teamName && (
          <span style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--text-3)", letterSpacing: "0.05em", textTransform: "uppercase" }}>
            {teamName}
          </span>
        )}
      </div>
      <div
        style={{
          fontFamily: "var(--font-display)",
          fontSize: 16,
          fontWeight: 600,
          color: "var(--text-1)",
          lineHeight: 1.1,
          letterSpacing: "-0.02em",
          marginBottom: news ? 3 : 4,
        }}
      >
        {name}
      </div>

      {/* News alert badge */}
      {news && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 4,
            marginBottom: 3,
          }}
        >
          <AlertTriangle size={9} style={{ color: "var(--amber)", flexShrink: 0 }} />
          <span
            style={{
              fontFamily: "var(--font-ui)",
              fontSize: 9,
              color: "var(--amber)",
              lineHeight: 1.3,
              overflow: "hidden",
              display: "-webkit-box",
              WebkitLineClamp: 1,
              WebkitBoxOrient: "vertical" as const,
            }}
          >
            {news}
          </span>
        </div>
      )}

      <div
        style={{
          fontFamily: "var(--font-data)",
          fontSize: 11,
          color: accent === "green" ? "var(--green)" : "var(--text-3)",
          letterSpacing: "-0.02em",
        }}
      >
        {xpts.toFixed(1)} xP
      </div>
    </div>
  );
}

function BenchChip({
  label,
  name,
  xpts,
  teamCode,
  accent,
}: {
  label: string;
  name: string;
  xpts: number;
  teamCode?: number | null;
  accent: "red" | "green" | "neutral";
}) {
  const clr = accent === "red" ? "var(--red)" : accent === "green" ? "var(--green)" : "var(--text-3)";
  const bg = accent === "red" ? "rgba(239,68,68,0.05)" : accent === "green" ? "rgba(34,197,94,0.05)" : "rgba(255,255,255,0.03)";
  const border = accent === "red" ? "rgba(239,68,68,0.15)" : accent === "green" ? "rgba(34,197,94,0.15)" : "rgba(255,255,255,0.08)";

  return (
    <div
      style={{
        flex: 1,
        background: bg,
        border: `1px solid ${border}`,
        borderRadius: 7,
        padding: "5px 7px",
        minWidth: 0,
      }}
    >
      <div
        style={{
          fontFamily: "var(--font-ui)",
          fontSize: 8,
          fontWeight: 700,
          color: clr,
          letterSpacing: "0.08em",
          textTransform: "uppercase" as const,
          marginBottom: 2,
          display: "flex",
          alignItems: "center",
          gap: 3,
        }}
      >
        {label}
        {teamCode && (
          <img
            src={`https://resources.premierleague.com/premierleague/badges/25/t${teamCode}.png`}
            alt=""
            width={10} height={10}
            style={{ objectFit: "contain", opacity: 0.7 }}
            onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
          />
        )}
      </div>
      <div
        style={{
          fontFamily: "var(--font-display)",
          fontSize: 11,
          fontWeight: 600,
          color: "var(--text-1)",
          letterSpacing: "-0.02em",
          overflow: "hidden",
          whiteSpace: "nowrap" as const,
          textOverflow: "ellipsis",
        }}
      >
        {name}
      </div>
      <div
        style={{
          fontFamily: "var(--font-data)",
          fontSize: 9,
          color: "var(--text-3)",
          marginTop: 1,
        }}
      >
        {xpts.toFixed(1)} xP
      </div>
    </div>
  );
}

function ILPPlayerChip({
  name,
  pos,
  xpts,
  accent,
  teamCode,
  isBench,
  label,
  routeLabel,
}: {
  name: string;
  pos: number;
  xpts: number | null;
  accent: "red" | "green";
  teamCode?: number | null;
  /** Whether this player was on the bench (adds a bench tag) */
  isBench?: boolean;
  /** Optional override label instead of POS_LABEL (e.g. "↑ XI", "→ bench") */
  label?: string;
  /** Route destination for transferred-in players ("XI" or "bench") */
  routeLabel?: string;
}) {
  const clr = accent === "red" ? "var(--red)" : "var(--green)";
  const bg = accent === "red" ? "rgba(239,68,68,0.05)" : "rgba(34,197,94,0.05)";
  const border = accent === "red" ? "rgba(239,68,68,0.15)" : "rgba(34,197,94,0.15)";

  return (
    <div
      style={{
        flex: 1,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        background: bg,
        border: `1px solid ${border}`,
        borderRadius: 8,
        padding: "6px 9px",
        gap: 6,
        minWidth: 0,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 5, minWidth: 0 }}>
        <span
          style={{
            fontFamily: "var(--font-ui)",
            fontSize: 8,
            fontWeight: 700,
            color: clr,
            letterSpacing: "0.06em",
            flexShrink: 0,
            whiteSpace: "nowrap",
          }}
        >
          {label ?? POS_LABEL[pos] ?? ""}
        </span>
        {/* Bench tag — shown when selling a bench player */}
        {isBench && !label && (
          <span
            style={{
              fontFamily: "var(--font-ui)",
              fontSize: 7,
              fontWeight: 700,
              color: "var(--text-3)",
              letterSpacing: "0.06em",
              background: "rgba(255,255,255,0.06)",
              border: "1px solid rgba(255,255,255,0.12)",
              borderRadius: 3,
              padding: "1px 3px",
              flexShrink: 0,
            }}
          >
            bench
          </span>
        )}
        {teamCode && (
          <img
            src={`https://resources.premierleague.com/premierleague/badges/25/t${teamCode}.png`}
            alt=""
            width={12} height={12}
            style={{ objectFit: "contain", opacity: 0.7, flexShrink: 0 }}
            onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
          />
        )}
        <span
          style={{
            fontFamily: "var(--font-display)",
            fontSize: 12,
            fontWeight: 600,
            color: "var(--text-1)",
            letterSpacing: "-0.02em",
            overflow: "hidden",
            whiteSpace: "nowrap",
            textOverflow: "ellipsis",
          }}
        >
          {name}
        </span>
        {/* Route badge — shows where transferred-in player goes */}
        {routeLabel && (
          <span
            style={{
              fontFamily: "var(--font-ui)",
              fontSize: 7,
              fontWeight: 700,
              color: routeLabel === "XI" ? "var(--green)" : "var(--text-3)",
              letterSpacing: "0.05em",
              background: routeLabel === "XI" ? "rgba(34,197,94,0.1)" : "rgba(255,255,255,0.06)",
              border: `1px solid ${routeLabel === "XI" ? "rgba(34,197,94,0.25)" : "rgba(255,255,255,0.12)"}`,
              borderRadius: 3,
              padding: "1px 4px",
              flexShrink: 0,
              whiteSpace: "nowrap",
            }}
          >
            {routeLabel}
          </span>
        )}
      </div>
      {xpts !== null && (
        <span
          style={{
            fontFamily: "var(--font-data)",
            fontSize: 10,
            color: "var(--text-3)",
            flexShrink: 0,
          }}
        >
          {xpts.toFixed(1)}
        </span>
      )}
    </div>
  );
}
