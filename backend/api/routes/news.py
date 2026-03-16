"""
News API — exposes articles, injury alerts, and player sentiment from the news pipeline.

GET /api/news/articles      — recent articles from all sources
GET /api/news/alerts        — injury alerts mentioning FPL players
GET /api/news/sentiment     — per-player sentiment scores
GET /api/news/player/{name} — news + sentiment for a specific player
POST /api/news/refresh      — trigger a manual news refresh
"""
from __future__ import annotations

from fastapi import APIRouter, Query
from loguru import logger

router = APIRouter()

API = "http://localhost:8000"


@router.get("/articles")
async def get_articles(limit: int = Query(40, le=200)):
    """Recent articles from all sources, newest first."""
    try:
        from agents.news_agent import NewsAgent
        agent = NewsAgent()
        articles = await agent.get_recent_articles(limit=limit)
        return {
            "total": len(articles),
            "articles": articles,
        }
    except Exception as e:
        logger.error(f"get_articles: {e}")
        return {"total": 0, "articles": [], "error": str(e)}


@router.get("/alerts")
async def get_alerts(limit: int = Query(20, le=100)):
    """Most recent player injury/availability alerts."""
    try:
        from agents.news_agent import NewsAgent
        agent = NewsAgent()
        alerts = await agent.get_recent_alerts(limit=limit)
        return {
            "total": len(alerts),
            "alerts": alerts,
        }
    except Exception as e:
        logger.error(f"get_alerts: {e}")
        return {"total": 0, "alerts": [], "error": str(e)}


@router.get("/sentiment")
async def get_sentiment():
    """Per-player sentiment scores derived from recent news."""
    try:
        from agents.news_agent import NewsAgent
        agent = NewsAgent()
        data = await agent.get_player_sentiment()
        # Sort by absolute sentiment magnitude (most newsworthy first)
        sorted_players = sorted(
            [{"player": k, **v} for k, v in data.items()],
            key=lambda x: abs(x.get("sentiment", 0)),
            reverse=True,
        )
        return {
            "total_players": len(sorted_players),
            "players": sorted_players,
        }
    except Exception as e:
        logger.error(f"get_sentiment: {e}")
        return {"total_players": 0, "players": [], "error": str(e)}


@router.get("/player/{player_name}")
async def get_player_news(player_name: str):
    """News and sentiment for a specific player."""
    try:
        from agents.news_agent import NewsAgent
        agent = NewsAgent()
        sentiment = await agent.get_player_sentiment(player_name)
        alerts = await agent.get_recent_alerts(limit=100)
        player_alerts = [a for a in alerts if a.get("player_name", "").lower() == player_name.lower()]
        return {
            "player": player_name,
            "sentiment": sentiment,
            "alerts": player_alerts[:10],
        }
    except Exception as e:
        logger.error(f"get_player_news {player_name}: {e}")
        return {"player": player_name, "sentiment": {}, "alerts": [], "error": str(e)}


@router.post("/refresh")
async def refresh_news():
    """
    Manually trigger a full news pipeline run.
    Fetches player list from DB, then runs the full news agent.
    """
    try:
        from core.database import get_db
        from models.db.player import Player
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession
        from core.database import engine
        from agents.news_agent import NewsAgent

        # Get player names from DB
        async with engine.begin() as conn:
            from sqlalchemy.future import select as sa_select
            result = await conn.execute(
                sa_select(Player.web_name).where(Player.status == "a").limit(700)
            )
            player_names = [row[0] for row in result.fetchall()]

        if not player_names:
            # Fallback: use bootstrap endpoint
            import httpx
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(
                    "https://fantasy.premierleague.com/api/bootstrap-static/",
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if r.status_code == 200:
                    elements = r.json().get("elements", [])
                    player_names = [e.get("web_name", "") for e in elements][:700]

        agent = NewsAgent()
        alerts = await agent.run(player_names)
        articles = await agent.get_recent_articles(limit=10)

        return {
            "status": "ok",
            "players_tracked": len(player_names),
            "alerts_generated": len(alerts),
            "sources": ["reddit", "bbc_sport", "sky_sports", "guardian", "premier_league",
                        "fpl_review", "fantasy_football_scout", "planet_fpl"],
        }
    except Exception as e:
        logger.error(f"refresh_news: {e}")
        return {"status": "error", "error": str(e)}


@router.post("/retrain-model")
async def retrain_model():
    """
    Trigger a manual historical model retrain.
    Downloads vaastav FPL dataset (last 3 seasons) + retrains xPts LightGBM model.
    This runs in the background — returns immediately with a job ID.
    """
    import asyncio

    async def _retrain_bg():
        try:
            from data_pipeline.historical_fetcher import HistoricalFetcher
            async with HistoricalFetcher() as fetcher:
                metrics = await fetcher.retrain_xpts_model()
            logger.info(f"Manual retrain complete: {metrics}")
        except Exception as e:
            logger.error(f"Manual retrain failed: {e}")

    asyncio.create_task(_retrain_bg())
    return {
        "status": "started",
        "message": "Historical model retrain started in background. "
                   "Check logs for completion status.",
    }


@router.get("/oracle-learning")
async def get_oracle_learning():
    """Get Oracle ML learner summary — win rate vs top team, blind spots, bias adjustments."""
    try:
        from agents.oracle_learner import OracleLearner
        learner = OracleLearner()
        return learner.get_summary()
    except Exception as e:
        return {"error": str(e)}
