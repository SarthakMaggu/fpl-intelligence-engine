from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Any

from core.config import settings


REQUIRED_SIGNAL_FAMILIES = (
    "expected_points",
    "minutes",
    "fixture",
    "simulation",
    "form",
    "risk",
    "calibration",
)


@dataclass
class DecisionContext:
    recommendation_type: str
    risk_preference: str = "balanced"
    current_gameweek: int | None = None
    team_id: int | None = None


class DecisionEngine:
    """
    Shared recommendation synthesis layer.

    This sits behind the existing recommendation endpoints and enriches their
    outputs with confidence, risk, validation, differential edge, and
    explanation metadata without forcing frontend flow changes.
    """

    def __init__(self) -> None:
        self.mode = settings.DECISION_ENGINE_MODE
        self.default_risk_preference = settings.DEFAULT_RISK_PROFILE

    def should_replace_live_output(self, team_id: int | None = None) -> bool:
        if self.mode in {"enabled", "full"}:
            return True
        if self.mode == "admin":
            return team_id == settings.FPL_TEAM_ID
        return False

    def should_emit_shadow(self) -> bool:
        return self.mode == "shadow"

    def synthesize_player_recommendation(
        self,
        player: dict[str, Any],
        *,
        context: DecisionContext,
        baseline_score: float | None = None,
    ) -> dict[str, Any]:
        xpts = float(player.get("predicted_xpts_next", 0) or 0.0)
        start_prob = self._clamp(player.get("predicted_start_prob", player.get("start_probability", 0.72)) or 0.72)
        expected_minutes = float(player.get("expected_minutes", start_prob * 90.0) or (start_prob * 90.0))
        ownership = float(player.get("selected_by_percent", player.get("ownership", 35.0)) or 35.0)
        fdr = int(player.get("fdr_next", 3) or 3)
        is_home = bool(player.get("is_home_next", player.get("is_home", False)))
        has_double = bool(player.get("has_double_gw", False))
        form_score = self._safe_float(player.get("form"))
        form_trend = str(player.get("form_trend") or "stable")
        calibration_factor = float(player.get("calibration_factor", 1.0) or 1.0)

        fixture_strength = self._fixture_strength(fdr=fdr, is_home=is_home, has_double=has_double)
        minutes_risk = round(max(0.0, 1.0 - start_prob), 4)
        form_adjustment = round(self._form_adjustment(form_score=form_score, form_trend=form_trend), 3)
        differential_score = round(self._differential_score(xpts=xpts, ownership=ownership, start_prob=start_prob), 3)
        simulation_ev = round(xpts * (0.82 + start_prob * 0.18) * fixture_strength * calibration_factor, 3)
        variance = round(self._variance(xpts=xpts, start_prob=start_prob, ownership=ownership, form_score=form_score), 3)
        floor = round(max(0.0, simulation_ev - variance * 1.05), 2)
        median = round(max(floor, simulation_ev), 2)
        ceiling = round(max(median, simulation_ev + variance * (1.45 if context.risk_preference == "aggressive" else 1.15)), 2)

        risk_penalty = round(
            variance * (0.75 if context.risk_preference == "safe" else 0.5 if context.risk_preference == "balanced" else 0.25),
            3,
        )
        score = round(
            simulation_ev
            + form_adjustment
            + differential_score * (0.45 if context.risk_preference == "aggressive" else 0.2)
            - risk_penalty,
            3,
        )

        signals = self._validation_signals(
            xpts=xpts,
            start_prob=start_prob,
            fixture_strength=fixture_strength,
            simulation_ev=simulation_ev,
            form_score=form_score,
            variance=variance,
            calibration_factor=calibration_factor,
        )
        validation = self._validation_payload(signals)
        confidence = self._confidence_score(
            start_prob=start_prob,
            variance=variance,
            validation_ratio=validation["coverage_ratio"],
            baseline_score=baseline_score,
            score=score,
        )

        explanation = self._build_explanation(
            player_name=str(player.get("web_name", player.get("name", "Player"))),
            xpts=xpts,
            expected_minutes=expected_minutes,
            fixture_strength=fixture_strength,
            form_trend=form_trend,
            has_double=has_double,
            ownership=ownership,
            context=context,
            confidence=confidence,
        )

        enriched = {
            **player,
            "decision_score": score,
            "confidence_score": confidence,
            "confidence_label": self._confidence_label(confidence),
            "risk_label": self._risk_label(variance),
            "risk_profile": self._risk_profile(context.risk_preference, variance=variance, differential_score=differential_score),
            "minutes_risk": round(minutes_risk, 3),
            "fixture_strength": round(fixture_strength, 3),
            "form_adjustment": form_adjustment,
            "simulation_ev": simulation_ev,
            "differential_score": differential_score,
            "floor_projection": floor,
            "median_projection": median,
            "ceiling_projection": ceiling,
            "projection_variance": variance,
            "expected_minutes": round(expected_minutes, 1),
            "validation": validation,
            "validation_complete": validation["complete"],
            "inputs_used": validation["signals"],
            "explanation_summary": explanation["summary"],
            "explanation_reasons": explanation["reasons"],
            "risk_preference": context.risk_preference,
            "synthesis_version": "decision-engine-v1",
        }
        return enriched

    def synthesize_captain_candidates(
        self,
        candidates: list[dict[str, Any]],
        *,
        context: DecisionContext,
    ) -> list[dict[str, Any]]:
        enriched = [self.synthesize_player_recommendation(c, context=context, baseline_score=float(c.get("score", c.get("captain_score", 0)) or 0)) for c in candidates]
        enriched.sort(key=lambda item: item["decision_score"], reverse=True)
        for idx, item in enumerate(enriched):
            item["captain_style"] = "safe" if idx == 0 else "balanced" if idx == 1 else "aggressive"
        return enriched

    def synthesize_transfer_suggestions(
        self,
        suggestions: list[dict[str, Any]],
        *,
        context: DecisionContext,
    ) -> list[dict[str, Any]]:
        enriched: list[dict[str, Any]] = []
        for suggestion in suggestions:
            player_in = suggestion.get("player_in", {})
            player_out = suggestion.get("player_out", {})
            incoming = self.synthesize_player_recommendation(
                {
                    **player_in,
                    "predicted_xpts_next": suggestion.get("xpts_gain_next", 0) + float(player_out.get("predicted_xpts_next", 0) or 0),
                },
                context=context,
                baseline_score=float(suggestion.get("net_gain_3gw", suggestion.get("xpts_gain_3gw", 0)) or 0),
            )
            gain_3gw = float(suggestion.get("xpts_gain_3gw", 0) or 0)
            net_gain = float(suggestion.get("net_gain_3gw", gain_3gw) or gain_3gw)
            volatility = round(incoming["projection_variance"] + abs(gain_3gw - float(suggestion.get("xpts_gain_next", 0) or 0)) * 0.35, 3)
            confidence = max(35, min(98, int(incoming["confidence_score"] - volatility * 4 + max(net_gain, 0) * 2.5)))
            enriched.append(
                {
                    **suggestion,
                    "decision_score": round(net_gain + incoming["decision_score"] * 0.55 - volatility * 0.35, 3),
                    "confidence_score": confidence,
                    "confidence_label": self._confidence_label(confidence),
                    "risk_label": self._risk_label(volatility),
                    "risk_profile": self._risk_profile(context.risk_preference, variance=volatility, differential_score=incoming["differential_score"]),
                    "floor_projection": round(max(-4.0, net_gain - volatility), 2),
                    "median_projection": round(net_gain, 2),
                    "ceiling_projection": round(net_gain + volatility * 1.25, 2),
                    "projection_variance": volatility,
                    "differential_signal": incoming["differential_score"] >= 1.25,
                    "minutes_security": round(1.0 - incoming["minutes_risk"], 3),
                    "simulation_value": incoming["simulation_ev"],
                    "validation": incoming["validation"],
                    "validation_complete": incoming["validation_complete"],
                    "inputs_used": incoming["inputs_used"],
                    "explanation_summary": self._transfer_summary(suggestion=suggestion, incoming=incoming),
                    "explanation_reasons": self._transfer_reasons(suggestion=suggestion, incoming=incoming),
                    "risk_preference": context.risk_preference,
                }
            )
        enriched.sort(key=lambda item: item["decision_score"], reverse=True)
        return enriched

    def synthesize_priority_actions(
        self,
        actions: list[dict[str, Any]],
        *,
        context: DecisionContext,
    ) -> list[dict[str, Any]]:
        enriched: list[dict[str, Any]] = []
        for action in actions:
            impact_value = float(action.get("impact_value", 0) or 0)
            urgency = str(action.get("urgency", "LOW"))
            urgency_boost = {"HIGH": 1.3, "MEDIUM": 1.05, "LOW": 0.85}.get(urgency, 1.0)
            score = round(impact_value * urgency_boost + (1.2 if action.get("must_do") else 0.0), 3)
            confidence = max(40, min(95, int(62 + impact_value * 5 + (10 if urgency == "HIGH" else 0) - (6 if action.get("type") == "chip" else 0))))
            validation = {
                "complete": action.get("type") not in {"injury", "chip"},
                "coverage_ratio": 1.0 if action.get("type") not in {"injury", "chip"} else 0.57,
                "signals": {
                    "expected_points": True,
                    "minutes": action.get("type") != "chip",
                    "fixture": True,
                    "simulation": action.get("type") in {"captain", "transfer", "bench_swap"},
                    "form": action.get("type") in {"captain", "transfer", "bench_swap"},
                    "risk": True,
                    "calibration": action.get("type") in {"captain", "transfer"},
                },
            }
            enriched.append(
                {
                    **action,
                    "decision_score": score,
                    "confidence_score": confidence,
                    "confidence_label": self._confidence_label(confidence),
                    "risk_label": "low" if urgency == "HIGH" and action.get("type") == "injury" else "medium",
                    "risk_profile": "safe" if action.get("type") in {"injury", "bench_swap"} else context.risk_preference,
                    "floor_projection": round(max(0.0, impact_value * 0.6), 2),
                    "median_projection": round(max(0.0, impact_value), 2),
                    "ceiling_projection": round(max(0.0, impact_value * 1.35), 2),
                    "projection_variance": round(max(0.2, impact_value * 0.22), 2),
                    "differential_signal": action.get("type") == "captain" and "DGW" in str(action.get("reasoning", "")),
                    "validation": validation,
                    "validation_complete": validation["complete"],
                    "inputs_used": validation["signals"],
                    "explanation_summary": action.get("reasoning") or action.get("label"),
                    "explanation_reasons": [action.get("reasoning") or action.get("label")],
                    "risk_preference": context.risk_preference,
                }
            )
        enriched.sort(key=lambda item: (-item["decision_score"], item.get("priority", 99)))
        for idx, item in enumerate(enriched):
            item["priority"] = idx + 1
        return enriched

    def build_shadow_payload(self, *, current: list[dict[str, Any]], synthesized: list[dict[str, Any]], label: str) -> dict[str, Any]:
        current_top = current[0] if current else None
        synthesized_top = synthesized[0] if synthesized else None
        changed = False
        if current_top and synthesized_top:
            current_name = current_top.get("web_name") or current_top.get("player_in_name") or current_top.get("label")
            synth_name = synthesized_top.get("web_name") or synthesized_top.get("player_in_name") or synthesized_top.get("label")
            changed = current_name != synth_name
        return {
            "mode": "shadow",
            "label": label,
            "changed_top_recommendation": changed,
            "current_top": self._shadow_label(current_top),
            "synthesized_top": self._shadow_label(synthesized_top),
            "current_count": len(current),
            "synthesized_count": len(synthesized),
        }

    def frozen_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "captured_at": payload.get("captured_at"),
            "mode": self.mode,
            "gameweek": payload.get("gameweek"),
            "team_id": payload.get("team_id"),
            "payload": payload,
        }

    def _shadow_label(self, item: dict[str, Any] | None) -> str | None:
        if not item:
            return None
        return item.get("web_name") or item.get("player_in_name") or item.get("label")

    def _fixture_strength(self, *, fdr: int, is_home: bool, has_double: bool) -> float:
        base = {1: 1.22, 2: 1.11, 3: 1.0, 4: 0.88, 5: 0.76}.get(fdr, 1.0)
        if is_home:
            base += 0.04
        if has_double:
            base += 0.18
        return round(base, 3)

    def _form_adjustment(self, *, form_score: float, form_trend: str) -> float:
        trend_boost = {"rising": 0.45, "stable": 0.15, "falling": -0.25}.get(form_trend, 0.0)
        return min(1.2, (form_score / 10.0) + trend_boost)

    def _differential_score(self, *, xpts: float, ownership: float, start_prob: float) -> float:
        ownership_factor = max(0.0, (25.0 - min(ownership, 25.0)) / 10.0)
        return ownership_factor * max(0.0, xpts / 5.0) * max(0.5, start_prob)

    def _variance(self, *, xpts: float, start_prob: float, ownership: float, form_score: float) -> float:
        ownership_vol = max(0.0, (20.0 - min(ownership, 20.0)) / 20.0)
        start_vol = 1.0 - start_prob
        form_vol = max(0.0, (6.0 - min(form_score, 6.0)) / 8.0)
        return max(0.45, round(xpts * 0.18 + ownership_vol + start_vol + form_vol, 3))

    def _validation_signals(
        self,
        *,
        xpts: float,
        start_prob: float,
        fixture_strength: float,
        simulation_ev: float,
        form_score: float,
        variance: float,
        calibration_factor: float,
    ) -> dict[str, bool]:
        return {
            "expected_points": xpts > 0,
            "minutes": start_prob >= 0,
            "fixture": fixture_strength > 0,
            "simulation": simulation_ev > 0,
            "form": form_score >= 0,
            "risk": variance >= 0,
            "calibration": calibration_factor > 0,
        }

    def _validation_payload(self, signals: dict[str, bool]) -> dict[str, Any]:
        covered = sum(1 for item in REQUIRED_SIGNAL_FAMILIES if signals.get(item))
        ratio = covered / len(REQUIRED_SIGNAL_FAMILIES)
        return {
            "complete": ratio >= 0.99,
            "coverage_ratio": round(ratio, 3),
            "signals": signals,
            "missing": [item for item in REQUIRED_SIGNAL_FAMILIES if not signals.get(item)],
        }

    def _confidence_score(
        self,
        *,
        start_prob: float,
        variance: float,
        validation_ratio: float,
        baseline_score: float | None,
        score: float,
    ) -> int:
        agreement = 1.0
        if baseline_score is not None:
            agreement = max(0.3, 1.0 - min(abs(score - baseline_score) / 10.0, 0.7))
        confidence = 100 * (
            0.38 * start_prob
            + 0.24 * validation_ratio
            + 0.20 * agreement
            + 0.18 * max(0.0, 1.0 - min(variance / 4.0, 1.0))
        )
        return int(max(25, min(98, round(confidence))))

    def _confidence_label(self, confidence: int) -> str:
        if confidence >= 80:
            return "high"
        if confidence >= 60:
            return "medium"
        return "low"

    def _risk_label(self, variance: float) -> str:
        if variance <= 1.0:
            return "low"
        if variance <= 2.0:
            return "medium"
        return "high"

    def _risk_profile(self, risk_preference: str, *, variance: float, differential_score: float) -> str:
        if risk_preference == "safe":
            return "safe_pick"
        if risk_preference == "aggressive" or differential_score >= 1.25 or variance > 2.2:
            return "high_risk_high_reward"
        return "balanced_pick"

    def _build_explanation(
        self,
        *,
        player_name: str,
        xpts: float,
        expected_minutes: float,
        fixture_strength: float,
        form_trend: str,
        has_double: bool,
        ownership: float,
        context: DecisionContext,
        confidence: int,
    ) -> dict[str, Any]:
        reasons = [
            f"{player_name} projects {xpts:.1f} expected points.",
            f"Expected minutes sit around {expected_minutes:.0f}.",
            f"Fixture profile grades at {fixture_strength:.2f}x baseline.",
        ]
        if form_trend == "rising":
            reasons.append("Recent form trend is improving.")
        if has_double:
            reasons.append("Double-gameweek upside lifts the ceiling.")
        if ownership < 15:
            reasons.append("Low ownership adds differential edge.")
        summary = f"{player_name} is the {context.risk_preference} {context.recommendation_type} play with {confidence}% confidence."
        return {"summary": summary, "reasons": reasons[:5]}

    def _transfer_summary(self, *, suggestion: dict[str, Any], incoming: dict[str, Any]) -> str:
        out_name = suggestion.get("player_out", {}).get("web_name", "out")
        in_name = suggestion.get("player_in", {}).get("web_name", "in")
        return (
            f"{out_name} -> {in_name} rates as a {incoming['risk_profile'].replace('_', ' ')} move "
            f"with {incoming['confidence_score']}% confidence and {incoming['simulation_ev']:.1f} simulation EV."
        )

    def _transfer_reasons(self, *, suggestion: dict[str, Any], incoming: dict[str, Any]) -> list[str]:
        reasons = [
            f"3-GW gain projects at {float(suggestion.get('xpts_gain_3gw', 0) or 0):.1f} xPts.",
            f"Incoming player minutes security is {max(0, 100 - int(incoming['minutes_risk'] * 100))}%.",
            f"Risk profile is {incoming['risk_profile'].replace('_', ' ')}.",
        ]
        if incoming["differential_score"] >= 1.25:
            reasons.append("Differential edge is materially positive.")
        return reasons

    def _safe_float(self, value: Any) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _clamp(self, value: float) -> float:
        return max(0.0, min(1.0, float(value)))


decision_engine = DecisionEngine()
