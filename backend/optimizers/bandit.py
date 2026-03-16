"""
UCB1 Multi-Armed Bandit for FPL Decision Making.

Learns which strategy produces the best outcomes for each decision type
by tracking predicted vs actual GW points and updating Q-values.

Decision types and arms:
  transfer_strategy:  greedy | ilp | hold
  captain_pick:       top_xpts | differential | form_weighted
  chip_timing:        play_now | wait_1_gw | skip
  hit_decision:       take_hit | hold

Q-values and counts are stored in Redis as hashes so they persist across
requests without a DB round-trip. DB records (BanditDecision) are written
for auditability and long-term analysis.

UCB1 formula:
  score(a) = Q(a) + sqrt(2 * ln(N+1) / n(a))
  where Q(a) = mean reward for arm a, N = total pulls, n(a) = pulls for arm a
  Unexplored arms (n=0) always get +inf score → guaranteed exploration.
"""
import math
import json
from typing import Optional
from loguru import logger


DECISION_ARMS: dict[str, list[str]] = {
    "transfer_strategy": ["greedy", "ilp", "hold"],
    "captain_pick": ["top_xpts", "differential", "form_weighted"],
    "chip_timing": ["play_now", "wait_1_gw", "skip"],
    "hit_decision": ["take_hit", "hold"],
    # Phase 2: captain strategy layer — blends model signal with meta-game risk
    "captain_strategy": [
        "model_pick",        # highest raw xPts (ML model recommendation)
        "form_pick",         # best recent form × xPts blend
        "fixture_pick",      # best fixture (lowest FDR next GW)
        "differential_pick", # low-ownership (<15%) upside play
        "safe_pick",         # highest combined ownership + xPts (template captain)
    ],
}

# Redis key pattern: bandit:{team_id}:{decision_type}
# Value: JSON {"q": {arm: float}, "n": {arm: int}, "total_n": int}
_REDIS_KEY_TTL = 60 * 60 * 24 * 365  # 1 year — persist across season


class UCB1Bandit:
    """Upper Confidence Bound (UCB1) bandit for FPL decisions."""

    def __init__(self, exploration_constant: float = math.sqrt(2)):
        self.c = exploration_constant

    # ── Redis state helpers ──────────────────────────────────────────────────

    def _redis_key(self, team_id: int, decision_type: str) -> str:
        return f"bandit:{team_id}:{decision_type}"

    async def _load_state(self, team_id: int, decision_type: str) -> dict:
        """Load bandit state from Redis. Returns default state if not found."""
        from core.redis_client import redis_client
        key = self._redis_key(team_id, decision_type)
        raw = await redis_client.get(key)
        if raw:
            return json.loads(raw)
        arms = DECISION_ARMS.get(decision_type, [])
        return {
            "q": {arm: 0.0 for arm in arms},
            "n": {arm: 0 for arm in arms},
            "total_n": 0,
        }

    async def _save_state(self, team_id: int, decision_type: str, state: dict) -> None:
        from core.redis_client import redis_client
        key = self._redis_key(team_id, decision_type)
        await redis_client.set(key, json.dumps(state), ex=_REDIS_KEY_TTL)

    # ── Core UCB1 logic ──────────────────────────────────────────────────────

    def _ucb1_score(self, q: float, n: int, total_n: int) -> float:
        """UCB1 score for one arm."""
        if n == 0:
            return float("inf")
        return q + self.c * math.sqrt(math.log(total_n + 1) / n)

    def select_arm(self, state: dict, decision_type: str) -> str:
        """Select best arm using UCB1 scores."""
        arms = DECISION_ARMS.get(decision_type, [])
        total_n = state["total_n"]
        scores = {
            arm: self._ucb1_score(
                state["q"].get(arm, 0.0),
                state["n"].get(arm, 0),
                total_n,
            )
            for arm in arms
        }
        best = max(scores, key=scores.__getitem__)
        logger.debug(f"Bandit {decision_type}: UCB1 scores={scores} → selected={best}")
        return best

    def update_arm(self, state: dict, arm: str, reward: float) -> dict:
        """Incremental mean update: Q(a) ← Q(a) + (r - Q(a)) / N(a)."""
        n = state["n"].get(arm, 0) + 1
        q_old = state["q"].get(arm, 0.0)
        q_new = q_old + (reward - q_old) / n
        state["q"][arm] = round(q_new, 4)
        state["n"][arm] = n
        state["total_n"] = state.get("total_n", 0) + 1
        return state

    # ── Public API ───────────────────────────────────────────────────────────

    async def recommend(
        self,
        team_id: int,
        decision_type: str,
        context: Optional[dict] = None,
    ) -> dict:
        """
        Returns the recommended arm for a decision type.

        Response includes:
          arm: str                    — recommended strategy
          q_values: dict[str, float]  — current Q-value for each arm
          n_counts: dict[str, int]    — times each arm has been tried
          total_pulls: int
          is_exploring: bool          — True if UCB1 is exploring (not just exploiting)
        """
        if decision_type not in DECISION_ARMS:
            raise ValueError(f"Unknown decision type: {decision_type}. Valid: {list(DECISION_ARMS.keys())}")

        state = await self._load_state(team_id, decision_type)
        arm = self.select_arm(state, decision_type)

        # Check if we're exploring (any unexplored arm → all have n=0 initially)
        arms = DECISION_ARMS[decision_type]
        is_exploring = any(state["n"].get(a, 0) == 0 for a in arms)

        return {
            "arm": arm,
            "decision_type": decision_type,
            "q_values": {a: round(state["q"].get(a, 0.0), 3) for a in arms},
            "n_counts": {a: state["n"].get(a, 0) for a in arms},
            "total_pulls": state["total_n"],
            "is_exploring": is_exploring,
            "context": context or {},
            "explanation": self._explain(arm, decision_type, state, is_exploring),
        }

    async def record_outcome(
        self,
        team_id: int,
        decision_type: str,
        arm: str,
        predicted_value: float,
        actual_value: float,
    ) -> dict:
        """
        Record the outcome of a decision and update Q-values.

        reward = (actual - predicted) / max(abs(predicted), 1.0)
        Normalised so reward ∈ roughly [-1, +1].
        Positive reward = better than expected. Negative = worse.
        """
        if decision_type not in DECISION_ARMS:
            raise ValueError(f"Unknown decision type: {decision_type}")

        denom = max(abs(predicted_value), 1.0)
        reward = (actual_value - predicted_value) / denom

        state = await self._load_state(team_id, decision_type)
        state = self.update_arm(state, arm, reward)
        await self._save_state(team_id, decision_type, state)

        logger.info(
            f"Bandit outcome: team={team_id} type={decision_type} arm={arm} "
            f"predicted={predicted_value:.2f} actual={actual_value:.2f} reward={reward:.3f}"
        )

        return {
            "arm": arm,
            "reward": round(reward, 4),
            "updated_q": round(state["q"].get(arm, 0.0), 4),
            "n": state["n"].get(arm, 0),
            "total_pulls": state["total_n"],
        }

    async def get_all_states(self, team_id: int) -> dict:
        """Return full bandit state for all decision types (for debugging/display)."""
        result = {}
        for dt in DECISION_ARMS:
            state = await self._load_state(team_id, dt)
            arms = DECISION_ARMS[dt]
            result[dt] = {
                "arms": arms,
                "q_values": {a: round(state["q"].get(a, 0.0), 3) for a in arms},
                "n_counts": {a: state["n"].get(a, 0) for a in arms},
                "total_pulls": state["total_n"],
                "best_arm": max(arms, key=lambda a: state["q"].get(a, 0.0)) if any(state["n"].get(a, 0) > 0 for a in arms) else "unexplored",
            }
        return result

    def _explain(self, arm: str, decision_type: str, state: dict, is_exploring: bool) -> str:
        explanations = {
            ("transfer_strategy", "greedy"): "Greedy: transfer your weakest XI player for the highest-gain available player.",
            ("transfer_strategy", "ilp"):    "ILP: trust the globally optimal transfer plan from the integer linear program.",
            ("transfer_strategy", "hold"):   "Hold: no transfers — current squad is strong enough for this GW.",
            ("captain_pick", "top_xpts"):    "Top xPts: captain the player with the highest expected points.",
            ("captain_pick", "differential"):"Differential: captain a low-ownership player for rank gain potential.",
            ("captain_pick", "form_weighted"):"Form-weighted: blend current form with predicted xPts for the captain pick.",
            ("chip_timing", "play_now"):     "Play chip this GW — conditions are optimal.",
            ("chip_timing", "wait_1_gw"):    "Wait one GW — better chip timing window is coming.",
            ("chip_timing", "skip"):         "Skip chip — save it for a more impactful moment.",
            ("hit_decision", "take_hit"):    "Take the -4pt hit — the 3GW net gain justifies the cost.",
            ("hit_decision", "hold"):        "Hold — insufficient gain to justify a hit this GW.",
        }
        captain_strategy_explanations = {
            "model_pick":        "ML Model Pick: captain the player with the highest model-predicted xPts.",
            "form_pick":         "Form Pick: captain the player with the best recent form × xPts blend.",
            "fixture_pick":      "Fixture Pick: captain the player with the easiest next fixture (lowest FDR).",
            "differential_pick": "Differential Pick: captain a low-ownership (<15%) player for rank gain potential.",
            "safe_pick":         "Safe Pick: captain the highest ownership player — minimises rank loss risk.",
        }
        for k, v in captain_strategy_explanations.items():
            explanations[("captain_strategy", k)] = v

        base = explanations.get((decision_type, arm), f"Selected arm: {arm}")
        n = state["n"].get(arm, 0)
        if is_exploring:
            return f"{base} [Exploring — only {n} prior observations]"
        q = state["q"].get(arm, 0.0)
        return f"{base} [Q={q:.3f}, n={n} obs]"
