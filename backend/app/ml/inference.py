"""
ML Inference Module (application tier).

Loads the files produced by ml/train_model.py ONCE at server start-up and uses
them for prediction only - no training happens in the web application.

Classes match the service classes in the class diagram:
    Preprocessor, RiskPredictor, SHAPExplainer, ReferralRuleEngine
"""
import json
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import shap
from xgboost import XGBClassifier


class Preprocessor:
    """Applies the imputer + scaler fitted on the training set."""

    def __init__(self, feature_order: list[str]):
        self._feature_order = feature_order
        self._pipeline = None

    def load(self, path: Path) -> None:
        self._pipeline = joblib.load(path)

    def get_feature_order(self) -> list[str]:
        return list(self._feature_order)

    def transform(self, features: dict) -> np.ndarray:
        """dict of raw answers -> 1 x 12 model-ready vector. None (declined) -> NaN -> imputed."""
        row = [np.nan if features.get(f) is None else float(features[f]) for f in self._feature_order]
        return self._pipeline.transform(pd.DataFrame([row], columns=self._feature_order, dtype=float))


class RiskPredictor:
    """Wraps the trained XGBoost model."""

    def __init__(self, model_path: Path, model_version: str):
        self._model_path = model_path
        self._model_version = model_version
        self._model = XGBClassifier()

    def load(self) -> None:
        self._model.load_model(self._model_path)

    def predict_probability(self, vector: np.ndarray) -> float:
        return float(self._model.predict_proba(vector)[0, 1])

    def get_model_version(self) -> str:
        return self._model_version

    def get_model_path(self) -> str:
        return str(self._model_path)

    @property
    def model(self) -> XGBClassifier:
        return self._model


@dataclass
class Factor:
    feature_name: str
    feature_value: str
    shap_value: float
    rank: int
    plain_language_text: str


class SHAPExplainer:
    """Explains ONE prediction: which answers pushed this woman's risk up or down."""

    def __init__(self, model: XGBClassifier, labels: dict[str, str], feature_order: list[str], top_k: int = 3):
        self._explainer = shap.TreeExplainer(model)
        self._labels = labels
        self._feature_order = feature_order
        self._top_k = top_k

    def get_top_k(self) -> int:
        return self._top_k

    def set_top_k(self, k: int) -> None:
        self._top_k = k

    @staticmethod
    def _display(value) -> str:
        if value is None:
            return "Not answered"
        if isinstance(value, bool):
            return "Yes" if value else "No"
        value = float(value)
        return str(int(value)) if value.is_integer() else f"{value:.1f}"

    def to_plain_language(self, name: str, display_value: str, shap_value: float) -> str:
        direction = "increased" if shap_value > 0 else "lowered"
        return f"{self._labels.get(name, name)} ({display_value}): {direction} the risk estimate"

    def explain(self, vector: np.ndarray, raw_features: dict) -> list[Factor]:
        values = np.asarray(self._explainer.shap_values(vector))[0]
        # Explain using answers the client actually gave; a declined question (filled in by
        # imputation) is not shown as a "reason", since that would confuse the CHW.
        answered = [i for i, f in enumerate(self._feature_order) if raw_features.get(f) is not None]
        candidates = answered or list(range(len(self._feature_order)))
        order = sorted(candidates, key=lambda i: -abs(values[i]))[: self._top_k]
        factors = []
        for rank, idx in enumerate(order, start=1):
            name = self._feature_order[idx]
            shown = self._display(raw_features.get(name))
            sv = float(values[idx])
            factors.append(Factor(name, shown, round(sv, 4), rank, self.to_plain_language(name, shown, sv)))
        return factors


class ReferralRuleEngine:
    """Business rule: probability -> LOW / MODERATE / HIGH -> referral message."""

    def __init__(self, low_threshold: float, high_threshold: float, messages: dict[str, str]):
        self.set_thresholds(low_threshold, high_threshold)
        self._messages = dict(messages)

    def classify(self, probability: float) -> str:
        if probability >= self._high:
            return "HIGH"
        if probability >= self._low:
            return "MODERATE"
        return "LOW"

    def get_referral(self, level: str) -> str:
        return self._messages[level]

    def get_low_threshold(self) -> float:
        return self._low

    def get_high_threshold(self) -> float:
        return self._high

    def set_thresholds(self, low: float, high: float) -> None:
        if not 0 <= low < high <= 1:
            raise ValueError("Thresholds must satisfy 0 <= low < high <= 1")
        self._low, self._high = low, high

    def set_message(self, level: str, text: str) -> None:
        self._messages[level] = text


class MLModule:
    """Holds the four components; created once when the server starts."""

    def __init__(self, model_dir: Path):
        config_file = model_dir / "config.json"
        if not config_file.exists():
            raise FileNotFoundError(
                f"{config_file} not found. Train the model first: python ml/train_model.py")
        self.config = json.loads(config_file.read_text())
        features = self.config["features"]

        self.preprocessor = Preprocessor(features)
        self.preprocessor.load(model_dir / "preprocessor.pkl")

        self.predictor = RiskPredictor(model_dir / "model.json", self.config["model_version"])
        self.predictor.load()

        self.explainer = SHAPExplainer(self.predictor.model, self.config["feature_labels"], features,
                                       self.config.get("top_k_factors", 3))
        self.rules = ReferralRuleEngine(self.config["thresholds"]["t1"], self.config["thresholds"]["t2"],
                                        self.config["referral_messages"])

    @property
    def features(self) -> list[str]:
        return self.config["features"]
