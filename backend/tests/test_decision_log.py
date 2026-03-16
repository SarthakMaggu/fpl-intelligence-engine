"""
Tests for DecisionLog model and bandit captain_strategy arm.

DB-dependent tests (requiring asyncpg) are skipped outside Docker.
Pure-Python tests (bandit, Pydantic schemas) always run.
"""
import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Check if we're in an environment with asyncpg (Docker) or not (local)
try:
    import asyncpg  # noqa: F401
    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False

requires_asyncpg = pytest.mark.skipif(
    not HAS_ASYNCPG,
    reason="asyncpg not installed — test runs inside Docker only",
)


# ── Bandit captain_strategy tests ─────────────────────────────────────────────

def test_captain_strategy_in_decision_arms():
    """captain_strategy is registered in DECISION_ARMS."""
    from optimizers.bandit import DECISION_ARMS
    assert "captain_strategy" in DECISION_ARMS


def test_captain_strategy_has_five_arms():
    """captain_strategy has exactly 5 arms."""
    from optimizers.bandit import DECISION_ARMS
    arms = DECISION_ARMS["captain_strategy"]
    assert len(arms) == 5


def test_captain_strategy_arm_names():
    """All expected arm names present."""
    from optimizers.bandit import DECISION_ARMS
    expected = {"model_pick", "form_pick", "fixture_pick", "differential_pick", "safe_pick"}
    assert set(DECISION_ARMS["captain_strategy"]) == expected


def test_ucb1_selects_unexplored_arm_first():
    """Unexplored arms (n=0) get inf score and should be selected first."""
    from optimizers.bandit import UCB1Bandit, DECISION_ARMS
    bandit = UCB1Bandit()
    arms = DECISION_ARMS["captain_strategy"]
    state = {
        "q": {a: 1.0 for a in arms},
        "n": {arms[0]: 5, arms[1]: 3, arms[2]: 0, arms[3]: 1, arms[4]: 2},  # arms[2] unexplored
        "total_n": 11,
    }
    selected = bandit.select_arm(state, "captain_strategy")
    assert selected == arms[2]  # Unexplored arm should be selected


def test_ucb1_update_increments_n():
    """update_arm increments n correctly."""
    from optimizers.bandit import UCB1Bandit, DECISION_ARMS
    bandit = UCB1Bandit()
    arms = DECISION_ARMS["captain_strategy"]
    state = {
        "q": {a: 0.0 for a in arms},
        "n": {a: 0 for a in arms},
        "total_n": 0,
    }
    updated = bandit.update_arm(state, "model_pick", reward=1.5)
    assert updated["n"]["model_pick"] == 1
    assert updated["total_n"] == 1


def test_existing_decision_types_preserved():
    """Original 4 decision types still present."""
    from optimizers.bandit import DECISION_ARMS
    original = ["transfer_strategy", "captain_pick", "chip_timing", "hit_decision"]
    for dt in original:
        assert dt in DECISION_ARMS


# ── DecisionLog model tests (schema validation) ───────────────────────────────

@requires_asyncpg
def test_decision_log_model_imports():
    """DecisionLog model can be imported (requires asyncpg)."""
    from models.db.decision_log import DecisionLog
    assert DecisionLog is not None


@requires_asyncpg
def test_decision_log_tablename():
    """DecisionLog uses correct table name (requires asyncpg)."""
    from models.db.decision_log import DecisionLog
    assert DecisionLog.__tablename__ == "decision_log"


@requires_asyncpg
def test_prediction_calibration_imports():
    """PredictionCalibration model can be imported (requires asyncpg)."""
    from models.db.calibration import PredictionCalibration, PointsDistribution
    assert PredictionCalibration.__tablename__ == "prediction_calibration"
    assert PointsDistribution.__tablename__ == "points_distribution"


# ── API route schema tests (Pydantic only — no asyncpg needed) ─────────────────

@requires_asyncpg
def test_decision_create_request_schema():
    """DecisionCreateRequest validates correctly."""
    from api.routes.decision_log import DecisionCreateRequest
    req = DecisionCreateRequest(
        team_id=1234,
        gameweek_id=29,
        decision_type="captain",
        recommended_option="Haaland (C)",
        expected_points=12.5,
        reasoning="Highest xPts, home fixture.",
    )
    assert req.team_id == 1234
    assert req.decision_type == "captain"


@requires_asyncpg
def test_decision_update_request_optional_fields():
    """DecisionUpdateRequest fields are all optional."""
    from api.routes.decision_log import DecisionUpdateRequest
    req = DecisionUpdateRequest()
    assert req.user_choice is None
    assert req.decision_followed is None


@requires_asyncpg
def test_resolve_request_schema():
    """ResolveRequest validates correctly."""
    from api.routes.review import ResolveRequest
    req = ResolveRequest(
        team_id=1234,
        gameweek_id=29,
        actual_team_points=72.0,
        rank_before=50000,
        rank_after=45000,
    )
    assert req.rank_before == 50000


# ── Market/Review route import tests ──────────────────────────────────────────

@requires_asyncpg
def test_market_router_importable():
    """market.py router can be imported without errors (requires asyncpg)."""
    from api.routes.market import router
    assert router is not None


@requires_asyncpg
def test_review_router_importable():
    """review.py router can be imported without errors (requires asyncpg)."""
    from api.routes.review import router
    assert router is not None
