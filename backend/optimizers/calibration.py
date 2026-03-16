"""
Bayesian Calibration Layer — Empirical Bayes EMA correction for xPts predictions.

Algorithm:
  1. After each GW, compute per-player prediction error: e_i = actual_i - predicted_i
  2. Update running bias estimate with EMA:  bias_i = alpha * e_i + (1-alpha) * bias_i_prev
  3. At prediction time, apply correction:  corrected_xpts = raw_xpts + beta * bias_i
  4. Track MAE / RMSE over rolling window for model health monitoring.

alpha controls how fast the bias estimate responds (0.3 = moderately reactive).
beta controls how aggressively the correction is applied (0.5 = half-correction).
"""
from __future__ import annotations

import math
from typing import Optional
from loguru import logger


class BayesianCalibrator:
    """
    Per-player running bias correction with EMA.

    State is stored in Redis as a lightweight JSON hash:
      calibration:{player_id} → {"bias": float, "mae": float, "rmse": float, "n": int}

    The corrected xPts = raw_xpts + beta * bias
    """

    def __init__(self, alpha: float = 0.3, beta: float = 0.5):
        self.alpha = alpha   # EMA learning rate
        self.beta = beta     # Correction strength

    # ── Redis helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _key(player_id: int) -> str:
        return f"calibration:{player_id}"

    async def _load(self, player_id: int) -> dict:
        from core.redis_client import redis_client
        import json
        raw = await redis_client.get(self._key(player_id))
        if raw:
            return json.loads(raw)
        return {"bias": 0.0, "mae_sum": 0.0, "mse_sum": 0.0, "n": 0}

    async def _save(self, player_id: int, state: dict) -> None:
        from core.redis_client import redis_client
        import json
        await redis_client.set(
            self._key(player_id),
            json.dumps(state),
            ex=60 * 60 * 24 * 180,  # 6 months
        )

    # ── Core API ──────────────────────────────────────────────────────────────

    async def update(
        self,
        player_id: int,
        predicted_xpts: float,
        actual_points: float,
    ) -> dict:
        """
        Update calibration state after a GW result is known.

        Returns the updated state including current bias, MAE, RMSE.
        """
        error = actual_points - predicted_xpts
        abs_error = abs(error)

        state = await self._load(player_id)
        n = state["n"] + 1

        # EMA bias update: bias_new = alpha * error + (1-alpha) * bias_old
        old_bias = state["bias"]
        new_bias = self.alpha * error + (1 - self.alpha) * old_bias

        # Cumulative MAE / MSE (for RMSE)
        new_mae_sum = state["mae_sum"] + abs_error
        new_mse_sum = state["mse_sum"] + error ** 2

        updated = {
            "bias": round(new_bias, 4),
            "mae_sum": round(new_mae_sum, 4),
            "mse_sum": round(new_mse_sum, 4),
            "n": n,
        }
        await self._save(player_id, updated)

        mae = new_mae_sum / n
        rmse = math.sqrt(new_mse_sum / n)

        logger.debug(
            f"Calibration update player={player_id}: "
            f"predicted={predicted_xpts:.2f} actual={actual_points:.2f} "
            f"error={error:.2f} new_bias={new_bias:.3f}"
        )

        return {
            "player_id": player_id,
            "bias": round(new_bias, 4),
            "mae": round(mae, 4),
            "rmse": round(rmse, 4),
            "n_observations": n,
            "last_error": round(error, 3),
        }

    async def correct(self, player_id: int, raw_xpts: float) -> float:
        """
        Apply Bayesian correction to a raw xPts prediction.

        corrected = raw_xpts + beta * bias
        Clipped to [0, 30] to prevent nonsensical outputs.
        """
        state = await self._load(player_id)
        bias = state["bias"]
        corrected = raw_xpts + self.beta * bias
        return round(max(0.0, min(30.0, corrected)), 3)

    async def correct_batch(
        self,
        player_ids: list[int],
        raw_xpts_list: list[float],
    ) -> list[float]:
        """Batch-correct xPts for multiple players."""
        results = []
        for pid, raw in zip(player_ids, raw_xpts_list):
            corrected = await self.correct(pid, raw)
            results.append(corrected)
        return results

    async def get_state(self, player_id: int) -> dict:
        """Return current calibration state for a player."""
        state = await self._load(player_id)
        n = max(state["n"], 1)
        return {
            "player_id": player_id,
            "bias": round(state["bias"], 4),
            "mae": round(state["mae_sum"] / n, 4),
            "rmse": round(math.sqrt(state["mse_sum"] / n), 4),
            "n_observations": state["n"],
        }

    async def bulk_update_from_gw(
        self,
        results: list[dict],
        db=None,
    ) -> dict:
        """
        Process a full GW result batch.

        results: list of {"player_id", "predicted_xpts", "actual_points"}
        Optionally persists to PredictionCalibration table if db is provided.
        """
        from models.db.calibration import PredictionCalibration

        updates = []
        for r in results:
            pid = r["player_id"]
            pred = float(r.get("predicted_xpts", 0.0))
            actual = float(r.get("actual_points", 0.0))

            state = await self.update(pid, pred, actual)
            updates.append(state)

            # Optionally persist to DB for long-term analysis
            if db is not None:
                try:
                    record = PredictionCalibration(
                        player_id=pid,
                        gameweek_id=r.get("gameweek_id", 0),
                        predicted_xpts=pred,
                        actual_points=actual,
                        error=round(actual - pred, 4),
                        abs_error=round(abs(actual - pred), 4),
                        model_version=r.get("model_version", "v1"),
                    )
                    db.add(record)
                except Exception as e:
                    logger.warning(f"Failed to persist calibration record: {e}")

        if db is not None:
            try:
                await db.commit()
            except Exception as e:
                logger.error(f"Calibration DB commit failed: {e}")
                await db.rollback()

        total = len(updates)
        avg_mae = sum(u["mae"] for u in updates) / max(total, 1)
        avg_rmse = sum(u["rmse"] for u in updates) / max(total, 1)
        avg_bias = sum(u["bias"] for u in updates) / max(total, 1)

        logger.info(
            f"Calibration bulk update: {total} players | "
            f"avg_MAE={avg_mae:.3f} avg_RMSE={avg_rmse:.3f} avg_bias={avg_bias:.3f}"
        )

        return {
            "players_updated": total,
            "avg_mae": round(avg_mae, 4),
            "avg_rmse": round(avg_rmse, 4),
            "avg_bias": round(avg_bias, 4),
            "detail": updates,
        }


# Singleton
calibrator = BayesianCalibrator(alpha=0.3, beta=0.5)
