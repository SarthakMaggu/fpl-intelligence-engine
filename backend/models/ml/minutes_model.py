"""
Minutes Probability Model — predicts P(start) and P(60+ minutes played).

Used as inputs to the xPts model feature matrix.
Key signal: rotation risk from high-performing teams (Pep Guardiola style).
"""
import joblib
import numpy as np
import pandas as pd
from pathlib import Path
from loguru import logger

MODEL_START_PATH = Path("models/ml/artifacts/minutes_start_model.pkl")
MODEL_60_PATH = Path("models/ml/artifacts/minutes_60_model.pkl")

MINUTES_FEATURES = [
    # Original 12 features
    "minutes_last_5_gws",        # rolling total minutes
    "starts_last_5_gws",         # rolling starts count
    "chance_of_playing",         # FPL official (0-1 normalized)
    "status_available",          # binary: status == 'a'
    "price_millions",            # proxy for squad status (starters cost more)
    "is_set_piece_taker",        # regular starters take set pieces
    "team_fixture_count",        # double GW = 2, blank = 0, normal = 1
    "rotation_risk_score",       # computed from team variance
    "is_gk", "is_def", "is_mid", "is_fwd",

    # Phase 2 additions — rotation intelligence
    "rolling_minutes_last_5",    # per-90 minutes rate (normalised)
    "days_since_last_match",     # recency signal (< 4 days = rotation risk)
    "matches_last_7_days",       # fixture congestion proxy
    "team_depth_index",          # squad depth at the player's position (0-1)
    "manager_rotation_index",    # historical manager rotation tendency (0-1)
    "consecutive_starts",        # streak of consecutive starts
    "avg_minutes_per_game",      # season avg minutes/game
]

MIN_TRAIN_ROWS = 50


class MinutesModel:
    def __init__(self):
        self.start_model = None
        self.min60_model = None
        self._load()

    def _load(self) -> None:
        for path, attr in [(MODEL_START_PATH, "start_model"), (MODEL_60_PATH, "min60_model")]:
            if path.exists():
                try:
                    setattr(self, attr, joblib.load(path))
                    logger.info(f"Minutes model '{attr}' loaded")
                except Exception as e:
                    logger.warning(f"Failed to load {attr}: {e}")

    def _prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ensure all required features exist, fill missing with defaults."""
        available = [f for f in MINUTES_FEATURES if f in df.columns]
        X = df[available].fillna(0)
        return X

    def train(self, df: pd.DataFrame) -> dict:
        """
        Train start probability and 60min+ models.
        df must contain:
          - MINUTES_FEATURES columns
          - 'did_start' (binary: started in that GW)
          - 'played_60_plus' (binary: played 60+ min)
        """
        try:
            import lightgbm as lgb
            from sklearn.model_selection import cross_val_score
        except ImportError:
            return {"error": "lightgbm not installed"}

        df = df.dropna(subset=["did_start", "played_60_plus"])
        if len(df) < MIN_TRAIN_ROWS:
            return {"error": f"Need {MIN_TRAIN_ROWS} rows, got {len(df)}"}

        X = self._prepare_features(df)
        metrics = {}

        for target_col, model_attr, save_path, label in [
            ("did_start", "start_model", MODEL_START_PATH, "start"),
            ("played_60_plus", "min60_model", MODEL_60_PATH, "60min"),
        ]:
            y = df[target_col].astype(int)
            model = lgb.LGBMClassifier(
                n_estimators=300,
                learning_rate=0.05,
                max_depth=5,
                num_leaves=20,
                random_state=42,
                n_jobs=-1,
                verbose=-1,
            )
            try:
                scores = cross_val_score(
                    model, X, y,
                    cv=min(5, len(df) // 10),
                    scoring="roc_auc",
                )
                model.fit(X, y)
                setattr(self, model_attr, model)
                joblib.dump(model, save_path)
                metrics[f"{label}_auc"] = float(scores.mean())
                logger.info(f"Minutes '{label}' model trained: AUC={scores.mean():.3f}")
            except Exception as e:
                logger.error(f"Minutes '{label}' model training failed: {e}")
                metrics[f"{label}_error"] = str(e)

        return metrics

    def predict(self, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        """
        Returns (start_probs, min60_probs) arrays of shape (n_players,).
        Falls back to heuristic if models not trained.
        """
        if self.start_model is not None and self.min60_model is not None:
            X = self._prepare_features(df)
            start_probs = self.start_model.predict_proba(X)[:, 1]
            min60_probs = self.min60_model.predict_proba(X)[:, 1]

            # Override with FPL chance_of_playing if very low (injury/doubt)
            if "chance_of_playing" in df.columns:
                cop = df["chance_of_playing"].values
                start_probs = np.where(cop < 0.5, start_probs * cop, start_probs)
                min60_probs = np.where(cop < 0.5, min60_probs * cop, min60_probs)

            return start_probs, min60_probs

        return self._cold_start_predict(df)

    def predict_state_probabilities(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Approximate Markov-style minutes states from current lineup signals.
        The output probabilities sum to 1 for each player.
        """
        start_probs, min60_probs = self.predict(df)
        n = len(df)
        bench_prob = np.clip(1.0 - start_probs, 0.0, 1.0)
        injury_penalty = df.get("chance_of_playing", pd.Series(1.0, index=df.index)).fillna(1.0).values
        start_90 = np.clip(start_probs * min60_probs * injury_penalty, 0.0, 1.0)
        start_60 = np.clip(start_probs * (1.0 - min60_probs) * 0.7, 0.0, 1.0)
        sub_30 = np.clip(bench_prob * 0.45 * injury_penalty, 0.0, 1.0)
        sub_10 = np.clip(bench_prob * 0.2 * injury_penalty, 0.0, 1.0)
        benched = np.clip(bench_prob * 0.2, 0.0, 1.0)
        dnp = np.clip(1.0 - (start_90 + start_60 + sub_30 + sub_10 + benched), 0.0, 1.0)
        total = start_90 + start_60 + sub_30 + sub_10 + benched + dnp
        total = np.where(total == 0, 1.0, total)
        data = {
            "START_90": start_90 / total,
            "START_60": start_60 / total,
            "SUB_30": sub_30 / total,
            "SUB_10": sub_10 / total,
            "BENCHED": benched / total,
            "DNP": dnp / total,
        }
        return pd.DataFrame(data, index=df.index)

    def expected_minutes_from_states(self, state_probs: pd.DataFrame) -> np.ndarray:
        weights = {
            "START_90": 90.0,
            "START_60": 65.0,
            "SUB_30": 25.0,
            "SUB_10": 10.0,
            "BENCHED": 0.0,
            "DNP": 0.0,
        }
        expected = np.zeros(len(state_probs))
        for state, weight in weights.items():
            expected += state_probs.get(state, 0.0).values * weight
        return expected

    def _cold_start_predict(self, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        """Heuristic when models not trained."""
        n = len(df)
        start_probs = np.full(n, 0.7)
        min60_probs = np.full(n, 0.55)

        for i, (_, row) in enumerate(df.iterrows()):
            cop = float(row.get("chance_of_playing", 1.0) or 1.0)
            status = row.get("status", "a")
            price = float(row.get("price_millions", 5.0) or 5.0)
            rotation_risk = float(row.get("rotation_risk_score", 0) or 0)
            # `minutes` column added in processor.py; -1 = column not present (backwards compat)
            season_minutes = float(row.get("minutes", -1) if "minutes" in row.index else -1)

            if status == "i":
                start_probs[i] = 0.0
                min60_probs[i] = 0.0
            elif status == "d":
                start_probs[i] = cop * 0.5
                min60_probs[i] = cop * 0.35
            elif season_minutes == 0:
                # Available (status='a') but zero season minutes → frozen out.
                # Hard cap prevents recommending players who aren't in manager's plans.
                start_probs[i] = 0.08
                min60_probs[i] = 0.04
            else:
                # Higher price players are more likely to start
                price_factor = min(1.0, price / 12.0)
                base = 0.65 + price_factor * 0.2 - rotation_risk * 0.2
                start_probs[i] = max(0.0, min(1.0, base * cop))
                min60_probs[i] = max(0.0, min(1.0, (base - 0.1) * cop))

        return start_probs, min60_probs

    def compute_rotation_risk(self, df: pd.DataFrame) -> pd.Series:
        """
        Compute rotation risk score per player (0=no risk, 1=high risk).

        Combines:
          1. Team depth index (expensive bench depth → more rotation)
          2. Manager rotation tendency (inferred from historical starting XI changes)
          3. Recent fixture congestion (≥ 2 games in 7 days → higher rotation)
          4. Player price (cheaper players = less guaranteed starter)
        """
        if "team_id" not in df.columns or "price_millions" not in df.columns:
            return pd.Series(0.0, index=df.index)

        # Component 1: Team avg price (bench depth proxy — big clubs rotate)
        team_avg_price = df.groupby("team_id")["price_millions"].mean()
        price_risk = team_avg_price.apply(
            lambda x: min(0.7, max(0.0, (x - 5.5) / 10.0))
        )
        base_risk = df["team_id"].map(price_risk).fillna(0.0)

        # Component 2: Team depth index (if available)
        if "team_depth_index" in df.columns:
            depth_component = df["team_depth_index"].fillna(0.3) * 0.4
            base_risk = (base_risk + depth_component) / 2

        # Component 3: Fixture congestion
        if "matches_last_7_days" in df.columns:
            congestion = df["matches_last_7_days"].fillna(0).clip(0, 3) / 3.0 * 0.3
            base_risk = base_risk + congestion

        # Component 4: Low price player within a high-depth team
        if "price_millions" in df.columns:
            player_price = df["price_millions"].fillna(5.5)
            low_price_penalty = (player_price < 5.0).astype(float) * 0.15
            base_risk = base_risk + low_price_penalty

        return base_risk.clip(0.0, 1.0)

    def compute_team_depth_index(self, df: pd.DataFrame) -> pd.Series:
        """
        Team depth index per player: fraction of teammates at the same position
        who cost within £1m of this player (competition for a spot).
        Higher = more competition = higher rotation risk.
        """
        if "team_id" not in df.columns or "element_type" not in df.columns:
            return pd.Series(0.3, index=df.index)

        result = pd.Series(0.3, index=df.index)
        for idx, row in df.iterrows():
            same_pos_same_team = df[
                (df["team_id"] == row["team_id"])
                & (df["element_type"] == row.get("element_type", 3))
                & (df.index != idx)
            ]
            if len(same_pos_same_team) == 0:
                result[idx] = 0.0
                continue
            # Close competitors: within £1.5m
            price = float(row.get("price_millions", 5.0) or 5.0)
            close_competitors = same_pos_same_team[
                abs(same_pos_same_team["price_millions"] - price) <= 1.5
            ]
            result[idx] = min(1.0, len(close_competitors) / 4.0)

        return result
