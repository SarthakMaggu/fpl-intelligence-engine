"""
Expected Points (xPts) Model — LightGBM gradient boosting regressor.

Predicts expected fantasy points for each player in the next gameweek.

Cold start (GW1): falls back to FPL's own expected_goals/expected_assists fields
and a form-based heuristic until enough historical data exists to train.
"""
import joblib
import numpy as np
import pandas as pd
from pathlib import Path
from loguru import logger

MODEL_PATH = Path("models/ml/artifacts/xpts_model.pkl")
MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)

XPTS_FEATURES = [
    # ── Core FPL signals ─────────────────────────────────────────────────────
    "xg_per_90",
    "xa_per_90",
    "npxg_per_90",
    "ict_index",
    "predicted_start_prob",
    "predicted_60min_prob",
    "form",
    "points_per_game",
    "bps_per_90",
    "fdr_next",
    "is_home_next",
    "blank_gw",
    "double_gw",
    "team_strength_attack",
    "opponent_strength_defence",
    "selected_by_percent",
    "transfers_in_event_delta",
    "team_win_probability",
    "is_set_piece_taker",
    "is_gk",
    "is_def",
    "is_mid",
    "is_fwd",
    "price_millions",
    # ── News & sentiment signals (Phase 2) ───────────────────────────────────
    "news_sentiment",       # float [-1, 1] — positive/negative news tone
    "news_article_count",   # int — volume of news (more = more volatile/uncertain)
    # ── Rolling 5-GW performance (Phase 2) ───────────────────────────────────
    "xg_last_5_gws",       # sum of expected goals over last 5 GWs
    "xa_last_5_gws",       # sum of expected assists over last 5 GWs
    "goals_last_5_gws",    # actual goals scored
    "cs_last_5_gws",       # clean sheets (GK/DEF)
    "pts_last_5_gws",      # actual total points
    "minutes_trend",        # minutes_last_5 / minutes_prev_5 (improving = >1, declining = <1)
]

# Minimum rows required for meaningful training
MIN_TRAIN_ROWS = 50


class XPtsModel:
    def __init__(self):
        self.model = None
        self._load()

    def _load(self) -> None:
        if MODEL_PATH.exists():
            try:
                self.model = joblib.load(MODEL_PATH)
                logger.info("xPts model loaded from disk")
            except Exception as e:
                logger.warning(f"Failed to load xPts model: {e}")
                self.model = None

    def train(self, df: pd.DataFrame) -> dict:
        """
        Train on historical GW data.
        df must contain XPTS_FEATURES + 'actual_points' column.
        Returns training metrics dict.
        """
        try:
            import lightgbm as lgb
            from sklearn.model_selection import cross_val_score
        except ImportError:
            logger.error("lightgbm/scikit-learn not installed — cannot train xPts model")
            return {"error": "lightgbm not installed"}

        df = df.dropna(subset=["actual_points"])
        if len(df) < MIN_TRAIN_ROWS:
            logger.warning(f"Insufficient training data: {len(df)} rows (need {MIN_TRAIN_ROWS})")
            return {"error": f"Need at least {MIN_TRAIN_ROWS} rows, got {len(df)}"}

        available_features = [f for f in XPTS_FEATURES if f in df.columns]
        X = df[available_features].fillna(0)
        y = df["actual_points"].clip(lower=0)

        self.model = lgb.LGBMRegressor(
            n_estimators=500,
            learning_rate=0.05,
            max_depth=6,
            num_leaves=31,
            min_child_samples=20,
            colsample_bytree=0.8,
            subsample=0.8,
            reg_alpha=0.1,
            reg_lambda=0.1,
            random_state=42,
            n_jobs=-1,
            verbose=-1,
        )

        try:
            scores = cross_val_score(
                self.model, X, y,
                cv=min(5, len(df) // 10),
                scoring="neg_root_mean_squared_error",
            )
            self.model.fit(X, y)
            joblib.dump(self.model, MODEL_PATH)

            feature_importance = dict(zip(
                available_features,
                self.model.feature_importances_.tolist(),
            ))

            metrics = {
                "cv_rmse": float(-scores.mean()),
                "cv_rmse_std": float(scores.std()),
                "n_samples": len(df),
                "n_features": len(available_features),
                "feature_importance": feature_importance,
            }
            logger.info(f"xPts model trained: RMSE={metrics['cv_rmse']:.3f} (n={len(df)})")
            return metrics

        except Exception as e:
            logger.error(f"xPts model training failed: {e}")
            return {"error": str(e)}

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        """
        Predict expected points for each player.

        Cold start fallback if model not trained:
        - For GW1: use FPL's own expected_goals/expected_assists to estimate
        - Otherwise: form-based heuristic (form × 0.8)
        """
        if self.model is not None:
            available = [f for f in XPTS_FEATURES if f in df.columns]
            X = df[available].fillna(0)
            predictions = self.model.predict(X)
            # Zero out blank GW players
            if "blank_gw" in df.columns:
                predictions = np.where(df["blank_gw"].values == 1, 0.0, predictions)
            return predictions.clip(min=0)

        # Cold start: xG-based estimate
        logger.info("xPts model not trained — using cold start heuristic")
        return self._cold_start_predict(df)

    def _cold_start_predict(self, df: pd.DataFrame) -> np.ndarray:
        """
        Vectorized heuristic using all available signals:
        xG/xA/npxG, ICT, form, PPG, FDR, home/away, DGW, start probability.

        This replaces the old iterrows-based approach (50–100× faster) and
        produces more accurate estimates by incorporating all FPL feature signals.
        """
        n = len(df)
        if n == 0:
            return np.zeros(0)

        def col(name: str, default: float) -> np.ndarray:
            if name in df.columns:
                return df[name].fillna(default).values.astype(float)
            return np.full(n, default, dtype=float)

        # ── Raw signals ──────────────────────────────────────────────────────
        pos      = col("element_type", 3).astype(int)
        form     = col("form", 0.0)
        ppg      = col("points_per_game", 0.0)
        xg       = col("xg_per_90", 0.0)
        xa       = col("xa_per_90", 0.0)
        npxg     = col("npxg_per_90", 0.0)
        ict      = col("ict_index", 0.0)
        fdr      = np.clip(col("fdr_next", 3).astype(int), 1, 5)
        is_home  = col("is_home_next", 0.0).astype(bool)
        blank    = col("blank_gw", 0.0).astype(bool)
        double   = col("double_gw", 0.0).astype(bool)
        s_prob   = np.clip(col("predicted_start_prob", 0.75), 0.0, 1.0)

        # ── Fixture difficulty factor (FDR 1 = easiest, 5 = hardest) ────────
        fdr_factor = np.select(
            [fdr == 1, fdr == 2, fdr == 4, fdr == 5],
            [1.35,     1.18,     0.80,     0.60],
            default=1.00,
        )

        # ── Home/away bonus ──────────────────────────────────────────────────
        fixture_mult = np.where(is_home, 1.10, 0.93)

        # ── Position-specific scoring weights ────────────────────────────────
        goal_pts = np.select([pos == 1, pos == 2, pos == 3], [6, 6, 5], default=4)
        cs_base  = np.select([pos == 1, pos == 2, pos == 3], [4.0, 4.0, 1.0], default=0.0)
        # Clean sheet probability by fixture difficulty
        cs_prob  = np.select(
            [fdr <= 2, fdr == 3, fdr == 4],
            [0.42,     0.28,     0.15],
            default=0.07,
        )

        # ── Best xG signal: prefer npxg (excludes pens) if available ────────
        xg_signal = np.where(npxg > 0, npxg, xg)

        # ── Base score ───────────────────────────────────────────────────────
        # Appearance (2) + attacking (xG/xA) + defensive (CS) + performance (form/PPG) + ICT
        base = (
            2.0                        # Appearance points for playing ≥1 min
            + xg_signal * goal_pts     # Goal-scoring contribution
            + xa * 3.0                 # Assist contribution
            + cs_base * cs_prob        # Position-weighted clean sheet expectation
            + 0.25 * form              # Recent form (last 30-day rolling average)
            + 0.18 * ppg               # Season-level anchor (points per game)
            + 0.015 * ict              # FPL's creativity/threat composite (small weight)
        )

        # ── Apply fixture modifier then home advantage ───────────────────────
        estimate = base * fdr_factor * fixture_mult

        # ── Double GW: player plays ~twice → ~1.85× single-GW score ─────────
        estimate = np.where(double, estimate * 1.85, estimate)

        # ── Blank GW: no fixture → 0 points ──────────────────────────────────
        estimate = np.where(blank, 0.0, estimate)

        # ── Multiply by start probability ─────────────────────────────────────
        estimate = estimate * s_prob

        return np.maximum(0.0, estimate)

    def is_trained(self) -> bool:
        return self.model is not None

    def apply_calibration(
        self,
        predictions: np.ndarray,
        df: pd.DataFrame,
        calibration_map: dict[tuple, float],
    ) -> np.ndarray:
        """
        Apply post-GW calibration corrections to raw xPts predictions.

        calibration_map: {(position, price_band): mean_residual} where
            position    = player element_type (1=GK, 2=DEF, 3=MID, 4=FWD)
            price_band  = int(price_millions) floor
            mean_residual = average (actual - predicted) for this group

        Corrections are clipped to ±1.5 pts to avoid overcorrection on small samples.
        """
        if not calibration_map or len(predictions) == 0:
            return predictions

        corrected = predictions.copy().astype(float)

        for i, (_, row) in enumerate(df.iterrows()):
            pos = int(row.get("element_type", 3))
            price_band = int(float(row.get("price_millions", 5.0)))
            key = (pos, price_band)
            residual = calibration_map.get(key, 0.0)
            # Clip correction: don't overcorrect more than ±1.5 pts
            correction = max(-1.5, min(1.5, residual))
            corrected[i] = max(0.0, predictions[i] + correction)

        return corrected
