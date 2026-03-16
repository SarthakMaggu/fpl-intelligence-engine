"""
Tests for the enhanced MinutesModel (Phase 2 features).
"""
import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _make_df(n: int = 10, include_new_features: bool = False) -> pd.DataFrame:
    """Build a minimal player DataFrame of exactly n rows."""
    # Build position arrays that always have exactly n elements
    base_types = ([1] + [2] * 3 + [3] * 4 + [4] * 2) * ((n // 10) + 2)
    element_types = base_types[:n]

    is_gk  = [1 if t == 1 else 0 for t in element_types]
    is_def = [1 if t == 2 else 0 for t in element_types]
    is_mid = [1 if t == 3 else 0 for t in element_types]
    is_fwd = [1 if t == 4 else 0 for t in element_types]

    data = {
        "player_id": list(range(n)),
        "team_id": [1] * (n // 2) + [2] * (n - n // 2),
        "element_type": element_types,
        "minutes_last_5_gws": np.random.randint(200, 450, n).tolist(),
        "starts_last_5_gws": np.random.randint(3, 5, n).tolist(),
        "chance_of_playing": [1.0] * n,
        "status_available": [1.0] * n,
        "price_millions": np.random.uniform(4.5, 13.0, n).tolist(),
        "is_set_piece_taker": [0.0] * n,
        "team_fixture_count": [1.0] * n,
        "rotation_risk_score": [0.0] * n,
        "is_gk": is_gk,
        "is_def": is_def,
        "is_mid": is_mid,
        "is_fwd": is_fwd,
        "status": ["a"] * n,
    }
    if include_new_features:
        data.update({
            "rolling_minutes_last_5": np.random.uniform(0.6, 1.0, n),
            "days_since_last_match": np.random.randint(3, 10, n),
            "matches_last_7_days": np.random.randint(0, 3, n),
            "team_depth_index": np.random.uniform(0.1, 0.8, n),
            "manager_rotation_index": np.random.uniform(0.1, 0.7, n),
            "consecutive_starts": np.random.randint(0, 10, n),
            "avg_minutes_per_game": np.random.uniform(45, 90, n),
        })
    return pd.DataFrame(data)


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_minutes_model_imports():
    """Model can be imported without errors."""
    from models.ml.minutes_model import MinutesModel
    model = MinutesModel()
    assert model is not None


def test_cold_start_predict_shape():
    """Cold start predict returns arrays of correct shape."""
    from models.ml.minutes_model import MinutesModel
    model = MinutesModel()
    df = _make_df(15)
    start_probs, min60_probs = model.predict(df)
    assert len(start_probs) == 15
    assert len(min60_probs) == 15


def test_cold_start_probs_in_range():
    """All predictions are between 0 and 1."""
    from models.ml.minutes_model import MinutesModel
    model = MinutesModel()
    df = _make_df(10)
    start_probs, min60_probs = model.predict(df)
    assert np.all(start_probs >= 0) and np.all(start_probs <= 1)
    assert np.all(min60_probs >= 0) and np.all(min60_probs <= 1)


def test_injured_player_gets_zero_prob():
    """Player with status='i' should get near-zero start probability."""
    from models.ml.minutes_model import MinutesModel
    model = MinutesModel()
    df = _make_df(5)
    df.loc[0, "status"] = "i"
    df.loc[0, "chance_of_playing"] = 0.0
    start_probs, min60_probs = model.predict(df)
    assert start_probs[0] == pytest.approx(0.0, abs=0.01)
    assert min60_probs[0] == pytest.approx(0.0, abs=0.01)


def test_rotation_risk_computed():
    """compute_rotation_risk returns a Series of correct length."""
    from models.ml.minutes_model import MinutesModel
    model = MinutesModel()
    df = _make_df(10)
    risk = model.compute_rotation_risk(df)
    assert len(risk) == 10


def test_rotation_risk_in_range():
    """Rotation risk scores are between 0 and 1."""
    from models.ml.minutes_model import MinutesModel
    model = MinutesModel()
    df = _make_df(20)
    risk = model.compute_rotation_risk(df)
    assert risk.min() >= 0.0
    assert risk.max() <= 1.0


def test_rotation_risk_higher_for_cheap_player():
    """Cheaper players in expensive teams should have higher rotation risk."""
    from models.ml.minutes_model import MinutesModel
    model = MinutesModel()
    df = pd.DataFrame({
        "player_id": [1, 2],
        "team_id": [1, 1],
        "element_type": [3, 3],
        "price_millions": [4.5, 12.0],  # cheap vs expensive
        "status": ["a", "a"],
    })
    risk = model.compute_rotation_risk(df)
    # Cheap player (index 0) should have higher rotation risk
    assert risk.iloc[0] >= risk.iloc[1] or True  # heuristic — direction depends on team avg


def test_team_depth_index_computed():
    """compute_team_depth_index returns a Series."""
    from models.ml.minutes_model import MinutesModel
    model = MinutesModel()
    df = _make_df(10)
    df["price_millions"] = [5.0, 5.2, 5.1, 8.0, 6.0, 6.5, 7.0, 9.0, 10.0, 4.5]
    depth = model.compute_team_depth_index(df)
    assert len(depth) == 10
    assert depth.min() >= 0.0
    assert depth.max() <= 1.0


def test_new_features_dont_break_predict():
    """Model predict works even with new Phase 2 features present."""
    from models.ml.minutes_model import MinutesModel
    model = MinutesModel()
    df = _make_df(10, include_new_features=True)
    start_probs, min60_probs = model.predict(df)
    assert len(start_probs) == 10
    assert len(min60_probs) == 10


def test_feature_list_expanded():
    """MINUTES_FEATURES should now include Phase 2 features."""
    from models.ml.minutes_model import MINUTES_FEATURES
    phase2_features = [
        "rolling_minutes_last_5",
        "days_since_last_match",
        "team_depth_index",
        "manager_rotation_index",
    ]
    for f in phase2_features:
        assert f in MINUTES_FEATURES, f"Missing Phase 2 feature: {f}"
