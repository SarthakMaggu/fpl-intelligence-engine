"""
Model Loader — versioned ML artifact management.

Provides:
  get_current_model(model_name)  — load the production-flagged artifact
  promote_model(model_name, version, artifact_path, metrics)  — register and
      promote a new model, demoting the previous production version.

On startup, all prediction code should call get_current_model("xpts_lgbm")
instead of hardcoded file paths, so that the model registry controls which
artifact is live.

Rollback is as simple as:
  UPDATE model_registry SET is_current_production = TRUE WHERE version = 'X'
  (and set the current one to FALSE)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import joblib
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AsyncSessionLocal
from models.db.model_registry import ModelRegistry

logger = logging.getLogger(__name__)

# Default artifact directory (matches the Docker volume mount)
DEFAULT_ARTIFACT_DIR = Path("models/ml/artifacts")
DEFAULT_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

# Module-level in-memory cache: {model_name: (version, model_object)}
_model_cache: Dict[str, tuple[str, Any]] = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_current_model(model_name: str) -> Optional[Any]:
    """
    Load and return the current production model for `model_name`.

    Strategy:
    1. Check in-memory cache — return immediately if version matches DB.
    2. Look up model_registry for is_current_production=True + model_name.
    3. Load artifact from artifact_path (or fallback to legacy path).
    4. Cache and return.

    Returns None if no production model is registered (caller uses cold start).
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ModelRegistry).where(
                ModelRegistry.model_name == model_name,
                ModelRegistry.is_current_production == True,  # noqa: E712
            )
        )
        registry_row = result.scalar_one_or_none()

    if registry_row is None:
        # Fall back to legacy hardcoded path for backward compatibility
        legacy_path = DEFAULT_ARTIFACT_DIR / f"{model_name.replace('_lgbm', '_model')}.pkl"
        if legacy_path.exists():
            try:
                model = joblib.load(legacy_path)
                logger.info(
                    f"[model_loader] No registry entry for '{model_name}' — "
                    f"loaded legacy artifact: {legacy_path}"
                )
                _model_cache[model_name] = ("legacy", model)
                return model
            except Exception as e:
                logger.warning(f"[model_loader] Legacy load failed for {legacy_path}: {e}")
        return None

    # Check if cached version matches
    cached = _model_cache.get(model_name)
    if cached and cached[0] == registry_row.version:
        return cached[1]

    # Load from registry artifact_path
    artifact_path = (
        Path(registry_row.artifact_path)
        if registry_row.artifact_path
        else DEFAULT_ARTIFACT_DIR / f"{model_name}.pkl"
    )

    if not artifact_path.exists():
        logger.error(
            f"[model_loader] Artifact not found: {artifact_path} "
            f"(model={model_name} version={registry_row.version})"
        )
        return None

    try:
        model = joblib.load(artifact_path)
        _model_cache[model_name] = (registry_row.version, model)
        logger.info(
            f"[model_loader] Loaded '{model_name}' v{registry_row.version} "
            f"from {artifact_path} (MAE={registry_row.val_mae})"
        )
        return model
    except Exception as e:
        logger.error(f"[model_loader] Failed to load {artifact_path}: {e}")
        return None


async def promote_model(
    model_name: str,
    version: str,
    artifact_path: str,
    metrics: Dict[str, float],
    *,
    only_if_better: bool = True,
    tolerance: float = 0.05,
) -> bool:
    """
    Register a new model version and promote it to production if metrics are better.

    Args:
        model_name: e.g. "xpts_lgbm"
        version: e.g. "2026.03.15.001"
        artifact_path: absolute or relative path to the saved .pkl file
        metrics: dict with keys "val_mae", "val_rmse", "val_rank_corr", etc.
        only_if_better: if True, only promote when new val_mae is lower than current
                        production (or within tolerance, in case of ties)
        tolerance: fractional tolerance — promote if new_mae <= current_mae * (1 + tolerance)

    Returns:
        True if the new version was promoted to production, False otherwise.
    """
    new_mae = float(metrics.get("val_mae", 999.0))

    async with AsyncSessionLocal() as db:
        # Load current production model's MAE for comparison
        curr_res = await db.execute(
            select(ModelRegistry).where(
                ModelRegistry.model_name == model_name,
                ModelRegistry.is_current_production == True,  # noqa: E712
            )
        )
        current = curr_res.scalar_one_or_none()

        if only_if_better and current is not None and current.val_mae is not None:
            current_mae = float(current.val_mae)
            threshold = current_mae * (1 + tolerance)
            if new_mae > threshold:
                logger.info(
                    f"[model_loader] Skipping promotion: new MAE {new_mae:.3f} "
                    f"> current MAE {current_mae:.3f} × (1+{tolerance}) = {threshold:.3f}"
                )
                # Still register the artefact for auditability, but not production
                await _insert_registry_row(db, model_name, version, artifact_path, metrics, False)
                await db.commit()
                return False

        # Demote current production model
        if current is not None:
            await db.execute(
                update(ModelRegistry)
                .where(
                    ModelRegistry.model_name == model_name,
                    ModelRegistry.is_current_production == True,  # noqa: E712
                )
                .values(is_current_production=False)
            )

        # Insert new production row
        await _insert_registry_row(db, model_name, version, artifact_path, metrics, True)
        await db.commit()

    # Invalidate cache so next get_current_model() reloads from disk
    _model_cache.pop(model_name, None)

    logger.info(
        f"[model_loader] Promoted '{model_name}' v{version} to production "
        f"(MAE={new_mae:.3f})"
    )
    return True


async def _insert_registry_row(
    db: AsyncSession,
    model_name: str,
    version: str,
    artifact_path: str,
    metrics: Dict[str, float],
    is_production: bool,
) -> None:
    """Insert a new row into model_registry (helper)."""
    row = ModelRegistry(
        model_name=model_name,
        version=version,
        artifact_path=artifact_path,
        val_mae=metrics.get("val_mae"),
        val_rmse=metrics.get("val_rmse"),
        val_rank_corr=metrics.get("val_rank_corr"),
        val_top10_hit_rate=metrics.get("val_top10_hit_rate"),
        train_gw_start=metrics.get("train_gw_start"),
        train_gw_end=metrics.get("train_gw_end"),
        is_current_production=is_production,
    )
    db.add(row)


def get_current_model_sync(model_name: str) -> Optional[Any]:
    """
    Synchronous wrapper around get_current_model for use in non-async contexts.
    Creates a new event loop if necessary (e.g. during model train scripts).
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # In an async context — use the cache only (cannot await here)
            cached = _model_cache.get(model_name)
            return cached[1] if cached else None
        return loop.run_until_complete(get_current_model(model_name))
    except Exception as e:
        logger.warning(f"[model_loader] get_current_model_sync failed: {e}")
        return None
