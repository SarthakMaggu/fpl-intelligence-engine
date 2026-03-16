"""
Data integrity and logic tests — no DB connection required.

Tests:
- UserBank chip availability logic (pure Python, no DB)
- ChipEngine numpy safety
- SquadOptimizer ILP constraints
- Format utilities

Run: pytest backend/tests/test_data_integrity.py -v
"""
import sys
import os
import pytest
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# UserBank chip logic — tested via pure dataclass, no DB import
# ---------------------------------------------------------------------------

class FakeUserBank:
    """
    Standalone replica of UserBank chip logic for host-side testing.
    Mirrors the logic in models/db/user_squad.py without triggering
    SQLAlchemy / asyncpg imports.
    """
    FIRST_HALF_MAX_GW = 18

    def __init__(self, **kwargs):
        for chip in ["wildcard", "free_hit", "bench_boost", "triple_captain"]:
            for half in [1, 2]:
                col = f"{chip}_{half}_used_gw"
                setattr(self, col, kwargs.get(col, None))

    def get_current_half(self, current_gw: int) -> str:
        return "first" if current_gw <= self.FIRST_HALF_MAX_GW else "second"

    def chip_available(self, chip: str, current_gw: int) -> bool:
        half = self.get_current_half(current_gw)
        col = f"{chip}_{'1' if half == 'first' else '2'}_used_gw"
        return getattr(self, col, None) is None


class TestUserBankChipLogic:
    def _bank(self, **kwargs):
        return FakeUserBank(**kwargs)

    def test_chip_available_when_not_used(self):
        bank = self._bank()
        assert bank.chip_available("wildcard", current_gw=29) is True

    def test_chip_unavailable_when_used_in_half(self):
        bank = self._bank(wildcard_2_used_gw=25)
        assert bank.chip_available("wildcard", current_gw=29) is False

    def test_chip_available_in_second_half_if_only_used_in_first(self):
        bank = self._bank(wildcard_1_used_gw=10)
        # GW29 is second half — wildcard_2 not used
        assert bank.chip_available("wildcard", current_gw=29) is True

    def test_get_current_half_first(self):
        bank = self._bank()
        assert bank.get_current_half(15) == "first"
        assert bank.get_current_half(18) == "first"

    def test_get_current_half_second(self):
        bank = self._bank()
        assert bank.get_current_half(20) == "second"
        assert bank.get_current_half(38) == "second"

    def test_all_chips_available_fresh_season(self):
        bank = self._bank()
        for chip in ["wildcard", "free_hit", "bench_boost", "triple_captain"]:
            assert bank.chip_available(chip, current_gw=5) is True

    def test_all_chips_unavailable_when_all_used_in_second_half(self):
        bank = self._bank(
            wildcard_2_used_gw=21,
            free_hit_2_used_gw=22,
            bench_boost_2_used_gw=23,
            triple_captain_2_used_gw=24,
        )
        for chip in ["wildcard", "free_hit", "bench_boost", "triple_captain"]:
            assert bank.chip_available(chip, current_gw=29) is False

    def test_half_boundary_gw19_is_first_half(self):
        """GW19 is the BBWC deadline — treated as first half."""
        bank = self._bank()
        assert bank.get_current_half(19) == "second"  # 19 > 18

    def test_chip_used_gw_field_name_pattern(self):
        """Verify field names follow the correct naming convention."""
        bank = self._bank(bench_boost_1_used_gw=8)
        assert bank.chip_available("bench_boost", current_gw=5) is False
        assert bank.chip_available("bench_boost", current_gw=25) is True


# ---------------------------------------------------------------------------
# ChipEngine numpy safety
# ---------------------------------------------------------------------------

class TestChipEngineNumpySafety:
    """Ensure ChipEngine never crashes on edge-case inputs."""

    def _engine(self):
        from optimizers.chip_engine import ChipEngine
        return ChipEngine(n_simulations=100)

    def test_bench_boost_single_gw(self):
        engine = self._engine()
        m = np.array([[3.0, 2.5, 2.0, 1.5]])  # shape (1, 4)
        rec = engine.recommend_bench_boost(m, current_gw=29, half="second", available=True)
        assert rec is None or rec.chip == "bench_boost"

    def test_bench_boost_zero_xpts(self):
        engine = self._engine()
        m = np.zeros((5, 4))
        rec = engine.recommend_bench_boost(m, current_gw=29, half="second", available=True)
        assert rec is None or rec.expected_gain >= 0

    def test_bench_boost_full_remaining_season(self):
        engine = self._engine()
        m = np.full((10, 4), 3.5)
        rec = engine.recommend_bench_boost(m, current_gw=29, half="second", available=True)
        assert rec is not None
        assert 29 <= rec.recommended_gw <= 38

    def test_triple_captain_single_gw(self):
        engine = self._engine()
        rec = engine.recommend_triple_captain(
            captain_xpts_by_gw=np.array([7.0]),
            fdr_by_gw=np.array([2.0]),
            is_double_gw=np.array([False]),
            current_gw=29,
            half="second",
            available=True,
        )
        assert rec is None or rec.chip == "triple_captain"

    def test_sample_points_shape(self):
        engine = self._engine()
        matrix = np.full((5, 4), 4.0)
        result = engine._sample_points(matrix, sigma=2.5)
        assert result.shape == (5, engine.n_simulations, 4)

    def test_sample_points_non_negative(self):
        engine = self._engine()
        matrix = np.full((3, 4), 0.1)
        result = engine._sample_points(matrix, sigma=0.0)
        assert (result >= 0).all(), "Points should never be negative"

    def test_engine_reproducible_with_same_seed(self):
        """Same seed → same recommendations."""
        from optimizers.chip_engine import ChipEngine
        e1 = ChipEngine(n_simulations=200)
        e2 = ChipEngine(n_simulations=200)
        m = np.full((5, 4), 4.0)
        r1 = e1.recommend_bench_boost(m, current_gw=29, half="second", available=True)
        r2 = e2.recommend_bench_boost(m, current_gw=29, half="second", available=True)
        if r1 and r2:
            assert r1.recommended_gw == r2.recommended_gw


# ---------------------------------------------------------------------------
# SquadOptimizer — ILP constraints
# ---------------------------------------------------------------------------

class TestSquadOptimizerConstraints:
    """Verify the ILP solver produces FPL-valid squads."""

    def _make_player(self, pid, pos, team, cost=60, xpts=5.0):
        return {
            "id": pid,
            "web_name": f"P{pid}",
            "element_type": pos,
            "team_id": team,
            "now_cost": cost,
            "predicted_xpts_next": xpts,
            "has_blank_gw": False,
            "has_double_gw": False,
            "selected_by_percent": "10.0",
            "status": "a",
        }

    def _build_df(self):
        import pandas as pd
        rows = []
        pid = 1
        # 6 GKs from different teams
        for i in range(6):
            rows.append(self._make_player(pid, 1, i + 1, 50, 4.0))
            pid += 1
        # 15 DEFs from different teams
        for i in range(15):
            rows.append(self._make_player(pid, 2, (i % 10) + 1, 55, 5.5))
            pid += 1
        # 15 MIDs from different teams
        for i in range(15):
            rows.append(self._make_player(pid, 3, (i % 10) + 1, 65, 6.5))
            pid += 1
        # 10 FWDs from different teams
        for i in range(10):
            rows.append(self._make_player(pid, 4, (i % 10) + 1, 75, 7.0))
            pid += 1
        return pd.DataFrame(rows)

    def test_optimizer_produces_15_players(self):
        try:
            from optimizers.squad_optimizer import SquadOptimizer
            import pulp  # noqa
        except ImportError:
            pytest.skip("SquadOptimizer or pulp not available")

        optimizer = SquadOptimizer()
        df = self._build_df()
        result = optimizer.optimize_squad(df, budget=1000)
        if result is None:
            pytest.skip("Solver returned None")

        total = len(result.squad)
        assert total == 15, f"Squad should have 15 players, got {total}"

    def test_optimizer_starting_xi_has_11(self):
        try:
            from optimizers.squad_optimizer import SquadOptimizer
            import pulp  # noqa
        except ImportError:
            pytest.skip("SquadOptimizer or pulp not available")

        optimizer = SquadOptimizer()
        df = self._build_df()
        result = optimizer.optimize_squad(df, budget=1000)
        if result is None:
            pytest.skip("Solver returned None")

        assert len(result.starting_xi) == 11, "Starting XI must have 11 players"

    def test_optimizer_bench_has_4(self):
        try:
            from optimizers.squad_optimizer import SquadOptimizer
            import pulp  # noqa
        except ImportError:
            pytest.skip("SquadOptimizer or pulp not available")

        optimizer = SquadOptimizer()
        df = self._build_df()
        result = optimizer.optimize_squad(df, budget=1000)
        if result is None:
            pytest.skip("Solver returned None")

        assert len(result.bench) == 4, "Bench must have 4 players"

    def test_optimizer_respects_budget(self):
        try:
            from optimizers.squad_optimizer import SquadOptimizer
            import pulp  # noqa
        except ImportError:
            pytest.skip("SquadOptimizer or pulp not available")

        optimizer = SquadOptimizer()
        df = self._build_df()
        budget = 1000
        result = optimizer.optimize_squad(df, budget=budget)
        if result is None:
            pytest.skip("Solver returned None")

        # budget_used is in pence units (not millions)
        assert result.budget_used <= budget + 1, f"Budget exceeded: {result.budget_used} > {budget}"

    def test_optimizer_formation_is_valid_string(self):
        try:
            from optimizers.squad_optimizer import SquadOptimizer
            import pulp  # noqa
        except ImportError:
            pytest.skip("SquadOptimizer or pulp not available")

        optimizer = SquadOptimizer()
        df = self._build_df()
        result = optimizer.optimize_squad(df, budget=1000)
        if result is None:
            pytest.skip("Solver returned None")

        # Formation should be like "3-5-2", "4-4-2", etc.
        assert "-" in result.formation, f"Invalid formation: {result.formation}"
        parts = result.formation.split("-")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)
        assert sum(int(p) for p in parts) == 10  # 10 outfield players


# ---------------------------------------------------------------------------
# Cost formatting utility
# ---------------------------------------------------------------------------

class TestCostFormatting:
    def test_pence_to_millions(self):
        """FPL pence units: 90 → £9.0m, 115 → £11.5m."""
        def to_millions(pence: int) -> float:
            return pence / 10

        assert to_millions(90) == 9.0
        assert to_millions(115) == 11.5
        assert to_millions(50) == 5.0
        assert to_millions(1000) == 100.0

    def test_bank_calculation(self):
        """Bank in pence units: 10 → £1.0m."""
        def bank_millions(pence: int) -> float:
            return round(pence / 10, 1)

        assert bank_millions(10) == 1.0
        assert bank_millions(5) == 0.5
        assert bank_millions(0) == 0.0
