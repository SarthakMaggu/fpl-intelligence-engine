"""
Probabilistic Points Simulation — Monte Carlo over player GW points.

For each player, simulates N_SIMS gameweek points draws using:
  - P(start) from minutes model
  - xPts as mean of the scoring distribution (conditional on starting)
  - Poisson-like noise on the scoring process

Outputs per player:
  - P(blank)   = P(points ≤ 2)
  - P(5+)      = P(points ≥ 5)
  - P(10+)     = P(points ≥ 10)
  - mean_xpts, std_xpts, percentiles (p10, p25, p50, p75, p90)
  - rank_volatility_score = combined ownership-adjusted upside metric
"""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import Optional
from loguru import logger

N_SIMS = 2000    # default simulation count
MIN_POINTS = 2   # GK / DEF clean-sheet base for "blank"


@dataclass
class PlayerSimInput:
    player_id: int
    web_name: str
    xpts: float                        # raw predicted xPts
    p_start: float = 0.7              # P(playing any minutes)
    selected_by_percent: float = 10.0  # ownership %
    element_type: int = 3             # 1=GK,2=DEF,3=MID,4=FWD
    is_captain: bool = False


@dataclass
class PlayerSimResult:
    player_id: int
    web_name: str
    mean_xpts: float
    std_xpts: float
    prob_blank: float      # P(≤2 pts)
    prob_5_plus: float     # P(≥5 pts)
    prob_10_plus: float    # P(≥10 pts)
    p10: float
    p25: float
    p50: float
    p75: float
    p90: float
    rank_volatility_score: float
    captain_ev: float      # if captain: mean_xpts * 2
    upside_score: float    # p75 - p25 (interquartile range)


class ProbabilisticSimulator:
    """
    Monte Carlo simulator for FPL GW points distributions.

    Usage:
        sim = ProbabilisticSimulator()
        results = sim.simulate_players(player_inputs)
    """

    def __init__(self, n_sims: int = N_SIMS, seed: Optional[int] = 42):
        self.n_sims = n_sims
        self.rng = np.random.default_rng(seed)

    # ── Core simulation ───────────────────────────────────────────────────────

    def _simulate_player(self, inp: PlayerSimInput) -> np.ndarray:
        """
        Simulate `n_sims` GW point totals for one player.

        Model:
          1. Sample did_play ~ Bernoulli(p_start)
          2. If played, sample base_pts ~ max(0, Normal(xpts, xpts * noise_scale))
          3. If not played, pts = 0 (sub appearance gives ~1-2 pts occasionally)
          4. Round to nearest integer
        """
        n = self.n_sims
        noise_scale = 0.6   # coefficient of variation — xPts has ~60% relative std

        # 1. Who plays?
        played = self.rng.random(n) < inp.p_start

        # 2. Points when playing — Normal approximation around xPts
        std = max(inp.xpts * noise_scale, 1.0)
        raw_pts = self.rng.normal(loc=inp.xpts, scale=std, size=n)
        raw_pts = np.maximum(raw_pts, 0.0)

        # 3. Non-playing: small chance of sub appearance (1-2 pts)
        sub_pts = self.rng.choice([0, 1, 2], size=n, p=[0.85, 0.10, 0.05])

        # Combine
        pts = np.where(played, raw_pts, sub_pts.astype(float))

        # Captain doubling
        if inp.is_captain:
            pts = pts * 2

        return np.round(pts).astype(int)

    def simulate_players(
        self,
        players: list[PlayerSimInput],
        save_to_db: bool = False,
        gameweek_id: int = 0,
        db=None,
    ) -> list[PlayerSimResult]:
        """
        Run Monte Carlo for all players. Returns a list of PlayerSimResult.
        """
        results = []
        for inp in players:
            pts_arr = self._simulate_player(inp)

            mean_xpts = float(np.mean(pts_arr))
            std_xpts = float(np.std(pts_arr))
            prob_blank = float(np.mean(pts_arr <= 2))
            prob_5_plus = float(np.mean(pts_arr >= 5))
            prob_10_plus = float(np.mean(pts_arr >= 10))
            p10, p25, p50, p75, p90 = np.percentile(pts_arr, [10, 25, 50, 75, 90])

            # Rank volatility: high ownership + high upside = template (low vol)
            #                  low ownership + high upside = differential (high vol)
            ownership_norm = min(inp.selected_by_percent / 100.0, 1.0)
            upside_score = float(p90 - p25)
            rank_volatility = upside_score * (1.0 - ownership_norm)

            captain_ev = mean_xpts * 2 if not inp.is_captain else mean_xpts  # raw EV when captained

            result = PlayerSimResult(
                player_id=inp.player_id,
                web_name=inp.web_name,
                mean_xpts=round(mean_xpts, 3),
                std_xpts=round(std_xpts, 3),
                prob_blank=round(prob_blank, 3),
                prob_5_plus=round(prob_5_plus, 3),
                prob_10_plus=round(prob_10_plus, 3),
                p10=float(round(p10, 1)),
                p25=float(round(p25, 1)),
                p50=float(round(p50, 1)),
                p75=float(round(p75, 1)),
                p90=float(round(p90, 1)),
                rank_volatility_score=round(rank_volatility, 3),
                captain_ev=round(captain_ev, 3),
                upside_score=round(upside_score, 3),
            )
            results.append(result)

        if save_to_db and db is not None and gameweek_id > 0:
            import asyncio
            asyncio.ensure_future(self._persist(results, gameweek_id, db))

        return results

    async def _persist(
        self,
        results: list[PlayerSimResult],
        gameweek_id: int,
        db,
    ) -> None:
        """Persist distribution results to PointsDistribution table."""
        from models.db.calibration import PointsDistribution
        try:
            for r in results:
                record = PointsDistribution(
                    player_id=r.player_id,
                    gameweek_id=gameweek_id,
                    mean_xpts=r.mean_xpts,
                    std_xpts=r.std_xpts,
                    p10=r.p10,
                    p25=r.p25,
                    p50=r.p50,
                    p75=r.p75,
                    p90=r.p90,
                    prob_blank=r.prob_blank,
                    prob_5_plus=r.prob_5_plus,
                    prob_10_plus=r.prob_10_plus,
                    rank_volatility_score=r.rank_volatility_score,
                    n_simulations=self.n_sims,
                )
                db.add(record)
            await db.commit()
            logger.info(f"Persisted {len(results)} distributions for GW {gameweek_id}")
        except Exception as e:
            logger.error(f"Failed to persist distributions: {e}")
            await db.rollback()

    # ── Team-level simulation ─────────────────────────────────────────────────

    def simulate_team_total(
        self,
        players: list[PlayerSimInput],
        n_sims: Optional[int] = None,
    ) -> dict:
        """
        Simulate total GW team points across all players.
        Returns expected total, P(90+ team pts), P(110+ team pts).
        """
        sims = n_sims or self.n_sims
        team_pts = np.zeros(sims)

        for inp in players:
            pts_arr = self._simulate_player(inp)
            pts_arr = pts_arr[:sims]
            team_pts += pts_arr

        return {
            "mean_team_pts": round(float(np.mean(team_pts)), 1),
            "std_team_pts": round(float(np.std(team_pts)), 1),
            "p25_team": float(np.percentile(team_pts, 25)),
            "p50_team": float(np.percentile(team_pts, 50)),
            "p75_team": float(np.percentile(team_pts, 75)),
            "prob_90_plus": round(float(np.mean(team_pts >= 90)), 3),
            "prob_110_plus": round(float(np.mean(team_pts >= 110)), 3),
            "prob_130_plus": round(float(np.mean(team_pts >= 130)), 3),
        }


# Singleton
simulator = ProbabilisticSimulator(n_sims=N_SIMS)
