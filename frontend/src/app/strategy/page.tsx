"use client";
import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Info, Crown, Zap, ArrowUpDown, ArrowLeftRight, AlertTriangle } from "lucide-react";

/* ── Engine icon — replaces generic Sparkles ──────────────────────────── */
function IconEngine({ size = 11, style }: { size?: number; style?: React.CSSProperties }) {
  return (
    <svg width={size} height={size} viewBox="0 0 12 12" fill="none" style={style}>
      <circle cx="6" cy="6" r="2" stroke="currentColor" strokeWidth="1.2" />
      <line x1="6" y1="1" x2="6" y2="2.5" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
      <line x1="6" y1="9.5" x2="6" y2="11" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
      <line x1="1" y1="6" x2="2.5" y2="6" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
      <line x1="9.5" y1="6" x2="11" y2="6" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
      <line x1="2.46" y1="2.46" x2="3.52" y2="3.52" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
      <line x1="8.48" y1="8.48" x2="9.54" y2="9.54" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
      <line x1="9.54" y1="2.46" x2="8.48" y2="3.52" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
      <line x1="3.52" y1="8.48" x2="2.46" y2="9.54" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
    </svg>
  );
}
import BottomDock from "@/components/BottomDock";
import { useFPLStore } from "@/store/fpl.store";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function fdrStyle(fdr: number | null | undefined) {
  if (!fdr) return { bg: "rgba(255,255,255,0.04)", color: "var(--text-3)" };
  const intensities: Record<number, { bg: string; color: string }> = {
    1: { bg: "rgba(34,197,94,0.18)",   color: "var(--green)" },
    2: { bg: "rgba(34,197,94,0.10)",   color: "var(--green)" },
    3: { bg: "rgba(255,255,255,0.08)", color: "var(--text-2)" },
    4: { bg: "rgba(239,68,68,0.15)",   color: "var(--red)" },
    5: { bg: "rgba(239,68,68,0.22)",   color: "var(--red)" },
  };
  return intensities[fdr] ?? { bg: "rgba(255,255,255,0.06)", color: "var(--text-3)" };
}

const POSITIONS: Record<number, string> = { 1: "GK", 2: "DEF", 3: "MID", 4: "FWD" };
const CHIP_CONFIG: Record<string, {
  label: string;
  icon: string;
  description: string;
  accentColor: string;
  bgColor: string;
  borderColor: string;
  glowColor: string;
}> = {
  wildcard: {
    label: "WILDCARD",
    icon: "🃏",
    description: "Rebuild your entire squad — unlimited free transfers for one GW",
    accentColor: "#a855f7",
    bgColor: "rgba(168,85,247,0.07)",
    borderColor: "rgba(168,85,247,0.25)",
    glowColor: "rgba(168,85,247,0.12)",
  },
  free_hit: {
    label: "FREE HIT",
    icon: "⚡",
    description: "Temporary squad for one GW — reverts to current squad after",
    accentColor: "#38bdf8",
    bgColor: "rgba(56,189,248,0.07)",
    borderColor: "rgba(56,189,248,0.25)",
    glowColor: "rgba(56,189,248,0.12)",
  },
  bench_boost: {
    label: "BENCH BOOST",
    icon: "📈",
    description: "Score points from ALL 15 players — bench comes alive",
    accentColor: "#22c55e",
    bgColor: "rgba(34,197,94,0.07)",
    borderColor: "rgba(34,197,94,0.25)",
    glowColor: "rgba(34,197,94,0.12)",
  },
  triple_captain: {
    label: "TRIPLE CAPTAIN",
    icon: "👑",
    description: "Captain scores 3x instead of 2x — premium pick",
    accentColor: "#f59e0b",
    bgColor: "rgba(245,158,11,0.07)",
    borderColor: "rgba(245,158,11,0.25)",
    glowColor: "rgba(245,158,11,0.12)",
  },
};

interface GWState {
  state: "pre_deadline" | "deadline_passed" | "finished" | "unknown";
  current_gw: number | null;
  next_gw: number | null;
  deadline_time: string | null;
  finished: boolean;
}

export default function StrategyPage() {
  const { fixtureSwings, fetchFixtureSwings, squad, captainCandidates, fetchCaptains, fetchSquad, teamId } = useFPLStore();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [chipRecs, setChipRecs] = useState<Record<string, any> | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [yellowCards, setYellowCards] = useState<any[] | null>(null);
  const [showSwingInfo, setShowSwingInfo] = useState(false);
  const [showRLInfo, setShowRLInfo] = useState(false);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [benchSwaps, setBenchSwaps] = useState<any | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [benchTransferXI, setBenchTransferXI] = useState<any | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [banditState, setBanditState] = useState<any | null>(null);
  const [gwState, setGwState] = useState<GWState | null>(null);

  useEffect(() => {
    fetchFixtureSwings();
    fetchCaptains();
    if (!squad) fetchSquad();
    const params = teamId ? `?team_id=${teamId}` : "";
    fetch(`${API}/api/chips/recommendations${params}`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => d && setChipRecs(d.recommendations))
      .catch(() => {});
    fetch(`${API}/api/intel/yellow-cards${params}`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => d && setYellowCards(d.players_at_risk))
      .catch(() => {});
    fetch(`${API}/api/transfers/bench-swaps${params}`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => d && setBenchSwaps(d))
      .catch(() => {});
    fetch(`${API}/api/transfers/bench-transfer-xi${params}`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => d && setBenchTransferXI(d))
      .catch(() => {});
    fetch(`${API}/api/bandit/state${params}`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => d && setBanditState(d))
      .catch(() => {});
    // Fetch GW state to know whether to show strategy or waiting message
    fetch(`${API}/api/gameweeks/current`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => d && setGwState(d))
      .catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Reset section counter on each render
  resetSectionIdx();

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)" }}>
      <main style={{ maxWidth: 960, margin: "0 auto", padding: "32px 20px 96px", display: "flex", flexDirection: "column", gap: 16 }}>
        <div style={{ marginBottom: 8 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <h1 style={{ fontFamily: "var(--font-display)", fontSize: "clamp(26px, 4vw, 40px)", fontWeight: 700, color: "var(--text-1)", letterSpacing: "-0.04em", margin: 0 }}>
              Strategy Board
            </h1>
          </div>
        </div>

        {/* ══ GW AWAITING RESULTS — deadline passed, games not yet started ═══ */}
        {gwState && gwState.state === "deadline_passed" && !gwState.finished && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.4 }}
            style={{
              borderRadius: 16,
              padding: "32px 28px",
              background: "var(--surface)",
              border: "1px solid var(--divider)",
              textAlign: "center",
            }}
          >
            <div style={{ fontFamily: "var(--font-data)", fontSize: 10, color: "var(--text-3)", letterSpacing: "0.18em", textTransform: "uppercase", marginBottom: 16 }}>
              GW{gwState.current_gw} · DEADLINE PASSED
            </div>
            <h2 style={{ fontFamily: "var(--font-display)", fontSize: "clamp(24px, 4vw, 36px)", fontWeight: 700, color: "var(--text-1)", letterSpacing: "-0.04em", margin: "0 0 12px", lineHeight: 1 }}>
              Awaiting GW{gwState.current_gw} Results
            </h2>
            <p style={{ fontFamily: "var(--font-ui)", fontSize: 13, color: "var(--text-3)", lineHeight: 1.7, maxWidth: 400, margin: "0 auto" }}>
              Squad is locked. Strategy for GW{gwState.next_gw ?? ((gwState.current_gw ?? 0) + 1)} will appear once fixtures complete.
            </p>
          </motion.div>
        )}

        {/* ══ BEST PLAYS THIS WEEK — top-level synthesis card ════════ */}
        {(captainCandidates.length > 0 || chipRecs || benchSwaps?.swaps?.length > 0) && (() => {
          // Build a ranked list of the best single action per category
          type Play = { rank: number; icon: React.ElementType; label: string; detail: string; impact: string; color: string; urgent?: boolean; team_code?: number | null };
          const plays: Play[] = [];
          let rank = 1;

          // Captain
          if (captainCandidates[0]) {
            const c = captainCandidates[0];
            const xp = (c.predicted_xpts_next ?? 0).toFixed(1);
            plays.push({
              rank: rank++, icon: Crown,
              label: `Captain ${c.web_name}`,
              detail: `${xp} xPts expected · ${c.has_double_gw ? "DGW · " : ""}${c.reasoning?.slice(0, 60) ?? ""}`,
              impact: `${xp} xPts`, color: "var(--amber)", urgent: (c.predicted_xpts_next ?? 0) >= 7,
              team_code: c.team_code ?? null,
            });
          }

          // Urgent chip
          if (chipRecs) {
            const urgentEntry = Object.entries(chipRecs).find(([, rec]: [string, any]) => rec.urgency === "urgent");
            if (urgentEntry) {
              const [chip, rec]: [string, any] = urgentEntry;
              plays.push({
                rank: rank++, icon: Zap,
                label: `Play ${CHIP_CONFIG[chip]?.label ?? chip.toUpperCase()} now`,
                detail: `GW${rec.recommended_gw ?? rec.best_gw} · ${Math.round((rec.confidence ?? 0) * 100)}% confidence`,
                impact: `+${rec.expected_gain?.toFixed(1)} xPts`, color: "var(--green)", urgent: true,
              });
            }
          }

          // Bench swap
          if (benchSwaps?.swaps?.[0]) {
            const s = benchSwaps.swaps[0];
            plays.push({
              rank: rank++, icon: ArrowUpDown,
              label: `Swap ${s.bench_out_name} → ${s.bench_in_name}`,
              detail: "No transfer needed · formation-preserving",
              impact: `+${s.xpts_gain?.toFixed(1)} xPts`, color: "var(--green)",
            });
          }

          // Transfer suggestion from bench-transfer XI
          if (benchTransferXI?.suggestions?.[0]) {
            const s = benchTransferXI.suggestions[0];
            plays.push({
              rank: rank++, icon: ArrowLeftRight,
              label: `Transfer in ${s.transfer_in?.web_name}`,
              detail: `Out: ${s.bench_out?.web_name} · £${s.cost_millions}m`,
              impact: `+${s.net_gain?.toFixed(1)} xPts`, color: "var(--blue)",
              team_code: s.transfer_in?.team_code ?? null,
            });
          }

          // Rotation risk alert
          if (squad?.squad) {
            const highRisk = squad.squad.find((p) => p.position <= 11 && (p.predicted_start_prob ?? 1) < 0.40);
            if (highRisk) {
              plays.push({
                rank: rank++, icon: AlertTriangle,
                label: `Consider selling ${highRisk.web_name}`,
                detail: `Start probability only ${Math.round((highRisk.predicted_start_prob ?? 0) * 100)}% — high rotation risk`,
                impact: "Risk mgmt", color: "var(--red)",
              });
            }
          }

          if (plays.length === 0) return null;

          return (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ type: "spring", stiffness: 220, damping: 26 }}
              style={{
                borderRadius: 16,
                padding: "20px 20px 16px",
                background: "var(--surface)",
                border: "1px solid var(--divider)",
              }}
            >
              <div>
                {/* Header */}
                <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 16 }}>
                  <div>
                    <h2 style={{ fontFamily: "var(--font-display)", fontSize: 20, fontWeight: 700, color: "var(--text-1)", letterSpacing: "-0.03em", margin: 0 }}>
                      Best Plays This Week
                    </h2>
                    <p style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)", margin: "2px 0 0", letterSpacing: "0.1em", textTransform: "uppercase" }}>
                      Engine synthesis
                    </p>
                  </div>
                </div>

                {/* Play list */}
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {plays.map((play, i) => {
                    const PlayIcon = play.icon;
                    return (
                      <motion.div
                        key={play.rank}
                        initial={{ opacity: 0, x: -10 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: i * 0.07, type: "spring", stiffness: 280, damping: 26 }}
                        style={{
                          display: "flex",
                          alignItems: "flex-start",
                          gap: 10,
                          padding: "10px 12px",
                          background: "rgba(255,255,255,0.02)",
                          border: "1px solid var(--divider)",
                          borderRadius: 10,
                        }}
                      >
                        {/* Team badge (if applicable) */}
                        {play.team_code && (
                          <div style={{ width: 28, height: 28, flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center", borderRadius: 7, background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", padding: 3 }}>
                            <img
                              src={`https://resources.premierleague.com/premierleague/badges/25/t${play.team_code}.png`}
                              alt="" width={18} height={18} style={{ objectFit: "contain" }}
                              onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                            />
                          </div>
                        )}
                        {/* Icon + content */}
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 2 }}>
                            <span style={{ fontFamily: "var(--font-ui)", fontSize: 13, fontWeight: 600, color: "var(--text-1)", letterSpacing: "-0.01em" }}>
                              {play.label}
                            </span>
                          </div>
                          <p style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-3)", margin: 0, lineHeight: 1.4 }}>
                            {play.detail}
                          </p>
                        </div>
                        {/* Impact */}
                        <span style={{ fontFamily: "var(--font-data)", fontSize: 13, fontWeight: 700, color: play.color, flexShrink: 0, alignSelf: "center" }}>
                          {play.impact}
                        </span>
                      </motion.div>
                    );
                  })}
                </div>
              </div>
            </motion.div>
          );
        })()}

        {captainCandidates.length > 0 && (
          <Section title="Captain Picks" accent="var(--amber)">
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {captainCandidates.slice(0, 5).map((c, i) => {
                const isHero     = i === 0;
                const xPts       = c.predicted_xpts_next ?? 0;
                const isConfirmed = isHero && xPts >= 7.0;
                return (
                  <motion.div
                    key={c.player_id}
                    initial={{ opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: i * 0.06, type: "spring", stiffness: 300, damping: 26 }}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: isHero ? "flex-start" : "center",
                      padding: isHero ? "18px 18px" : "11px 14px",
                      background: isHero ? "rgba(34,197,94,0.05)" : "rgba(255,255,255,0.02)",
                      border: `1px solid ${isHero ? "rgba(34,197,94,0.22)" : "var(--divider)"}`,
                      borderRadius: 14,
                      position: "relative",
                      overflow: "hidden",
                    }}
                  >
                    {/* Editorial watermark for hero */}
                    {isConfirmed && (
                      <div style={{
                        position: "absolute", inset: 0, display: "flex", alignItems: "center",
                        paddingLeft: 16, pointerEvents: "none", opacity: 0.04,
                      }}>
                        <span style={{
                          fontFamily: "var(--font-display)", fontSize: 72, fontWeight: 700,
                          color: "var(--green)", letterSpacing: "-0.04em", whiteSpace: "nowrap",
                        }}>CAPTAIN</span>
                      </div>
                    )}

                    {/* Left: team badge + name + reasoning */}
                    <div style={{ position: "relative", zIndex: 1, display: "flex", alignItems: isHero ? "flex-start" : "center", gap: 12 }}>
                      {/* Team badge — large for hero */}
                      {c.team_code && (
                        <div style={{
                          width: isHero ? 44 : 28,
                          height: isHero ? 44 : 28,
                          flexShrink: 0,
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          borderRadius: isHero ? 10 : 7,
                          background: "rgba(255,255,255,0.04)",
                          border: "1px solid rgba(255,255,255,0.08)",
                          padding: 4,
                        }}>
                          <img
                            src={`https://resources.premierleague.com/premierleague/badges/25/t${c.team_code}.png`}
                            alt="" width={isHero ? 32 : 18} height={isHero ? 32 : 18}
                            style={{ objectFit: "contain" }}
                            onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                          />
                        </div>
                      )}
                      <div>
                        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: isHero ? 6 : 2 }}>
                          {/* Captain badge */}
                          <span style={{
                            display: "inline-flex", alignItems: "center", justifyContent: "center",
                            width: isHero ? 20 : 15, height: isHero ? 20 : 15, borderRadius: "50%",
                            background: "var(--amber)", color: "#000",
                            fontFamily: "var(--font-display)", fontSize: isHero ? 11 : 9, fontWeight: 700,
                            flexShrink: 0,
                          }}>C</span>
                          <span style={{
                            fontFamily: "var(--font-display)",
                            fontSize: isHero ? 22 : 13,
                            fontWeight: 600, color: "var(--text-1)", letterSpacing: "-0.03em",
                          }}>{c.web_name}</span>
                          {c.team_short_name && (
                            <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)", letterSpacing: "0.04em" }}>
                              {c.team_short_name}
                            </span>
                          )}
                          {c.has_double_gw && <span className="badge badge-amber" style={{ fontSize: 9 }}>DGW</span>}
                          {isConfirmed && (
                            <span style={{
                              fontFamily: "var(--font-display)", fontSize: 9, fontWeight: 700,
                              color: "var(--green)", background: "rgba(34,197,94,0.12)",
                              border: "1px solid rgba(34,197,94,0.28)",
                              borderRadius: 999, padding: "2px 9px", letterSpacing: "0.06em",
                            }}>CONFIRMED</span>
                          )}
                        </div>
                        {c.reasoning && (
                          <div style={{
                            fontSize: isHero ? 11 : 10,
                            color: "var(--text-3)", fontFamily: "var(--font-ui)", lineHeight: 1.45,
                            maxWidth: isHero ? 320 : 200,
                          }}>{c.reasoning}</div>
                        )}
                      </div>
                    </div>

                    {/* Right: xPts number */}
                    <div style={{ textAlign: "right", flexShrink: 0, position: "relative", zIndex: 1 }}>
                      <div style={{
                        fontFamily: "var(--font-data)",
                        fontSize: isHero ? 48 : 22,
                        fontWeight: 600,
                        color: isHero ? "var(--green)" : "var(--text-2)",
                        letterSpacing: "-0.04em", lineHeight: 1,
                      }}>
                        {xPts.toFixed(1)}
                      </div>
                      <div style={{ fontSize: 9, color: "var(--text-3)", fontFamily: "var(--font-ui)", letterSpacing: "0.06em", marginTop: 3 }}>xPts</div>
                    </div>
                  </motion.div>
                );
              })}
            </div>
          </Section>
        )}

        {chipRecs && Object.keys(chipRecs).length > 0 && (
          <Section title="Chip Strategy" accent="#a855f7">
            {/* ENGINE ACTION BANNER — urgent chip */}
            {(() => {
              const urgentEntry = Object.entries(chipRecs).find(([, rec]: [string, any]) => rec.urgency === "urgent");
              if (!urgentEntry) return null;
              const [chip, rec]: [string, any] = urgentEntry;
              const cfg = CHIP_CONFIG[chip];
              return (
                <motion.div
                  initial={{ opacity: 0, scale: 0.98 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ type: "spring", stiffness: 300, damping: 28 }}
                  style={{
                    display: "flex", alignItems: "center", gap: 10, marginBottom: 16,
                    padding: "10px 14px", borderRadius: 10,
                    background: cfg?.bgColor ?? "rgba(34,197,94,0.07)",
                    border: `1px solid ${cfg?.borderColor ?? "rgba(34,197,94,0.25)"}`,
                    boxShadow: `0 0 20px ${cfg?.glowColor ?? "transparent"}`,
                  }}
                >
                  <span style={{ fontSize: 20, flexShrink: 0 }}>{cfg?.icon ?? "⚡"}</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontFamily: "var(--font-display)", fontSize: 12, fontWeight: 700, color: cfg?.accentColor ?? "var(--green)", letterSpacing: "0.03em", marginBottom: 2 }}>
                      PLAY NOW: {cfg?.label ?? chip.toUpperCase()} · GW{rec.recommended_gw ?? rec.best_gw}
                    </div>
                    <div style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-2)" }}>
                      +{rec.expected_gain?.toFixed(1)} xPts gain expected{rec.confidence != null ? ` · ${Math.round(rec.confidence * 100)}% confidence` : ""}
                    </div>
                  </div>
                  <span style={{
                    fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 700,
                    color: cfg?.accentColor ?? "var(--green)",
                    background: cfg?.bgColor ?? "rgba(34,197,94,0.12)",
                    border: `1px solid ${cfg?.borderColor ?? "rgba(34,197,94,0.25)"}`,
                    borderRadius: 999, padding: "3px 10px", letterSpacing: "0.08em", flexShrink: 0,
                  }}>NOW</span>
                </motion.div>
              );
            })()}

            {/* Per-chip cards — distinctive visual per chip type */}
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {Object.entries(chipRecs).map(([chip, rec]: [string, any], i) => {
                const cfg = CHIP_CONFIG[chip];
                const isUrgent = rec.urgency === "urgent";
                const gwNum = rec.recommended_gw ?? rec.best_gw;
                const gain = rec.expected_gain?.toFixed(1);
                const conf = rec.confidence != null ? Math.round(rec.confidence * 100) : null;

                return (
                  <motion.div
                    key={chip}
                    initial={{ opacity: 0, x: -12 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: i * 0.1, type: "spring", stiffness: 280, damping: 26 }}
                    style={{
                      display: "flex",
                      gap: 14,
                      alignItems: "flex-start",
                      background: cfg?.bgColor ?? "rgba(255,255,255,0.03)",
                      border: `1px solid ${isUrgent ? (cfg?.borderColor ?? "var(--divider)") : "var(--divider)"}`,
                      borderLeft: `3px solid ${cfg?.accentColor ?? "var(--text-3)"}`,
                      borderRadius: 12,
                      padding: "14px 16px",
                      position: "relative",
                      overflow: "hidden",
                      boxShadow: isUrgent ? `0 0 24px ${cfg?.glowColor ?? "transparent"}` : undefined,
                    }}
                  >
                    {/* Background icon watermark */}
                    <div style={{
                      position: "absolute", right: 14, top: "50%", transform: "translateY(-50%)",
                      fontSize: 56, opacity: 0.06, pointerEvents: "none", lineHeight: 1,
                    }}>
                      {cfg?.icon ?? "⚡"}
                    </div>

                    {/* Left: big icon */}
                    <div style={{
                      width: 44, height: 44, borderRadius: 10, flexShrink: 0,
                      display: "flex", alignItems: "center", justifyContent: "center",
                      background: cfg?.bgColor ?? "rgba(255,255,255,0.04)",
                      border: `1px solid ${cfg?.borderColor ?? "var(--divider)"}`,
                      fontSize: 22,
                    }}>
                      {cfg?.icon ?? "⚡"}
                    </div>

                    {/* Right: content */}
                    <div style={{ flex: 1, minWidth: 0, position: "relative", zIndex: 1 }}>
                      {/* Header row */}
                      <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 4 }}>
                        <span style={{
                          fontFamily: "var(--font-display)", fontSize: 12, fontWeight: 700,
                          color: cfg?.accentColor ?? "var(--text-1)", letterSpacing: "0.04em",
                        }}>
                          {cfg?.label ?? chip.toUpperCase().replace(/_/g, " ")}
                        </span>
                        {isUrgent && (
                          <span style={{
                            fontFamily: "var(--font-ui)", fontSize: 8, fontWeight: 700,
                            color: cfg?.accentColor ?? "var(--green)",
                            background: cfg?.bgColor ?? "rgba(34,197,94,0.12)",
                            border: `1px solid ${cfg?.borderColor ?? "rgba(34,197,94,0.3)"}`,
                            borderRadius: 999, padding: "1px 7px", letterSpacing: "0.08em",
                          }}>PLAY NOW</span>
                        )}
                      </div>

                      {/* Description */}
                      <div style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-3)", lineHeight: 1.45, marginBottom: 8 }}>
                        {cfg?.description ?? rec.reasoning ?? ""}
                      </div>

                      {/* Stats row */}
                      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
                        <div>
                          <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)", letterSpacing: "0.06em", textTransform: "uppercase", display: "block", marginBottom: 1 }}>Optimal GW</span>
                          <span style={{ fontFamily: "var(--font-data)", fontSize: 22, fontWeight: 700, color: cfg?.accentColor ?? "var(--text-1)", letterSpacing: "-0.03em", lineHeight: 1 }}>
                            {gwNum ?? "—"}
                          </span>
                        </div>
                        {gain && (
                          <div>
                            <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)", letterSpacing: "0.06em", textTransform: "uppercase", display: "block", marginBottom: 1 }}>Expected gain</span>
                            <span style={{ fontFamily: "var(--font-data)", fontSize: 18, fontWeight: 600, color: cfg?.accentColor ?? "var(--green)", letterSpacing: "-0.02em", lineHeight: 1 }}>
                              +{gain} xP
                            </span>
                          </div>
                        )}
                        {conf != null && (
                          <div>
                            <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)", letterSpacing: "0.06em", textTransform: "uppercase", display: "block", marginBottom: 1 }}>Confidence</span>
                            <span style={{ fontFamily: "var(--font-data)", fontSize: 16, fontWeight: 600, color: conf >= 70 ? (cfg?.accentColor ?? "var(--green)") : "var(--text-2)", letterSpacing: "-0.02em", lineHeight: 1 }}>
                              {conf}%
                            </span>
                          </div>
                        )}
                      </div>

                      {/* Reasoning if different from description */}
                      {rec.reasoning && rec.reasoning !== cfg?.description && (
                        <div style={{ marginTop: 8, fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-3)", lineHeight: 1.45, fontStyle: "italic" }}>
                          {rec.reasoning}
                        </div>
                      )}
                    </div>
                  </motion.div>
                );
              })}
            </div>
          </Section>
        )}

        {squad?.squad && squad.squad.length > 0 && (
          <Section title="Fixture Overview">
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "separate", borderSpacing: "0 3px", fontFamily: "var(--font-ui)" }}>
                <thead>
                  <tr>
                    {["Player", "Pos", "FDR", "H/A", "xPts"].map((h) => (
                      <th key={h} style={{ textAlign: h === "Player" ? "left" : "center", fontSize: 9, color: "var(--text-3)", fontWeight: 600, letterSpacing: "0.1em", textTransform: "uppercase", padding: "4px 8px" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {squad.squad.filter((p) => p.position <= 11).map((p, i) => {
                    const s = fdrStyle(p.fdr_next);
                    return (
                      <tr key={p.player_id}>
                        <td style={{ fontFamily: "var(--font-ui)", fontSize: 13, fontWeight: 600, color: "var(--text-1)", padding: "6px 8px" }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                            {p.team_code && (
                              <img src={`https://resources.premierleague.com/premierleague/badges/25/t${p.team_code}.png`}
                                alt="" width={14} height={14} style={{ objectFit: "contain", opacity: 0.8 }}
                                onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />
                            )}
                            {p.web_name}
                          </div>
                        </td>
                        <td style={{ textAlign: "center", padding: "6px 8px" }}><span style={{ fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 600, color: "var(--text-3)", letterSpacing: "0.06em" }}>{POSITIONS[p.element_type] ?? "—"}</span></td>
                        <td style={{ textAlign: "center", padding: "6px 8px" }}><span style={{ display: "inline-block", background: s.bg, color: s.color, borderRadius: 6, padding: "2px 10px", fontFamily: "var(--font-data)", fontSize: 12, fontWeight: 600 }}>{p.fdr_next ?? "—"}</span></td>
                        <td style={{ textAlign: "center", fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-3)", padding: "6px 8px" }}>{p.is_home_next === null || p.is_home_next === undefined ? "—" : p.is_home_next ? "H" : "A"}</td>
                        <td style={{ textAlign: "center", padding: "6px 8px" }}><span style={{ fontFamily: "var(--font-data)", fontSize: 13, fontWeight: 600, color: "var(--green)", letterSpacing: "-0.02em" }}>{p.predicted_xpts_next != null ? p.predicted_xpts_next.toFixed(1) : "—"}</span></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Section>
        )}

        {fixtureSwings && (
          <Section
            title="Fixture Swing Radar"
            accent="var(--blue)"
            titleRight={
              <button
                onClick={() => setShowSwingInfo(v => !v)}
                style={{
                  background: showSwingInfo ? "rgba(59,130,246,0.12)" : "rgba(59,130,246,0.06)",
                  border: `1px solid ${showSwingInfo ? "rgba(59,130,246,0.35)" : "rgba(59,130,246,0.18)"}`,
                  borderRadius: 6,
                  cursor: "pointer",
                  padding: "3px 5px",
                  display: "flex",
                  alignItems: "center",
                  color: "var(--blue)",
                  transition: "background 0.15s",
                }}
                title="What is the Fixture Swing Radar?"
              >
                <Info size={13} />
              </button>
            }
          >
            <AnimatePresence>
              {showSwingInfo && (
                <motion.div
                  key="swing-info"
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.22 }}
                  style={{ overflow: "hidden", marginBottom: 14 }}
                >
                  <div style={{ padding: "10px 12px", background: "rgba(59,130,246,0.06)", border: "1px solid rgba(59,130,246,0.18)", borderRadius: 10, fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-2)", lineHeight: 1.6 }}>
                    <div style={{ fontWeight: 600, color: "var(--blue)", marginBottom: 5 }}>How it works</div>
                    Ranks all 20 Premier League teams by their <em>average FDR (Fixture Difficulty Rating)</em> across the next 6 GWs.
                    {" "}<strong style={{ color: "var(--green)" }}>Buy Windows</strong>: teams with the easiest upcoming run — great time to buy their attacking players.
                    {" "}<strong style={{ color: "var(--red)" }}>Sell Windows</strong>: teams facing the toughest fixtures — consider selling their players before the run hits.
                    {" "}FDR 1–2 = easy, 4–5 = hard (set by the Premier League).
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
              {[
                { key: "buy_windows", label: "buy windows", color: "var(--green)", xDir: -8 },
                { key: "sell_windows", label: "sell windows", color: "var(--red)", xDir: 8 },
              ].map(({ key, label, color, xDir }) => (
                <div key={key}>
                  <p style={{ fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 600, color, letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 10 }}>{label}</p>
                  {(fixtureSwings as any)[key].slice(0, 5).map((team: any, i: number) => {
                    const s = fdrStyle(Math.round(team.avg_fdr_next_6));
                    return (
                      <motion.div key={team.team_id} initial={{ opacity: 0, x: xDir }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.06 }}
                        style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "9px 12px", marginBottom: 5, background: "rgba(255,255,255,0.02)", border: "1px solid var(--divider)", borderRadius: 10 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                          {team.team_code && (
                            <img src={`https://resources.premierleague.com/premierleague/badges/25/t${team.team_code}.png`}
                              alt="" width={16} height={16} style={{ objectFit: "contain", opacity: 0.8 }}
                              onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />
                          )}
                          <span style={{ fontFamily: "var(--font-ui)", fontSize: 13, fontWeight: 500, color: "var(--text-1)" }}>{team.team_name}</span>
                        </div>
                        <span style={{ fontFamily: "var(--font-data)", fontSize: 12, fontWeight: 600, background: s.bg, color: s.color, borderRadius: 6, padding: "2px 8px" }}>{team.avg_fdr_next_6.toFixed(1)}</span>
                      </motion.div>
                    );
                  })}
                </div>
              ))}
            </div>
          </Section>
        )}

        {benchSwaps && benchSwaps.swaps && benchSwaps.swaps.length > 0 && (
          <Section title="Bench → XI Swaps" accent="var(--green)">
            <p style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-3)", marginBottom: 12, lineHeight: 1.5 }}>
              Formation-preserving lineup changes that increase your starting XI xPts — no transfer needed.
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {benchSwaps.swaps.slice(0, 4).map((swap: any, i: number) => (
                <motion.div key={i} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.05 }}
                  style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 14px", background: "rgba(34,197,94,0.04)", border: "1px solid rgba(34,197,94,0.15)", borderRadius: 10 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    {/* Player going to bench */}
                    <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                      {swap.bench_out_team_code && (
                        <img src={`https://resources.premierleague.com/premierleague/badges/25/t${swap.bench_out_team_code}.png`}
                          alt="" width={13} height={13} style={{ objectFit: "contain", opacity: 0.7 }}
                          onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />
                      )}
                      <span style={{ fontFamily: "var(--font-ui)", fontSize: 12, color: "var(--red)", fontWeight: 600 }}>{swap.bench_out_name}</span>
                    </div>
                    <span style={{ fontFamily: "var(--font-data)", fontSize: 10, color: "var(--text-3)" }}>→</span>
                    {/* Player coming into XI */}
                    <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                      {swap.bench_in_team_code && (
                        <img src={`https://resources.premierleague.com/premierleague/badges/25/t${swap.bench_in_team_code}.png`}
                          alt="" width={13} height={13} style={{ objectFit: "contain", opacity: 0.7 }}
                          onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />
                      )}
                      <span style={{ fontFamily: "var(--font-ui)", fontSize: 12, color: "var(--green)", fontWeight: 600 }}>{swap.bench_in_name}</span>
                    </div>
                  </div>
                  <span style={{ fontFamily: "var(--font-data)", fontSize: 12, fontWeight: 700, color: "var(--green)" }}>+{swap.xpts_gain.toFixed(1)}</span>
                </motion.div>
              ))}
            </div>
          </Section>
        )}

        {benchTransferXI && benchTransferXI.suggestions && benchTransferXI.suggestions.length > 0 && (
          <Section title="Bench Transfer → XI Upgrade" accent="var(--blue)">
            <p style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-3)", marginBottom: 12, lineHeight: 1.5 }}>
              Transfer out a bench player to fund a better signing — the new player starts in your XI, pushing a weak starter to the bench.
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {benchTransferXI.suggestions.map((s: any, i: number) => (
                <motion.div key={i} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.07 }}
                  style={{ padding: "12px 14px", background: "rgba(59,130,246,0.04)", border: "1px solid rgba(59,130,246,0.15)", borderRadius: 12 }}>
                  {/* Three-step flow */}
                  <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8, flexWrap: "wrap" }}>
                    {/* Bench out */}
                    <div style={{ display: "flex", alignItems: "center", gap: 5, padding: "4px 8px", background: "rgba(239,68,68,0.06)", border: "1px solid rgba(239,68,68,0.18)", borderRadius: 8 }}>
                      {s.bench_out.team_code && <img src={`https://resources.premierleague.com/premierleague/badges/25/t${s.bench_out.team_code}.png`} alt="" width={11} height={11} style={{ objectFit: "contain", opacity: 0.7 }} onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />}
                      <span style={{ fontFamily: "var(--font-ui)", fontSize: 11, fontWeight: 600, color: "var(--red)" }}>{s.bench_out.web_name}</span>
                      <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)" }}>bench out</span>
                    </div>
                    <span style={{ fontFamily: "var(--font-data)", fontSize: 10, color: "var(--text-3)" }}>→</span>
                    {/* Transfer in */}
                    <div style={{ display: "flex", alignItems: "center", gap: 5, padding: "4px 8px", background: "rgba(34,197,94,0.06)", border: "1px solid rgba(34,197,94,0.18)", borderRadius: 8 }}>
                      {s.transfer_in.team_code && <img src={`https://resources.premierleague.com/premierleague/badges/25/t${s.transfer_in.team_code}.png`} alt="" width={11} height={11} style={{ objectFit: "contain", opacity: 0.7 }} onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />}
                      <span style={{ fontFamily: "var(--font-ui)", fontSize: 11, fontWeight: 600, color: "var(--green)" }}>{s.transfer_in.web_name}</span>
                      <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)" }}>£{s.cost_millions}m · {(s.transfer_in.predicted_xpts_next ?? 0).toFixed(1)} xPts</span>
                    </div>
                    <span style={{ fontFamily: "var(--font-data)", fontSize: 10, color: "var(--text-3)" }}>→</span>
                    {/* XI swap */}
                    <div style={{ display: "flex", alignItems: "center", gap: 5, padding: "4px 8px", background: "rgba(255,255,255,0.03)", border: "1px solid var(--divider)", borderRadius: 8 }}>
                      {s.xi_swap_out.team_code && <img src={`https://resources.premierleague.com/premierleague/badges/25/t${s.xi_swap_out.team_code}.png`} alt="" width={11} height={11} style={{ objectFit: "contain", opacity: 0.7 }} onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />}
                      <span style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-2)" }}>{s.xi_swap_out.web_name}</span>
                      <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)" }}>to bench</span>
                    </div>
                  </div>
                  {/* Gain + meta */}
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-3)", lineHeight: 1.45, maxWidth: "75%" }}>{s.reasoning}</span>
                    <span style={{ fontFamily: "var(--font-data)", fontSize: 15, fontWeight: 700, color: s.net_gain >= 2 ? "var(--green)" : "var(--amber)", flexShrink: 0 }}>+{s.net_gain.toFixed(1)} xP</span>
                  </div>
                  {s.budget_after_millions < 0.5 && (
                    <div style={{ marginTop: 5, fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--amber)" }}>⚠ £{s.budget_after_millions.toFixed(1)}m left in bank</div>
                  )}
                </motion.div>
              ))}
            </div>
          </Section>
        )}

        {banditState && banditState.decision_states && (
          <Section
            title="RL Decision Engine"
            accent="var(--blue)"
            titleRight={
              <button
                onClick={() => setShowRLInfo(v => !v)}
                style={{
                  background: showRLInfo ? "rgba(59,130,246,0.12)" : "rgba(59,130,246,0.06)",
                  border: `1px solid ${showRLInfo ? "rgba(59,130,246,0.35)" : "rgba(59,130,246,0.18)"}`,
                  borderRadius: 6,
                  cursor: "pointer",
                  padding: "3px 5px",
                  display: "flex",
                  alignItems: "center",
                  color: "var(--blue)",
                  transition: "background 0.15s",
                }}
                title="What is the RL Decision Engine?"
              >
                <Info size={13} />
              </button>
            }
          >
            <AnimatePresence>
              {showRLInfo && (
                <motion.div key="rl-info" initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} transition={{ duration: 0.22 }} style={{ overflow: "hidden", marginBottom: 14 }}>
                  <div style={{ padding: "10px 12px", background: "rgba(59,130,246,0.06)", border: "1px solid rgba(59,130,246,0.18)", borderRadius: 10, fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-2)", lineHeight: 1.6 }}>
                    <div style={{ fontWeight: 600, color: "var(--blue)", marginBottom: 5 }}>UCB1 Multi-Armed Bandit</div>
                    Learns which FPL strategies produce the best GW outcomes over time. Each <em>arm</em> is a strategy option (e.g. greedy vs ILP vs hold). The bandit picks the arm with the highest <strong>UCB1 score</strong> — balancing exploitation of known good strategies with exploration of untried ones.
                    <br /><br />
                    <span style={{ color: "var(--amber)" }}>Exploring</span> = trying all options before settling on a strategy. <span style={{ color: "var(--text-3)" }}>Learning</span> = fresh install, no GW history yet — strategies will populate automatically after your first gameweek resolves. Scores (Q-values) update automatically after each GW outcome is recorded via <code style={{ fontSize: 10, background: "rgba(255,255,255,0.06)", padding: "1px 4px", borderRadius: 4 }}>POST /api/bandit/outcome</code>.
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
            {/* ENGINE RECOMMENDS banner — best arm across all decision types */}
            {(() => {
              const entries = Object.entries(banditState.decision_states);
              const bestEntry = entries.find(([, state]: [string, any]) =>
                state.best_arm && state.best_arm !== "unexplored" && (state.total_pulls ?? 0) >= 2
              );
              if (!bestEntry) return null;
              const [dtype, state]: [string, any] = bestEntry;
              const label = dtype.replace(/_/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase());
              return (
                <div style={{
                  display: "flex", alignItems: "center", gap: 7, marginBottom: 14,
                  padding: "6px 10px", borderRadius: 8,
                  background: "rgba(59,130,246,0.07)", border: "1px solid rgba(59,130,246,0.22)",
                }}>
                  <IconEngine size={11} style={{ color: "var(--blue)", flexShrink: 0 }} />
                  <span style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--blue)", fontWeight: 600, letterSpacing: "0.04em" }}>
                    BEST STRATEGY: Use <strong>{state.best_arm}</strong> for {label} ({state.total_pulls} observations)
                  </span>
                </div>
              );
            })()}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              {Object.entries(banditState.decision_states).map(([dtype, state]: [string, any], i) => {
                const bestArm = state.best_arm === "unexplored" ? state.arms[0] : state.best_arm;
                const totalPulls = state.total_pulls ?? 0;
                const isExploring = totalPulls < state.arms.length;
                const isBestDecision = !isExploring && state.best_arm !== "unexplored";
                const label = dtype.replace(/_/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase());
                return (
                  <motion.div key={dtype} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.07 }}
                    style={{
                      padding: "12px 14px",
                      background: isBestDecision ? "rgba(59,130,246,0.07)" : "rgba(59,130,246,0.04)",
                      border: `1px solid ${isBestDecision ? "rgba(59,130,246,0.28)" : "rgba(59,130,246,0.15)"}`,
                      borderRadius: 10,
                    }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: 6 }}>
                      <IconEngine size={9} style={{ color: isBestDecision ? "var(--blue)" : "var(--text-3)", flexShrink: 0 }} />
                      <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 600, color: isBestDecision ? "var(--blue)" : "var(--text-3)", letterSpacing: "0.1em", textTransform: "uppercase" }}>{label}</span>
                    </div>
                    <div style={{ fontFamily: "var(--font-display)", fontSize: 13, fontWeight: 700, color: "var(--text-1)", marginBottom: 4 }}>{bestArm}</div>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <span style={{ fontFamily: "var(--font-data)", fontSize: 10, color: "var(--text-3)" }}>
                        {totalPulls === 0 ? "no history yet" : `${totalPulls} obs`}
                      </span>
                      {totalPulls === 0 && <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)", background: "rgba(148,163,184,0.1)", borderRadius: 4, padding: "1px 5px" }}>learning</span>}
                      {totalPulls > 0 && isExploring && <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--amber)", background: "rgba(245,158,11,0.1)", borderRadius: 4, padding: "1px 5px" }}>exploring</span>}
                      {isBestDecision && <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--blue)", background: "rgba(59,130,246,0.12)", borderRadius: 4, padding: "1px 5px" }}>best</span>}
                    </div>
                  </motion.div>
                );
              })}
            </div>
          </Section>
        )}

        {yellowCards && yellowCards.length > 0 && (
          <Section title="Suspension Risk" accent="var(--amber)">
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {yellowCards.map((p, i) => (
                <motion.div key={p.player_id} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.05 }}
                  style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 14px", background: "rgba(245,158,11,0.04)", border: "1px solid rgba(245,158,11,0.15)", borderRadius: 10 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                    {p.team_code && (
                      <img src={`https://resources.premierleague.com/premierleague/badges/25/t${p.team_code}.png`}
                        alt="" width={16} height={16} style={{ objectFit: "contain", opacity: 0.8 }}
                        onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />
                    )}
                    <span style={{ fontFamily: "var(--font-ui)", fontSize: 13, fontWeight: 600, color: "var(--text-1)" }}>{p.web_name}</span>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span className="badge badge-amber" style={{ fontSize: 10 }}>{p.yellow_cards} YC</span>
                    {p.action && <span style={{ fontSize: 11, color: "var(--text-3)", fontFamily: "var(--font-ui)" }}>{p.action}</span>}
                  </div>
                </motion.div>
              ))}
            </div>
          </Section>
        )}

        {/* ── Rotation Risk — players with low start probability ── */}
        {squad?.squad && (() => {
          const POSITIONS: Record<number, string> = { 1: "GK", 2: "DEF", 3: "MID", 4: "FWD" };
          const rotationPlayers = squad.squad
            .filter((p) => p.position <= 11 && p.predicted_start_prob != null && p.predicted_start_prob < 0.65)
            .sort((a, b) => (a.predicted_start_prob ?? 1) - (b.predicted_start_prob ?? 1));
          if (rotationPlayers.length === 0) return null;
          return (
            <Section title="Rotation Risk" accent="var(--red)">
              <p style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-3)", marginBottom: 12, lineHeight: 1.5 }}>
                Starting XI players with a start probability below 65% — manager may rotate or squad them.
              </p>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {rotationPlayers.map((p) => {
                  const prob = p.predicted_start_prob ?? 0;
                  const riskColor = prob < 0.40 ? "var(--red)" : prob < 0.55 ? "var(--amber)" : "var(--text-3)";
                  const riskLabel = prob < 0.40 ? "HIGH" : prob < 0.55 ? "MEDIUM" : "LOW";
                  return (
                    <motion.div key={p.player_id} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }}
                      style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "9px 12px", background: "rgba(255,255,255,0.02)", border: "1px solid var(--divider)", borderRadius: 10 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                        {p.team_code && (
                          <img src={`https://resources.premierleague.com/premierleague/badges/25/t${p.team_code}.png`}
                            alt="" width={14} height={14} style={{ objectFit: "contain", opacity: 0.75 }}
                            onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />
                        )}
                        <span style={{ fontFamily: "var(--font-ui)", fontSize: 13, fontWeight: 600, color: "var(--text-1)" }}>{p.web_name}</span>
                        <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)", letterSpacing: "0.06em" }}>{POSITIONS[p.element_type] ?? "—"}</span>
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        {/* Start prob bar */}
                        <div style={{ width: 48, height: 4, borderRadius: 2, background: "rgba(255,255,255,0.08)", overflow: "hidden" }}>
                          <div style={{ height: "100%", width: `${prob * 100}%`, background: riskColor, borderRadius: 2, transition: "width 400ms" }} />
                        </div>
                        <span style={{ fontFamily: "var(--font-data)", fontSize: 12, fontWeight: 700, color: riskColor, minWidth: 32 }}>
                          {Math.round(prob * 100)}%
                        </span>
                        <span style={{
                          fontFamily: "var(--font-ui)", fontSize: 8, fontWeight: 700, color: riskColor,
                          background: `${riskColor}18`, border: `1px solid ${riskColor}33`,
                          borderRadius: 999, padding: "1px 6px", letterSpacing: "0.06em",
                        }}>{riskLabel}</span>
                      </div>
                    </motion.div>
                  );
                })}
              </div>
            </Section>
          );
        })()}

        {!fixtureSwings && !chipRecs && !yellowCards && captainCandidates.length === 0 && (
          <div style={{ textAlign: "center", padding: "56px 0", color: "var(--text-3)", fontSize: 13, fontFamily: "var(--font-ui)" }}>
            sync your squad on the pitch page to load strategy data.
          </div>
        )}
      </main>
      <BottomDock />
    </div>
  );
}

// Auto-incrementing section index for editorial numbered headers
let _sectionIdx = 0;
function resetSectionIdx() { _sectionIdx = 0; }

function Section({ title, titleRight, children, accent }: {
  title: string;
  titleRight?: React.ReactNode;
  children: React.ReactNode;
  accent?: string; // optional accent color for the section number
}) {
  _sectionIdx += 1;
  const num = String(_sectionIdx).padStart(2, "0");
  const accentColor = accent ?? "var(--text-3)";

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 220, damping: 26 }}
      style={{
        background: "var(--surface)",
        border: "1px solid var(--divider)",
        borderRadius: 16,
        overflow: "hidden",
      }}
    >
      {/* Editorial section header */}
      <div style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "16px 20px 14px",
        borderBottom: "1px solid var(--divider)",
      }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
          <span style={{
            fontFamily: "var(--font-data)",
            fontSize: 11,
            fontWeight: 700,
            color: accentColor,
            letterSpacing: "0.08em",
            opacity: 0.7,
          }}>
            {num}
          </span>
          <h2 style={{
            fontFamily: "var(--font-display)",
            fontSize: 18,
            fontWeight: 600,
            color: "var(--text-1)",
            letterSpacing: "-0.03em",
            margin: 0,
            lineHeight: 1,
          }}>
            {title}
          </h2>
        </div>
        {titleRight}
      </div>
      <div style={{ padding: "16px 20px 18px" }}>
        {children}
      </div>
    </motion.div>
  );
}
