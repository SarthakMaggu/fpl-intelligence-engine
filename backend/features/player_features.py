"""
Player Feature Store — build and persist per-player feature snapshots per GW.

build_features_for_gw(gw_id)  — assembles the full feature dict from DB + Redis
update_latest_features(gw_id, features)  — upserts into the feature store tables

Called from scheduler.py after each pipeline run so that backtest and evaluation
can replay the exact features that were available at prediction time.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import orjson
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.db.feature_store import PlayerFeaturesHistory, PlayerFeaturesLatest
from models.db.player import Player

logger = logging.getLogger(__name__)


async def build_features_for_gw(
    gw_id: int,
    db: AsyncSession,
    redis,
) -> Dict[int, Dict[str, Any]]:
    """
    Assemble the full feature dictionary for all active players for a given GW.

    Sources merged (in priority order):
    1. players table  — xpts, form, price, element_type, fixture signals
    2. player_gw_history — rolling 5-GW stats (via existing DB query)
    3. Redis news:sentiment — live sentiment per player name
    4. Redis ml:calibration_map — per-(position, price_band) residual corrections

    Returns:
        {player_id: {feature_name: value, ...}}
    """
    features: Dict[int, Dict[str, Any]] = {}

    # ── 1. Base features from players table ─────────────────────────────────
    result = await db.execute(
        select(Player).where(Player.status != "u")  # exclude unavailable
    )
    players = result.scalars().all()

    for p in players:
        features[p.id] = {
            "player_id": p.id,
            "team_id": p.team_id,          # FPL team ID — used for fixture congestion lookup
            "web_name": p.web_name,
            "element_type": p.element_type,
            "price_millions": float(p.now_cost or 0) / 10.0,
            "price_band": int(float(p.now_cost or 0) / 10.0),
            "form": float(p.form or 0.0),
            "points_per_game": float(p.points_per_game or 0.0),
            "selected_by_percent": float(p.selected_by_percent or 0.0),
            "ownership": float(p.selected_by_percent or 0.0),
            "predicted_xpts_next": float(p.predicted_xpts_next or 0.0),
            "xg_per_90": float(p.expected_goals_per_90 or 0.0),
            "xa_per_90": float(p.expected_assists_per_90 or 0.0),
            "rolling_xg": 0.0,
            "rolling_xa": 0.0,
            "shots": float(p.threat or 0.0),
            "key_passes": float(p.creativity or 0.0),
            "team_attacking_strength": 0.0,
            "team_defensive_strength": 0.0,
            "fixture_difficulty": float(p.fdr_next or 3.0),
            "home_away": 1 if p.is_home_next else 0,
            "ict_index": float(p.ict_index or 0.0),
            "transfers_in_event_delta": float(p.transfers_in_event or 0),
            "suspension_risk": float(p.suspension_risk or 0.0),
            "rotation_risk": 0.0,
            "injury_risk": 1.0 - float((p.chance_of_playing_next_round or 100) / 100.0),
            "availability_probability": float((p.chance_of_playing_next_round or 100) / 100.0),
            "expected_minutes": float(p.predicted_start_prob or 0.0) * 75.0,
            # Blank/DGW flags (set elsewhere in pipeline, default 0)
            "blank_gw": 0,
            "double_gw": 0,
            # News
            "news_sentiment": 0.0,
            "news_article_count": 0,
            # Rolling 5-GW (filled below)
            "xg_last_5_gws": 0.0,
            "xa_last_5_gws": 0.0,
            "goals_last_5_gws": 0.0,
            "cs_last_5_gws": 0.0,
            "pts_last_5_gws": 0.0,
            "minutes_trend": 1.0,
        }

    # ── 2. Rolling 5-GW stats from player_gw_history ────────────────────────
    try:
        rolling_sql = text("""
            SELECT
                element,
                SUM(expected_goals)   AS xg_last_5,
                SUM(expected_assists) AS xa_last_5,
                SUM(goals_scored)     AS goals_last_5,
                SUM(clean_sheets)     AS cs_last_5,
                SUM(total_points)     AS pts_last_5,
                AVG(minutes)          AS avg_minutes_last_5
            FROM (
                SELECT *,
                    ROW_NUMBER() OVER (PARTITION BY element ORDER BY event DESC) AS rn
                FROM player_gw_history
                WHERE event < :gw_id
            ) ranked
            WHERE rn <= 5
            GROUP BY element
        """)
        rolling_res = await db.execute(rolling_sql, {"gw_id": gw_id})
        for row in rolling_res.mappings():
            pid = row["element"]
            if pid in features:
                features[pid]["xg_last_5_gws"] = float(row["xg_last_5"] or 0.0)
                features[pid]["xa_last_5_gws"] = float(row["xa_last_5"] or 0.0)
                features[pid]["rolling_xg"] = float(row["xg_last_5"] or 0.0)
                features[pid]["rolling_xa"] = float(row["xa_last_5"] or 0.0)
                features[pid]["goals_last_5_gws"] = float(row["goals_last_5"] or 0.0)
                features[pid]["cs_last_5_gws"] = float(row["cs_last_5"] or 0.0)
                features[pid]["pts_last_5_gws"] = float(row["pts_last_5"] or 0.0)
                # Compute minutes trend vs previous 5 GWs (rough proxy)
                avg_min = float(row["avg_minutes_last_5"] or 60.0)
                features[pid]["minutes_trend"] = min(avg_min / 60.0, 2.0)
    except Exception as e:
        logger.warning(f"[feature_store] Rolling stats query failed: {e}")

    # ── 3. News sentiment from Redis ─────────────────────────────────────────
    try:
        if redis:
            sentiment_raw = await redis.get("news:sentiment")
            if sentiment_raw:
                smap = orjson.loads(sentiment_raw)
                for pid, feat in features.items():
                    name = feat.get("web_name", "")
                    if name in smap:
                        feat["news_sentiment"] = float(smap[name].get("sentiment", 0.0))
                        feat["news_article_count"] = int(smap[name].get("article_count", 0))
    except Exception as e:
        logger.warning(f"[feature_store] Sentiment Redis fetch failed: {e}")

    # ── 4. Competition fixture congestion → rotation_risk boost ─────────────
    # Checks UCL / FAC / UEL games within 3 days of the GW deadline.
    # Adds 0.20–0.50 rotation risk boost for congested teams.
    try:
        from services.competition_fixtures import get_fixture_congestion_scores

        # Build set of unique FPL team IDs across all active players
        team_ids_set = {
            int(feat.get("team_id", 0) or 0)
            for feat in features.values()
            if feat.get("team_id")
        }

        # Fallback: look up team IDs from Player table in this session
        if not team_ids_set:
            team_result = await db.execute(
                select(Player.id, Player.team_id).where(Player.status != "u")
            )
            pid_to_team = {row[0]: row[1] for row in team_result.fetchall()}
            # Attach team to feature dict if missing
            for pid, feat in features.items():
                if pid in pid_to_team:
                    feat["team_id"] = pid_to_team[pid]
            team_ids_set = {t for t in pid_to_team.values() if t}

        if team_ids_set:
            congestion_map = await get_fixture_congestion_scores(list(team_ids_set), db)
            for feat in features.values():
                tid = int(feat.get("team_id", 0) or 0)
                boost = congestion_map.get(tid, 0.0)
                if boost > 0.0:
                    existing = float(feat.get("rotation_risk", 0.0) or 0.0)
                    # Combine but cap at 1.0: higher of the two risks wins, then add
                    # partial of the other to avoid double-counting
                    feat["rotation_risk"] = min(max(existing, boost) + min(existing, boost) * 0.3, 1.0)
    except Exception as e:
        logger.warning(f"[feature_store] Competition fixture congestion lookup failed: {e}")

    # ── 5. Add gw_id to each feature dict ────────────────────────────────────
    for feat in features.values():
        feat["gw_id"] = gw_id
        feat["rotation_risk"] = float(feat.get("rotation_risk_score", feat.get("rotation_risk", 0.0)) or 0.0)

    logger.info(
        f"[feature_store] Built features for GW{gw_id}: {len(features)} players"
    )
    return features


async def update_latest_features(
    gw_id: int,
    features: Dict[int, Dict[str, Any]],
    db: AsyncSession,
) -> None:
    """
    Persist feature snapshot:
    - UPSERT into player_features_latest (one row per player, overwritten)
    - INSERT IGNORE into player_features_history (one row per player+gw, append-only)
    """
    if not features:
        return

    now = datetime.now(timezone.utc)
    batch_size = 100

    player_ids = list(features.keys())

    # Process in batches to avoid overwhelming the DB
    for i in range(0, len(player_ids), batch_size):
        batch = player_ids[i : i + batch_size]

        for pid in batch:
            feat = features[pid]

            # Upsert into player_features_latest
            latest_stmt = (
                pg_insert(PlayerFeaturesLatest)
                .values(
                    player_id=pid,
                    gw_id=gw_id,
                    features_json=feat,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["player_id"],
                    set_={
                        "gw_id": gw_id,
                        "features_json": feat,
                        "updated_at": now,
                    },
                )
            )
            await db.execute(latest_stmt)

            # Insert into player_features_history (skip if already exists for this GW + season)
            history_stmt = (
                pg_insert(PlayerFeaturesHistory)
                .values(
                    player_id=pid,
                    gw_id=gw_id,
                    season="2024-25",   # current season — historical seasons use historical_backfill
                    features_json=feat,
                    created_at=now,
                )
                .on_conflict_do_nothing(constraint="uq_pfh_player_gw_season")
            )
            await db.execute(history_stmt)

        await db.commit()

    logger.info(
        f"[feature_store] Persisted features for GW{gw_id}: "
        f"{len(features)} players to latest + history tables"
    )
