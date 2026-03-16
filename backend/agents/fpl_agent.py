"""
FPL Agent — wraps all official Fantasy Premier League API endpoints.

All endpoints are cached in Redis with appropriate TTLs.
Rate limit handling: tenacity retry with exponential backoff + Retry-After header respect.
"""
import asyncio
import httpx
import orjson
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from core.redis_client import cache_get, cache_set
from core.exceptions import FPLAPIError

FPL_BASE = "https://fantasy.premierleague.com/api"
FPL_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-GB,en;q=0.9",
    "Referer": "https://fantasy.premierleague.com/",
}

# Redis TTLs per endpoint (seconds)
CACHE_TTLS = {
    "bootstrap": 3600,        # Full player/team/event data — changes once per GW
    "fixtures_gw": 3600,      # Fixture list for a GW
    "player_summary": 1800,   # Individual player history
    "live_gw": 60,            # Live scoring — short TTL during active GW
    "entry": 300,             # User profile data
    "picks": 300,             # User squad picks
    "transfers": 900,         # Transfer history
    "leagues": 300,           # League standings
}


class FPLAgent:
    def __init__(self, client: httpx.AsyncClient):
        self._client = client

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=15),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException)),
        reraise=True,
    )
    async def _get(self, url: str, cache_key: str, ttl: int) -> dict | list:
        """
        Fetch URL with Redis caching. On 429, respects Retry-After header.
        """
        cached = await cache_get(cache_key)
        if cached:
            return orjson.loads(cached)

        try:
            resp = await self._client.get(url, headers=FPL_HEADERS, timeout=30.0)

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", "60"))
                logger.warning(f"FPL API rate limited. Waiting {retry_after}s before retry.")
                await asyncio.sleep(retry_after)
                raise httpx.HTTPStatusError("Rate limited", request=resp.request, response=resp)

            resp.raise_for_status()

        except httpx.HTTPStatusError as e:
            logger.error(f"FPL API HTTP error for {url}: {e}")
            raise FPLAPIError(f"FPL API returned {e.response.status_code} for {url}") from e

        data = resp.json()
        await cache_set(cache_key, orjson.dumps(data).decode(), ttl)
        logger.debug(f"Fetched {url} → cached as {cache_key} for {ttl}s")
        return data

    # ── Main endpoints ─────────────────────────────────────────────────────────

    async def get_bootstrap(self) -> dict:
        """
        Main data source: all players, teams, events, game_settings.
        ~700 players, 20 teams, 38 GWs.
        """
        return await self._get(
            f"{FPL_BASE}/bootstrap-static/",
            "fpl:bootstrap",
            CACHE_TTLS["bootstrap"],
        )

    async def get_player_summary(self, player_id: int) -> dict:
        """
        Per-player fixture history + upcoming fixtures.
        history[] = past GW data (points, minutes, goals, etc.)
        fixtures[] = remaining fixtures with FDR
        history_past[] = previous season summaries
        """
        return await self._get(
            f"{FPL_BASE}/element-summary/{player_id}/",
            f"fpl:player:{player_id}",
            CACHE_TTLS["player_summary"],
        )

    async def get_fixtures_gw(self, gw_id: int) -> list:
        """All fixtures for a specific gameweek. Returns list of fixture dicts."""
        return await self._get(
            f"{FPL_BASE}/fixtures/?event={gw_id}",
            f"fpl:fixtures:{gw_id}",
            CACHE_TTLS["fixtures_gw"],
        )

    async def get_all_fixtures(self) -> list:
        """All fixtures across the entire season (no GW filter)."""
        return await self._get(
            f"{FPL_BASE}/fixtures/",
            "fpl:fixtures:all",
            CACHE_TTLS["fixtures_gw"],
        )

    async def get_live_gw(self, gw_id: int) -> dict:
        """
        Live scoring data for a gameweek.
        elements{} keyed by player_id → stats (goals, assists, minutes, bonus, bps, etc.)
        """
        return await self._get(
            f"{FPL_BASE}/event/{gw_id}/live/",
            f"fpl:live:{gw_id}",
            CACHE_TTLS["live_gw"],
        )

    async def get_entry(self, team_id: int) -> dict:
        """
        User entry (team) profile.
        Contains: bank, squad_value, overall_rank, event_transfers, chips used.
        """
        return await self._get(
            f"{FPL_BASE}/entry/{team_id}/",
            f"fpl:entry:{team_id}",
            CACHE_TTLS["entry"],
        )

    async def get_picks(self, team_id: int, gw: int) -> dict:
        """
        User squad picks for a specific gameweek.
        picks[]: {element, position, multiplier, is_captain, is_vice_captain, purchase_price, selling_price}
        active_chip: active chip name or None
        entry_history: {points, bank, value, event_transfers, event_transfers_cost, etc.}
        """
        return await self._get(
            f"{FPL_BASE}/entry/{team_id}/event/{gw}/picks/",
            f"fpl:picks:{team_id}:{gw}",
            CACHE_TTLS["picks"],
        )

    async def get_transfers(self, team_id: int) -> list:
        """Full transfer history for a team."""
        return await self._get(
            f"{FPL_BASE}/entry/{team_id}/transfers/",
            f"fpl:transfers:{team_id}",
            CACHE_TTLS["transfers"],
        )

    async def get_entry_history(self, team_id: int) -> dict:
        """Full GW-by-GW history for a team (rank, points, bank per GW)."""
        return await self._get(
            f"{FPL_BASE}/entry/{team_id}/history/",
            f"fpl:history:{team_id}",
            CACHE_TTLS["transfers"],
        )

    async def get_league_standings(self, league_id: int, page: int = 1) -> dict:
        """Classic league standings, paginated."""
        return await self._get(
            f"{FPL_BASE}/leagues-classic/{league_id}/standings/?page_standings={page}",
            f"fpl:league:{league_id}:p{page}",
            CACHE_TTLS["leagues"],
        )

    async def invalidate_bootstrap_cache(self) -> None:
        """Force next bootstrap fetch to hit the API."""
        from core.redis_client import redis_client
        await redis_client.delete("fpl:bootstrap")
        logger.info("Bootstrap cache invalidated")

    async def invalidate_picks_cache(self, team_id: int, gw: int) -> None:
        """Invalidate cached picks for a team/GW."""
        from core.redis_client import redis_client
        await redis_client.delete(f"fpl:picks:{team_id}:{gw}")
