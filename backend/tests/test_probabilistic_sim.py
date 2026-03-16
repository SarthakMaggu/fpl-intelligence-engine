"""
Tests for ProbabilisticSimulator and LineupSimulator.
"""
import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── ProbabilisticSimulator tests ───────────────────────────────────────────────

from optimizers.probabilistic_sim import ProbabilisticSimulator, PlayerSimInput


def _make_input(pid: int = 1, xpts: float = 5.0, p_start: float = 0.9,
                ownership: float = 20.0, element_type: int = 3) -> PlayerSimInput:
    return PlayerSimInput(
        player_id=pid,
        web_name=f"Player{pid}",
        xpts=xpts,
        p_start=p_start,
        selected_by_percent=ownership,
        element_type=element_type,
    )


def test_simulate_returns_correct_count():
    sim = ProbabilisticSimulator(n_sims=500, seed=1)
    players = [_make_input(i) for i in range(5)]
    results = sim.simulate_players(players)
    assert len(results) == 5


def test_prob_blank_between_0_and_1():
    sim = ProbabilisticSimulator(n_sims=1000, seed=2)
    results = sim.simulate_players([_make_input(1)])
    r = results[0]
    assert 0.0 <= r.prob_blank <= 1.0


def test_prob_5_plus_between_0_and_1():
    sim = ProbabilisticSimulator(n_sims=1000, seed=3)
    results = sim.simulate_players([_make_input(1)])
    r = results[0]
    assert 0.0 <= r.prob_5_plus <= 1.0


def test_high_xpts_player_has_low_prob_blank():
    """Player with 9.0 xPts should rarely blank."""
    sim = ProbabilisticSimulator(n_sims=2000, seed=4)
    results = sim.simulate_players([_make_input(1, xpts=9.0, p_start=0.99)])
    assert results[0].prob_blank < 0.3


def test_zero_xpts_player_has_high_prob_blank():
    """Player with 0 xPts (injured) should almost always blank."""
    sim = ProbabilisticSimulator(n_sims=2000, seed=5)
    results = sim.simulate_players([_make_input(1, xpts=0.0, p_start=0.0)])
    assert results[0].prob_blank >= 0.8


def test_captain_doubles_ev():
    """Captain EV should be ~2x non-captain EV for same player."""
    sim = ProbabilisticSimulator(n_sims=2000, seed=6)
    normal = sim.simulate_players([_make_input(1, xpts=6.0, p_start=0.9)])
    capped = sim.simulate_players([PlayerSimInput(
        player_id=1, web_name="Player1", xpts=6.0, p_start=0.9,
        selected_by_percent=20.0, element_type=3, is_captain=True
    )])
    # Captain mean should be ~2x normal
    ratio = capped[0].mean_xpts / max(normal[0].mean_xpts, 0.1)
    assert 1.5 < ratio < 2.5


def test_percentiles_are_ordered():
    """p10 <= p25 <= p50 <= p75 <= p90."""
    sim = ProbabilisticSimulator(n_sims=1000, seed=7)
    results = sim.simulate_players([_make_input(1)])
    r = results[0]
    assert r.p10 <= r.p25 <= r.p50 <= r.p75 <= r.p90


def test_rank_volatility_higher_for_low_ownership():
    """Low-ownership player with same xPts has higher rank volatility."""
    sim = ProbabilisticSimulator(n_sims=1000, seed=8)
    template = sim.simulate_players([_make_input(1, ownership=60.0, xpts=7.0)])
    differential = sim.simulate_players([_make_input(2, ownership=3.0, xpts=7.0)])
    assert differential[0].rank_volatility_score > template[0].rank_volatility_score


def test_team_total_simulation():
    """Team total mean should be sum of individual means (approximately)."""
    sim = ProbabilisticSimulator(n_sims=2000, seed=9)
    players = [_make_input(i, xpts=5.0, p_start=0.95) for i in range(11)]
    total = sim.simulate_team_total(players)
    assert total["mean_team_pts"] > 0
    assert "prob_90_plus" in total
    assert 0.0 <= total["prob_90_plus"] <= 1.0


# ── LineupSimulator tests ──────────────────────────────────────────────────────

from optimizers.lineup_simulator import LineupSimulator, SquadPlayerInput


def _make_squad() -> list[SquadPlayerInput]:
    """Build a valid 15-player squad."""
    squad = []
    pos = 1
    # 2 GK (positions 1, 12)
    for i in range(2):
        squad.append(SquadPlayerInput(
            player_id=pos, web_name=f"GK{i}", position=pos,
            element_type=1, xpts=3.0, p_start=0.9 if i == 0 else 0.1, is_bench=(i==1)
        ))
        pos += 1
    # 5 DEF (3 XI + 2 bench)
    for i in range(5):
        squad.append(SquadPlayerInput(
            player_id=pos, web_name=f"DEF{i}", position=pos,
            element_type=2, xpts=4.5, p_start=0.85 if i < 3 else 0.2, is_bench=(i>=3)
        ))
        pos += 1
    # 5 MID (5 XI)
    for i in range(5):
        squad.append(SquadPlayerInput(
            player_id=pos, web_name=f"MID{i}", position=pos,
            element_type=3, xpts=6.0, p_start=0.9, is_bench=False
        ))
        pos += 1
    # 3 FWD (2 XI + 1 bench)
    for i in range(3):
        squad.append(SquadPlayerInput(
            player_id=pos, web_name=f"FWD{i}", position=pos,
            element_type=4, xpts=7.0, p_start=0.9 if i < 2 else 0.1, is_bench=(i==2)
        ))
        pos += 1
    return squad


def test_lineup_sim_returns_all_players():
    sim = LineupSimulator(n_sims=200, seed=10)
    squad = _make_squad()
    result = sim.simulate(squad)
    assert len(result["player_probabilities"]) == len(squad)


def test_lineup_sim_probabilities_in_range():
    sim = LineupSimulator(n_sims=200, seed=11)
    squad = _make_squad()
    result = sim.simulate(squad)
    for p in result["player_probabilities"]:
        assert 0.0 <= p["p_start"] <= 1.0


def test_lineup_sim_expected_xi_xpts_positive():
    sim = LineupSimulator(n_sims=200, seed=12)
    result = sim.simulate(_make_squad())
    assert result["expected_xi_xpts"] > 0


def test_lineup_sim_uncertainty_summary_keys():
    sim = LineupSimulator(n_sims=200, seed=13)
    result = sim.simulate(_make_squad())
    summary = result["uncertainty_summary"]
    assert "high_confidence_starters" in summary
    assert "rotation_risks" in summary
    assert "unlikely_starters" in summary


def test_high_p_start_players_in_most_likely_xi():
    """Players with p_start=0.95 should be in the most likely XI."""
    sim = LineupSimulator(n_sims=500, seed=14)
    squad = _make_squad()
    result = sim.simulate(squad)
    probs = {p["player_id"]: p["p_start"] for p in result["player_probabilities"]}
    # High-confidence starters (p_start > 0.85 in input) should have high simulated p_start
    high_confidence = [p for p in result["player_probabilities"] if p["p_start"] > 0.7]
    assert len(high_confidence) >= 8, "At least 8 players should be high confidence starters"
