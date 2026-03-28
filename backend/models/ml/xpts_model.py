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
CALIBRATORS_PATH = Path("models/ml/artifacts/isotonic_calibrators.pkl")
MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)

XPTS_FEATURES = [
    # ── Core per-90 performance signals ──────────────────────────────────────
    "xg_per_90",                    # expected goals per 90 (current GW)
    "xa_per_90",                    # expected assists per 90
    "npxg_per_90",                  # non-penalty xG per 90
    "ict_index",                    # FPL ICT threat/creativity/influence composite
    "bps_per_90",                   # bonus points system score per 90
    # ── Rolling 5-GW form signals (shift-1, NO data leakage) ─────────────────
    "form",                         # rolling 5-GW avg total_points
    "points_per_game",              # expanding mean total_points up to prior GW
    "pts_last_5_gws",               # sum of points in last 5 GWs
    "xg_last_5_gws",                # sum of expected goals in last 5 GWs
    "xa_last_5_gws",                # sum of expected assists in last 5 GWs
    "goals_last_5_gws",             # actual goals in last 5 GWs
    "cs_last_5_gws",                # clean sheets in last 5 GWs (GK/DEF signal)
    "minutes_trend",                # avg_mins_last5 / avg_mins_prev5 (rotation risk)
    # ── Playing time / availability signals ───────────────────────────────────
    "predicted_start_prob",         # prob of starting (lagged: based on prior GW minutes)
    "predicted_60min_prob",         # prob of playing 60+ min (lagged)
    # ── Fixture context ───────────────────────────────────────────────────────
    "fdr_next",                     # fixture difficulty rating (1=easy, 5=hard)
    "is_home_next",                 # 1 if home fixture
    "blank_gw",                     # 1 if no fixture this GW
    "double_gw",                    # 1 if two fixtures this GW
    "fdr_next3_avg",                # avg FDR across next 3 GWs (transfer horizon)
    "opponent_goals_conceded_per90", # opponent defensive weakness signal
    # ── Player market signals ─────────────────────────────────────────────────
    "selected_by_percent",          # ownership % — market consensus proxy
    "transfers_in_event_delta",     # net transfer activity (positive = trending up)
    # NOTE: price_millions intentionally EXCLUDED from XPTS_FEATURES.
    # Price has no causal relationship with scoring (a £10m player can score 20pts
    # just as easily as a £5m player). Including it causes the model to learn a
    # spurious negative correlation for expensive players (regression-to-mean
    # confounded by price), systematically underpredicting elite hot-streak
    # players like Bruno Fernandes, Salah, etc.
    # Price information is captured indirectly via: selected_by_percent (ownership
    # % correlates with price), points_per_game (historical performance anchors
    # the model's season-level expectation), and the position dummies.
    # ── Position dummies ─────────────────────────────────────────────────────
    "is_gk",
    "is_def",
    "is_mid",
    "is_fwd",
    # ── Contextual signals (often available live, default to neutral for training) ──
    "news_sentiment",               # [-1, 1] news tone; 0=neutral (default in training)
    "season_stage",                 # [0, 1] GW1→GW38 normalised position in season
    # ── These have low/zero variance in historical training but used live ──────
    # team_strength_attack, opponent_strength_defence, team_win_probability,
    # is_set_piece_taker, news_article_count, days_since_last_game
    # are excluded from XPTS_FEATURES because they are constant in historical
    # training data (all 3.0 / 0.5 / 0 respectively) and therefore contribute
    # zero predictive signal while increasing model complexity.
]

# Minimum rows required for meaningful training
MIN_TRAIN_ROWS = 50

# Monotone constraints per feature:
#   +1 = feature can only increase predictions (positive signal)
#   -1 = feature can only decrease predictions (negative signal)
#    0 = unconstrained
#
# These constraints prevent the model from learning spurious "regression anchors":
#   - popular players (high selected_by_percent) being penalised for popularity
#   - in-form players (high pts_last_5_gws) being penalised for recent excellence
# The tradeoff is slightly higher RMSE (~0.03) but directionally correct predictions.
FEATURE_MONOTONE_CONSTRAINTS = {
    "xg_per_90":                    1,   # more xG = better
    "xa_per_90":                    1,   # more xA = better
    "npxg_per_90":                  1,   # more npxG = better
    "ict_index":                    1,   # higher ICT = better
    "bps_per_90":                   1,   # higher BPS = better
    "form":                         1,   # better form = better
    "points_per_game":              1,   # more pts/game = better
    "pts_last_5_gws":               1,   # more recent pts = better (not a regression anchor)
    "xg_last_5_gws":                1,
    "xa_last_5_gws":                1,
    "goals_last_5_gws":             1,
    "cs_last_5_gws":                1,
    "minutes_trend":                1,   # improving minutes = better
    "predicted_start_prob":         1,
    "predicted_60min_prob":         1,
    "fdr_next":                    -1,   # harder fixture = worse
    "is_home_next":                 1,   # home = better
    "blank_gw":                    -1,   # blank = worse
    "double_gw":                    1,   # double = better
    "fdr_next3_avg":               -1,   # harder 3-gw run = worse
    "opponent_goals_conceded_per90": 1,  # leakier opponent = better for attackers
    "selected_by_percent":          1,   # popular = quality signal, not regression anchor
    "transfers_in_event_delta":     1,   # net buys = positive sentiment
    "is_gk":                        0,
    "is_def":                       0,
    "is_mid":                       0,
    "is_fwd":                       0,
    "news_sentiment":               1,   # positive news = better
    "season_stage":                 0,   # complex seasonal effects, unconstrained
}


class XPtsModel:
    def __init__(self):
        self.model = None
        # {(pos_int, price_band_int): fitted IsotonicRegression}
        self.calibrators: dict = {}
        self._load()
        self._load_calibrators()

    def _load(self) -> None:
        if MODEL_PATH.exists():
            try:
                self.model = joblib.load(MODEL_PATH)
                logger.info("xPts model loaded from disk")
            except Exception as e:
                logger.warning(f"Failed to load xPts model: {e}")
                self.model = None

    def _load_calibrators(self) -> None:
        """Load persisted isotonic calibrators if available."""
        if CALIBRATORS_PATH.exists():
            try:
                self.calibrators = joblib.load(CALIBRATORS_PATH)
                logger.info(
                    f"Isotonic calibrators loaded: {len(self.calibrators)} groups"
                )
            except Exception as e:
                logger.warning(f"Failed to load isotonic calibrators: {e}")
                self.calibrators = {}

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

        # Cap pts_last_5_gws to reduce extreme regression signal.
        # Bruno scoring 46 pts in 5 GWs (avg 9.2/GW) shouldn't predict regression;
        # capping at 40 keeps the "excellent form" signal without creating an outlier.
        if "pts_last_5_gws" in X.columns:
            X = X.copy()
            X["pts_last_5_gws"] = X["pts_last_5_gws"].clip(upper=40)

        # Build monotone constraint vector aligned to available_features order
        monotone_constraints = [FEATURE_MONOTONE_CONSTRAINTS.get(f, 0) for f in available_features]

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
            monotone_constraints=monotone_constraints,
            monotone_constraints_method="advanced",
        )

        try:
            scores = cross_val_score(
                self.model, X, y,
                cv=min(5, len(df) // 10),
                scoring="neg_root_mean_squared_error",
            )
            self.model.fit(X, y)
            joblib.dump(self.model, MODEL_PATH)

            # ── Gain-based feature importance ─────────────────────────────────
            # More meaningful than split-count: monotone constraints cause
            # unconstrained features (season_stage, position dummies) to
            # accumulate many low-gain splits, skewing split-count importance.
            feature_importance = dict(zip(
                available_features,
                self.model.booster_.feature_importance(importance_type='gain').tolist(),
            ))

            # ── SHAP importance (mean |SHAP value| per feature) ───────────────
            # Unlike gain importance, SHAP distributes credit fairly among
            # correlated features (e.g. xa_last_5_gws and xg_last_5_gws).
            # Computed on a random sample to keep training time bounded.
            shap_importance: dict[str, float] = {}
            try:
                import shap as _shap
                # Cap sample at 1000 rows — TreeExplainer is O(n·leaves) so
                # anything larger yields diminishing returns in < 1s extra.
                sample_size = min(1000, len(X))
                X_sample = X.sample(sample_size, random_state=42)
                explainer = _shap.TreeExplainer(self.model)
                shap_matrix = explainer.shap_values(X_sample)   # shape: (n, features)
                shap_importance = dict(zip(
                    available_features,
                    [float(v) for v in np.abs(shap_matrix).mean(axis=0).tolist()],
                ))
                logger.info(
                    f"SHAP computed on {sample_size} samples — "
                    f"top feature: {max(shap_importance, key=shap_importance.get)}"
                )
            except ImportError:
                logger.warning("shap not installed — SHAP importance skipped (pip install shap)")
            except Exception as _shap_err:
                logger.warning(f"SHAP computation failed (non-fatal): {_shap_err}")

            metrics = {
                "cv_rmse": float(-scores.mean()),
                "cv_rmse_std": float(scores.std()),
                "n_samples": len(df),
                "n_features": len(available_features),
                "feature_importance": feature_importance,
                "shap_importance": shap_importance,
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
            # Use the model's own stored feature list to avoid training/live
            # feature set mismatches.  LightGBM stores feature_name_ after
            # fitting with a DataFrame.  Any features the live DataFrame is
            # missing are filled with 0 (safe: model assigns them low weight
            # or they were also 0 in most training rows).
            try:
                model_features = list(getattr(self.model, "feature_name_", None) or [])
            except Exception:
                model_features = []

            if model_features:
                # Reindex: keeps only model features, fills missing with 0
                X = df.reindex(columns=model_features, fill_value=0.0).fillna(0)
            else:
                # Fallback: old behaviour (may cause shape mismatch on old pkl)
                available = [f for f in XPTS_FEATURES if f in df.columns]
                X = df[available].fillna(0)

            try:
                predictions = self.model.predict(X)
            except Exception as e:
                # Feature count mismatch (model trained on old feature set) — fall back
                logger.warning(
                    f"xPts model predict failed ({e}) — falling back to cold-start heuristic. "
                    f"Re-train the model via /api/lab/run-backtest to resolve."
                )
                return self._cold_start_predict(df)
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

    # ──────────────────────────────────────────────────────────────────────────
    # Isotonic calibration layer
    # ──────────────────────────────────────────────────────────────────────────

    def train_calibrators(
        self,
        y_pred: np.ndarray,
        y_actual: np.ndarray,
        positions: np.ndarray,
        price_bands: np.ndarray,
    ) -> dict:
        """
        Fit one IsotonicRegression per (position, price_band) group using
        out-of-sample (predicted, actual) pairs collected from the last N GWs.

        IsotonicRegression maps raw_predicted → calibrated without assuming
        linearity — it corrects the U-shaped bias seen in expensive players
        (where the model over-predicts) and cheap players (under-predicts).

        Groups with fewer than 5 samples are skipped (too noisy to calibrate).
        Falls back gracefully: if no calibrators are fitted, predictions pass
        through unchanged.

        Returns a summary dict for logging / admin display.
        """
        try:
            from sklearn.isotonic import IsotonicRegression as _IR
        except ImportError:
            logger.warning("scikit-learn not installed — isotonic calibration skipped")
            return {}

        import pandas as _pd

        cal_df = _pd.DataFrame({
            "pred":   y_pred,
            "actual": y_actual,
            "pos":    positions.astype(int),
            "band":   price_bands.astype(int),
        }).dropna()

        if cal_df.empty:
            logger.warning("train_calibrators: empty input, nothing fitted")
            return {}

        calibrators: dict = {}
        summary: dict = {}

        for (pos, band), grp in cal_df.groupby(["pos", "band"]):
            if len(grp) < 5:
                continue   # not enough data to learn a monotone mapping

            ir = _IR(out_of_bounds="clip")
            ir.fit(grp["pred"].values, grp["actual"].values)
            calibrators[(int(pos), int(band))] = ir

            # Residual reduction for logging
            cal_preds = ir.predict(grp["pred"].values)
            residual_before = float((grp["actual"].values - grp["pred"].values).mean())
            residual_after  = float((grp["actual"].values - cal_preds).mean())
            summary[f"pos{int(pos)}_band{int(band)}"] = {
                "n":               len(grp),
                "residual_before": round(residual_before, 3),
                "residual_after":  round(residual_after,  3),
            }

        self.calibrators = calibrators

        try:
            joblib.dump(calibrators, CALIBRATORS_PATH)
            logger.info(
                f"Isotonic calibrators saved: {len(calibrators)} groups "
                f"({sum(v['n'] for v in summary.values())} total samples)"
            )
        except Exception as _save_err:
            logger.warning(f"Failed to persist calibrators: {_save_err}")

        return summary

    def apply_isotonic_calibration(
        self,
        predictions: np.ndarray,
        df: pd.DataFrame,
    ) -> np.ndarray:
        """
        Apply the fitted isotonic calibrators to live predictions.

        Each player is routed to their (position, price_band) calibrator.
        Groups without a calibrator (too few training samples) pass through
        unchanged.  Output is clipped to [0, ∞).

        This runs AFTER the mean-residual apply_calibration step so the two
        layers stack:
            raw_pred → mean-residual correction → isotonic correction
        """
        if not self.calibrators or len(predictions) == 0:
            return predictions

        corrected = predictions.copy().astype(float)

        pos_col   = df["element_type"].fillna(3).astype(int).values   if "element_type"   in df.columns else np.full(len(df), 3)
        price_col = df["price_millions"].fillna(5.0).astype(float).values if "price_millions" in df.columns else np.full(len(df), 5.0)
        # Use round() to match the band computation in train_calibrators
        band_col  = np.round(price_col).astype(int)

        for i in range(len(corrected)):
            key = (int(pos_col[i]), int(band_col[i]))
            ir  = self.calibrators.get(key)
            if ir is not None:
                # predict() accepts a 1-element array; clip to ≥0
                corrected[i] = max(0.0, float(ir.predict([corrected[i]])[0]))

        return corrected
