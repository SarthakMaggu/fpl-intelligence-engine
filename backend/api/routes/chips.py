"""Chip status, history, and Monte Carlo recommendation routes."""
import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from api.deps import get_db_session
from core.config import settings
from core.redis_client import redis_client
from models.db.user_squad import UserSquad, UserBank
from models.db.gameweek import Gameweek
from models.db.player import Player

router = APIRouter()

CHIP_NAMES = ["wildcard", "free_hit", "bench_boost", "triple_captain"]

HALF_1_GW_RANGE = (1, 18)
HALF_2_GW_RANGE = (20, 38)


@router.get("/status")
async def get_chip_status(
    team_id: int | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    """
    Returns chip availability per half for the 2025/26 season.
    Each chip is available once in GW1-18 and once in GW20-38.
    """
    active_team_id = team_id or settings.FPL_TEAM_ID

    result = await db.execute(select(UserBank).where(UserBank.team_id == active_team_id))
    bank = result.scalar_one_or_none()
    if not bank:
        raise HTTPException(404, "Team bank data not found. Run /api/squad/sync first.")

    result = await db.execute(select(Gameweek).where(Gameweek.is_current == True))
    current_gw = result.scalar_one_or_none()
    current_gw_id = current_gw.id if current_gw else 1

    current_half = 1 if current_gw_id <= 18 else 2

    chips_status = {}
    for chip in CHIP_NAMES:
        gw_used_h1 = getattr(bank, f"{chip}_1_used_gw", None)
        gw_used_h2 = getattr(bank, f"{chip}_2_used_gw", None)

        chips_status[chip] = {
            "half_1": {
                "available": gw_used_h1 is None and current_gw_id <= 19,
                "used_gw": gw_used_h1,
            },
            "half_2": {
                "available": gw_used_h2 is None and current_gw_id >= 20,
                "used_gw": gw_used_h2,
            },
            "available_now": bank.chip_available(chip, current_gw_id),
            "current_half": current_half,
        }

    return {
        "team_id": active_team_id,
        "current_gw": current_gw_id,
        "current_half": current_half,
        "chips": chips_status,
    }


@router.get("/active")
async def get_active_chip(
    team_id: int | None = None,
):
    """
    Returns the chip played in the latest GW for this team, sourced from Redis.
    Cached by run_full_pipeline() at key fpl:chip:active:{team_id} (2h TTL).

    Response:
      { "team_id": int, "chip": str | null, "gameweek": int | null }
    """
    active_team_id = team_id or settings.FPL_TEAM_ID
    if not active_team_id:
        raise HTTPException(400, "No team_id provided and FPL_TEAM_ID not configured.")

    chip_redis_key = f"fpl:chip:active:{active_team_id}"
    raw = await redis_client.get(chip_redis_key)

    if not raw:
        return {"team_id": active_team_id, "chip": None, "gameweek": None}

    # Stored as "chip_name:gw_id"  e.g. "triple_captain:29"
    try:
        parts = raw.decode() if isinstance(raw, bytes) else raw
        chip_name, gw_str = parts.split(":", 1)
        return {
            "team_id": active_team_id,
            "chip": chip_name,
            "gameweek": int(gw_str),
        }
    except Exception:
        # Malformed cache value — return None gracefully
        return {"team_id": active_team_id, "chip": None, "gameweek": None}


@router.get("/history")
async def get_chip_history(
    team_id: int | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    """Returns a timeline of when each chip was used."""
    active_team_id = team_id or settings.FPL_TEAM_ID

    result = await db.execute(select(UserBank).where(UserBank.team_id == active_team_id))
    bank = result.scalar_one_or_none()
    if not bank:
        raise HTTPException(404, "Team bank data not found.")

    history = []
    for chip in CHIP_NAMES:
        for half in [1, 2]:
            used_gw = getattr(bank, f"{chip}_{half}_used_gw", None)
            if used_gw is not None:
                history.append({
                    "chip": chip,
                    "half": half,
                    "gameweek": used_gw,
                })

    history.sort(key=lambda x: (x["gameweek"] or 0))
    return {"team_id": active_team_id, "chip_history": history}


@router.get("/recommendations")
async def get_chip_recommendations(
    team_id: int | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    """Monte Carlo chip timing recommendations using the ChipEngine."""
    from optimizers.chip_engine import ChipEngine

    active_team_id = team_id or settings.FPL_TEAM_ID

    # --- Load bank / chip availability ---
    result = await db.execute(select(UserBank).where(UserBank.team_id == active_team_id))
    bank = result.scalar_one_or_none()
    if not bank:
        raise HTTPException(404, "Team bank data not found. Run /api/squad/sync first.")

    result = await db.execute(select(Gameweek).where(Gameweek.is_current == True))
    current_gw = result.scalar_one_or_none()
    if not current_gw:
        raise HTTPException(404, "No active gameweek found.")

    current_gw_id: int = current_gw.id

    # When between GWs, use the upcoming GW number for chip planning
    display_gw_id = current_gw_id
    if current_gw.finished:
        next_result = await db.execute(select(Gameweek).where(Gameweek.is_next == True))
        next_gw = next_result.scalar_one_or_none()
        if next_gw:
            display_gw_id = next_gw.id

    half = bank.get_current_half(display_gw_id)  # "first" | "second"
    n_remaining = max(1, 38 - display_gw_id + 1)

    # --- Load squad picks (always stored under current_gw_id) ---
    squad_result = await db.execute(
        select(UserSquad).where(
            UserSquad.team_id == active_team_id,
            UserSquad.gameweek_id == current_gw_id,
        )
    )
    squad_picks = squad_result.scalars().all()

    if not squad_picks:
        return {
            "gameweek": current_gw_id,
            "message": "No squad data. Run /api/squad/sync first.",
            "recommendations": {},
        }

    bench_player_ids = {p.player_id for p in squad_picks if p.position > 11}
    starting_player_ids = {p.player_id for p in squad_picks if p.position <= 11}

    # --- Load player xpts for squad members ---
    all_squad_ids = {p.player_id for p in squad_picks}
    result = await db.execute(
        select(Player).where(Player.id.in_(all_squad_ids))
    )
    squad_players = {p.id: p for p in result.scalars().all()}

    # --- Load top players globally for wildcard comparison ---
    result = await db.execute(
        select(Player)
        .where(Player.predicted_xpts_next.isnot(None))
        .order_by(Player.predicted_xpts_next.desc())
        .limit(100)
    )
    top_players = result.scalars().all()

    # --- Build numpy arrays for ChipEngine ---
    engine = ChipEngine(n_simulations=5_000)

    chips_available = {
        chip: bank.chip_available(chip, display_gw_id) for chip in CHIP_NAMES
    }

    recommendations: dict = {}

    # ── Bench Boost ────────────────────────────────────────────────────────────
    if chips_available.get("bench_boost"):
        bench_players = [
            squad_players[pid]
            for pid in bench_player_ids
            if pid in squad_players
        ]
        if bench_players:
            # Shape: (n_remaining_gws, n_bench=4)  — repeat single-GW prediction
            bench_xpts = np.array([
                p.predicted_xpts_next or 0.0 for p in bench_players
            ])
            # Pad to 4 bench slots if fewer players
            bench_xpts = np.pad(bench_xpts, (0, max(0, 4 - len(bench_xpts))))[:4]
            # Tile across remaining GWs: (n_remaining, 4)
            bench_matrix = np.tile(bench_xpts, (n_remaining, 1))

            bb_rec = engine.recommend_bench_boost(
                bench_xpts_by_gw=bench_matrix,
                current_gw=display_gw_id,
                half=half,
                available=True,
            )
            if bb_rec:
                recommendations["bench_boost"] = _rec_to_dict(bb_rec)

    # ── Triple Captain ─────────────────────────────────────────────────────────
    if chips_available.get("triple_captain"):
        starters = [
            squad_players[pid]
            for pid in starting_player_ids
            if pid in squad_players and squad_players[pid].predicted_xpts_next
        ]
        if starters:
            best_captain = max(starters, key=lambda p: p.predicted_xpts_next or 0)

            # Fetch upcoming GWs for fixture info
            upcoming_result = await db.execute(
                select(Gameweek)
                .where(Gameweek.id >= display_gw_id)
                .order_by(Gameweek.id)
                .limit(n_remaining)
            )
            upcoming_gws = upcoming_result.scalars().all()

            # Build per-GW arrays — we only have static predictions so repeat
            cap_xpts_by_gw = np.full(
                n_remaining,
                best_captain.predicted_xpts_next or 0.0,
            )
            fdr_by_gw = np.full(
                n_remaining,
                float(best_captain.fdr_next or 3),
            )
            is_double_gw = np.array(
                [bool(best_captain.has_double_gw)] + [False] * (n_remaining - 1),
                dtype=bool,
            )

            tc_rec = engine.recommend_triple_captain(
                captain_xpts_by_gw=cap_xpts_by_gw,
                fdr_by_gw=fdr_by_gw,
                is_double_gw=is_double_gw,
                current_gw=display_gw_id,
                half=half,
                available=True,
            )
            if tc_rec:
                rec_dict = _rec_to_dict(tc_rec)
                rec_dict["suggested_captain"] = best_captain.web_name
                recommendations["triple_captain"] = rec_dict

    # ── Wildcard ───────────────────────────────────────────────────────────────
    if chips_available.get("wildcard"):
        # Current squad expected points over next 5 GWs (approximation: 5× next-GW xpts)
        current_squad_xpts_5gw = sum(
            (squad_players[pid].predicted_xpts_next or 0) * 5
            for pid in starting_player_ids
            if pid in squad_players
        )
        # Optimal squad: top players by xpts, respecting 15-player budget
        optimal_xpts_5gw = sum(
            (p.predicted_xpts_next or 0) * 5 for p in top_players[:11]
        )

        wc_rec = engine.recommend_wildcard(
            current_squad_xpts_5gw=current_squad_xpts_5gw,
            optimal_squad_xpts_5gw=optimal_xpts_5gw,
            current_gw=display_gw_id,
            half=half,
            available=True,
        )
        if wc_rec:
            recommendations["wildcard"] = _rec_to_dict(wc_rec)

    # ── Free Hit ───────────────────────────────────────────────────────────────
    if chips_available.get("free_hit"):
        blank_count = sum(
            1
            for pid in starting_player_ids
            if pid in squad_players and squad_players[pid].has_blank_gw
        )
        fh_rec = engine.recommend_free_hit(
            squad_blank_count=blank_count,
            current_gw=display_gw_id,
            half=half,
            available=True,
        )
        if fh_rec:
            recommendations["free_hit"] = _rec_to_dict(fh_rec)

    return {
        "gameweek": display_gw_id,
        "chips_available": chips_available,
        "recommendations": recommendations,
    }


def _rec_to_dict(rec) -> dict:
    """Convert ChipRecommendation dataclass to JSON-serialisable dict."""
    return {
        "chip": rec.chip,
        "recommended_gw": rec.recommended_gw,
        "confidence": rec.confidence,
        "expected_gain": rec.expected_gain,
        "reasoning": rec.reasoning,
        "urgency": rec.urgency,
    }
