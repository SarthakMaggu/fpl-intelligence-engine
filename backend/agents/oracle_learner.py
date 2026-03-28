"""
Oracle Learner — analyses oracle blind spots and improves the xPts model.

After each GW resolves:
  1. Compare Oracle XI vs top FPL team of the week
  2. Identify systematically missed player types by position
  3. Record blind spots in a persistent learning log
  4. Adjust position-specific xPts multipliers based on accumulated patterns

HOW IT ACTUALLY WORKS (honest description):
  - The learner does NOT retrain LightGBM from scratch each GW.
  - Instead it maintains `feature_bias.json` — a set of multipliers applied
    to raw ML predictions BEFORE the ILP optimizer ranks players.
  - Biases are per-position (GK/DEF/MID/FWD) and per-player (for chronic misses).
  - When Oracle misses 3+ MID players in recent GWs, it raises MID multiplier by 5%.
    This means ALL midfielders' xPts are scaled up slightly at next snapshot time,
    making midfielders more likely to appear in the Oracle XI.
  - Per-player boosts: if one player (e.g. Salah) appears in missed list 4+ times
    in the last 10 GWs, that specific player gets a +10% permanent boost.
  - TC threshold auto-lowers if Oracle's TC recommendation threshold was too high
    (i.e. top team used TC when Oracle decided not to recommend it).
  - This is incremental — biases compound across GWs and are persisted to disk.

Full LightGBM retraining uses the separate historical pipeline (historical_fetcher.py).
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

# Position labels used in bias dict keys
_POS_LABELS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
_LABEL_TO_POS = {v: k for k, v in _POS_LABELS.items()}

# How much to nudge position multipliers per learning step
_POS_NUDGE = 0.05          # +5% per step
_POS_MAX = 1.50            # cap at 150% of raw xPts
_PLAYER_BOOST = 0.10       # +10% for chronically missed individual players
_PLAYER_BOOST_MAX = 1.40   # cap at 140% for individual player


class OracleLearner:
    """
    Maintains a rolling learning log of what Oracle consistently misses.
    Produces feature bias adjustments for xPts scoring.

    Bias structure in feature_bias.json:
    {
      "pos_GK": 1.0,       # multiplier for all GKs
      "pos_DEF": 1.0,      # multiplier for all DEFs
      "pos_MID": 1.0,      # multiplier for all MIDs
      "pos_FWD": 1.0,      # multiplier for all FWDs
      "player_Salah": 1.1, # individual player boost (web_name key)
      "tc_threshold": 7.0, # minimum captain xPts to recommend TC
    }
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
        # Optional: list of (player_name, element_type) for missed players
        # so we can compute position-specific patterns
        missed_players_with_pos: Optional[list[tuple[str, int]]] = None,
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
            "missed_with_pos": missed_players_with_pos or [],
            "top_chip": top_chip,
            "chip_miss_reason": chip_miss_reason,
            "oracle_xi": oracle_xi,
            "top_xi": top_xi,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self.log.append(entry)
        self._save_log()

        # Update feature bias from patterns and get insight
        insight = self._update_bias_from_patterns()
        entry["insight"] = insight
        # Re-save with insight attached
        self._save_log()
        return entry

    def _update_bias_from_patterns(self) -> str:
        """
        Analyse rolling log to find systematic blind spots.
        Adjusts position-specific multipliers and per-player boosts.
        Returns an honest, human-readable insight string describing
        what changed and why.
        """
        if len(self.log) < 2:
            return "Not enough GW data for pattern learning yet."

        recent = self.log[-10:]  # analyse last 10 GWs

        # ── 1. Count missed players overall ──────────────────────────────────
        miss_counter: Counter = Counter()
        for e in recent:
            for p in e.get("missed", []):
                miss_counter[p] += 1

        # Players missed 4+ times in last 10 GWs → individual boost
        chronic_individual = [p for p, cnt in miss_counter.most_common(10) if cnt >= 4]

        # ── 2. Position-level miss patterns ──────────────────────────────────
        pos_miss_counter: Counter = Counter()  # "GK", "DEF", "MID", "FWD"
        for e in recent:
            for name, pos_id in e.get("missed_with_pos", []):
                label = _POS_LABELS.get(pos_id)
                if label:
                    pos_miss_counter[label] += 1

        # Positions where Oracle misses 3+ players total in last 10 GWs
        # get a nudge upward
        positions_to_boost: list[str] = [
            pos for pos, cnt in pos_miss_counter.items() if cnt >= 3
        ]

        # ── 3. Chip patterns ─────────────────────────────────────────────────
        chip_usage: Counter = Counter()
        for e in recent:
            chip = e.get("top_chip")
            if chip:
                chip_usage[chip] += 1

        # ── 4. Win rate ───────────────────────────────────────────────────────
        losses = [e for e in recent if not e.get("beat_top")]
        avg_loss_gap = sum(e.get("gap", 0) for e in losses) / max(len(losses), 1)
        win_rate = (len(recent) - len(losses)) / len(recent) * 100

        # ── 5. Apply bias updates ─────────────────────────────────────────────
        bias_changes: list[str] = []

        # Position-level boosts
        for pos_label in positions_to_boost:
            key = f"pos_{pos_label}"
            old_val = self.bias.get(key, 1.0)
            new_val = min(round(old_val + _POS_NUDGE, 3), _POS_MAX)
            if new_val != old_val:
                self.bias[key] = new_val
                bias_changes.append(
                    f"{pos_label} xPts multiplier raised {old_val:.2f}→{new_val:.2f} "
                    f"(missed {pos_miss_counter[pos_label]} {pos_label}s in last 10 GWs)"
                )

        # Individual chronic-miss player boosts
        for player_name in chronic_individual:
            key = f"player_{player_name}"
            old_val = self.bias.get(key, 1.0)
            new_val = min(round(old_val + _PLAYER_BOOST, 3), _PLAYER_BOOST_MAX)
            if new_val != old_val:
                self.bias[key] = new_val
                bias_changes.append(
                    f"{player_name} individual xPts boost raised {old_val:.2f}→{new_val:.2f} "
                    f"(missed {miss_counter[player_name]}x in last 10 GWs)"
                )

        # TC threshold learning
        tc_missed_under_threshold = sum(
            1 for e in recent
            if (e.get("top_chip") or "").lower() in ("3xc", "triple_captain")
            and "may need lowering" in (e.get("chip_miss_reason") or "")
        )
        current_threshold = self.bias.get("tc_threshold", 7.0)
        if tc_missed_under_threshold >= 3 and current_threshold > 5.5:
            new_threshold = round(current_threshold - 0.5, 1)
            self.bias["tc_threshold"] = new_threshold
            bias_changes.append(
                f"TC recommendation threshold lowered {current_threshold}→{new_threshold} xPts "
                f"(missed TC opportunity {tc_missed_under_threshold} times)"
            )
            logger.info(f"OracleLearner: TC threshold {current_threshold} → {new_threshold}")

        self._save_bias()

        # ── 6. Build honest insight string ────────────────────────────────────
        parts = [
            f"Oracle beats top team {win_rate:.0f}% of recent GWs"
            + (f", avg gap when losing: {avg_loss_gap:.1f} pts" if losses else "")
        ]

        if bias_changes:
            parts.append("Self-improvement applied: " + "; ".join(bias_changes))
        elif chronic_individual or positions_to_boost:
            parts.append("Pattern detected but multipliers already at cap — no further adjustment")
        else:
            parts.append("No systematic blind spots detected in last 10 GWs")

        if chip_usage:
            top_chip_entry = chip_usage.most_common(1)[0]
            parts.append(
                f"Top teams used {top_chip_entry[0]} chip {top_chip_entry[1]}/{len(recent)} GWs "
                f"— Oracle does not play chips on users' behalf"
            )

        return " · ".join(parts)

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

        # Summarise active biases for display
        pos_biases = {
            k: v for k, v in self.bias.items()
            if k.startswith("pos_") and v != 1.0
        }
        player_boosts = {
            k.replace("player_", ""): v for k, v in self.bias.items()
            if k.startswith("player_")
        }

        return {
            "gws_analysed": len(self.log),
            "beat_top_rate": round(beat_rate * 100, 1),
            "chronic_misses": chronic,
            "bias": self.bias,
            "position_biases_active": pos_biases,
            "player_boosts_active": player_boosts,
            "last_insight": self.log[-1].get("insight", "") if self.log else "",
        }

    def apply_bias(self, player_name: str, raw_xpts: float, element_type: Optional[int] = None) -> float:
        """
        Apply learned feature bias to a raw xPts score.

        Applies in order:
          1. Position-level multiplier (e.g. pos_MID = 1.05 → all MIDs get +5%)
          2. Individual player boost (e.g. player_Salah = 1.10 → Salah gets additional +10%)

        Both multipliers stack: a MID with pos_MID=1.05 and individual boost=1.10
        ends up at xpts * 1.05 * 1.10 = xpts * 1.155.
        """
        result = raw_xpts

        # Position multiplier
        if element_type is not None:
            pos_label = _POS_LABELS.get(element_type)
            if pos_label:
                pos_mult = self.bias.get(f"pos_{pos_label}", 1.0)
                result = result * pos_mult

        # Individual player boost (web_name key)
        if player_name:
            player_mult = self.bias.get(f"player_{player_name}", 1.0)
            result = result * player_mult

        return round(result, 2)
