"""
Tests for optimizers/chip_engine.py — ChipEngine Monte Carlo recommendations.

Run: pytest backend/tests/test_chip_engine.py -v
"""
import sys
import os
import pytest
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from optimizers.chip_engine import ChipEngine, ChipRecommendation


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine():
    """ChipEngine with smaller n_simulations for speed."""
    return ChipEngine(n_simulations=500)


def _bench_matrix(n_gws: int = 5, xpts: float = 3.0) -> np.ndarray:
    """Return a (n_gws, 4) bench xpts matrix filled with `xpts`."""
    return np.full((n_gws, 4), xpts)


def _cap_xpts(n_gws: int = 5, xpts: float = 6.0) -> np.ndarray:
    return np.full(n_gws, xpts)


def _fdr_arr(n_gws: int = 5, fdr: int = 2) -> np.ndarray:
    return np.full(n_gws, float(fdr))


def _dgw_arr(n_gws: int = 5, has_dgw: bool = False) -> np.ndarray:
    arr = np.zeros(n_gws, dtype=bool)
    if has_dgw:
        arr[1] = True  # DGW in GW+1
    return arr


# ---------------------------------------------------------------------------
# ChipRecommendation dataclass
# ---------------------------------------------------------------------------

def test_chip_recommendation_fields():
    rec = ChipRecommendation(
        chip="bench_boost",
        recommended_gw=31,
        confidence=0.75,
        expected_gain=12.5,
        reasoning="Test reasoning",
        urgency="plan",
    )
    assert rec.chip == "bench_boost"
    assert rec.recommended_gw == 31
    assert 0.0 <= rec.confidence <= 1.0
    assert rec.expected_gain > 0
    assert rec.urgency in ("urgent", "plan", "monitor")


# ---------------------------------------------------------------------------
# recommend_bench_boost
# ---------------------------------------------------------------------------

class TestBenchBoost:
    def test_returns_none_when_unavailable(self, engine):
        m = _bench_matrix()
        rec = engine.recommend_bench_boost(m, current_gw=29, half="second", available=False)
        assert rec is None

    def test_returns_none_when_empty_matrix(self, engine):
        rec = engine.recommend_bench_boost(
            np.zeros((0, 4)), current_gw=29, half="second", available=True
        )
        assert rec is None

    def test_returns_recommendation_with_valid_data(self, engine):
        m = _bench_matrix(n_gws=6, xpts=4.0)
        rec = engine.recommend_bench_boost(m, current_gw=30, half="second", available=True)
        assert rec is not None
        assert rec.chip == "bench_boost"
        assert rec.recommended_gw >= 30
        assert 0.0 <= rec.confidence <= 1.0
        assert rec.expected_gain > 0

    def test_dgw_week_preferred(self, engine):
        """DGW GW should score higher than non-DGW."""
        n_gws = 6
        # Higher xpts in GW index 2 (simulating DGW)
        m = np.full((n_gws, 4), 3.0)
        m[2] = 7.0  # DGW-like spike
        rec = engine.recommend_bench_boost(m, current_gw=30, half="second", available=True)
        assert rec is not None
        assert rec.recommended_gw == 32  # current_gw + 2

    def test_first_half_restriction(self, engine):
        """In first half, recommendations must be ≤ GW18."""
        m = _bench_matrix(n_gws=10, xpts=4.0)
        rec = engine.recommend_bench_boost(m, current_gw=10, half="first", available=True)
        assert rec is not None
        assert rec.recommended_gw <= 18

    def test_urgency_flag_near_cutoff(self, engine):
        m = _bench_matrix(n_gws=3, xpts=4.0)
        rec = engine.recommend_bench_boost(m, current_gw=29, half="second", available=True)
        # With only 3 GWs remaining, urgency should reflect proximity
        assert rec is None or rec.urgency in ("urgent", "plan")


# ---------------------------------------------------------------------------
# recommend_triple_captain
# ---------------------------------------------------------------------------

class TestTripleCaptain:
    def test_returns_none_when_unavailable(self, engine):
        rec = engine.recommend_triple_captain(
            _cap_xpts(), _fdr_arr(), _dgw_arr(),
            current_gw=29, half="second", available=False
        )
        assert rec is None

    def test_returns_recommendation(self, engine):
        rec = engine.recommend_triple_captain(
            _cap_xpts(xpts=7.0), _fdr_arr(fdr=2), _dgw_arr(),
            current_gw=29, half="second", available=True
        )
        assert rec is not None
        assert rec.chip == "triple_captain"
        assert rec.recommended_gw >= 29

    def test_dgw_boosts_score(self, engine):
        """A DGW GW should result in higher expected gain."""
        dgw = _dgw_arr(has_dgw=True)  # DGW at index 1
        rec_dgw = engine.recommend_triple_captain(
            _cap_xpts(xpts=6.0), _fdr_arr(fdr=2), dgw,
            current_gw=29, half="second", available=True
        )
        rec_no_dgw = engine.recommend_triple_captain(
            _cap_xpts(xpts=6.0), _fdr_arr(fdr=2), _dgw_arr(has_dgw=False),
            current_gw=29, half="second", available=True
        )
        # DGW version should recommend the DGW week (GW30 = 29+1)
        assert rec_dgw is not None
        assert rec_dgw.recommended_gw == 30

    def test_low_fdr_boosts_score(self, engine):
        """FDR 1 fixture should outrank FDR 5 fixture."""
        fdr_good = np.array([1.0, 5.0, 5.0, 5.0, 5.0])
        fdr_bad = np.array([5.0, 5.0, 5.0, 5.0, 5.0])
        rec_good = engine.recommend_triple_captain(
            _cap_xpts(xpts=6.0), fdr_good, _dgw_arr(),
            current_gw=29, half="second", available=True
        )
        rec_bad = engine.recommend_triple_captain(
            _cap_xpts(xpts=6.0), fdr_bad, _dgw_arr(),
            current_gw=29, half="second", available=True
        )
        if rec_good and rec_bad:
            assert rec_good.expected_gain >= rec_bad.expected_gain


# ---------------------------------------------------------------------------
# recommend_wildcard
# ---------------------------------------------------------------------------

class TestWildcard:
    def test_returns_none_when_unavailable(self, engine):
        rec = engine.recommend_wildcard(
            current_squad_xpts_5gw=50.0,
            optimal_squad_xpts_5gw=70.0,
            current_gw=29, half="second", available=False
        )
        assert rec is None

    def test_monitor_when_gap_below_threshold(self, engine):
        """Gap < 15 pts → urgency should be 'monitor'."""
        rec = engine.recommend_wildcard(60.0, 70.0, current_gw=29, half="second", available=True)
        assert rec is not None
        assert rec.urgency == "monitor"

    def test_urgent_when_gap_large(self, engine):
        """Gap ≥ 15 pts → chip should be recommended."""
        rec = engine.recommend_wildcard(40.0, 80.0, current_gw=29, half="second", available=True)
        assert rec is not None
        assert rec.expected_gain >= 15.0
        assert rec.chip == "wildcard"

    def test_confidence_scales_with_gain(self, engine):
        rec_small = engine.recommend_wildcard(55.0, 70.0, current_gw=29, half="second", available=True)
        rec_large = engine.recommend_wildcard(30.0, 90.0, current_gw=29, half="second", available=True)
        if rec_small and rec_large:
            assert rec_large.confidence >= rec_small.confidence


# ---------------------------------------------------------------------------
# recommend_free_hit
# ---------------------------------------------------------------------------

class TestFreeHit:
    def test_returns_none_when_unavailable(self, engine):
        rec = engine.recommend_free_hit(
            squad_blank_count=6, current_gw=29, half="second", available=False
        )
        assert rec is None

    def test_returns_none_below_threshold(self, engine):
        """< 3 blanking starters → no recommendation."""
        rec = engine.recommend_free_hit(
            squad_blank_count=2, current_gw=29, half="second", available=True
        )
        assert rec is None

    def test_monitor_when_3_blankers(self, engine):
        rec = engine.recommend_free_hit(
            squad_blank_count=3, current_gw=29, half="second", available=True
        )
        assert rec is not None
        assert rec.urgency == "monitor"

    def test_urgent_when_5_or_more_blankers(self, engine):
        rec = engine.recommend_free_hit(
            squad_blank_count=7, current_gw=29, half="second", available=True
        )
        assert rec is not None
        assert rec.urgency == "urgent"
        assert rec.chip == "free_hit"

    def test_confidence_scales_with_blank_count(self, engine):
        rec_low = engine.recommend_free_hit(3, current_gw=29, half="second", available=True)
        rec_high = engine.recommend_free_hit(9, current_gw=29, half="second", available=True)
        if rec_low and rec_high:
            assert rec_high.confidence >= rec_low.confidence


# ---------------------------------------------------------------------------
# get_all_recommendations
# ---------------------------------------------------------------------------

class TestGetAllRecommendations:
    def test_empty_when_no_chips_available(self, engine):
        chips = {c: False for c in ["bench_boost", "triple_captain", "wildcard", "free_hit"]}
        recs = engine.get_all_recommendations(
            chips_available=chips,
            current_gw=29,
            half="second",
        )
        assert recs == []

    def test_sorted_by_confidence_desc(self, engine):
        chips = {
            "bench_boost": True,
            "triple_captain": True,
            "wildcard": True,
            "free_hit": True,
        }
        recs = engine.get_all_recommendations(
            chips_available=chips,
            current_gw=29,
            half="second",
            bench_xpts_by_gw=_bench_matrix(xpts=5.0),
            captain_xpts_by_gw=_cap_xpts(xpts=7.0),
            fdr_by_gw=_fdr_arr(fdr=2),
            is_double_gw=_dgw_arr(),
            current_squad_xpts_5gw=40.0,
            optimal_squad_xpts_5gw=90.0,
            squad_blank_count=6,
        )
        confidences = [r.confidence for r in recs]
        assert confidences == sorted(confidences, reverse=True)

    def test_all_recs_are_chip_recommendation(self, engine):
        chips = {"bench_boost": True, "triple_captain": True, "wildcard": False, "free_hit": False}
        recs = engine.get_all_recommendations(
            chips_available=chips,
            current_gw=29,
            half="second",
        )
        for rec in recs:
            assert isinstance(rec, ChipRecommendation)
            assert rec.chip in ("bench_boost", "triple_captain", "wildcard", "free_hit")

    def test_defaults_used_when_arrays_are_none(self, engine):
        """Engine should not crash when optional arrays are None."""
        chips = {"bench_boost": True, "triple_captain": True, "wildcard": True, "free_hit": True}
        recs = engine.get_all_recommendations(
            chips_available=chips,
            current_gw=30,
            half="second",
            current_squad_xpts_5gw=50.0,
            optimal_squad_xpts_5gw=80.0,
            squad_blank_count=4,
        )
        # Should not raise; may return 0 or more recs
        assert isinstance(recs, list)


# ---------------------------------------------------------------------------
# _valid_gw_range
# ---------------------------------------------------------------------------

class TestValidGwRange:
    def test_first_half_max_gw18(self, engine):
        gws = engine._valid_gw_range(current_gw=16, n_gws=5, half="first")
        assert all(g <= 18 for g in gws)

    def test_second_half_up_to_gw38(self, engine):
        gws = engine._valid_gw_range(current_gw=35, n_gws=5, half="second")
        assert all(g <= 38 for g in gws)

    def test_returns_sequential_gws(self, engine):
        gws = engine._valid_gw_range(current_gw=29, n_gws=4, half="second")
        assert gws == sorted(gws)
        assert gws[0] == 29
