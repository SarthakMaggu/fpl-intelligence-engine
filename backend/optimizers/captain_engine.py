"""
Captain Engine — ranks starting XI players for captaincy selection.

Scoring formula: xpts × FDR_factor × home_bonus × differential_bonus × double_gw_bonus

Key rules:
- No GK as captain
- Double GW captain scores twice (×1.8 expected multiplier)
- Differential captain: bonus if ownership < 20% (big differential upside)
"""
from dataclasses import dataclass
from typing import Optional
import pandas as pd


# FDR fixture difficulty → multiplier
FDR_FACTORS = {1: 1.30, 2: 1.20, 3: 1.00, 4: 0.75, 5: 0.50}

HOME_BONUS = 1.05   # slight home advantage in expected scoring
DGW_BONUS = 1.80    # double GW captain expected to score roughly twice


@dataclass
class CaptainCandidate:
    player_id: int
    web_name: str
    element_type: int
    xpts: float
    fdr_next: int
    is_home: bool
    ownership: float
    has_double_gw: bool
    captain_score: float
    fdr_factor: float
    is_differential: bool        # ownership < 20%
    reasoning: str


class CaptainEngine:

    def rank_candidates(
        self,
        squad_player_ids: list[int],
        players_df: pd.DataFrame,
        xi_ids: Optional[list[int]] = None,
    ) -> list[CaptainCandidate]:
        """
        Rank starting XI players by captain suitability.

        squad_player_ids: player IDs in starting XI (or full squad if xi_ids not provided)
        xi_ids: if provided, only consider XI players (not bench)
        """
        target_ids = set(xi_ids or squad_player_ids)
        target_df = players_df[players_df["id"].isin(target_ids)]

        candidates = []
        for _, row in target_df.iterrows():
            pos = int(row.get("element_type", 1))
            if pos == 1:  # No GK captains
                continue

            # Skip blank GW players — they can't score points, pointless to captain
            if bool(row.get("has_blank_gw", False)):
                continue
            # Skip 0-xPts players (injured, blank GW, suspended)
            if float(row.get("predicted_xpts_next", 0) or 0) <= 0:
                continue

            player_id = int(row["id"])
            xpts = float(row.get("predicted_xpts_next", 0) or 0)
            fdr = int(row.get("fdr_next", 3) or 3)
            is_home = bool(row.get("is_home_next", True))
            ownership = float(row.get("selected_by_percent", 50) or 50)
            has_double = bool(row.get("has_double_gw", False))

            fdr_factor = FDR_FACTORS.get(fdr, 1.0)
            home_bonus = HOME_BONUS if is_home else 1.0
            dgw_bonus = DGW_BONUS if has_double else 1.0
            is_diff = ownership < 20.0
            diff_bonus = 1.10 if is_diff else 1.0

            score = xpts * fdr_factor * home_bonus * dgw_bonus * diff_bonus

            # Build reasoning
            reasons = []
            if has_double:
                reasons.append(f"DGW (plays twice)")
            if fdr <= 2:
                reasons.append(f"Excellent fixture (FDR {fdr})")
            if is_home:
                reasons.append("Home advantage")
            if is_diff:
                reasons.append(f"Differential ({ownership:.1f}% owned)")
            if not reasons:
                reasons.append(f"FDR {fdr}, {'home' if is_home else 'away'}")

            candidates.append(CaptainCandidate(
                player_id=player_id,
                web_name=str(row.get("web_name", "")),
                element_type=pos,
                xpts=round(xpts, 2),
                fdr_next=fdr,
                is_home=is_home,
                ownership=round(ownership, 1),
                has_double_gw=has_double,
                captain_score=round(score, 3),
                fdr_factor=fdr_factor,
                is_differential=is_diff,
                reasoning=", ".join(reasons),
            ))

        candidates.sort(key=lambda c: c.captain_score, reverse=True)
        return candidates

    def get_captain(self, squad_player_ids, players_df, xi_ids=None) -> Optional[CaptainCandidate]:
        """Returns the top-ranked captain candidate."""
        ranked = self.rank_candidates(squad_player_ids, players_df, xi_ids)
        return ranked[0] if ranked else None

    def rank_captains(self, players: list[dict]) -> list[dict]:
        """
        Convenience method: accepts a list of player dicts (not DataFrame).
        Returns sorted list of dicts with captain score and reasoning.
        """
        candidates = []
        for p in players:
            pos = int(p.get("element_type", 1))
            if pos == 1:  # No GK captains
                continue

            xpts = float(p.get("predicted_xpts_next", 0) or 0)

            # Skip blank GW players and 0-xPts players — useless as captain picks
            if bool(p.get("has_blank_gw", False)) or xpts <= 0:
                continue
            fdr = int(p.get("fdr_next", 3) or 3)
            is_home = bool(p.get("is_home_next", True))
            ownership = float(p.get("selected_by_percent", 50) or 50)
            has_double = bool(p.get("has_double_gw", False))

            fdr_factor = FDR_FACTORS.get(fdr, 1.0)
            home_bonus = HOME_BONUS if is_home else 1.0
            dgw_bonus = DGW_BONUS if has_double else 1.0
            diff_bonus = 1.10 if ownership < 20.0 else 1.0

            score = xpts * fdr_factor * home_bonus * dgw_bonus * diff_bonus

            reasons = []
            if has_double:
                reasons.append("DGW (plays twice)")
            if fdr <= 2:
                reasons.append(f"Excellent fixture (FDR {fdr})")
            if is_home:
                reasons.append("Home advantage")
            if not reasons:
                reasons.append(f"FDR {fdr}, {'home' if is_home else 'away'}")

            candidates.append({
                "player_id": p.get("player_id") or p.get("id"),
                "web_name": p.get("web_name", ""),
                "element_type": pos,
                "score": round(score, 3),
                "predicted_xpts_next": xpts,
                "fdr_next": fdr,
                "is_home_next": is_home,
                "has_double_gw": has_double,
                "selected_by_percent": ownership,
                "reasoning": ", ".join(reasons),
                # Pass-through badge fields if provided by caller
                "team_code": p.get("team_code"),
                "team_short_name": p.get("team_short_name"),
            })

        candidates.sort(key=lambda c: c["score"], reverse=True)
        return candidates
