"""
Odds Agent — fetches Premier League match odds from The Odds API.

Free tier: 500 requests/month → cached aggressively (12h TTL).
Falls back to team-strength-based probability if API key not configured.
"""
import httpx
import orjson
from loguru import logger

from core.config import settings
from core.redis_client import cache_get_json, cache_set_json

ODDS_BASE = "https://api.the-odds-api.com/v4"
ODDS_CACHE_KEY = "odds:epl:current"
ODDS_CACHE_TTL = 43200  # 12h — very conservative to preserve free tier


class OddsAgent:
    def __init__(self, client: httpx.AsyncClient):
        self._client = client

    async def get_premier_league_odds(self) -> list[dict]:
        """
        Fetch EPL match win/draw probabilities.
        Returns list of {home_team, away_team, home_win_prob, draw_prob, away_win_prob}.
        """
        cached = await cache_get_json(ODDS_CACHE_KEY)
        if cached:
            return cached

        if not settings.odds_enabled:
            logger.info("Odds API key not configured — skipping odds fetch")
            return []

        try:
            resp = await self._client.get(
                f"{ODDS_BASE}/sports/soccer_epl/odds",
                params={
                    "apiKey": settings.ODDS_API_KEY,
                    "regions": "uk",
                    "markets": "h2h",
                    "oddsFormat": "decimal",
                },
                timeout=20.0,
            )
            resp.raise_for_status()
            raw_games = resp.json()

            results = []
            for game in raw_games:
                odds_data = self._extract_h2h_odds(game)
                if odds_data:
                    results.append(odds_data)

            await cache_set_json(ODDS_CACHE_KEY, results, ODDS_CACHE_TTL)
            logger.info(f"Fetched odds for {len(results)} EPL fixtures")
            return results

        except Exception as e:
            logger.error(f"Odds API fetch failed: {e}")
            return []

    def _extract_h2h_odds(self, game: dict) -> dict | None:
        """Convert decimal odds → implied probabilities (normalized)."""
        try:
            bookmakers = game.get("bookmakers", [])
            if not bookmakers:
                return None

            # Use first available bookmaker (typically Bet365 or William Hill for UK)
            bm = bookmakers[0]
            h2h_market = next(
                (m for m in bm.get("markets", []) if m["key"] == "h2h"),
                None,
            )
            if not h2h_market:
                return None

            outcomes = {o["name"]: o["price"] for o in h2h_market.get("outcomes", [])}
            home_team = game.get("home_team", "")
            away_team = game.get("away_team", "")

            home_odds = outcomes.get(home_team, 3.0)
            away_odds = outcomes.get(away_team, 3.0)
            draw_odds = outcomes.get("Draw", 3.5)

            # Convert to implied prob: P = 1/odds
            home_raw = 1 / home_odds
            away_raw = 1 / away_odds
            draw_raw = 1 / draw_odds

            # Normalize (remove bookmaker overround)
            total = home_raw + away_raw + draw_raw
            return {
                "home_team": home_team,
                "away_team": away_team,
                "kickoff": game.get("commence_time", ""),
                "home_win_prob": round(home_raw / total, 4),
                "away_win_prob": round(away_raw / total, 4),
                "draw_prob": round(draw_raw / total, 4),
            }
        except Exception:
            return None

    def team_strength_probability(
        self,
        team_strength_home: int,
        opponent_strength_away: int,
        is_home: bool,
    ) -> float:
        """
        Fallback win probability based on FPL team strength ratings.
        Returns P(team wins).
        """
        if is_home:
            delta = team_strength_home - opponent_strength_away
        else:
            delta = opponent_strength_away - team_strength_home

        # Sigmoid-like mapping: delta [-2, 2] → prob [0.2, 0.8]
        raw = 0.5 + (delta * 0.15)
        return max(0.1, min(0.9, raw))
