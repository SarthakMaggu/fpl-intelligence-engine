"""
RL constants — bandit arm definitions per decision type.

Each arm maps to concrete behavior in the engine (captain, transfer, chip, hit).
These names are stored in bandit_decisions.arm_chosen and decision_log.engine_strategy_arm.
"""
from typing import Dict, List

# ---------------------------------------------------------------------------
# Captain pick arms
# top_xpts        — pick player with highest predicted xPts from your XI
# differential    — pick a low-owned player if xPts within 1.5 of top choice
# form_weighted   — blend xPts (60%) + last-3-GW actual pts (40%)
# ---------------------------------------------------------------------------
CAPTAIN_PICK_ARMS: List[str] = ["top_xpts", "differential", "form_weighted"]

# ---------------------------------------------------------------------------
# Transfer strategy arms
# greedy          — always take the single transfer with highest 3-GW xPts gain
# ilp             — use ILP solver to find globally optimal 1-2 transfers
# hold            — bank the free transfer (no outgoing transfer)
# ---------------------------------------------------------------------------
TRANSFER_STRATEGY_ARMS: List[str] = ["greedy", "ilp", "hold"]

# ---------------------------------------------------------------------------
# Chip timing arms
# play_now        — use chip this GW if criteria met (score > threshold)
# wait_1_gw       — delay by 1 GW (check again next cycle)
# skip            — don't play chip this GW regardless of criteria
# ---------------------------------------------------------------------------
CHIP_TIMING_ARMS: List[str] = ["play_now", "wait_1_gw", "skip"]

# ---------------------------------------------------------------------------
# Hit decision arms
# take_hit        — accept the -4 pts penalty if predicted gain > break-even
# hold            — never take a hit, use 1 free transfer max
# ---------------------------------------------------------------------------
HIT_DECISION_ARMS: List[str] = ["take_hit", "hold"]

# All arms by decision type
ARMS_BY_DECISION_TYPE: Dict[str, List[str]] = {
    "captain_pick": CAPTAIN_PICK_ARMS,
    "transfer_strategy": TRANSFER_STRATEGY_ARMS,
    "chip_timing": CHIP_TIMING_ARMS,
    "hit_decision": HIT_DECISION_ARMS,
}

# Minimum predicted gain (pts) to justify a hit (-4 pts cost)
HIT_BREAK_EVEN_PTS: float = 6.0   # >6 expected net gain to consider hit

# Captain differential: max xPts gap before preferring top_xpts
CAPTAIN_DIFFERENTIAL_MAX_GAP: float = 1.5

# Chip play_now thresholds
CHIP_TC_MIN_CAPTAIN_XPTS: float = 7.0     # TC threshold (lowered from 7.5 by OracleLearner)
CHIP_BB_MIN_DGW_BENCH_PLAYERS: int = 2   # BB only if ≥2 DGW players on bench
