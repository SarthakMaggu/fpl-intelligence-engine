"""
Data Pipeline Processor — handles all DB upserts and feature engineering.

Transforms raw FPL API + understat data into structured DB records
and computes derived features for ML models.
"""
import asyncio
import orjson
from datetime import datetime
from typing import Optional
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.database import AsyncSessionLocal
from models.db.player import Player
from models.db.team import Team
from models.db.gameweek import Gameweek, Fixture
from models.db.user_squad import UserSquad, UserSquadSnapshot, UserBank
from models.db.prediction import Prediction
from models.db.history import PlayerGWHistory, UserGWHistory


# Yellow card suspension threshold
YELLOW_CARD_SUSPENSION_THRESHOLD = 4  # flag at 4 (5th = ban)
YELLOW_CARD_RESET_GW = 19             # resets after GW19 deadline


class DataProcessor:

    # ── Teams ──────────────────────────────────────────────────────────────────

    async def upsert_teams(self, bootstrap: dict) -> int:
        """Upsert all 20 Premier League teams from bootstrap-static."""
        teams_data = bootstrap.get("teams", [])
        async with AsyncSessionLocal() as db:
            for t in teams_data:
                existing = await db.get(Team, t["id"])
                if existing:
                    existing.code = t.get("code", 0)
                    existing.name = t.get("name", "")
                    existing.short_name = t.get("short_name", "")
                    existing.strength_overall_home = t.get("strength_overall_home", 3)
                    existing.strength_overall_away = t.get("strength_overall_away", 3)
                    existing.strength_attack_home = t.get("strength_attack_home", 3)
                    existing.strength_attack_away = t.get("strength_attack_away", 3)
                    existing.strength_defence_home = t.get("strength_defence_home", 3)
                    existing.strength_defence_away = t.get("strength_defence_away", 3)
                    existing.played = t.get("played", 0)
                    existing.win = t.get("win", 0)
                    existing.draw = t.get("draw", 0)
                    existing.loss = t.get("loss", 0)
                    existing.points = t.get("points", 0)
                    existing.position = t.get("position", 0)
                    existing.unavailable = t.get("unavailable", False)
                else:
                    db.add(Team(
                        id=t["id"],
                        code=t.get("code", 0),
                        name=t.get("name", ""),
                        short_name=t.get("short_name", ""),
                        pulse_id=t.get("pulse_id", 0),
                        strength_overall_home=t.get("strength_overall_home", 3),
                        strength_overall_away=t.get("strength_overall_away", 3),
                        strength_attack_home=t.get("strength_attack_home", 3),
                        strength_attack_away=t.get("strength_attack_away", 3),
                        strength_defence_home=t.get("strength_defence_home", 3),
                        strength_defence_away=t.get("strength_defence_away", 3),
                        played=t.get("played", 0),
                        win=t.get("win", 0),
                        draw=t.get("draw", 0),
                        loss=t.get("loss", 0),
                        points=t.get("points", 0),
                        position=t.get("position", 0),
                        unavailable=t.get("unavailable", False),
                    ))
            await db.commit()
        logger.info(f"Upserted {len(teams_data)} teams")
        return len(teams_data)

    # ── Gameweeks ──────────────────────────────────────────────────────────────

    async def upsert_gameweeks(self, bootstrap: dict) -> int:
        """Upsert all 38 gameweeks from bootstrap-static events array."""
        events = bootstrap.get("events", [])
        async with AsyncSessionLocal() as db:
            for e in events:
                deadline_str = e.get("deadline_time", "")
                try:
                    deadline = datetime.fromisoformat(deadline_str.replace("Z", "+00:00")).replace(tzinfo=None)
                except (ValueError, AttributeError):
                    deadline = datetime.utcnow()

                existing = await db.get(Gameweek, e["id"])
                if existing:
                    existing.name = e.get("name", "")
                    existing.deadline_time = deadline
                    existing.finished = e.get("finished", False)
                    existing.data_checked = e.get("data_checked", False)
                    existing.is_current = e.get("is_current", False)
                    existing.is_next = e.get("is_next", False)
                    existing.is_previous = e.get("is_previous", False)
                    existing.average_entry_score = e.get("average_entry_score") or 0
                    existing.highest_score = e.get("highest_score") or 0
                    existing.chip_plays = orjson.dumps(e.get("chip_plays") or []).decode()
                    existing.top_element = e.get("top_element")
                    existing.transfers_made = e.get("transfers_made") or 0
                else:
                    db.add(Gameweek(
                        id=e["id"],
                        name=e.get("name", ""),
                        deadline_time=deadline,
                        finished=e.get("finished", False),
                        data_checked=e.get("data_checked", False),
                        is_current=e.get("is_current", False),
                        is_next=e.get("is_next", False),
                        is_previous=e.get("is_previous", False),
                        average_entry_score=e.get("average_entry_score") or 0,
                        highest_score=e.get("highest_score") or 0,
                        chip_plays=orjson.dumps(e.get("chip_plays") or []).decode(),
                        top_element=e.get("top_element"),
                        transfers_made=e.get("transfers_made") or 0,
                    ))
            await db.commit()
        logger.info(f"Upserted {len(events)} gameweeks")
        return len(events)

    # ── Fixtures ───────────────────────────────────────────────────────────────

    async def upsert_fixtures(self, fixtures: list[dict]) -> int:
        """Upsert fixtures. gameweek_id=None means postponed."""
        async with AsyncSessionLocal() as db:
            for f in fixtures:
                kickoff_str = f.get("kickoff_time")
                try:
                    kickoff = datetime.fromisoformat(kickoff_str.replace("Z", "+00:00")).replace(tzinfo=None) if kickoff_str else None
                except (ValueError, AttributeError):
                    kickoff = None

                existing = await db.get(Fixture, f["id"])
                gw_id = f.get("event")  # None if postponed

                if existing:
                    existing.gameweek_id = gw_id
                    existing.event_id = gw_id
                    existing.team_home_id = f.get("team_h", 0)
                    existing.team_away_id = f.get("team_a", 0)
                    existing.kickoff_time = kickoff
                    existing.finished = f.get("finished", False)
                    existing.finished_provisional = f.get("finished_provisional", False)
                    existing.started = f.get("started")
                    existing.team_home_score = f.get("team_h_score")
                    existing.team_away_score = f.get("team_a_score")
                    existing.team_h_difficulty = f.get("team_h_difficulty", 3)
                    existing.team_a_difficulty = f.get("team_a_difficulty", 3)
                else:
                    db.add(Fixture(
                        id=f["id"],
                        code=f.get("code", f["id"]),
                        gameweek_id=gw_id,
                        event_id=gw_id,
                        team_home_id=f.get("team_h", 0),
                        team_away_id=f.get("team_a", 0),
                        kickoff_time=kickoff,
                        kickoff_time_provisional=f.get("provisional_start_time", False),
                        finished=f.get("finished", False),
                        finished_provisional=f.get("finished_provisional", False),
                        started=f.get("started"),
                        team_home_score=f.get("team_h_score"),
                        team_away_score=f.get("team_a_score"),
                        team_h_difficulty=f.get("team_h_difficulty", 3),
                        team_a_difficulty=f.get("team_a_difficulty", 3),
                        pulse_id=f.get("pulse_id", 0),
                    ))
            await db.commit()
        logger.debug(f"Upserted {len(fixtures)} fixtures")

        # Update gw_start_time / gw_end_time on every affected Gameweek row.
        # gw_start_time = MIN(kickoff_time) for that GW
        # gw_end_time   = MAX(kickoff_time) + 115 minutes (approx full-time of last game)
        await self._update_gw_timing()

        return len(fixtures)

    async def _update_gw_timing(self) -> None:
        """
        Compute and persist gw_start_time and gw_end_time on each Gameweek.
        Called after every upsert_fixtures() so the GW state watcher has
        accurate kick-off windows without any manual input.
        """
        from datetime import timedelta
        async with AsyncSessionLocal() as db:
            rows = await db.execute(text("""
                SELECT gameweek_id,
                       MIN(kickoff_time) AS first_kickoff,
                       MAX(kickoff_time) AS last_kickoff
                FROM fixtures
                WHERE gameweek_id IS NOT NULL
                  AND kickoff_time IS NOT NULL
                GROUP BY gameweek_id
            """))
            timing = rows.fetchall()

            for gw_id, first_ko, last_ko in timing:
                gw = await db.get(Gameweek, gw_id)
                if gw and first_ko and last_ko:
                    gw.gw_start_time = first_ko
                    gw.gw_end_time   = last_ko + timedelta(minutes=115)

            await db.commit()
        logger.debug(f"GW timing updated for {len(timing)} gameweeks")

    # ── Blank/Double GW Detection ──────────────────────────────────────────────

    async def compute_blank_double_gws(self) -> None:
        """
        For each gameweek, compute which teams have 0 or 2 fixtures.
        Updates Gameweek.is_blank/is_double and Player.has_blank_gw/has_double_gw.
        """
        async with AsyncSessionLocal() as db:
            # Get fixture counts per team per GW
            result = await db.execute(text("""
                SELECT gw_id, team_id, COUNT(*) as fixture_count
                FROM (
                    SELECT gameweek_id AS gw_id, team_home_id AS team_id
                    FROM fixtures WHERE gameweek_id IS NOT NULL
                    UNION ALL
                    SELECT gameweek_id, team_away_id
                    FROM fixtures WHERE gameweek_id IS NOT NULL
                ) t
                GROUP BY gw_id, team_id
            """))
            rows = result.fetchall()

            # Build lookup: {(gw_id, team_id): count}
            fixture_counts: dict[tuple, int] = {}
            for row in rows:
                fixture_counts[(row.gw_id, row.team_id)] = row.fixture_count

            # Find which GWs are blank/double overall
            from collections import defaultdict
            gw_teams: dict[int, list] = defaultdict(list)
            for (gw_id, team_id), count in fixture_counts.items():
                gw_teams[gw_id].append((team_id, count))

            for gw_id, team_counts in gw_teams.items():
                # A GW is blank if fewer than 20 teams appear in the fixture list
                # (teams with 0 fixtures are simply absent from fixture_counts, not
                # stored as count=0 — the SQL only returns rows that exist).
                has_blank = len(team_counts) < 20
                has_double = any(c >= 2 for _, c in team_counts)

                gw = await db.get(Gameweek, gw_id)
                if gw:
                    gw.is_blank = has_blank
                    gw.is_double = has_double

            # Update each player's blank/double flags based on their team
            player_result = await db.execute(select(Player))
            players = player_result.scalars().all()

            # Use same GW target logic as _build_next_fixture_lookup:
            # - If current GW is underway (not finished) → flags for current GW
            # - Otherwise → flags for next GW
            gw_result = await db.execute(
                select(Gameweek).where(Gameweek.is_current == True)
            )
            current_gw_flag = gw_result.scalar_one_or_none()
            # Use current GW when it is live (not finished) OR when it is finished
            # but data hasn't been checked yet (brief transition state between
            # last game finishing and FPL finalising GW data).  In both cases the
            # pitch/market should still reflect the CURRENT GW's blank/double flags.
            gw_fully_resolved = (
                current_gw_flag is not None
                and current_gw_flag.finished
                and current_gw_flag.data_checked
            )
            if current_gw_flag and not gw_fully_resolved:
                # GW underway or in brief post-game / pre-data-checked window
                next_gw = current_gw_flag
            else:
                gw_result = await db.execute(
                    select(Gameweek).where(Gameweek.is_next == True)
                )
                next_gw = gw_result.scalar_one_or_none()
                if not next_gw:
                    next_gw = current_gw_flag

            if next_gw:
                for player in players:
                    # Default 0: teams absent from fixture_counts have NO fixture
                    # (previously defaulted to 1 which caused blank GW teams like Man City
                    #  to be treated as having a fixture → has_blank_gw was never set True)
                    team_count = fixture_counts.get((next_gw.id, player.team_id), 0)
                    player.has_blank_gw = team_count == 0
                    player.has_double_gw = team_count >= 2

            await db.commit()
            logger.info("Blank/double GW flags updated")

    # ── Players ────────────────────────────────────────────────────────────────

    async def upsert_players(self, bootstrap: dict) -> int:
        """
        Upsert all FPL players from bootstrap-static elements array.
        Sets form_trend, suspension_risk, fixture context (FDR, home/away).
        """
        elements = bootstrap.get("elements", [])
        teams_data = {t["id"]: t for t in bootstrap.get("teams", [])}

        # Build next fixture lookup: {team_id: {fdr, is_home}}
        # _build_next_fixture_lookup() returns the CURRENT GW fixtures when a GW
        # is underway (is_current=True, finished=False), and the NEXT GW fixtures
        # otherwise. This means fdr_next always reflects the live-GW context, not
        # next-GW values, while the GW is being played.
        next_fixture_lookup = await self._build_next_fixture_lookup()

        # Detect whether a GW is currently live (deadline passed, not yet resolved).
        # During this window, fdr_next / is_home_next are FROZEN to prevent the
        # brief "GW temporarily finished" transition state from writing GW+1 FDR
        # values while the current GW is still being displayed.
        # Exception: blank-GW teams (no fixture this GW) ALWAYS get fdr_next=0.
        gw_underway = False
        async with AsyncSessionLocal() as _gw_db:
            _gw_res = await _gw_db.execute(
                select(Gameweek).where(Gameweek.is_current == True)
            )
            _cur_gw = _gw_res.scalar_one_or_none()
            if _cur_gw and not _cur_gw.finished:
                gw_underway = True
                logger.info(
                    f"GW{_cur_gw.id} is underway — fdr_next / is_home_next frozen "
                    f"at pre-deadline values (blank-GW teams still get fdr=0)"
                )

        async with AsyncSessionLocal() as db:
            for e in elements:
                player_id = e["id"]
                team_id = e.get("team", 0)

                news_added_str = e.get("news_added")
                try:
                    news_added = datetime.fromisoformat(
                        news_added_str.replace("Z", "+00:00")
                    ).replace(tzinfo=None) if news_added_str else None
                except (ValueError, AttributeError):
                    news_added = None

                next_fix = next_fixture_lookup.get(team_id, {})

                # Yellow card suspension: flag if within 1 card of ban
                yellow_cards = e.get("yellow_cards", 0)
                suspension_risk = yellow_cards >= YELLOW_CARD_SUSPENSION_THRESHOLD

                existing = await db.get(Player, player_id)
                if existing:
                    self._update_player_from_element(
                        existing, e, next_fix, news_added, suspension_risk,
                        gw_underway=gw_underway,
                    )
                else:
                    player = Player(
                        id=player_id,
                        code=e.get("code", player_id),
                        web_name=e.get("web_name", ""),
                        first_name=e.get("first_name", ""),
                        second_name=e.get("second_name", ""),
                        element_type=e.get("element_type", 1),
                        team_id=team_id,
                    )
                    self._update_player_from_element(
                        player, e, next_fix, news_added, suspension_risk,
                        gw_underway=gw_underway,
                    )
                    db.add(player)

            await db.commit()

        logger.info(f"Upserted {len(elements)} players")
        return len(elements)

    def _update_player_from_element(
        self,
        player: Player,
        e: dict,
        next_fix: dict,
        news_added: Optional[datetime],
        suspension_risk: bool,
        gw_underway: bool = False,
    ) -> None:
        """Update player fields from FPL element dict."""
        player.now_cost = e.get("now_cost", 0)
        player.cost_change_start = e.get("cost_change_start", 0)
        cost_change_event = e.get("cost_change_event", 0) or 0
        player.predicted_price_direction = 1 if cost_change_event > 0 else (-1 if cost_change_event < 0 else 0)
        player.selected_by_percent = float(e.get("selected_by_percent", 0) or 0)
        player.form = float(e.get("form", 0) or 0)
        player.total_points = e.get("total_points", 0)
        player.points_per_game = float(e.get("points_per_game", 0) or 0)
        player.event_points = e.get("event_points", 0)
        player.transfers_in_event = e.get("transfers_in_event", 0)
        player.transfers_out_event = e.get("transfers_out_event", 0)
        player.transfers_in = e.get("transfers_in", 0)
        player.transfers_out = e.get("transfers_out", 0)
        player.minutes = e.get("minutes", 0)
        player.goals_scored = e.get("goals_scored", 0)
        player.assists = e.get("assists", 0)
        player.clean_sheets = e.get("clean_sheets", 0)
        player.goals_conceded = e.get("goals_conceded", 0)
        player.own_goals = e.get("own_goals", 0)
        player.penalties_saved = e.get("penalties_saved", 0)
        player.penalties_missed = e.get("penalties_missed", 0)
        player.yellow_cards = e.get("yellow_cards", 0)
        player.red_cards = e.get("red_cards", 0)
        player.saves = e.get("saves", 0)
        player.bonus = e.get("bonus", 0)
        player.bps = e.get("bps", 0)
        player.influence = float(e.get("influence", 0) or 0)
        player.creativity = float(e.get("creativity", 0) or 0)
        player.threat = float(e.get("threat", 0) or 0)
        player.ict_index = float(e.get("ict_index", 0) or 0)
        player.expected_goals = float(e.get("expected_goals", 0) or 0)
        player.expected_assists = float(e.get("expected_assists", 0) or 0)
        player.expected_goal_involvements = float(e.get("expected_goal_involvements", 0) or 0)
        player.expected_goals_conceded = float(e.get("expected_goals_conceded", 0) or 0)
        player.status = e.get("status", "a")
        player.chance_of_playing_this_round = e.get("chance_of_playing_this_round")
        player.chance_of_playing_next_round = e.get("chance_of_playing_next_round")
        player.news = e.get("news", "")
        player.news_added = news_added
        player.suspension_risk = suspension_risk

        # Fixture context — next_fix is {} (empty dict) for blank GW teams.
        # Use 0 as the sentinel for "no fixture this GW" so the UI can detect
        # blank GWs. is_home=False for blank GW teams (not at home for any game).
        # next_fix comes from _build_next_fixture_lookup() which already returns
        # the live-GW fixtures (not next-GW) when a GW is underway.
        #
        # FREEZE during live GW: if the GW is underway AND this team has a fixture,
        # skip writing fdr_next/is_home_next to prevent the brief "GW transition"
        # state from corrupting the pre-deadline values with GW+1 data.
        # Blank-GW teams (no fixture) ALWAYS get fdr=0 written — their absence from
        # the fixture lookup is deterministic and must not stay at a stale value.
        has_fixture = bool(next_fix)
        if not gw_underway or not has_fixture:
            player.fdr_next = next_fix.get("fdr", 0) if has_fixture else 0
            player.is_home_next = next_fix.get("is_home", False) if has_fixture else False

        # Set piece taker heuristic: top creativity or many assists in team
        player.is_set_piece_taker = player.creativity > 50 or player.assists >= 3

        # Form trend: compare form to points_per_game
        if player.form > player.points_per_game * 1.15:
            player.form_trend = "rising"
        elif player.form < player.points_per_game * 0.85:
            player.form_trend = "falling"
        else:
            player.form_trend = "stable"

    async def _build_next_fixture_lookup(self) -> dict[int, dict]:
        """Build {team_id: {fdr, is_home}} for the next GW.

        Priority logic:
          1. If the current GW is underway (is_current=True AND finished=False)
             → use that GW's fixtures (deadline has passed, games are live/pending)
          2. Otherwise (current GW finished OR no current GW)
             → use is_next=True GW (upcoming GW)
        This prevents showing GW+1 FDR values while GW is still being played.
        """
        async with AsyncSessionLocal() as db:
            # Check current GW first
            result = await db.execute(
                select(Gameweek).where(Gameweek.is_current == True)
            )
            current_gw = result.scalar_one_or_none()

            # Use current GW fixtures when:
            # - GW is actively underway (not finished), OR
            # - GW just finished but data hasn't been checked yet (transition window)
            # This prevents the brief "finished=True, data_checked=False" state from
            # returning GW+1 fixtures while the current GW is still being displayed.
            gw_fully_resolved = (
                current_gw is not None
                and current_gw.finished
                and current_gw.data_checked
            )
            if current_gw and not gw_fully_resolved:
                # GW is underway or in brief post-game / pre-data-checked window
                target_gw = current_gw
            else:
                # Current GW finished and resolved, OR no current GW — use upcoming GW
                result = await db.execute(
                    select(Gameweek).where(Gameweek.is_next == True)
                )
                target_gw = result.scalar_one_or_none()
                if not target_gw:
                    target_gw = current_gw  # last resort fallback

            if not target_gw:
                return {}

            result = await db.execute(
                select(Fixture).where(Fixture.gameweek_id == target_gw.id)
            )
            fixtures = result.scalars().all()

            # Build lookup: for double GW teams keep the BEST (lowest) FDR fixture
            # and mark is_home=True if either fixture is at home.
            # Previous code overwrote the first fixture with the second, losing FDR data.
            raw: dict[int, list[dict]] = {}
            for f in fixtures:
                raw.setdefault(f.team_home_id, []).append({"fdr": f.team_h_difficulty, "is_home": True})
                raw.setdefault(f.team_away_id, []).append({"fdr": f.team_a_difficulty, "is_home": False})

            lookup: dict[int, dict] = {}
            for team_id, fix_list in raw.items():
                best_fdr = min(fx["fdr"] for fx in fix_list)
                has_home = any(fx["is_home"] for fx in fix_list)
                lookup[team_id] = {
                    "fdr": best_fdr,
                    "is_home": has_home,
                    "fixture_count": len(fix_list),
                }

            return lookup

    # ── xG/xA from understat ───────────────────────────────────────────────────

    async def upsert_xg_data(
        self,
        understat_players: list[dict],
        name_map: dict[int, str],
        stats_agent,
    ) -> int:
        """
        Map understat player stats to FPL players and update xG/xA fields.
        """
        understat_by_id = {p["id"]: p for p in understat_players}
        updated = 0

        async with AsyncSessionLocal() as db:
            for fpl_id, understat_id in name_map.items():
                understat_player = understat_by_id.get(understat_id)
                if not understat_player:
                    continue

                player = await db.get(Player, fpl_id)
                if not player:
                    continue

                per90 = stats_agent.compute_per90_stats(understat_player)
                player.xg_per_90 = per90["xg_per_90"]
                player.xa_per_90 = per90["xa_per_90"]
                player.npxg_per_90 = per90["npxg_per_90"]
                player.xg_season = per90["xg_season"]
                player.xa_season = per90["xa_season"]
                player.understat_id = str(understat_id)
                updated += 1

            await db.commit()

        logger.info(f"Updated xG/xA data for {updated} players")
        return updated

    # ── User Squad ─────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_free_transfers(
        history_current: list,
        current_gw: int,
        chips: list | None = None,
    ) -> int:
        """
        Compute free transfers available for current_gw using full season history.

        FPL rules:
          - Season starts with 1 FT
          - Each completed GW: banked = max(0, ft - transfers_made)
                               ft_next = min(5, banked + 1)   — max bank is 5 FTs
          - After wildcard or free_hit: FT resets to 1 for the next GW
        """
        # GWs where FT should reset to 1 (wildcard / free_hit chips)
        reset_gws: set[int] = set()
        if chips:
            for chip in chips:
                if chip.get("name") in ("wildcard", "freehit"):
                    reset_gws.add(chip.get("event", 0))

        ft = 1
        for gw_entry in sorted(history_current, key=lambda x: x.get("event", 0)):
            gw = gw_entry.get("event", 0)
            if gw >= current_gw:
                break
            if gw in reset_gws:
                # Wildcard / free_hit played this GW → next GW starts fresh with 1 FT
                ft = 1
            else:
                transfers_made = gw_entry.get("event_transfers", 0) or 0
                unused = max(0, ft - transfers_made)
                ft = min(5, unused + 1)   # FPL max accumulated FTs = 5
        return ft

    async def upsert_user_squad(
        self,
        picks_data: dict,
        entry_data: dict,
        team_id: int,
        gw: int,
        history_data: dict | None = None,
    ) -> None:
        """
        Upsert user squad picks and bank state from FPL API response.
        Handles chip detection and Free Hit snapshot.
        """
        picks = picks_data.get("picks", [])
        entry_history = picks_data.get("entry_history", {})
        active_chip = picks_data.get("active_chip")

        # Delete existing picks for this GW (fresh upsert)
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(UserSquad).where(
                    UserSquad.team_id == team_id,
                    UserSquad.gameweek_id == gw,
                )
            )

            for pick in picks:
                db.add(UserSquad(
                    team_id=team_id,
                    gameweek_id=gw,
                    player_id=pick["element"],
                    position=pick["position"],
                    is_captain=pick.get("is_captain", False),
                    is_vice_captain=pick.get("is_vice_captain", False),
                    multiplier=pick.get("multiplier", 1),
                    purchase_price=pick.get("purchase_price", 0),
                    selling_price=pick.get("selling_price", 0),
                ))

            await db.commit()

        # Update bank / chip state
        await self._upsert_user_bank(entry_data, picks_data, team_id, gw, active_chip, history_data)

        # If Free Hit active: save snapshot for post-GW revert
        if active_chip == "freehit":
            await self._save_squad_snapshot(team_id, gw, picks)

        logger.info(f"Upserted squad for team {team_id} GW{gw} ({len(picks)} picks, chip={active_chip})")

    async def _upsert_user_bank(
        self,
        entry_data: dict,
        picks_data: dict,
        team_id: int,
        gw: int,
        active_chip: Optional[str],
        history_data: dict | None = None,
    ) -> None:
        """Update UserBank with latest financial state and chip usage."""
        entry_history = picks_data.get("entry_history", {})

        async with AsyncSessionLocal() as db:
            # Query by team_id (not PK id) — UserBank.id is auto-increment
            result = await db.execute(select(UserBank).where(UserBank.team_id == team_id))
            bank = result.scalar_one_or_none()
            if not bank:
                bank = UserBank(
                    team_id=team_id,
                    team_name=entry_data.get("name", ""),
                    player_first_name=entry_data.get("player_first_name", ""),
                    player_last_name=entry_data.get("player_last_name", ""),
                )
                db.add(bank)

            bank.team_name = entry_data.get("name", bank.team_name)
            bank.bank = entry_history.get("bank", 0)
            bank.value = entry_history.get("value", 1000)
            bank.overall_rank = entry_data.get("summary_overall_rank")
            bank.total_points = entry_data.get("summary_overall_points", 0)

            # Free transfers: compute from FULL season history for accuracy.
            # _compute_free_transfers gives FTs available at the START of the
            # current GW (processing all GWs < gw).
            #
            # Two scenarios:
            #  A) Pre-deadline: current GW NOT yet in history → show FTs still
            #     available for THIS GW (subtract pre-deadline transfers already made).
            #  B) Post-deadline / GW in play: current GW IS in history (transfers
            #     locked) → show FTs for NEXT GW = min(5, unused + 1).
            if history_data and history_data.get("current"):
                ft_at_gw_start = self._compute_free_transfers(
                    history_data["current"], gw,
                    chips=history_data.get("chips"),
                )
                # Detect whether GW deadline has passed (entry in history = locked).
                current_gw_entry = next(
                    (e for e in history_data["current"] if e.get("event") == gw), None
                )
                if current_gw_entry is not None:
                    # Post-deadline: GW is in play or done.
                    # Show FTs available for NEXT gameweek.
                    transfers_this_gw = current_gw_entry.get("event_transfers", 0) or 0
                    unused = max(0, ft_at_gw_start - transfers_this_gw)
                    bank.free_transfers = min(5, unused + 1)
                    logger.info(
                        f"FT (post-deadline, GW{gw}): start={ft_at_gw_start}, "
                        f"used={transfers_this_gw}, next_gw_ft={bank.free_transfers} "
                        f"for team {team_id}"
                    )
                else:
                    # Pre-deadline: subtract any transfers already queued this GW.
                    transfers_this_gw = entry_history.get("event_transfers", 0) or 0
                    bank.free_transfers = max(0, ft_at_gw_start - transfers_this_gw)
                    logger.info(
                        f"FT (pre-deadline, GW{gw}): start={ft_at_gw_start}, "
                        f"queued={transfers_this_gw}, remaining={bank.free_transfers} "
                        f"for team {team_id}"
                    )
            else:
                current_ft = entry_history.get("event_transfers") or 0
                prev_ft = bank.free_transfers or 1
                bank.free_transfers = min(max(1, (prev_ft + 1) - current_ft), 5)
                logger.warning(f"FT fallback (no history): {bank.free_transfers} for team {team_id}")

            # Track chip usage from picks_data (active this GW)
            if active_chip:
                current_half = "1" if gw <= 18 else "2"
                chip_map = {
                    "wildcard": f"wildcard_{current_half}_used_gw",
                    "freehit": f"free_hit_{current_half}_used_gw",
                    "bboost": f"bench_boost_{current_half}_used_gw",
                    "3xc": f"triple_captain_{current_half}_used_gw",
                }
                col = chip_map.get(active_chip)
                if col and getattr(bank, col, None) is None:
                    setattr(bank, col, gw)

            # Backfill chip usage from full season history (authoritative).
            # This catches chips played in past GWs — e.g. wildcard played in
            # GW29 won't appear as active_chip when we sync in GW30.
            for chip_entry in (history_data or {}).get("chips", []):
                chip_name = chip_entry.get("name")
                chip_gw   = chip_entry.get("event")
                if not chip_name or not chip_gw:
                    continue
                chip_half = "1" if chip_gw <= 18 else "2"
                hist_chip_map = {
                    "wildcard": f"wildcard_{chip_half}_used_gw",
                    "freehit":  f"free_hit_{chip_half}_used_gw",
                    "bboost":   f"bench_boost_{chip_half}_used_gw",
                    "3xc":      f"triple_captain_{chip_half}_used_gw",
                }
                hist_col = hist_chip_map.get(chip_name)
                if hist_col:
                    setattr(bank, hist_col, chip_gw)

            await db.commit()

    async def _save_squad_snapshot(self, team_id: int, gw: int, picks: list) -> None:
        """Save pre-Free-Hit squad for post-GW revert."""
        async with AsyncSessionLocal() as db:
            snapshot = UserSquadSnapshot(
                team_id=team_id,
                snapshot_gw=gw,
                picks_json=orjson.dumps(picks).decode(),
            )
            db.add(snapshot)
            await db.commit()
        logger.info(f"Saved Free Hit snapshot for team {team_id} GW{gw}")

    # ── Feature DataFrame ──────────────────────────────────────────────────────

    async def build_player_feature_dataframe(self):
        """
        Build pandas DataFrame with all features for ML training/inference.
        Returns DataFrame with columns matching XPTS_FEATURES.
        """
        import pandas as pd

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Player))
            players = result.scalars().all()

            result = await db.execute(select(Team))
            teams = result.scalars().all()
            team_lookup = {t.id: t for t in teams}

        records = []
        for p in players:
            team = team_lookup.get(p.team_id)
            # Per-90 stats require a meaningful sample to be valid.
            # Using a tiny denominator (e.g. 6 min → nineties=0.067) inflates
            # xg/90, xa/90 enormously: 0.17 xG in 6 min = 2.55 xg/90 — absurd.
            # Threshold: require ≥ 1 full 90-minute game worth of minutes.
            # Below that, all per-90 signals are zeroed out.
            nineties = p.minutes / 90.0 if p.minutes > 0 else 0.0
            has_reliable_90s = nineties >= 1.0   # at least one full game

            bps_per_90 = p.bps / nineties if has_reliable_90s else 0.0
            xg_per_90 = (p.xg_per_90 or (p.expected_goals / nineties)) if has_reliable_90s else 0.0
            xa_per_90 = (p.xa_per_90 or (p.expected_assists / nineties)) if has_reliable_90s else 0.0
            npxg_per_90 = (p.npxg_per_90 or 0.0) if has_reliable_90s else 0.0
            # ICT also unreliable without meaningful playing time
            ict = p.ict_index if has_reliable_90s else 0.0
            # form is safe once player appears (FPL updates it per appearance)
            form = p.form if nineties > 0 else 0.0

            records.append({
                "id": p.id,
                "web_name": p.web_name,
                "element_type": p.element_type,
                "team_id": p.team_id,
                "now_cost": p.now_cost,
                "price_millions": p.now_cost / 10,
                "minutes": p.minutes,  # raw season minutes — used by reality gate in fetcher.py

                # xG/xA features — only when ≥ 90 season minutes played (reliable sample)
                "xg_per_90": xg_per_90,
                "xa_per_90": xa_per_90,
                "npxg_per_90": npxg_per_90,

                # ICT + form — zero for near-zero-minute players
                "ict_index": ict,
                "form": form,
                "points_per_game": p.points_per_game,
                "bps_per_90": bps_per_90,

                # Minutes probability (placeholder, updated by minutes model)
                "predicted_start_prob": p.predicted_start_prob,
                "predicted_60min_prob": p.predicted_60min_prob,

                # Fixture context
                "fdr_next": p.fdr_next,
                "is_home_next": int(p.is_home_next) if p.is_home_next is not None else 0,
                "blank_gw": int(p.has_blank_gw),
                "double_gw": int(p.has_double_gw),

                # Team strength (opponent's defence)
                "team_strength_attack": (
                    team.strength_attack_home if p.is_home_next
                    else team.strength_attack_away
                ) if team else 3,
                "opponent_strength_defence": 3,  # Updated per fixture in full pipeline

                # Market signals
                "selected_by_percent": p.selected_by_percent,
                "transfers_in_event": p.transfers_in_event,
                "transfers_in_event_delta": p.transfers_in_event - p.transfers_out_event,

                # Win probability (set by odds agent; default to team strength)
                "team_win_probability": 0.4,  # Updated when odds available

                # Set piece taker
                "is_set_piece_taker": int(bool(p.is_set_piece_taker)),

                # Position dummies
                "is_gk": int(p.element_type == 1),
                "is_def": int(p.element_type == 2),
                "is_mid": int(p.element_type == 3),
                "is_fwd": int(p.element_type == 4),

                # Status flags
                "status": p.status,
                # Use explicit None check — `(0 or 100)` evaluates to 100 in Python,
                # which would treat a 0%-chance player as fully fit (100%).
                "chance_of_playing": (
                    p.chance_of_playing_next_round / 100
                    if p.chance_of_playing_next_round is not None
                    else 1.0
                ),
                "suspension_risk": int(p.suspension_risk),
                "form_trend": p.form_trend,

                # ML predictions (for display/captain engine)
                "predicted_xpts_next": p.predicted_xpts_next,
            })

        df = pd.DataFrame(records)

        # ── News sentiment features ───────────────────────────────────────────
        try:
            from core.redis_client import redis_client
            import orjson as _orjson

            sentiment_raw = await redis_client.get("news:sentiment")
            if sentiment_raw:
                smap = _orjson.loads(sentiment_raw)
                df["news_sentiment"] = df["web_name"].map(
                    lambda n: smap.get(n, {}).get("sentiment", 0.0)
                ).fillna(0.0)
                df["news_article_count"] = df["web_name"].map(
                    lambda n: smap.get(n, {}).get("article_count", 0)
                ).fillna(0).astype(int)
            else:
                df["news_sentiment"] = 0.0
                df["news_article_count"] = 0
        except Exception as _ns_err:
            logger.warning(f"News sentiment feature skipped: {_ns_err}")
            df["news_sentiment"] = 0.0
            df["news_article_count"] = 0

        # ── Rolling 5-GW performance features ────────────────────────────────
        # Primary source: player_gw_history (squad players, ~59 entries).
        # Fallback: player_features_latest (feature store — covers all 825 players
        #           from the last full pipeline run).  Non-squad transfer targets
        #           get 0 without this fallback, causing severe under/over-prediction.
        _rolling_cols = ["xg_last_5_gws", "xa_last_5_gws", "goals_last_5_gws",
                         "cs_last_5_gws", "pts_last_5_gws", "minutes_trend"]
        try:
            player_ids = df["id"].tolist()
            rolling = await self.get_player_rolling_stats(player_ids, n_gws=5)
            if rolling:
                rolling_df = pd.DataFrame(rolling).set_index("player_id")
                for col in _rolling_cols:
                    if col in rolling_df.columns:
                        df[col] = df["id"].map(rolling_df[col]).fillna(0.0)
                    else:
                        df[col] = 0.0
            else:
                for col in _rolling_cols:
                    df[col] = 0.0
        except Exception as _roll_err:
            logger.warning(f"Rolling 5-GW features skipped: {_roll_err}")
            for col in _rolling_cols:
                df[col] = 0.0

        # ── Feature store fallback for non-squad players ──────────────────────
        # Players absent from player_gw_history (transfer targets not in squad)
        # get 0 for all rolling stats above.  Fill those gaps from the feature store.
        try:
            _zero_mask = (df["pts_last_5_gws"] == 0.0)
            if _zero_mask.any():
                from models.db.feature_store import PlayerFeaturesLatest
                from sqlalchemy import select as _sel2
                _missing_ids = df.loc[_zero_mask, "id"].tolist()
                async with AsyncSessionLocal() as _fdb:
                    _fres = await _fdb.execute(
                        _sel2(PlayerFeaturesLatest).where(
                            PlayerFeaturesLatest.player_id.in_(_missing_ids)
                        )
                    )
                    _frows = _fres.scalars().all()
                if _frows:
                    import orjson as _orjson2
                    _fmap: dict = {}
                    for _fr in _frows:
                        try:
                            _fj = _orjson2.loads(_fr.features_json) if isinstance(_fr.features_json, (str, bytes)) else _fr.features_json
                            _fmap[_fr.player_id] = _fj
                        except Exception:
                            pass
                    for _col in _rolling_cols:
                        _fallback_vals = df.loc[_zero_mask, "id"].map(
                            lambda pid: float(_fmap.get(pid, {}).get(_col, 0.0) or 0.0)
                        )
                        df.loc[_zero_mask, _col] = df.loc[_zero_mask, _col].where(
                            df.loc[_zero_mask, _col] != 0.0, _fallback_vals
                        )
                    logger.debug(
                        f"Feature store fallback filled rolling stats for "
                        f"{sum(_zero_mask)} non-squad players"
                    )
        except Exception as _fs_err:
            logger.warning(f"Feature store rolling-stats fallback skipped: {_fs_err}")

        # ── Season stage — GW position normalised to [0, 1] ──────────────────
        # Computed from current GW id stored in the gameweek table.
        # Pre-announced fixture info: no leakage.
        try:
            from models.db.gameweek import Gameweek
            from sqlalchemy import select as _sel
            from core.database import AsyncSessionLocal as _ASL
            async with _ASL() as _db:
                _gw_res = await _db.execute(
                    _sel(Gameweek.id).where(Gameweek.is_next == True)
                )
                _next_gw_id = _gw_res.scalar() or 1
            df["season_stage"] = round(min(max((_next_gw_id - 1) / 37.0, 0.0), 1.0), 4)
        except Exception:
            df["season_stage"] = 0.5  # mid-season neutral fallback

        # ── opponent_goals_conceded_per90 — derived from fdr_next ─────────────
        # This feature IS trained on (historical_fetcher computes it from rolling
        # opponent goals conceded). At inference it was previously missing (defaulted
        # to 0.0 = "opponent never concedes", biasing xPts upward for all players).
        # FIX: approximate from fdr_next using FPL's difficulty scale:
        #   FDR 1 (easiest) → opponent concedes ~2.0/game (leaky defence)
        #   FDR 3 (neutral) → ~1.3/game (Premier League average)
        #   FDR 5 (hardest) → ~0.6/game (top defensive side)
        #   FDR 0 (blank GW) → 0.0 (no fixture)
        import numpy as _np
        _fdr = df["fdr_next"].fillna(3).values.astype(float)
        df["opponent_goals_conceded_per90"] = _np.select(
            [_fdr == 0, _fdr == 1, _fdr == 2, _fdr == 4, _fdr == 5],
            [0.0,        2.0,       1.7,       0.9,       0.6],
            default=1.3,   # FDR 3 = average Premier League attack difficulty
        )

        # ── fdr_next3_avg — 3-GW avg FDR (from fixture table) ────────────────
        # Computed from upcoming fixture FDR data.  If unavailable, fall back
        # to the current fdr_next (single-GW proxy).  This feature has low
        # predictive weight in the model (team-level signal already in fdr_next)
        # but must not default to 0 (implies impossibly easy run of fixtures).
        if "fdr_next3_avg" not in df.columns:
            df["fdr_next3_avg"] = df["fdr_next"].fillna(3.0)

        # ── Normalize transfers_in_event_delta by total GW volume ────────────
        # Raw FPL counts (0 – 500,000) had the same scale mismatch pattern as
        # selected_by_percent.  More critically: the model learned
        # "very high raw delta → regression" from training data (players with
        # 100k+ transfers in had just hauled → often regress next GW).
        # This caused elite in-form players (Bruno Fernandes, Salah) to receive
        # LOWER predictions than mediocre players because massive bandwagon buying
        # after a haul was interpreted as a regression anchor.
        #
        # Fix: normalise by total GW transfers volume → percentage of market
        # activity directed at this player.  Bounded range ≈ -10 to +10.
        # Bruno at 107k / ~1M total GW transfers = +10.7% (genuinely popular).
        # This matches the training-data normalised distribution and lets the
        # model see "market flow %" as the intended buying-pressure signal.
        if "transfers_in_event_delta" in df.columns:
            _raw_ti = df["transfers_in_event"].fillna(0) if "transfers_in_event" in df.columns else df["transfers_in_event_delta"].clip(lower=0)
            _total_ti = _raw_ti.sum() or 1.0
            df["transfers_in_event_delta"] = (
                df["transfers_in_event_delta"] / _total_ti * 100
            ).clip(-10, 10)

        # Log-compress selected_by_percent to match training distribution.
        # Training: log1p applied after computing %; must mirror here at inference.
        # This reduces feature importance from 2nd → ~15th while keeping signal.
        if "selected_by_percent" in df.columns:
            import numpy as _np_sel2
            df["selected_by_percent"] = _np_sel2.log1p(df["selected_by_percent"].fillna(0))

        # Cap pts_last_5_gws to match training cap (40 pts max).
        # Prevents extreme outliers (e.g. Bruno 46pts) from triggering model's
        # regression-to-mean pattern. Monotone +1 constraint + cap = correct direction.
        if "pts_last_5_gws" in df.columns:
            df["pts_last_5_gws"] = df["pts_last_5_gws"].clip(upper=40)

        return df

    async def get_player_rolling_stats(
        self, player_ids: list[int], n_gws: int = 5
    ) -> list[dict]:
        """
        Compute rolling N-GW stats for each player from player_gw_history table.

        Returns list of dicts with keys:
            player_id, xg_last_5_gws, xa_last_5_gws, goals_last_5_gws,
            cs_last_5_gws, pts_last_5_gws, minutes_trend
        """
        if not player_ids:
            return []

        import pandas as pd

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(PlayerGWHistory)
                .where(PlayerGWHistory.player_id.in_(player_ids))
                .order_by(PlayerGWHistory.player_id, PlayerGWHistory.gw_id.desc())
            )
            rows = result.scalars().all()

        if not rows:
            return []

        records = []
        for r in rows:
            records.append({
                "player_id": r.player_id,
                "gw_id": r.gw_id,
                "expected_goals": float(r.expected_goals or 0),
                "expected_assists": float(r.expected_assists or 0),
                "goals_scored": int(r.goals_scored or 0),
                "clean_sheets": int(r.clean_sheets or 0),
                "total_points": int(r.total_points or 0),
                "minutes": int(r.minutes or 0),
            })

        df = pd.DataFrame(records)
        output = []

        for pid, grp in df.groupby("player_id"):
            grp = grp.sort_values("gw_id", ascending=False)
            last5 = grp.head(n_gws)
            prev5 = grp.iloc[n_gws:n_gws * 2]

            # Minutes trend: ratio of last 5 GW minutes vs preceding 5 GW minutes
            last5_mins = last5["minutes"].sum()
            prev5_mins = prev5["minutes"].sum() if len(prev5) > 0 else last5_mins
            minutes_trend = (last5_mins / prev5_mins) if prev5_mins > 0 else 1.0

            output.append({
                "player_id": int(pid),
                "xg_last_5_gws": round(last5["expected_goals"].sum(), 3),
                "xa_last_5_gws": round(last5["expected_assists"].sum(), 3),
                "goals_last_5_gws": int(last5["goals_scored"].sum()),
                "cs_last_5_gws": int(last5["clean_sheets"].sum()),
                "pts_last_5_gws": int(last5["total_points"].sum()),
                "minutes_trend": round(float(minutes_trend), 3),
            })

        return output

    # ── Historical data ────────────────────────────────────────────────────────

    async def upsert_user_gw_history(self, history_data: dict, team_id: int) -> int:
        """
        Upsert per-GW user performance history from entry/{team_id}/history/.
        Returns number of rows upserted.
        """
        current_season = history_data.get("current", [])
        if not current_season:
            return 0

        async with AsyncSessionLocal() as db:
            for gw_entry in current_season:
                gw_id = gw_entry.get("event")
                if not gw_id:
                    continue

                stmt = pg_insert(UserGWHistory).values(
                    team_id=team_id,
                    gw_id=gw_id,
                    points=gw_entry.get("points", 0),
                    total_points=gw_entry.get("total_points", 0),
                    rank=gw_entry.get("rank"),
                    rank_sort=gw_entry.get("rank_sort"),
                    overall_rank=gw_entry.get("overall_rank"),
                    bank=gw_entry.get("bank", 0),
                    value=gw_entry.get("value", 0),
                    event_transfers=gw_entry.get("event_transfers", 0),
                    event_transfers_cost=gw_entry.get("event_transfers_cost", 0),
                    points_on_bench=gw_entry.get("points_on_bench", 0),
                ).on_conflict_do_update(
                    index_elements=["team_id", "gw_id"],
                    set_={
                        "points": gw_entry.get("points", 0),
                        "total_points": gw_entry.get("total_points", 0),
                        "rank": gw_entry.get("rank"),
                        "rank_sort": gw_entry.get("rank_sort"),
                        "overall_rank": gw_entry.get("overall_rank"),
                        "bank": gw_entry.get("bank", 0),
                        "value": gw_entry.get("value", 0),
                        "event_transfers": gw_entry.get("event_transfers", 0),
                        "event_transfers_cost": gw_entry.get("event_transfers_cost", 0),
                        "points_on_bench": gw_entry.get("points_on_bench", 0),
                    },
                )
                await db.execute(stmt)
            await db.commit()
        logger.info(f"Upserted {len(current_season)} user GW history rows for team {team_id}")
        return len(current_season)

    async def upsert_player_gw_history(self, player_id: int, summary_data: dict) -> int:
        """
        Upsert per-GW player stats from element-summary/{player_id}/.
        Returns number of rows upserted.
        """
        history = summary_data.get("history", [])
        if not history:
            return 0

        async with AsyncSessionLocal() as db:
            for entry in history:
                gw_id = entry.get("round")
                if not gw_id:
                    continue

                stmt = pg_insert(PlayerGWHistory).values(
                    player_id=player_id,
                    gw_id=gw_id,
                    total_points=entry.get("total_points", 0),
                    minutes=entry.get("minutes", 0),
                    goals_scored=entry.get("goals_scored", 0),
                    assists=entry.get("assists", 0),
                    clean_sheets=entry.get("clean_sheets", 0),
                    yellow_cards=entry.get("yellow_cards", 0),
                    red_cards=entry.get("red_cards", 0),
                    saves=entry.get("saves", 0),
                    bonus=entry.get("bonus", 0),
                    bps=entry.get("bps", 0),
                    expected_goals=float(entry.get("expected_goals", 0) or 0),
                    expected_assists=float(entry.get("expected_assists", 0) or 0),
                    expected_goal_involvements=float(entry.get("expected_goal_involvements", 0) or 0),
                    value=entry.get("value", 0),
                    selected=entry.get("selected", 0),
                    transfers_in=entry.get("transfers_in", 0),
                    transfers_out=entry.get("transfers_out", 0),
                    was_home=entry.get("was_home", False),
                    team_h_score=entry.get("team_h_score"),
                    team_a_score=entry.get("team_a_score"),
                ).on_conflict_do_update(
                    index_elements=["player_id", "gw_id"],
                    set_={
                        "total_points": entry.get("total_points", 0),
                        "minutes": entry.get("minutes", 0),
                        "goals_scored": entry.get("goals_scored", 0),
                        "assists": entry.get("assists", 0),
                        "clean_sheets": entry.get("clean_sheets", 0),
                        "yellow_cards": entry.get("yellow_cards", 0),
                        "red_cards": entry.get("red_cards", 0),
                        "saves": entry.get("saves", 0),
                        "bonus": entry.get("bonus", 0),
                        "bps": entry.get("bps", 0),
                        "expected_goals": float(entry.get("expected_goals", 0) or 0),
                        "expected_assists": float(entry.get("expected_assists", 0) or 0),
                        "expected_goal_involvements": float(entry.get("expected_goal_involvements", 0) or 0),
                        "value": entry.get("value", 0),
                        "selected": entry.get("selected", 0),
                        "transfers_in": entry.get("transfers_in", 0),
                        "transfers_out": entry.get("transfers_out", 0),
                        "was_home": entry.get("was_home", False),
                    },
                )
                await db.execute(stmt)
            await db.commit()
        return len(history)
