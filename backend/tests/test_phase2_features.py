"""
Phase 2 feature tests — run against the live Docker backend + pure unit tests.

Covers:
  - GET /api/health/detailed  (new Phase 2 endpoint)
  - POST /api/user/profile, GET /api/user/profile, DELETE /api/user/profile
  - _normalise_chip_score() — TC, BB, WC, FH, no-chip cases
  - XPtsModel.apply_calibration() — corrections, clipping, empty cases

Run:
    pytest backend/tests/test_phase2_features.py -v

Requires for integration tests:
  - Docker stack running (docker compose up -d)
"""
import sys
import os
import pytest
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_URL = os.getenv("API_URL", "http://localhost:8000")
TEAM_ID  = int(os.getenv("FPL_TEAM_ID", "8433551"))
TEST_EMAIL = "phase2test@fpl-test.invalid"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    import httpx
    with httpx.Client(base_url=BASE_URL, timeout=15.0) as c:
        yield c


# ===========================================================================
# 1. GET /api/health/detailed
# ===========================================================================

class TestDetailedHealth:
    def test_returns_200(self, client):
        r = client.get("/api/health/detailed")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:200]}"

    def test_top_level_status_ok(self, client):
        data = client.get("/api/health/detailed").json()
        assert data.get("status") == "ok"

    def test_services_block_present(self, client):
        data = client.get("/api/health/detailed").json()
        assert "services" in data
        svcs = data["services"]
        assert "redis" in svcs
        assert "database" in svcs

    def test_scheduler_block_has_running_flag(self, client):
        data = client.get("/api/health/detailed").json()
        assert "scheduler" in data
        sched = data["scheduler"]
        assert "running" in sched
        assert isinstance(sched["running"], bool)

    def test_scheduler_jobs_is_list(self, client):
        data = client.get("/api/health/detailed").json()
        jobs = data.get("scheduler", {}).get("jobs", [])
        assert isinstance(jobs, list)

    def test_scheduler_jobs_have_id_and_next_run(self, client):
        data = client.get("/api/health/detailed").json()
        jobs = data.get("scheduler", {}).get("jobs", [])
        for job in jobs[:5]:
            assert "id" in job, f"Job missing 'id': {job}"
            # next_run may be None for jobs that haven't been scheduled yet
            assert "next_run" in job

    def test_ml_block_present(self, client):
        data = client.get("/api/health/detailed").json()
        assert "ml" in data
        ml = data["ml"]
        assert "model_trained" in ml
        assert isinstance(ml["model_trained"], bool)

    def test_ml_mae_is_float_or_null(self, client):
        data = client.get("/api/health/detailed").json()
        mae = data.get("ml", {}).get("current_mae")
        assert mae is None or isinstance(mae, float)

    def test_news_block_present(self, client):
        data = client.get("/api/health/detailed").json()
        assert "news" in data
        news = data["news"]
        assert "articles_cached" in news
        assert "players_with_sentiment" in news

    def test_news_articles_cached_is_int(self, client):
        data = client.get("/api/health/detailed").json()
        articles = data.get("news", {}).get("articles_cached", 0)
        assert isinstance(articles, int)

    def test_oracle_block_present(self, client):
        data = client.get("/api/health/detailed").json()
        assert "oracle" in data
        oracle = data["oracle"]
        assert "tc_threshold" in oracle
        assert isinstance(oracle["tc_threshold"], float)

    def test_oracle_tc_threshold_in_valid_range(self, client):
        data = client.get("/api/health/detailed").json()
        tc = data.get("oracle", {}).get("tc_threshold", 7.0)
        assert 4.0 <= tc <= 10.0, f"TC threshold {tc} out of valid range"


# ===========================================================================
# 2. User profile endpoints  (POST / GET / DELETE)
# ===========================================================================

class TestUserProfile:
    def test_upsert_profile_returns_200(self, client):
        r = client.post(
            "/api/user/profile",
            json={"team_id": TEAM_ID, "email": TEST_EMAIL},
        )
        assert r.status_code == 200, f"Got {r.status_code}: {r.text[:300]}"

    def test_upsert_profile_response_has_email(self, client):
        r = client.post(
            "/api/user/profile",
            json={"team_id": TEAM_ID, "email": TEST_EMAIL},
        )
        data = r.json()
        assert "email" in data or "id" in data or "team_id" in data, \
            f"Profile response missing expected fields: {data}"

    def test_get_profile_returns_200(self, client):
        # Make sure profile exists first
        client.post(
            "/api/user/profile",
            json={"team_id": TEAM_ID, "email": TEST_EMAIL},
        )
        r = client.get("/api/user/profile", params={"team_id": TEAM_ID})
        assert r.status_code == 200, f"Got {r.status_code}: {r.text[:300]}"

    def test_get_profile_has_correct_email(self, client):
        client.post(
            "/api/user/profile",
            json={"team_id": TEAM_ID, "email": TEST_EMAIL},
        )
        r = client.get("/api/user/profile", params={"team_id": TEAM_ID})
        data = r.json()
        assert data.get("email") == TEST_EMAIL

    def test_get_profile_has_team_id(self, client):
        r = client.get("/api/user/profile", params={"team_id": TEAM_ID})
        data = r.json()
        assert data.get("team_id") == TEAM_ID

    def test_get_profile_unknown_team_id_returns_null_email(self, client):
        """API returns 200 with email=null for unknown/uncreated team profiles."""
        r = client.get("/api/user/profile", params={"team_id": 9999999})
        assert r.status_code == 200
        data = r.json()
        # No email registered for this team — email field should be null/absent
        assert data.get("email") is None

    def test_upsert_idempotent_returns_200(self, client):
        """Upserting the same email twice should be fine."""
        r1 = client.post("/api/user/profile", json={"team_id": TEAM_ID, "email": TEST_EMAIL})
        r2 = client.post("/api/user/profile", json={"team_id": TEAM_ID, "email": TEST_EMAIL})
        assert r1.status_code == 200
        assert r2.status_code == 200

    def test_upsert_invalid_email_returns_error(self, client):
        r = client.post(
            "/api/user/profile",
            json={"team_id": TEAM_ID, "email": "not-an-email"},
        )
        # Should be 422 (validation) or 400 (bad request)
        assert r.status_code in (400, 422), f"Expected 400/422, got {r.status_code}"

    def test_delete_profile_returns_200_or_404(self, client):
        r = client.delete("/api/user/profile", params={"team_id": TEAM_ID})
        assert r.status_code in (200, 404), f"Got {r.status_code}: {r.text[:200]}"

    def test_get_after_delete_returns_null_email(self, client):
        """After deletion, GET returns 200 with email=null (profile cleared, not 404)."""
        client.delete("/api/user/profile", params={"team_id": TEAM_ID})
        r = client.get("/api/user/profile", params={"team_id": TEAM_ID})
        assert r.status_code == 200
        data = r.json()
        assert data.get("email") is None


# ===========================================================================
# 3. Oracle chip normalisation — unit tests (no Docker required)
# ===========================================================================

# Import the function under test directly (sys.path already set above)
try:
    from api.routes.oracle import _normalise_chip_score
    ORACLE_IMPORTABLE = True
except ImportError:
    ORACLE_IMPORTABLE = False


@pytest.mark.skipif(not ORACLE_IMPORTABLE, reason="oracle module not importable outside Docker")
class TestNormaliseChipScore:
    """Unit tests for _normalise_chip_score() — no DB/API needed."""

    # --- Triple Captain ---

    def test_tc_strips_one_times_captain_pts(self):
        """Raw 3× captain = 36. Oracle counts 2×. Strip 1× = 12. Result = 36 - 12 = 24."""
        live_map = {101: 12}  # captain scored 12 pts
        norm, adj, reason = _normalise_chip_score(
            raw_points=36, chip="3xc", live_map=live_map,
            captain_id=101, bench_ids=[],
        )
        assert norm == 24
        assert adj == 12
        assert reason is None  # reason is set later by chip-miss logic

    def test_tc_canonical_triple_captain_string(self):
        """'triple_captain' chip string also handled."""
        live_map = {5: 8}
        norm, adj, reason = _normalise_chip_score(
            raw_points=58, chip="triple_captain", live_map=live_map,
            captain_id=5, bench_ids=[],
        )
        assert adj == 8
        assert norm == 50

    def test_tc_zero_captain_pts_no_adjustment(self):
        """Captain scored 0 — no adjustment needed."""
        live_map = {7: 0}
        norm, adj, reason = _normalise_chip_score(
            raw_points=42, chip="3xc", live_map=live_map,
            captain_id=7, bench_ids=[],
        )
        assert adj == 0
        assert norm == 42

    def test_tc_unknown_captain_id_defaults_to_zero(self):
        """Captain ID not in live_map — treat as 0 pts."""
        live_map = {999: 15}
        norm, adj, _ = _normalise_chip_score(
            raw_points=55, chip="3xc", live_map=live_map,
            captain_id=1, bench_ids=[],
        )
        assert adj == 0
        assert norm == 55

    # --- Bench Boost ---

    def test_bb_strips_bench_player_pts(self):
        """Bench players scored 2+5+7=14. Strip all 14."""
        live_map = {10: 2, 11: 5, 12: 7}
        norm, adj, reason = _normalise_chip_score(
            raw_points=90, chip="bboost", live_map=live_map,
            captain_id=None, bench_ids=[10, 11, 12],
        )
        assert adj == 14
        assert norm == 76
        assert reason is None

    def test_bb_canonical_bench_boost_string(self):
        live_map = {20: 6, 21: 3}
        norm, adj, _ = _normalise_chip_score(
            raw_points=70, chip="bench_boost", live_map=live_map,
            captain_id=None, bench_ids=[20, 21],
        )
        assert adj == 9
        assert norm == 61

    def test_bb_bench_ids_not_in_live_map_zeros(self):
        """Bench player not in live_map — contributes 0."""
        norm, adj, _ = _normalise_chip_score(
            raw_points=55, chip="bboost", live_map={},
            captain_id=None, bench_ids=[100, 200],
        )
        assert adj == 0
        assert norm == 55

    def test_bb_empty_bench_ids(self):
        norm, adj, _ = _normalise_chip_score(
            raw_points=60, chip="bboost", live_map={1: 8},
            captain_id=None, bench_ids=[],
        )
        assert adj == 0
        assert norm == 60

    # --- Wildcard / Free Hit ---

    def test_wildcard_no_adjustment_returns_raw(self):
        norm, adj, reason = _normalise_chip_score(
            raw_points=75, chip="wildcard", live_map={},
            captain_id=None, bench_ids=[],
        )
        assert norm == 75
        assert adj == 0
        assert reason is not None
        assert "wildcard" in reason.lower() or "wc" in reason.lower() or "unreliable" in reason.lower()

    def test_free_hit_no_adjustment_returns_raw(self):
        norm, adj, reason = _normalise_chip_score(
            raw_points=82, chip="freehit", live_map={},
            captain_id=None, bench_ids=[],
        )
        assert norm == 82
        assert adj == 0
        assert reason is not None

    def test_free_hit_alternative_string(self):
        norm, adj, reason = _normalise_chip_score(
            raw_points=65, chip="free_hit", live_map={},
            captain_id=None, bench_ids=[],
        )
        assert norm == 65
        assert reason is not None

    # --- No chip ---

    def test_no_chip_returns_raw_unchanged(self):
        norm, adj, reason = _normalise_chip_score(
            raw_points=54, chip=None, live_map={1: 12},
            captain_id=1, bench_ids=[2, 3],
        )
        assert norm == 54
        assert adj == 0
        assert reason is None

    def test_empty_chip_string_treated_as_no_chip(self):
        norm, adj, reason = _normalise_chip_score(
            raw_points=67, chip="", live_map={},
            captain_id=None, bench_ids=[],
        )
        assert norm == 67
        assert adj == 0
        assert reason is None

    # --- Edge cases ---

    def test_case_insensitive_chip_matching(self):
        """Chip strings should be matched case-insensitively."""
        live_map = {3: 10}
        norm, adj, _ = _normalise_chip_score(
            raw_points=40, chip="3XC", live_map=live_map,
            captain_id=3, bench_ids=[],
        )
        assert adj == 10
        assert norm == 30


# ===========================================================================
# 4. XPtsModel.apply_calibration() — unit tests
# ===========================================================================

try:
    from models.ml.xpts_model import XPtsModel
    XPTS_IMPORTABLE = True
except ImportError:
    XPTS_IMPORTABLE = False


@pytest.mark.skipif(not XPTS_IMPORTABLE, reason="xpts_model not importable outside container")
class TestApplyCalibration:
    """Unit tests for XPtsModel.apply_calibration() — no DB/API needed."""

    @pytest.fixture(autouse=True)
    def model(self):
        self.m = XPtsModel()
        # Don't require a trained model — calibration works independently

    def _make_df(self, rows: list[dict]) -> pd.DataFrame:
        return pd.DataFrame(rows)

    def test_returns_ndarray(self):
        df = self._make_df([{"element_type": 3, "price_millions": 7.0}])
        preds = np.array([4.5])
        cal_map = {(3, 7): 0.5}
        result = self.m.apply_calibration(preds, df, cal_map)
        assert isinstance(result, np.ndarray)

    def test_applies_positive_correction(self):
        """Residual +0.8 → raw 4.0 → corrected 4.8."""
        df = self._make_df([{"element_type": 3, "price_millions": 7.0}])
        preds = np.array([4.0])
        cal_map = {(3, 7): 0.8}
        result = self.m.apply_calibration(preds, df, cal_map)
        assert abs(result[0] - 4.8) < 1e-9

    def test_applies_negative_correction(self):
        """Residual -0.5 → raw 5.0 → corrected 4.5."""
        df = self._make_df([{"element_type": 2, "price_millions": 5.0}])
        preds = np.array([5.0])
        cal_map = {(2, 5): -0.5}
        result = self.m.apply_calibration(preds, df, cal_map)
        assert abs(result[0] - 4.5) < 1e-9

    def test_clips_correction_at_positive_1_5(self):
        """Residual 2.0 → clipped to +1.5."""
        df = self._make_df([{"element_type": 4, "price_millions": 9.0}])
        preds = np.array([3.0])
        cal_map = {(4, 9): 2.0}
        result = self.m.apply_calibration(preds, df, cal_map)
        assert abs(result[0] - 4.5) < 1e-9

    def test_clips_correction_at_negative_1_5(self):
        """Residual -3.0 → clipped to -1.5."""
        df = self._make_df([{"element_type": 1, "price_millions": 4.0}])
        preds = np.array([5.0])
        cal_map = {(1, 4): -3.0}
        result = self.m.apply_calibration(preds, df, cal_map)
        assert abs(result[0] - 3.5) < 1e-9

    def test_correction_never_produces_negative_xpts(self):
        """Prediction + correction must be ≥ 0.0."""
        df = self._make_df([{"element_type": 2, "price_millions": 4.0}])
        preds = np.array([0.8])
        cal_map = {(2, 4): -1.5}  # would push to -0.7
        result = self.m.apply_calibration(preds, df, cal_map)
        assert result[0] >= 0.0

    def test_unknown_group_defaults_to_zero_correction(self):
        """No entry for (3, 6) → no correction applied."""
        df = self._make_df([{"element_type": 3, "price_millions": 6.0}])
        preds = np.array([5.5])
        cal_map = {(2, 5): 0.3}  # different group
        result = self.m.apply_calibration(preds, df, cal_map)
        assert abs(result[0] - 5.5) < 1e-9

    def test_multiple_players_different_groups(self):
        """Three players in three different calibration groups."""
        df = self._make_df([
            {"element_type": 1, "price_millions": 4.0},   # GK
            {"element_type": 3, "price_millions": 8.0},   # MID
            {"element_type": 4, "price_millions": 10.0},  # FWD
        ])
        preds = np.array([4.0, 6.0, 8.0])
        cal_map = {(1, 4): 0.5, (3, 8): -0.5, (4, 10): 1.0}
        result = self.m.apply_calibration(preds, df, cal_map)
        assert abs(result[0] - 4.5) < 1e-9
        assert abs(result[1] - 5.5) < 1e-9
        assert abs(result[2] - 9.0) < 1e-9

    def test_empty_predictions_returns_empty(self):
        df = pd.DataFrame(columns=["element_type", "price_millions"])
        preds = np.array([])
        cal_map = {(3, 7): 0.5}
        result = self.m.apply_calibration(preds, df, cal_map)
        assert len(result) == 0

    def test_empty_calibration_map_no_change(self):
        df = self._make_df([{"element_type": 3, "price_millions": 7.0}])
        preds = np.array([5.0])
        result = self.m.apply_calibration(preds, df, {})
        assert abs(result[0] - 5.0) < 1e-9

    def test_price_band_uses_floor(self):
        """£7.8m player → price_band = 7, not 8."""
        df = self._make_df([{"element_type": 3, "price_millions": 7.8}])
        preds = np.array([5.0])
        cal_map = {(3, 7): 1.0}   # band 7, not 8
        result = self.m.apply_calibration(preds, df, cal_map)
        assert abs(result[0] - 6.0) < 1e-9

    def test_preserves_length(self):
        """Output length always matches input length."""
        df = self._make_df([{"element_type": i % 4 + 1, "price_millions": 5.0} for i in range(15)])
        preds = np.random.rand(15) * 10
        cal_map = {(2, 5): 0.3, (3, 5): -0.2}
        result = self.m.apply_calibration(preds, df, cal_map)
        assert len(result) == 15

    def test_original_predictions_not_mutated(self):
        """apply_calibration must not modify the input array in place."""
        df = self._make_df([{"element_type": 3, "price_millions": 7.0}])
        preds = np.array([4.0])
        original_copy = preds.copy()
        cal_map = {(3, 7): 1.5}
        self.m.apply_calibration(preds, df, cal_map)
        np.testing.assert_array_equal(preds, original_copy)
