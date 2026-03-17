"""Optimization routes — ILP squad optimization, captain ranking, chip recommendations."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from api.deps import get_db_session, get_team_context
from core.config import settings
from core.exceptions import OptimizationError
from models.db.player import Player
from models.db.user_squad import UserSquad, UserBank
from models.db.gameweek import Gameweek
from models.db.team import Team as TeamModel
from optimizers.squad_optimizer import SquadOptimizer
from optimizers.captain_engine import CaptainEngine
from optimizers.chip_engine import ChipEngine
from optimizers.lineup_simulator import lineup_simulator, SquadPlayerInput
from optimizers.probabilistic_sim import simulator as prob_simulator, PlayerSimInput
from services.cache_service import ANALYSIS_TTL, get_cached_payload, set_cached_payload
from services.decision_engine import decision_engine, DecisionContext

router = APIRouter()
squad_optimizer = SquadOptimizer()
captain_engine = CaptainEngine()
chip_engine = ChipEngine(n_simulations=10_000)


@router.get("/squad")
async def optimize_full_squad(
    team_context: dict = Depends(get_team_context),
    db: AsyncSession = Depends(get_db_session),
):
    """ILP-optimized full squad suggestion."""
    active_team_id = team_context["team_id"]
    session = team_context.get("session")
    cached = await get_cached_payload("optimization_squad", active_team_id, session.session_token if session else "registered")
    if cached:
        cached["analysis_mode"] = "cached"
        return cached

    result = await db.execute(select(Gameweek).where(Gameweek.is_current == True))
    current_gw = result.scalar_one_or_none()

    # Get bank state
    result = await db.execute(select(UserBank).where(UserBank.team_id == active_team_id))
    bank = result.scalar_one_or_none()
    free_transfers = bank.free_transfers if bank else 1
    bank_pence = bank.bank if bank else 0

    # Get existing squad for transfer penalty calculation.
    # Fall back to most recent GW if current GW has no data (GW boundary).
    existing_squad = []
    if current_gw and bank:
        result = await db.execute(
            select(UserSquad).where(
                UserSquad.team_id == active_team_id,
                UserSquad.gameweek_id == current_gw.id,
            )
        )
        picks = result.scalars().all()
        if not picks:
            from sqlalchemy import desc as _desc
            fb = await db.execute(
                select(UserSquad)
                .where(UserSquad.team_id == active_team_id)
                .order_by(_desc(UserSquad.gameweek_id))
                .limit(15)
            )
            picks = fb.scalars().all()
        existing_squad = [p.player_id for p in picks]

    # Build budget: team value + bank (can't exceed £100m for full squad rebuild)
    budget = min(1000, (bank.value if bank else 1000) + bank_pence)

    # Get all available players
    result = await db.execute(select(Player).where(Player.status != "u"))
    players = result.scalars().all()

    import pandas as pd
    df = pd.DataFrame([{
        "id": p.id,
        "web_name": p.web_name,
        "element_type": p.element_type,
        "team_id": p.team_id,
        "now_cost": p.now_cost,
        "predicted_xpts_next": max(0, p.predicted_xpts_next),
        "has_blank_gw": p.has_blank_gw,
        "selected_by_percent": p.selected_by_percent,
        "fdr_next": p.fdr_next,
        "is_home_next": p.is_home_next,
    } for p in players if p.now_cost > 0])

    try:
        result = squad_optimizer.optimize_squad(
            players_df=df,
            budget=budget,
            existing_squad=existing_squad or None,
            free_transfers=free_transfers,
        )

        # Enrich result with player details
        player_map = {p.id: p for p in players}

        def enrich(ids):
            return [
                {
                    "id": pid,
                    "web_name": player_map[pid].web_name if pid in player_map else str(pid),
                    "element_type": player_map[pid].element_type if pid in player_map else 0,
                    "now_cost": player_map[pid].now_cost if pid in player_map else 0,
                    "predicted_xpts_next": player_map[pid].predicted_xpts_next if pid in player_map else 0,
                    "team_id": player_map[pid].team_id if pid in player_map else 0,
                }
                for pid in ids
            ]

        payload = {
            "formation": result.formation,
            "total_xpts": result.total_xpts,
            "budget_used_millions": result.budget_used / 10,
            "solver_status": result.solver_status,
            "transfers_needed": result.transfers_needed,
            "point_deduction": result.point_deduction,
            "captain_id": result.captain_id,
            "vice_captain_id": result.vice_captain_id,
            "starting_xi": enrich(result.starting_xi),
            "bench": enrich(result.bench),
            "analysis_mode": "full",
            "session_expires_at": session.expires_at.isoformat() if session else None,
        }
        await set_cached_payload("optimization_squad", payload, ANALYSIS_TTL, active_team_id, session.session_token if session else "registered")
        return payload
    except OptimizationError as e:
        if cached:
            cached["analysis_mode"] = "degraded"
            cached["warning"] = "Advanced analysis temporarily unavailable"
            return cached
        raise HTTPException(422, str(e))


@router.get("/captain")
async def get_captain_recommendations(
    team_context: dict = Depends(get_team_context),
    db: AsyncSession = Depends(get_db_session),
):
    """Ranked captain candidates from current starting XI."""
    active_team_id = team_context["team_id"]
    session = team_context.get("session")
    cached = await get_cached_payload("captain_candidates", active_team_id, session.session_token if session else "registered")
    if cached:
        cached["analysis_mode"] = "cached"
        return cached

    result = await db.execute(select(Gameweek).where(Gameweek.is_current == True))
    current_gw = result.scalar_one_or_none()
    if not current_gw:
        raise HTTPException(404, "No current gameweek")

    result = await db.execute(
        select(UserSquad, Player)
        .join(Player, UserSquad.player_id == Player.id)
        .where(
            UserSquad.team_id == active_team_id,
            UserSquad.gameweek_id == current_gw.id,
            UserSquad.position <= 11,  # Starting XI only
        )
    )
    xi_picks = result.all()
    if not xi_picks:
        # GW boundary fallback: use most recent synced squad
        from sqlalchemy import desc as _desc
        sub = (
            select(UserSquad.gameweek_id)
            .where(UserSquad.team_id == active_team_id)
            .order_by(_desc(UserSquad.gameweek_id))
            .limit(1)
            .scalar_subquery()
        )
        result = await db.execute(
            select(UserSquad, Player)
            .join(Player, UserSquad.player_id == Player.id)
            .where(UserSquad.team_id == active_team_id, UserSquad.gameweek_id == sub, UserSquad.position <= 11)
        )
        xi_picks = result.all()
    if not xi_picks:
        raise HTTPException(404, "No squad data. Visit the Squad tab first to sync your team.")

    xi_ids = [pick.UserSquad.player_id for pick in xi_picks]
    # Build team_id → Team mapping for badge display
    all_team_ids = list({p.Player.team_id for p in xi_picks if p.Player.team_id})
    team_rows = await db.execute(select(TeamModel).where(TeamModel.id.in_(all_team_ids)))
    team_map = {t.id: t for t in team_rows.scalars().all()}
    team_info_map = {
        p.Player.id: {
            "team_code": team_map.get(p.Player.team_id, None) and team_map[p.Player.team_id].code,
            "team_short_name": team_map.get(p.Player.team_id, None) and team_map[p.Player.team_id].short_name,
        }
        for p in xi_picks
    }
    import pandas as pd
    df = pd.DataFrame([{
        "id": p.Player.id,
        "web_name": p.Player.web_name,
        "element_type": p.Player.element_type,
        "predicted_xpts_next": p.Player.predicted_xpts_next,
        "fdr_next": p.Player.fdr_next,
        "is_home_next": p.Player.is_home_next,
        "selected_by_percent": p.Player.selected_by_percent,
        "has_double_gw": p.Player.has_double_gw,
    } for p in xi_picks])

    candidates = captain_engine.rank_candidates(xi_ids, df, xi_ids)
    synthesized_candidates = decision_engine.synthesize_captain_candidates(
        [
            {
                "player_id": c.player_id,
                "web_name": c.web_name,
                "captain_score": c.captain_score,
                "score": c.captain_score,
                "xpts": c.xpts,
                "predicted_xpts_next": c.xpts,
                "fdr_next": c.fdr_next,
                "is_home": c.is_home,
                "is_home_next": c.is_home,
                "ownership": c.ownership,
                "selected_by_percent": c.ownership,
                "has_double_gw": c.has_double_gw,
                "is_differential": c.is_differential,
                "reasoning": c.reasoning,
                "team_code": team_info_map.get(c.player_id, {}).get("team_code"),
                "team_short_name": team_info_map.get(c.player_id, {}).get("team_short_name"),
            }
            for c in candidates[:8]
        ],
        context=DecisionContext(
            recommendation_type="captain",
            risk_preference=settings.DEFAULT_RISK_PROFILE,
            current_gameweek=current_gw.id,
            team_id=active_team_id,
        ),
    )
    selected_candidates = synthesized_candidates if decision_engine.should_replace_live_output(active_team_id) else [
        {
            "player_id": c.player_id,
            "web_name": c.web_name,
            "captain_score": c.captain_score,
            "xpts": c.xpts,
            "predicted_xpts_next": c.xpts,
            "fdr_next": c.fdr_next,
            "is_home": c.is_home,
            "ownership": c.ownership,
            "has_double_gw": c.has_double_gw,
            "is_differential": c.is_differential,
            "reasoning": c.reasoning,
            "team_code": team_info_map.get(c.player_id, {}).get("team_code"),
            "team_short_name": team_info_map.get(c.player_id, {}).get("team_short_name"),
        }
        for c in candidates[:8]
    ]

    payload = {
        "gameweek": current_gw.id,
        "candidates": selected_candidates,
        "analysis_mode": "full",
        "decision_engine_mode": settings.DECISION_ENGINE_MODE,
        "session_expires_at": session.expires_at.isoformat() if session else None,
    }
    if decision_engine.should_emit_shadow():
        payload["decision_engine_shadow"] = decision_engine.build_shadow_payload(
            current=[
                {
                    "web_name": c.web_name,
                    "captain_score": c.captain_score,
                }
                for c in candidates[:8]
            ],
            synthesized=synthesized_candidates,
            label="captain",
        )
    await set_cached_payload("captain_candidates", payload, ANALYSIS_TTL, active_team_id, session.session_token if session else "registered")
    return payload


@router.get("/chips")
async def get_chip_recommendations(
    team_id: int | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    """Monte Carlo chip timing recommendations."""
    active_team_id = team_id or settings.FPL_TEAM_ID

    result = await db.execute(select(Gameweek).where(Gameweek.is_current == True))
    current_gw = result.scalar_one_or_none()
    if not current_gw:
        raise HTTPException(404, "No current gameweek")

    result = await db.execute(select(UserBank).where(UserBank.team_id == active_team_id))
    bank = result.scalar_one_or_none()

    gw = current_gw.id
    half = "first" if gw <= 18 else "second"

    chips_available = {
        "wildcard": bank.chip_available("wildcard", gw) if bank else True,
        "free_hit": bank.chip_available("free_hit", gw) if bank else True,
        "bench_boost": bank.chip_available("bench_boost", gw) if bank else True,
        "triple_captain": bank.chip_available("triple_captain", gw) if bank else True,
    } if bank else {"wildcard": True, "free_hit": True, "bench_boost": True, "triple_captain": True}

    # Count blanking starters
    result = await db.execute(
        select(UserSquad, Player)
        .join(Player, UserSquad.player_id == Player.id)
        .where(
            UserSquad.team_id == active_team_id,
            UserSquad.gameweek_id == gw,
            UserSquad.position <= 11,
        )
    )
    xi_picks = result.all()
    squad_blank_count = sum(1 for p in xi_picks if p.Player.has_blank_gw)

    import numpy as np
    recs = chip_engine.get_all_recommendations(
        chips_available=chips_available,
        current_gw=gw,
        half=half,
        squad_blank_count=squad_blank_count,
    )

    return {
        "current_gw": gw,
        "current_half": half,
        "chips_available": chips_available,
        "squad_blank_count": squad_blank_count,
        "recommendations": [
            {
                "chip": r.chip,
                "recommended_gw": r.recommended_gw,
                "confidence": r.confidence,
                "expected_gain": r.expected_gain,
                "reasoning": r.reasoning,
                "urgency": r.urgency,
            }
            for r in recs
        ],
    }


@router.get("/lineup-simulator")
async def simulate_lineup(
    team_id: int | None = None,
    n_sims: int = Query(2000, ge=500, le=5000),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Monte Carlo lineup probability simulator.
    Runs n_sims trials sampling which players start based on P(start).
    Returns P(in_XI) per player and expected XI xPts under uncertainty.
    """
    active_team_id = team_id or settings.FPL_TEAM_ID

    result = await db.execute(select(Gameweek).where(Gameweek.is_current == True))
    current_gw = result.scalar_one_or_none()
    if not current_gw:
        raise HTTPException(404, "No current gameweek")

    result = await db.execute(
        select(UserSquad, Player)
        .join(Player, UserSquad.player_id == Player.id)
        .where(
            UserSquad.team_id == active_team_id,
            UserSquad.gameweek_id == current_gw.id,
        )
        .order_by(UserSquad.position)
    )
    picks = result.all()

    if not picks:
        raise HTTPException(404, "No squad found. Run /api/squad/sync first.")

    squad_inputs = [
        SquadPlayerInput(
            player_id=p.Player.id,
            web_name=p.Player.web_name,
            position=p.UserSquad.position,
            element_type=p.Player.element_type,
            xpts=max(0.0, p.Player.predicted_xpts_next or 0.0),
            p_start=max(0.0, min(1.0, p.Player.predicted_start_prob or 0.7)),
            is_bench=p.UserSquad.position > 11,
        )
        for p in picks
    ]

    # Use custom n_sims if provided
    from optimizers.lineup_simulator import LineupSimulator
    sim = LineupSimulator(n_sims=n_sims)
    result_data = sim.simulate(squad_inputs)

    return {
        "gameweek": current_gw.id,
        "team_id": active_team_id,
        "n_simulations": n_sims,
        **result_data,
    }


@router.get("/probabilistic")
async def get_probabilistic_predictions(
    team_id: int | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    """
    Monte Carlo probability distribution for each squad player.
    Returns P(blank), P(5+pts), P(10+pts), percentiles, and rank volatility.
    """
    active_team_id = team_id or settings.FPL_TEAM_ID

    result = await db.execute(select(Gameweek).where(Gameweek.is_current == True))
    current_gw = result.scalar_one_or_none()
    if not current_gw:
        raise HTTPException(404, "No current gameweek")

    result = await db.execute(
        select(UserSquad, Player)
        .join(Player, UserSquad.player_id == Player.id)
        .where(
            UserSquad.team_id == active_team_id,
            UserSquad.gameweek_id == current_gw.id,
        )
        .order_by(UserSquad.position)
    )
    picks = result.all()

    if not picks:
        raise HTTPException(404, "No squad found. Run /api/squad/sync first.")

    sim_inputs = [
        PlayerSimInput(
            player_id=p.Player.id,
            web_name=p.Player.web_name,
            xpts=max(0.0, p.Player.predicted_xpts_next or 0.0),
            p_start=max(0.0, min(1.0, p.Player.predicted_start_prob or 0.7)),
            selected_by_percent=float(p.Player.selected_by_percent or 0),
            element_type=p.Player.element_type,
            is_captain=p.UserSquad.is_captain,
        )
        for p in picks
    ]

    sim_results = prob_simulator.simulate_players(sim_inputs)
    team_totals = prob_simulator.simulate_team_total(sim_inputs)

    return {
        "gameweek": current_gw.id,
        "team_id": active_team_id,
        "players": [
            {
                "player_id": r.player_id,
                "web_name": r.web_name,
                "mean_xpts": r.mean_xpts,
                "std_xpts": r.std_xpts,
                "prob_blank": r.prob_blank,
                "prob_5_plus": r.prob_5_plus,
                "prob_10_plus": r.prob_10_plus,
                "p10": r.p10,
                "p25": r.p25,
                "p50": r.p50,
                "p75": r.p75,
                "p90": r.p90,
                "rank_volatility_score": r.rank_volatility_score,
                "captain_ev": r.captain_ev,
                "upside_score": r.upside_score,
            }
            for r in sim_results
        ],
        "team_totals": team_totals,
    }
