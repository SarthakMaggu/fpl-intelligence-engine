"""
Market Intelligence — ownership trends, price risers/fallers, differential alerts.

GET /api/market/trends
  Returns most-transferred-in/out, ownership risers, high-value differentials.

All data is sourced from the Player model (updated by the data pipeline).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, asc

from core.database import get_db
from models.db.player import Player
from models.db.team import Team

router = APIRouter()


@router.get("/trends")
async def get_market_trends(
    top_n: int = 10,
    db: AsyncSession = Depends(get_db),
):
    """
    Market intelligence snapshot:
      - most_transferred_in:  top N by transfers_in_event
      - most_transferred_out: top N by transfers_out_event
      - ownership_risers:     players with fastest selected_by_percent growth (proxy: high transfers_in)
      - differentials:        low ownership (<5%) but high xPts
      - must_haves:           high ownership (>40%) + high xPts
    """
    result = await db.execute(select(Player).where(Player.status != "u"))
    players: list[Player] = result.scalars().all()

    # Build team lookup for short_name + badge code
    result_teams = await db.execute(select(Team))
    team_lookup: dict[int, Team] = {t.id: t for t in result_teams.scalars().all()}

    def to_dict(p: Player, extra: dict | None = None) -> dict:
        team = team_lookup.get(p.team_id)
        base = {
            "id": p.id,
            "web_name": p.web_name,
            "element_type": p.element_type,
            "team_short_name": team.short_name if team else None,
            "team_code": team.code if team else None,
            "now_cost": p.now_cost,
            "price_millions": round(p.now_cost / 10, 1) if p.now_cost else None,
            "selected_by_percent": float(p.selected_by_percent or 0),
            "transfers_in_event": p.transfers_in_event or 0,
            "transfers_out_event": p.transfers_out_event or 0,
            "predicted_xpts_next": p.predicted_xpts_next,
            "form": p.form,
            "status": p.status,
            "news": p.news,
            "has_double_gw": p.has_double_gw,
            "has_blank_gw": p.has_blank_gw,
        }
        if extra:
            base.update(extra)
        return base

    # Sort lists
    by_transfers_in = sorted(players, key=lambda p: -(p.transfers_in_event or 0))
    by_transfers_out = sorted(players, key=lambda p: -(p.transfers_out_event or 0))

    # Differentials: low ownership (<5%) and reasonably high xPts (≥3.5)
    differentials = [
        p for p in players
        if float(p.selected_by_percent or 0) < 5.0
        and (p.predicted_xpts_next or 0) >= 3.5
        and p.status == "a"
    ]
    differentials.sort(key=lambda p: -(p.predicted_xpts_next or 0))

    # Must-haves: high ownership (≥30%) + high xPts (≥4.5)
    must_haves = [
        p for p in players
        if float(p.selected_by_percent or 0) >= 30.0
        and (p.predicted_xpts_next or 0) >= 4.5
    ]
    must_haves.sort(key=lambda p: -(p.predicted_xpts_next or 0))

    # Price direction signals — actual price changes first, then transfer-momentum proxy
    price_risers = [
        p for p in players
        if (p.predicted_price_direction or 0) > 0
        and p.status == "a"
    ]
    price_risers.sort(key=lambda p: -(p.predicted_xpts_next or 0))

    # Fallback: no actual changes yet this GW — use net transfer inflow as "approaching rise"
    if not price_risers:
        price_risers = [
            p for p in players
            if (p.transfers_in_event or 0) > (p.transfers_out_event or 0)
            and p.status == "a"
        ]
        price_risers.sort(key=lambda p: -((p.transfers_in_event or 0) - (p.transfers_out_event or 0)))

    price_fallers = [
        p for p in players
        if (p.predicted_price_direction or 0) < 0
    ]
    price_fallers.sort(key=lambda p: -(p.transfers_out_event or 0))

    # Fallback: no actual changes yet this GW — use net transfer outflow as "approaching fall"
    if not price_fallers:
        price_fallers = [
            p for p in players
            if (p.transfers_out_event or 0) > (p.transfers_in_event or 0)
        ]
        price_fallers.sort(key=lambda p: -((p.transfers_out_event or 0) - (p.transfers_in_event or 0)))

    return {
        "most_transferred_in": [to_dict(p) for p in by_transfers_in[:top_n]],
        "most_transferred_out": [to_dict(p) for p in by_transfers_out[:top_n]],
        "differentials": [to_dict(p) for p in differentials[:top_n]],
        "must_haves": [to_dict(p) for p in must_haves[:top_n]],
        "price_risers": [to_dict(p) for p in price_risers[:top_n]],
        "price_fallers": [to_dict(p) for p in price_fallers[:top_n]],
        "summary": {
            "total_players_analyzed": len(players),
            "differentials_count": len(differentials),
            "must_haves_count": len(must_haves),
            "price_risers_count": len(price_risers),
            "price_fallers_count": len(price_fallers),
        },
    }
