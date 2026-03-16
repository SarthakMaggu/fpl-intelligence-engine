"""
Oracle Learner — analyses oracle blind spots and improves the xPts model.

After each GW resolves:
  1. Compare Oracle XI vs top FPL team of the week
  2. Identify systematically missed player types (high-form, set-piece takers, etc.)
  3. Record blind spots in a persistent learning log
  4. Adjust xPts model feature weights based on accumulated patterns

The learning loop is lightweight — it does NOT retrain LightGBM from scratch each GW.
Instead it maintains a `feature_bias` file that scales raw model predictions before
ranking players. Full retraining uses the historical pipeline (see historical_fetcher.py).
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional
from datetime import datetime
from loguru import logger

LEARNING_LOG_PATH = Path("models/ml/artifacts/oracle_learning_log.json")
FEATURE_BIAS_PATH = Path("models/ml/artifacts/feature_bias.json")
LEARNING_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


class OracleLearner:
    """
    Maintains a rolling learning log of what Oracle consistently misses.
    Produces feature bias adjustments for xPts scoring.
    """

    def __init__(self):
        self.log: list[dict] = self._load_log()
        self.bias: dict[str, float] = self._load_bias()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load_log(self) -> list[dict]:
        if LEARNING_LOG_PATH.exists():
            try:
                return json.loads(LEARNING_LOG_PATH.read_text())
            except Exception:
                return []
        return []

    def _save_log(self) -> None:
        LEARNING_LOG_PATH.write_text(json.dumps(self.log, indent=2))

    def _load_bias(self) -> dict[str, float]:
        if FEATURE_BIAS_PATH.exists():
            try:
                return json.loads(FEATURE_BIAS_PATH.read_text())
            except Exception:
                return {}
        return {}

    def _save_bias(self) -> None:
        FEATURE_BIAS_PATH.write_text(json.dumps(self.bias, indent=2))

    # ── Core learning step ────────────────────────────────────────────────────

    def record_gw_result(
        self,
        gw_id: int,
        oracle_pts: float,
        top_team_pts: int,
        missed_players: list[str],
        top_chip: Optional[str],
        oracle_xi: list[str],
        top_xi: list[str],
        chip_miss_reason: Optional[str] = None,
    ) -> dict:
        """
        Record one GW's learning data.
        Returns the insight dict that should be stored in oracle_blind_spots_json.
        top_team_pts should be the NORMALISED score (chip contribution stripped).
        """
        oracle_beat_top = oracle_pts >= top_team_pts
        gap = top_team_pts - oracle_pts

        entry = {
            "gw": gw_id,
            "oracle_pts": oracle_pts,
            "top_pts": top_team_pts,  # normalised
            "beat_top": oracle_beat_top,
            "gap": gap,
            "missed": missed_players,
            "top_chip": top_chip,
            "chip_miss_reason": chip_miss_reason,
            "oracle_xi": oracle_xi,
            "top_xi": top_xi,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self.log.append(entry)
        self._save_log()

        # Update feature bias from patterns
        insight = self._update_bias_from_patterns()
        entry["insight"] = insight
        return entry

    def _update_bias_from_patterns(self) -> str:
        """
        Analyse rolling log to find systematic blind spots.
        Returns a human-readable insight string.
        """
        if len(self.log) < 2:
            return "Not enough GW data for pattern learning yet."

        recent = self.log[-10:]  # analyse last 10 GWs

        # Count how often each missed player appears
        miss_counter: Counter = Counter()
        for e in recent:
            for p in e.get("missed", []):
                miss_counter[p] += 1

        # Players missed 3+ times in last 10 GWs are a systematic blind spot
        chronic_misses = [p for p, cnt in miss_counter.most_common(10) if cnt >= 2]

        # Chip patterns: if top team frequently used a chip Oracle doesn't account for
        chip_usage: Counter = Counter()
        for e in recent:
            chip = e.get("top_chip")
            if chip:
                chip_usage[chip] += 1

        # Average gap when Oracle lost to top team
        losses = [e for e in recent if not e.get("beat_top")]
        avg_loss_gap = sum(e["gap"] for e in losses) / max(len(losses), 1)

        # Build insight message
        parts = []
        if chronic_misses:
            parts.append(f"Consistently missed: {', '.join(chronic_misses[:5])}")
        if chip_usage:
            top_chip = chip_usage.most_common(1)[0]
            parts.append(f"Top teams often use {top_chip[0]} chip ({top_chip[1]}/{len(recent)} GWs)")
        if losses:
            win_rate = (len(recent) - len(losses)) / len(recent) * 100
            parts.append(
                f"Oracle beats top team {win_rate:.0f}% of recent GWs, avg gap when losing: {avg_loss_gap:.1f}pts"
            )

        # Adjust feature bias: upweight "form" if high-form players are being missed
        if len(chronic_misses) >= 3:
            self.bias["form"] = min(self.bias.get("form", 1.0) + 0.05, 1.5)
            self.bias["points_per_game"] = min(self.bias.get("points_per_game", 1.0) + 0.03, 1.4)

        if chip_usage.get("3xc", 0) >= 3 or chip_usage.get("bboost", 0) >= 3:
            # Top teams are using chips Oracle ignores — flag in insight
            parts.append("⚡ Consider chip timing in Oracle recommendations")

        # ── TC threshold learning ─────────────────────────────────────────────
        # Count entries where top team used TC and Oracle missed it with
        # "threshold may need lowering" reason — if ≥3 times in 10 GWs, lower threshold
        tc_missed_under_threshold = sum(
            1 for e in recent
            if (e.get("top_chip") or "").lower() in ("3xc", "triple_captain")
            and "may need lowering" in (e.get("chip_miss_reason") or "")
        )
        current_threshold = self.bias.get("tc_threshold", 7.0)

        if tc_missed_under_threshold >= 3 and current_threshold > 5.5:
            new_threshold = round(current_threshold - 0.5, 1)
            self.bias["tc_threshold"] = new_threshold
            parts.append(
                f"⬇ TC threshold lowered {current_threshold} → {new_threshold} "
                f"(missed {tc_missed_under_threshold} times under threshold)"
            )
            logger.info(f"OracleLearner: TC threshold updated {current_threshold} → {new_threshold}")

        self._save_bias()
        return " · ".join(parts) if parts else "Oracle performance within expected range."

    def get_summary(self) -> dict:
        """Return a summary of Oracle learning for display."""
        if not self.log:
            return {"gws_analysed": 0, "beat_top_rate": None, "chronic_misses": [], "bias": {}}

        recent = self.log[-10:]
        beat_rate = sum(1 for e in recent if e.get("beat_top")) / len(recent)

        miss_counter: Counter = Counter()
        for e in recent:
            for p in e.get("missed", []):
                miss_counter[p] += 1
        chronic = [p for p, cnt in miss_counter.most_common(5) if cnt >= 2]

        return {
            "gws_analysed": len(self.log),
            "beat_top_rate": round(beat_rate * 100, 1),
            "chronic_misses": chronic,
            "bias": self.bias,
            "last_insight": self.log[-1].get("insight", "") if self.log else "",
        }

    def apply_bias(self, player_name: str, raw_xpts: float) -> float:
        """
        Apply learned feature bias to a raw xPts score.
        Right now bias is global (not player-specific); future: per-player bias.
        """
        form_mult = self.bias.get("form", 1.0)
        ppg_mult = self.bias.get("points_per_game", 1.0)
        # Weighted average of bias multipliers applied to xPts
        combined = (form_mult + ppg_mult) / 2
        return round(raw_xpts * combined, 2)
