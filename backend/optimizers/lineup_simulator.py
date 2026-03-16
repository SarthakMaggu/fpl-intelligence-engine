"""
Lineup Probability Simulator — Monte Carlo over full squad XI composition.

For each simulation, samples which players start (Bernoulli per P(start)),
ensures formation validity (≥1 GK, ≥3 DEF, ≥2 MID, ≥1 FWD, exactly 11 starters),
and selects the highest-xPts valid lineup when the naive sampling fails.

Returns:
  - P(starts) for each player across N_SIMS trials
  - Most likely XI composition
  - Expected XI xPts under uncertainty
"""
from __future__ import annotations

import numpy as np
from collections import Counter
from typing import Optional
from dataclasses import dataclass
from loguru import logger

N_SIMS = 3000   # more sims for lineup — it's a combinatorial problem

# Formation constraints
FORMATION_MIN = {1: 1, 2: 3, 3: 2, 4: 1}  # element_type → minimum starters
SQUAD_SIZE = 15
XI_SIZE = 11


@dataclass
class SquadPlayerInput:
    player_id: int
    web_name: str
    position: int        # 1–15 (FPL squad slot)
    element_type: int    # 1=GK, 2=DEF, 3=MID, 4=FWD
    xpts: float
    p_start: float = 0.7
    is_bench: bool = False  # provided by squad API (position > 11)


@dataclass
class PlayerStartProb:
    player_id: int
    web_name: str
    element_type: int
    xpts: float
    p_simulated_start: float   # fraction of sims where they started
    p_in_xi: float             # fraction of sims where they're in the optimal XI
    avg_xi_xpts_contribution: float


class LineupSimulator:
    """
    Monte Carlo lineup probability simulator for a 15-player squad.
    """

    def __init__(self, n_sims: int = N_SIMS, seed: Optional[int] = 7):
        self.n_sims = n_sims
        self.rng = np.random.default_rng(seed)

    def _valid_xi(self, starters: list[SquadPlayerInput]) -> bool:
        """Check if a set of 11 players meets formation constraints."""
        if len(starters) != XI_SIZE:
            return False
        type_counts = Counter(p.element_type for p in starters)
        return all(type_counts.get(t, 0) >= m for t, m in FORMATION_MIN.items())

    def _best_valid_xi(self, squad: list[SquadPlayerInput]) -> list[SquadPlayerInput]:
        """
        Select optimal valid XI from squad using greedy xPts maximization.
        Ensures formation constraints are met.
        """
        available = sorted(squad, key=lambda p: -p.xpts)
        xi: list[SquadPlayerInput] = []
        counts: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0}

        # Phase 1: fill minimums
        for min_type, min_count in FORMATION_MIN.items():
            candidates = [p for p in available if p.element_type == min_type and p not in xi]
            for p in candidates[:min_count]:
                xi.append(p)
                counts[min_type] += 1

        # Phase 2: fill to 11 with highest xPts
        remaining = [p for p in available if p not in xi]
        slots = XI_SIZE - len(xi)
        xi.extend(remaining[:slots])

        return xi[:XI_SIZE]

    def simulate(self, squad: list[SquadPlayerInput]) -> dict:
        """
        Run Monte Carlo over the squad to estimate each player's start probability.

        For each simulation:
          1. Sample did_start[i] ~ Bernoulli(p_start[i]) for each player
          2. If the sampled XI is valid, use it; otherwise fall back to best valid XI
          3. Record who's in the final XI
        """
        n = self.n_sims
        n_players = len(squad)

        # Pre-compute start probabilities
        p_starts = np.array([p.p_start for p in squad])
        xpts_arr = np.array([p.xpts for p in squad])

        # Track how often each player appears in the XI
        start_counts = np.zeros(n_players, dtype=int)
        xi_xpts_sum = np.zeros(n_players)

        for _ in range(n):
            # Sample who starts
            sampled = self.rng.random(n_players) < p_starts
            sampled_squad = [squad[i] for i in range(n_players) if sampled[i]]

            # Try to build a valid XI from sampled starters
            if len(sampled_squad) >= XI_SIZE:
                xi = self._best_valid_xi(sampled_squad)
            else:
                # Not enough players started; use best valid from full squad
                xi = self._best_valid_xi(squad)

            xi_ids = {p.player_id for p in xi}
            for i, player in enumerate(squad):
                if player.player_id in xi_ids:
                    start_counts[i] += 1
                    xi_xpts_sum[i] += player.xpts

        # Compute probabilities
        results: list[PlayerStartProb] = []
        most_likely_xi_ids = set()

        for i, player in enumerate(squad):
            p_sim_start = start_counts[i] / n
            avg_xpts_when_in_xi = xi_xpts_sum[i] / max(start_counts[i], 1)
            results.append(PlayerStartProb(
                player_id=player.player_id,
                web_name=player.web_name,
                element_type=player.element_type,
                xpts=player.xpts,
                p_simulated_start=round(p_sim_start, 3),
                p_in_xi=round(p_sim_start, 3),
                avg_xi_xpts_contribution=round(avg_xpts_when_in_xi, 3),
            ))
            # Consider "likely starters" as > 50% simulated start rate
            if p_sim_start > 0.5:
                most_likely_xi_ids.add(player.player_id)

        # Compute expected XI xPts
        expected_xi_xpts = sum(
            r.p_simulated_start * r.xpts for r in results
        )

        # Most likely XI from probabilities (greedy valid selection)
        sorted_results = sorted(results, key=lambda r: -r.p_simulated_start)
        most_likely_xi = self._best_valid_xi([
            squad[i] for i, _ in enumerate(sorted_results)
            if i < XI_SIZE  # rough selection
        ])

        logger.info(
            f"Lineup simulation: {n_players} players, {n} sims → "
            f"expected XI xPts={expected_xi_xpts:.2f}"
        )

        return {
            "player_probabilities": [
                {
                    "player_id": r.player_id,
                    "web_name": r.web_name,
                    "element_type": r.element_type,
                    "xpts": r.xpts,
                    "p_start": r.p_simulated_start,
                    "p_in_xi": r.p_in_xi,
                }
                for r in results
            ],
            "expected_xi_xpts": round(expected_xi_xpts, 2),
            "n_simulations": n,
            "most_likely_xi": [p.player_id for p in most_likely_xi],
            "uncertainty_summary": {
                "high_confidence_starters": sum(1 for r in results if r.p_simulated_start > 0.85),
                "rotation_risks": sum(1 for r in results if 0.4 < r.p_simulated_start < 0.75),
                "unlikely_starters": sum(1 for r in results if r.p_simulated_start < 0.4),
            },
        }


# Singleton
lineup_simulator = LineupSimulator(n_sims=N_SIMS)
