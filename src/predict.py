"""Prediction interface — turns a list of reported symptoms into a ranked shortlist."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from .knowledge_base import RED_FLAG_SYMPTOMS, SYMPTOMS, URGENT_CONDITIONS
from .model import load_model


@dataclass(frozen=True)
class Prediction:
    """One candidate condition and how strongly the evidence points at it."""

    disease: str
    probability: float

    @property
    def confidence(self) -> str:
        if self.probability >= 0.70:
            return "high"
        if self.probability >= 0.40:
            return "moderate"
        return "low"


@dataclass(frozen=True)
class Assessment:
    """The full response: ranked candidates plus a triage recommendation."""

    predictions: list[Prediction]
    urgent: bool
    recognised_symptoms: list[str]
    unknown_symptoms: list[str]
    advice: str

    @property
    def top(self) -> Prediction | None:
        return self.predictions[0] if self.predictions else None


def encode_symptoms(symptoms: Iterable[str]) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Convert reported symptom names into the model's binary feature vector.

    Returns a single-row DataFrame with named columns rather than a bare array, so
    scikit-learn can verify the feature order it was fitted on. A bare array would
    silently accept a wrong ordering and predict confidently against the wrong columns.

    Unknown names are reported back rather than silently dropped — a typo that
    quietly becomes "no symptom" would skew the result with no visible cause.
    """
    known = {s.strip().lower().replace(" ", "_") for s in symptoms if s and s.strip()}
    index = {symptom: i for i, symptom in enumerate(SYMPTOMS)}

    row = np.zeros((1, len(SYMPTOMS)), dtype=np.int8)
    recognised, unknown = [], []

    for symptom in sorted(known):
        if symptom in index:
            row[0, index[symptom]] = 1
            recognised.append(symptom)
        else:
            unknown.append(symptom)

    return pd.DataFrame(row, columns=list(SYMPTOMS)), recognised, unknown


class DiseasePredictor:
    """Loads a trained model once and serves ranked predictions from it."""

    def __init__(self, model_path: str | Path | None = None, model=None) -> None:
        if model is not None:
            self.model = model
        else:
            self.model, _ = load_model(model_path) if model_path else load_model()

    def predict(self, symptoms: Sequence[str], top_k: int = 3) -> Assessment:
        """Rank the most probable conditions for the reported symptoms."""
        vector, recognised, unknown = encode_symptoms(symptoms)

        if not recognised:
            return Assessment(
                predictions=[],
                urgent=False,
                recognised_symptoms=[],
                unknown_symptoms=unknown,
                advice="No recognised symptoms were provided, so no assessment can be made.",
            )

        probabilities = self.model.predict_proba(vector)[0]
        ranked = np.argsort(probabilities)[::-1][:top_k]

        predictions = [
            Prediction(disease=str(self.model.classes_[i]), probability=float(probabilities[i]))
            for i in ranked
        ]

        urgent = self._is_urgent(recognised, predictions)
        return Assessment(
            predictions=predictions,
            urgent=urgent,
            recognised_symptoms=recognised,
            unknown_symptoms=unknown,
            advice=self._advice(urgent, predictions),
        )

    @staticmethod
    def _is_urgent(recognised: list[str], predictions: list[Prediction]) -> bool:
        """Escalate on red-flag symptoms regardless of what the model ranked first.

        This check deliberately sits outside the model. A classifier trained on a
        finite label set can be confidently wrong, and a missed red flag costs far
        more than an unnecessary referral.
        """
        if RED_FLAG_SYMPTOMS.intersection(recognised):
            return True
        return any(
            p.disease in URGENT_CONDITIONS and p.probability >= 0.40 for p in predictions
        )

    @staticmethod
    def _advice(urgent: bool, predictions: list[Prediction]) -> str:
        if urgent:
            return (
                "⚠️ Red-flag symptoms or a serious candidate condition were identified. "
                "Seek medical attention today."
            )
        if predictions and predictions[0].probability < 0.40:
            return (
                "The reported symptoms are not strongly specific to one condition. "
                "Monitor them and consult a clinician if they persist or worsen."
            )
        return (
            "This is a preliminary screening result only. Confirm with a qualified "
            "clinician before acting on it."
        )
