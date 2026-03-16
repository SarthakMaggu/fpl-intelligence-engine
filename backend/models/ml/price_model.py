"""
Price Change Predictor — 3-class LightGBM classifier.

Predicts: -1 (price drop), 0 (stable), +1 (price rise).

FPL price algorithm approximation:
- Price rises when net transfers in exceed ~1% of total ownership
- The exact threshold is undocumented but empirically ~1% net positive ownership

Returns class probabilities for display + direction prediction.
"""
import joblib
import numpy as np
import pandas as pd
from pathlib import Path
from loguru import logger

MODEL_PATH = Path("models/ml/artifacts/price_model.pkl")

PRICE_FEATURES = [
    "transfers_in_event",
    "transfers_out_event",
    "net_transfers_event",         # in - out
    "selected_by_percent",
    "form",
    "price_millions",
    "fdr_next",                    # good fixtures → more transfers in
    "is_gk", "is_def", "is_mid", "is_fwd",
]

MIN_TRAIN_ROWS = 30


class PriceModel:
    def __init__(self):
        self.model = None
        self._load()

    def _load(self) -> None:
        if MODEL_PATH.exists():
            try:
                self.model = joblib.load(MODEL_PATH)
                logger.info("Price model loaded")
            except Exception as e:
                logger.warning(f"Failed to load price model: {e}")

    def train(self, df: pd.DataFrame) -> dict:
        """
        Train on historical GW data.
        df must contain PRICE_FEATURES + 'price_direction' (-1/0/1).
        """
        try:
            import lightgbm as lgb
            from sklearn.model_selection import cross_val_score
        except ImportError:
            return {"error": "lightgbm not installed"}

        df = df.dropna(subset=["price_direction"])
        if len(df) < MIN_TRAIN_ROWS:
            return {"error": f"Need {MIN_TRAIN_ROWS} rows, got {len(df)}"}

        # Add derived features
        df = df.copy()
        if "transfers_in_event" in df and "transfers_out_event" in df:
            df["net_transfers_event"] = df["transfers_in_event"] - df["transfers_out_event"]

        available = [f for f in PRICE_FEATURES if f in df.columns]
        X = df[available].fillna(0)
        y = df["price_direction"].astype(int) + 1  # shift to 0/1/2 for LightGBM

        try:
            import lightgbm as lgb
            self.model = lgb.LGBMClassifier(
                n_estimators=300,
                learning_rate=0.05,
                max_depth=4,
                num_leaves=15,
                random_state=42,
                n_jobs=-1,
                verbose=-1,
                num_class=3,
                objective="multiclass",
            )
            scores = cross_val_score(self.model, X, y, cv=min(3, len(df) // 10), scoring="accuracy")
            self.model.fit(X, y)
            joblib.dump(self.model, MODEL_PATH)
            logger.info(f"Price model trained: accuracy={scores.mean():.3f}")
            return {"accuracy": float(scores.mean()), "n_samples": len(df)}
        except Exception as e:
            logger.error(f"Price model training failed: {e}")
            return {"error": str(e)}

    def predict(self, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        """
        Returns:
          - direction: array of -1/0/1 (predicted price change direction)
          - confidence: array of 0.0-1.0 (confidence of prediction)
        """
        # Add derived feature
        df = df.copy()
        if "transfers_in_event" in df.columns and "transfers_out_event" in df.columns:
            df["net_transfers_event"] = df["transfers_in_event"] - df["transfers_out_event"]

        if self.model is not None:
            available = [f for f in PRICE_FEATURES if f in df.columns]
            X = df[available].fillna(0)
            proba = self.model.predict_proba(X)           # shape (n, 3): [drop, stable, rise]
            predicted_class = np.argmax(proba, axis=1)   # 0/1/2
            direction = predicted_class - 1              # back to -1/0/1
            confidence = np.max(proba, axis=1)
            return direction, confidence

        # Fallback: heuristic based on net transfers
        return self._heuristic_predict(df)

    def _heuristic_predict(self, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        """Simple threshold-based prediction when model not trained."""
        n = len(df)
        direction = np.zeros(n, dtype=int)
        confidence = np.full(n, 0.5)

        if "net_transfers_event" in df.columns:
            net = df["net_transfers_event"].values
            direction = np.where(net > 50000, 1, np.where(net < -50000, -1, 0))
            confidence = np.where(np.abs(net) > 100000, 0.7, 0.5)

        return direction, confidence
