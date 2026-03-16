"""
Chip Strategy Engine — Monte Carlo simulation to find optimal chip timing.

Runs 10,000 season simulations, sampling actual GW points from
Normal(xpts, σ=2.5) for each player each GW.

2025/26 chip rules:
- Each chip usable once per half (GW1-18 first half, GW20-38 second half)
- First half deadline: GW19 deadline
- Second half: from GW20 onwards
- Only 1 chip per GW

Chips evaluated:
- Bench Boost: find GW with highest expected bench contribution
  → Priority: Double GW (bench plays twice)
- Triple Captain: find GW with highest expected captain score
  → Priority: Double GW + FDR ≤ 2
- Wildcard: trigger when current squad is significantly underperforming
  → Signal: E[optimal] - E[current] > 15 pts over next 5 GWs
- Free Hit: trigger when ≥5 starters have a blank GW
"""
import numpy as np
from dataclasses import dataclass
from typing import Optional
from loguru import logger


FIRST_HALF_MAX_GW = 18
SECOND_HALF_MIN_GW = 20


@dataclass
class ChipRecommendation:
    chip: str                # "wildcard" | "free_hit" | "bench_boost" | "triple_captain"
    recommended_gw: int
    confidence: float        # 0.0 - 1.0
    expected_gain: float     # additional xPts vs not using chip
    reasoning: str
    urgency: str             # "urgent" | "plan" | "monitor"


class ChipEngine:
    def __init__(self, n_simulations: int = 10_000):
        self.n_simulations = n_simulations
        self.rng = np.random.default_rng(seed=42)

    def _sample_points(
        self,
        xpts_matrix: np.ndarray,
        sigma: float = 2.5,
    ) -> np.ndarray:
        """
        Sample actual points from Normal(xpts, σ).
        Shape: (n_gws, n_sims, n_players)
        """
        n_gws, n_players = xpts_matrix.shape
        noise = self.rng.normal(0, sigma, (n_gws, self.n_simulations, n_players))
        samples = xpts_matrix[:, np.newaxis, :] + noise
        return np.clip(samples, 0, None)  # points can't be negative

    def recommend_bench_boost(
        self,
        bench_xpts_by_gw: np.ndarray,   # shape: (n_remaining_gws, 4) — bench player xpts
        current_gw: int,
        half: str,
        available: bool = True,
    ) -> Optional[ChipRecommendation]:
        """
        Find the GW with highest expected bench contribution.
        Prioritizes Double GW weeks (bench plays twice → multiply by 1.8).
        """
        if not available:
            return None

        n_gws = bench_xpts_by_gw.shape[0]
        if n_gws == 0:
            return None

        # Validate GW range for current half
        valid_gws = self._valid_gw_range(current_gw, n_gws, half)
        if not valid_gws:
            return None

        # Sample bench points for each GW
        samples = self._sample_points(bench_xpts_by_gw)  # (n_gws, n_sims, 4)
        bench_pts_per_gw = samples.sum(axis=2)            # (n_gws, n_sims)
        mean_bench_pts = bench_pts_per_gw.mean(axis=1)    # (n_gws,)

        # Restrict to valid GW indices
        valid_indices = [g - current_gw for g in valid_gws if 0 <= g - current_gw < n_gws]
        if not valid_indices:
            return None

        best_idx = valid_indices[np.argmax(mean_bench_pts[valid_indices])]
        best_gw = current_gw + best_idx
        best_pts = mean_bench_pts[best_idx]
        avg_pts = mean_bench_pts[valid_indices].mean()

        confidence = min(1.0, (best_pts - avg_pts) / (avg_pts + 1e-6) + 0.5)

        return ChipRecommendation(
            chip="bench_boost",
            recommended_gw=best_gw,
            confidence=round(float(confidence), 2),
            expected_gain=round(float(best_pts), 1),
            reasoning=(
                f"Expected {best_pts:.1f}xPts from bench in GW{best_gw}. "
                "Target a Double Gameweek for maximum bench contribution."
            ),
            urgency="plan" if best_gw > current_gw + 3 else "urgent",
        )

    def recommend_triple_captain(
        self,
        captain_xpts_by_gw: np.ndarray,   # shape: (n_remaining_gws,) — captain xpts
        fdr_by_gw: np.ndarray,            # shape: (n_remaining_gws,) — fixture FDR
        is_double_gw: np.ndarray,         # shape: (n_remaining_gws,) — bool
        current_gw: int,
        half: str,
        available: bool = True,
    ) -> Optional[ChipRecommendation]:
        """
        TC gives 1 extra captain multiplier (3x vs 2x = +1x captain pts).
        Best used on a Double GW with FDR ≤ 2.
        """
        if not available:
            return None

        n_gws = len(captain_xpts_by_gw)
        valid_gws = self._valid_gw_range(current_gw, n_gws, half)
        if not valid_gws:
            return None

        # TC extra gain = 1x captain points (since normal captain is already 2x)
        # For DGW: captain scores twice, so extra gain = captain_pts × 2 (TC adds ×1 again)
        tc_gains = []
        for g in valid_gws:
            idx = g - current_gw
            if 0 <= idx < n_gws:
                cap_pts = captain_xpts_by_gw[idx]
                fdr_factor = {1: 1.3, 2: 1.2, 3: 1.0, 4: 0.75, 5: 0.5}.get(
                    int(fdr_by_gw[idx]), 1.0
                )
                dgw_mult = 1.8 if is_double_gw[idx] else 1.0
                tc_gains.append((g, cap_pts * fdr_factor * dgw_mult))
            else:
                tc_gains.append((g, 0.0))

        if not tc_gains:
            return None

        best_gw, best_gain = max(tc_gains, key=lambda x: x[1])
        avg_gain = sum(g for _, g in tc_gains) / len(tc_gains)
        confidence = min(1.0, (best_gain / (avg_gain + 1e-6)) * 0.5)

        dgw_flag = is_double_gw[best_gw - current_gw] if 0 <= best_gw - current_gw < n_gws else False
        best_fdr = int(fdr_by_gw[best_gw - current_gw]) if 0 <= best_gw - current_gw < n_gws else 3

        # TC urgency requires: confidence ≥ 0.6 AND (DGW OR FDR ≤ 2) AND within 2 GWs.
        # Plain fixtures at moderate confidence remain "plan" — TC is wasted outside prime GWs.
        is_prime_gw = dgw_flag or best_fdr <= 2
        urgency = (
            "urgent"
            if (best_gw <= current_gw + 2 and confidence >= 0.6 and is_prime_gw)
            else "plan"
        )

        return ChipRecommendation(
            chip="triple_captain",
            recommended_gw=best_gw,
            confidence=round(float(confidence), 2),
            expected_gain=round(float(best_gain), 1),
            reasoning=(
                f"GW{best_gw}: {best_gain:.1f} expected TC bonus"
                + (" (Double GW — captain plays twice!)" if dgw_flag else f" · FDR {best_fdr}")
            ),
            urgency=urgency,
        )

    def recommend_wildcard(
        self,
        current_squad_xpts_5gw: float,
        optimal_squad_xpts_5gw: float,
        current_gw: int,
        half: str,
        available: bool = True,
    ) -> Optional[ChipRecommendation]:
        """
        Wildcard: use when optimal squad outperforms current squad by >15 pts over 5 GWs.
        Also flag pre-major fixture swing.
        """
        if not available:
            return None

        gain = optimal_squad_xpts_5gw - current_squad_xpts_5gw

        # Determine half deadline
        if half == "first":
            deadline_gw = FIRST_HALF_MAX_GW
            urgency = "urgent" if current_gw >= deadline_gw - 2 else "plan"
        else:
            deadline_gw = 38
            urgency = "plan"

        if gain < 15.0:
            return ChipRecommendation(
                chip="wildcard",
                recommended_gw=current_gw,
                confidence=0.3,
                expected_gain=round(gain, 1),
                reasoning=f"Current squad is {gain:.1f}xPts below optimal over 5 GWs. Consider wildcarding.",
                urgency="monitor",
            )

        return ChipRecommendation(
            chip="wildcard",
            recommended_gw=current_gw,
            confidence=min(1.0, gain / 30.0),
            expected_gain=round(gain, 1),
            reasoning=(
                f"Wildcard recommended! Optimal squad is +{gain:.1f}xPts better "
                f"than current over 5 GWs."
            ),
            urgency=urgency,
        )

    def recommend_free_hit(
        self,
        squad_blank_count: int,
        current_gw: int,
        half: str,
        available: bool = True,
    ) -> Optional[ChipRecommendation]:
        """
        Free Hit: recommended when ≥5 starters have a blank GW.
        Lets you field a full playing XI for that GW and revert.
        """
        if not available:
            return None

        if squad_blank_count >= 5:
            return ChipRecommendation(
                chip="free_hit",
                recommended_gw=current_gw,
                confidence=min(1.0, squad_blank_count / 11),
                expected_gain=float(squad_blank_count * 3.5),  # rough estimate
                reasoning=(
                    f"{squad_blank_count}/11 starters have no fixture this GW. "
                    "Use Free Hit to field a full playing squad."
                ),
                urgency="urgent",
            )
        elif squad_blank_count >= 3:
            return ChipRecommendation(
                chip="free_hit",
                recommended_gw=current_gw,
                confidence=0.4,
                expected_gain=float(squad_blank_count * 2.5),
                reasoning=(
                    f"{squad_blank_count} starters blanking — consider Free Hit "
                    "if you can't make enough transfers."
                ),
                urgency="monitor",
            )

        return None

    def get_all_recommendations(
        self,
        chips_available: dict[str, bool],
        current_gw: int,
        half: str,
        bench_xpts_by_gw: Optional[np.ndarray] = None,
        captain_xpts_by_gw: Optional[np.ndarray] = None,
        fdr_by_gw: Optional[np.ndarray] = None,
        is_double_gw: Optional[np.ndarray] = None,
        current_squad_xpts_5gw: float = 0,
        optimal_squad_xpts_5gw: float = 0,
        squad_blank_count: int = 0,
    ) -> list[ChipRecommendation]:
        """Generate all chip recommendations in one call."""
        recs = []
        n_gws = 38 - current_gw + 1

        if bench_xpts_by_gw is None:
            bench_xpts_by_gw = np.zeros((n_gws, 4))
        if captain_xpts_by_gw is None:
            captain_xpts_by_gw = np.zeros(n_gws)
        if fdr_by_gw is None:
            fdr_by_gw = np.full(n_gws, 3)
        if is_double_gw is None:
            is_double_gw = np.zeros(n_gws, dtype=bool)

        for chip_fn, args in [
            (self.recommend_bench_boost, (
                bench_xpts_by_gw, current_gw, half,
                chips_available.get("bench_boost", False),
            )),
            (self.recommend_triple_captain, (
                captain_xpts_by_gw, fdr_by_gw, is_double_gw, current_gw, half,
                chips_available.get("triple_captain", False),
            )),
            (self.recommend_wildcard, (
                current_squad_xpts_5gw, optimal_squad_xpts_5gw, current_gw, half,
                chips_available.get("wildcard", False),
            )),
            (self.recommend_free_hit, (
                squad_blank_count, current_gw, half,
                chips_available.get("free_hit", False),
            )),
        ]:
            rec = chip_fn(*args)
            if rec:
                recs.append(rec)

        return sorted(recs, key=lambda r: r.confidence, reverse=True)

    def _valid_gw_range(self, current_gw: int, n_gws: int, half: str) -> list[int]:
        """Return valid GW numbers for chip use in the current half."""
        if half == "first":
            max_gw = FIRST_HALF_MAX_GW
        else:
            max_gw = 38

        return [
            current_gw + i
            for i in range(n_gws)
            if current_gw + i <= max_gw
        ]


from typing import Optional
