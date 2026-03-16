"""
Squad Optimizer — Integer Linear Programming via PuLP.

Maximizes expected points subject to FPL 2025/26 rules:
- 15-player squad (2 GK, 5 DEF, 5 MID, 3 FWD)
- Starting XI: 1 GK, ≥3 DEF, ≥2 MID, ≥1 FWD
- Budget: £100m (1000 pence units)
- Max 3 players per club
- Captain (×2) and Vice Captain (×1.1 bonus)
- Transfer penalty: -4pts per extra transfer beyond free transfers
- Blank GW players: forced to 0 xPts
"""
from dataclasses import dataclass
from typing import Optional
import pandas as pd
from loguru import logger

from core.exceptions import OptimizationError


@dataclass
class OptimizationResult:
    squad: list[int]           # All 15 player IDs
    starting_xi: list[int]     # Starting 11 player IDs
    bench: list[int]           # Bench 4 player IDs (priority order)
    captain_id: int
    vice_captain_id: int
    total_xpts: float
    formation: str             # e.g. "3-5-2"
    solver_status: str
    budget_used: int           # pence
    transfers_needed: int      # relative to existing squad
    point_deduction: int       # 4 × extra hits


class SquadOptimizer:

    def optimize_squad(
        self,
        players_df: pd.DataFrame,
        budget: int = 1000,                    # £100m = 1000 pence units
        existing_squad: Optional[list[int]] = None,
        free_transfers: int = 1,
        wildcard_active: bool = False,
        bench_boost_active: bool = False,
        triple_captain_active: bool = False,
    ) -> OptimizationResult:
        """
        Run ILP to find optimal 15-player squad.

        players_df required columns:
          id, element_type, team_id, now_cost, predicted_xpts_next,
          has_blank_gw (optional)

        wildcard_active: ignore transfer costs
        bench_boost_active: bench players also score (include in objective)
        triple_captain_active: captain gets ×3 instead of ×2
        """
        try:
            import pulp
        except ImportError:
            raise OptimizationError("PuLP not installed. Run: pip install PuLP")

        # Filter out unavailable players (no fixture, injured with 0 chance)
        df = players_df.copy()
        df = df[df["id"].notna()].reset_index(drop=True)

        player_ids = df["id"].astype(int).tolist()
        n = len(player_ids)

        if n < 15:
            raise OptimizationError(f"Need at least 15 players to optimize, got {n}")

        # Build lookup dictionaries
        idx = {pid: i for i, pid in enumerate(player_ids)}
        pos = dict(zip(df["id"].astype(int), df["element_type"].astype(int)))
        team = dict(zip(df["id"].astype(int), df["team_id"].astype(int)))
        price = dict(zip(df["id"].astype(int), df["now_cost"].astype(int)))
        xpts = dict(zip(df["id"].astype(int), df["predicted_xpts_next"].astype(float)))

        # Zero out blank GW players
        if "has_blank_gw" in df.columns:
            for pid in player_ids:
                if df.loc[df["id"] == pid, "has_blank_gw"].values[0]:
                    xpts[pid] = 0.0

        prob = pulp.LpProblem("FPL_Squad_Optimization", pulp.LpMaximize)

        # Decision variables (all binary)
        squad = pulp.LpVariable.dicts("squad", player_ids, cat="Binary")
        xi = pulp.LpVariable.dicts("xi", player_ids, cat="Binary")
        cap = pulp.LpVariable.dicts("cap", player_ids, cat="Binary")
        vcap = pulp.LpVariable.dicts("vcap", player_ids, cat="Binary")

        # Captain multiplier: 2x normal, 3x for Triple Captain
        cap_bonus = 2.0 if not triple_captain_active else 3.0

        # Objective: maximize total xPts
        if bench_boost_active:
            # Bench players also score
            prob += (
                pulp.lpSum(xpts[p] * xi[p] for p in player_ids)
                + pulp.lpSum(xpts[p] * (cap_bonus - 1) * cap[p] for p in player_ids)
                + pulp.lpSum(xpts[p] * 0.1 * vcap[p] for p in player_ids)
                + pulp.lpSum(xpts[p] * (squad[p] - xi[p]) for p in player_ids)  # bench pts
            )
        else:
            prob += (
                pulp.lpSum(xpts[p] * xi[p] for p in player_ids)
                + pulp.lpSum(xpts[p] * (cap_bonus - 1) * cap[p] for p in player_ids)
                + pulp.lpSum(xpts[p] * 0.1 * vcap[p] for p in player_ids)
            )

        # ── Squad composition constraints ──────────────────────────────────────
        prob += pulp.lpSum(squad[p] for p in player_ids) == 15

        for pos_type, count in [(1, 2), (2, 5), (3, 5), (4, 3)]:
            prob += pulp.lpSum(squad[p] for p in player_ids if pos[p] == pos_type) == count

        # Budget constraint
        prob += pulp.lpSum(price[p] * squad[p] for p in player_ids) <= budget

        # Max 3 players per club
        for club_id in set(team.values()):
            club_players = [p for p in player_ids if team[p] == club_id]
            prob += pulp.lpSum(squad[p] for p in club_players) <= 3

        # ── Starting XI constraints ────────────────────────────────────────────
        prob += pulp.lpSum(xi[p] for p in player_ids) == 11

        # XI must be subset of squad
        for p in player_ids:
            prob += xi[p] <= squad[p]

        # Formation: valid FPL formation rules
        prob += pulp.lpSum(xi[p] for p in player_ids if pos[p] == 1) == 1   # Exactly 1 GK
        prob += pulp.lpSum(xi[p] for p in player_ids if pos[p] == 2) >= 3   # Min 3 DEF
        prob += pulp.lpSum(xi[p] for p in player_ids if pos[p] == 3) >= 2   # Min 2 MID
        prob += pulp.lpSum(xi[p] for p in player_ids if pos[p] == 4) >= 1   # Min 1 FWD

        # ── Captain constraints ────────────────────────────────────────────────
        prob += pulp.lpSum(cap[p] for p in player_ids) == 1
        prob += pulp.lpSum(vcap[p] for p in player_ids) == 1

        for p in player_ids:
            prob += cap[p] <= xi[p]       # Captain must be in XI
            prob += vcap[p] <= xi[p]      # VC must be in XI
            prob += cap[p] + vcap[p] <= 1  # Captain ≠ Vice Captain

        # No GK as captain (strategy constraint)
        for p in player_ids:
            if pos[p] == 1:
                prob += cap[p] == 0

        # ── Transfer penalty ───────────────────────────────────────────────────
        if existing_squad and not wildcard_active:
            existing_set = set(existing_squad)
            in_transfers = pulp.lpSum(
                squad[p] * (1 if p not in existing_set else 0)
                for p in player_ids
            )
            penalized_hits = pulp.LpVariable("penalized_hits", lowBound=0)
            prob += penalized_hits >= in_transfers - free_transfers
            prob.setObjective(prob.objective - 4 * penalized_hits)

        # ── Solve ──────────────────────────────────────────────────────────────
        solver = pulp.PULP_CBC_CMD(msg=0, timeLimit=30)
        prob.solve(solver)

        status = pulp.LpStatus[prob.status]
        if prob.status != 1:  # 1 = Optimal
            raise OptimizationError(f"Solver returned non-optimal status: {status}")

        # ── Extract results ────────────────────────────────────────────────────
        squad_ids = sorted(
            [p for p in player_ids if squad[p].value() and squad[p].value() > 0.5],
            key=lambda p: (-xpts[p], p),
        )
        xi_ids = [p for p in player_ids if xi[p].value() and xi[p].value() > 0.5]
        bench_ids = [p for p in squad_ids if p not in xi_ids]
        captain_id = next(p for p in player_ids if cap[p].value() and cap[p].value() > 0.5)
        vc_id = next(p for p in player_ids if vcap[p].value() and vcap[p].value() > 0.5)

        # Sort bench by position priority (GK last on bench)
        bench_sorted = sorted(bench_ids, key=lambda p: (pos[p] == 1, -xpts[p]))

        # Determine formation
        xi_df = df[df["id"].isin(xi_ids)]
        def_cnt = (xi_df["element_type"] == 2).sum()
        mid_cnt = (xi_df["element_type"] == 3).sum()
        fwd_cnt = (xi_df["element_type"] == 4).sum()
        formation = f"{def_cnt}-{mid_cnt}-{fwd_cnt}"

        # Calculate total xPts (with captain bonus)
        total_xpts = sum(xpts[p] for p in xi_ids) + xpts[captain_id] * (cap_bonus - 1)
        if bench_boost_active:
            total_xpts += sum(xpts[p] for p in bench_sorted)

        budget_used = sum(price[p] for p in squad_ids)

        # Count transfers vs existing squad
        transfers_needed = 0
        point_deduction = 0
        if existing_squad and not wildcard_active:
            existing_set = set(existing_squad)
            new_players = [p for p in squad_ids if p not in existing_set]
            transfers_needed = len(new_players)
            extra_hits = max(0, transfers_needed - free_transfers)
            point_deduction = extra_hits * 4

        logger.info(
            f"Squad optimized: {formation}, xPts={total_xpts:.1f}, "
            f"cost=£{budget_used/10:.1f}m, status={status}"
        )

        return OptimizationResult(
            squad=squad_ids,
            starting_xi=xi_ids,
            bench=bench_sorted,
            captain_id=captain_id,
            vice_captain_id=vc_id,
            total_xpts=round(total_xpts, 2),
            formation=formation,
            solver_status=status,
            budget_used=budget_used,
            transfers_needed=transfers_needed,
            point_deduction=point_deduction,
        )
