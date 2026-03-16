"""
Stats Agent — scrapes understat.com for xG/xA player statistics.

understat embeds player data as a JSON.parse() call inside a <script> tag.
Pattern: var playersData = JSON.parse('...')
"""
import re
import json
import difflib
import asyncio
import httpx
from loguru import logger
from bs4 import BeautifulSoup

from core.redis_client import cache_get_json, cache_set_json
from core.config import settings

UNDERSTAT_BASE = "https://understat.com"
NAME_MAP_CACHE_KEY = "understat:name_map"
NAME_MAP_TTL = 86400  # 24h


class StatsAgent:
    def __init__(self, client: httpx.AsyncClient):
        self._client = client

    async def _fetch_html(self, url: str) -> str:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.5",
        }
        resp = await self._client.get(url, headers=headers, timeout=30.0)
        resp.raise_for_status()
        return resp.text

    def _extract_json_var(self, html: str, var_name: str) -> dict | list:
        """
        Extract JSON data from: var {var_name} = JSON.parse('...')
        understat uses JSON.parse with Unicode-escaped strings.
        """
        soup = BeautifulSoup(html, "lxml")
        for script in soup.find_all("script"):
            if var_name in (script.string or ""):
                match = re.search(
                    rf"var\s+{var_name}\s*=\s*JSON\.parse\('(.+?)'\)",
                    script.string,
                    re.DOTALL,
                )
                if match:
                    raw = match.group(1)
                    # Unescape: understat uses \\x hex encoding inside single-quoted JSON
                    raw = raw.encode("utf-8").decode("unicode_escape")
                    try:
                        return json.loads(raw)
                    except json.JSONDecodeError:
                        # Fallback: strip single-quote escaping
                        raw_clean = raw.replace("\\'", "'")
                        return json.loads(raw_clean)
        return {}

    async def get_league_players(self, season: str | None = None) -> list[dict]:
        """
        Fetch all EPL player stats for a season from understat.
        Returns list of player dicts with xG, xA, npxG, minutes, etc.

        season: "2025" = 2025/26 season, "2024" = 2024/25, etc.
        """
        s = season or settings.UNDERSTAT_SEASON
        url = f"{UNDERSTAT_BASE}/league/EPL/{s}"
        logger.info(f"Fetching understat EPL players for season {s}")

        try:
            html = await self._fetch_html(url)
            raw = self._extract_json_var(html, "playersData")

            if isinstance(raw, dict):
                players = list(raw.values())
            elif isinstance(raw, list):
                players = raw
            else:
                logger.warning("Unexpected understat playersData format")
                return []

            # Normalize field types
            result = []
            for p in players:
                try:
                    result.append({
                        "id": str(p.get("id", "")),
                        "player_name": p.get("player_name", ""),
                        "team_title": p.get("team_title", ""),
                        "games": int(p.get("games", 0)),
                        "time": int(p.get("time", 0)),           # minutes played
                        "goals": int(p.get("goals", 0)),
                        "assists": int(p.get("assists", 0)),
                        "xG": float(p.get("xG", 0)),
                        "xA": float(p.get("xA", 0)),
                        "npg": int(p.get("npg", 0)),             # non-penalty goals
                        "npxG": float(p.get("npxG", 0)),
                        "xGChain": float(p.get("xGChain", 0)),
                        "xGBuildup": float(p.get("xGBuildup", 0)),
                        "shots": int(p.get("shots", 0)),
                        "key_passes": int(p.get("key_passes", 0)),
                        "yellow_cards": int(p.get("yellow_cards", 0)),
                        "red_cards": int(p.get("red_cards", 0)),
                        "position": p.get("position", ""),
                    })
                except (ValueError, TypeError) as e:
                    logger.debug(f"Skipping malformed understat player: {e}")

            logger.info(f"Fetched {len(result)} understat players")
            return result

        except Exception as e:
            logger.error(f"Understat scrape failed: {e}")
            return []

    def _normalize_name(self, name: str) -> str:
        """Lowercase, strip accents, remove punctuation for fuzzy matching."""
        import unicodedata
        name = unicodedata.normalize("NFKD", name)
        name = "".join(c for c in name if not unicodedata.combining(c))
        return name.lower().strip()

    async def build_name_map(
        self,
        fpl_players: list[dict],
        understat_players: list[dict],
    ) -> dict[int, str]:
        """
        Match FPL player IDs → understat player IDs via fuzzy name matching.
        Cached in Redis for 24h.

        Returns: {fpl_player_id: understat_id}
        """
        cached = await cache_get_json(NAME_MAP_CACHE_KEY)
        if cached:
            logger.debug("Using cached understat name map")
            return {int(k): v for k, v in cached.items()}

        name_map: dict[int, str] = {}
        understat_names = [
            (self._normalize_name(p["player_name"]), p["id"])
            for p in understat_players
        ]
        understat_lookup = {name: uid for name, uid in understat_names}

        for fpl_player in fpl_players:
            fpl_id = fpl_player.get("id")
            web_name = self._normalize_name(fpl_player.get("web_name", ""))
            full_name = self._normalize_name(
                f"{fpl_player.get('first_name', '')} {fpl_player.get('second_name', '')}".strip()
            )

            # Try exact match on web_name first
            if web_name in understat_lookup:
                name_map[fpl_id] = understat_lookup[web_name]
                continue

            # Try exact match on full name
            if full_name in understat_lookup:
                name_map[fpl_id] = understat_lookup[full_name]
                continue

            # Fuzzy match against all understat names
            all_names = [name for name, _ in understat_names]
            matches = difflib.get_close_matches(full_name, all_names, n=1, cutoff=0.8)
            if matches:
                name_map[fpl_id] = understat_lookup[matches[0]]
                continue

            # Try web_name fuzzy
            matches = difflib.get_close_matches(web_name, all_names, n=1, cutoff=0.75)
            if matches:
                name_map[fpl_id] = understat_lookup[matches[0]]

        logger.info(f"Name map built: {len(name_map)}/{len(fpl_players)} FPL players matched to understat")

        # Cache as string keys (JSON doesn't support int keys)
        await cache_set_json(NAME_MAP_CACHE_KEY, {str(k): v for k, v in name_map.items()}, NAME_MAP_TTL)
        return name_map

    def compute_per90_stats(self, player: dict) -> dict:
        """Calculate per-90 xG/xA stats from understat totals."""
        minutes = player.get("time", 0)
        nineties = max(minutes / 90, 0.01)  # avoid division by zero

        return {
            "xg_per_90": round(player.get("xG", 0) / nineties, 4),
            "xa_per_90": round(player.get("xA", 0) / nineties, 4),
            "npxg_per_90": round(player.get("npxG", 0) / nineties, 4),
            "xg_season": round(player.get("xG", 0), 4),
            "xa_season": round(player.get("xA", 0), 4),
        }
