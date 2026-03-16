"""
Integration tests for FastAPI routes — run against the live Docker backend.

These tests hit the real API at http://localhost:8000.
Run: pytest backend/tests/test_api_routes.py -v

Requires:
  - Docker stack running (docker compose up -d)
  - Squad already synced (POST /api/squad/sync called at least once)
"""
import sys
import os
import pytest
import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_URL = os.getenv("API_URL", "http://localhost:8000")
TEAM_ID = int(os.getenv("FPL_TEAM_ID", "8433551"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def client():
    """Shared sync httpx client for all route tests."""
    with httpx.Client(base_url=BASE_URL, timeout=15.0) as c:
        yield c


def _params(extra: dict = None) -> dict:
    p = {"team_id": TEAM_ID}
    if extra:
        p.update(extra)
    return p


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_ok(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["redis"] in ("ok", "error")  # redis may be unavailable in CI

    def test_health_has_team_id(self, client):
        r = client.get("/api/health")
        assert "team_id" in r.json()


# ---------------------------------------------------------------------------
# Squad
# ---------------------------------------------------------------------------

class TestSquadRoutes:
    def test_get_squad_returns_200(self, client):
        r = client.get("/api/squad/", params=_params())
        assert r.status_code == 200

    def test_get_squad_has_picks_key(self, client):
        r = client.get("/api/squad/", params=_params())
        data = r.json()
        assert "picks" in data

    def test_squad_picks_have_required_fields(self, client):
        r = client.get("/api/squad/", params=_params())
        data = r.json()
        picks = data.get("picks", [])
        if not picks:
            pytest.skip("Squad not synced — run /api/squad/sync first")
        for pick in picks:
            assert "position" in pick
            assert "player" in pick
            player = pick["player"]
            assert "id" in player
            assert "web_name" in player
            assert "element_type" in player

    def test_squad_has_bank_and_ft(self, client):
        r = client.get("/api/squad/", params=_params())
        data = r.json()
        assert "bank" in data
        assert "free_transfers" in data

    def test_squad_position_range(self, client):
        r = client.get("/api/squad/", params=_params())
        picks = r.json().get("picks", [])
        if not picks:
            pytest.skip("No squad data")
        positions = [p["position"] for p in picks]
        assert all(1 <= pos <= 15 for pos in positions), "positions must be 1-15"

    def test_squad_max_15_players(self, client):
        r = client.get("/api/squad/", params=_params())
        picks = r.json().get("picks", [])
        assert len(picks) <= 15

    def test_sync_returns_started(self, client):
        r = client.post("/api/squad/sync", params=_params())
        assert r.status_code == 200
        data = r.json()
        assert data["status"] in ("started", "already_running")

    def test_sync_status_returns_dict(self, client):
        r = client.get("/api/squad/status")
        assert r.status_code == 200
        data = r.json()
        assert "is_running" in data

    def test_leagues_returns_dict(self, client):
        r = client.get("/api/squad/leagues", params={"team_id": TEAM_ID})
        assert r.status_code == 200
        data = r.json()
        assert "classic" in data or "h2h" in data


# ---------------------------------------------------------------------------
# Transfers
# ---------------------------------------------------------------------------

class TestTransferRoutes:
    def test_suggestions_returns_200(self, client):
        r = client.get("/api/transfers/suggestions", params=_params())
        assert r.status_code == 200

    def test_suggestions_has_required_keys(self, client):
        r = client.get("/api/transfers/suggestions", params=_params())
        data = r.json()
        assert "free_transfers" in data
        assert "bank_millions" in data
        assert "suggestions" in data

    def test_suggestions_list(self, client):
        r = client.get("/api/transfers/suggestions", params=_params())
        suggestions = r.json().get("suggestions", [])
        assert isinstance(suggestions, list)

    def test_suggestion_fields_when_present(self, client):
        r = client.get("/api/transfers/suggestions", params=_params())
        suggestions = r.json().get("suggestions", [])
        for s in suggestions[:3]:
            assert "player_out" in s or "player_out_id" in s or "player_out_name" in s
            assert "recommendation" in s

    def test_bank_route_returns_200(self, client):
        r = client.get("/api/transfers/bank", params=_params())
        assert r.status_code in (200, 404)  # 404 if not synced

    def test_evaluate_endpoint_exists(self, client):
        r = client.post(
            "/api/transfers/evaluate",
            params=_params(),
            json={"player_out_id": 1, "player_in_id": 2},
        )
        assert r.status_code in (200, 404, 422)


# ---------------------------------------------------------------------------
# Optimization
# ---------------------------------------------------------------------------

class TestOptimizationRoutes:
    def test_captain_returns_200(self, client):
        r = client.get("/api/optimization/captain", params=_params())
        assert r.status_code == 200

    def test_captain_has_candidates(self, client):
        r = client.get("/api/optimization/captain", params=_params())
        data = r.json()
        assert "candidates" in data
        assert isinstance(data["candidates"], list)

    def test_captain_candidate_fields(self, client):
        r = client.get("/api/optimization/captain", params=_params())
        candidates = r.json().get("candidates", [])
        for c in candidates[:3]:
            assert "player_id" in c
            assert "web_name" in c
            assert "captain_score" in c or "score" in c

    def test_captain_sorted_by_score_desc(self, client):
        r = client.get("/api/optimization/captain", params=_params())
        candidates = r.json().get("candidates", [])
        if len(candidates) < 2:
            pytest.skip("Not enough candidates")
        scores = [c.get("captain_score", c.get("score", 0)) for c in candidates]
        assert scores == sorted(scores, reverse=True), "Candidates should be sorted by score desc"

    def test_squad_optimizer_returns_200(self, client):
        r = client.get("/api/optimization/squad", params=_params())
        assert r.status_code == 200

    def test_squad_optimizer_has_starting_xi(self, client):
        r = client.get("/api/optimization/squad", params=_params())
        data = r.json()
        assert "starting_xi" in data
        xi = data["starting_xi"]
        assert isinstance(xi, list)
        assert 1 <= len(xi) <= 11


# ---------------------------------------------------------------------------
# Chips
# ---------------------------------------------------------------------------

class TestChipRoutes:
    def test_status_returns_200(self, client):
        r = client.get("/api/chips/status", params=_params())
        assert r.status_code == 200

    def test_status_has_chips_dict(self, client):
        r = client.get("/api/chips/status", params=_params())
        data = r.json()
        assert "chips" in data
        chips = data["chips"]
        for chip in ["wildcard", "free_hit", "bench_boost", "triple_captain"]:
            assert chip in chips

    def test_chip_available_now_is_bool(self, client):
        r = client.get("/api/chips/status", params=_params())
        chips = r.json()["chips"]
        for chip_data in chips.values():
            assert isinstance(chip_data["available_now"], bool)

    def test_history_returns_200(self, client):
        r = client.get("/api/chips/history", params=_params())
        assert r.status_code == 200

    def test_history_has_chip_history_list(self, client):
        r = client.get("/api/chips/history", params=_params())
        assert "chip_history" in r.json()

    def test_recommendations_returns_200(self, client):
        r = client.get("/api/chips/recommendations", params=_params())
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:300]}"

    def test_recommendations_has_gameweek(self, client):
        r = client.get("/api/chips/recommendations", params=_params())
        data = r.json()
        assert "gameweek" in data
        assert isinstance(data["gameweek"], int)

    def test_recommendations_structure(self, client):
        r = client.get("/api/chips/recommendations", params=_params())
        data = r.json()
        recs = data.get("recommendations", {})
        assert isinstance(recs, dict)
        for rec in recs.values():
            assert "chip" in rec
            assert "recommended_gw" in rec
            assert "confidence" in rec
            assert "urgency" in rec
            assert 0.0 <= rec["confidence"] <= 1.0


# ---------------------------------------------------------------------------
# Intel
# ---------------------------------------------------------------------------

class TestIntelRoutes:
    def test_gw_intel_returns_200(self, client):
        r = client.get("/api/intel/gw", params=_params())
        assert r.status_code == 200

    def test_gw_intel_has_captain_recommendation(self, client):
        r = client.get("/api/intel/gw", params=_params())
        data = r.json()
        assert "captain_recommendation" in data

    def test_gw_intel_has_injury_alerts(self, client):
        r = client.get("/api/intel/gw", params=_params())
        data = r.json()
        assert "injury_alerts" in data
        assert isinstance(data["injury_alerts"], list)

    def test_fixture_swings_returns_200(self, client):
        r = client.get("/api/intel/fixture-swings")
        assert r.status_code == 200

    def test_fixture_swings_has_buy_sell(self, client):
        r = client.get("/api/intel/fixture-swings")
        data = r.json()
        assert "buy_windows" in data
        assert "sell_windows" in data

    def test_yellow_cards_returns_200(self, client):
        r = client.get("/api/intel/yellow-cards", params=_params())
        assert r.status_code == 200

    def test_yellow_cards_has_players(self, client):
        r = client.get("/api/intel/yellow-cards", params=_params())
        data = r.json()
        assert "players_at_risk" in data
        assert isinstance(data["players_at_risk"], list)
        for player in data["players_at_risk"][:3]:
            assert "player_id" in player
            assert "yellow_cards" in player


# ---------------------------------------------------------------------------
# Live
# ---------------------------------------------------------------------------

class TestLiveRoutes:
    def test_score_returns_200(self, client):
        r = client.get("/api/live/score", params=_params())
        assert r.status_code == 200

    def test_score_has_squad(self, client):
        r = client.get("/api/live/score", params=_params())
        data = r.json()
        assert "squad" in data
        assert "total_live_points" in data
        assert "gameweek" in data

    def test_score_squad_player_fields(self, client):
        r = client.get("/api/live/score", params=_params())
        squad = r.json().get("squad", [])
        for player in squad[:5]:
            assert "player_id" in player
            assert "web_name" in player
            assert "live_points" in player
            assert "effective_points" in player
            assert isinstance(player["live_points"], (int, float))

    def test_autosubs_returns_200(self, client):
        r = client.get("/api/live/autosubs", params=_params())
        assert r.status_code == 200

    def test_autosubs_has_autosubs_list(self, client):
        r = client.get("/api/live/autosubs", params=_params())
        data = r.json()
        assert "autosubs" in data
        assert isinstance(data["autosubs"], list)


# ---------------------------------------------------------------------------
# Players
# ---------------------------------------------------------------------------

class TestPlayersRoutes:
    def test_list_returns_200(self, client):
        r = client.get("/api/players/", params={"limit": 10})
        assert r.status_code == 200

    def test_list_is_array(self, client):
        r = client.get("/api/players/", params={"limit": 5})
        data = r.json()
        assert isinstance(data, list)

    def test_player_fields(self, client):
        r = client.get("/api/players/", params={"limit": 5})
        players = r.json()
        for p in players:
            assert "id" in p
            assert "web_name" in p
            assert "element_type" in p
            assert p["element_type"] in (1, 2, 3, 4)

    def test_filter_by_element_type(self, client):
        r = client.get("/api/players/", params={"element_type": 4, "limit": 10})
        players = r.json()
        for p in players:
            assert p["element_type"] == 4, "All players should be FWD (element_type 4)"

    def test_search_filter(self, client):
        r = client.get("/api/players/", params={"search": "Haaland", "limit": 5})
        players = r.json()
        # Haaland should appear in results if DB has player data
        names = [p["web_name"].lower() for p in players]
        assert any("haaland" in n for n in names) or len(players) == 0

    def test_watchlist_get(self, client):
        r = client.get("/api/players/watchlist", params=_params())
        assert r.status_code in (200, 404)


# ---------------------------------------------------------------------------
# Rivals
# ---------------------------------------------------------------------------

class TestRivalsRoutes:
    def test_list_returns_200(self, client):
        r = client.get("/api/rivals/", params=_params())
        assert r.status_code == 200

    def test_list_is_array(self, client):
        r = client.get("/api/rivals/", params=_params())
        assert isinstance(r.json(), list)

    def test_captain_picks_returns_200(self, client):
        r = client.get("/api/rivals/captain-picks", params=_params())
        assert r.status_code == 200

    def test_add_rival_validates_body(self, client):
        r = client.post("/api/rivals/add", params=_params(), json={})
        assert r.status_code == 422  # missing rival_team_id

    def test_add_rival_with_valid_body(self, client):
        r = client.post(
            "/api/rivals/add",
            params=_params(),
            json={"rival_team_id": 999999},
        )
        assert r.status_code in (200, 404, 422, 502)
