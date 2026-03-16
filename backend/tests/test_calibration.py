"""
Tests for BayesianCalibrator.

Uses a mock Redis client to avoid real Redis dependency.
"""
import pytest
import asyncio
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from unittest.mock import AsyncMock, patch, MagicMock


# ── Mock Redis ─────────────────────────────────────────────────────────────────

class MockRedis:
    """In-memory mock for async Redis."""
    def __init__(self):
        self._store: dict = {}

    async def get(self, key: str):
        val = self._store.get(key)
        return val.encode() if isinstance(val, str) else val

    async def set(self, key: str, value, ex=None):
        self._store[key] = value

    async def ping(self): return True


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_redis():
    return MockRedis()


@pytest.fixture
def calibrator(mock_redis):
    from optimizers.calibration import BayesianCalibrator
    cal = BayesianCalibrator(alpha=0.3, beta=0.5)
    return cal, mock_redis


@pytest.mark.asyncio
async def test_initial_state_is_zero(calibrator, mock_redis):
    """Fresh player has zero bias."""
    cal, redis = calibrator
    with patch("core.redis_client.redis_client", redis):
        state = await cal.get_state(player_id=1)
    assert state["bias"] == 0.0
    assert state["n_observations"] == 0


@pytest.mark.asyncio
async def test_update_increases_n(calibrator, mock_redis):
    """Each update increments n_observations."""
    cal, redis = calibrator
    with patch("core.redis_client.redis_client", redis):
        for i in range(3):
            await cal.update(player_id=1, predicted_xpts=5.0, actual_points=6.0 + i)
        state = await cal.get_state(player_id=1)
    assert state["n_observations"] == 3


@pytest.mark.asyncio
async def test_positive_bias_from_underestimation(calibrator, mock_redis):
    """Consistently under-predicting → positive bias (correct upward)."""
    cal, redis = calibrator
    with patch("core.redis_client.redis_client", redis):
        for _ in range(10):
            await cal.update(player_id=2, predicted_xpts=3.0, actual_points=6.0)
        state = await cal.get_state(player_id=2)
    assert state["bias"] > 0, "Should have positive bias after under-prediction"


@pytest.mark.asyncio
async def test_negative_bias_from_overestimation(calibrator, mock_redis):
    """Consistently over-predicting → negative bias (correct downward)."""
    cal, redis = calibrator
    with patch("core.redis_client.redis_client", redis):
        for _ in range(10):
            await cal.update(player_id=3, predicted_xpts=8.0, actual_points=2.0)
        state = await cal.get_state(player_id=3)
    assert state["bias"] < 0, "Should have negative bias after over-prediction"


@pytest.mark.asyncio
async def test_correct_applies_correction(calibrator, mock_redis):
    """correct() adds beta * bias to raw xPts."""
    cal, redis = calibrator
    with patch("core.redis_client.redis_client", redis):
        # Force a known state
        state = {"bias": 2.0, "mae_sum": 2.0, "mse_sum": 4.0, "n": 5}
        await redis.set(cal._key(10), json.dumps(state))
        corrected = await cal.correct(player_id=10, raw_xpts=5.0)
    # corrected = 5.0 + 0.5 * 2.0 = 6.0
    assert corrected == pytest.approx(6.0, abs=0.01)


@pytest.mark.asyncio
async def test_correction_clipped_at_zero(calibrator, mock_redis):
    """Corrected xPts cannot go below 0."""
    cal, redis = calibrator
    with patch("core.redis_client.redis_client", redis):
        state = {"bias": -20.0, "mae_sum": 0.0, "mse_sum": 0.0, "n": 5}
        await redis.set(cal._key(11), json.dumps(state))
        corrected = await cal.correct(player_id=11, raw_xpts=2.0)
    assert corrected >= 0.0


@pytest.mark.asyncio
async def test_batch_correct(calibrator, mock_redis):
    """correct_batch returns a list of corrected values."""
    cal, redis = calibrator
    with patch("core.redis_client.redis_client", redis):
        results = await cal.correct_batch([1, 2, 3], [4.0, 5.0, 6.0])
    assert len(results) == 3
    assert all(isinstance(r, float) for r in results)


@pytest.mark.asyncio
async def test_mae_converges(calibrator, mock_redis):
    """MAE should converge toward the true absolute error over many observations."""
    cal, redis = calibrator
    true_error = 1.5
    with patch("core.redis_client.redis_client", redis):
        for _ in range(50):
            await cal.update(player_id=99, predicted_xpts=5.0, actual_points=5.0 + true_error)
        state = await cal.get_state(player_id=99)
    # MAE should be close to true_error after 50 observations
    assert abs(state["mae"] - true_error) < 0.5
