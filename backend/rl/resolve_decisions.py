"""
resolve_decisions — compute actual outcome data before writing rewards to decision_log.

Called by oracle.py auto_resolve_oracle() after GW results are available.
Fetches actual player/squad points, fills actual_points in decision_log rows,
then delegates to reward functions and auto-updates UCB1 bandit Q-values.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db.decision_log import DecisionLog
from models.db.history import PlayerGWHistory, UserGWHistory
from rl.rewards import (
    compute_captain_reward,
    compute_chip_reward,
    compute_hit_reward,
    compute_transfer_reward,
)

logger = logging.getLogger(__name__)


async def resolve_gw_decisions(
    team_id: int,
    gw_id: int,
    db: AsyncSession,
    *,
    captain_player_id: Optional[int] = None,
    chip_played: Optional[str] = None,
) -> int:
    """
    Resolve all unresolved decision_log rows for a team + GW.

    Steps:
    1. Load unresolved DecisionLog rows.
    2. Load actual GW history for the team from user_gw_history.
    3. For each decision, compute actual_points and reward using the correct
       hit_taken value stored on the row (no longer hardcoded False).
    4. Mark resolved=True, set resolved_at.
    5. Auto-update UCB1 bandit Q-values for rows that have engine_strategy_arm.

    Returns:
        Number of rows resolved.
    """
    # Load unresolved decisions for this team/GW
    result = await db.execute(
        select(DecisionLog).where(
            DecisionLog.team_id == team_id,
            DecisionLog.gameweek_id == gw_id,
            DecisionLog.resolved == False,  # noqa: E712
        )
    )
    decisions: List[DecisionLog] = list(result.scalars().all())

    if not decisions:
        return 0

    # Load user's actual GW history row
    gw_hist_res = await db.execute(
        select(UserGWHistory).where(
            UserGWHistory.team_id == team_id,
            UserGWHistory.event == gw_id,
        )
    )
    gw_hist = gw_hist_res.scalar_one_or_none()
    actual_total_pts = float(gw_hist.points) if gw_hist else 0.0
    avg_gw_pts = float(gw_hist.points) if gw_hist else 40.0  # fallback average

    # Load player-level history for the GW (for captain points)
    player_pts_map: Dict[int, float] = {}
    if captain_player_id:
        cap_res = await db.execute(
            select(PlayerGWHistory).where(
                PlayerGWHistory.event == gw_id,
                PlayerGWHistory.element == captain_player_id,
            )
        )
        cap_hist = cap_res.scalar_one_or_none()
        if cap_hist:
            player_pts_map[captain_player_id] = float(cap_hist.total_points)

    resolved_count = 0
    now = datetime.now(timezone.utc)

    # Collect (decision_type, arm, reward) tuples for bandit updates
    bandit_updates: List[tuple] = []

    for decision in decisions:
        was_followed = decision.decision_followed or False
        predicted_gain = decision.engine_predicted_gain or 0.0
        # Normalise decision_type to lowercase for matching
        dt = (decision.decision_type or "").lower()

        if dt in ("captain", "captain_pick", "captain_strategy"):
            # Use actual_gain if cross-check already filled it (player's pts × 2 bonus)
            if decision.actual_gain is not None:
                actual_pts = float(decision.actual_gain) * 2  # restore 2× captain value
            else:
                actual_pts = player_pts_map.get(captain_player_id or -1, 0.0) * 2
            decision.actual_points = actual_pts
            decision.reward = compute_captain_reward(
                predicted_xpts=decision.expected_points,
                actual_captain_pts=actual_pts,
                was_followed=was_followed,
            )

        elif dt in ("transfer", "transfer_strategy"):
            decision.actual_points = actual_total_pts
            # Use actual_gain (player_in pts - player_out pts) if set by cross-check
            gain = float(decision.actual_gain) if decision.actual_gain is not None else (actual_total_pts - avg_gw_pts)
            decision.reward = compute_transfer_reward(
                predicted_gain=predicted_gain,
                actual_gain=gain,
                hit_taken=bool(getattr(decision, "hit_taken", False)),
                was_followed=was_followed,
            )

        elif dt in ("chip", "chip_used", "chip_recommendation"):
            decision.actual_points = actual_total_pts
            decision.reward = compute_chip_reward(
                chip_used=chip_played or decision.recommended_option,
                chip_pts=actual_total_pts,
                avg_gw_pts=avg_gw_pts,
                was_followed=was_followed,
            )

        elif dt in ("hit",):
            decision.actual_points = actual_total_pts
            decision.reward = compute_hit_reward(
                pts_gained=actual_total_pts - avg_gw_pts + 4.0,  # vs no-hit baseline
                hit_cost=4.0,
                was_followed=was_followed,
            )

        else:
            # Unknown type — mark resolved with zero reward
            decision.reward = 0.0

        decision.resolved = True
        decision.resolved_at = now
        resolved_count += 1

        # Queue bandit update if we know which arm was used
        arm = getattr(decision, "engine_strategy_arm", None)
        if arm and decision.reward is not None:
            bandit_updates.append((
                decision.decision_type,
                arm,
                float(decision.engine_predicted_gain or decision.expected_points or 0.0),
                float(decision.actual_points or 0.0),
                decision.reward,
            ))

    await db.commit()
    logger.info(
        f"Resolved {resolved_count} decision_log rows for team {team_id} GW {gw_id}"
    )

    # ── Auto-update UCB1 bandit Q-values ──────────────────────────────────────
    # This closes the learning loop: every resolved decision feeds back into the bandit
    # without requiring a manual POST /api/bandit/outcome call.
    if bandit_updates:
        await _update_bandit_q_values(team_id, gw_id, bandit_updates)

    return resolved_count


async def _update_bandit_q_values(
    team_id: int,
    gw_id: int,
    updates: List[tuple],
) -> None:
    """
    Auto-update UCB1 bandit Q-values from resolved decision rewards.

    Each entry in `updates` is:
      (decision_type, arm, predicted_value, actual_value, reward)

    We instantiate a UCB1Bandit directly from the optimizers module so that
    this works even when called outside the HTTP request cycle (e.g. from
    the scheduler's oracle_resolve job). Because UCB1Bandit persists its
    state in Redis, all instances share the same Q-values.
    """
    try:
        from optimizers.bandit import UCB1Bandit
        bandit = UCB1Bandit()

        for (decision_type, arm, predicted_value, actual_value, _reward) in updates:
            try:
                await bandit.record_outcome(
                    team_id=team_id,
                    decision_type=decision_type,
                    arm=arm,
                    predicted_value=predicted_value,
                    actual_value=actual_value,
                )
            except Exception as arm_err:
                logger.warning(
                    f"Bandit Q-update failed for team={team_id} gw={gw_id} "
                    f"type={decision_type} arm={arm}: {arm_err}"
                )

        logger.info(
            f"Bandit Q-values auto-updated: team={team_id} gw={gw_id} "
            f"{len(updates)} decisions"
        )
    except Exception as e:
        # Never let bandit failures block the resolution flow
        logger.warning(f"Bandit auto-update failed (non-fatal): {e}")
