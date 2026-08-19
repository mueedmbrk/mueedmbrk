"""End-to-end tests: knowledge base -> cohort -> model -> assessment."""

import numpy as np
import pytest

from src.dataset import generate_cohort, split_features_labels
from src.knowledge_base import DISEASES, SYMPTOMS, validate_knowledge_base
from src.model import save_model, load_model, train_best_model
from src.predict import DiseasePredictor, encode_symptoms


@pytest.fixture(scope="module")
def cohort():
    # Small but sufficient — keeps the suite fast while staying learnable.
    return generate_cohort(samples_per_disease=120, random_state=7)


@pytest.fixture(scope="module")
def trained(cohort):
    model, best, _ = train_best_model(cohort, random_state=7, cv=3)
    return model, best


def test_knowledge_base_is_consistent():
    validate_knowledge_base()


def test_cohort_shape_and_balance(cohort):
    assert len(cohort) == 120 * len(DISEASES)
    assert set(cohort["disease"].unique()) == set(DISEASES)
    # Perfectly balanced by construction, so accuracy is not inflated by a majority class.
    assert cohort["disease"].value_counts().nunique() == 1


def test_cohort_features_are_binary(cohort):
    features, _ = split_features_labels(cohort)
    assert list(features.columns) == list(SYMPTOMS)
    assert set(np.unique(features.to_numpy())) <= {0, 1}


def test_noise_prevents_trivial_separability(cohort):
    """With under-reporting applied, no symptom should be present in every case."""
    features, _ = split_features_labels(cohort)
    assert features.to_numpy().mean() < 0.5


def test_model_beats_random_baseline(trained):
    _, best = trained
    baseline = 1.0 / len(DISEASES)
    assert best.accuracy > baseline * 3
    assert best.top_3_accuracy >= best.accuracy


def test_encode_flags_unknown_symptoms():
    vector, recognised, unknown = encode_symptoms(["fever", "not_a_symptom", "Dry Cough"])
    assert list(vector.columns) == list(SYMPTOMS), "feature order must match training"
    assert "fever" in recognised
    assert "dry_cough" in recognised, "input should be normalised to snake_case"
    assert unknown == ["not_a_symptom"]
    assert vector.to_numpy().sum() == 2


def test_encode_ignores_blank_input():
    vector, recognised, unknown = encode_symptoms(["", "   ", "fever"])
    assert recognised == ["fever"]
    assert unknown == []
    assert vector.to_numpy().sum() == 1


def test_prediction_is_ranked_and_normalised(trained):
    model, _ = trained
    assessment = DiseasePredictor(model=model).predict(["fever", "dry_cough", "fatigue"], top_k=3)

    assert len(assessment.predictions) == 3
    probabilities = [p.probability for p in assessment.predictions]
    assert probabilities == sorted(probabilities, reverse=True)
    assert all(0.0 <= p <= 1.0 for p in probabilities)


def test_classic_presentation_reaches_the_shortlist(trained):
    """Textbook dengue symptoms should put dengue in the top three."""
    model, _ = trained
    assessment = DiseasePredictor(model=model).predict(
        ["high_fever", "joint_pain", "muscle_pain", "skin_rash", "headache"], top_k=3
    )
    assert "Dengue" in [p.disease for p in assessment.predictions]


def test_red_flag_symptom_forces_urgent(trained):
    """A red flag escalates even when the model's top pick is a mild condition."""
    model, _ = trained
    assessment = DiseasePredictor(model=model).predict(["runny_nose", "stiff_neck"])
    assert assessment.urgent is True
    assert "medical attention" in assessment.advice


def test_mild_presentation_is_not_urgent(trained):
    model, _ = trained
    assessment = DiseasePredictor(model=model).predict(["runny_nose", "sneezing", "sore_throat"])
    assert assessment.urgent is False


def test_no_recognised_symptoms_returns_empty_assessment(trained):
    model, _ = trained
    assessment = DiseasePredictor(model=model).predict(["purple_spots", "hiccups"])
    assert assessment.predictions == []
    assert assessment.top is None
    assert assessment.unknown_symptoms == ["hiccups", "purple_spots"]


def test_confidence_bands():
    from src.predict import Prediction

    assert Prediction("X", 0.85).confidence == "high"
    assert Prediction("X", 0.50).confidence == "moderate"
    assert Prediction("X", 0.10).confidence == "low"


def test_model_roundtrips_through_disk(trained, tmp_path):
    model, _ = trained
    path = save_model(model, tmp_path / "model.joblib")
    restored, symptoms = load_model(path)

    assert symptoms == list(SYMPTOMS)
    sample = ["fever", "dry_cough", "fatigue"]
    before = DiseasePredictor(model=model).predict(sample).top
    after = DiseasePredictor(model=restored).predict(sample).top
    assert before.disease == after.disease


def test_missing_model_file_is_reported_clearly(tmp_path):
    with pytest.raises(FileNotFoundError, match="Train one first"):
        load_model(tmp_path / "absent.joblib")
