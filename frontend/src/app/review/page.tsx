"use client";
import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  CheckCircle, XCircle, Clock,
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
  actual_gain?: number | null;        // decision-specific gain/loss (player score)
  player_id_primary?: number | null;  // captain player / player_in FPL id
  player_id_secondary?: number | null; // player_out FPL id (transfers)
  player_team_code?: number | null;   // FPL team code for badge (primary player)
  player_out_team_code?: number | null; // FPL team code for badge (secondary/out player)
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
    actual_gw_points?: number | null;
    actual_points_followed?: number | null;
  };
  user_gw_performance?: {
    gw_points?: number | null;
    overall_rank?: number | null;
    transfers_made?: number | null;
    transfer_cost?: number | null;
    chip_played?: string | null;
    points_on_bench?: number | null;
    fpl_avg_pts?: number | null;  // FPL overall average for this GW
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
    avg_actual_gain: number | null;
    last_actual_gain: number | null;
  }>;
  decisions?: Decision[];  // individual decision rows for per-decision audit
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

      {/* Main recommendation text with team badges */}
      {!isChip && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
          {/* Transfers: OUT badge first, then IN badge */}
          {d.player_out_team_code != null && d.player_out_team_code > 0 && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={`https://resources.premierleague.com/premierleague/badges/25/t${d.player_out_team_code}.png`}
              alt="" width={18} height={18}
              style={{ objectFit: "contain", opacity: 0.7, flexShrink: 0 }}
              onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
            />
          )}
          {/* Captain / transfer IN: primary player badge */}
          {d.player_team_code != null && d.player_team_code > 0 && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={`https://resources.premierleague.com/premierleague/badges/25/t${d.player_team_code}.png`}
              alt="" width={18} height={18}
              style={{ objectFit: "contain", opacity: 0.9, flexShrink: 0 }}
              onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
            />
          )}
          <span style={{ fontFamily: "var(--font-ui)", fontSize: 13, fontWeight: 600, color: "var(--text-1)" }}>
            {d.recommended_option}
          </span>
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

      {/* Points row — expected xPts and actual gain for this decision */}
      {(showExpected || d.actual_gain != null) && (
        <div style={{ display: "flex", gap: 12, marginTop: 6, alignItems: "flex-end" }}>
          {showExpected && (
            <div>
              <div style={{ fontSize: 9, color: "var(--text-3)", fontFamily: "var(--font-ui)", letterSpacing: "0.06em", textTransform: "uppercase" }}>predicted</div>
              <div style={{ fontFamily: "var(--font-data)", fontSize: 14, color: "var(--text-2)", fontWeight: 600 }}>
                +{d.expected_points!.toFixed(1)}
              </div>
            </div>
          )}
          {d.actual_gain != null && d.decision_followed && (
            <div>
              <div style={{ fontSize: 9, color: "var(--text-3)", fontFamily: "var(--font-ui)", letterSpacing: "0.06em", textTransform: "uppercase" }}>
                {d.decision_type?.toLowerCase().includes("captain") ? "captain scored" : "net gain"}
              </div>
              <div style={{
                fontFamily: "var(--font-data)", fontSize: 14, fontWeight: 700,
                color: d.actual_gain >= 0 ? "var(--green)" : "var(--red)",
              }}>
                {d.actual_gain >= 0 ? "+" : ""}{d.actual_gain.toFixed(1)} pts
              </div>
            </div>
          )}
          {d.actual_gain != null && !d.decision_followed && (
            <div>
              <div style={{ fontSize: 9, color: "var(--text-3)", fontFamily: "var(--font-ui)", letterSpacing: "0.06em", textTransform: "uppercase" }}>would have gained</div>
              <div style={{
                fontFamily: "var(--font-data)", fontSize: 14, fontWeight: 700,
                color: "var(--text-3)", opacity: 0.7,
              }}>
                {d.actual_gain >= 0 ? "+" : ""}{d.actual_gain.toFixed(1)} pts
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
  gw_average?: number | null;
  oracle_vs_avg?: number | null;
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
      let fplCurrentGwId = 0; // actual is_current GW from FPL (not planning GW)
      if (gwRes.ok) {
        loadedGwReview = await gwRes.json();
        setGwReview(loadedGwReview);
        // Load cross-check keyed by GW — prevents stale data from a prior GW
        if (loadedGwReview && typeof window !== "undefined") {
          const ccKey = `fpl_crosscheck_${teamId}_gw${loadedGwReview.gameweek_id}`;
          const saved = localStorage.getItem(ccKey);
          if (saved) {
            try {
              const parsed = JSON.parse(saved);
              if (parsed && typeof parsed.verified_count === "number" && typeof parsed.total_checks === "number") {
                setCrossCheck(parsed);
              } else {
                localStorage.removeItem(ccKey);
                setCrossCheck(null);
              }
            } catch { setCrossCheck(null); }
          } else {
            setCrossCheck(null); // clear stale result from a previous GW
          }
        }
      }
      if (seasonRes.ok) setSeasonReview(await seasonRes.json());
      let loadedSnapshots: OracleSnapshot[] = [];
      if (oracleRes.ok) {
        const d = await oracleRes.json();
        loadedSnapshots = d.snapshots || [];
        setOracleHistory(loadedSnapshots);
      }
      if (txRes.ok) setTransfersReview(await txRes.json());
      if (chipRes.ok) setActiveChip(await chipRes.json());
      if (gwStateRes.ok) {
        const gwStateData = await gwStateRes.json();
        fplCurrentGwId = gwStateData.current_gw ?? 0;
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
        // Auto-run cross-check when deadline has passed and no saved result for THIS GW
        if (gwStateData.state === "deadline_passed" && loadedGwReview) {
          const savedKey = `fpl_crosscheck_${teamId}_gw${loadedGwReview.gameweek_id}`;
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
      // ── Oracle auto-actions (silent, on page load) ──────────────────────────
      // 1. Compute snapshot if no snapshot exists for the CURRENT GW.
      //    Use the FPL is_current GW (e.g. GW31), NOT the latest decision GW (which
      //    may be GW32 planning). This prevents an infinite loop where GW32 planning
      //    decisions cause us to keep recreating a GW32 snapshot that the backend
      //    intentionally excludes from history (unresolved future GW).
      const currentGwId = fplCurrentGwId || (loadedGwReview?.gameweek_id ?? 0);
      const latestSnapshotGw = loadedSnapshots.length > 0
        ? Math.max(...loadedSnapshots.map((s: OracleSnapshot) => s.gameweek_id))
        : 0;
      const missingCurrentGwSnapshot = currentGwId > 0 && !loadedSnapshots.some(
        (s: OracleSnapshot) => s.gameweek_id === currentGwId
      );
      if (missingCurrentGwSnapshot && teamId) {
        try {
          setTakingSnapshot(true);
          // Compute for current GW first
          await fetch(`${API}/api/oracle/snapshot?team_id=${teamId}`, { method: "POST" });
          // If there's a gap (e.g. GW30→GW32, missing GW31), backfill it
          if (latestSnapshotGw > 0 && currentGwId - latestSnapshotGw > 1) {
            await fetch(`${API}/api/oracle/backfill?team_id=${teamId}&from_gw=${latestSnapshotGw + 1}&to_gw=${currentGwId - 1}`, { method: "POST" });
          }
          const refreshed = await fetch(`${API}/api/oracle/history?team_id=${teamId}&limit=10`);
          if (refreshed.ok) {
            const rd = await refreshed.json();
            loadedSnapshots = rd.snapshots || [];
            setOracleHistory(loadedSnapshots);
          }
        } catch { /* non-fatal */ }
        finally { setTakingSnapshot(false); }
      }

      // 2. If snapshots exist but some are unresolved → auto-resolve silently.
      //    Backend only resolves finished GWs, so this is always safe to call.
      const hasUnresolved_ = loadedSnapshots.some(
        (s: OracleSnapshot) => !s.resolved || s.actual_algo_points == null || s.actual_oracle_points == null || !s.top_team || s.top_team?.status === "unavailable"
      );
      if (hasUnresolved_ && teamId && loadedSnapshots.length > 0) {
        try {
          setAutoResolving(true);
          await fetch(`${API}/api/oracle/auto-resolve?team_id=${teamId}`, { method: "POST" });
          const refreshed = await fetch(`${API}/api/oracle/history?team_id=${teamId}&limit=10`);
          if (refreshed.ok) {
            const rd = await refreshed.json();
            setOracleHistory(rd.snapshots || []);
          }
        } catch { /* non-fatal */ }
        finally { setAutoResolving(false); }
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
          localStorage.setItem(`fpl_crosscheck_${teamId}_gw${gwReview.gameweek_id}`, JSON.stringify(data));
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


      </motion.div>


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
          {/* GW in play — always show live-only view when deadline_passed, regardless of partial history */}
          {gwState === "deadline_passed" ? (
            <div style={{ display: "flex", gap: 8 }}>
              {liveGwPts != null && (
                <div style={{ flex: 1, textAlign: "center", padding: "8px 6px", borderRadius: 8, background: "rgba(245,158,11,0.07)", border: "1px solid rgba(245,158,11,0.2)" }}>
                  <div style={{ fontFamily: "var(--font-data)", fontSize: 20, fontWeight: 700, color: "var(--amber)" }}>{liveGwPts}</div>
                  <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--amber)", textTransform: "uppercase", letterSpacing: "0.06em", opacity: 0.8 }}>live pts</div>
                </div>
              )}
              {perf?.overall_rank != null && perf.overall_rank > 0 && (
                <div style={{ flex: 1, textAlign: "center", padding: "8px 6px", borderRadius: 8, background: "rgba(255,255,255,0.03)", border: "1px solid var(--divider)" }}>
                  <div style={{ fontFamily: "var(--font-data)", fontSize: 20, fontWeight: 700, color: "var(--text-1)" }}>{perf.overall_rank.toLocaleString()}</div>
                  <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>rank</div>
                </div>
              )}
              <div style={{ flex: 2, padding: "8px 10px", borderRadius: 8, background: "rgba(255,255,255,0.02)", border: "1px solid var(--divider)", display: "flex", alignItems: "center" }}>
                <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)", lineHeight: 1.5 }}>
                  Avg pts &amp; bench pts update after all GW fixtures finish.
                </span>
              </div>
            </div>
          ) : (
          <div style={{ display: "flex", gap: 8 }}>
            {/* Live pts — primary when GW active */}
            {liveGwPts != null && (
              <div style={{ flex: 1, textAlign: "center", padding: "8px 6px", borderRadius: 8, background: "rgba(245,158,11,0.07)", border: "1px solid rgba(245,158,11,0.2)" }}>
                <div style={{ fontFamily: "var(--font-data)", fontSize: 20, fontWeight: 700, color: "var(--amber)" }}>{liveGwPts}</div>
                <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--amber)", textTransform: "uppercase", letterSpacing: "0.06em", opacity: 0.8 }}>live pts</div>
              </div>
            )}
            {/* Settled GW pts — only when no live score */}
            {perf?.gw_points != null && perf.gw_points > 0 && liveGwPts == null && (
              <div style={{ flex: 1, textAlign: "center", padding: "8px 6px", borderRadius: 8, background: "rgba(255,255,255,0.03)", border: "1px solid var(--divider)" }}>
                <div style={{ fontFamily: "var(--font-data)", fontSize: 20, fontWeight: 700, color: "var(--text-1)" }}>{perf.gw_points}</div>
                <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>GW pts</div>
              </div>
            )}
            {/* FPL overall GW average — labelled clearly */}
            {perf?.fpl_avg_pts != null && perf.fpl_avg_pts > 0 && (
              <div style={{ flex: 1, textAlign: "center", padding: "8px 6px", borderRadius: 8, background: "rgba(255,255,255,0.03)", border: "1px solid var(--divider)" }}>
                <div style={{ fontFamily: "var(--font-data)", fontSize: 20, fontWeight: 700, color: "var(--text-3)" }}>{perf.fpl_avg_pts}</div>
                <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>FPL avg</div>
              </div>
            )}
            {perf?.overall_rank != null && perf.overall_rank > 0 && (
              <div style={{ flex: 1, textAlign: "center", padding: "8px 6px", borderRadius: 8, background: "rgba(255,255,255,0.03)", border: "1px solid var(--divider)" }}>
                <div style={{ fontFamily: "var(--font-data)", fontSize: 20, fontWeight: 700, color: "var(--text-1)" }}>{perf.overall_rank.toLocaleString()}</div>
                <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>rank</div>
              </div>
            )}
            {perf?.points_on_bench != null && perf.points_on_bench > 0 && (
              <div style={{ flex: 1, textAlign: "center", padding: "8px 6px", borderRadius: 8, background: "rgba(255,255,255,0.03)", border: "1px solid var(--divider)" }}>
                <div style={{ fontFamily: "var(--font-data)", fontSize: 20, fontWeight: 700, color: "var(--text-1)" }}>{perf.points_on_bench}</div>
                <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>bench pts</div>
              </div>
            )}
          </div>
          )}
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
                  <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>expected xP gain</div>
                  <div style={{ fontFamily: "var(--font-data)", fontSize: 13, color: "var(--text-2)", fontWeight: 600 }}>
                    {tx.ai_decision.expected_points.toFixed(1)}
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

// ── Accuracy verdict helpers ──────────────────────────────────────────────────

const SEASON_CHIP_LABEL: Record<string, string> = {
  triple_captain: "Triple Captain",
  bench_boost: "Bench Boost",
  free_hit: "Free Hit",
  wildcard: "Wildcard",
};

function getSeasonDecisionLabel(d: Decision): string {
  if (d.decision_type === "CHIP_USED") {
    const key = (d.recommended_option || "").toLowerCase().replace(/\s+/g, "_");
    return SEASON_CHIP_LABEL[key] || d.recommended_option || "Chip";
  }
  return d.decision_type
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function getSeasonDecisionColor(d: Decision): string {
  const dt = (d.decision_type || "").toLowerCase();
  const ro = (d.recommended_option || "").toLowerCase().replace(/\s+/g, "_");
  if (dt.includes("captain")) return "var(--amber)";
  if (dt === "chip_used" || dt === "chip") {
    if (ro.includes("triple_captain")) return "var(--amber)";
    if (ro.includes("free_hit")) return "var(--green)";
    if (ro.includes("bench_boost")) return "var(--blue)";
    return "var(--text-2)";
  }
  if (dt.includes("transfer")) return "var(--blue)";
  return "var(--text-2)";
}

interface AccuracyVerdict {
  label: string;
  color: string;
  errorPts: number;
  errorPct: number;
  modelLearn: string;
}

function computeAccuracyVerdict(
  predicted: number | null | undefined,
  actual: number | null | undefined,
  followed: boolean | null | undefined,
  dt: string
): AccuracyVerdict | null {
  if (predicted == null || predicted < 0.5) return null;
  if (actual == null) return null;
  if (!followed) return null;

  const error = predicted - actual;
  const absError = Math.abs(error);
  const errorPct = (absError / Math.abs(predicted)) * 100;
  const dtLower = dt.toLowerCase();
  const thingName = dtLower.includes("captain")
    ? "captaincy value"
    : dtLower.includes("transfer")
    ? "transfer gain"
    : "impact value";

  if (errorPct <= 20) {
    return {
      label: "ON TARGET",
      color: "var(--green)",
      errorPts: error,
      errorPct,
      modelLearn: "Accurate prediction. Model confidence reinforced — no adjustment needed.",
    };
  }
  if (error > 0 && errorPct <= 50) {
    return {
      label: "SLIGHT OVERESTIMATE",
      color: "var(--amber)",
      errorPts: error,
      errorPct,
      modelLearn: `Model overestimated ${thingName} by ${errorPct.toFixed(0)}%. Within acceptable range — minor calibration applied.`,
    };
  }
  if (error < 0 && errorPct <= 50) {
    return {
      label: "SLIGHT UNDERESTIMATE",
      color: "var(--amber)",
      errorPts: error,
      errorPct,
      modelLearn: `Model underestimated ${thingName} by ${errorPct.toFixed(0)}%. Within acceptable range — minor calibration applied.`,
    };
  }
  if (error > 0) {
    return {
      label: "OVERESTIMATE",
      color: "var(--red)",
      errorPts: error,
      errorPct,
      modelLearn: `Model overestimated ${thingName} by ${errorPct.toFixed(0)}%. Learning: recalibrating xPts ceiling down for similar scenarios.`,
    };
  }
  return {
    label: "UNDERESTIMATE",
    color: "var(--blue)",
    errorPts: error,
    errorPct,
    modelLearn: `Model underestimated ${thingName} by ${errorPct.toFixed(0)}%. Learning: recalibrating xPts floor up for similar scenarios.`,
  };
}

// ── Per-decision audit card ───────────────────────────────────────────────────

function DecisionAuditCard({ d }: { d: Decision }) {
  const color = getSeasonDecisionColor(d);
  const label = getSeasonDecisionLabel(d);
  const isChip = d.decision_type === "CHIP_USED" || d.decision_type.toLowerCase() === "chip";
  const verdict = computeAccuracyVerdict(
    d.expected_points,
    d.actual_gain,
    d.decision_followed,
    d.decision_type
  );

  const showPredicted = d.expected_points != null && !(isChip && (d.expected_points === 0 || d.expected_points === 0.0));
  const actualLabel = d.decision_type.toLowerCase().includes("captain")
    ? "captain scored"
    : "actual gain";

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      style={{
        borderRadius: 12,
        background: "var(--surface)",
        border: "1px solid var(--divider)",
        borderLeft: `3px solid ${color}`,
        marginBottom: 10,
        overflow: "hidden",
      }}
    >
      {/* Card header: GW badge + type label + followed/ignored */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 14px 8px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
          <span style={{
            fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 700,
            color: "var(--text-3)", background: "rgba(255,255,255,0.04)",
            border: "1px solid var(--divider)", borderRadius: 4, padding: "2px 6px",
            letterSpacing: "0.06em",
          }}>
            GW{d.gameweek_id}
          </span>
          <span style={{
            fontFamily: "var(--font-ui)", fontSize: 11, fontWeight: 700,
            color, letterSpacing: "0.04em", textTransform: "uppercase",
          }}>
            {label}
          </span>
        </div>
        {/* Followed / Ignored / Pending indicator */}
        <span style={{
          display: "flex", alignItems: "center", gap: 4,
          fontFamily: "var(--font-ui)", fontSize: 10, fontWeight: 600,
          color: d.decision_followed === true
            ? "var(--green)"
            : d.decision_followed === false
            ? "var(--red)"
            : "var(--text-3)",
        }}>
          {d.decision_followed === true
            ? <><CheckCircle size={11} />Followed</>
            : d.decision_followed === false
            ? <><XCircle size={11} />Ignored</>
            : <><Clock size={11} />Pending</>}
        </span>
      </div>

      {/* Body */}
      <div style={{ padding: "0 14px 12px" }}>
        {/* What was recommended — with team badge(s) */}
        <div style={{
          display: "flex", alignItems: "center", gap: 8,
          fontFamily: "var(--font-ui)", fontSize: 13, fontWeight: 600,
          color: "var(--text-1)", marginBottom: 10, lineHeight: 1.3,
        }}>
          {!isChip && d.player_out_team_code != null && d.player_out_team_code > 0 && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={`https://resources.premierleague.com/premierleague/badges/25/t${d.player_out_team_code}.png`}
              alt="" width={20} height={20}
              style={{ objectFit: "contain", opacity: 0.7, flexShrink: 0 }}
              onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
            />
          )}
          {!isChip && d.player_team_code != null && d.player_team_code > 0 && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={`https://resources.premierleague.com/premierleague/badges/25/t${d.player_team_code}.png`}
              alt="" width={20} height={20}
              style={{ objectFit: "contain", opacity: 0.95, flexShrink: 0 }}
              onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
            />
          )}
          <span>
            {isChip
              ? `${SEASON_CHIP_LABEL[(d.recommended_option || "").toLowerCase().replace(/\s+/g, "_")] || d.recommended_option} chip`
              : d.recommended_option}
          </span>
        </div>

        {/* Predicted vs Actual numbers */}
        {(showPredicted || d.actual_gain != null) && (
          <div style={{ display: "flex", gap: 24, marginBottom: verdict || (d.decision_followed === false && showPredicted) ? 10 : 0, alignItems: "flex-end" }}>
            {showPredicted && (
              <div>
                <div style={{
                  fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--text-3)",
                  letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 3,
                }}>
                  model predicted
                </div>
                <div style={{
                  fontFamily: "var(--font-data)", fontSize: 22, fontWeight: 700,
                  color: "var(--text-2)", letterSpacing: "-0.04em",
                }}>
                  +{d.expected_points!.toFixed(1)}
                  <span style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-3)", marginLeft: 2 }}>pts</span>
                </div>
              </div>
            )}

            {d.actual_gain != null && d.decision_followed === true && (
              <div>
                <div style={{
                  fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--text-3)",
                  letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 3,
                }}>
                  {actualLabel}
                </div>
                <div style={{
                  fontFamily: "var(--font-data)", fontSize: 22, fontWeight: 700,
                  letterSpacing: "-0.04em",
                  color: verdict
                    ? verdict.color
                    : d.actual_gain >= 0
                    ? "var(--green)"
                    : "var(--red)",
                }}>
                  {d.actual_gain >= 0 ? "+" : ""}{d.actual_gain.toFixed(1)}
                  <span style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-3)", marginLeft: 2 }}>pts</span>
                </div>
              </div>
            )}

            {d.actual_gain != null && d.decision_followed === false && (
              <div>
                <div style={{
                  fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--text-3)",
                  letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 3,
                }}>
                  would have gained
                </div>
                <div style={{
                  fontFamily: "var(--font-data)", fontSize: 22, fontWeight: 700,
                  color: "var(--text-3)", letterSpacing: "-0.04em", opacity: 0.65,
                }}>
                  {d.actual_gain >= 0 ? "+" : ""}{d.actual_gain.toFixed(1)}
                  <span style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-3)", marginLeft: 2 }}>pts</span>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Accuracy verdict box — only when prediction + actual both available */}
        {verdict && (
          <div style={{
            background: `${verdict.color}0d`,
            border: `1px solid ${verdict.color}2a`,
            borderRadius: 8,
            padding: "8px 10px",
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 3 }}>
              <span style={{
                fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 700,
                color: verdict.color, letterSpacing: "0.1em",
              }}>
                {verdict.label}
              </span>
              <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)" }}>
                {Math.abs(verdict.errorPts).toFixed(1)} pts off · {verdict.errorPct.toFixed(0)}% error
              </span>
            </div>
            <div style={{
              fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-3)", lineHeight: 1.55,
            }}>
              {verdict.modelLearn}
            </div>
          </div>
        )}

        {/* Ignored with known prediction — show missed opportunity */}
        {d.decision_followed === false && showPredicted && d.actual_gain == null && (
          <div style={{
            fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-3)",
            lineHeight: 1.55, marginTop: 2,
          }}>
            Not followed before deadline. Engine had predicted +{d.expected_points!.toFixed(1)} pts gain.
          </div>
        )}

        {/* Chip followed, no expected pts — show resolved status or pending */}
        {isChip && d.decision_followed === true && !showPredicted && d.actual_gain == null && (
          <div style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-3)", lineHeight: 1.55 }}>
            {d.actual_points != null
              ? `Chip played in GW${d.gameweek_id}. GW resolved.`
              : `Chip played in GW${d.gameweek_id}. Awaiting GW resolution.`}
          </div>
        )}

        {/* Followed, has a prediction, but GW not yet resolved (no team score yet) */}
        {!isChip && d.decision_followed === true && showPredicted && d.actual_points == null && (
          <div style={{
            marginTop: 2,
            display: "flex", alignItems: "center", gap: 5,
            fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--amber)",
            lineHeight: 1.55,
          }}>
            <Clock size={10} />
            GW{d.gameweek_id} in progress — awaiting final score.
          </div>
        )}

        {/* Followed, GW resolved, but no individual gain tracked (transfers) */}
        {!isChip && d.decision_followed === true && showPredicted && d.actual_points != null && d.actual_gain == null && (
          <div style={{
            marginTop: 2,
            fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-3)",
            lineHeight: 1.55,
          }}>
            Transfer outcome — individual gain not separately tracked.
          </div>
        )}

        {/* TC chip: explain predicted vs actual discrepancy */}
        {isChip && d.decision_followed === true && showPredicted && d.actual_gain != null && (
          <div style={{
            marginTop: 2, fontFamily: "var(--font-ui)", fontSize: 10,
            color: "var(--text-3)", lineHeight: 1.55,
          }}>
            Predicted: total captain score ×3 = {d.expected_points!.toFixed(1)} pts.
            {" "}Actual bonus gained over regular captaincy: {d.actual_gain.toFixed(1)} pts.
          </div>
        )}
      </div>
    </motion.div>
  );
}

// ── Season view ───────────────────────────────────────────────────────────────

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

  // Sort individual decisions newest-first (by GW descending, then created_at descending)
  const auditDecisions = [...(review.decisions || [])].sort(
    (a, b) => (b.gameweek_id - a.gameweek_id) || ((b.created_at || "") > (a.created_at || "") ? 1 : -1)
  );

  return (
    <>
      {/* ── Season summary stats ─────────────────────────────────────────────── */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="glass"
        style={{ padding: 16, borderRadius: 12, marginBottom: 16 }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
          <div style={{ fontFamily: "var(--font-ui)", fontSize: 11, fontWeight: 600, color: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase" }}>
            Season Overview
          </div>
          {(review as any).pending_decisions > 0 && (
            <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 600, color: "var(--amber)", background: "rgba(245,158,11,0.1)", border: "1px solid rgba(245,158,11,0.2)", borderRadius: 20, padding: "2px 8px", letterSpacing: "0.06em" }}>
              {(review as any).pending_decisions} actionable
            </span>
          )}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 10 }}>
          {[
            { label: "decisions tracked", value: String(review.total_decisions), color: undefined as string | undefined },
            { label: "followed / ignored", value: `${review.followed ?? 0} / ${review.ignored ?? 0}`, color: undefined },
            {
              label: "adherence rate",
              value: `${((review.adherence_rate || 0) * 100).toFixed(0)}%`,
              color: (review.adherence_rate || 0) >= 0.7
                ? "var(--green)"
                : (review.adherence_rate || 0) >= 0.4
                ? "var(--amber)"
                : "var(--red)",
            },
            {
              label: "vs GW average",
              value: review.net_pts_vs_ai != null
                ? `${review.net_pts_vs_ai >= 0 ? "+" : ""}${review.net_pts_vs_ai.toFixed(1)}`
                : "—",
              color: (review.net_pts_vs_ai || 0) >= 0 ? "var(--green)" : "var(--red)",
            },
          ].map(({ label, value, color }) => (
            <div key={label} style={{ padding: "10px 12px", background: "var(--surface)", borderRadius: 8, border: "1px solid var(--divider)" }}>
              <div style={{ fontFamily: "var(--font-data)", fontSize: 18, fontWeight: 700, color: color || "var(--text-1)", letterSpacing: "-0.02em" }}>{value}</div>
              <div style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em", marginTop: 2 }}>{label}</div>
            </div>
          ))}
        </div>
        {(review as any).resolved_gw_count != null && (
          <div style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-3)", lineHeight: 1.5 }}>
            {(review as any).resolved_gw_count === 0
              ? "No resolved GWs yet — stats appear once a GW settles."
              : `Based on ${(review as any).resolved_gw_count} resolved GW${(review as any).resolved_gw_count !== 1 ? "s" : ""}. Ignored = recommended but deadline passed without action.`}
          </div>
        )}
      </motion.div>

      {/* ── Decision audit ───────────────────────────────────────────────────── */}
      {auditDecisions.length > 0 && (
        <>
          <div style={{
            fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 700,
            color: "var(--text-3)", letterSpacing: "0.12em",
            textTransform: "uppercase", marginBottom: 10,
          }}>
            Decision Audit
          </div>
          {auditDecisions.map((d) => (
            <DecisionAuditCard key={d.id} d={d} />
          ))}
        </>
      )}

      {/* Fallback: show aggregate by_decision_type if no individual rows returned */}
      {auditDecisions.length === 0 && review.by_decision_type && (
        Object.entries(review.by_decision_type).map(([dt, stats]) => (
          <motion.div
            key={dt}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            style={{ padding: "12px 14px", borderRadius: 10, background: "var(--surface)", border: "1px solid var(--divider)", marginBottom: 8 }}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
              <span style={{ fontFamily: "var(--font-ui)", fontSize: 12, fontWeight: 600, color: "var(--text-1)", textTransform: "capitalize" }}>
                {dt.replace(/_/g, " ")}
              </span>
              <span style={{ fontFamily: "var(--font-data)", fontSize: 12, color: stats.adherence_rate > 0.6 ? "var(--green)" : stats.adherence_rate > 0 ? "var(--amber)" : "var(--red)" }}>
                {stats.followed}✓ {stats.ignored}✗
              </span>
            </div>
            <div style={{ display: "flex", gap: 16 }}>
              <div>
                <div style={{ fontFamily: "var(--font-data)", fontSize: 16, fontWeight: 600, color: "var(--text-2)" }}>{stats.avg_expected.toFixed(1)}</div>
                <div style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>model predicted</div>
              </div>
              {stats.avg_actual_gain != null && (
                <div>
                  <div style={{ fontFamily: "var(--font-data)", fontSize: 16, fontWeight: 700, color: stats.avg_actual_gain >= 0 ? "var(--green)" : "var(--red)" }}>
                    {stats.avg_actual_gain >= 0 ? "+" : ""}{(stats.avg_actual_gain as number).toFixed(1)}
                  </div>
                  <div style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                    {dt.toLowerCase().includes("captain") ? "captain scored" : "actual gain"}
                  </div>
                </div>
              )}
            </div>
          </motion.div>
        ))
      )}
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
                  <div key={pi} title={name} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 3, cursor: "default" }}>
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
        {/* Auto-snapshot & auto-resolve status — no manual buttons needed */}
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {(takingSnapshot || autoResolving) && (
            <span style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-3)", display: "flex", alignItems: "center", gap: 5 }}>
              <motion.span animate={{ opacity: [0.4, 1, 0.4] }} transition={{ repeat: Infinity, duration: 1.4 }} style={{ display: "inline-block", width: 6, height: 6, borderRadius: "50%", background: "var(--green)" }} />
              {takingSnapshot ? "Computing oracle…" : "Updating results…"}
            </span>
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
          <motion.div style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--amber)", margin: "0 auto 16px" }} animate={{ opacity: [0.3, 0.9, 0.3] }} transition={{ repeat: Infinity, duration: 1.8 }} />
          <p style={{ fontFamily: "var(--font-ui)", fontSize: 13, color: "var(--text-3)", lineHeight: 1.7, margin: 0 }}>
            Computing oracle squad…
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
                              {/* Always show the real FPL score — normalisation is only for Oracle comparison */}
                              {s.top_team.points ?? "—"}
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
                              <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "rgba(255,255,255,0.2)", marginTop: 2, lineHeight: 1.4 }}>Updates automatically after GW settles.</div>
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

                {/* ── Oracle vs GW average context ── */}
                {s.resolved && s.actual_oracle_points != null && s.gw_average != null && (
                  <div style={{ display: "flex", gap: 8, alignItems: "center", padding: "6px 10px", borderRadius: 7, background: "rgba(255,255,255,0.03)", border: "1px solid var(--divider)" }}>
                    <span style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-3)" }}>
                      GW avg: <strong style={{ color: "var(--text-2)" }}>{s.gw_average}</strong>
                    </span>
                    <span style={{ fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--text-3)", marginLeft: 4 }}>·</span>
                    <span style={{ fontFamily: "var(--font-ui)", fontSize: 10, fontWeight: 600,
                      color: (s.oracle_vs_avg ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>
                      Oracle {(s.oracle_vs_avg ?? 0) >= 0 ? "+" : ""}{s.oracle_vs_avg?.toFixed(0)} vs avg
                    </span>
                    <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)", marginLeft: "auto", lineHeight: 1.4 }}>
                      Benchmark: best team (top 250 scan)
                    </span>
                  </div>
                )}

                {/* ── Oracle vs #1 FPL Analysis (post-resolve) — plain English ── */}
                {s.resolved && (() => {
                  const tt = s.top_team;
                  const noData = !tt || tt.status === "unavailable";
                  const oraclePts = s.actual_oracle_points ?? 0;
                  // Always use normalised pts for the fair comparison (chip stripped)
                  const topFairPts = tt?.points_normalised ?? tt?.points ?? 0;
                  const topRawPts = tt?.points ?? 0;
                  const chipAdj = tt?.chip_adjustment ?? 0;
                  const chip = tt?.chip;
                  const CHIP_NAMES: Record<string, string> = { bboost: "Bench Boost", "3xc": "Triple Captain", freehit: "Free Hit", wildcard: "Wildcard" };
                  const chipName = chip ? (CHIP_NAMES[chip] ?? chip) : null;
                  const gap = topFairPts - oraclePts; // positive = oracle lost by this much
                  const oracleLost = s.oracle_beat_top === false;
                  const captainMatch = tt?.captain && s.oracle_captain?.name && tt.captain === s.oracle_captain.name;
                  const captainMismatch = tt?.captain && s.oracle_captain?.name && tt.captain !== s.oracle_captain.name;

                  return (
                    <div style={{ borderRadius: 10, overflow: "hidden", border: `1px solid ${oracleLost ? "rgba(239,68,68,0.2)" : noData ? "var(--divider)" : "rgba(34,197,94,0.2)"}`, background: "var(--surface-2)" }}>
                      {/* Header */}
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 14px", borderBottom: "1px solid var(--divider)", background: "rgba(255,255,255,0.02)" }}>
                        <span style={{ fontFamily: "var(--font-ui)", fontSize: 11, fontWeight: 600, color: "var(--text-2)" }}>
                          GW{s.gameweek_id} · Oracle vs best FPL team
                        </span>
                        {!noData && (
                          <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
                            <span style={{ fontFamily: "var(--font-data)", fontSize: 18, fontWeight: 700, color: "var(--amber)" }}>{oraclePts}</span>
                            <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)" }}>vs</span>
                            <span style={{ fontFamily: "var(--font-data)", fontSize: 18, fontWeight: 700, color: oracleLost ? "var(--red)" : "var(--green)" }}>{topFairPts}</span>
                            {oracleLost && gap > 0 && (
                              <span style={{ fontFamily: "var(--font-ui)", fontSize: 9, fontWeight: 600, color: "var(--red)", background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.2)", borderRadius: 4, padding: "1px 5px" }}>
                                −{gap} pts
                              </span>
                            )}
                          </div>
                        )}
                      </div>

                      <div style={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: 10 }}>
                        {noData ? (
                          <p style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-3)", margin: 0 }}>
                            Top team data updates automatically after each GW settles.
                          </p>
                        ) : (
                          <>
                            {/* ── Chip explanation ── */}
                            {chipName && chipAdj > 0 && (
                              <div style={{ padding: "10px 12px", borderRadius: 8, background: "rgba(245,158,11,0.06)", border: "1px solid rgba(245,158,11,0.2)" }}>
                                <div style={{ fontFamily: "var(--font-ui)", fontSize: 11, fontWeight: 600, color: "var(--amber)", marginBottom: 4 }}>
                                  The best team used {chipName}
                                </div>
                                <div style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-2)", lineHeight: 1.6 }}>
                                  {chip === "bboost"
                                    ? `Their bench players scored ${chipAdj} extra points thanks to the Bench Boost chip. Oracle doesn't use chips, so to compare fairly we remove those ${chipAdj} points. Their real score was ${topRawPts} — we compare against ${topFairPts} (without bench boost).`
                                    : chip === "3xc"
                                    ? `They used Triple Captain — their captain scored ${chipAdj} extra points. Oracle captains normally (2×), so to compare fairly we remove those ${chipAdj} points. Their real score was ${topRawPts} — we compare against ${topFairPts}.`
                                    : `They used ${chipName} and gained ${chipAdj} extra points from it. We compare against ${topFairPts} (chip points removed for a fair comparison).`
                                  }
                                </div>
                              </div>
                            )}

                            {/* ── Score comparison ── */}
                            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                              <div style={{ padding: "8px 10px", borderRadius: 8, background: "rgba(245,158,11,0.06)", border: "1px solid rgba(245,158,11,0.15)", textAlign: "center" }}>
                                <div style={{ fontFamily: "var(--font-data)", fontSize: 22, fontWeight: 700, color: "var(--amber)" }}>{oraclePts}</div>
                                <div style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em", marginTop: 2 }}>Oracle scored</div>
                              </div>
                              <div style={{ padding: "8px 10px", borderRadius: 8, background: oracleLost ? "rgba(239,68,68,0.06)" : "rgba(34,197,94,0.06)", border: `1px solid ${oracleLost ? "rgba(239,68,68,0.15)" : "rgba(34,197,94,0.15)"}`, textAlign: "center" }}>
                                <div style={{ fontFamily: "var(--font-data)", fontSize: 22, fontWeight: 700, color: oracleLost ? "var(--red)" : "var(--green)" }}>{topFairPts}</div>
                                <div style={{ fontFamily: "var(--font-ui)", fontSize: 9, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em", marginTop: 2 }}>Best team{chipAdj > 0 ? " (no chip)" : ""}</div>
                              </div>
                            </div>

                            {/* ── Captain ── */}
                            <div style={{ display: "flex", gap: 8, alignItems: "flex-start", flexWrap: "wrap" as const }}>
                              <div style={{ padding: "6px 10px", borderRadius: 7, background: "rgba(255,255,255,0.04)", border: "1px solid var(--divider)", flex: 1, minWidth: 100 }}>
                                <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 3 }}>Oracle captain</div>
                                <div style={{ fontFamily: "var(--font-ui)", fontSize: 12, fontWeight: 600, color: "var(--amber)" }}>{s.oracle_captain?.name ?? "—"}</div>
                              </div>
                              <div style={{ padding: "6px 10px", borderRadius: 7, background: "rgba(255,255,255,0.04)", border: "1px solid var(--divider)", flex: 1, minWidth: 100 }}>
                                <div style={{ fontFamily: "var(--font-ui)", fontSize: 8, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 3 }}>Best team captain</div>
                                <div style={{ fontFamily: "var(--font-ui)", fontSize: 12, fontWeight: 600, color: captainMatch ? "var(--green)" : "var(--text-1)" }}>
                                  {tt.captain ?? "—"} {captainMatch ? "✓" : ""}
                                </div>
                              </div>
                            </div>

                            {/* ── Why Oracle lost / What to improve ── */}
                            {oracleLost ? (
                              <div style={{ padding: "10px 12px", borderRadius: 8, background: "rgba(239,68,68,0.04)", border: "1px solid rgba(239,68,68,0.15)" }}>
                                <div style={{ fontFamily: "var(--font-ui)", fontSize: 10, fontWeight: 600, color: "var(--red)", marginBottom: 6, textTransform: "uppercase" as const, letterSpacing: "0.06em" }}>
                                  Why did Oracle score less?
                                </div>
                                <div style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--text-2)", lineHeight: 1.7, display: "flex", flexDirection: "column" as const, gap: 4 }}>
                                  {captainMismatch && (
                                    <span>
                                      <strong style={{ color: "var(--text-1)" }}>Captain call:</strong> Oracle picked <strong style={{ color: "var(--amber)" }}>{s.oracle_captain?.name}</strong> as captain but the best team had <strong style={{ color: "var(--text-1)" }}>{tt.captain}</strong>. Oracle chose based on expected points at deadline — {tt.captain} simply outperformed the model&apos;s prediction.
                                    </span>
                                  )}
                                  {captainMatch && (
                                    <span>
                                      <strong style={{ color: "var(--green)" }}>Captain was right</strong> — both Oracle and the best team captained {tt.captain}. The gap came from player selection, not the captain pick.
                                    </span>
                                  )}
                                  {s.missed_players && s.missed_players.length > 0 && (
                                    <span>
                                      <strong style={{ color: "var(--text-1)" }}>Players Oracle missed:</strong>{" "}
                                      {s.missed_players.slice(0, 5).join(", ")}
                                      {s.missed_players.length > 5 ? ` and ${s.missed_players.length - 5} more` : ""}. These players were in the best team but Oracle&apos;s model ranked others higher based on pre-GW expected points.
                                    </span>
                                  )}
                                  {s.blind_spots?.insight && s.blind_spots.insight.includes("Self-improvement") && (
                                    <span style={{ marginTop: 2, padding: "6px 8px", borderRadius: 6, background: "rgba(251,191,36,0.06)", border: "1px solid rgba(251,191,36,0.15)", display: "block", fontFamily: "var(--font-ui)", fontSize: 10, color: "var(--amber)", lineHeight: 1.6 }}>
                                      <strong style={{ display: "block", marginBottom: 2 }}>Self-improvement applied this GW:</strong>
                                      {s.blind_spots.insight.split("Self-improvement applied: ")[1]?.split(" · ")[0] ?? s.blind_spots.insight}
                                    </span>
                                  )}
                                  {chipAdj > 0 && chipName && (
                                    <span>
                                      <strong style={{ color: "var(--amber)" }}>{chipName} chip:</strong> Even without the chip, the best team scored {topFairPts} — still {topFairPts - oraclePts} pts ahead of Oracle. The chip wasn&apos;t the only reason Oracle fell short.
                                    </span>
                                  )}
                                </div>
                              </div>
                            ) : (
                              <div style={{ padding: "10px 12px", borderRadius: 8, background: "rgba(34,197,94,0.04)", border: "1px solid rgba(34,197,94,0.15)" }}>
                                <div style={{ fontFamily: "var(--font-ui)", fontSize: 11, color: "var(--green)", lineHeight: 1.7 }}>
                                  <strong>Oracle matched the best team</strong> after removing the chip advantage. Oracle scored {oraclePts} vs their {topFairPts} (fair comparison). The model&apos;s predictions were on target this week.
                                  {s.missed_players && s.missed_players.length > 0 && (
                                    <> Players like {s.missed_players.slice(0, 3).join(", ")} were in the best team but not Oracle — Oracle still kept pace overall.</>
                                  )}
                                </div>
                              </div>
                            )}
                          </>
                        )}
                      </div>
                    </div>
                  );
                })()}

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
