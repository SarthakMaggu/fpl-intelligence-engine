"""GW Intelligence routes — fixture swings, yellow cards, full GW brief."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text, and_
from datetime import datetime

from api.deps import get_db_session, get_team_context
from core.config import settings
from models.db.player import Player
from models.db.gameweek import Gameweek, Fixture
from models.db.user_squad import UserSquad, UserBank
from models.db.decision_log import DecisionLog
from services.cache_service import ANALYSIS_TTL, FIXTURE_TTL, get_cached_payload, set_cached_payload
from services.decision_engine import decision_engine, DecisionContext

router = APIRouter()


@router.get("/gw")
async def get_gw_intelligence(
    team_context: dict = Depends(get_team_context),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Full GW intelligence card: transfer suggestion, captain pick,
    chip advice, injury alerts, suspension risk, fixture swings.
    """
    from optimizers.captain_engine import CaptainEngine
    from optimizers.transfer_engine import TransferEngine

    active_team_id = team_context["team_id"]
    session = team_context.get("session")
    cached = await get_cached_payload("gw_intel", active_team_id, session.session_token if session else "registered")
    if cached:
        cached["analysis_mode"] = "cached"
        return cached

    result = await db.execute(select(Gameweek).where(Gameweek.is_current == True))
    current_gw = result.scalar_one_or_none()
    if not current_gw:
        raise HTTPException(404, "No active gameweek")

    # When between GWs, display the upcoming GW number and deadline
    display_gw = current_gw
    if current_gw.finished:
        next_result = await db.execute(select(Gameweek).where(Gameweek.is_next == True))
        next_gw = next_result.scalar_one_or_none()
        if next_gw:
            display_gw = next_gw

    # Fetch squad (always keyed to current_gw in DB)
    result = await db.execute(
        select(UserSquad).where(
            UserSquad.team_id == active_team_id,
            UserSquad.gameweek_id == current_gw.id,
        )
    )
    picks = result.scalars().all()

    squad_player_ids = {p.player_id for p in picks}
    squad_players = []
    for pick in picks:
        player = await db.get(Player, pick.player_id)
        if player:
            squad_players.append(player)

    # Team lookup for badge enrichment
    from models.db.team import Team as TeamModel
    team_res = await db.execute(select(TeamModel))
    team_map = {t.id: t for t in team_res.scalars().all()}

    def _team_code(tid: int | None) -> int | None:
        if not tid:
            return None
        t = team_map.get(tid)
        return t.code if t else None

    def _team_short(tid: int | None) -> str | None:
        if not tid:
            return None
        t = team_map.get(tid)
        return t.short_name if t else None

    # Captain recommendation
    captain_engine = CaptainEngine()
    captain_candidates = captain_engine.rank_captains(
        [
            {
                "player_id": p.id,
                "web_name": p.web_name,
                "element_type": p.element_type,
                "predicted_xpts_next": p.predicted_xpts_next or 0,
                "fdr_next": p.fdr_next or 3,
                "is_home_next": p.is_home_next or False,
                "has_double_gw": p.has_double_gw or False,
                "has_blank_gw": p.has_blank_gw or False,
                "selected_by_percent": float(p.selected_by_percent or 0),
                "team_code": _team_code(p.team_id),
                "team_short_name": _team_short(p.team_id),
            }
            for p in squad_players
            if p.element_type != 1  # No GK captain
        ]
    )
    synthesized_captains = decision_engine.synthesize_captain_candidates(
        captain_candidates,
        context=DecisionContext(
            recommendation_type="captain",
            risk_preference=settings.DEFAULT_RISK_PROFILE,
            current_gameweek=display_gw.id,
            team_id=active_team_id,
        ),
    ) if captain_candidates else []
    top_captain = (
        synthesized_captains[0]
        if synthesized_captains and decision_engine.should_replace_live_output(active_team_id)
        else captain_candidates[0] if captain_candidates else None
    )

    # Injury alerts in squad
    injury_alerts = [
        {
            "player_id": p.id,
            "web_name": p.web_name,
            "status": p.status,
            "news": p.news,
            "chance_of_playing": p.chance_of_playing_next_round,
            "team_code": _team_code(p.team_id),
            "team_short_name": _team_short(p.team_id),
        }
        for p in squad_players
        if p.status in ("d", "i", "s", "u") or (p.chance_of_playing_next_round is not None and p.chance_of_playing_next_round < 75)
    ]

    # Suspension risk
    suspension_alerts = [
        {
            "player_id": p.id,
            "web_name": p.web_name,
            "yellow_cards": p.yellow_cards,
            "team_code": _team_code(p.team_id),
        }
        for p in squad_players
        if p.suspension_risk
    ]

    # Blank GW starters
    blank_starters = [
        {
            "player_id": p.id,
            "web_name": p.web_name,
            "team_code": _team_code(p.team_id),
        }
        for p in squad_players
        if p.has_blank_gw
    ]

    # Double GW players
    double_players = [
        {
            "player_id": p.id,
            "web_name": p.web_name,
            "predicted_xpts_next": p.predicted_xpts_next,
            "team_code": _team_code(p.team_id),
            "team_short_name": _team_short(p.team_id),
        }
        for p in squad_players
        if p.has_double_gw
    ]

    # ── Free transfers + 0-FT advice ─────────────────────────────────────────
    bank_res = await db.execute(
        select(UserBank).where(UserBank.team_id == active_team_id)
    )
    bank = bank_res.scalar_one_or_none()
    free_transfers = bank.free_transfers if bank else 1

    zero_ft_advice = None
    if free_transfers == 0 and squad_players:
        pick_map = {p.player_id: p for p in picks}

        starters = [p for p in squad_players if pick_map.get(p.id) and pick_map[p.id].position <= 11]
        bench    = [p for p in squad_players if pick_map.get(p.id) and pick_map[p.id].position >= 12]

        # Bench-to-XI swaps: bench player with better xPts than worst starter of same type
        bench_swaps = []
        for b in bench:
            b_xpts = b.predicted_xpts_next or 0
            if b_xpts <= 0:
                continue
            same_pos_starters = [s for s in starters if s.element_type == b.element_type]
            if not same_pos_starters:
                continue
            worst = min(same_pos_starters, key=lambda s: s.predicted_xpts_next or 0)
            w_xpts = worst.predicted_xpts_next or 0
            if b_xpts > w_xpts + 0.5:
                bench_swaps.append({
                    "out": {
                        "player_id": worst.id,
                        "web_name": worst.web_name,
                        "xpts": round(w_xpts, 2),
                        "element_type": worst.element_type,
                        "team_code": _team_code(worst.team_id),
                    },
                    "in": {
                        "player_id": b.id,
                        "web_name": b.web_name,
                        "xpts": round(b_xpts, 2),
                        "element_type": b.element_type,
                        "team_code": _team_code(b.team_id),
                    },
                    "gain": round(b_xpts - w_xpts, 2),
                })
        bench_swaps.sort(key=lambda x: -x["gain"])

        # Optimal XI from current 15 (greedy valid selection)
        from optimizers.lineup_simulator import LineupSimulator, SquadPlayerInput
        sim_inputs = [
            SquadPlayerInput(
                player_id=p.id,
                web_name=p.web_name,
                position=pick_map[p.id].position,
                element_type=p.element_type,
                xpts=p.predicted_xpts_next or 0,
                is_bench=pick_map[p.id].position >= 12,
            )
            for p in squad_players if pick_map.get(p.id)
        ]
        _sim = LineupSimulator(n_sims=1, seed=0)
        optimal_xi_players = _sim._best_valid_xi(sim_inputs)
        ilp_optimal_xi = [
            {
                "player_id": p.player_id,
                "web_name": p.web_name,
                "element_type": p.element_type,
                "xpts": round(p.xpts, 2),
            }
            for p in sorted(optimal_xi_players, key=lambda x: (x.element_type, -x.xpts))
        ]

        # Chip suggestion
        chip_suggestion = None
        blank_count = len(blank_starters)
        if blank_count >= 3:
            chip_suggestion = {
                "chip": "free_hit",
                "reason": f"{blank_count} starters have no fixture — Free Hit recommended.",
                "urgency": "urgent" if blank_count >= 5 else "monitor",
            }
        elif sum(p.predicted_xpts_next or 0 for p in starters) < 42:
            chip_suggestion = {
                "chip": "wildcard",
                "reason": "Squad xPts below baseline — consider Wildcard to rebuild.",
                "urgency": "plan",
            }

        if chip_suggestion and chip_suggestion["urgency"] == "urgent":
            verdict = "chip"
        elif bench_swaps:
            verdict = "bench_swap"
        elif chip_suggestion:
            verdict = "chip"
        else:
            verdict = "hold"

        zero_ft_advice = {
            "bench_swaps": bench_swaps,
            "chip_suggestion": chip_suggestion,
            "ilp_optimal_xi": ilp_optimal_xi,
            "verdict": verdict,
        }

    payload = {
        "gameweek": display_gw.id,
        "deadline": display_gw.deadline_time.isoformat() if display_gw.deadline_time else None,
        "captain_recommendation": top_captain,
        "injury_alerts": injury_alerts,
        "suspension_risk": suspension_alerts,
        "blank_gw_starters": blank_starters,
        "double_gw_players": double_players,
        "squad_size": len(picks),
        "free_transfers": free_transfers,
        "zero_ft_advice": zero_ft_advice,
        "analysis_mode": "full",
        "decision_engine_mode": settings.DECISION_ENGINE_MODE,
        "data_freshness": display_gw.deadline_time.isoformat() if display_gw.deadline_time else None,
        "session_expires_at": session.expires_at.isoformat() if session else None,
    }
    if decision_engine.should_emit_shadow() and captain_candidates:
        payload["decision_engine_shadow"] = {
            "captain": decision_engine.build_shadow_payload(
                current=captain_candidates,
                synthesized=synthesized_captains,
                label="gw_intel_captain",
            )
        }
    await set_cached_payload("gw_intel", payload, ANALYSIS_TTL, active_team_id, session.session_token if session else "registered")
    return payload


@router.get("/fixture-swings")
async def get_fixture_swings(
    db: AsyncSession = Depends(get_db_session),
):
    """
    Identify buy/sell windows by computing average FDR over the next 6 GWs per team.
    Returns teams with improving fixtures (buy window) and worsening fixtures (sell window).
    """
    cached = await get_cached_payload("fixture_swings", "global")
    if cached:
        return cached

    result = await db.execute(select(Gameweek).where(Gameweek.is_current == True))
    current_gw = result.scalar_one_or_none()
    if not current_gw:
        return {"buy_windows": [], "sell_windows": []}

    gw_start = current_gw.id
    gw_end = min(gw_start + 6, 38)

    # Get upcoming fixtures
    result = await db.execute(
        select(Fixture).where(
            Fixture.gameweek_id >= gw_start,
            Fixture.gameweek_id <= gw_end,
        )
    )
    fixtures = result.scalars().all()

    # Compute average FDR per team
    from collections import defaultdict
    team_fdrs: dict[int, list[int]] = defaultdict(list)
    for f in fixtures:
        if f.team_h_difficulty:
            team_fdrs[f.team_home_id].append(f.team_h_difficulty)
        if f.team_a_difficulty:
            team_fdrs[f.team_away_id].append(f.team_a_difficulty)

    team_avg_fdr = {tid: sum(fdrs) / len(fdrs) for tid, fdrs in team_fdrs.items() if fdrs}

    # Also look back 3 GWs for comparison
    gw_back_start = max(1, gw_start - 3)
    result = await db.execute(
        select(Fixture).where(
            Fixture.gameweek_id >= gw_back_start,
            Fixture.gameweek_id < gw_start,
        )
    )
    past_fixtures = result.scalars().all()

    past_team_fdrs: dict[int, list[int]] = defaultdict(list)
    for f in past_fixtures:
        if f.team_h_difficulty:
            past_team_fdrs[f.team_home_id].append(f.team_h_difficulty)
        if f.team_a_difficulty:
            past_team_fdrs[f.team_away_id].append(f.team_a_difficulty)

    past_avg_fdr = {tid: sum(fdrs) / len(fdrs) for tid, fdrs in past_team_fdrs.items() if fdrs}

    from models.db.team import Team
    all_teams_result = await db.execute(select(Team))
    team_objs = {t.id: t for t in all_teams_result.scalars().all()}

    all_teams = []
    for team_id, avg_fdr in team_avg_fdr.items():
        past_avg = past_avg_fdr.get(team_id, avg_fdr)
        delta = avg_fdr - past_avg  # negative = improving (easier run coming)
        t_obj = team_objs.get(team_id)
        all_teams.append({
            "team_id": team_id,
            "team_name": t_obj.name if t_obj else str(team_id),
            "team_code": t_obj.code if t_obj else None,
            "avg_fdr_next_6": round(avg_fdr, 2),
            "prev_avg_fdr": round(past_avg, 2),
            "delta": round(delta, 2),
        })

    # Top 5 easiest upcoming runs (buy windows)
    buy_candidates = sorted(all_teams, key=lambda x: x["avg_fdr_next_6"])[:5]
    buy_windows = [
        {**t, "improvement": round(-t["delta"], 2), "signal": "BUY — Easy run of fixtures incoming"}
        for t in buy_candidates
    ]

    # Top 5 hardest upcoming runs (sell windows)
    sell_candidates = sorted(all_teams, key=lambda x: x["avg_fdr_next_6"], reverse=True)[:5]
    sell_windows = [
        {**t, "difficulty_increase": max(0.0, round(t["delta"], 2)), "signal": "SELL — Tough fixtures incoming"}
        for t in sell_candidates
    ]

    payload = {
        "gameweek": current_gw.id,
        "gw_range": f"GW{gw_start}-GW{gw_end}",
        "buy_windows": buy_windows,
        "sell_windows": sell_windows,
    }
    await set_cached_payload("fixture_swings", payload, FIXTURE_TTL, "global")
    return payload


@router.get("/priority-actions")
async def get_priority_actions(
    team_context: dict = Depends(get_team_context),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Intelligence Brief — top 5 priority actions ranked by impact.
    Combines transfer suggestions, captain pick, injury alerts, and chip timing
    into one ranked list so managers know exactly what to do this GW.
    """
    from optimizers.captain_engine import CaptainEngine
    from optimizers.transfer_engine import TransferEngine
    from models.db.user_squad import UserBank
    from models.db.team import Team as TeamModel
    import pandas as pd

    active_team_id = team_context["team_id"]

    # ── GW ───────────────────────────────────────────────────────────────────
    result = await db.execute(select(Gameweek).where(Gameweek.is_current == True))
    current_gw = result.scalar_one_or_none()
    if not current_gw:
        raise HTTPException(404, "No active gameweek")
    gw_id = current_gw.id  # Used for squad lookup (data stored under current GW)

    # When current GW is finished, show brief for NEXT GW (preparing for GW30, not GW29)
    display_gw_id = gw_id
    if current_gw.finished:
        next_res = await db.execute(select(Gameweek).where(Gameweek.is_next == True))
        next_gw = next_res.scalar_one_or_none()
        if next_gw:
            display_gw_id = next_gw.id

    # ── Squad ────────────────────────────────────────────────────────────────
    result = await db.execute(
        select(UserSquad).where(
            UserSquad.team_id == active_team_id,
            UserSquad.gameweek_id == gw_id,
        )
    )
    picks = result.scalars().all()
    if not picks:
        raise HTTPException(404, "No squad data. Run /api/squad/sync first.")

    # ── Bank ─────────────────────────────────────────────────────────────────
    result = await db.execute(select(UserBank).where(UserBank.team_id == active_team_id))
    bank = result.scalar_one_or_none()
    free_transfers = bank.free_transfers if bank else 1
    bank_pence = bank.bank if bank else 0

    # ── GW Underway Gate ─────────────────────────────────────────────────────
    # If the GW deadline has passed but the GW is not yet finished, the squad
    # is locked — no transfers, no bench changes, no captain changes possible.
    # Return early with an empty action list so nothing gets logged and the
    # home page shows a "GW underway" state instead of stale suggestions.
    from datetime import datetime as _dt_check
    _now = _dt_check.utcnow()
    _gw_underway = (
        not current_gw.finished
        and current_gw.deadline_time is not None
        and current_gw.deadline_time < _now
    )
    if _gw_underway:
        return {
            "gameweek": current_gw.id,
            "free_transfers": free_transfers,
            "actions": [],
            "total_actions": 0,
            "gw_state": "underway",
            "message": f"GW{current_gw.id} is underway — squad locked, fixtures in play",
            "decision_engine_mode": settings.DECISION_ENGINE_MODE,
        }

    # ── Player lookups ────────────────────────────────────────────────────────
    squad_ids = [p.player_id for p in picks]
    xi_ids = [p.player_id for p in picks if p.position <= 11]
    selling_prices = {p.player_id: p.selling_price or p.purchase_price or 0 for p in picks}
    picks_map = {p.player_id: p for p in picks}

    squad_players: list[Player] = []
    for pid in squad_ids:
        player = await db.get(Player, pid)
        if player:
            squad_players.append(player)

    result = await db.execute(select(Player))
    all_players = result.scalars().all()

    # Build team_code lookup early (used across all action types for crest logos)
    from models.db.team import Team as TeamModel
    team_map_res = await db.execute(select(TeamModel))
    team_map = {t.id: t for t in team_map_res.scalars().all()}

    actions: list[dict] = []

    # ── 1. Injury / doubt alerts in starting XI ──────────────────────────────
    for player in squad_players:
        pick = picks_map.get(player.id)
        if not pick or pick.position > 11:
            continue
        chance = player.chance_of_playing_next_round
        bad_status = player.status in ("d", "i", "s", "u")
        low_chance = chance is not None and chance < 75
        if not bad_status and not low_chance:
            continue

        is_out = player.status == "i" or chance == 0
        urgency = "HIGH" if (is_out or (chance is not None and chance <= 25)) else "MEDIUM"
        label = (
            f"Replace {player.web_name} — confirmed out"
            if is_out
            else f"Replace {player.web_name} — {chance}% fit"
        )
        actions.append({
            "type": "injury",
            "urgency": urgency,
            "must_do": urgency == "HIGH",
            "label": label,
            "impact_label": "xPts at risk",
            "impact_value": round(player.predicted_xpts_next or 0, 1),
            "reasoning": player.news or f"{player.web_name} unavailable for next fixture",
            "decision_type": "transfer_strategy",
            "recommended_option": f"Transfer out {player.web_name}",
            "team_code": team_map[player.team_id].code if player.team_id in team_map else None,
            "player_id_primary": player.id,  # for badge + gain tracking
        })

    # ── 2. Captain recommendation ─────────────────────────────────────────────
    captain_engine = CaptainEngine()
    xi_squad = [
        p for p in squad_players
        if picks_map.get(p.id) and picks_map[p.id].position <= 11 and p.element_type != 1
    ]
    cap_candidates = captain_engine.rank_captains([
        {
            "player_id": p.id,
            "web_name": p.web_name,
            "element_type": p.element_type,
            "team_id": p.team_id,
            "team_code": team_map[p.team_id].code if p.team_id in team_map else None,
            "predicted_xpts_next": p.predicted_xpts_next or 0,
            "has_blank_gw": p.has_blank_gw or False,
            "fdr_next": p.fdr_next or 3,
            "is_home_next": p.is_home_next or False,
            "has_double_gw": p.has_double_gw or False,
            "selected_by_percent": float(p.selected_by_percent or 0),
        }
        for p in xi_squad
    ])
    top_captain = cap_candidates[0] if cap_candidates else None
    if top_captain:
        xpts = top_captain.get("predicted_xpts_next", 0)
        urgency = "HIGH" if xpts >= 6 else "MEDIUM" if xpts >= 4 else "LOW"
        actions.append({
            "type": "captain",
            "urgency": urgency,
            "must_do": xpts >= 6,
            "label": f"Captain {top_captain['web_name']}",
            "impact_label": "Captain xPts",
            "impact_value": round(xpts * 2, 1),
            "reasoning": (
                f"{top_captain['web_name']}: {xpts:.1f} xPts — "
                f"{'home' if top_captain.get('is_home_next') else 'away'}, "
                f"FDR {top_captain.get('fdr_next', 3)}"
                + (" · DGW" if top_captain.get("has_double_gw") else "")
            ),
            "decision_type": "captain_pick",
            "recommended_option": f"{top_captain['web_name']} (C)",
            "team_code": top_captain.get("team_code"),
            "player_id_primary": top_captain.get("player_id"),  # for gain tracking
        })

    # ── 3. Transfer suggestions (lightweight greedy engine) ───────────────────
    try:
        df = pd.DataFrame([{
            "id": p.id,
            "web_name": p.web_name,
            "element_type": p.element_type,
            "team_id": p.team_id,
            "team_short_name": team_map[p.team_id].short_name if p.team_id in team_map else None,
            "team_code": team_map[p.team_id].code if p.team_id in team_map else None,
            "now_cost": p.now_cost,
            "predicted_xpts_next": p.predicted_xpts_next,
            "has_blank_gw": p.has_blank_gw,
            "status": p.status,
            "selected_by_percent": p.selected_by_percent,
            "form": p.form,
            "fdr_next": p.fdr_next,
        } for p in all_players])

        te = TransferEngine()
        suggestions = te.get_transfer_suggestions(
            squad_player_ids=squad_ids,
            players_df=df,
            bank=bank_pence,
            free_transfers=free_transfers,
            selling_prices=selling_prices,
            top_n=3,
            starting_xi_ids=xi_ids,
        )
        for s in suggestions:
            if s.recommendation == "HOLD":
                continue
            urgency = "HIGH" if (s.recommendation == "MAKE" and s.xpts_gain_next >= 1.5) else "MEDIUM"
            out_name = s.player_out.get("web_name", "?")
            in_name = s.player_in.get("web_name", "?")
            actions.append({
                "type": "transfer",
                "urgency": urgency,
                "must_do": s.recommendation == "MAKE" and free_transfers >= 1,
                "label": f"{out_name} → {in_name}",
                "impact_label": "xPts gain",
                "impact_value": round(s.xpts_gain_next, 1),
                "reasoning": s.reasoning,
                "decision_type": "transfer_strategy",
                "recommended_option": f"OUT: {out_name} / IN: {in_name}",
                "team_code": s.player_in.get("team_code"),
                "player_out_team_code": s.player_out.get("team_code"),
                "player_id_primary": s.player_in.get("id"),    # player_in FPL id (for gain tracking)
                "player_id_secondary": s.player_out.get("id"), # player_out FPL id
            })
    except Exception:
        pass  # Non-fatal — transfer engine may fail during between-GW windows

    # ── 4. Bench ↔ XI free swap suggestions ──────────────────────────────────
    # Compare bench players vs XI players in same position.
    # A free swap (no transfer cost) is flagged when bench player has meaningfully
    # higher xPts than the weakest XI player in that position.
    bench_players = [
        p for p in squad_players
        if picks_map.get(p.id) and picks_map[p.id].position > 11
    ]
    xi_players_list = [
        p for p in squad_players
        if picks_map.get(p.id) and picks_map[p.id].position <= 11
    ]
    for bench_p in bench_players:
        # Skip injured / unavailable bench players
        if bench_p.status in ("i", "u"):
            continue
        chance = bench_p.chance_of_playing_next_round
        if chance is not None and chance < 50:
            continue
        bench_xpts = bench_p.predicted_xpts_next or 0
        if bench_xpts < 2.0:
            continue  # Bench player too weak to be worth surfacing
        # Find weakest XI player of the same position
        same_pos_xi = [xi for xi in xi_players_list if xi.element_type == bench_p.element_type]
        if not same_pos_xi:
            continue
        weakest_xi = min(same_pos_xi, key=lambda p: p.predicted_xpts_next or 0)
        xi_xpts = weakest_xi.predicted_xpts_next or 0
        gain = round(bench_xpts - xi_xpts, 1)
        if gain >= 1.5:
            urgency = "HIGH" if gain >= 3.0 else "MEDIUM"
            actions.append({
                "type": "bench_swap",
                "urgency": urgency,
                "must_do": urgency == "HIGH",
                "label": f"{bench_p.web_name} → XI (free swap)",
                "impact_label": "xPts gain",
                "impact_value": gain,
                "reasoning": (
                    f"Bench {bench_p.web_name} ({bench_xpts:.1f} xP) > "
                    f"XI {weakest_xi.web_name} ({xi_xpts:.1f} xP). "
                    f"No transfer cost — just a positional swap."
                ),
                "decision_type": "formation_change",
                "recommended_option": (
                    f"Move {bench_p.web_name} to XI, {weakest_xi.web_name} to bench"
                ),
                "team_code": team_map[bench_p.team_id].code if bench_p.team_id in team_map else None,
            })

    # ── 5. Chip timing ────────────────────────────────────────────────────────
    if bank:
        bench_dgw = [
            p for p in squad_players
            if p.has_double_gw and picks_map.get(p.id) and picks_map[p.id].position > 11
        ]

        # Triple Captain: top captain has DGW + strong xPts
        if bank.chip_available("triple_captain", gw_id) and top_captain:
            cap_xpts_raw = top_captain.get("predicted_xpts_next", 0)
            if top_captain.get("has_double_gw") and cap_xpts_raw >= 7:
                actions.append({
                    "type": "chip",
                    "urgency": "HIGH",
                    "must_do": True,
                    "label": f"Triple Captain {top_captain['web_name']}",
                    "impact_label": "TC xPts",
                    "impact_value": round(cap_xpts_raw * 3, 1),
                    "reasoning": f"DGW: {top_captain['web_name']} projects {cap_xpts_raw*3:.1f} xPts with TC",
                    "decision_type": "chip_timing",
                    "recommended_option": f"Triple Captain ({top_captain['web_name']})",
                })

        # Bench Boost: ≥2 DGW players on bench
        if bank.chip_available("bench_boost", gw_id) and len(bench_dgw) >= 2:
            bench_xpts = sum(p.predicted_xpts_next or 0 for p in bench_dgw)
            actions.append({
                "type": "chip",
                "urgency": "MEDIUM",
                "must_do": False,
                "label": f"Bench Boost — {len(bench_dgw)} DGW players on bench",
                "impact_label": "Extra xPts",
                "impact_value": round(bench_xpts, 1),
                "reasoning": f"BB adds ~{bench_xpts:.1f} xPts from {len(bench_dgw)} DGW bench players",
                "decision_type": "chip_timing",
                "recommended_option": "Bench Boost",
            })

    # ── Rank by urgency then impact ───────────────────────────────────────────
    urgency_rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    actions.sort(key=lambda a: (urgency_rank.get(a["urgency"], 3), -a["impact_value"]))
    for i, a in enumerate(actions):
        a["priority"] = i + 1

    current_actions = actions[:7]
    synthesized_actions = decision_engine.synthesize_priority_actions(
        current_actions,
        context=DecisionContext(
            recommendation_type="priority_action",
            risk_preference=settings.DEFAULT_RISK_PROFILE,
            current_gameweek=display_gw_id,
            team_id=active_team_id,
        ),
    )
    payload = {
        "gameweek": display_gw_id,
        "free_transfers": free_transfers,
        "actions": synthesized_actions if decision_engine.should_replace_live_output(active_team_id) else current_actions,
        "total_actions": len(actions),
        "decision_engine_mode": settings.DECISION_ENGINE_MODE,
    }
    if decision_engine.should_emit_shadow():
        payload["decision_engine_shadow"] = decision_engine.build_shadow_payload(
            current=current_actions,
            synthesized=synthesized_actions,
            label="priority_actions",
        )

    # ── Auto-persist recommendations to decision_log (idempotent) ─────────────
    # Each time the intel route is called we record every action as a pending
    # decision (decision_followed=None). Cross-check later marks them
    # followed/ignored. This means "ignored" decisions are captured automatically
    # even when the user never clicks anything.
    #
    # Deduplication rules:
    #   SINGLETON types (captain_pick, formation_change): only ONE entry per
    #     (team, gw, decision_type). When the recommendation changes (e.g.,
    #     captain switches from Thiago → Bruno), UPDATE the existing entry in
    #     place and refresh created_at so the review page sees the latest pick.
    #   All other types: one row per (team, gw, recommended_option) — multiple
    #     transfer options each get their own row.
    _SINGLETON_DT = {"captain_pick", "captain", "formation_change", "formation"}
    try:
        actions_to_log = payload["actions"]
        now_ts = datetime.utcnow()
        for action in actions_to_log:
            dt = action.get("decision_type")
            ro = action.get("recommended_option")
            if not dt or not ro:
                continue

            dt_key = dt.lower().replace(" ", "_")
            is_singleton = any(s in dt_key for s in _SINGLETON_DT)

            if is_singleton:
                # SINGLETON: only ONE captain_pick / formation_change row per (team, gw).
                # Strategy: find all pending entries for this decision_type.
                #   - DELETE any that DON'T match the current recommendation (stale).
                #   - UPDATE the matching one (refresh created_at so review page
                #     ordering stays correct), or INSERT if none found.
                all_existing_res = await db.execute(
                    select(DecisionLog).where(
                        and_(
                            DecisionLog.team_id == active_team_id,
                            DecisionLog.gameweek_id == display_gw_id,
                            DecisionLog.decision_type == dt,
                            DecisionLog.resolved_at.is_(None),
                        )
                    )
                )
                all_existing = all_existing_res.scalars().all()

                # Partition into: current recommendation entry vs stale entries
                match = next((e for e in all_existing if e.recommended_option == ro), None)
                stale  = [e for e in all_existing if e.recommended_option != ro and e.decision_followed is None]

                # Delete stale entries (old recommendations superseded by new one)
                for stale_entry in stale:
                    await db.delete(stale_entry)

                if match and match.decision_followed is None:
                    # Refresh the matched entry so it sorts as newest
                    match.expected_points = action.get("impact_value") or 0.0
                    match.reasoning = action.get("reasoning")
                    match.created_at = now_ts
                    match.player_id_primary = action.get("player_id_primary")
                    match.player_id_secondary = action.get("player_id_secondary")
                elif not match:
                    # No existing entry → insert fresh
                    await db.flush()  # flush deletes before insert to avoid constraint races
                    db.add(DecisionLog(
                        team_id=active_team_id,
                        gameweek_id=display_gw_id,
                        decision_type=dt,
                        recommended_option=ro,
                        expected_points=action.get("impact_value") or 0.0,
                        reasoning=action.get("reasoning"),
                        created_at=now_ts,
                        player_id_primary=action.get("player_id_primary"),
                        player_id_secondary=action.get("player_id_secondary"),
                    ))
            else:
                # NON-SINGLETON: one row per (team, gw, recommended_option).
                #
                # Skip standalone "Transfer out X" injury flags when a specific
                # "OUT: X / IN: Y" recommendation already exists for the same player.
                # This prevents double-logging: the specific transfer captures the action;
                # the standalone flag is redundant noise.
                primary_pid = action.get("player_id_primary")
                if ro.startswith("Transfer out "):
                    # Extract player name: "Transfer out James" → "James"
                    player_name_flag = ro[len("Transfer out "):].strip()
                    specific_res = await db.execute(
                        select(DecisionLog).where(
                            and_(
                                DecisionLog.team_id == active_team_id,
                                DecisionLog.gameweek_id == display_gw_id,
                                DecisionLog.recommended_option.like(f"OUT: {player_name_flag} / IN: %"),
                                DecisionLog.resolved_at.is_(None),
                            )
                        ).limit(1)
                    )
                    if specific_res.scalars().first():
                        # Specific transfer exists for this player — delete any stale
                        # standalone "Transfer out X" and skip creating a new one.
                        stale_flag_res = await db.execute(
                            select(DecisionLog).where(
                                and_(
                                    DecisionLog.team_id == active_team_id,
                                    DecisionLog.gameweek_id == display_gw_id,
                                    DecisionLog.recommended_option == ro,
                                    DecisionLog.resolved_at.is_(None),
                                )
                            )
                        )
                        for stale_flag in stale_flag_res.scalars().all():
                            if stale_flag.decision_followed is None:
                                await db.delete(stale_flag)
                        continue  # skip logging the standalone flag

                # For "OUT: X / IN: Y" transfer decisions, deduplicate by the OUT player
                # name extracted from recommended_option. Only one transfer recommendation
                # per out-player per GW, keeping the most current one.
                # (player_id_primary on these rows is the IN player, so dedup by name string.)
                if ro.startswith("OUT:") and " / IN: " in ro:
                    out_player_name = ro.split(" / IN: ")[0].replace("OUT: ", "").strip()
                    # Find all existing OUT: <same-player> recommendations for this GW
                    all_out_res = await db.execute(
                        select(DecisionLog).where(
                            and_(
                                DecisionLog.team_id == active_team_id,
                                DecisionLog.gameweek_id == display_gw_id,
                                DecisionLog.recommended_option.like(f"OUT: {out_player_name} / IN: %"),
                                DecisionLog.resolved_at.is_(None),
                            )
                        )
                    )
                    all_for_player = all_out_res.scalars().all()
                    match = next((e for e in all_for_player if e.recommended_option == ro), None)
                    stale = [e for e in all_for_player if e.recommended_option != ro and e.decision_followed is None]
                    for stale_entry in stale:
                        await db.delete(stale_entry)
                    if match:
                        if match.decision_followed is None:
                            match.decision_type = dt
                            match.expected_points = action.get("impact_value") or 0.0
                            match.reasoning = action.get("reasoning")
                            match.player_id_primary = primary_pid
                            match.player_id_secondary = action.get("player_id_secondary")
                    else:
                        await db.flush()
                        db.add(DecisionLog(
                            team_id=active_team_id,
                            gameweek_id=display_gw_id,
                            decision_type=dt,
                            recommended_option=ro,
                            expected_points=action.get("impact_value") or 0.0,
                            reasoning=action.get("reasoning"),
                            created_at=now_ts,
                            player_id_primary=primary_pid,
                            player_id_secondary=action.get("player_id_secondary"),
                        ))
                    continue

                existing_res = await db.execute(
                    select(DecisionLog).where(
                        and_(
                            DecisionLog.team_id == active_team_id,
                            DecisionLog.gameweek_id == display_gw_id,
                            DecisionLog.recommended_option == ro,
                            DecisionLog.resolved_at.is_(None),
                        )
                    ).limit(1)
                )
                existing = existing_res.scalars().first()

                if existing:
                    if existing.decision_followed is None:
                        existing.decision_type = dt
                        existing.expected_points = action.get("impact_value") or 0.0
                        existing.reasoning = action.get("reasoning")
                        existing.player_id_primary = action.get("player_id_primary")
                        existing.player_id_secondary = action.get("player_id_secondary")
                else:
                    db.add(DecisionLog(
                        team_id=active_team_id,
                        gameweek_id=display_gw_id,
                        decision_type=dt,
                        recommended_option=ro,
                        expected_points=action.get("impact_value") or 0.0,
                        reasoning=action.get("reasoning"),
                        created_at=now_ts,
                        player_id_primary=action.get("player_id_primary"),
                        player_id_secondary=action.get("player_id_secondary"),
                    ))

        await db.commit()
    except Exception as _log_exc:
        import logging as _logging
        _logging.getLogger(__name__).warning(f"Intel: failed to auto-log decisions: {_log_exc}")

    return payload


@router.get("/yellow-cards")
async def get_yellow_card_risks(
    team_id: int | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    """
    Returns players at suspension risk (4+ yellow cards before GW19 or GW38 cut-off).
    When team_id is provided, filters to only squad players owned by that team.
    FPL rule: 5 yellows in GW1-19 = 1-match ban; counter resets at GW19 deadline.
    """
    active_team_id = team_id or settings.FPL_TEAM_ID

    result = await db.execute(select(Gameweek).where(Gameweek.is_current == True))
    current_gw = result.scalar_one_or_none()
    current_gw_id = current_gw.id if current_gw else 1

    # GW19 cut-off (first half ends GW19), GW38 (season end)
    gws_until_cutoff = 19 - current_gw_id if current_gw_id <= 19 else 38 - current_gw_id
    near_cutoff = gws_until_cutoff <= 3

    # Filter to squad players only
    squad_player_ids: set[int] = set()
    if active_team_id:
        squad_result = await db.execute(
            select(UserSquad.player_id).where(
                UserSquad.team_id == active_team_id,
                UserSquad.gameweek_id == current_gw_id,
            )
        )
        squad_player_ids = {row[0] for row in squad_result.fetchall()}

    if squad_player_ids:
        result = await db.execute(
            select(Player).where(
                Player.suspension_risk == True,
                Player.id.in_(squad_player_ids),
            )
        )
    else:
        result = await db.execute(
            select(Player).where(Player.suspension_risk == True)
        )
    at_risk = result.scalars().all()

    # Team lookup for badge enrichment
    from models.db.team import Team as TeamModel
    all_team_ids = {p.team_id for p in at_risk if p.team_id}
    team_res = await db.execute(select(TeamModel).where(TeamModel.id.in_(all_team_ids)))
    yc_team_map = {t.id: t for t in team_res.scalars().all()}

    return {
        "gameweek": current_gw_id,
        "gws_until_yellow_cutoff": max(0, gws_until_cutoff),
        "cutoff_approaching": near_cutoff,
        "players_at_risk": [
            {
                "player_id": p.id,
                "web_name": p.web_name,
                "team_id": p.team_id,
                "team_code": yc_team_map[p.team_id].code if p.team_id and p.team_id in yc_team_map else None,
                "yellow_cards": p.yellow_cards,
                "element_type": p.element_type,
                "selected_by_percent": p.selected_by_percent,
                "now_cost": p.now_cost,
                "action": "CONSIDER SELLING before potential ban" if near_cutoff else "Monitor closely",
            }
            for p in at_risk
        ],
    }
