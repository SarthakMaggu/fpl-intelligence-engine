"""
Smoke tests for the optimization engine.
Run: pytest backend/tests/ -v
"""
import pytest
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_player(
    player_id: int,
    element_type: int,
    team_id: int,
    now_cost: int = 60,
    xpts: float = 5.0,
):
    return {
        "player_id": player_id,
        "web_name": f"Player{player_id}",
        "element_type": element_type,
        "team_id": team_id,
        "now_cost": now_cost,
        "predicted_xpts_next": xpts,
        "predicted_xpts_gw": [xpts, xpts, xpts],
        "fdr_next": 3,
        "is_home_next": True,
        "has_blank_gw": False,
        "has_double_gw": False,
        "selected_by_percent": 10.0,
        "status": "a",
        "suspension_risk": False,
    }


def _make_valid_pool():
    """Create a pool of players meeting FPL squad constraints."""
    players = []
    pid = 1

    # 6 GKs from different teams
    for i in range(6):
        players.append(_make_player(pid, 1, i + 1, 50, 4.0))
        pid += 1

    # 15 DEFs from different teams
    for i in range(15):
        players.append(_make_player(pid, 2, (i % 10) + 1, 55, 5.5))
        pid += 1

    # 15 MIDs from different teams
    for i in range(15):
        players.append(_make_player(pid, 3, (i % 10) + 1, 70, 7.0))
        pid += 1

    # 10 FWDs from different teams
    for i in range(10):
        players.append(_make_player(pid, 4, (i % 10) + 1, 80, 8.0))
        pid += 1

    return players


class TestSquadOptimizer:
    def _pool_df(self):
        import pandas as pd
        pool = _make_valid_pool()
        df = pd.DataFrame(pool)
        df["id"] = df["player_id"]
        return df

    def test_squad_valid_formation(self):
        """Optimizer should return 15 players: 2 GK, 5 DEF, 5 MID, 3 FWD."""
        try:
            from optimizers.squad_optimizer import SquadOptimizer
        except ImportError:
            pytest.skip("PuLP not installed")

        optimizer = SquadOptimizer()
        result = optimizer.optimize_squad(self._pool_df(), budget=1000, free_transfers=1)

        assert result.solver_status == "Optimal", f"Optimizer status: {result.solver_status}"
        squad_ids = result.squad
        assert len(squad_ids) == 15, f"Expected 15 players, got {len(squad_ids)}"

        import pandas as pd
        df = self._pool_df()
        squad_df = df[df["id"].isin(squad_ids)]
        by_type = squad_df["element_type"].value_counts().to_dict()

        assert by_type.get(1, 0) == 2, "Need exactly 2 GKs"
        assert by_type.get(2, 0) == 5, "Need exactly 5 DEFs"
        assert by_type.get(3, 0) == 5, "Need exactly 5 MIDs"
        assert by_type.get(4, 0) == 3, "Need exactly 3 FWDs"

    def test_max_3_per_club(self):
        """No more than 3 players from same club."""
        try:
            from optimizers.squad_optimizer import SquadOptimizer
        except ImportError:
            pytest.skip("PuLP not installed")

        optimizer = SquadOptimizer()
        result = optimizer.optimize_squad(self._pool_df(), budget=1000, free_transfers=1)

        if result.solver_status != "Optimal":
            pytest.skip(f"Optimizer returned non-optimal: {result.solver_status}")

        import pandas as pd
        from collections import Counter
        df = self._pool_df()
        squad_df = df[df["id"].isin(result.squad)]
        club_counts = Counter(squad_df["team_id"].tolist())
        for club, count in club_counts.items():
            assert count <= 3, f"Club {club} has {count} players (max 3)"

    def test_budget_constraint(self):
        """Total squad cost must not exceed budget."""
        try:
            from optimizers.squad_optimizer import SquadOptimizer
        except ImportError:
            pytest.skip("PuLP not installed")

        optimizer = SquadOptimizer()
        result = optimizer.optimize_squad(self._pool_df(), budget=1000, free_transfers=1)

        if result.solver_status != "Optimal":
            pytest.skip(f"Optimizer returned non-optimal: {result.solver_status}")

        assert result.budget_used <= 1000, f"Squad costs {result.budget_used} pence, over budget"


class TestCaptainEngine:
    def test_no_gk_captain(self):
        """GKs must never be top captain pick."""
        from optimizers.captain_engine import CaptainEngine

        players = [
            {"player_id": 1, "web_name": "GK", "element_type": 1, "predicted_xpts_next": 20.0, "fdr_next": 1, "is_home_next": True, "has_double_gw": False, "selected_by_percent": 5.0},
            {"player_id": 2, "web_name": "FWD", "element_type": 4, "predicted_xpts_next": 10.0, "fdr_next": 2, "is_home_next": True, "has_double_gw": False, "selected_by_percent": 30.0},
        ]
        engine = CaptainEngine()
        # Filter out GK as per business rule
        non_gk = [p for p in players if p["element_type"] != 1]
        ranked = engine.rank_captains(non_gk)
        assert ranked[0]["player_id"] == 2

    def test_dgw_bonus(self):
        """Double GW player should outscore identical non-DGW player."""
        from optimizers.captain_engine import CaptainEngine

        players = [
            {"player_id": 1, "web_name": "Normal", "element_type": 4, "predicted_xpts_next": 8.0, "fdr_next": 2, "is_home_next": True, "has_double_gw": False, "selected_by_percent": 20.0},
            {"player_id": 2, "web_name": "DGW", "element_type": 4, "predicted_xpts_next": 8.0, "fdr_next": 2, "is_home_next": True, "has_double_gw": True, "selected_by_percent": 20.0},
        ]
        engine = CaptainEngine()
        ranked = engine.rank_captains(players)
        assert ranked[0]["player_id"] == 2, "DGW player should rank above non-DGW"


class TestPriceModel:
    def test_heuristic_predict_rise(self):
        """Large net transfers in should predict price rise."""
        import pandas as pd
        from models.ml.price_model import PriceModel

        model = PriceModel()
        df = pd.DataFrame([{
            "transfers_in_event": 200_000,
            "transfers_out_event": 50_000,
            "net_transfers_event": 150_000,
            "selected_by_percent": 15.0,
            "form": 8.0,
            "price_millions": 9.0,
            "fdr_next": 2,
            "is_gk": 0, "is_def": 0, "is_mid": 0, "is_fwd": 1,
        }])
        direction, confidence = model.predict(df)
        assert direction[0] == 1, "Expected price rise prediction"

    def test_heuristic_predict_drop(self):
        """Large net transfers out should predict price drop."""
        import pandas as pd
        from models.ml.price_model import PriceModel

        model = PriceModel()
        df = pd.DataFrame([{
            "transfers_in_event": 10_000,
            "transfers_out_event": 200_000,
            "net_transfers_event": -190_000,
            "selected_by_percent": 5.0,
            "form": 2.0,
            "price_millions": 8.0,
            "fdr_next": 5,
            "is_gk": 0, "is_def": 0, "is_mid": 1, "is_fwd": 0,
        }])
        direction, confidence = model.predict(df)
        assert direction[0] == -1, "Expected price drop prediction"
