"""
RL reward functions — compute normalised scalar rewards [-1, 1] from decision outcomes.

Rewards are computed post-GW in resolve_decisions.py and stored in
decision_log.reward. They feed back into the UCB1 bandit via
api/routes/bandit.py POST /outcome.

All rewards are clipped to [-1, 1] to bound bandit Q-value updates.
"""
from __future__ import annotations

from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Captain pick reward
# ---------------------------------------------------------------------------

def compute_captain_reward(
    predicted_xpts: float,
    actual_captain_pts: float,
    was_followed: bool,
) -> float:
    """
    Reward for a captain pick decision.

    If the user followed the recommendation, reward = normalised gain vs prediction.
    If not followed, reward = 0.0 (bandit can't learn from rejected picks).

    Args:
        predicted_xpts: Engine's xPts estimate for the recommended captain.
        actual_captain_pts: Points scored by the chosen captain (2× multiplier applied).
        was_followed: True if user used the engine's recommended captain.

    Returns:
        Float in [-1, 1].
    """
    if not was_followed:
        return 0.0
    gain = actual_captain_pts - predicted_xpts
    return float(np.clip(gain / 10.0, -1.0, 1.0))


# ---------------------------------------------------------------------------
# Transfer reward
# ---------------------------------------------------------------------------

def compute_transfer_reward(
    predicted_gain: float,
    actual_gain: float,
    hit_taken: bool,
    was_followed: bool,
) -> float:
    """
    Reward for a transfer decision.

    Net gain = actual_gain minus hit cost (4 pts per hit).

    Args:
        predicted_gain: Engine's predicted net points gain from the transfer.
        actual_gain: Actual net points gained (player_in_pts - player_out_pts over next 3 GWs).
        hit_taken: True if user took a -4 hit.
        was_followed: True if user executed the recommended transfer.

    Returns:
        Float in [-1, 1].
    """
    if not was_followed:
        return 0.0
    hit_cost = 4.0 if hit_taken else 0.0
    net_gain = actual_gain - hit_cost
    return float(np.clip(net_gain / 10.0, -1.0, 1.0))


# ---------------------------------------------------------------------------
# Chip reward
# ---------------------------------------------------------------------------

def compute_chip_reward(
    chip_used: Optional[str],
    chip_pts: float,
    avg_gw_pts: float,
    was_followed: bool,
) -> float:
    """
    Reward for a chip timing decision.

    Reward = how much the chip boosted points vs the manager's rolling average GW score.

    Args:
        chip_used: Name of chip played ("wildcard", "free_hit", etc.) or None.
        chip_pts: Total points scored in the GW the chip was played.
        avg_gw_pts: Rolling 5-GW average points for this team.
        was_followed: True if user played the chip as recommended.

    Returns:
        Float in [-1, 1].
    """
    if not was_followed or chip_used is None:
        return 0.0
    delta = chip_pts - avg_gw_pts
    return float(np.clip(delta / 20.0, -1.0, 1.0))


# ---------------------------------------------------------------------------
# Hit decision reward
# ---------------------------------------------------------------------------

def compute_hit_reward(
    pts_gained: float,
    hit_cost: float = 4.0,
    was_followed: bool = True,
) -> float:
    """
    Reward for the hit decision (take_hit vs hold arm).

    Reward is positive when the transferred-in player outperformed by more than
    the hit cost, negative when the hit was not worth it.

    Args:
        pts_gained: Points scored by the player brought in via the hit.
        hit_cost: Cost of the hit in points (default 4.0).
        was_followed: True if user followed the take_hit recommendation.

    Returns:
        Float in [-1, 1].
    """
    if not was_followed:
        return 0.0
    net = pts_gained - hit_cost
    return float(np.clip(net / 10.0, -1.0, 1.0))
