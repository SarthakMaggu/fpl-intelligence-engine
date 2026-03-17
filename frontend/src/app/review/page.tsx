"use client";
import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  CheckCircle, XCircle, Clock, TrendingUp, TrendingDown,
  RefreshCw, ArrowLeftRight, Zap,
} from "lucide-react";
import BottomDock from "@/components/BottomDock";
import { useFPLStore } from "@/store/fpl.store";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface Decision {
  id: number;
  gameweek_id: number;
  decision_type: string;
  recommended_option: string;
  user_choice?: string | null;
  expected_points?: number | null;
  actual_points?: number | null;
  decision_followed?: boolean | null;
  reasoning?: string | null;
  notes?: string | null;
  created_at?: string | null;
  resolved_at?: string | null;
}

interface GWReview {
  team_id: number;
  gameweek_id: number;
  summary: {
    total_decisions: number;
    followed: number;
    ignored: number;
    pending_resolution: number;
    adherence_rate: number;
    expected_points_if_followed: number;
    actual_points_followed: number;
    gain_vs_ai_pts?: number | null;
  };
  user_gw_performance?: {
    gw_points?: number | null;
    overall_rank?: number | null;
    transfers_made?: number | null;
    transfer_cost?: number | null;
    chip_played?: string | null;
    points_on_bench?: number | null;
    avg_gw_pts?: number | null;
  } | null;
  decisions: Decision[];
}

interface RealTransfer {
  gameweek: number;
  time: string;
  element_in: number;
  element_in_name: string;
  element_in_team?: string | null;
  element_in_team_code?: number | null;
  element_in_position?: number | null;
  element_out: number;
  element_out_name: string;
  element_out_team?: string | null;
  element_out_team_code?: number | null;
  element_out_position?: number | null;
  element_in_cost_millions: number;
  element_out_cost_millions: number;
  ai_recommended: boolean;
  ai_decision?: {
    id: number;
    recommended_option: string;
    user_choice?: string | null;
    decision_followed?: boolean | null;
    expected_points?: number | null;
    actual_points?: number | null;
    reasoning?: string | null;
  } | null;
}

interface TransfersReview {
  team_id: number;
  total_transfers: number;
  ai_recommended_count: number;
  user_initiated_count: number;
  adherence_rate: number;
  transfers: RealTransfer[];
}

interface ActiveChip {
  team_id: number;
  chip: string | null;
  gameweek: number | null;
}

interface SeasonReview {
  team_id: number;
  total_decisions: number;
  followed?: number;
  ignored?: number;
  adherence_rate?: number;
  net_pts_vs_ai?: number;
  total_rank_gain_following_ai?: number;
  by_decision_type?: Record<string, {
    followed: number;
    ignored: number;
    adherence_rate: number;
    avg_expected: number;
    avg_actual: number;
  }>;
  message?: string;
}

function AdherenceBadge({ followed }: { followed?: boolean | null }) {
  if (followed === null || followed === undefined) {
    return (
      <span style={{ display: "flex", alignItems: "center", gap: 4, color: "var(--text-3)", fontSize: 11 }}>
        <Clock size={12} /> pending
      </span>
    );
  }
  return (
    <span style={{ display: "flex", alignItems: "center", gap: 4, color: followed ? "var(--green)" : "var(--red)", fontSize: 11 }}>
      {followed ? <CheckCircle size={12} /> : <XCircle size={12} />}
      {followed ? "followed" : "ignored"}
    </span>
  );
}

function DecisionCard({ d }: { d: Decision }) {
  const isChip = d.decision_type === "CHIP_USED" || d.decision_type.toLowerCase().includes("chip");
  const dtColors: Record<string, string> = {
    transfer_strategy: "var(--blue)",
    captain: "var(--amber)",
    captain_strategy: "var(--amber)",
    chip: "var(--green)",
    CHIP_USED: "var(--amber)",
    chip_recommendation: "var(--green)",
    hit: "var(--red)",
  };
  const color = dtColors[d.decision_type] || "var(--blue)";

  // Chip-type label mapping
  const CHIP_LABEL_MAP: Record<string, string> = {
    triple_captain: "Triple Captain",
    wildcard: "Wildcard",
    bench_boost: "Bench Boost",
    free_hit: "Free Hit",
  };

  // Human-readable type label
  const typeLabel = isChip
    ? (CHIP_LABEL_MAP[d.recommended_option] ?? d.recommended_option?.replace(/_/g, " "))
    : d.decision_type.replace(/_/g, " ").toLowerCase();

  // Don't show 0.0 expected for auto-logged chips (uninformative)
  const showExpected = d.expected_points != null && !(isChip && (d.expected_points === 0 || d.expected_points === 0.0));

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      style={{
        padding: "12px 14px",
        borderRadius: 10,
        background: "var(--surface)",
        border: "1px solid var(--divider)",
        marginBottom: 8,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{
            fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 600, color,
            letterSpacing: "0.08em", textTransform: "uppercase",
            background: `${color}18`, border: `1px solid ${color}44`,
            borderRadius: 4, padding: "2px 6px",
          }}>
            {typeLabel}
          </span>
          <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)" }}>
            GW{d.gameweek_id}
          </span>
        </div>
        <AdherenceBadge followed={d.decision_followed} />
      </div>

      {/* Main recommendation text */}
      {!isChip && (
        <div style={{ fontFamily: "var(--font-ui)", fontSize: 13, fontWeight: 600, color: "var(--text-1)", marginBottom: 4 }}>
          {d.recommended_option}
        </div>
      )}

      {/* Chip: show it as a natural statement */}
      {isChip && (
        <div style={{ fontFamily: "var(--font-ui)", fontSize: 12, color: "var(--text-2)", marginBottom: 4 }}>
          {d.decision_followed
            ? `Played ${CHIP_LABEL_MAP[d.recommended_option] ?? d.recommended_option?.replace(/_/g, " ")} in GW${d.gameweek_id}`
            : `${CHIP_LABEL_MAP[d.recommended_option] ?? d.recommended_option?.replace(/_/g, " ")} was available`}
        </div>
      )}

      {/* Points row — only for transfers/captain decisions with meaningful data */}
      {(showExpected || d.actual_points != null) && (
        <div style={{ display: "flex", gap: 12, marginTop: 6 }}>
          {showExpected && (
            <div>
              <div style={{ fontSize: 9, color: "var(--text-3)", fontFamily: "var(--font-ui)", letterSpacing: "0.06em", textTransform: "uppercase" }}>expected</div>
              <div style={{ fontFamily: "var(--font-data)", fontSize: 14, color: "var(--text-2)", fontWeight: 600 }}>
                +{d.expected_points!.toFixed(1)}
              </div>
            </div>
          )}
          {d.actual_points != null && (
            <div>
              <div style={{ fontSize: 9, color: "var(--text-3)", fontFamily: "var(--font-ui)", letterSpacing: "0.06em", textTransform: "uppercase" }}>actual</div>
              <div style={{
                fontFamily: "var(--font-data)", fontSize: 14, fontWeight: 600,
                color: d.actual_points >= (d.expected_points || 0) ? "var(--green)" : "var(--red)",
              }}>
                {d.actual_points >= 0 ? "+" : ""}{d.actual_points.toFixed(1)}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Reasoning — short, clean */}
      {d.reasoning && !isChip && (
        <div style={{
          marginTop: 8, fontSize: 10, color: "var(--text-3)", fontFamily: "var(--font-ui)",
          lineHeight: 1.5, paddingTop: 8, borderTop: "1px solid var(--divider)",
        }}>
          {d.reasoning.slice(0, 100)}{d.reasoning.length > 100 ? "…" : ""}
        </div>
      )}
    </motion.div>
  );
}

interface OracleSquadPlayer {
  name: string;
  team_code: number | null;
  team_short_name: string | null;
  element_type?: number | null; // 1=GK 2=DEF 3=MID 4=FWD
}

interface TopTeam {
  team_id: number | null;
  team_name: string | null;
  points: number | null;
  points_normalised: number | null;
  display_points?: number | string | null;
  status?: string | null;
  chip_adjustment: number | null;
  squad: string[];
  captain: string | null;
  chip: string | null;
  chip_miss_reason: string | null;
}

interface BlindSpots {
  gw?: number;
  missed?: string[];
  insight?: string;
  top_pts?: number;
  oracle_pts?: number;
  gap?: number;
}

interface OracleSnapshot {
  gameweek_id: number;
  oracle_formation: string | null;
  oracle_xpts: number | null;
  oracle_cost_millions: number | null;
  oracle_captain: { name: string | null; xpts: number | null } | null;
  oracle_squad: string[];  // player names for XI (legacy)
  oracle_squad_with_teams: OracleSquadPlayer[];  // enriched with team badge info
  algo_xpts: number | null;
  gap_xpts: number | null;
  actual_oracle_points: number | null;
  actual_algo_points: number | null;
  oracle_beat_algo: boolean | null;
  resolved: boolean;
  snapshot_taken_at: string | null;
  // Top-team comparison (filled after auto-resolve)
  top_team: TopTeam | null;
  oracle_beat_top: boolean | null;
  missed_players: string[];
  blind_spots: BlindSpots | null;
}

interface CrossCheckResult {
  verified: boolean;
  verified_count: number;
  total_checks: number;
  real_captain: string | null;
  real_captain_id: number | null;
  checks: { decision_id: number; type: string; matched: boolean; detail: string }[];
}

export default function ReviewPage() {
  const teamId = useFPLStore((s) => s.teamId);
  const [gwReview, setGwReview] = useState<GWReview | null>(null);
  const [seasonReview, setSeasonReview] = useState<SeasonReview | null>(null);
  const [oracleHistory, setOracleHistory] = useState<OracleSnapshot[]>([]);
  const [transfersReview, setTransfersReview] = useState<TransfersReview | null>(null);
  const [activeChip, setActiveChip] = useState<ActiveChip | null>(null);
  const [tab, setTab] = useState<"gw" | "transfers" | "season" | "oracle">("gw");
  const [loading, setLoading] = useState(true);
  const [takingSnapshot, setTakingSnapshot] = useState(false);
  const [crossCheck, setCrossCheck] = useState<CrossCheckResult | null>(null);
  const [crossChecking, setCrossChecking] = useState(false);
  const [gwStateStr, setGwStateStr] = useState<string | null>(null);
  const [autoResolving, setAutoResolving] = useState(false);
  const [liveGwPts, setLiveGwPts] = useState<number | null>(null);

  // Load persisted cross-check from localStorage on mount
  useEffect(() => {
    if (!teamId) return;
    const saved = typeof window !== "undefined" ? localStorage.getItem(`fpl_crosscheck_${teamId}`) : null;
    if (saved) {
      try { setCrossCheck(JSON.parse(saved)); } catch { /* ignore */ }
    }
  }, [teamId]);

  const load = async () => {
    if (!teamId) { setLoading(false); return; }
    setLoading(true);
    try {
      const [gwRes, seasonRes, oracleRes, txRes, chipRes, gwStateRes] = await Promise.all([
        fetch(`${API}/api/review/gameweek?team_id=${teamId}`),
        fetch(`${API}/api/review/season?team_id=${teamId}`),
        fetch(`${API}/api/oracle/history?team_id=${teamId}&limit=10`),
        fetch(`${API}/api/review/transfers?team_id=${teamId}`),
        fetch(`${API}/api/chips/active?team_id=${teamId}`),
        fetch(`${API}/api/gameweeks/current`),
      ]);
      let loadedGwReview: GWReview | null = null;
      if (gwRes.ok) { loadedGwReview = await gwRes.json(); setGwReview(loadedGwReview); }
      if (seasonRes.ok) setSeasonReview(await seasonRes.json());
      if (oracleRes.ok) {
        const d = await oracleRes.json();
        setOracleHistory(d.snapshots || []);
      }
      if (txRes.ok) setTransfersReview(await txRes.json());
      if (chipRes.ok) setActiveChip(await chipRes.json());
      if (gwStateRes.ok) {
        const gwStateData = await gwStateRes.json();
        setGwStateStr(gwStateData.state || null);
        // Fetch live score when GW is active (deadline passed but not finished)
        if (gwStateData.state === "deadline_passed" && teamId) {
          try {
            const liveRes = await fetch(`${API}/api/live/score?team_id=${teamId}`);
            if (liveRes.ok) {
              const liveData = await liveRes.json();
              const livePts = liveData.total_live_points ?? liveData.total_points ?? liveData.live_total ?? null;
              if (typeof livePts === "number") setLiveGwPts(livePts);
            }
          } catch { /* non-fatal */ }
        }
        // Auto-run cross-check when deadline has passed and no saved result
        if (gwStateData.state === "deadline_passed" && loadedGwReview) {
          const savedKey = `fpl_crosscheck_${teamId}`;
          const savedRaw = typeof window !== "undefined" ? localStorage.getItem(savedKey) : null;
          if (!savedRaw) {
            // Run cross-check silently
            setCrossChecking(true);
            try {
              const ccRes = await fetch(
                `${API}/api/review/cross-check?team_id=${teamId}&gameweek=${loadedGwReview.gameweek_id}`
              );
              if (ccRes.ok) {
                const ccData = await ccRes.json();
                setCrossCheck(ccData);
                if (typeof window !== "undefined") {
                  localStorage.setItem(savedKey, JSON.stringify(ccData));
                }
              }
            } catch { /* silent */ }
            finally { setCrossChecking(false); }
          }
        }
      }
    } catch { /* silent */ }
    finally { setLoading(false); }
  };

  const takeSnapshot = async () => {
    if (!teamId) return;
    setTakingSnapshot(true);
    try {
      await fetch(`${API}/api/oracle/snapshot?team_id=${teamId}`, { method: "POST" });
      await load(); // refresh after snapshot
    } catch { /* silent */ }
    finally { setTakingSnapshot(false); }
  };

  const autoResolve = async () => {
    if (!teamId) return;
    setAutoResolving(true);
    try {
      await fetch(`${API}/api/oracle/auto-resolve?team_id=${teamId}`, { method: "POST" });
      await load();
    } catch { /* silent */ }
    finally { setAutoResolving(false); }
  };

  const runCrossCheck = async () => {
    if (!teamId || !gwReview) return;
    setCrossChecking(true);
    try {
      const res = await fetch(
        `${API}/api/review/cross-check?team_id=${teamId}&gameweek=${gwReview.gameweek_id}`
      );
      if (res.ok) {
        const data = await res.json();
        setCrossCheck(data);
        if (typeof window !== "undefined") {
          localStorage.setItem(`fpl_crosscheck_${teamId}`, JSON.stringify(data));
        }
        await load(); // refresh so decision_followed flags update
      }
    } catch { /* silent */ }
    finally { setCrossChecking(false); }
  };

  useEffect(() => { load(); }, [teamId]);

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)", paddingBottom: 80 }}>
      {/* Top bar */}
      <div style={{ padding: "18px 20px 0", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <div style={{
            fontFamily: "var(--font-display)",
            fontSize: 22,
            fontWeight: 700,
            color: "var(--text-1)",
            letterSpacing: "-0.02em",
          }}>
            GW Review
          </div>
          <div style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-3)", marginTop: 2 }}>
            Intelligence recommendation adherence
          </div>
        </div>
        <button
          onClick={load}
          style={{
            background: "var(--surface)",
            border: "1px solid var(--divider)",
            borderRadius: 8,
            padding: "6px 10px",
            cursor: "pointer",
            color: "var(--text-2)",
          }}
        >
          <RefreshCw size={13} />
        </button>
      </div>

      {/* Tab strip */}
      <div style={{ display: "flex", gap: 6, padding: "14px 20px 0", overflowX: "auto" }}>
        {([
          { key: "gw",        label: "This GW",    accent: "var(--blue)" },
          { key: "transfers", label: "Transfers",   accent: "var(--green)" },
          { key: "season",    label: "Season",      accent: "var(--blue)" },
          { key: "oracle",    label: "Oracle",    accent: "var(--amber)" },
        ] as const).map(({ key, label, accent }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            style={{
              padding: "6px 14px",
              borderRadius: 8,
              border: `1px solid ${tab === key ? accent : "var(--divider)"}`,
              background: tab === key ? `${accent}18` : "var(--surface)",
              color: tab === key ? accent : "var(--text-3)",
              fontFamily: "var(--font-ui)",
              fontSize: 11,
              fontWeight: tab === key ? 600 : 400,
              cursor: "pointer",
              transition: "all 150ms",
              whiteSpace: "nowrap",
              flexShrink: 0,
            }}
          >
            {label}
          </button>
        ))}
      </div>

      <div style={{ padding: "14px 20px", maxWidth: 1180, margin: "0 auto", width: "100%" }}>
        {!teamId ? (
          <div style={{ textAlign: "center", padding: 40, color: "var(--text-3)", fontFamily: "var(--font-ui)", fontSize: 13 }}>
            Enter your team ID on the Pitch screen to see your review.
          </div>
        ) : loading ? (
          <div style={{ textAlign: "center", padding: 40, color: "var(--text-3)", fontFamily: "var(--font-ui)", fontSize: 13 }}>
            Loading review...
          </div>
        ) : tab === "gw" ? (
          <GWView
            review={gwReview}
            activeChip={activeChip}
            crossCheck={crossCheck}
            crossChecking={crossChecking}
            onCrossCheck={runCrossCheck}
            gwState={gwStateStr}
            liveGwPts={liveGwPts}
          />
        ) : tab === "transfers" ? (
          <TransfersView review={transfersReview} />
        ) : tab === "oracle" ? (
          <OracleView
            snapshots={oracleHistory}
            teamId={teamId}
            takingSnapshot={takingSnapshot}
            onSnapshot={takeSnapshot}
            autoResolving={autoResolving}
            onAutoResolve={autoResolve}
          />
        ) : (
          <SeasonView review={seasonReview} />
        )}
      </div>

      <BottomDock />
    </div>
  );
}

const CHIP_LABELS: Record<string, string> = {
  wildcard: "Wildcard",
  free_hit: "Free Hit",
  bench_boost: "Bench Boost",
  triple_captain: "Triple Captain",
  bboost: "Bench Boost",
  "3xc": "Triple Captain",
};

function GWView({
  review,
  activeChip,
  crossCheck,
  crossChecking,
  onCrossCheck,
  gwState,
  liveGwPts,
}: {
  review: GWReview | null;
  activeChip: ActiveChip | null;
  crossCheck: CrossCheckResult | null;
  crossChecking: boolean;
  onCrossCheck: () => void;
  gwState?: string | null;
  liveGwPts?: number | null;
}) {
  if (!review) return (
    <div style={{ textAlign: "center", padding: 40, color: "var(--text-3)", fontFamily: "var(--font-ui)", fontSize: 13 }}>
      No review data yet. Decisions are tracked as you make transfers and captain picks.
    </div>
  );

  const { summary, user_gw_performance: perf, decisions } = review;

  return (
    <>
      {/* Summary card */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="glass"
        style={{ padding: 16, borderRadius: 12, marginBottom: 16 }}
      >
        <div style={{
          fontFamily: "var(--font-ui)",
          fontSize: 11,
          color: "var(--text-3)",
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          marginBottom: 12,
        }}>
          GW{review.gameweek_id} · Adherence
        </div>

        {/* Stats grid */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, marginBottom: 14 }}>
          {[
            { label: "followed", value: summary.followed, color: "var(--green)" },
            { label: "ignored", value: summary.ignored, color: "var(--red)" },
            { label: "pending", value: summary.pending_resolution, color: "var(--text-3)" },
          ].map(({ label, value, color }) => (
            <div key={label} style={{ textAlign: "center" }}>
              <div style={{ fontFamily: "var(--font-data)", fontSize: 24, fontWeight: 700, color }}>{value}</div>
              <div style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</div>
            </div>
          ))}
        </div>

        {/* Adherence bar */}
        <div style={{ marginBottom: 10 }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
            <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>adherence rate</span>
            <span style={{ fontFamily: "var(--font-data)", fontSize: 11, color: "var(--text-2)" }}>{(summary.adherence_rate * 100).toFixed(0)}%</span>
          </div>
          <div style={{ height: 4, background: "var(--divider)", borderRadius: 2 }}>
            <div style={{
              height: "100%",
              width: `${summary.adherence_rate * 100}%`,
              background: summary.adherence_rate > 0.7 ? "var(--green)" : summary.adherence_rate > 0.4 ? "var(--amber)" : "var(--red)",
              borderRadius: 2,
              transition: "width 600ms var(--ease-out)",
            }} />
          </div>
        </div>

        {/* Gain vs recommendations */}
        {summary.gain_vs_ai_pts != null && (
          <div style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "8px 10px",
            background: summary.gain_vs_ai_pts >= 0 ? "rgba(34,197,94,0.08)" : "rgba(239,68,68,0.08)",
            borderRadius: 8,
            border: `1px solid ${summary.gain_vs_ai_pts >= 0 ? "rgba(34,197,94,0.2)" : "rgba(239,68,68,0.2)"}`,
          }}>
            {summary.gain_vs_ai_pts >= 0
              ? <TrendingUp size={13} style={{ color: "var(--green)" }} />
              : <TrendingDown size={13} style={{ color: "var(--red)" }} />}
            <span style={{ fontFamily: "var(--font-data)", fontSize: 13, color: summary.gain_vs_ai_pts >= 0 ? "var(--green)" : "var(--red)", fontWeight: 600 }}>
              {summary.gain_vs_ai_pts >= 0 ? "+" : ""}{summary.gain_vs_ai_pts.toFixed(1)} pts vs recommendation
            </span>
          </div>
        )}
      </motion.div>

      {/* ── Cross-check with real FPL squad ─────────────────── */}
      <div style={{ marginBottom: 16 }}>
        {crossChecking && !crossCheck ? (
          <div style={{ width: "100%", padding: "10px 16px", borderRadius: 10, background: "var(--surface)", border: "1px solid var(--divider)", fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-3)", letterSpacing: "0.02em", textAlign: "center" }}>
            Verifying with FPL API…
          </div>
        ) : !crossCheck ? (
          <button
            onClick={onCrossCheck}
            disabled={crossChecking}
            style={{
              width: "100%",
              padding: "10px 16px", borderRadius: 10,
              background: "var(--surface)",
              border: "1px solid var(--divider)",
              cursor: crossChecking ? "default" : "pointer",
              color: crossChecking ? "var(--text-3)" : "var(--text-2)",
              fontFamily: "var(--font-ui)", fontSize: 11, fontWeight: 500,
              letterSpacing: "0.02em",
              transition: "border-color 150ms",
            }}
            onMouseEnter={(e) => { if (!crossChecking) (e.currentTarget as HTMLButtonElement).style.borderColor = "rgba(255,255,255,0.2)"; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--divider)"; }}
          >
            Verify against real FPL squad
          </button>
        ) : (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            style={{
              padding: "12px 16px", borderRadius: 10,
              background: "var(--surface)",
              border: "1px solid var(--divider)",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <div style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-3)", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 4 }}>
                  Squad verification
                </div>
                <div style={{ fontFamily: "var(--font-display)", fontSize: 14, fontWeight: 600, color: crossCheck.total_checks === 0 ? "var(--text-2)" : crossCheck.verified ? "var(--green)" : "var(--text-2)", letterSpacing: "-0.02em" }}>
                  {crossCheck.total_checks === 0
                    ? "No decisions to verify"
                    : `${crossCheck.verified_count} of ${crossCheck.total_checks} confirmed`}
                </div>
                {crossCheck.real_captain && (
                  <div style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-3)", marginTop: 3 }}>
                    Captain · {crossCheck.real_captain}
                  </div>
                )}
              </div>
              <div>
                <div style={{
                  fontFamily: "var(--font-data)", fontSize: 22, fontWeight: 700,
                  color: crossCheck.total_checks === 0 ? "var(--text-3)" : crossCheck.verified ? "var(--green)" : "var(--text-2)",
                  letterSpacing: "-0.04em", textAlign: "right",
                }}>
                  {crossCheck.total_checks === 0 ? "—" : `${Math.round(crossCheck.verified_count / Math.max(crossCheck.total_checks, 1) * 100)}%`}
                </div>
                {/* Show re-run button only when not auto-verified after deadline */}
                {gwState !== "deadline_passed" && (
                  <button
                    onClick={onCrossCheck}
                    style={{
                      marginTop: 4, padding: "2px 8px", borderRadius: 6,
                      background: "transparent", border: "1px solid var(--divider)",
                      cursor: "pointer", color: "var(--text-3)",
                      fontFamily: "var(--font-ui)", fontSize: 9, letterSpacing: "0.04em",
                    }}
                  >re-check</button>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </div>

      {/* Active chip — inline with performance stats, no robotic icons */}
      {activeChip?.chip && (
        <motion.div
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05 }}
          style={{
            marginBottom: 12,
            padding: "8px 12px",
            borderRadius: 8,
            background: "rgba(245,158,11,0.07)",
            border: "1px solid rgba(245,158,11,0.22)",
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <span style={{ fontFamily: "var(--font-data)", fontSize: 10, fontWeight: 700, color: "var(--amber)", letterSpacing: "0.08em", textTransform: "uppercase" }}>
            {CHIP_LABELS[activeChip.chip] ?? activeChip.chip.replace(/_/g, " ")}
          </span>
          <span style={{ width: 1, height: 10, background: "rgba(245,158,11,0.3)" }} />
          <span style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-3)" }}>
            GW{activeChip.gameweek} · played
          </span>
        </motion.div>
      )}

      {/* GW performance */}
      {(perf || liveGwPts != null) && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="glass"
          style={{ padding: 14, borderRadius: 12, marginBottom: 16 }}
        >
          <div style={{ marginBottom: 10 }}>
            <div style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase" }}>
              Your performance
            </div>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            {/* Live pts — primary when GW active */}
            {liveGwPts != null && (
              <div style={{ flex: 1, textAlign: "center", padding: "8px 6px", borderRadius: 8, background: "rgba(245,158,11,0.07)", border: "1px solid rgba(245,158,11,0.2)" }}>
                <div style={{ fontFamily: "var(--font-data)", fontSize: 20, fontWeight: 700, color: "var(--amber)" }}>{liveGwPts}</div>
                <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--amber)", textTransform: "uppercase", letterSpacing: "0.06em", opacity: 0.8 }}>live pts</div>
              </div>
            )}
            {/* Settled GW pts — only when no live score */}
            {perf?.gw_points != null && liveGwPts == null && (
              <div style={{ flex: 1, textAlign: "center", padding: "8px 6px", borderRadius: 8, background: "rgba(255,255,255,0.03)", border: "1px solid var(--divider)" }}>
                <div style={{ fontFamily: "var(--font-data)", fontSize: 20, fontWeight: 700, color: "var(--text-1)" }}>{perf.gw_points}</div>
                <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>GW pts</div>
              </div>
            )}
            {/* Average GW score */}
            {perf?.avg_gw_pts != null && (
              <div style={{ flex: 1, textAlign: "center", padding: "8px 6px", borderRadius: 8, background: "rgba(255,255,255,0.03)", border: "1px solid var(--divider)" }}>
                <div style={{ fontFamily: "var(--font-data)", fontSize: 20, fontWeight: 700, color: "var(--text-3)" }}>{perf.avg_gw_pts}</div>
                <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>avg pts</div>
              </div>
            )}
            {perf?.overall_rank != null && (
              <div style={{ flex: 1, textAlign: "center", padding: "8px 6px", borderRadius: 8, background: "rgba(255,255,255,0.03)", border: "1px solid var(--divider)" }}>
                <div style={{ fontFamily: "var(--font-data)", fontSize: 20, fontWeight: 700, color: "var(--text-1)" }}>{perf.overall_rank.toLocaleString()}</div>
                <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>rank</div>
              </div>
            )}
            {perf?.points_on_bench != null && (
              <div style={{ flex: 1, textAlign: "center", padding: "8px 6px", borderRadius: 8, background: "rgba(255,255,255,0.03)", border: "1px solid var(--divider)" }}>
                <div style={{ fontFamily: "var(--font-data)", fontSize: 20, fontWeight: 700, color: "var(--text-1)" }}>{perf.points_on_bench}</div>
                <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>bench pts</div>
              </div>
            )}
          </div>
          {perf?.chip_played && (
            <div style={{ marginTop: 8, padding: "4px 8px", background: "rgba(245,158,11,0.1)", border: "1px solid rgba(245,158,11,0.25)", borderRadius: 6, fontSize: 10, color: "var(--amber)", fontFamily: "var(--font-ui)", display: "inline-block" }}>
              Chip: {perf.chip_played}
            </div>
          )}
        </motion.div>
      )}

      {/* Decisions */}
      {decisions.length > 0 ? (
        <>
          <div style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 }}>
            Decisions ({decisions.length})
          </div>
          {decisions.map((d) => <DecisionCard key={d.id} d={d} />)}
        </>
      ) : (
        <div style={{ textAlign: "center", padding: 30, color: "var(--text-3)", fontFamily: "var(--font-ui)", fontSize: 13 }}>
          No decisions logged for this GW yet.
        </div>
      )}
    </>
  );
}

function TransfersView({ review }: { review: TransfersReview | null }) {
  if (!review) return (
    <div style={{ textAlign: "center", padding: 40, color: "var(--text-3)", fontFamily: "var(--font-ui)", fontSize: 13 }}>
      No transfer data loaded. Sync your squad first.
    </div>
  );

  if (review.total_transfers === 0) return (
    <div style={{ textAlign: "center", padding: 40, color: "var(--text-3)", fontFamily: "var(--font-ui)", fontSize: 13 }}>
      No transfers found for this team in the FPL API.
    </div>
  );

  return (
    <>
      {/* Summary */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        style={{
          marginBottom: 16,
          padding: "16px 18px",
          background: "var(--surface)",
          border: "1px solid var(--divider)",
          borderLeft: "3px solid var(--green)",
          borderRadius: 12,
        }}
      >
        <div style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 12 }}>
          Real FPL Transfers — Cross-Referenced
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, marginBottom: 12 }}>
          {[
            { label: "total",        value: review.total_transfers,        color: "var(--text-1)" },
            { label: "engine rec'd", value: review.ai_recommended_count,   color: "var(--green)" },
            { label: "self-init.",   value: review.user_initiated_count,   color: "var(--text-2)" },
          ].map(({ label, value, color }) => (
            <div key={label} style={{ textAlign: "center" }}>
              <div style={{ fontFamily: "var(--font-data)", fontSize: 24, fontWeight: 700, color }}>{value}</div>
              <div style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</div>
            </div>
          ))}
        </div>
        {/* Adherence bar */}
        <div>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
            <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>engine adherence</span>
            <span style={{ fontFamily: "var(--font-data)", fontSize: 11, color: "var(--text-2)" }}>{(review.adherence_rate * 100).toFixed(0)}%</span>
          </div>
          <div style={{ height: 4, background: "var(--divider)", borderRadius: 2 }}>
            <div style={{
              height: "100%",
              width: `${review.adherence_rate * 100}%`,
              background: review.adherence_rate > 0.6 ? "var(--green)" : review.adherence_rate > 0.35 ? "var(--amber)" : "var(--red)",
              borderRadius: 2,
              transition: "width 600ms var(--ease-out)",
            }} />
          </div>
        </div>
      </motion.div>

      {/* Transfer list */}
      <div style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 }}>
        Transfer history ({review.transfers.length})
      </div>
      {review.transfers.map((tx, i) => (
        <motion.div
          key={i}
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: i * 0.04 }}
          style={{
            padding: "12px 14px",
            borderRadius: 10,
            background: "var(--surface)",
            border: `1px solid ${tx.ai_recommended ? "rgba(34,197,94,0.25)" : "var(--divider)"}`,
            marginBottom: 8,
          }}
        >
          {/* Header row */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{
                fontFamily: "var(--font-data)",
                fontSize: 9,
                color: "var(--text-3)",
                background: "var(--surface-2)",
                border: "1px solid var(--divider)",
                borderRadius: 4,
                padding: "2px 6px",
                letterSpacing: "0.04em",
              }}>GW{tx.gameweek}</span>
              {tx.ai_recommended ? (
                <span style={{
                  display: "flex", alignItems: "center", gap: 3,
                  fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 600,
                  color: "var(--green)",
                  background: "rgba(34,197,94,0.1)",
                  border: "1px solid rgba(34,197,94,0.25)",
                  borderRadius: 4, padding: "2px 6px", letterSpacing: "0.04em",
                }}>
                  <CheckCircle size={9} /> Engine recommended
                </span>
              ) : (
                <span style={{
                  fontFamily: "var(--font-ui)", fontSize: 9,
                  color: "var(--text-3)",
                  background: "var(--surface-2)",
                  border: "1px solid var(--divider)",
                  borderRadius: 4, padding: "2px 6px",
                }}>
                  Self-initiated
                </span>
              )}
            </div>
            <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)" }}>
              {tx.time ? new Date(tx.time).toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : ""}
            </span>
          </div>

          {/* Player row: OUT → IN */}
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {/* OUT player */}
            <div style={{
              flex: 1, padding: "8px 10px", borderRadius: 8,
              background: "rgba(239,68,68,0.06)", border: "1px solid rgba(239,68,68,0.2)",
              display: "flex", alignItems: "center", gap: 8,
            }}>
              {tx.element_out_team_code && (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={`https://resources.premierleague.com/premierleague/badges/25/t${tx.element_out_team_code}.png`}
                  alt={tx.element_out_team ?? ""}
                  width={18} height={18}
                  style={{ objectFit: "contain", flexShrink: 0 }}
                  onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                />
              )}
              <div>
                <div style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--red)", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 2 }}>out</div>
                <div style={{ fontFamily: "var(--font-ui)", fontSize: 12, color: "var(--text-2)", fontWeight: 600, lineHeight: 1.2 }}>
                  {tx.element_out_name}
                </div>
                <div style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)" }}>
                  £{tx.element_out_cost_millions.toFixed(1)}m
                </div>
              </div>
            </div>
            <ArrowLeftRight size={11} style={{ color: "var(--text-3)", flexShrink: 0 }} />
            {/* IN player */}
            <div style={{
              flex: 1, padding: "8px 10px", borderRadius: 8,
              background: "rgba(34,197,94,0.06)", border: "1px solid rgba(34,197,94,0.2)",
              display: "flex", alignItems: "center", gap: 8,
            }}>
              {tx.element_in_team_code && (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={`https://resources.premierleague.com/premierleague/badges/25/t${tx.element_in_team_code}.png`}
                  alt={tx.element_in_team ?? ""}
                  width={18} height={18}
                  style={{ objectFit: "contain", flexShrink: 0 }}
                  onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                />
              )}
              <div>
                <div style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--green)", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 2 }}>in</div>
                <div style={{ fontFamily: "var(--font-ui)", fontSize: 12, color: "var(--text-1)", fontWeight: 600, lineHeight: 1.2 }}>
                  {tx.element_in_name}
                </div>
                <div style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)" }}>
                  £{tx.element_in_cost_millions.toFixed(1)}m
                </div>
              </div>
            </div>
          </div>

          {/* AI decision details if matched */}
          {tx.ai_recommended && tx.ai_decision && (
            <div style={{
              marginTop: 8, paddingTop: 8,
              borderTop: "1px solid var(--divider)",
              display: "flex", gap: 12,
            }}>
              {tx.ai_decision.expected_points != null && (
                <div>
                  <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>expected</div>
                  <div style={{ fontFamily: "var(--font-data)", fontSize: 13, color: "var(--text-2)", fontWeight: 600 }}>
                    {tx.ai_decision.expected_points.toFixed(1)}
                  </div>
                </div>
              )}
              {tx.ai_decision.actual_points != null && (
                <div>
                  <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>actual</div>
                  <div style={{
                    fontFamily: "var(--font-data)", fontSize: 13, fontWeight: 600,
                    color: tx.ai_decision.actual_points >= (tx.ai_decision.expected_points || 0) ? "var(--green)" : "var(--red)",
                  }}>
                    {tx.ai_decision.actual_points.toFixed(1)}
                  </div>
                </div>
              )}
              {tx.ai_decision.reasoning && (
                <div style={{ flex: 1 }}>
                  <div style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)", lineHeight: 1.5 }}>
                    {tx.ai_decision.reasoning.slice(0, 80)}{tx.ai_decision.reasoning.length > 80 ? "…" : ""}
                  </div>
                </div>
              )}
            </div>
          )}
        </motion.div>
      ))}
    </>
  );
}

function SeasonView({ review }: { review: SeasonReview | null }) {
  if (!review || review.total_decisions === 0) return (
    <div style={{ textAlign: "center", padding: 40, color: "var(--text-3)", fontFamily: "var(--font-ui)", fontSize: 13, lineHeight: 1.6 }}>
      {review?.message || "No decisions logged yet. Sync your squad and make transfers to start tracking."}
    </div>
  );
  // Decisions logged but GW not resolved yet
  if ((review as any).analysis_mode === "pending") return (
    <div style={{ padding: "32px 16px", fontFamily: "var(--font-ui)", fontSize: 13, lineHeight: 1.7 }}>
      <div style={{
        padding: "16px 18px",
        background: "var(--surface)",
        border: "1px solid var(--divider)",
        borderRadius: 12,
        display: "flex", flexDirection: "column", gap: 8,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--amber)", flexShrink: 0 }} />
          <span style={{ fontFamily: "var(--font-ui)", fontSize: 10, fontWeight: 600, color: "var(--amber)", letterSpacing: "0.08em", textTransform: "uppercase" }}>
            Pending Resolution
          </span>
        </div>
        <div style={{ color: "var(--text-1)", fontWeight: 600, fontSize: 14 }}>
          {review.total_decisions} decision{review.total_decisions !== 1 ? "s" : ""} tracked this season
        </div>
        <div style={{ color: "var(--text-3)", fontSize: 11, lineHeight: 1.6 }}>
          {review.message}
        </div>
      </div>
    </div>
  );

  return (
    <>
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="glass"
        style={{ padding: 16, borderRadius: 12, marginBottom: 16 }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
          <div style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase" }}>
            Season overview
          </div>
          {(review as any).pending_decisions > 0 && (
            <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 600, color: "var(--amber)", background: "rgba(245,158,11,0.1)", border: "1px solid rgba(245,158,11,0.2)", borderRadius: 20, padding: "2px 8px", letterSpacing: "0.06em" }}>
              {(review as any).pending_decisions} pending
            </span>
          )}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
          {[
            { label: "total decisions", value: review.total_decisions },
            { label: "adherence", value: `${((review.adherence_rate || 0) * 100).toFixed(0)}%` },
            { label: "net pts vs rec", value: review.net_pts_vs_ai != null ? `${review.net_pts_vs_ai >= 0 ? "+" : ""}${review.net_pts_vs_ai.toFixed(1)}` : "—", color: (review.net_pts_vs_ai || 0) >= 0 ? "var(--green)" : "var(--red)" },
            { label: "rank gain", value: review.total_rank_gain_following_ai?.toLocaleString() || "—" },
          ].map(({ label, value, color }) => (
            <div key={label} style={{ padding: "10px 12px", background: "var(--surface)", borderRadius: 8, border: "1px solid var(--divider)" }}>
              <div style={{ fontFamily: "var(--font-data)", fontSize: 20, fontWeight: 700, color: (color as string | undefined) || "var(--text-1)" }}>{value}</div>
              <div style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em", marginTop: 2 }}>{label}</div>
            </div>
          ))}
        </div>
      </motion.div>

      {review.by_decision_type && Object.entries(review.by_decision_type).map(([dt, stats]) => (
        <motion.div
          key={dt}
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          style={{
            padding: "12px 14px",
            borderRadius: 10,
            background: "var(--surface)",
            border: "1px solid var(--divider)",
            marginBottom: 8,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
            <span style={{ fontFamily: "var(--font-ui)", fontSize: 12, fontWeight: 600, color: "var(--text-1)", textTransform: "capitalize" }}>
              {dt}
            </span>
            <span style={{ fontFamily: "var(--font-data)", fontSize: 12, color: stats.adherence_rate > 0.6 ? "var(--green)" : "var(--amber)" }}>
              {(stats.adherence_rate * 100).toFixed(0)}% followed
            </span>
          </div>
          <div style={{ display: "flex", gap: 16 }}>
            {[
              { label: "avg expected", value: stats.avg_expected.toFixed(1) },
              { label: "avg actual", value: stats.avg_actual.toFixed(1), color: stats.avg_actual >= stats.avg_expected ? "var(--green)" : "var(--red)" },
            ].map(({ label, value, color }) => (
              <div key={label}>
                <div style={{ fontFamily: "var(--font-data)", fontSize: 16, fontWeight: 600, color: (color as string | undefined) || "var(--text-2)" }}>{value}</div>
                <div style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</div>
              </div>
            ))}
          </div>
        </motion.div>
      ))}
    </>
  );
}

/** Parse a formation string like "4-3-3" → row counts [4,3,3] (excl GK) */
function parseFormation(formation: string | null): number[] {
  if (!formation) return [4, 3, 3];
  return formation.split("-").map(Number).filter((n) => !isNaN(n) && n > 0);
}

/** Distribute oracle squad names into formation rows [gk, def..., mid..., fwd...] */
function distributeFormation(players: string[], formRows: number[]): string[][] {
  const rows: string[][] = [];
  let idx = 0;
  // GK always 1
  rows.push(players.slice(idx, idx + 1)); idx += 1;
  for (const count of formRows) {
    rows.push(players.slice(idx, idx + count)); idx += count;
  }
  return rows;
}

const ROW_COLORS = ["var(--amber)", "var(--green)", "rgba(255,255,255,0.5)", "var(--red)"];

function OracleFormationGrid({ squad, formation, captain, compact = false }: {
  squad: OracleSquadPlayer[];
  formation: string | null;
  captain: string | null;
  compact?: boolean;
}) {
  const formRows = parseFormation(formation);
  const names = squad.map(p => p.name);
  const rows = distributeFormation(names.slice(0, 11), formRows);
  const playerByName = Object.fromEntries(squad.map(p => [p.name, p]));

  // Sizes: compact=true for narrow modal overlays, false for main snapshot cards
  const circleSize  = compact ? 34 : 46;
  const badgeSize   = compact ? 18 : 24;
  const nameFontSz  = compact ? 9  : 10;
  const nameMaxW    = compact ? 46 : 56;
  const pitchHeight = compact ? 210 : 340;
  const capBadgeSz  = compact ? 12 : 16;

  return (
    <div style={{
      borderRadius: 12, overflow: "hidden", position: "relative",
      background: "linear-gradient(180deg, #0D2B1A 0%, #0A2415 60%, #071A10 100%)",
      border: "1px solid rgba(255,255,255,0.07)",
    }}>
      {/* Subtle pitch stripes */}
      <div style={{ position: "absolute", inset: 0, overflow: "hidden", pointerEvents: "none" }}>
        {Array.from({ length: 8 }, (_, i) => (
          <div key={i} style={{ position: "absolute", left: 0, right: 0, top: `${i * 12.5}%`, height: "12.5%", background: i % 2 === 0 ? "rgba(255,255,255,0.018)" : "transparent" }} />
        ))}
        <div style={{ position: "absolute", left: "10%", right: "10%", top: "50%", height: 1, background: "rgba(255,255,255,0.1)", transform: "translateY(-0.5px)" }} />
        <div style={{ position: "absolute", left: "50%", top: "50%", width: 52, height: 52, borderRadius: "50%", border: "1px solid rgba(255,255,255,0.08)", transform: "translate(-50%,-50%)" }} />
        <div style={{ position: "absolute", inset: "5%", border: "1px solid rgba(255,255,255,0.07)", borderRadius: 4 }} />
      </div>

      {formation && (
        <div style={{ position: "absolute", top: 8, right: 10, fontFamily: "var(--font-data)", fontSize: 9, color: "rgba(255,255,255,0.2)", letterSpacing: "0.04em", zIndex: 20 }}>
          {formation}
        </div>
      )}

      {/* Player rows — FWD at top, GK at bottom */}
      <div style={{ position: "relative", zIndex: 10, display: "flex", flexDirection: "column", justifyContent: "space-around", padding: compact ? "10px 8px 8px" : "12px 6px 10px", minHeight: pitchHeight, gap: compact ? 1 : 2 }}>
        {[...rows].reverse().map((rowPlayers, ri) => {
          const rowIdx = rows.length - 1 - ri;
          const lineColor = ROW_COLORS[Math.min(rowIdx, ROW_COLORS.length - 1)];
          return (
            <div key={ri} style={{ display: "flex", justifyContent: "center", gap: compact ? 8 : 5, flexWrap: "nowrap" }}>
              {rowPlayers.map((name, pi) => {
                const isCaptain = name === captain;
                const pInfo = playerByName[name];
                return (
                  <div key={pi} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 3 }}>
                    {/* Player circle */}
                    <div style={{
                      width: circleSize, height: circleSize, borderRadius: "50%", position: "relative",
                      background: `radial-gradient(circle at 38% 35%, ${lineColor}30, ${lineColor}08)`,
                      border: `1.5px solid ${isCaptain ? "var(--amber)" : lineColor}90`,
                      boxShadow: isCaptain ? `0 0 14px rgba(245,158,11,0.5)` : `0 0 10px ${lineColor}33`,
                      display: "flex", alignItems: "center", justifyContent: "center",
                      flexShrink: 0,
                    }}>
                      {pInfo?.team_code && (
                        <img
                          src={`https://resources.premierleague.com/premierleague/badges/25/t${pInfo.team_code}.png`}
                          alt="" width={badgeSize} height={badgeSize}
                          style={{ objectFit: "contain", opacity: 0.85 }}
                          onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                        />
                      )}
                      {isCaptain && (
                        <span style={{
                          position: "absolute", top: -2, right: -2,
                          width: capBadgeSz, height: capBadgeSz, borderRadius: "50%",
                          background: "var(--amber)", color: "#000",
                          fontFamily: "var(--font-display)", fontSize: 7, fontWeight: 700,
                          display: "flex", alignItems: "center", justifyContent: "center",
                          border: "1.5px solid #0D2B1A",
                        }}>C</span>
                      )}
                    </div>
                    {/* Name */}
                    <span style={{
                      fontFamily: "var(--font-ui)", fontSize: nameFontSz, fontWeight: isCaptain ? 700 : 500,
                      color: isCaptain ? "var(--amber)" : "rgba(255,255,255,0.85)",
                      whiteSpace: "nowrap" as const, letterSpacing: "-0.01em",
                      maxWidth: nameMaxW, overflow: "hidden", textOverflow: "ellipsis",
                      display: "block", textAlign: "center",
                    }}>{name}</span>
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function OracleView({
  snapshots,
  teamId,
  takingSnapshot,
  onSnapshot,
  autoResolving,
  onAutoResolve,
}: {
  snapshots: OracleSnapshot[];
  teamId: number | null;
  takingSnapshot: boolean;
  onSnapshot: () => void;
  autoResolving?: boolean;
  onAutoResolve?: () => void;
}) {
  const latestGW = snapshots.length > 0 ? snapshots[0].gameweek_id : null;
  const hasUnresolved = snapshots.some(
    (s) => !s.resolved || s.actual_algo_points == null || s.actual_oracle_points == null || !s.top_team || s.top_team.status === "unavailable"
  );
  // (pitch preview removed — top team squad view is not shown)

  // Helper to format chip label for display
  const fmtChip = (chip: string | null | undefined) =>
    chip?.replace("3xc", "TC").replace("bboost", "BB").replace("freehit", "FH").replace("wildcard", "WC") ?? null;

  return (
    <>
      {/* Header row */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, marginBottom: 20, maxWidth: 880, marginInline: "auto" }}>
        <div>
          <h2 style={{
            fontFamily: "var(--font-display)", fontSize: "clamp(22px, 3.5vw, 32px)", fontWeight: 700,
            color: "var(--text-1)", letterSpacing: "-0.04em", margin: "0 0 6px",
          }}>
            GW Oracle
          </h2>
          <p style={{
            fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-3)",
            lineHeight: 1.6, maxWidth: 320, margin: 0,
          }}>
            Best possible £100m squad at deadline vs your actual picks.
          </p>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8, alignItems: "flex-end" }}>
          <motion.button
            whileHover={{ scale: 1.01 }}
            whileTap={{ scale: 0.98 }}
            onClick={onSnapshot}
            disabled={takingSnapshot || !teamId}
            style={{
              padding: "8px 16px", borderRadius: 10,
              border: "1px solid rgba(245,158,11,0.35)",
              background: takingSnapshot ? "rgba(255,255,255,0.03)" : "rgba(245,158,11,0.08)",
              color: takingSnapshot ? "var(--text-3)" : "var(--amber)",
              fontFamily: "var(--font-ui)", fontSize: 11, fontWeight: 600,
              cursor: takingSnapshot ? "not-allowed" : "pointer",
              whiteSpace: "nowrap" as const,
              transition: "all 150ms",
            }}
          >
            {takingSnapshot ? "Computing…" : "Snapshot Now"}
          </motion.button>
          {hasUnresolved && onAutoResolve && (
            <motion.button
              whileHover={{ scale: 1.01 }}
              whileTap={{ scale: 0.98 }}
              onClick={onAutoResolve}
              disabled={autoResolving}
              style={{
                padding: "6px 14px", borderRadius: 8,
                border: "1px solid rgba(34,197,94,0.3)",
                background: autoResolving ? "rgba(255,255,255,0.02)" : "rgba(34,197,94,0.06)",
                color: autoResolving ? "var(--text-3)" : "var(--green)",
                fontFamily: "var(--font-ui)", fontSize: 10, fontWeight: 600,
                cursor: autoResolving ? "not-allowed" : "pointer",
                whiteSpace: "nowrap" as const,
                transition: "all 150ms",
              }}
            >
              {autoResolving ? "Resolving…" : "Fetch Actual Points"}
            </motion.button>
          )}
        </div>
      </div>

      {snapshots.length === 0 ? (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          style={{
            textAlign: "center", padding: "56px 20px",
            background: "var(--surface)", border: "1px solid var(--divider)",
            borderRadius: 16,
          }}
        >
          <div style={{ fontFamily: "var(--font-data)", fontSize: 44, marginBottom: 16, color: "var(--amber)", opacity: 0.25 }}>◈</div>
          <p style={{ fontFamily: "var(--font-ui)", fontSize: 13, color: "var(--text-3)", lineHeight: 1.7, margin: 0 }}>
            No oracle snapshots yet.<br />
            <span style={{ color: "var(--amber)", fontWeight: 600 }}>Snapshot Now</span> to log the theoretically optimal team.
          </p>
        </motion.div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 14, maxWidth: 880, margin: "0 auto", width: "100%" }}>
          {snapshots.map((s, i) => (
            <motion.div
              key={s.gameweek_id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.06 }}
              style={{
                background: "var(--surface)",
                border: "1px solid var(--divider)",
                borderRadius: 14,
                overflow: "hidden",
              }}
            >
              {/* Card header */}
              <div style={{
                display: "flex", justifyContent: "space-between", alignItems: "center",
                padding: "14px 18px",
                borderBottom: "1px solid var(--divider)",
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span style={{
                    fontFamily: "var(--font-display)", fontSize: 18, fontWeight: 700,
                    color: "var(--text-1)", letterSpacing: "-0.03em",
                  }}>GW{s.gameweek_id}</span>
                  {i === 0 && latestGW && (
                    <span style={{
                      fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 600,
                      color: "var(--amber)", background: "rgba(245,158,11,0.1)",
                      border: "1px solid rgba(245,158,11,0.2)", borderRadius: 20,
                      padding: "2px 8px", letterSpacing: "0.06em",
                    }}>LATEST</span>
                  )}
                  {s.oracle_formation && (
                    <span style={{
                      fontFamily: "var(--font-data)", fontSize: 10, fontWeight: 500,
                      color: "var(--text-3)", letterSpacing: "0.02em",
                      background: "rgba(255,255,255,0.05)", borderRadius: 4,
                      padding: "2px 6px",
                    }}>
                      {s.oracle_formation}
                    </span>
                  )}
                  {s.oracle_cost_millions != null && (
                    <span style={{
                      fontFamily: "var(--font-data)", fontSize: 10, color: "var(--text-3)",
                      background: "rgba(255,255,255,0.05)", borderRadius: 4,
                      padding: "2px 6px",
                    }}>
                      £{s.oracle_cost_millions.toFixed(1)}m
                    </span>
                  )}
                </div>
                {s.resolved ? (
                  <div style={{
                    display: "flex", alignItems: "center", gap: 5,
                    padding: "3px 10px", borderRadius: 20,
                    background: s.oracle_beat_algo ? "rgba(34,197,94,0.08)" : "rgba(239,68,68,0.06)",
                    border: `1px solid ${s.oracle_beat_algo ? "rgba(34,197,94,0.2)" : "rgba(239,68,68,0.2)"}`,
                  }}>
                    <span style={{
                      fontFamily: "var(--font-ui)", fontSize: 10, fontWeight: 600,
                      color: s.oracle_beat_algo ? "var(--green)" : "var(--red)",
                    }}>
                      {s.oracle_beat_algo ? "Oracle beat you" : "You beat Oracle"}
                    </span>
                  </div>
                ) : (
                  <span style={{
                    fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)",
                    background: "var(--surface-2)", border: "1px solid var(--divider)",
                    borderRadius: 4, padding: "2px 8px",
                  }}>GW in play</span>
                )}
              </div>

              <div style={{ padding: "14px 16px", display: "flex", flexDirection: "column", gap: 12 }}>
                {/* Primary metrics: actual pts for resolved GWs, xPts for live */}
                {s.resolved && (s.actual_oracle_points != null || s.actual_algo_points != null) ? (
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
                    {/* Oracle actual */}
                    <div style={{ background: "var(--surface-2)", borderRadius: 10, padding: "10px 12px", border: "1px solid var(--divider)", textAlign: "center" }}>
                      <div style={{ fontFamily: "var(--font-data)", fontSize: 22, fontWeight: 700, color: "var(--amber)", lineHeight: 1 }}>
                        {s.actual_oracle_points?.toFixed(0) ?? "—"}
                      </div>
                      <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--text-3)", textTransform: "uppercase" as const, letterSpacing: "0.06em", marginTop: 4 }}>Oracle actual</div>
                    </div>

                    {/* Your actual */}
                    <div style={{ background: "var(--surface-2)", borderRadius: 10, padding: "10px 12px", border: "1px solid var(--divider)", textAlign: "center" }}>
                      <div style={{ fontFamily: "var(--font-data)", fontSize: 22, fontWeight: 700, color: "var(--text-2)", lineHeight: 1 }}>
                        {s.actual_algo_points?.toFixed(0) ?? "—"}
                      </div>
                      <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--text-3)", textTransform: "uppercase" as const, letterSpacing: "0.06em", marginTop: 4 }}>Your actual</div>
                    </div>

                    {/* #1 FPL team actual — chip badge */}
                    <div
                      style={{
                        background: "var(--surface-2)", borderRadius: 10, padding: "10px 12px",
                        border: s.top_team ? "1px solid rgba(255,255,255,0.1)" : "1px solid var(--divider)",
                        textAlign: "center", position: "relative",
                      }}
                    >
                      {s.top_team ? (
                        <>
                          <div style={{ display: "flex", alignItems: "baseline", justifyContent: "center", gap: 4 }}>
                            <div style={{ fontFamily: "var(--font-data)", fontSize: 22, fontWeight: 700, color: "var(--text-1)", lineHeight: 1 }}>
                              {/* Show normalised score when chip stripped */}
                              {s.top_team.chip && (s.top_team.chip_adjustment ?? 0) > 0
                                ? (s.top_team.display_points ?? s.top_team.points_normalised ?? s.top_team.points ?? "Data unavailable")
                                : (s.top_team.display_points ?? s.top_team.points ?? "Data unavailable")}
                            </div>
                            {/* Chip badge */}
                            {s.top_team.chip && (
                              <span style={{ fontFamily: "var(--font-data)", fontSize: 9, fontWeight: 700, color: "var(--amber)", background: "rgba(245,158,11,0.12)", border: "1px solid rgba(245,158,11,0.3)", borderRadius: 3, padding: "1px 4px" }}>
                                {fmtChip(s.top_team.chip)}
                              </span>
                            )}
                          </div>
                          <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--text-3)", textTransform: "uppercase" as const, letterSpacing: "0.06em", marginTop: 4 }}>
                            {s.top_team.team_name ? s.top_team.team_name.slice(0, 12) : "#1 FPL"}
                          </div>
                        </>
                      ) : (
                        <>
                          {s.resolved ? (
                            /* GW finished but top-team data missing — explicit unavailable state */
                            <>
                              <div style={{ fontFamily: "var(--font-data)", fontSize: 16, fontWeight: 600, color: "rgba(255,255,255,0.2)", lineHeight: 1.2 }}>—</div>
                              <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "rgba(255,255,255,0.25)", textTransform: "uppercase" as const, letterSpacing: "0.05em", marginTop: 5 }}>Data unavailable</div>
                              <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "rgba(255,255,255,0.2)", marginTop: 2, lineHeight: 1.4 }}>Top team data is updated post-GW. Try auto-resolve.</div>
                            </>
                          ) : (
                            /* GW not yet finished */
                            <>
                              <div style={{ fontFamily: "var(--font-data)", fontSize: 22, fontWeight: 700, color: "var(--text-3)", lineHeight: 1 }}>—</div>
                              <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--text-3)", textTransform: "uppercase" as const, letterSpacing: "0.06em", marginTop: 4 }}>#1 FPL</div>
                            </>
                          )}
                        </>
                      )}
                    </div>
                  </div>
                ) : (
                  /* xPts comparison for live/upcoming GWs */
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
                    {[
                      { label: "Oracle xPts", value: s.oracle_xpts?.toFixed(1) ?? "—", color: "var(--amber)" },
                      { label: "Your xPts", value: s.algo_xpts?.toFixed(1) ?? "—", color: "var(--text-2)" },
                      { label: "Gap", value: s.gap_xpts != null ? `+${s.gap_xpts.toFixed(1)}` : "—", color: "var(--green)" },
                    ].map(({ label, value, color }) => (
                      <div key={label} style={{
                        background: "var(--surface-2)", borderRadius: 10, padding: "10px 12px",
                        border: "1px solid var(--divider)", textAlign: "center",
                      }}>
                        <div style={{ fontFamily: "var(--font-data)", fontSize: 22, fontWeight: 700, color, lineHeight: 1 }}>{value}</div>
                        <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--text-3)", textTransform: "uppercase" as const, letterSpacing: "0.06em", marginTop: 4 }}>{label}</div>
                      </div>
                    ))}
                  </div>
                )}

                {/* ── Oracle vs #1 FPL Analysis (post-resolve) ── */}
                {s.resolved && s.top_team && (
                  <div style={{
                    borderRadius: 10, overflow: "hidden",
                    border: "1px solid var(--divider)",
                    background: "var(--surface-2)",
                  }}>
                    {/* Section header */}
                    <div style={{
                      display: "flex", alignItems: "center", justifyContent: "space-between",
                      padding: "9px 12px",
                      borderBottom: "1px solid var(--divider)",
                      background: "rgba(255,255,255,0.02)",
                    }}>
                      <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase" }}>
                        Oracle vs #1 FPL · GW{s.gameweek_id}
                      </span>
                      <span style={{
                        fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 600, padding: "2px 8px", borderRadius: 4,
                        background: s.top_team.status === "unavailable"
                          ? "rgba(255,255,255,0.06)"
                          : s.oracle_beat_top ? "rgba(34,197,94,0.12)" : "rgba(239,68,68,0.1)",
                        color: s.top_team.status === "unavailable"
                          ? "var(--text-3)"
                          : s.oracle_beat_top ? "var(--green)" : "var(--red)",
                        border: `1px solid ${s.top_team.status === "unavailable"
                          ? "rgba(255,255,255,0.1)"
                          : s.oracle_beat_top ? "rgba(34,197,94,0.25)" : "rgba(239,68,68,0.2)"}`,
                      }}>
                        {s.top_team.status === "unavailable" ? "Top team unavailable" : s.oracle_beat_top ? "Oracle won" : "Oracle lost"}
                      </span>
                    </div>

                    <div style={{ padding: "10px 12px", display: "flex", flexDirection: "column", gap: 7 }}>
                      {s.top_team.status === "unavailable" && (
                        <div style={{
                          padding: "8px 10px", borderRadius: 8,
                          background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)",
                          fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-2)", lineHeight: 1.5,
                        }}>
                          Data unavailable. The top GW team could not be resolved from FPL for this gameweek yet.
                        </div>
                      )}
                      {/* Why Oracle was beaten — only shown when it lost */}
                      {s.top_team.status !== "unavailable" && s.oracle_beat_top === false && (
                        <div style={{
                          padding: "8px 10px", borderRadius: 8,
                          background: "rgba(239,68,68,0.06)", border: "1px solid rgba(239,68,68,0.18)",
                        }}>
                          <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--red)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 5 }}>
                            Why Oracle lost
                          </div>
                          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                            {/* Chip advantage */}
                            {s.top_team.chip && (
                              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                                <span style={{ fontFamily: "var(--font-data)", fontSize: 9, fontWeight: 700, color: "var(--amber)", background: "rgba(245,158,11,0.12)", border: "1px solid rgba(245,158,11,0.3)", borderRadius: 3, padding: "1px 5px" }}>
                                  {s.top_team.chip.replace("3xc","Triple Captain").replace("bboost","Bench Boost").replace("freehit","Free Hit").replace("wildcard","Wildcard")}
                                </span>
                                <span style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-2)" }}>
                                  {(s.top_team.chip_adjustment ?? 0) > 0
                                    ? `chip gave +${s.top_team.chip_adjustment} pts advantage`
                                    : "chip advantage — comparison normalised"}
                                </span>
                              </div>
                            )}
                            {/* Captain mismatch */}
                            {s.top_team.captain && s.oracle_captain?.name && s.top_team.captain !== s.oracle_captain.name && (
                              <div style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-2)" }}>
                                Their captain: <strong style={{ color: "var(--text-1)" }}>{s.top_team.captain}</strong> · Oracle captained <strong style={{ color: "var(--amber)" }}>{s.oracle_captain.name}</strong>
                              </div>
                            )}
                            {/* Missed players */}
                            {s.missed_players && s.missed_players.length > 0 && (
                              <div style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-2)" }}>
                                Missed high-scorers:{" "}
                                {s.missed_players.slice(0, 4).map((p, idx) => (
                                  <span key={p}><strong style={{ color: "var(--red)" }}>{p}</strong>{idx < Math.min(3, s.missed_players.length - 1) ? ", " : ""}</span>
                                ))}
                                {s.missed_players.length > 4 && <span style={{ color: "var(--text-3)" }}> +{s.missed_players.length - 4} more</span>}
                              </div>
                            )}
                            {/* Chip miss reason (engine learning) */}
                            {s.top_team.chip_miss_reason && (
                              <div style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--amber)", opacity: 0.85, lineHeight: 1.4 }}>
                                Engine note: {s.top_team.chip_miss_reason.slice(0, 120)}
                              </div>
                            )}
                          </div>
                        </div>
                      )}

                      {/* Captain row */}
                      {s.top_team.status !== "unavailable" && s.top_team.captain && (
                        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                          <span style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em", minWidth: 50 }}>Captain</span>
                          <span style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-2)", fontWeight: 600 }}>{s.top_team.captain}</span>
                        </div>
                      )}

                      {/* Chip strip note */}
                      {s.top_team.status !== "unavailable" && s.top_team.chip && (s.top_team.chip_adjustment ?? 0) > 0 && (
                        <div style={{ display: "flex", alignItems: "center", gap: 6, fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)" }}>
                          <span style={{ fontFamily: "var(--font-ui)", fontSize: 8, fontWeight: 600, color: "var(--amber)", textTransform: "uppercase", letterSpacing: "0.08em" }}>{s.top_team.chip.replace("3xc","TC").replace("bboost","BB")}</span>
                          <span>Raw: {s.top_team.points} pts, normalised: {s.top_team.points_normalised}</span>
                        </div>
                      )}
                    </div>

                    {/* Engine learning — always shown post-resolve */}
                    {s.resolved && (
                      <div style={{
                        borderTop: "1px solid var(--divider)",
                        padding: "8px 12px",
                        background: "rgba(255,255,255,0.01)",
                      }}>
                        <div style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 5 }}>
                          What the engine learned
                        </div>
                        {s.blind_spots?.insight ? (
                          <div style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-2)", lineHeight: 1.5 }}>
                            {s.blind_spots.insight}
                          </div>
                        ) : s.missed_players && s.missed_players.length > 0 ? (
                          <div style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-3)", lineHeight: 1.5 }}>
                            Blind spot: Oracle didn&apos;t pick {s.missed_players.slice(0, 3).join(", ")}{s.missed_players.length > 3 ? ` and ${s.missed_players.length - 3} others` : ""} who scored highly for #1 FPL. Form weighting for these positions adjusted.
                          </div>
                        ) : (() => {
                          const oraclePts = s.actual_oracle_points;
                          const topPts = s.top_team?.points;
                          const chip = s.top_team?.chip;
                          const chipLabel = chip ? chip.replace("3xc","Triple Captain").replace("bboost","Bench Boost").replace("freehit","Free Hit").replace("wildcard","Wildcard") : null;
                          const gap = oraclePts != null && topPts != null ? Math.abs(topPts - oraclePts) : null;
                          const oracleLost = oraclePts != null && topPts != null ? oraclePts < topPts : true;
                          return (
                            <div style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-3)", lineHeight: 1.5 }}>
                              {oracleLost
                                ? <>Oracle scored {oraclePts ?? "—"} pts vs #1 FPL&apos;s {topPts ?? "—"} pts{chipLabel ? ` (they used ${chipLabel})` : ""}. {gap != null ? `${gap}-pt gap` : "Gap"} recorded — model bias adjustment queued for next run.</>
                                : <>Oracle scored {oraclePts ?? "—"} pts vs #1 FPL&apos;s {topPts ?? "—"} pts{chipLabel ? ` (they used ${chipLabel})` : ""}. Oracle beat the top team — prediction residuals within target range.</>
                              }
                            </div>
                          );
                        })()}
                        {/* Show pts gap data if available */}
                        {(s.blind_spots?.top_pts != null || s.blind_spots?.oracle_pts != null) && (
                          <div style={{ display: "flex", gap: 10, marginTop: 6 }}>
                            {s.blind_spots.oracle_pts != null && (
                              <div>
                                <div style={{ fontFamily: "var(--font-data)", fontSize: 12, fontWeight: 700, color: "var(--amber)" }}>{s.blind_spots.oracle_pts}</div>
                                <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--text-3)", textTransform: "uppercase" }}>oracle</div>
                              </div>
                            )}
                            {s.blind_spots.top_pts != null && (
                              <div>
                                <div style={{ fontFamily: "var(--font-data)", fontSize: 12, fontWeight: 700, color: "var(--text-1)" }}>{s.blind_spots.top_pts}</div>
                                <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--text-3)", textTransform: "uppercase" }}>#1 FPL</div>
                              </div>
                            )}
                            {s.blind_spots.gap != null && (
                              <div>
                                <div style={{ fontFamily: "var(--font-data)", fontSize: 12, fontWeight: 700, color: "var(--red)" }}>-{s.blind_spots.gap}</div>
                                <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--text-3)", textTransform: "uppercase" }}>gap</div>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* Formation view — full size for uniform UI/UX */}
                {(s.oracle_squad_with_teams?.length > 0 || s.oracle_squad.length > 0) && (
                  <OracleFormationGrid
                    squad={s.oracle_squad_with_teams?.length > 0 ? s.oracle_squad_with_teams : s.oracle_squad.map(n => ({ name: n, team_code: null, team_short_name: null }))}
                    formation={s.oracle_formation}
                    captain={s.oracle_captain?.name ?? null}
                  />
                )}
              </div>
            </motion.div>
          ))}
        </div>
      )}

    </>
  );
}
