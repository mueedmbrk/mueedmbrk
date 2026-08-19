"""Dataset construction.

Real symptom-checker training data is patient data, which cannot ship in a public
repository. So the engine generates a reproducible cohort from the clinical
knowledge base instead: every patient is sampled from a disease's presentation
profile, with realistic imperfections layered on top.

Point ``load_csv`` at a real dataset when you have one — the model code does not
care where the frame came from, only that it has one binary column per symptom
plus a ``disease`` label.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .knowledge_base import DISEASE_PROFILES, SYMPTOMS

# Probability that a symptom unrelated to the condition is reported anyway.
BACKGROUND_NOISE = 0.02
# Probability that a symptom the patient does have goes unreported.
UNDER_REPORTING = 0.08


def generate_cohort(
    samples_per_disease: int = 400,
    random_state: int = 42,
    background_noise: float = BACKGROUND_NOISE,
    under_reporting: float = UNDER_REPORTING,
) -> pd.DataFrame:
    """Build a synthetic patient cohort as a tidy DataFrame.

    Two kinds of noise make the task honest rather than trivially separable:

    * **Background noise** — patients report symptoms unrelated to their condition
      (a coincidental headache), so the model cannot treat any single symptom as proof.
    * **Under-reporting** — patients forget or downplay symptoms they do have, so the
      model must work from partial evidence, which is the realistic case.

    Without these the classifier scores ~100% and tells you nothing.
    """
    if samples_per_disease < 1:
        raise ValueError("samples_per_disease must be at least 1")

    rng = np.random.default_rng(random_state)
    symptom_index = {symptom: i for i, symptom in enumerate(SYMPTOMS)}

    rows: list[np.ndarray] = []
    labels: list[str] = []

    for disease, profile in DISEASE_PROFILES.items():
        # Start every patient from background noise across all symptoms.
        block = (rng.random((samples_per_disease, len(SYMPTOMS))) < background_noise)

        for symptom, probability in profile.items():
            column = symptom_index[symptom]
            presents = rng.random(samples_per_disease) < probability
            reported = rng.random(samples_per_disease) >= under_reporting
            # A symptom lands only if the patient has it *and* mentions it.
            block[:, column] |= presents & reported

        rows.append(block.astype(np.int8))
        labels.extend([disease] * samples_per_disease)

    frame = pd.DataFrame(np.vstack(rows), columns=list(SYMPTOMS))
    frame["disease"] = labels
    # Shuffle so any downstream split without stratification is still sane.
    return frame.sample(frac=1.0, random_state=random_state).reset_index(drop=True)


def load_csv(path: str | Path) -> pd.DataFrame:
    """Load a real dataset, validating that it matches the expected schema."""
    frame = pd.read_csv(path)

    if "disease" not in frame.columns:
        raise ValueError("dataset must contain a 'disease' label column")

    missing = set(SYMPTOMS) - set(frame.columns)
    if missing:
        raise ValueError(f"dataset is missing symptom columns: {sorted(missing)}")

    return frame


def split_features_labels(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Split into the symptom matrix and the label vector, with columns in a fixed order.

    Column order matters: a model trained on one ordering and served another will
    predict confidently and wrongly, with nothing raising an error.
    """
    return frame[list(SYMPTOMS)], frame["disease"]
