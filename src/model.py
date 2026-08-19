"""Training, evaluation and persistence for the disease classifier."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, top_k_accuracy_score
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.naive_bayes import BernoulliNB

from .dataset import split_features_labels
from .knowledge_base import SYMPTOMS

MODEL_PATH = Path("artifacts/disease_model.joblib")


def build_candidates(random_state: int = 42) -> dict[str, Any]:
    """The models worth trying on binary symptom vectors.

    ``BernoulliNB`` is included because it is the textbook fit for binary features
    and sets an honest floor — if the forest cannot beat it, the extra complexity
    is not earning its place.
    """
    return {
        "random_forest": RandomForestClassifier(
            n_estimators=300,
            max_depth=None,
            min_samples_leaf=2,
            class_weight="balanced",
            random_state=random_state,
            n_jobs=-1,
        ),
        "logistic_regression": LogisticRegression(
            max_iter=2000, C=1.0, class_weight="balanced", random_state=random_state
        ),
        "bernoulli_nb": BernoulliNB(alpha=0.5),
    }


@dataclass
class EvaluationReport:
    """What a trained model scored, and on what."""

    model_name: str
    accuracy: float
    top_3_accuracy: float
    cv_mean: float
    cv_std: float
    report: str = field(repr=False, default="")

    def summary(self) -> str:
        return (
            f"{self.model_name}: accuracy {self.accuracy:.3f} | "
            f"top-3 {self.top_3_accuracy:.3f} | "
            f"5-fold CV {self.cv_mean:.3f} ±{self.cv_std:.3f}"
        )


def evaluate(model, X_test, y_test, X, y, name: str, cv: int = 5) -> EvaluationReport:
    """Score a fitted model on the holdout set and by cross-validation.

    Top-3 accuracy is reported alongside top-1 because the engine is a triage aid:
    surfacing the right condition in a shortlist a clinician reviews is the actual
    job, and conditions with overlapping presentations (flu vs COVID-19) will always
    trade places at rank 1.
    """
    predictions = model.predict(X_test)
    probabilities = model.predict_proba(X_test)

    cv_scores = cross_val_score(model, X, y, cv=cv, scoring="accuracy", n_jobs=-1)

    return EvaluationReport(
        model_name=name,
        accuracy=accuracy_score(y_test, predictions),
        top_3_accuracy=top_k_accuracy_score(y_test, probabilities, k=3, labels=model.classes_),
        cv_mean=float(np.mean(cv_scores)),
        cv_std=float(np.std(cv_scores)),
        report=classification_report(y_test, predictions, zero_division=0),
    )


def train_best_model(
    frame: pd.DataFrame,
    test_size: float = 0.2,
    random_state: int = 42,
    cv: int = 5,
) -> tuple[Any, EvaluationReport, list[EvaluationReport]]:
    """Train every candidate, and return the one with the best cross-validated score.

    Selection uses the CV mean rather than holdout accuracy so the choice is not
    made on a single lucky split.
    """
    X, y = split_features_labels(frame)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=random_state, stratify=y
    )

    reports: list[EvaluationReport] = []
    fitted: dict[str, Any] = {}

    for name, model in build_candidates(random_state).items():
        model.fit(X_train, y_train)
        fitted[name] = model
        reports.append(evaluate(model, X_test, y_test, X, y, name, cv=cv))

    best = max(reports, key=lambda r: r.cv_mean)
    return fitted[best.model_name], best, reports


def symptom_importance(model, top_n: int = 15) -> list[tuple[str, float]]:
    """Rank symptoms by how much the model relies on them, when it can say."""
    if not hasattr(model, "feature_importances_"):
        return []
    pairs = zip(SYMPTOMS, model.feature_importances_)
    return sorted(pairs, key=lambda pair: pair[1], reverse=True)[:top_n]


def save_model(model, path: str | Path = MODEL_PATH) -> Path:
    """Persist the model together with the feature order it was trained on."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "symptoms": list(SYMPTOMS)}, path)
    return path


def load_model(path: str | Path = MODEL_PATH) -> tuple[Any, list[str]]:
    """Load a model and reject it if the feature order no longer matches the code."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"No model at {path}. Train one first: python -m src.train"
        )

    bundle = joblib.load(path)
    symptoms = bundle["symptoms"]

    if symptoms != list(SYMPTOMS):
        raise ValueError(
            "Saved model was trained on a different symptom set. Retrain before serving — "
            "a mismatched feature order predicts confidently and wrongly."
        )

    return bundle["model"], symptoms
