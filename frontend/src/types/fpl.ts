export type ElementType = 1 | 2 | 3 | 4; // GK DEF MID FWD
export type FormTrend = "rising" | "falling" | "stable";
export type PlayerStatus = "a" | "d" | "i" | "s" | "u" | "n";

export interface Player {
  id: number;
  web_name: string;
  element_type: ElementType;
  team_id: number;
  team_short_name?: string | null;
  team_code?: number | null;
  now_cost: number; // pence (e.g. 90 = £9.0m)
  selected_by_percent: string;
  form: string;
  status: PlayerStatus;
  news: string | null;
  chance_of_playing_next_round: number | null;
  xg_per_90: number | null;
  xa_per_90: number | null;
  npxg_per_90: number | null;
  predicted_xpts_next: number | null;
  predicted_start_prob: number | null;
  predicted_price_direction: number | null; // -1 / 0 / 1
  fdr_next: number | null;
  is_home_next: boolean | null;
  has_blank_gw: boolean;
  has_double_gw: boolean;
  form_trend: FormTrend | null;
  suspension_risk: boolean;
}

export interface SquadPick {
  player_id: number;
  web_name: string;
  element_type: ElementType;
  team_id: number;
  team_short_name?: string | null;
  team_code?: number | null;
  position: number; // 1-15
  is_captain: boolean;
  is_vice_captain: boolean;
  multiplier: number; // 0=bench, 1=start, 2=cap, 3=TC
  predicted_xpts_next: number | null;
  fdr_next: number | null;
  is_home_next: boolean | null;
  has_blank_gw: boolean;
  has_double_gw: boolean;
  status: PlayerStatus;
  news: string | null;
  suspension_risk: boolean;
  form_trend: FormTrend | null;
  now_cost: number;
  selling_price: number | null;
  purchase_price: number | null;
  predicted_start_prob?: number | null;
  xg_per_90?: number | null;
  xa_per_90?: number | null;
  total_points?: number | null;
  form?: string | number | null;
  points_per_game?: string | number | null;
}

export interface Squad {
  team_id: number;
  gameweek: number;
  squad: SquadPick[];
  bank: number; // pence
  free_transfers: number;
  total_points: number;
  overall_rank: number | null;
  team_name?: string | null;
}

export interface TransferSuggestion {
  player_out_id: number;
  player_out_name: string;
  player_out_xpts: number;
  player_out_news?: string | null;
  player_out_team_code?: number | null;
  player_out_team_name?: string | null;
  player_in_id: number;
  player_in_name: string;
  player_in_xpts: number;
  player_in_news?: string | null;
  player_in_team_code?: number | null;
  player_in_team_name?: string | null;
  xpts_gain_next: number;
  xpts_gain_3gw: number;
  net_gain_3gw: number;
  transfer_cost: number;
  recommendation: "MAKE" | "CONSIDER" | "HOLD";
  reasoning: string;
  confidence_score?: number;
  confidence_label?: "high" | "medium" | "low";
  risk_label?: "low" | "medium" | "high";
  risk_profile?: string;
  floor_projection?: number;
  median_projection?: number;
  ceiling_projection?: number;
  projection_variance?: number;
  differential_signal?: boolean;
  explanation_summary?: string;
  explanation_reasons?: string[];
  validation_complete?: boolean;
}

export interface OptimalPlayer {
  id: number;
  web_name: string;
  element_type: number;
  now_cost: number;
  predicted_xpts_next: number | null;
  team_short_name?: string | null;
  team_code?: number | null;
  /** Whether this player was on the bench in the current squad (not starting XI) */
  is_bench_player?: boolean;
  /** Whether this transferred-in player will be in the starting XI */
  is_xi_player?: boolean;
  /** If this player goes to XI and displaces an existing starter, that displaced player */
  displaces?: OptimalPlayer | null;
}

export interface BenchSwap {
  /** Player moving from bench → starting XI (free, no transfer cost) */
  from_bench: OptimalPlayer;
  /** Player moving from starting XI → bench (demoted) */
  to_bench: OptimalPlayer;
}

export interface OptimalSquad {
  total_xpts: number;
  formation: string;
  transfers_needed: number;
  point_deduction: number;
  captain: OptimalPlayer;
  transfers_out: OptimalPlayer[];
  transfers_in: OptimalPlayer[];
  /** Free bench↔XI positional swaps (no transfer cost) */
  bench_swaps: BenchSwap[];
  /** XI players pushed to bench by incoming transfers (displacement chain) */
  xi_demoted?: OptimalPlayer[];
  solver_status: string;
}

export interface CaptainCandidate {
  player_id: number;
  web_name: string;
  score: number;
  predicted_xpts_next: number;
  fdr_next: number | null;
  is_home_next: boolean;
  has_double_gw: boolean;
  selected_by_percent: number;
  reasoning: string;
  team_code?: number | null;
  team_short_name?: string | null;
  confidence_score?: number;
  confidence_label?: "high" | "medium" | "low";
  risk_label?: "low" | "medium" | "high";
  risk_profile?: string;
  floor_projection?: number;
  median_projection?: number;
  ceiling_projection?: number;
  projection_variance?: number;
  explanation_summary?: string;
  explanation_reasons?: string[];
  validation_complete?: boolean;
}

export interface ChipStatus {
  available_now: boolean;
  current_half: 1 | 2;
  half_1: { available: boolean; used_gw: number | null };
  half_2: { available: boolean; used_gw: number | null };
}

export interface ChipRecommendation {
  action: "USE_NOW" | "HOLD" | "NOT_AVAILABLE";
  best_gw: number;
  expected_gain: number;
  reasoning: string;
}

export type ActionType = "captain" | "transfer" | "injury" | "chip" | "double_gw" | "bench_swap";
export type ActionUrgency = "HIGH" | "MEDIUM" | "LOW";

export interface PriorityAction {
  priority: number;
  type: ActionType;
  urgency: ActionUrgency;
  must_do: boolean;
  label: string;
  impact_label: string;
  impact_value: number;
  reasoning: string;
  decision_type: string;
  recommended_option: string;
  team_code?: number | null;
  player_out_team_code?: number | null;
  confidence_score?: number;
  confidence_label?: "high" | "medium" | "low";
  risk_label?: "low" | "medium" | "high";
  risk_profile?: string;
  floor_projection?: number;
  median_projection?: number;
  ceiling_projection?: number;
  projection_variance?: number;
  explanation_summary?: string;
  explanation_reasons?: string[];
  validation_complete?: boolean;
}

export interface PriorityActions {
  gameweek: number;
  free_transfers: number;
  actions: PriorityAction[];
  total_actions: number;
  gw_state?: "underway" | "pre_deadline" | "finished";
  message?: string;
}

export interface GwIntelligence {
  gameweek: number;
  deadline: string | null;
  captain_recommendation: CaptainCandidate | null;
  injury_alerts: { player_id: number; web_name: string; status: string; news: string; chance_of_playing: number | null; team_code?: number | null; team_short_name?: string | null }[];
  suspension_risk: { player_id: number; web_name: string; yellow_cards: number; team_code?: number | null }[];
  blank_gw_starters: { player_id: number; web_name: string; team_code?: number | null }[];
  double_gw_players: { player_id: number; web_name: string; predicted_xpts_next: number; team_code?: number | null; team_short_name?: string | null }[];
  squad_size: number;
  free_transfers: number;
  zero_ft_advice?: {
    bench_swaps: { out: { player_id: number; web_name: string; xpts: number; element_type: number; team_code?: number | null }; in: { player_id: number; web_name: string; xpts: number; element_type: number; team_code?: number | null }; gain: number }[];
    chip_suggestion: { chip: string; reason: string; urgency: string } | null;
    ilp_optimal_xi: { player_id: number; web_name: string; element_type: number; xpts: number }[];
    verdict: "hold" | "bench_swap" | "chip";
  } | null;
}

export interface LiveSquad {
  gameweek: number;
  total_live_points: number;
  live_data_available: boolean;
  squad: {
    player_id: number;
    web_name: string;
    team_short_name: string | null;
    team_code: number | null;
    element_type: number | null;
    position: number;
    is_captain: boolean;
    is_vice_captain: boolean;
    multiplier: number;
    live_points: number;
    effective_points: number;
    playing: boolean;
    minutes: number;
    goals: number;
    assists: number;
    bonus: number;
  }[];
}

export interface Rival {
  rival_team_id: number;
  rival_name: string | null;
}

export interface FixtureSwing {
  team_id: number;
  team_name: string;
  avg_fdr_next_6: number;
  prev_avg_fdr: number;
  improvement?: number;
  difficulty_increase?: number;
  signal: string;
}

export interface LeagueInfo {
  id: number;
  name: string;
  type: "classic" | "h2h";
  rank: number | null;
  last_rank: number | null;
  entry_percentile_rank: number | null;
  total_entries: number | null;
  start_event: number;
}
