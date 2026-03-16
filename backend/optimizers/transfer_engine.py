"""
Transfer Decision Engine — evaluates individual transfer options.

Key insight: evaluates over 3 GWs (not just next 1 GW) to handle
cases where taking a -4pt hit is worth it long-term.
"""
from dataclasses import dataclass
from typing import Optional
import pandas as pd
from loguru import logger


@dataclass
class TransferEvaluation:
    player_out: dict
    player_in: dict
    xpts_gain_next: float         # gain for next GW only
    xpts_gain_3gw: float          # gain over next 3 GWs
    transfer_cost_pts: int         # 0 if free transfer, else 4
    net_gain_next: float           # xpts_gain_next - transfer_cost_pts
    net_gain_3gw: float            # xpts_gain_3gw - transfer_cost_pts
    recommendation: str            # "MAKE" | "HOLD" | "CONSIDER"
    feasible: bool
    shortfall: int                 # pence short if not feasible
    reasoning: str


class TransferEngine:

    def evaluate_transfer(
        self,
        player_out_id: int,
        player_in_id: int,
        players_df: pd.DataFrame,
        bank: int,
        free_transfers: int,
        selling_price: int,
        future_xpts: Optional[dict[int, list[float]]] = None,
    ) -> TransferEvaluation:
        """
        Evaluate a single transfer.

        players_df: full player DataFrame with predicted_xpts_next
        bank: pence available in bank
        free_transfers: number of free transfers remaining
        selling_price: selling price for player_out (pence, FPL sell-on cap)
        future_xpts: optional {player_id: [xpts_gw1, xpts_gw2, xpts_gw3]}
        """
        out_row = players_df[players_df["id"] == player_out_id]
        in_row = players_df[players_df["id"] == player_in_id]

        if out_row.empty:
            raise ValueError(f"Player {player_out_id} not found in players_df")
        if in_row.empty:
            raise ValueError(f"Player {player_in_id} not found in players_df")

        out = out_row.iloc[0].to_dict()
        inp = in_row.iloc[0].to_dict()

        # Feasibility check
        cost = int(inp.get("now_cost", 0))
        funds = selling_price + bank
        feasible = funds >= cost
        shortfall = max(0, cost - funds)

        # xPts gain next GW
        xpts_out = float(out.get("predicted_xpts_next", 0) or 0)
        xpts_in = float(inp.get("predicted_xpts_next", 0) or 0)
        xpts_gain_next = xpts_in - xpts_out

        # xPts gain over 3 GWs
        if future_xpts:
            out_future = future_xpts.get(player_out_id, [xpts_out, xpts_out, xpts_out])
            in_future = future_xpts.get(player_in_id, [xpts_in, xpts_in, xpts_in])
            xpts_gain_3gw = sum(i - o for i, o in zip(in_future[:3], out_future[:3]))
        else:
            xpts_gain_3gw = xpts_gain_next * 2.5  # rough 3-GW projection

        transfer_cost = 0 if free_transfers > 0 else 4
        net_gain_next = xpts_gain_next - transfer_cost
        net_gain_3gw = xpts_gain_3gw - transfer_cost

        # Recommendation logic
        if not feasible:
            recommendation = "HOLD"
            reasoning = f"Can't afford — £{shortfall/10:.1f}m short"
        elif net_gain_3gw > 6.0 and xpts_gain_next > 0:
            recommendation = "MAKE"
            reasoning = f"+{xpts_gain_3gw:.1f}xPts gain over 3 GWs (net +{net_gain_3gw:.1f})"
        elif net_gain_next > 0.5 and free_transfers > 0:
            recommendation = "MAKE"
            reasoning = f"+{xpts_gain_next:.1f}xPts next GW (free transfer)"
        elif net_gain_3gw > 2.0 and free_transfers > 0:
            recommendation = "CONSIDER"
            reasoning = f"+{xpts_gain_3gw:.1f}xPts over 3 GWs (marginal benefit)"
        elif transfer_cost == 4 and net_gain_3gw > 6.0:
            recommendation = "CONSIDER"
            reasoning = f"Hit worth it: +{net_gain_3gw:.1f} net over 3 GWs after -4pt cost"
        else:
            recommendation = "HOLD"
            reasoning = (
                f"Insufficient gain: {net_gain_next:.1f}xP next GW"
                if free_transfers > 0
                else f"Hit not worth it: {net_gain_3gw:.1f}xP gain over 3 GWs vs -4pt cost"
            )

        return TransferEvaluation(
            player_out=out,
            player_in=inp,
            xpts_gain_next=round(xpts_gain_next, 2),
            xpts_gain_3gw=round(xpts_gain_3gw, 2),
            transfer_cost_pts=transfer_cost,
            net_gain_next=round(net_gain_next, 2),
            net_gain_3gw=round(net_gain_3gw, 2),
            recommendation=recommendation,
            feasible=feasible,
            shortfall=shortfall,
            reasoning=reasoning,
        )

    def get_transfer_suggestions(
        self,
        squad_player_ids: list[int],
        players_df: pd.DataFrame,
        bank: int,
        free_transfers: int,
        selling_prices: dict[int, int],
        top_n: int = 5,
        future_xpts: Optional[dict] = None,
        starting_xi_ids: Optional[list[int]] = None,
    ) -> list[TransferEvaluation]:
        """
        Generate top transfer suggestions from current squad.

        For each squad player: find the best replacement outside the squad
        that is feasible within budget and improves xPts.

        starting_xi_ids: if provided, only XI players are considered as transfer-out
        candidates. Bench players are excluded because swapping a bench player 1-for-1
        doesn't improve your PLAYING XI — the gain calculation is inflated by their 0-xPts
        (e.g. blank GW bench player) while the true XI impact requires first benching someone.
        """
        squad_set = set(squad_player_ids)
        # Restrict transfer-out candidates to starting XI only.
        # This prevents the engine from recommending "transfer your 0-xPts bench player out"
        # when the real fix is to improve your weakest XI player.
        xi_set = set(starting_xi_ids) if starting_xi_ids else squad_set
        transfer_out_ids = squad_set & xi_set          # only XI players as candidates
        squad_df = players_df[players_df["id"].isin(transfer_out_ids)]
        candidates_df = players_df[~players_df["id"].isin(squad_set)]

        # Quality filter: only consider available players with realistic predictions.
        # Removes injured/suspended, players with 0 form (not playing), and
        # ML artifacts (absurd xPts for low-ownership fringe players).
        #
        # start_prob >= 0.35: eliminates players who are frozen out of their squad
        # (the reality gate in fetcher.py caps zero-minute players at 0.08, so any
        # player below 0.35 is either injured, doubted, or not in manager's plans).
        candidates_df = candidates_df[
            (candidates_df["status"] == "a") &
            (candidates_df["predicted_xpts_next"].notna()) &
            (candidates_df["predicted_xpts_next"] <= 14.0) &       # realistic single-GW cap
            (candidates_df["form"].fillna(0) >= 1.0) &              # at least some recent activity
            (candidates_df.get("predicted_start_prob", pd.Series(1.0, index=candidates_df.index)).fillna(1.0) >= 0.35)
            # ↑ Filters out frozen-out players like Edozie (0 minutes → start_prob ≤ 0.08)
        ]

        # Build per-club count for current squad (FPL rule: max 3 per club)
        squad_club_counts: dict[int, int] = {}
        for _, row in squad_df.iterrows():
            tid = int(row.get("team_id", 0))
            squad_club_counts[tid] = squad_club_counts.get(tid, 0) + 1

        evaluations = []
        for _, out_row in squad_df.iterrows():
            out_id = int(out_row["id"])
            raw_sp = selling_prices.get(out_id, 0)
            # Caller (transfers.py) pre-computes sell-on-cap corrected prices.
            # This now_cost fallback is a safety net only — should rarely trigger.
            selling_price = raw_sp if raw_sp > 0 else int(out_row.get("now_cost", 0))
            out_xpts = float(out_row.get("predicted_xpts_next", 0) or 0)
            out_pos = int(out_row.get("element_type", 1))
            out_team = int(out_row.get("team_id", 0))

            # Only look at same-position replacements
            pos_candidates = candidates_df[candidates_df["element_type"] == out_pos]

            # Check affordability and gain
            for _, in_row in pos_candidates.iterrows():
                in_id = int(in_row["id"])
                in_cost = int(in_row.get("now_cost", 0))
                funds = selling_price + bank

                if funds < in_cost:
                    continue

                # FPL rule: max 3 players per club.
                # Removing player_out frees a slot if they share the same club.
                in_team = int(in_row.get("team_id", 0))
                effective_club_count = squad_club_counts.get(in_team, 0) - (
                    1 if out_team == in_team else 0
                )
                if effective_club_count >= 3:
                    continue

                in_xpts = float(in_row.get("predicted_xpts_next", 0) or 0)
                gain = in_xpts - out_xpts
                if gain <= 0.5:
                    continue

                try:
                    eval_result = self.evaluate_transfer(
                        player_out_id=out_id,
                        player_in_id=in_id,
                        players_df=players_df,
                        bank=bank,
                        free_transfers=free_transfers,
                        selling_price=selling_price,
                        future_xpts=future_xpts,
                    )
                    if eval_result.feasible:
                        evaluations.append(eval_result)
                except Exception:
                    continue

        # Sort by 3-GW net gain (highest first)
        evaluations.sort(key=lambda e: e.net_gain_3gw, reverse=True)

        # Deduplicate: one suggestion per player_out AND one per player_in.
        #
        # When the user has multiple free transfers (e.g. 5 FT), showing the same
        # player_in target for two different "out" players is invalid — FPL only
        # allows each player to be transferred in once per GW. Without this fix, all
        # 5 suggestions could recommend the same popular player_in (e.g. Edozie ×4).
        seen_out: set[int] = set()
        seen_in: set[int] = set()
        unique_evals = []
        for e in evaluations:
            out_id = e.player_out["id"]
            in_id = e.player_in["id"]
            if out_id not in seen_out and in_id not in seen_in:
                seen_out.add(out_id)
                seen_in.add(in_id)
                unique_evals.append(e)
            if len(unique_evals) >= top_n:
                break

        logger.info(f"Generated {len(unique_evals)} transfer suggestions")
        return unique_evals
