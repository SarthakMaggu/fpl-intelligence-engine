"""Transfer evaluation and suggestions routes."""
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from loguru import logger

from api.deps import get_db_session, get_team_context
from core.config import settings
from core.redis_client import redis_client
from models.db.player import Player
from models.db.team import Team
from models.db.user_squad import UserSquad, UserBank
from models.db.gameweek import Gameweek
from optimizers.transfer_engine import TransferEngine
from optimizers.squad_optimizer import SquadOptimizer
from services.decision_engine import decision_engine, DecisionContext

router = APIRouter()
transfer_engine = TransferEngine()
squad_optimizer = SquadOptimizer()


class TransferEvaluateRequest(BaseModel):
    player_out_id: int
    player_in_id: int
    team_id: int | None = None


@router.get("/suggestions")
async def get_transfer_suggestions(
    team_context: dict = Depends(get_team_context),
    top_n: int = 5,
    db: AsyncSession = Depends(get_db_session),
):
    """Get top transfer suggestions for current squad."""
    active_team_id = team_context["team_id"]
    session = team_context.get("session")

    # Get current GW
    result = await db.execute(select(Gameweek).where(Gameweek.is_current == True))
    current_gw = result.scalar_one_or_none()
    if not current_gw:
        raise HTTPException(404, "No current gameweek found")

    # Get squad picks — try current GW first, fall back to most recent GW.
    # During GW transition (current GW just ended, next GW squad not yet synced),
    # the current GW's squad is used as a proxy for the upcoming GW's squad.
    result = await db.execute(
        select(UserSquad).where(
            UserSquad.team_id == active_team_id,
            UserSquad.gameweek_id == current_gw.id,
        )
    )
    picks = result.scalars().all()
    if not picks:
        # GW boundary: fall back to the most recent GW with squad data
        from sqlalchemy import desc
        fallback = await db.execute(
            select(UserSquad)
            .where(UserSquad.team_id == active_team_id)
            .order_by(desc(UserSquad.gameweek_id))
            .limit(15)
        )
        picks = fallback.scalars().all()
    if not picks:
        raise HTTPException(404, "No squad data. Visit the Squad tab first to sync your team.")

    # Get bank data
    result = await db.execute(select(UserBank).where(UserBank.team_id == active_team_id))
    bank = result.scalar_one_or_none()

    # Build selling prices dict (FPL sell-on cap stored per pick)
    selling_prices = {p.player_id: p.selling_price for p in picks}
    picks_purchase = {p.player_id: p.purchase_price for p in picks}
    squad_ids = [p.player_id for p in picks]
    # Starting XI: positions 1-11 (bench = 12-15). Used to restrict transfer-out
    # candidates to XI players only — bench player swaps don't improve playing XI.
    xi_player_ids = [p.player_id for p in picks if p.position <= 11]
    bank_pence = bank.bank if bank else 0
    free_transfers = bank.free_transfers if bank else 1

    # ── Chip detection: which chips are active this GW? ───────────────────────
    # Chips are tracked in UserBank by the GW they were played. Matching the
    # current GW id means the chip is ACTIVE NOW (before deadline passes).
    current_gw_id = current_gw.id
    wildcard_active: bool = bool(bank) and (
        bank.wildcard_1_used_gw == current_gw_id
        or bank.wildcard_2_used_gw == current_gw_id
    )
    free_hit_active: bool = bool(bank) and (
        bank.free_hit_1_used_gw == current_gw_id
        or bank.free_hit_2_used_gw == current_gw_id
    )
    bench_boost_active: bool = bool(bank) and (
        bank.bench_boost_1_used_gw == current_gw_id
        or bank.bench_boost_2_used_gw == current_gw_id
    )
    triple_captain_active: bool = bool(bank) and (
        bank.triple_captain_1_used_gw == current_gw_id
        or bank.triple_captain_2_used_gw == current_gw_id
    )
    # Both wildcard AND free hit waive all transfer costs (squad reverts after FH)
    transfers_free: bool = wildcard_active or free_hit_active

    # Get all players
    result = await db.execute(select(Player))
    all_players = result.scalars().all()

    # Load team lookup for badge enrichment (team_short_name + team_code)
    result_teams = await db.execute(select(Team))
    _teams = result_teams.scalars().all()
    team_lookup: dict[int, Team] = {t.id: t for t in _teams}

    def _team_short(tid: int) -> str | None:
        t = team_lookup.get(tid)
        return t.short_name if t else None

    def _team_code(tid: int) -> int | None:
        t = team_lookup.get(tid)
        return t.code if t else None

    # Build cost lookup BEFORE computing sell prices (needed for fallback)
    player_cost_map = {p.id: p.now_cost for p in all_players}

    # ── Accurate sell-on cap prices ────────────────────────────────────────────
    # FPL rule: if price rose → sell at purchase_price + floor((gain) / 2)
    #           if price same or dropped → sell at current now_cost
    # Our DB stores this in selling_price, but it can be 0 on stale / early syncs.
    # Using now_cost directly would OVER-estimate budget by up to £0.25m per player.
    def _compute_sell_price(pid: int) -> int:
        stored = selling_prices.get(pid, 0)
        if stored > 0:
            return stored                              # FPL API value — always prefer
        purchase = picks_purchase.get(pid, 0)
        now = player_cost_map.get(pid, 0)
        if purchase > 0 and now > purchase:
            return purchase + (now - purchase) // 2   # sell-on cap
        return now if now > 0 else purchase            # price flat or dropped

    effective_selling_prices = {pid: _compute_sell_price(pid) for pid in squad_ids}

    import pandas as pd
    df = pd.DataFrame([{
        "id": p.id,
        "web_name": p.web_name,
        "element_type": p.element_type,
        "team_id": p.team_id,
        "team_short_name": _team_short(p.team_id),
        "team_code": _team_code(p.team_id),
        "now_cost": p.now_cost,
        "predicted_xpts_next": p.predicted_xpts_next,
        "has_blank_gw": p.has_blank_gw,
        "status": p.status,
        "selected_by_percent": p.selected_by_percent,
        "form": p.form,
        "fdr_next": p.fdr_next,
    } for p in all_players])

    suggestions = transfer_engine.get_transfer_suggestions(
        squad_player_ids=squad_ids,
        players_df=df,
        bank=bank_pence,
        free_transfers=free_transfers,
        selling_prices=effective_selling_prices,   # sell-on cap corrected
        top_n=top_n,
        starting_xi_ids=xi_player_ids,             # only XI players as transfer-out candidates
    )

    # ── ILP optimal plan ──────────────────────────────────────────────────────
    # Runs the full Integer Linear Programming optimizer with the current squad
    # as the baseline. Finds the globally optimal set of transfers (respecting
    # budget, formation, 3-per-club, and the -4pt hit cost per extra transfer).
    # Run in executor so we don't block the async event loop during CBC solving.
    optimal_squad_payload: dict | None = None
    try:
        # Budget = accurate sell-on-cap squad value + bank.
        # effective_selling_prices already uses purchase_price for the 50% gain split.
        total_budget = bank_pence + sum(
            effective_selling_prices.get(pid, 0) for pid in squad_ids
        )

        # ── ILP player pool: two-tier filtering ───────────────────────────────
        # Tier 1 — Current squad members: always included regardless of form so
        #   the ILP can consider bench↔XI swaps without forcing a real transfer.
        #   A bench player with high xPts should be swappable into the XI for free.
        squad_set = set(squad_ids)
        current_squad_df = df[df["id"].isin(squad_set)].copy()

        # Tier 2 — External candidates: quality-gated to avoid recommending
        #   fringe/frozen-out players as transfer targets.
        external_df = df[
            ~df["id"].isin(squad_set) &
            (df["status"] == "a") &
            (df["now_cost"] > 0) &
            (df["predicted_xpts_next"].notna()) &
            (df["predicted_xpts_next"] >= 0) &
            (df["form"].fillna(0).astype(float) >= 1.0)   # must have recent activity
        ].copy()

        import pandas as _pd
        ilp_df = _pd.concat([current_squad_df, external_df], ignore_index=True).drop_duplicates(subset=["id"])
        ilp_df["predicted_xpts_next"] = ilp_df["predicted_xpts_next"].clip(upper=14.0)

        loop = asyncio.get_event_loop()
        ilp_result = await loop.run_in_executor(
            None,
            lambda: squad_optimizer.optimize_squad(
                players_df=ilp_df,
                budget=total_budget,
                existing_squad=squad_ids,
                free_transfers=free_transfers,
                wildcard_active=transfers_free,          # wildcard or free hit → no cost
                bench_boost_active=bench_boost_active,   # bench players score
                triple_captain_active=triple_captain_active,  # captain ×3
            ),
        )

        # Derive specific transfer moves
        existing_set = set(squad_ids)
        optimal_set = set(ilp_result.squad)
        out_ids = [pid for pid in squad_ids if pid not in optimal_set]
        in_ids = [pid for pid in ilp_result.squad if pid not in existing_set]

        # Sort both lists by position (element_type) so display pairs them correctly:
        # GK→GK, DEF→DEF, MID→MID, FWD→FWD. Without this, the UI pairs by index
        # and shows cross-position pairs (e.g. GK→FWD) which look like invalid moves.
        def _elem_type(pid: int) -> int:
            p = next((p for p in all_players if p.id == pid), None)
            return p.element_type if p else 99
        out_ids = sorted(out_ids, key=_elem_type)
        in_ids = sorted(in_ids, key=_elem_type)

        # Build a capped xpts lookup (same cap as ILP objective, avoids misleading UI)
        capped_xpts = {
            int(row["id"]): float(row["predicted_xpts_next"])
            for _, row in ilp_df.iterrows()
        }

        def enrich_player(pid: int) -> dict:
            p = next((p for p in all_players if p.id == pid), None)
            if not p:
                return {"id": pid, "web_name": str(pid), "element_type": 0, "now_cost": 0, "predicted_xpts_next": None, "team_short_name": None, "team_code": None}
            return {
                "id": p.id,
                "web_name": p.web_name,
                "element_type": p.element_type,
                "now_cost": p.now_cost,
                # Use capped xpts so display matches what ILP optimized against
                "predicted_xpts_next": capped_xpts.get(p.id, p.predicted_xpts_next),
                "team_short_name": _team_short(p.team_id),
                "team_code": _team_code(p.team_id),
            }

        captain = enrich_player(ilp_result.captain_id)
        captain = decision_engine.synthesize_player_recommendation(
            captain,
            context=DecisionContext(
                recommendation_type="ilp_captain",
                risk_preference=settings.DEFAULT_RISK_PROFILE,
                current_gameweek=current_gw.id,
                team_id=active_team_id,
            ),
            baseline_score=float(captain.get("predicted_xpts_next", 0) or 0),
        )

        # ── Bench ↔ XI free swaps (no transfer cost) ──────────────────────────
        # Players in both squads who changed role: bench→XI or XI→bench.
        # These are FREE moves (no hit) that the ILP recommends to improve the XI.
        existing_xi_set = set(xi_player_ids)
        optimal_xi_set = set(ilp_result.starting_xi)

        # Players who should move bench → XI (currently bench, ILP puts them in XI)
        bench_to_xi = [
            pid for pid in squad_ids
            if pid not in existing_xi_set   # currently on bench
            and pid in optimal_xi_set       # ILP wants them in XI
            and pid in optimal_set          # still in squad (not sold)
        ]
        # Players who should drop XI → bench (currently starting, ILP benches them)
        xi_to_bench = [
            pid for pid in xi_player_ids
            if pid not in optimal_xi_set    # ILP drops from XI
            and pid in optimal_set          # still in squad (not sold)
        ]
        # Sort both by position for display coherence
        bench_to_xi_sorted = sorted(bench_to_xi, key=_elem_type)
        xi_to_bench_sorted = sorted(xi_to_bench, key=_elem_type)
        n_free_pairs = min(len(bench_to_xi_sorted), len(xi_to_bench_sorted))
        bench_swaps = [
            {
                "from_bench": enrich_player(b_id),   # bench → XI
                "to_bench":   enrich_player(x_id),   # XI → bench
            }
            for b_id, x_id in zip(bench_to_xi_sorted[:n_free_pairs], xi_to_bench_sorted[:n_free_pairs])
        ]

        # XI players displaced by incoming transfers (not covered by free bench swaps)
        # e.g. Sarr (new transfer) goes to XI → existing XI player pushed to bench
        xi_demoted_ids = xi_to_bench_sorted[n_free_pairs:]

        # Build xi_demoted_map: which incoming player displaces which existing XI player.
        # Key insight: if Gabriel (DEF, XI) is sold and Virgil (DEF) comes in, Virgil takes
        # Gabriel's slot directly — no displacement. But if Wilson (bench MID) is sold and
        # Sarr (MID) comes in to XI, Sarr needs a slot from somewhere → displaces a demoted player.
        #
        # Step 1: Match XI-players-OUT with same-position XI-players-IN (direct slot replacement).
        # These transfers fill the freed XI slot and cause no displacement.
        xi_out_ids = [pid for pid in out_ids if pid in existing_xi_set]
        in_xi_ids = [pid for pid in in_ids if pid in optimal_xi_set]

        unmatched_in_xi = list(in_xi_ids)
        for out_pid in xi_out_ids:
            out_type = _elem_type(out_pid)
            match_idx = next(
                (i for i, in_pid in enumerate(unmatched_in_xi) if _elem_type(in_pid) == out_type),
                None,
            )
            if match_idx is not None:
                unmatched_in_xi.pop(match_idx)  # this in-player takes the sold player's XI slot

        # Step 2: Remaining in_xi_ids (no matching OUT slot) must displace an existing XI player.
        # Try same-position first; fall back to any if formation changed (e.g. MID displaces DEF).
        xi_demoted_map: dict[int, int] = {}
        unmatched_demoted = list(xi_demoted_ids)
        for pid in unmatched_in_xi:
            pid_type = _elem_type(pid)
            match_idx = next(
                (i for i, d_pid in enumerate(unmatched_demoted) if _elem_type(d_pid) == pid_type),
                None,
            )
            if match_idx is None and unmatched_demoted:
                match_idx = 0  # formation change — cross-position displacement
            if match_idx is not None:
                xi_demoted_map[pid] = unmatched_demoted.pop(match_idx)

        optimal_squad_payload = {
            "total_xpts": ilp_result.total_xpts,
            "formation": ilp_result.formation,
            "transfers_needed": ilp_result.transfers_needed,
            "point_deduction": ilp_result.point_deduction,
            "captain": captain,
            # Real transfers: players leaving or entering the 15-man squad
            "transfers_out": [
                {**enrich_player(pid), "is_bench_player": pid not in existing_xi_set}
                for pid in out_ids
            ],
            "transfers_in": [
                {
                    **enrich_player(pid),
                    "is_xi_player": pid in optimal_xi_set,
                    # If this incoming player goes to XI and displaces an existing starter
                    "displaces": enrich_player(xi_demoted_map[pid]) if pid in xi_demoted_map else None,
                }
                for pid in in_ids
            ],
            # Free positional swaps (bench↔XI, no cost)
            "bench_swaps": bench_swaps,
            # XI players pushed to bench due to incoming transfers (for chain display)
            "xi_demoted": [enrich_player(pid) for pid in xi_demoted_ids],
            "solver_status": ilp_result.solver_status,
            "risk_preference": settings.DEFAULT_RISK_PROFILE,
        }
    except Exception as exc:
        # Non-fatal — greedy suggestions still returned
        from loguru import logger
        logger.warning(f"ILP optimal plan failed (non-fatal): {exc}")

    # ── News alerts from Redis (populated by NewsAgent during squad sync) ─────
    # Build name → alert headline map so suggestions can surface injury warnings.
    news_alerts_map: dict[str, str] = {}
    try:
        import orjson
        raw_alerts = await redis_client.zrevrange("news:injuries", 0, 99)
        for raw in raw_alerts:
            alert = orjson.loads(raw)
            name_key = alert.get("player_name", "").lower()
            if name_key and name_key not in news_alerts_map:
                news_alerts_map[name_key] = alert.get("alert", "")
    except Exception:
        pass  # Redis unavailable or empty — proceed without news annotations

    def _news_flag(web_name: str) -> str | None:
        """Return headline if player has a cached news alert, else None."""
        return news_alerts_map.get(web_name.lower())

    current_suggestions = [
        {
            "player_out": {
                "id": s.player_out.get("id"),
                "web_name": s.player_out.get("web_name"),
                "element_type": s.player_out.get("element_type"),
                "now_cost": s.player_out.get("now_cost"),
                "selling_price": effective_selling_prices.get(int(s.player_out.get("id", 0)), 0),
                "predicted_xpts_next": s.player_out.get("predicted_xpts_next"),
                "team_short_name": s.player_out.get("team_short_name"),
                "team_code": s.player_out.get("team_code"),
                "news_alert": _news_flag(s.player_out.get("web_name", "")),
            },
            "player_in": {
                "id": s.player_in.get("id"),
                "web_name": s.player_in.get("web_name"),
                "element_type": s.player_in.get("element_type"),
                "now_cost": s.player_in.get("now_cost"),
                "predicted_xpts_next": s.player_in.get("predicted_xpts_next"),
                "team_short_name": s.player_in.get("team_short_name"),
                "team_code": s.player_in.get("team_code"),
                "news_alert": _news_flag(s.player_in.get("web_name", "")),
                "selected_by_percent": s.player_in.get("selected_by_percent"),
                "predicted_start_prob": s.player_in.get("predicted_start_prob"),
                "fdr_next": s.player_in.get("fdr_next"),
                "is_home_next": s.player_in.get("is_home_next"),
                "has_double_gw": s.player_in.get("has_double_gw"),
                "form": s.player_in.get("form"),
            },
            "xpts_gain_next": s.xpts_gain_next,
            "xpts_gain_3gw": s.xpts_gain_3gw,
            "transfer_cost_pts": s.transfer_cost_pts,
            "net_gain_next": s.net_gain_next,
            "net_gain_3gw": s.net_gain_3gw,
            "recommendation": s.recommendation,
            "feasible": s.feasible,
            "reasoning": (
                s.reasoning
                + (
                    f" ⚠️ {_news_flag(s.player_in.get('web_name', ''))}"
                    if _news_flag(s.player_in.get("web_name", ""))
                    else ""
                )
            ),
        }
        for s in suggestions
    ]
    synthesized_suggestions = decision_engine.synthesize_transfer_suggestions(
        current_suggestions,
        context=DecisionContext(
            recommendation_type="transfer",
            risk_preference=settings.DEFAULT_RISK_PROFILE,
            current_gameweek=current_gw.id,
            team_id=active_team_id,
        ),
    )
    selected_suggestions = synthesized_suggestions if decision_engine.should_replace_live_output(active_team_id) else current_suggestions

    payload = {
        "free_transfers": free_transfers,
        "bank_millions": bank_pence / 10,
        # Real-time chip state — clients use this to show chip overlays / banners
        "active_chips": {
            "wildcard": wildcard_active,
            "free_hit": free_hit_active,
            "bench_boost": bench_boost_active,
            "triple_captain": triple_captain_active,
            "transfers_free": transfers_free,    # wildcard OR free hit
        },
        "suggestions": selected_suggestions,
        # Globally optimal transfer plan from ILP (null if solver failed)
        "optimal_squad": optimal_squad_payload,
        # Top-level alert summary for the UI to show a dismissable banner
        "news_alerts": [
            {"player_name": name, "headline": headline}
            for name, headline in news_alerts_map.items()
        ],
        "decision_engine_mode": settings.DECISION_ENGINE_MODE,
        "session_expires_at": session.expires_at.isoformat() if session else None,
    }
    if decision_engine.should_emit_shadow():
        payload["decision_engine_shadow"] = decision_engine.build_shadow_payload(
            current=current_suggestions,
            synthesized=synthesized_suggestions,
            label="transfers",
        )
        logger.info(
            "decision_engine_shadow_transfer",
            team_id=active_team_id,
            changed=payload["decision_engine_shadow"]["changed_top_recommendation"],
        )
    return payload

@router.post("/evaluate")
async def evaluate_transfer(
    body: TransferEvaluateRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Evaluate a specific player-out / player-in transfer."""
    active_team_id = body.team_id or settings.FPL_TEAM_ID

    result = await db.execute(select(UserBank).where(UserBank.team_id == active_team_id))
    bank = result.scalar_one_or_none()

    result = await db.execute(select(Gameweek).where(Gameweek.is_current == True))
    current_gw = result.scalar_one_or_none()

    picks = []
    if current_gw:
        result = await db.execute(
            select(UserSquad).where(
                UserSquad.team_id == active_team_id,
                UserSquad.gameweek_id == current_gw.id,
            )
        )
        picks = result.scalars().all()

    pick_out = next((p for p in picks if p.player_id == body.player_out_id), None)
    # Apply sell-on cap: if stored selling_price is 0, compute from purchase_price
    if pick_out and pick_out.selling_price > 0:
        selling_price = pick_out.selling_price
    elif pick_out and pick_out.purchase_price > 0:
        # Need now_cost — fetch the player record for the fallback
        out_player_result = await db.execute(
            select(Player).where(Player.id == body.player_out_id)
        )
        out_player = out_player_result.scalar_one_or_none()
        now = out_player.now_cost if out_player else 0
        purchase = pick_out.purchase_price
        if now > purchase:
            selling_price = purchase + (now - purchase) // 2
        else:
            selling_price = now if now > 0 else purchase
    else:
        selling_price = 0

    result = await db.execute(select(Player))
    all_players = result.scalars().all()

    import pandas as pd
    df = pd.DataFrame([{
        "id": p.id,
        "web_name": p.web_name,
        "element_type": p.element_type,
        "team_id": p.team_id,
        "now_cost": p.now_cost,
        "predicted_xpts_next": p.predicted_xpts_next,
    } for p in all_players])

    try:
        evaluation = transfer_engine.evaluate_transfer(
            player_out_id=body.player_out_id,
            player_in_id=body.player_in_id,
            players_df=df,
            bank=bank.bank if bank else 0,
            free_transfers=bank.free_transfers if bank else 1,
            selling_price=selling_price,
        )
        return {
            "xpts_gain_next": evaluation.xpts_gain_next,
            "xpts_gain_3gw": evaluation.xpts_gain_3gw,
            "net_gain_next": evaluation.net_gain_next,
            "net_gain_3gw": evaluation.net_gain_3gw,
            "transfer_cost_pts": evaluation.transfer_cost_pts,
            "recommendation": evaluation.recommendation,
            "feasible": evaluation.feasible,
            "shortfall_millions": evaluation.shortfall / 10,
            "reasoning": evaluation.reasoning,
        }
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/bank")
async def get_bank(
    team_id: int | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    """Get financial state: free transfers, bank, selling prices."""
    active_team_id = team_id or settings.FPL_TEAM_ID
    result = await db.execute(select(UserBank).where(UserBank.team_id == active_team_id))
    bank = result.scalar_one_or_none()

    if not bank:
        return {"free_transfers": 1, "bank_millions": 0, "team_value_millions": 100.0}

    result = await db.execute(select(Gameweek).where(Gameweek.is_current == True))
    current_gw = result.scalar_one_or_none()

    selling_prices = {}
    if current_gw:
        result = await db.execute(
            select(UserSquad).where(
                UserSquad.team_id == active_team_id,
                UserSquad.gameweek_id == current_gw.id,
            )
        )
        picks = result.scalars().all()
        selling_prices = {p.player_id: p.selling_price / 10 for p in picks}

    return {
        "free_transfers": bank.free_transfers,
        "bank_millions": bank.bank / 10,
        "team_value_millions": bank.value / 10,
        "overall_rank": bank.overall_rank,
        "total_points": bank.total_points,
        "selling_prices": selling_prices,
    }


@router.get("/bench-swaps")
async def get_bench_swap_suggestions(
    team_id: int | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    """
    Suggest bench-to-XI swaps that improve your starting XI xPts without a transfer.

    Evaluates all valid bench↔XI position swaps (formation-preserving) and
    returns the best ones ranked by xPts gain. A swap is valid when:
    - GK can only swap with GK
    - Outfield swaps must keep the XI formation valid (min 3 DEF, 2 MID, 1 FWD)
    """
    active_team_id = team_id or settings.FPL_TEAM_ID
    if not active_team_id:
        raise HTTPException(400, "No team_id provided")

    result = await db.execute(select(Gameweek).where(Gameweek.is_current == True))
    current_gw = result.scalar_one_or_none()
    if not current_gw:
        raise HTTPException(404, "No active gameweek")

    # Squad picks are always stored under is_current GW (even between GWs)
    gw_id = current_gw.id

    result = await db.execute(
        select(UserSquad).where(
            UserSquad.team_id == active_team_id,
            UserSquad.gameweek_id == gw_id,
        )
    )
    picks = result.scalars().all()
    if not picks:
        raise HTTPException(404, "No squad found")

    # Load all 15 players
    player_map: dict[int, Player] = {}
    for pick in picks:
        pl = await db.get(Player, pick.player_id)
        if pl:
            player_map[pick.player_id] = pl

    # Separate into XI (pos 1-11) and bench (pos 12-15)
    xi_picks   = [p for p in picks if p.position <= 11]
    bench_picks = [p for p in picks if p.position > 11]

    def get_xpts(player_id: int) -> float:
        pl = player_map.get(player_id)
        return float(pl.predicted_xpts_next or 0) if pl else 0.0

    def get_pos(player_id: int) -> int:
        pl = player_map.get(player_id)
        return pl.element_type if pl else 0

    def formation_valid(xi_player_ids: list[int]) -> bool:
        """Check 3-4-3 min: ≥3 DEF, ≥2 MID, ≥1 FWD (1 GK always)."""
        counts = {1: 0, 2: 0, 3: 0, 4: 0}
        for pid in xi_player_ids:
            counts[get_pos(pid)] = counts.get(get_pos(pid), 0) + 1
        return counts[2] >= 3 and counts[3] >= 2 and counts[4] >= 1

    current_xi_ids  = [p.player_id for p in xi_picks]
    current_xi_xpts = sum(get_xpts(pid) for pid in current_xi_ids)

    swaps = []
    for bench_pick in bench_picks:
        bench_id  = bench_pick.player_id
        bench_pos = get_pos(bench_id)
        bench_pts = get_xpts(bench_id)

        for xi_pick in xi_picks:
            xi_id  = xi_pick.player_id
            xi_pos = get_pos(xi_id)
            xi_pts = get_xpts(xi_id)

            # Positions must match (GK↔GK only; outfield position-flexible but formation-valid)
            if bench_pos == 1 and xi_pos != 1:
                continue
            if bench_pos != 1 and xi_pos == 1:
                continue

            gain = bench_pts - xi_pts
            if gain <= 0:
                continue

            # Check formation remains valid after swap
            candidate_xi = [pid for pid in current_xi_ids if pid != xi_id] + [bench_id]
            if not formation_valid(candidate_xi):
                continue

            bench_player = player_map.get(bench_id)
            xi_player    = player_map.get(xi_id)
            swaps.append({
                "bench_out_id":         xi_id,
                "bench_out_name":       xi_player.web_name if xi_player else str(xi_id),
                "bench_out_team_code":  xi_player.team_code if xi_player else None,
                "bench_in_id":          bench_id,
                "bench_in_name":        bench_player.web_name if bench_player else str(bench_id),
                "bench_in_team_code":   bench_player.team_code if bench_player else None,
                "xi_xpts":              round(xi_pts, 2),
                "bench_xpts":           round(bench_pts, 2),
                "xpts_gain":            round(gain, 2),
                "reason":               (
                    f"Start {bench_player.web_name if bench_player else bench_id} "
                    f"({bench_pts:.1f} xPts) instead of "
                    f"{xi_player.web_name if xi_player else xi_id} "
                    f"({xi_pts:.1f} xPts) — +{gain:.1f} xPts"
                ),
            })

    # Sort by gain descending, deduplicate (one per bench player, one per xi player)
    swaps.sort(key=lambda s: s["xpts_gain"], reverse=True)
    seen_in: set[int]  = set()
    seen_out: set[int] = set()
    best_swaps = []
    for swap in swaps:
        if swap["bench_in_id"] not in seen_in and swap["bench_out_id"] not in seen_out:
            seen_in.add(swap["bench_in_id"])
            seen_out.add(swap["bench_out_id"])
            best_swaps.append(swap)

    return {
        "gameweek": gw_id,
        "current_xi_xpts": round(current_xi_xpts, 2),
        "swaps": best_swaps,
    }


@router.get("/bench-transfer-xi")
async def get_bench_transfer_xi_suggestions(
    team_id: int | None = None,
    top_n: int = 4,
    db: AsyncSession = Depends(get_db_session),
):
    """
    Suggest bench-player → transfer → XI upgrade moves.

    Flow: Transfer a low-value bench player (B) out of squad →
    bring in a high-xPts player (X) → start X in XI in place of a
    weak XI player (W) who drops to bench.

    Key difference from a standard W→X transfer: budget uses B's
    selling price, not W's. Useful when B is a cheap/useless bench
    occupier and you want to upgrade the XI without losing W entirely.
    """
    active_team_id = team_id or settings.FPL_TEAM_ID
    if not active_team_id:
        raise HTTPException(400, "No team_id provided")

    result = await db.execute(select(Gameweek).where(Gameweek.is_current == True))
    current_gw = result.scalar_one_or_none()
    if not current_gw:
        raise HTTPException(404, "No active gameweek")

    # Load squad
    result = await db.execute(
        select(UserSquad).where(
            UserSquad.team_id == active_team_id,
            UserSquad.gameweek_id == current_gw.id,
        )
    )
    picks = result.scalars().all()
    if not picks:
        raise HTTPException(404, "No squad found. Run /api/squad/sync first.")

    result = await db.execute(select(UserBank).where(UserBank.team_id == active_team_id))
    bank = result.scalar_one_or_none()
    bank_pence = bank.bank if bank else 0
    free_transfers = bank.free_transfers if bank else 1

    # Load all players + teams
    result = await db.execute(select(Player))
    all_players = result.scalars().all()
    result_teams = await db.execute(select(Team))
    _t = result_teams.scalars().all()
    tl: dict[int, Team] = {t.id: t for t in _t}

    player_map: dict[int, Player] = {p.id: p for p in all_players}
    # Squad player map
    squad_player_map: dict[int, Player] = {}
    for pick in picks:
        p = player_map.get(pick.player_id)
        if p:
            squad_player_map[pick.player_id] = p

    xi_picks    = [p for p in picks if p.position <= 11]
    bench_picks = [p for p in picks if p.position > 11]

    # Selling prices per pick
    selling_prices = {p.player_id: p.selling_price for p in picks}
    purchase_prices = {p.player_id: p.purchase_price for p in picks}

    def sell_price(pid: int) -> int:
        stored = selling_prices.get(pid, 0)
        if stored > 0:
            return stored
        purchase = purchase_prices.get(pid, 0)
        now = player_map.get(pid, None)
        now_cost = now.now_cost if now else 0
        if purchase > 0 and now_cost > purchase:
            return purchase + (now_cost - purchase) // 2
        return now_cost if now_cost > 0 else purchase

    squad_ids = {p.player_id for p in picks}
    xi_ids    = {p.player_id for p in xi_picks}

    def get_xpts(pid: int) -> float:
        p = player_map.get(pid)
        return float(p.predicted_xpts_next or 0) if p else 0.0

    def get_pos(pid: int) -> int:
        p = player_map.get(pid)
        return p.element_type if p else 0

    def team_badge(tid: int) -> tuple[str | None, int | None]:
        t = tl.get(tid)
        return (t.short_name if t else None, t.code if t else None)

    def formation_valid_xi(xi_player_ids: list[int]) -> bool:
        counts = {1: 0, 2: 0, 3: 0, 4: 0}
        for pid in xi_player_ids:
            counts[get_pos(pid)] = counts.get(get_pos(pid), 0) + 1
        return counts[2] >= 3 and counts[3] >= 2 and counts[4] >= 1

    # Transfer cost (pts deduction for a hit)
    # 0 if within free transfers, else -4 per extra transfer
    hit_cost_pts = max(0, 1 - free_transfers) * 4  # 1 transfer used

    suggestions = []

    # Candidate transfer-in players: available, not in squad, same position group
    available_players = [
        p for p in all_players
        if p.status == "a"
        and p.id not in squad_ids
        and p.now_cost > 0
        and p.predicted_xpts_next is not None
        and p.predicted_xpts_next > 0
        and float(p.form or 0) >= 1.0
    ]

    for bench_pick in bench_picks:
        bench_id   = bench_pick.player_id
        bench_pos  = get_pos(bench_id)
        b_sell     = sell_price(bench_id)
        bench_name = squad_player_map.get(bench_id)
        bench_name_str = bench_name.web_name if bench_name else str(bench_id)
        bench_tsn, bench_tc = team_badge(bench_name.team_id if bench_name else 0)

        # Budget available if we sell bench player
        budget_for_new = bank_pence + b_sell

        # Find top transfer-in candidates for this bench player's position
        position_candidates = [
            p for p in available_players
            if p.element_type == bench_pos
            and p.now_cost <= budget_for_new
        ]
        position_candidates.sort(key=lambda p: float(p.predicted_xpts_next or 0), reverse=True)

        for transfer_in_player in position_candidates[:10]:
            xpts_in = float(transfer_in_player.predicted_xpts_next or 0)
            cost    = transfer_in_player.now_cost
            leftover_bank = budget_for_new - cost

            # Find the weakest XI player at the same position to swap out
            xi_same_pos = [
                p for p in xi_picks
                if get_pos(p.player_id) == bench_pos or (bench_pos != 1 and get_pos(p.player_id) != 1)
            ]
            if bench_pos == 1:
                # GK only swaps with GK
                xi_same_pos = [p for p in xi_picks if get_pos(p.player_id) == 1]
            else:
                xi_same_pos = [p for p in xi_picks if get_pos(p.player_id) != 1]

            if not xi_same_pos:
                continue

            # Best swap: XI player with lowest xPts
            xi_same_pos.sort(key=lambda p: get_xpts(p.player_id))
            weakest_xi_pick = xi_same_pos[0]
            weakest_xi_id   = weakest_xi_pick.player_id
            xpts_weak_xi    = get_xpts(weakest_xi_id)
            xi_player       = squad_player_map.get(weakest_xi_id)
            xi_name_str     = xi_player.web_name if xi_player else str(weakest_xi_id)
            xi_tsn, xi_tc   = team_badge(xi_player.team_id if xi_player else 0)

            # Validate formation after swap (new_player takes xi slot of weakest, weakest to bench)
            candidate_xi = [p.player_id for p in xi_picks if p.player_id != weakest_xi_id] + [transfer_in_player.id]
            if not formation_valid_xi(candidate_xi):
                continue

            # XI gain = new player xPts - weakest xi xPts
            xi_gain      = xpts_in - xpts_weak_xi
            net_gain     = xi_gain - hit_cost_pts
            if net_gain <= 0:
                continue  # Not worth it

            in_tsn, in_tc = team_badge(transfer_in_player.team_id)

            suggestions.append({
                "bench_out": {
                    "id": bench_id,
                    "web_name": bench_name_str,
                    "element_type": bench_pos,
                    "now_cost": bench_name.now_cost if bench_name else 0,
                    "selling_price": b_sell,
                    "predicted_xpts_next": get_xpts(bench_id),
                    "team_short_name": bench_tsn,
                    "team_code": bench_tc,
                },
                "transfer_in": {
                    "id": transfer_in_player.id,
                    "web_name": transfer_in_player.web_name,
                    "element_type": transfer_in_player.element_type,
                    "now_cost": cost,
                    "predicted_xpts_next": xpts_in,
                    "team_short_name": in_tsn,
                    "team_code": in_tc,
                },
                "xi_swap_out": {
                    "id": weakest_xi_id,
                    "web_name": xi_name_str,
                    "element_type": get_pos(weakest_xi_id),
                    "predicted_xpts_next": xpts_weak_xi,
                    "team_short_name": xi_tsn,
                    "team_code": xi_tc,
                },
                "xi_gain": round(xi_gain, 2),
                "net_gain": round(net_gain, 2),
                "hit_cost_pts": hit_cost_pts,
                "cost_millions": round(cost / 10, 1),
                "budget_after_millions": round(leftover_bank / 10, 1),
                "feasible": leftover_bank >= 0,
                "reasoning": (
                    f"Sell {bench_name_str} (bench, £{b_sell/10:.1f}m) → "
                    f"buy {transfer_in_player.web_name} (£{cost/10:.1f}m, {xpts_in:.1f} xPts) → "
                    f"start {transfer_in_player.web_name} instead of {xi_name_str} "
                    f"({xpts_weak_xi:.1f} xPts). XI gain: +{xi_gain:.1f} xPts"
                    + (f", −{hit_cost_pts}pt hit" if hit_cost_pts > 0 else " (free transfer)")
                ),
            })

    # Sort by net_gain descending, keep only feasible
    suggestions = [s for s in suggestions if s["feasible"]]
    suggestions.sort(key=lambda s: s["net_gain"], reverse=True)

    # Deduplicate: one suggestion per bench_out player
    seen_bench: set[int] = set()
    best = []
    for s in suggestions:
        bid = s["bench_out"]["id"]
        if bid not in seen_bench:
            seen_bench.add(bid)
            best.append(s)
            if len(best) >= top_n:
                break

    return {
        "gameweek": current_gw.id,
        "suggestions": best,
    }
