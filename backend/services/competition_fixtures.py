"""
Competition Fixtures Sync Service.

Fetches and stores fixtures from all competitions that PL clubs participate in:
  PL  — FPL bootstrap-static + fixtures API (no key needed)
  UCL — football-data.org  (FOOTBALL_DATA_API_KEY required)
  UEL — football-data.org
  FAC — FA Cup football-data.org
  CC  — Carabao Cup football-data.org (if available in plan)

Used downstream by player_features.py to compute:
  - rotation_risk  (team has UCL/Cup game within 3 days of PL game)
  - fixture_load   (games in next 7 days — congestion score)
  - match_importance_boost (knockout round → key players start)

Environment variables:
  FOOTBALL_DATA_API_KEY  — optional; if absent only PL fixtures are synced
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import httpx
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.db.competition_fixture import CompetitionFixture

logger = logging.getLogger(__name__)

_FDORG_BASE = "https://api.football-data.org/v4"
_FPL_BASE   = "https://fantasy.premierleague.com/api"

# Current season year (start year, e.g. 2024 for 2024-25)
_CURRENT_SEASON_YEAR = 2024
_CURRENT_SEASON      = "2024-25"

# football-data.org competition codes
_FDORG_COMPETITIONS: Dict[str, str] = {
    "UCL": "CL",   # UEFA Champions League
    "UEL": "EL",   # UEFA Europa League
    "FAC": "FAC",  # FA Cup
    # "CC": "ELC",  # EFL Championship - Carabao not in free tier
}

# Knockout round labels that boost importance
_KNOCKOUT_LABELS = {
    "round of 16", "quarter-final", "quarter final", "semi-final",
    "semi final", "final", "knockout round play-offs", "last 16",
}

# ── FPL team name → FPL team ID (bootstrap lookup) ─────────────────────────
# Populated at runtime from FPL API to avoid stale hardcoded map
_fpl_team_id_by_name: Dict[str, int] = {}
_fpl_team_id_by_short: Dict[str, int] = {}

# football-data.org team name → normalised FPL team name
# Covers slight wording differences between the two APIs
_FDORG_NAME_MAP: Dict[str, str] = {
    "Arsenal FC":                        "Arsenal",
    "Aston Villa FC":                    "Aston Villa",
    "AFC Bournemouth":                   "Bournemouth",
    "Brentford FC":                      "Brentford",
    "Brighton & Hove Albion FC":         "Brighton",
    "Chelsea FC":                        "Chelsea",
    "Crystal Palace FC":                 "Crystal Palace",
    "Everton FC":                        "Everton",
    "Fulham FC":                         "Fulham",
    "Ipswich Town FC":                   "Ipswich",
    "Leicester City FC":                 "Leicester",
    "Liverpool FC":                      "Liverpool",
    "Manchester City FC":                "Man City",
    "Manchester United FC":              "Man Utd",
    "Newcastle United FC":               "Newcastle",
    "Nottingham Forest FC":              "Nott'm Forest",
    "Southampton FC":                    "Southampton",
    "Tottenham Hotspur FC":              "Spurs",
    "West Ham United FC":                "West Ham",
    "Wolverhampton Wanderers FC":        "Wolves",
    # Alternate spellings
    "Arsenal":                           "Arsenal",
    "Aston Villa":                       "Aston Villa",
    "Bournemouth":                       "Bournemouth",
    "Brentford":                         "Brentford",
    "Brighton":                          "Brighton",
    "Chelsea":                           "Chelsea",
    "Crystal Palace":                    "Crystal Palace",
    "Everton":                           "Everton",
    "Fulham":                            "Fulham",
    "Ipswich Town":                      "Ipswich",
    "Leicester City":                    "Leicester",
    "Liverpool":                         "Liverpool",
    "Manchester City":                   "Man City",
    "Manchester United":                 "Man Utd",
    "Newcastle United":                  "Newcastle",
    "Nottingham Forest":                 "Nott'm Forest",
    "Southampton":                       "Southampton",
    "Tottenham Hotspur":                 "Spurs",
    "West Ham United":                   "West Ham",
    "Wolverhampton Wanderers":           "Wolves",
    "Wolves":                            "Wolves",
    "Spurs":                             "Spurs",
}


def _resolve_fpl_team_id(raw_name: str) -> Optional[int]:
    """Map a football-data.org team name to an FPL team ID."""
    normalised = _FDORG_NAME_MAP.get(raw_name, raw_name)
    # Try exact match first, then case-insensitive substring
    if normalised in _fpl_team_id_by_name:
        return _fpl_team_id_by_name[normalised]
    lc = raw_name.lower()
    for name, tid in _fpl_team_id_by_name.items():
        if name.lower() in lc or lc in name.lower():
            return tid
    return None


async def _load_fpl_team_map(http: httpx.AsyncClient) -> None:
    """Populate the in-memory FPL team name → ID map from bootstrap-static."""
    global _fpl_team_id_by_name, _fpl_team_id_by_short
    try:
        r = await http.get(f"{_FPL_BASE}/bootstrap-static/", timeout=20.0)
        r.raise_for_status()
        teams = r.json().get("teams", [])
        _fpl_team_id_by_name  = {t["name"]: t["id"] for t in teams}
        _fpl_team_id_by_short = {t["short_name"]: t["id"] for t in teams}
        logger.info(f"[comp_fixtures] FPL team map loaded: {len(teams)} teams")
    except Exception as e:
        logger.warning(f"[comp_fixtures] FPL team map load failed: {e}")


# ── PL sync (FPL API) ─────────────────────────────────────────────────────

async def _sync_pl_fixtures(db: AsyncSession, http: httpx.AsyncClient) -> int:
    """
    Sync Premier League fixtures from the FPL fixtures endpoint.
    Returns number of rows upserted.
    """
    try:
        r = await http.get(f"{_FPL_BASE}/fixtures/", timeout=20.0)
        r.raise_for_status()
        fixtures = r.json()
    except Exception as e:
        logger.error(f"[comp_fixtures] PL fetch failed: {e}")
        return 0

    rows: List[dict] = []
    for fix in fixtures:
        if not fix.get("event"):
            continue  # not yet scheduled to a GW
        team_h = fix.get("team_h")
        team_a = fix.get("team_a")
        # Reverse-lookup team names from our map
        name_h = next((n for n, i in _fpl_team_id_by_name.items() if i == team_h), str(team_h))
        name_a = next((n for n, i in _fpl_team_id_by_name.items() if i == team_a), str(team_a))

        kickoff_raw = fix.get("kickoff_time")
        kickoff_utc = None
        if kickoff_raw:
            try:
                kickoff_utc = datetime.fromisoformat(kickoff_raw.replace("Z", "+00:00"))
            except ValueError:
                pass

        status = "FINISHED" if fix.get("finished") else "SCHEDULED"
        rows.append({
            "competition":      "PL",
            "season":           _CURRENT_SEASON,
            "home_team_name":   name_h,
            "away_team_name":   name_a,
            "home_fpl_team_id": team_h,
            "away_fpl_team_id": team_a,
            "match_utc":        kickoff_utc,
            "status":           status,
            "home_score":       fix.get("team_h_score"),
            "away_score":       fix.get("team_a_score"),
            "fixture_round":    f"GW{fix['event']}",
            "external_id":      f"fpl_{fix['id']}",
            "updated_at":       datetime.utcnow(),
        })

    if not rows:
        return 0

    stmt = pg_insert(CompetitionFixture).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_cf_competition_external_id",
        set_={
            "status":    stmt.excluded.status,
            "home_score": stmt.excluded.home_score,
            "away_score": stmt.excluded.away_score,
            "match_utc": stmt.excluded.match_utc,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    await db.execute(stmt)
    await db.commit()
    logger.info(f"[comp_fixtures] PL: upserted {len(rows)} fixtures")
    return len(rows)


# ── football-data.org sync ────────────────────────────────────────────────

async def _sync_fdorg_competition(
    db: AsyncSession,
    http: httpx.AsyncClient,
    comp_label: str,
    fdorg_code: str,
    api_key: str,
) -> int:
    """
    Sync a single competition from football-data.org.
    Returns rows upserted.
    """
    url = f"{_FDORG_BASE}/competitions/{fdorg_code}/matches?season={_CURRENT_SEASON_YEAR}"
    try:
        r = await http.get(
            url,
            headers={"X-Auth-Token": api_key},
            timeout=20.0,
        )
        if r.status_code == 404:
            logger.info(f"[comp_fixtures] {comp_label}: no data for season {_CURRENT_SEASON_YEAR}")
            return 0
        if r.status_code == 403:
            logger.warning(f"[comp_fixtures] {comp_label}: API key unauthorised for this competition")
            return 0
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.error(f"[comp_fixtures] {comp_label} fetch failed: {e}")
        return 0

    matches = data.get("matches", [])
    rows: List[dict] = []

    for m in matches:
        home_raw = m.get("homeTeam", {}).get("name", "") or m.get("homeTeam", {}).get("shortName", "")
        away_raw = m.get("awayTeam", {}).get("name", "") or m.get("awayTeam", {}).get("shortName", "")

        home_fpl = _resolve_fpl_team_id(home_raw)
        away_fpl = _resolve_fpl_team_id(away_raw)

        utc_date_raw = m.get("utcDate")
        match_utc = None
        if utc_date_raw:
            try:
                match_utc = datetime.fromisoformat(utc_date_raw.replace("Z", "+00:00"))
            except ValueError:
                pass

        raw_status = m.get("status", "SCHEDULED").upper()
        score_full = m.get("score", {}).get("fullTime", {})
        home_score = score_full.get("home")
        away_score = score_full.get("away")

        match_day = m.get("matchday")
        stage      = m.get("stage", "")
        round_name = m.get("group") or stage or (f"Matchday {match_day}" if match_day else None)

        rows.append({
            "competition":      comp_label,
            "season":           _CURRENT_SEASON,
            "home_team_name":   home_raw,
            "away_team_name":   away_raw,
            "home_fpl_team_id": home_fpl,
            "away_fpl_team_id": away_fpl,
            "match_utc":        match_utc,
            "status":           raw_status,
            "home_score":       home_score,
            "away_score":       away_score,
            "fixture_round":    round_name,
            "external_id":      f"fdorg_{m['id']}",
            "updated_at":       datetime.utcnow(),
        })

    if not rows:
        return 0

    stmt = pg_insert(CompetitionFixture).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_cf_competition_external_id",
        set_={
            "status":    stmt.excluded.status,
            "home_score": stmt.excluded.home_score,
            "away_score": stmt.excluded.away_score,
            "match_utc": stmt.excluded.match_utc,
            "fixture_round": stmt.excluded.fixture_round,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    await db.execute(stmt)
    await db.commit()
    logger.info(f"[comp_fixtures] {comp_label}: upserted {len(rows)} fixtures")
    return len(rows)


# ── Orchestrator ─────────────────────────────────────────────────────────

async def run_competition_sync(db: AsyncSession, http: Optional[httpx.AsyncClient] = None) -> dict:
    """
    Full sync: PL always, UCL/UEL/FAC if FOOTBALL_DATA_API_KEY is set.

    Returns summary dict:
        {"PL": 380, "UCL": 125, "FAC": 64, ...}
    """
    api_key = os.getenv("FOOTBALL_DATA_API_KEY", "")
    own_client = http is None
    if own_client:
        http = httpx.AsyncClient(timeout=25.0)

    try:
        await _load_fpl_team_map(http)
        results: dict = {}

        # Always sync PL
        results["PL"] = await _sync_pl_fixtures(db, http)

        # Sync other competitions if key available
        if api_key:
            for comp_label, fdorg_code in _FDORG_COMPETITIONS.items():
                results[comp_label] = await _sync_fdorg_competition(
                    db, http, comp_label, fdorg_code, api_key
                )
        else:
            logger.info("[comp_fixtures] FOOTBALL_DATA_API_KEY not set — skipping UCL/UEL/FAC sync")

        logger.info(f"[comp_fixtures] Sync complete: {results}")
        return results
    finally:
        if own_client:
            await http.aclose()


# ── Prediction helpers ────────────────────────────────────────────────────

async def get_team_upcoming_fixtures(
    fpl_team_id: int,
    db: AsyncSession,
    within_days: int = 10,
) -> List[CompetitionFixture]:
    """
    Return all upcoming fixtures for a team across all competitions,
    within the next `within_days` days.
    """
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=within_days)

    result = await db.execute(
        select(CompetitionFixture).where(
            (
                (CompetitionFixture.home_fpl_team_id == fpl_team_id) |
                (CompetitionFixture.away_fpl_team_id == fpl_team_id)
            ),
            CompetitionFixture.match_utc >= now,
            CompetitionFixture.match_utc <= cutoff,
            CompetitionFixture.status.not_in(["FINISHED", "CANCELLED", "POSTPONED"]),
        ).order_by(CompetitionFixture.match_utc)
    )
    return result.scalars().all()


async def compute_rotation_risk_boost(
    fpl_team_id: int,
    next_pl_kickoff: Optional[datetime],
    db: AsyncSession,
) -> float:
    """
    Returns a rotation risk boost (0.0–1.0) based on fixture congestion.

    Logic:
    - +0.35 if team has a UCL/UEL fixture within 3 days before/after the PL game
    - +0.20 if team has a FAC/CC fixture in the same window
    - +0.15 additional if the cup fixture is a knockout round (semi/final)
    - +0.10 if there are 3+ games in the next 7 days (general congestion)
    """
    if fpl_team_id is None:
        return 0.0

    try:
        upcoming = await get_team_upcoming_fixtures(fpl_team_id, db, within_days=10)
    except Exception:
        return 0.0

    if not upcoming:
        return 0.0

    boost = 0.0
    now = datetime.now(timezone.utc)
    window_7d = now + timedelta(days=7)

    # Count games in next 7 days (congestion)
    games_7d = [f for f in upcoming if f.match_utc and f.match_utc <= window_7d]
    if len(games_7d) >= 3:
        boost += 0.10

    if next_pl_kickoff is None:
        # Fall back to proximity-based check only
        non_pl = [f for f in upcoming if f.competition != "PL"]
        if non_pl:
            boost += 0.20
        return min(boost, 1.0)

    # Check for non-PL fixtures within 3 days of PL kickoff
    window_start = next_pl_kickoff - timedelta(days=3)
    window_end   = next_pl_kickoff + timedelta(days=3)

    for fix in upcoming:
        if fix.competition == "PL":
            continue
        if fix.match_utc and window_start <= fix.match_utc <= window_end:
            if fix.competition in ("UCL", "UEL"):
                boost += 0.35
            else:
                boost += 0.20
            # Extra boost for knockout rounds (more rotation in non-knockout rounds)
            if fix.fixture_round and any(
                kw in fix.fixture_round.lower() for kw in _KNOCKOUT_LABELS
            ):
                boost += 0.15  # Knockout = key players likely to START → actually LESS rotation
                # (teams go strong in knockouts — slightly offset the rotation penalty)
                boost -= 0.10

    return min(boost, 1.0)


async def get_fixture_congestion_scores(
    fpl_team_ids: List[int],
    db: AsyncSession,
) -> Dict[int, float]:
    """
    Batch compute rotation risk boosts for a list of FPL team IDs.
    Returns {fpl_team_id: boost_score}.
    """
    scores: Dict[int, float] = {}
    for tid in fpl_team_ids:
        scores[tid] = await compute_rotation_risk_boost(tid, None, db)
    return scores
