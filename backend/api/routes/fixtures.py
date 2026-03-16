"""
Fixtures API — team schedule, fixture difficulty, and match importance.

GET /api/fixtures/schedule      — all 20 teams × next N GWs with FDR + context
GET /api/fixtures/team/{id}     — single team fixture list
GET /api/fixtures/dgw           — double/blank gameweek detection for upcoming GWs
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Query
from sqlalchemy import select

from core.database import AsyncSessionLocal
from core.redis_client import redis_client
from models.db.gameweek import Gameweek

logger = logging.getLogger(__name__)
router = APIRouter()

_FPL_BASE = "https://fantasy.premierleague.com/api"
_CACHE_TTL = 900  # 15 min — FDR rarely changes mid-season

# FDR palette for frontend consumption
FDR_LABEL = {1: "very_easy", 2: "easy", 3: "medium", 4: "hard", 5: "very_hard"}

# Team strength thresholds for match_importance tag
_TITLE_STRENGTH = 1200
_RELEGATION_STRENGTH = 1060


async def _bootstrap() -> Dict:
    """Fetch and cache FPL bootstrap-static (teams + events)."""
    cache_key = "fpl:bootstrap:fixture_route"
    cached = await redis_client.get(cache_key)
    if cached:
        return json.loads(cached)

    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(f"{_FPL_BASE}/bootstrap-static/")
        r.raise_for_status()
        data = r.json()

    await redis_client.set(cache_key, json.dumps(data), ex=_CACHE_TTL)
    return data


async def _all_fixtures() -> List[Dict]:
    """Fetch and cache all FPL fixtures for the season."""
    cache_key = "fpl:fixtures:all"
    cached = await redis_client.get(cache_key)
    if cached:
        return json.loads(cached)

    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(f"{_FPL_BASE}/fixtures/")
        r.raise_for_status()
        fixtures = r.json()

    await redis_client.set(cache_key, json.dumps(fixtures), ex=_CACHE_TTL)
    return fixtures


def _match_importance(
    home_strength: int, away_strength: int
) -> Optional[str]:
    """
    Tag a fixture with a rough match-importance label.

    title_race      — both teams chasing the title (high strength)
    european        — one or both teams fighting for European places
    relegation      — one or both teams in relegation trouble
    top_vs_bottom   — clear quality mismatch (implies rotation risk for top team)
    """
    both_strong = home_strength >= _TITLE_STRENGTH and away_strength >= _TITLE_STRENGTH
    if both_strong:
        return "title_race"

    either_strong = max(home_strength, away_strength) >= _TITLE_STRENGTH
    either_weak = min(home_strength, away_strength) <= _RELEGATION_STRENGTH

    if either_strong and either_weak:
        return "top_vs_bottom"      # rotation risk for star players of top team

    if min(home_strength, away_strength) <= _RELEGATION_STRENGTH:
        return "relegation"

    if max(home_strength, away_strength) >= 1150:
        return "european"

    return None  # mid-table, no special context


# ---------------------------------------------------------------------------
# GET /api/fixtures/schedule
# ---------------------------------------------------------------------------


@router.get("/schedule")
async def get_fixture_schedule(
    gws: int = Query(6, ge=1, le=10, description="Number of upcoming GWs to include"),
):
    """
    Return the fixture schedule for all 20 Premier League teams across the next
    `gws` gameweeks.

    Response:
    {
      "current_gw": 29,
      "gw_range": [29, 30, 31, 32, 33, 34],
      "teams": [
        {
          "id": 1, "name": "Arsenal", "short_name": "ARS",
          "strength_overall": 1230,
          "match_type": "title_race",    // team's typical fixture type
          "fixtures": {
            "29": [{ "opponent_id": 14, "opponent": "Man City", "opponent_short": "MCI",
                     "was_home": false, "fdr": 5, "fdr_label": "very_hard",
                     "match_importance": "title_race" }],
            "30": [],         // blank gameweek — empty list
            "31": [{ ... }, { ... }]  // double gameweek — two fixtures
          }
        },
        ...
      ]
    }
    """
    cache_key = f"fixture:schedule:{gws}gws"
    cached = await redis_client.get(cache_key)
    if cached:
        return json.loads(cached)

    # ── 1. Current GW ────────────────────────────────────────────────────────
    async with AsyncSessionLocal() as db:
        gw_res = await db.execute(
            select(Gameweek).where(Gameweek.is_current == True)  # noqa: E712
        )
        current_gw = gw_res.scalar_one_or_none()

    current_gw_id = current_gw.id if current_gw else 1
    gw_range = list(range(current_gw_id, min(current_gw_id + gws, 39)))

    # ── 2. Bootstrap data ────────────────────────────────────────────────────
    bootstrap = await _bootstrap()
    teams_raw = {t["id"]: t for t in bootstrap.get("teams", [])}

    # ── 3. All fixtures ──────────────────────────────────────────────────────
    all_fixtures = await _all_fixtures()
    # Filter to target GWs only
    target_fixtures = [f for f in all_fixtures if f.get("event") in gw_range]

    # ── 4. Build per-team schedule ───────────────────────────────────────────
    # team_id → { gw_id → [fixture_dict, ...] }
    schedule: Dict[int, Dict[int, List[Dict]]] = {
        tid: {gw: [] for gw in gw_range} for tid in teams_raw
    }

    for fix in target_fixtures:
        gw_id = fix.get("event")
        if gw_id not in gw_range:
            continue

        team_h = fix.get("team_h")
        team_a = fix.get("team_a")
        fdr_h = fix.get("team_h_difficulty", 3)
        fdr_a = fix.get("team_a_difficulty", 3)

        h_team = teams_raw.get(team_h, {})
        a_team = teams_raw.get(team_a, {})

        h_strength = h_team.get("strength_overall_home", 1100)
        a_strength = a_team.get("strength_overall_away", 1100)
        importance = _match_importance(h_strength, a_strength)

        if team_h and team_h in schedule:
            schedule[team_h][gw_id].append({
                "opponent_id": team_a,
                "opponent": a_team.get("name", ""),
                "opponent_short": a_team.get("short_name", "???"),
                "was_home": True,
                "fdr": fdr_h,
                "fdr_label": FDR_LABEL.get(fdr_h, "medium"),
                "match_importance": importance,
                "finished": fix.get("finished", False),
            })

        if team_a and team_a in schedule:
            schedule[team_a][gw_id].append({
                "opponent_id": team_h,
                "opponent": h_team.get("name", ""),
                "opponent_short": h_team.get("short_name", "???"),
                "was_home": False,
                "fdr": fdr_a,
                "fdr_label": FDR_LABEL.get(fdr_a, "medium"),
                "match_importance": importance,
                "finished": fix.get("finished", False),
            })

    # ── 5. Build response ────────────────────────────────────────────────────
    result_teams = []
    for tid, team in sorted(teams_raw.items(), key=lambda x: x[1].get("name", "")):
        strength = team.get("strength_overall_home", 1100)

        # Compute avg FDR over the window (for sorting)
        all_fdrs = [
            fix["fdr"]
            for gw in gw_range
            for fix in schedule[tid].get(gw, [])
        ]
        avg_fdr = round(sum(all_fdrs) / len(all_fdrs), 2) if all_fdrs else 3.0

        # DGW / BGW flags
        is_dgw_gw = [gw for gw in gw_range if len(schedule[tid].get(gw, [])) >= 2]
        is_bgw_gw = [gw for gw in gw_range if len(schedule[tid].get(gw, [])) == 0]

        result_teams.append({
            "id": tid,
            "name": team.get("name", ""),
            "short_name": team.get("short_name", ""),
            "code": team.get("code"),
            "strength_overall": strength,
            "avg_fdr_next_n": avg_fdr,
            "has_dgw": len(is_dgw_gw) > 0,
            "dgw_gws": is_dgw_gw,
            "bgw_gws": is_bgw_gw,
            "fixtures": {str(gw): schedule[tid].get(gw, []) for gw in gw_range},
        })

    response = {
        "current_gw": current_gw_id,
        "gw_range": gw_range,
        "teams": result_teams,
    }

    await redis_client.set(cache_key, json.dumps(response), ex=_CACHE_TTL)
    return response


# ---------------------------------------------------------------------------
# GET /api/fixtures/team/{team_id}
# ---------------------------------------------------------------------------


@router.get("/team/{team_id}")
async def get_team_fixtures(
    team_id: int,
    gws: int = Query(6, ge=1, le=10),
):
    """Return fixtures for a single team over the next `gws` GWs."""
    schedule = await get_fixture_schedule(gws=gws)
    team = next((t for t in schedule["teams"] if t["id"] == team_id), None)
    if not team:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Team {team_id} not found")
    return {
        "current_gw": schedule["current_gw"],
        "gw_range": schedule["gw_range"],
        "team": team,
    }


# ---------------------------------------------------------------------------
# GET /api/fixtures/dgw
# ---------------------------------------------------------------------------


@router.get("/dgw")
async def get_dgw_teams(gws: int = Query(6, ge=1, le=10)):
    """
    Return teams with a Double or Blank Gameweek in the upcoming fixture window.

    Response:
    {
      "current_gw": 29,
      "gw_range": [29, ..., 34],
      "double_gws": { "32": ["Liverpool", "Arsenal"] },
      "blank_gws":  { "31": ["Everton"] }
    }
    """
    schedule = await get_fixture_schedule(gws=gws)
    double_gws: Dict[str, List[str]] = {}
    blank_gws: Dict[str, List[str]] = {}

    for team in schedule["teams"]:
        for gw in team["dgw_gws"]:
            double_gws.setdefault(str(gw), []).append(team["name"])
        for gw in team["bgw_gws"]:
            blank_gws.setdefault(str(gw), []).append(team["name"])

    return {
        "current_gw": schedule["current_gw"],
        "gw_range": schedule["gw_range"],
        "double_gws": double_gws,
        "blank_gws": blank_gws,
    }
