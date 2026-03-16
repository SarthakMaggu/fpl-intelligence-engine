"""
DataFetcher — main orchestrator for the full data pipeline.

Uses Redis SETNX lock (same pattern as war-intel-dashboard) to prevent
concurrent pipeline runs.

Pipeline steps:
1. Bootstrap (players, teams, GWs)
2. Fixtures (all GWs + blank/double detection)
3. User squad picks + bank state
4. xG/xA from understat (parallel with step 5)
5. News scrape (Reddit + BBC RSS)
6. ML model predictions (minutes → xPts → price)
7. Odds (if API key configured)
"""
import asyncio
import httpx
import numpy as np
import pandas as pd
from loguru import logger
from datetime import datetime

from core.config import settings
from core.redis_client import acquire_lock, release_lock, redis_client
from core.exceptions import PipelineRunningError
from core.database import AsyncSessionLocal

from agents.fpl_agent import FPLAgent
from agents.stats_agent import StatsAgent
from agents.news_agent import NewsAgent
from agents.odds_agent import OddsAgent
from data_pipeline.processor import DataProcessor
from models.ml.xpts_model import XPtsModel
from models.ml.minutes_model import MinutesModel
from models.ml.price_model import PriceModel
from models.db.prediction import Prediction
from services.versioning_service import (
    create_data_snapshot,
    get_or_create_feature_version,
    get_or_create_model_version,
)

PIPELINE_LOCK_KEY = "fpl:pipeline:lock"
PIPELINE_LOCK_TTL = 300  # 5 minutes max
LAST_RUN_KEY = "fpl:pipeline:last_run"


class DataFetcher:
    def __init__(self):
        self.processor = DataProcessor()
        self.xpts_model = XPtsModel()
        self.minutes_model = MinutesModel()
        self.price_model = PriceModel()
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                http2=True,
                timeout=30.0,
                limits=httpx.Limits(max_connections=10),
            )
        return self._client

    async def run_full_pipeline(self, team_id: int | None = None) -> dict:
        """
        Full data pipeline. Returns summary of operations.
        Redis lock prevents concurrent runs (same as war-intel-dashboard pattern).
        """
        lock_acquired = await acquire_lock(PIPELINE_LOCK_KEY, PIPELINE_LOCK_TTL)
        if not lock_acquired:
            raise PipelineRunningError("Pipeline already running — try again in a few minutes")

        summary = {"started_at": datetime.utcnow().isoformat()}
        client = self._get_client()
        fpl_agent = FPLAgent(client)
        stats_agent = StatsAgent(client)
        news_agent = NewsAgent()
        odds_agent = OddsAgent(client)

        try:
            async with AsyncSessionLocal() as snapshot_db:
                data_snapshot = await create_data_snapshot(snapshot_db, source="weekly_pipeline")
            summary["data_snapshot_id"] = data_snapshot.id
            # ── Step 0: Invalidate stale caches ───────────────────────────────
            # Force-fresh on every manual sync so we never serve stale GW data.
            active_team_id = team_id or settings.FPL_TEAM_ID
            logger.info("Pipeline: invalidating stale Redis caches")
            await fpl_agent.invalidate_bootstrap_cache()
            await redis_client.delete("fpl:fixtures:all")
            if active_team_id:
                await redis_client.delete(f"fpl:entry:{active_team_id}")
                await redis_client.delete(f"fpl:history:{active_team_id}")

            # ── Step 1: Bootstrap ─────────────────────────────────────────────
            logger.info("Pipeline: fetching bootstrap-static")
            bootstrap = await fpl_agent.get_bootstrap()

            teams_count = await self.processor.upsert_teams(bootstrap)
            gw_count = await self.processor.upsert_gameweeks(bootstrap)
            logger.info(f"Pipeline: {teams_count} teams, {gw_count} GWs upserted")

            # Determine which GW to use for squad picks.
            # Between GWs: if is_current is already finished, prefer is_next
            # so we see the squad the user is building for the upcoming GW.
            events = bootstrap.get("events", [])
            current_event = next((e for e in events if e.get("is_current")), None)
            next_event    = next((e for e in events if e.get("is_next")), None)

            current_gw = current_event["id"] if current_event else None
            next_gw    = next_event["id"]    if next_event    else current_gw

            squad_gw = current_gw
            if current_event and current_event.get("finished") and next_event:
                squad_gw = next_gw
                logger.info(f"GW{current_gw} finished — fetching squad for upcoming GW{squad_gw}")

            summary["current_gw"] = current_gw
            summary["next_gw"] = next_gw
            summary["squad_gw"] = squad_gw

            # ── Step 2: Fixtures ──────────────────────────────────────────────
            logger.info("Pipeline: fetching all fixtures")
            all_fixtures = await fpl_agent.get_all_fixtures()
            await self.processor.upsert_fixtures(all_fixtures)
            await self.processor.compute_blank_double_gws()
            logger.info(f"Pipeline: {len(all_fixtures)} fixtures processed")

            # ── Step 3: Players ───────────────────────────────────────────────
            logger.info("Pipeline: upserting players")
            player_count = await self.processor.upsert_players(bootstrap)
            summary["players"] = player_count

            # ── Step 4: User squad ────────────────────────────────────────────
            if active_team_id and squad_gw:
                logger.info(f"Pipeline: fetching squad for team {active_team_id} GW{squad_gw}")
                # Invalidate picks cache so wildcard / transfer changes since
                # the last sync are always reflected.
                await fpl_agent.invalidate_picks_cache(active_team_id, squad_gw)
                try:
                    try:
                        picks_data = await fpl_agent.get_picks(active_team_id, squad_gw)
                    except Exception:
                        # Between GWs: next GW deadline hasn't passed yet so the
                        # FPL API returns 404 for that GW's picks.  Fall back to
                        # the last completed GW — the squad is the same anyway.
                        if squad_gw != current_gw and current_gw:
                            logger.warning(
                                f"GW{squad_gw} picks not available yet (pre-deadline) "
                                f"— falling back to GW{current_gw}"
                            )
                            squad_gw = current_gw
                            await fpl_agent.invalidate_picks_cache(active_team_id, squad_gw)
                            picks_data = await fpl_agent.get_picks(active_team_id, squad_gw)
                        else:
                            raise

                    entry_data = await fpl_agent.get_entry(active_team_id)
                    history_data = await fpl_agent.get_entry_history(active_team_id)
                    await self.processor.upsert_user_squad(
                        picks_data, entry_data, active_team_id, squad_gw, history_data
                    )
                    # Sync user GW history
                    gw_history_count = await self.processor.upsert_user_gw_history(
                        history_data, active_team_id
                    )
                    summary["user_gw_history"] = gw_history_count
                    summary["squad_synced"] = True

                    # ── Chip tracking ─────────────────────────────────────────
                    # Priority 1: picks_data.active_chip (live, current GW only)
                    # Priority 2: history.chips[] array (permanent record of all chips)
                    # NOTE: history.current[] entries do NOT have an active_chip field.
                    try:
                        chip_in_latest: str | None = None
                        latest_event_id: int | None = None

                        # Check picks_data first (active chip this GW)
                        picks_chip = (picks_data or {}).get("active_chip")
                        if picks_chip:
                            chip_in_latest = picks_chip
                            # current gw id from bootstrap
                            current_gw_entries = (history_data or {}).get("current", [])
                            if current_gw_entries:
                                latest_event_id = max(
                                    (e.get("event", 0) for e in current_gw_entries), default=None
                                )

                        # Fallback: history.chips[] has a permanent log of all chip plays
                        if not chip_in_latest:
                            history_chips = (history_data or {}).get("chips", [])
                            if history_chips:
                                # Most recent chip = highest event number
                                latest_chip_entry = max(
                                    history_chips, key=lambda c: c.get("event", 0)
                                )
                                chip_in_latest = latest_chip_entry.get("name")
                                latest_event_id = latest_chip_entry.get("event")

                        chip_redis_key = f"fpl:chip:active:{active_team_id}"
                        if chip_in_latest and latest_event_id:
                            # Normalize FPL short-form chip name to canonical
                            _CHIP_NORM = {
                                "3xc": "triple_captain",
                                "bboost": "bench_boost",
                                "freehit": "free_hit",
                                "free_hit": "free_hit",
                                "wildcard": "wildcard",
                            }
                            chip_canonical = _CHIP_NORM.get(chip_in_latest, chip_in_latest)
                            chip_payload = f"{chip_canonical}:{latest_event_id}"
                            await redis_client.set(chip_redis_key, chip_payload, ex=7200)
                            summary["active_chip"] = chip_canonical
                            summary["active_chip_gw"] = latest_event_id
                            logger.info(
                                f"Chip tracking: team {active_team_id} played "
                                f"'{chip_canonical}' in GW{latest_event_id} "
                                f"→ cached at {chip_redis_key}"
                            )
                        else:
                            await redis_client.delete(chip_redis_key)
                            summary["active_chip"] = None
                    except Exception as chip_err:
                        logger.warning(f"Chip tracking failed (non-fatal): {chip_err}")
                except Exception as e:
                    logger.exception("Squad fetch failed: {!r}", e)
                    summary["squad_synced"] = False

            # ── Step 4b: Player GW history for squad players ──────────────────
            if active_team_id and summary.get("squad_synced"):
                logger.info("Pipeline: syncing player GW history for squad")
                try:
                    from models.db.user_squad import UserSquad
                    from sqlalchemy import select
                    from core.database import AsyncSessionLocal
                    async with AsyncSessionLocal() as db:
                        result = await db.execute(
                            select(UserSquad.player_id).where(
                                UserSquad.team_id == active_team_id,
                                UserSquad.gameweek_id == squad_gw,
                            )
                        )
                        squad_pids = [row[0] for row in result.fetchall()]

                    history_tasks = [
                        fpl_agent.get_player_summary(pid) for pid in squad_pids
                    ]
                    summaries = await asyncio.gather(*history_tasks, return_exceptions=True)
                    total_rows = 0
                    for pid, player_summary in zip(squad_pids, summaries):
                        if isinstance(player_summary, Exception):
                            logger.warning(f"Player summary failed for {pid}: {player_summary}")
                            continue
                        rows = await self.processor.upsert_player_gw_history(pid, player_summary)
                        total_rows += rows
                    summary["player_gw_history_rows"] = total_rows
                    logger.info(f"Pipeline: {total_rows} player GW history rows synced")
                except Exception as e:
                    logger.warning(f"Player history sync failed: {e}")

            # ── Steps 5+6: understat xG + news (parallel) ────────────────────
            logger.info("Pipeline: fetching understat xG and news in parallel")
            fpl_players_basic = [
                {"id": e["id"], "web_name": e.get("web_name", ""), "first_name": e.get("first_name", ""), "second_name": e.get("second_name", "")}
                for e in bootstrap.get("elements", [])
            ]
            player_names = [e.get("web_name", "") for e in bootstrap.get("elements", [])]

            understat_task = asyncio.create_task(
                stats_agent.get_league_players(settings.UNDERSTAT_SEASON)
            )
            news_task = asyncio.create_task(
                news_agent.run(player_names)
            )

            understat_players = await understat_task
            news_alerts = await news_task

            # Match understat players to FPL players
            if understat_players:
                name_map = await stats_agent.build_name_map(fpl_players_basic, understat_players)
                xg_count = await self.processor.upsert_xg_data(
                    understat_players, name_map, stats_agent
                )
                summary["xg_players_matched"] = xg_count
            summary["news_alerts"] = len(news_alerts)

            # ── Step 7: Odds ──────────────────────────────────────────────────
            if settings.odds_enabled:
                logger.info("Pipeline: fetching match odds")
                try:
                    await odds_agent.get_premier_league_odds()
                    summary["odds_fetched"] = True
                except Exception as e:
                    logger.warning("Odds fetch failed: {!r}", e)
                    summary["odds_fetched"] = False

            # ── Step 8: ML predictions ────────────────────────────────────────
            logger.info("Pipeline: running ML predictions")
            await self.run_ml_predictions()
            summary["predictions_updated"] = True

            summary["status"] = "complete"
            summary["completed_at"] = datetime.utcnow().isoformat()
            await redis_client.set(LAST_RUN_KEY, summary["completed_at"])
            logger.info(f"Pipeline complete: {summary}")

        except PipelineRunningError:
            raise
        except Exception as e:
            summary["status"] = "error"
            summary["error"] = repr(e)
            logger.exception("Pipeline failed: {!r}", e)
        finally:
            await release_lock(PIPELINE_LOCK_KEY)

        return summary

    async def run_news_only_pipeline(self) -> dict:
        """Lightweight daily news scrape (no full bootstrap needed)."""
        lock_acquired = await acquire_lock("fpl:news:lock", 120)
        if not lock_acquired:
            return {"status": "already_running"}

        try:
            client = self._get_client()
            fpl_agent = FPLAgent(client)
            bootstrap = await fpl_agent.get_bootstrap()
            player_names = [e.get("web_name", "") for e in bootstrap.get("elements", [])]

            news_agent = NewsAgent()
            alerts = await news_agent.run(player_names)
            return {"status": "complete", "alerts": len(alerts)}
        finally:
            await release_lock("fpl:news:lock")

    async def run_ml_predictions(self) -> None:
        """Run minutes → xPts → price predictions for all players, update DB."""
        df = await self.processor.build_player_feature_dataframe()

        if df.empty:
            logger.warning("No player data for ML predictions")
            return

        # Step 1: Minutes model → P(start), P(60min+)
        if "rotation_risk_score" not in df.columns:
            df["rotation_risk_score"] = self.minutes_model.compute_rotation_risk(df)

        if "minutes_last_5_gws" not in df.columns:
            # Estimate rolling-5-GW minutes from season total.
            # Players with 0 season minutes get 0 here, correctly signalling
            # they are frozen out / haven't featured at all.
            season_min = df.get("minutes", pd.Series(0, index=df.index)).fillna(0)
            df["minutes_last_5_gws"] = (season_min / 38 * 5 * 90).clip(lower=0)
        if "starts_last_5_gws" not in df.columns:
            season_min = df.get("minutes", pd.Series(0, index=df.index)).fillna(0)
            df["starts_last_5_gws"] = (season_min / 90).clip(0, 5)
        if "status_available" not in df.columns:
            df["status_available"] = (df.get("status", "a") == "a").astype(int)
        if "team_fixture_count" not in df.columns:
            df["team_fixture_count"] = df.apply(
                lambda r: 2 if r.get("has_double_gw", False) else (0 if r.get("has_blank_gw", False) else 1),
                axis=1,
            )
        if "chance_of_playing" not in df.columns:
            df["chance_of_playing"] = 1.0

        start_probs, min60_probs = self.minutes_model.predict(df)
        df["predicted_start_prob"] = start_probs
        df["predicted_60min_prob"] = min60_probs
        state_probs = self.minutes_model.predict_state_probabilities(df)
        expected_minutes = self.minutes_model.expected_minutes_from_states(state_probs)
        df["predicted_expected_minutes"] = expected_minutes
        df["predicted_bench_prob"] = state_probs["BENCHED"].values
        df["predicted_sub_appearance_prob"] = (state_probs["SUB_30"] + state_probs["SUB_10"]).values

        # Step 2: xPts model
        xpts_predictions = self.xpts_model.predict(df)
        df["predicted_xpts_next"] = xpts_predictions
        df["predicted_goal_prob"] = np.clip(df.get("xg_per_90", 0).fillna(0).values * (expected_minutes / 90.0), 0.0, 0.95)
        df["predicted_assist_prob"] = np.clip(df.get("xa_per_90", 0).fillna(0).values * (expected_minutes / 90.0), 0.0, 0.95)
        cs_base = np.where(df.get("element_type", pd.Series(3, index=df.index)).values <= 2, 0.35, 0.12)
        df["predicted_clean_sheet_prob"] = np.clip(cs_base * (6 - df.get("fdr_next", pd.Series(3, index=df.index)).fillna(3).values) / 5.0, 0.0, 0.75)
        df["predicted_card_prob"] = np.clip(df.get("suspension_risk", pd.Series(0.0, index=df.index)).fillna(0).values * 0.35, 0.0, 0.5)
        df["predicted_bonus_points"] = np.clip(xpts_predictions * 0.12, 0.0, 3.0)

        # Step 2b: Apply Oracle learning bias
        # OracleLearner accumulates feature bias when Oracle consistently misses
        # certain player types vs the top FPL team. The bias starts at 1.0 (no
        # effect) and grows each GW Oracle loses, nudging xPts upward for the
        # types of players it has been undervaluing (e.g. high-form, high-ppg).
        try:
            from agents.oracle_learner import OracleLearner
            _learner = OracleLearner()
            if _learner.bias:
                _form_mult = _learner.bias.get("form", 1.0)
                _ppg_mult = _learner.bias.get("points_per_game", 1.0)
                # Per-player bias: players with above-average form/ppg get boosted more
                _bias_factor = (_form_mult + _ppg_mult) / 2.0
                if abs(_bias_factor - 1.0) > 0.001:
                    # Apply stronger boost to players whose form/ppg is above median
                    _form_col = df.get("form", pd.Series(0.0, index=df.index)).fillna(0)
                    _ppg_col = df.get("points_per_game", pd.Series(0.0, index=df.index)).fillna(0)
                    _form_median = _form_col.median()
                    _ppg_median = _ppg_col.median()
                    _above_form = (_form_col > _form_median).values
                    _above_ppg = (_ppg_col > _ppg_median).values
                    # Players above both medians get full bias; others get a dampened version
                    _per_player_bias = np.where(
                        _above_form & _above_ppg,
                        _bias_factor,          # full boost: form + ppg star
                        np.where(
                            _above_form | _above_ppg,
                            1.0 + (_bias_factor - 1.0) * 0.5,  # half boost: one signal
                            1.0,               # no boost: below both medians
                        )
                    )
                    xpts_predictions = (xpts_predictions * _per_player_bias).clip(min=0)
                    df["predicted_xpts_next"] = xpts_predictions
                    logger.info(
                        f"Oracle bias applied: global={_bias_factor:.3f} "
                        f"(form_mult={_form_mult:.2f}, ppg_mult={_ppg_mult:.2f}) "
                        f"boosted {(_per_player_bias > 1.0).sum()} players"
                    )
        except Exception as _bias_err:
            logger.warning(f"Oracle bias skipped: {_bias_err}")

        # Step 2c: Apply online calibration (post-GW residual corrections)
        try:
            from core.redis_client import redis_client
            import orjson as _orjson
            _cal_raw = await redis_client.get("ml:calibration_map")
            if _cal_raw:
                _cal_map_raw = _orjson.loads(_cal_raw)
                # Convert {f"{pos}_{band}": float} → {(pos, band): float}
                _cal_map = {
                    (int(k.split("_")[0]), int(k.split("_")[1])): v
                    for k, v in _cal_map_raw.items()
                }
                xpts_predictions = self.xpts_model.apply_calibration(
                    xpts_predictions, df, _cal_map
                )
                df["predicted_xpts_next"] = xpts_predictions
                logger.info(
                    f"Calibration applied: {len(_cal_map)} position/price groups"
                )
        except Exception as _cal_err:
            logger.warning(f"Calibration step skipped: {_cal_err}")

        # ── Reality gates: fringe / frozen-out players ───────────────────────
        # The cold-start heuristic estimates start probability purely from price
        # and rotation risk — it has NO knowledge of actual appearances. Two bugs:
        #
        #  Bug 1 — Zero-minute players (frozen out):
        #     price heuristic → start_prob ≈ 0.65-0.75 (catastrophically wrong)
        #     FIX: hard-cap to 0.08
        #
        #  Bug 2 — Micro-sample players (e.g. 6 min all season):
        #     FPL ppg = total_pts / 1 app → inflated (e.g. 6 pts in 6 min → ppg=6.0)
        #     ppg drives xpts upward even though the player never really plays.
        #     FIX: dampen start_prob by √(season_min / 270). 270 min = 3 full 90s.
        #     Edozie (6 min): 0.69 × √(6/270) ≈ 0.69 × 0.15 = 0.10 → filtered by
        #     transfer engine's start_prob ≥ 0.35 threshold.
        if "minutes" in df.columns:
            season_min = df["minutes"].fillna(0)
            status_col = df["status"] if "status" in df.columns else pd.Series("a", index=df.index)

            # Gate 1: absolute zero minutes
            zero_min_mask = (season_min == 0) & (status_col == "a")
            if zero_min_mask.any():
                start_probs[zero_min_mask.values] = np.minimum(
                    start_probs[zero_min_mask.values], 0.08
                )
                xpts_predictions[zero_min_mask.values] = np.minimum(
                    xpts_predictions[zero_min_mask.values], 0.3
                )
                df.loc[zero_min_mask, "predicted_start_prob"] = start_probs[zero_min_mask.values]
                df.loc[zero_min_mask, "predicted_xpts_next"] = xpts_predictions[zero_min_mask.values]
                logger.info(f"Reality gate [0-min]: capped {zero_min_mask.sum()} frozen-out players")

            # Gate 2: micro-sample players (1–269 min) — dampen by √(min/270)
            low_min_mask = (season_min > 0) & (season_min < 270) & (status_col == "a")
            if low_min_mask.any():
                damping = np.sqrt(
                    season_min[low_min_mask].values.clip(min=1) / 270.0
                )
                start_probs[low_min_mask.values] = (
                    start_probs[low_min_mask.values] * damping
                ).clip(0, 1)
                # xpts was multiplied by start_prob inside the model; re-apply
                # same damping so xpts scales down proportionally.
                xpts_predictions[low_min_mask.values] = (
                    xpts_predictions[low_min_mask.values] * damping
                ).clip(0)
                df.loc[low_min_mask, "predicted_start_prob"] = start_probs[low_min_mask.values]
                df.loc[low_min_mask, "predicted_xpts_next"] = xpts_predictions[low_min_mask.values]
                logger.info(
                    f"Reality gate [low-sample]: dampened {low_min_mask.sum()} players "
                    f"with <270 season minutes (ppg inflated by small-sample artifact)"
                )

        # Step 3: Price change predictor
        price_directions, price_confidence = self.price_model.predict(df)

        # Step 4: Update DB
        from core.database import AsyncSessionLocal
        from models.db.player import Player
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            feature_version = await get_or_create_feature_version(
                db,
                training_distribution={
                    "expected_minutes": {"mean": float(np.mean(expected_minutes)) if len(expected_minutes) else 0.0},
                    "rolling_xg": {"mean": float(df.get("xg_last_5_gws", pd.Series(0.0, index=df.index)).fillna(0).mean())},
                    "rolling_xa": {"mean": float(df.get("xa_last_5_gws", pd.Series(0.0, index=df.index)).fillna(0).mean())},
                    "ownership": {"mean": float(df.get("selected_by_percent", pd.Series(0.0, index=df.index)).fillna(0).mean())},
                    "rotation_risk": {"mean": float(df.get("rotation_risk_score", pd.Series(0.0, index=df.index)).fillna(0).mean())},
                    "availability_probability": {"mean": float(df.get("chance_of_playing", pd.Series(1.0, index=df.index)).fillna(1.0).mean())},
                },
            )
            model_version = await get_or_create_model_version(
                db,
                model_name="xpts_model",
                version="xpts_model_v2",
                artifact_path=str(self.xpts_model.model.__class__.__name__) if self.xpts_model.model else None,
                metrics={"minutes_states": True},
            )
            data_snapshot = await create_data_snapshot(db, source="prediction_run")
            result = await db.execute(select(Player))
            players = result.scalars().all()
            player_map = {p.id: p for p in players}
            pred_res = await db.execute(select(Prediction))
            existing_predictions = {
                (pred.player_id, pred.gameweek_id): pred
                for pred in pred_res.scalars().all()
            }
            current_gw = int(df.get("gameweek_id", pd.Series(0, index=df.index)).fillna(0).max()) if "gameweek_id" in df.columns else 0

            for i, row in df.iterrows():
                pid = int(row["id"])
                player = player_map.get(pid)
                if player:
                    player.predicted_xpts_next = round(float(xpts_predictions[i]), 3)
                    player.predicted_start_prob = round(float(start_probs[i]), 3)
                    player.predicted_60min_prob = round(float(min60_probs[i]), 3)
                    player.predicted_price_direction = int(price_directions[i])
                pred_key = (pid, current_gw)
                prediction = existing_predictions.get(pred_key)
                if prediction is None:
                    prediction = Prediction(player_id=pid, gameweek_id=current_gw)
                    db.add(prediction)
                prediction.predicted_xpts = round(float(xpts_predictions[i]), 3)
                prediction.predicted_start_prob = round(float(start_probs[i]), 3)
                prediction.predicted_60min_prob = round(float(min60_probs[i]), 3)
                prediction.predicted_expected_minutes = round(float(expected_minutes[i]), 3)
                prediction.predicted_goal_prob = round(float(df.iloc[i]["predicted_goal_prob"]), 3)
                prediction.predicted_assist_prob = round(float(df.iloc[i]["predicted_assist_prob"]), 3)
                prediction.predicted_clean_sheet_prob = round(float(df.iloc[i]["predicted_clean_sheet_prob"]), 3)
                prediction.predicted_card_prob = round(float(df.iloc[i]["predicted_card_prob"]), 3)
                prediction.predicted_bonus_points = round(float(df.iloc[i]["predicted_bonus_points"]), 3)
                prediction.predicted_bench_prob = round(float(df.iloc[i]["predicted_bench_prob"]), 3)
                prediction.predicted_sub_appearance_prob = round(float(df.iloc[i]["predicted_sub_appearance_prob"]), 3)
                prediction.predicted_price_direction = int(price_directions[i])
                prediction.confidence = round(float(price_confidence[i]), 3) if len(price_confidence) > i else 0.5
                prediction.model_version = model_version.version
                prediction.model_version_id = model_version.id
                prediction.feature_version_id = feature_version.id
                prediction.data_snapshot_id = data_snapshot.id

            await db.commit()

        logger.info(f"ML predictions updated for {len(df)} players")

    async def get_pipeline_status(self) -> dict:
        """Check if pipeline is running and when it last ran."""
        is_running = await redis_client.exists(PIPELINE_LOCK_KEY) > 0
        last_run = await redis_client.get(LAST_RUN_KEY)
        return {
            "is_running": bool(is_running),
            "last_run": last_run,
        }

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# pandas imported at top of file
