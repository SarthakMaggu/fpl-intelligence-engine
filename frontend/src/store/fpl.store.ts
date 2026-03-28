import { create } from "zustand";
import type {
  Squad,
  Player,
  GwIntelligence,
  TransferSuggestion,
  OptimalSquad,
  CaptainCandidate,
  LiveSquad,
  Rival,
  FixtureSwing,
  LeagueInfo,
  PriorityActions,
} from "@/types/fpl";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Bench-sell → buy-in → XI-swap three-way strategy move
export interface BenchStrategy {
  bench_out: { id: number; web_name: string; element_type: number; now_cost: number; selling_price: number; predicted_xpts_next: number; team_short_name: string | null; team_code: number | null };
  transfer_in: { id: number; web_name: string; element_type: number; now_cost: number; predicted_xpts_next: number; team_short_name: string | null; team_code: number | null };
  xi_swap_out: { id: number; web_name: string; element_type: number; predicted_xpts_next: number; team_short_name: string | null; team_code: number | null };
  xi_gain: number;
  net_gain: number;
  hit_cost_pts: number;
  cost_millions: number;
  budget_after_millions: number;
  feasible: boolean;
  reasoning: string;
}

export interface GWState {
  state: "pre_deadline" | "deadline_passed" | "finished" | "settling" | "unknown";
  current_gw: number | null;
  next_gw: number | null;
  finished: boolean;
  deadline_time?: string | null;
  settling_until?: string | null;
}

interface DataState {
  squad: Squad | null;
  players: Player[];
  gwIntel: GwIntelligence | null;
  priorityActions: PriorityActions | null;
  transferSuggestions: TransferSuggestion[];
  optimalSquad: OptimalSquad | null;
  benchStrategies: BenchStrategy[];
  freeTransfers: number | null;
  bankMillions: number | null;
  captainCandidates: CaptainCandidate[];
  liveSquad: LiveSquad | null;
  rivals: Rival[];
  fixtureSwings: { buy_windows: FixtureSwing[]; sell_windows: FixtureSwing[] } | null;
  leagues: LeagueInfo[];
  teamId: number | null;
  anonymousSessionToken: string | null;
  deadline: string | null;
  // Global GW state — fetched once, shared across all pages (prevents per-page re-fetch flash)
  gwState: GWState | null;
  gwStateLoaded: boolean;
  // Set to true if the transfers endpoint returned 429 (rate limited)
  transfersRateLimited: boolean;
}

interface UIState {
  selectedPlayerId: number | null;
  activeView: "pitch" | "transfers" | "fixtures" | "live";
  isLiveGW: boolean;
  isLoading: boolean;
  isSyncing: boolean;
  syncPhase: string;
  lastSyncedAt: string | null;
  onboardingComplete: boolean;
  syncError: string | null;
  followedActions: string[]; // lines like "✓ Transferred in Mbappé" or "✗ Did not transfer out Saka"
}

interface Actions {
  setTeamId: (id: number) => void;
  setAnonymousSessionToken: (token: string | null) => void;
  setOnboardingComplete: (v: boolean) => void;
  setSelectedPlayer: (id: number | null) => void;
  setActiveView: (v: UIState["activeView"]) => void;
  clearSyncError: () => void;
  clearFollowedActions: () => void;
  logout: () => void;
  syncSquad: () => Promise<void>;
  fetchSquad: () => Promise<void>;
  fetchGwIntel: () => Promise<void>;
  fetchPriorityActions: () => Promise<void>;
  fetchTransfers: () => Promise<void>;
  fetchBenchStrategies: () => Promise<void>;
  fetchCaptains: () => Promise<void>;
  fetchLiveScore: () => Promise<void>;
  fetchRivals: () => Promise<void>;
  fetchFixtureSwings: () => Promise<void>;
  fetchLeagues: () => Promise<void>;
  updateLiveScore: (data: LiveSquad) => void;
  fetchGwState: () => Promise<void>;
}

type FPLStore = DataState & UIState & Actions;

function buildAuthQuery(teamId: number | null, anonymousSessionToken: string | null) {
  const params = new URLSearchParams();
  if (anonymousSessionToken) params.set("session_token", anonymousSessionToken);
  else if (teamId) params.set("team_id", String(teamId));
  const query = params.toString();
  return query ? `?${query}` : "";
}

export const useFPLStore = create<FPLStore>((set, get) => ({
  squad: null,
  players: [],
  gwIntel: null,
  priorityActions: null,
  transferSuggestions: [],
  optimalSquad: null,
  benchStrategies: [],
  freeTransfers: null,
  bankMillions: null,
  captainCandidates: [],
  liveSquad: null,
  rivals: [],
  fixtureSwings: null,
  leagues: [],
  teamId: null,
  anonymousSessionToken: null,
  deadline: null,
  gwState: null,
  gwStateLoaded: false,
  transfersRateLimited: false,

  selectedPlayerId: null,
  activeView: "pitch",
  isLiveGW: false,
  isLoading: false,
  isSyncing: false,
  syncPhase: "",
  lastSyncedAt: null,
  onboardingComplete: false,
  syncError: null,
  followedActions: [],

  setTeamId: (id) => {
    set({ teamId: id });
    if (typeof window !== "undefined") localStorage.setItem("fpl_team_id", String(id));
  },
  setAnonymousSessionToken: (token) => {
    set({ anonymousSessionToken: token });
    if (typeof window === "undefined") return;
    if (token) localStorage.setItem("fpl_anonymous_session_token", token);
    else localStorage.removeItem("fpl_anonymous_session_token");
  },
  setOnboardingComplete: (v) => set({ onboardingComplete: v }),
  setSelectedPlayer: (id) => set({ selectedPlayerId: id }),
  setActiveView: (v) => set({ activeView: v }),
  clearSyncError: () => set({ syncError: null }),
  clearFollowedActions: () => set({ followedActions: [] }),
  logout: () => {
    if (typeof window !== "undefined") localStorage.removeItem("fpl_team_id");
    if (typeof window !== "undefined") localStorage.removeItem("fpl_anonymous_session_token");
    if (typeof window !== "undefined") localStorage.removeItem("fpl_landing_shown");
    set({
      teamId: null,
      anonymousSessionToken: null,
      onboardingComplete: false,
      squad: null,
      gwIntel: null,
      priorityActions: null,
      transferSuggestions: [],
      optimalSquad: null,
      benchStrategies: [],
      freeTransfers: null,
      bankMillions: null,
      captainCandidates: [],
      liveSquad: null,
      selectedPlayerId: null,
      gwState: null,
      gwStateLoaded: false,
    });
    // Redirect to landing — show Onboarding on home page
    if (typeof window !== "undefined") window.location.href = "/";
  },

  syncSquad: async () => {
    const { teamId, anonymousSessionToken } = get();
    set({ isSyncing: true, syncError: null, syncPhase: "Starting sync..." });
    try {
      // ── Snapshot squad BEFORE sync to detect real transfers later ──────────
      const oldPickIds = new Set((get().squad?.squad ?? []).map((p) => p.player_id));
      const oldPickNames = new Map((get().squad?.squad ?? []).map((p) => [p.player_id, p.web_name]));

      const params = buildAuthQuery(teamId, anonymousSessionToken);
      const res = await fetch(`${API}/api/squad/sync${params}`, { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      // Phase labels while we wait for the pipeline to complete
      const phases = [
        { label: "Fetching bootstrap...", ms: 2000 },
        { label: "Loading your squad...", ms: 2000 },
        { label: "Running predictions...", ms: 2000 },
      ];
      for (const { label, ms } of phases) {
        set({ syncPhase: label });
        await new Promise((r) => setTimeout(r, ms));
      }

      // ── Poll /api/squad/status until pipeline finishes (max 60s) ──────────
      set({ syncPhase: "Waiting for pipeline..." });
      const pollStart = Date.now();
      while (Date.now() - pollStart < 60_000) {
        try {
          const statusRes = await fetch(`${API}/api/squad/status`);
          if (statusRes.ok) {
            const status = await statusRes.json();
            if (!status.is_running) break;
          }
        } catch { /* ignore poll errors */ }
        await new Promise((r) => setTimeout(r, 1500));
      }

      set({ syncPhase: "Refreshing data...", gwState: null, gwStateLoaded: false });
      await get().fetchGwState();   // re-fetch GW state first so all pages see fresh state
      await get().fetchSquad();
      await Promise.all([get().fetchGwIntel(), get().fetchPriorityActions(), get().fetchTransfers(), get().fetchBenchStrategies(), get().fetchLeagues()]);

      // ── Diff new squad vs old to detect actual transfers ────────────────────
      if (oldPickIds.size > 0 && teamId) {
        const newPicks = get().squad?.squad ?? [];
        const transferredInNames = newPicks
          .filter((p) => !oldPickIds.has(p.player_id))
          .map((p) => p.web_name);
        const transferredOutNames = [...oldPickIds]
          .filter((id) => !newPicks.find((p) => p.player_id === id))
          .map((id) => oldPickNames.get(id) ?? "");

        if (transferredInNames.length > 0 || transferredOutNames.length > 0) {
          set({ syncPhase: "Checking followed actions..." });
          const actionLines: string[] = [];

          // Always surface what actually changed in the squad
          for (const name of transferredInNames) {
            actionLines.push(`✓ Transferred in: ${name}`);
          }
          for (const name of transferredOutNames.filter(Boolean)) {
            actionLines.push(`✓ Transferred out: ${name}`);
          }

          try {
            // Fetch unresolved transfer decisions for this team and match
            const gwId = get().squad?.gameweek;
            const decRes = await fetch(
              `${API}/api/decisions/?team_id=${teamId}${gwId ? `&gameweek_id=${gwId}` : ""}`
            );
            if (decRes.ok) {
              const decData = await decRes.json();
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              const unresolved = (decData.decisions ?? []).filter((d: any) => d.decision_followed === null || d.decision_followed === undefined);
              for (const dec of unresolved) {
                if (dec.decision_type !== "transfer") continue;
                const option: string = dec.recommended_option ?? "";
                const followed = transferredInNames.some((name) =>
                  option.toLowerCase().includes(name.toLowerCase())
                );
                // Add to confirmation lines — did they follow the recommendation?
                const alreadyListed = actionLines.some((l) =>
                  option.toLowerCase().split(" ").some((w) => w.length > 4 && l.toLowerCase().includes(w))
                );
                if (!alreadyListed) {
                  actionLines.push(followed ? `✓ Followed: ${option}` : `✗ Did not follow: ${option}`);
                }
                if (followed) {
                  await fetch(`${API}/api/decisions/${dec.id}`, {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                      user_choice: dec.recommended_option,
                      decision_followed: true,
                    }),
                  });
                }
              }
            }
          } catch { /* non-fatal — sync still succeeded */ }

          if (actionLines.length > 0) set({ followedActions: actionLines });
        }
      }

      // ── Chip auto-detection ─────────────────────────────────────────────────
      if (teamId) {
        try {
          set({ syncPhase: "Checking chip usage..." });
          const chipRes = await fetch(
            `${API}/api/review/chip-check?team_id=${teamId}`,
            { method: "POST" }
          );
          if (chipRes.ok) {
            const chipData = await chipRes.json();
            if (chipData.chip_used && chipData.logged) {
              const chipLine = chipData.was_recommended
                ? `✓ Used ${chipData.chip_label} (engine recommended)`
                : `✓ ${chipData.chip_label} chip logged from FPL`;
              set((s) => ({ followedActions: [...(s.followedActions ?? []), chipLine] }));
            }
          }
        } catch { /* non-fatal */ }
      }

      set({ lastSyncedAt: new Date().toISOString(), syncPhase: "" });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Unknown error";
      set({ syncError: `Sync failed — ${msg.includes("fetch") || msg.includes("500") ? "backend offline or not ready" : msg}` });
    } finally {
      set({ isSyncing: false, syncPhase: "" });
    }
  },

  fetchSquad: async () => {
    const { teamId, anonymousSessionToken } = get();
    try {
      const params = buildAuthQuery(teamId, anonymousSessionToken);
      const res = await fetch(`${API}/api/squad/${params}`);
      if (!res.ok) return;
      const data = await res.json();
      if (data.picks) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const flatPicks = data.picks.map((p: any) => ({
          player_id: p.player?.id,
          web_name: p.player?.web_name,
          element_type: p.player?.element_type,
          team_id: p.player?.team_id,
          team_short_name: p.player?.team_short_name ?? null,
          team_code: p.player?.team_code ?? null,
          position: p.position,
          is_captain: p.is_captain,
          is_vice_captain: p.is_vice_captain,
          multiplier: p.multiplier,
          purchase_price: p.purchase_price,
          selling_price: p.selling_price,
          now_cost: p.player?.now_cost,
          predicted_xpts_next: p.player?.predicted_xpts_next ?? null,
          predicted_start_prob: p.player?.predicted_start_prob ?? null,
          predicted_price_direction: p.player?.predicted_price_direction ?? null,
          fdr_next: p.player?.fdr_next ?? null,
          is_home_next: p.player?.is_home_next ?? null,
          has_blank_gw: p.player?.has_blank_gw ?? false,
          has_double_gw: p.player?.has_double_gw ?? false,
          status: p.player?.status ?? "a",
          news: p.player?.news ?? null,
          suspension_risk: p.player?.suspension_risk ?? false,
          form_trend: p.player?.form_trend ?? null,
          xg_per_90: p.player?.xg_per_90 ?? null,
          xa_per_90: p.player?.xa_per_90 ?? null,
          total_points: p.player?.total_points ?? null,
          form: p.player?.form ?? null,
          points_per_game: p.player?.points_per_game ?? null,
        }));
        set({ deadline: data.deadline ?? null, squad: { team_id: data.team_id, gameweek: data.gameweek, squad: flatPicks, bank: data.bank, free_transfers: data.free_transfers, total_points: data.total_points, overall_rank: data.overall_rank, team_name: data.team_name ?? null } });
      }
    } catch (e) { console.warn("fetchSquad:", e); }
  },

  fetchGwIntel: async () => {
    const { teamId, anonymousSessionToken } = get();
    try {
      const params = buildAuthQuery(teamId, anonymousSessionToken);
      const res = await fetch(`${API}/api/intel/gw${params}`);
      if (!res.ok) return;
      set({ gwIntel: await res.json() });
    } catch (e) { console.warn("fetchGwIntel:", e); }
  },

  fetchPriorityActions: async () => {
    const { teamId, anonymousSessionToken } = get();
    try {
      const params = buildAuthQuery(teamId, anonymousSessionToken);
      const res = await fetch(`${API}/api/intel/priority-actions${params}`);
      if (!res.ok) return;
      set({ priorityActions: await res.json() });
    } catch (e) { console.warn("fetchPriorityActions:", e); }
  },

  fetchTransfers: async () => {
    const { teamId, anonymousSessionToken } = get();
    try {
      const params = buildAuthQuery(teamId, anonymousSessionToken);
      const res = await fetch(`${API}/api/transfers/suggestions${params}`);
      if (res.status === 429) {
        set({ transfersRateLimited: true });
        return;
      }
      if (!res.ok) return;
      set({ transfersRateLimited: false });
      const data = await res.json();
      // Normalize nested API format → flat TransferSuggestion interface
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const normalized = (data.suggestions || []).map((s: any) => ({
        player_out_id: s.player_out?.id || 0,
        player_out_name: s.player_out?.web_name || "",
        player_out_xpts: s.player_out?.predicted_xpts_next ?? 0,
        player_out_news: s.player_out?.news_alert ?? null,
        player_out_team_code: s.player_out?.team_code ?? null,
        player_out_team_name: s.player_out?.team_short_name ?? null,
        player_in_id: s.player_in?.id || 0,
        player_in_name: s.player_in?.web_name || "",
        player_in_xpts: s.player_in?.predicted_xpts_next ?? 0,
        player_in_news: s.player_in?.news_alert ?? null,
        player_in_team_code: s.player_in?.team_code ?? null,
        player_in_team_name: s.player_in?.team_short_name ?? null,
        xpts_gain_next: s.xpts_gain_next ?? 0,
        xpts_gain_3gw: s.xpts_gain_3gw ?? 0,
        net_gain_3gw: s.net_gain_3gw ?? 0,
        transfer_cost: s.transfer_cost_pts ?? 0,
        recommendation: s.recommendation || "HOLD",
        reasoning: s.reasoning || "",
        confidence_score: s.confidence_score,
        confidence_label: s.confidence_label,
        risk_label: s.risk_label,
        risk_profile: s.risk_profile,
        floor_projection: s.floor_projection,
        median_projection: s.median_projection,
        ceiling_projection: s.ceiling_projection,
        projection_variance: s.projection_variance,
        differential_signal: s.differential_signal,
        explanation_summary: s.explanation_summary,
        explanation_reasons: s.explanation_reasons,
        validation_complete: s.validation_complete,
      }));
      set({
        transferSuggestions: normalized,
        optimalSquad: data.optimal_squad ?? null,
        freeTransfers: data.free_transfers ?? null,
        bankMillions: data.bank_millions ?? null,
      });
    } catch (e) { console.warn("fetchTransfers:", e); }
  },

  fetchBenchStrategies: async () => {
    const { teamId, anonymousSessionToken } = get();
    try {
      const params = buildAuthQuery(teamId, anonymousSessionToken);
      const res = await fetch(`${API}/api/transfers/bench-transfer-xi${params}`);
      if (!res.ok) return;
      const data = await res.json();
      // Sort by net_gain descending, keep feasible ones only
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const strategies: BenchStrategy[] = (data.suggestions || [])
        .filter((s: BenchStrategy) => s.feasible && s.net_gain > 0)
        .sort((a: BenchStrategy, b: BenchStrategy) => b.net_gain - a.net_gain)
        .slice(0, 3);
      set({ benchStrategies: strategies });
    } catch (e) { console.warn("fetchBenchStrategies:", e); }
  },

  fetchCaptains: async () => {
    const { teamId, anonymousSessionToken } = get();
    try {
      const params = buildAuthQuery(teamId, anonymousSessionToken);
      const res = await fetch(`${API}/api/optimization/captain${params}`);
      if (!res.ok) return;
      const data = await res.json();
      // Backend returns `candidates` with `xpts`, `captain_score`, `is_home`.
      // Map to CaptainCandidate shape used by the UI.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const mapped = (data.candidates || []).map((c: any) => ({
        ...c,
        score:                c.score ?? c.captain_score ?? 0,
        predicted_xpts_next:  c.predicted_xpts_next ?? c.xpts ?? 0,
        is_home_next:         c.is_home_next ?? c.is_home ?? null,
        selected_by_percent:  c.selected_by_percent ?? c.ownership ?? 0,
        confidence_score:     c.confidence_score,
        confidence_label:     c.confidence_label,
        risk_label:           c.risk_label,
        risk_profile:         c.risk_profile,
        floor_projection:     c.floor_projection,
        median_projection:    c.median_projection,
        ceiling_projection:   c.ceiling_projection,
        projection_variance:  c.projection_variance,
        explanation_summary:  c.explanation_summary,
        explanation_reasons:  c.explanation_reasons,
        validation_complete:  c.validation_complete,
      }));
      set({ captainCandidates: mapped });
    } catch (e) { console.warn("fetchCaptains:", e); }
  },

  fetchLiveScore: async () => {
    const { teamId, anonymousSessionToken } = get();
    try {
      const params = buildAuthQuery(teamId, anonymousSessionToken);
      const res = await fetch(`${API}/api/live/score${params}`);
      if (!res.ok) return;
      set({ liveSquad: await res.json() });
    } catch (e) { console.warn("fetchLiveScore:", e); }
  },

  fetchRivals: async () => {
    const { teamId, anonymousSessionToken } = get();
    try {
      const params = buildAuthQuery(teamId, anonymousSessionToken);
      const res = await fetch(`${API}/api/rivals/${params}`);
      if (!res.ok) return;
      const data = await res.json();
      set({ rivals: Array.isArray(data) ? data : [] });
    } catch (e) { console.warn("fetchRivals:", e); }
  },

  fetchFixtureSwings: async () => {
    try {
      const res = await fetch(`${API}/api/intel/fixture-swings`);
      if (!res.ok) return;
      set({ fixtureSwings: await res.json() });
    } catch (e) { console.warn("fetchFixtureSwings:", e); }
  },

  fetchLeagues: async () => {
    const { teamId, anonymousSessionToken } = get();
    try {
      const params = buildAuthQuery(teamId, anonymousSessionToken);
      const res = await fetch(`${API}/api/squad/leagues${params}`);
      if (!res.ok) return;
      const data = await res.json();
      set({ leagues: [...(data.classic || []), ...(data.h2h || [])] });
    } catch (e) { console.warn("fetchLeagues:", e); }
  },

  updateLiveScore: (data) => set({ liveSquad: data }),

  // Fetch GW state once and cache globally — all pages share this to prevent
  // per-page re-fetch and the resulting "content flash → underway" transition.
  fetchGwState: async () => {
    if (get().gwStateLoaded) return; // already fetched, use cached value
    try {
      const res = await fetch(`${API}/api/gameweeks/current`);
      if (!res.ok) { set({ gwStateLoaded: true }); return; }
      const data = await res.json();
      set({ gwState: data || null, gwStateLoaded: true });
    } catch { set({ gwStateLoaded: true }); }
  },
}));
