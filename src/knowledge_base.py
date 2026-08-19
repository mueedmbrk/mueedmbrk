"""Clinical knowledge base: which symptoms present with which conditions.

Each disease maps a symptom to the probability that a patient with that condition
reports it. These are *presentation likelihoods*, not diagnostic weights — a
symptom at 0.9 shows up in about nine of ten cases.

Keeping this as data rather than as rules is deliberate: the model learns the
correlations, and clinicians can review or extend this table without touching
any training code.
"""

from __future__ import annotations

SYMPTOMS: tuple[str, ...] = (
    "fever",
    "high_fever",
    "chills",
    "fatigue",
    "headache",
    "body_ache",
    "joint_pain",
    "muscle_pain",
    "cough",
    "dry_cough",
    "productive_cough",
    "sore_throat",
    "runny_nose",
    "sneezing",
    "shortness_of_breath",
    "chest_pain",
    "wheezing",
    "loss_of_smell",
    "loss_of_taste",
    "nausea",
    "vomiting",
    "diarrhoea",
    "abdominal_pain",
    "loss_of_appetite",
    "weight_loss",
    "excessive_thirst",
    "frequent_urination",
    "blurred_vision",
    "dizziness",
    "palpitations",
    "sweating",
    "skin_rash",
    "itching",
    "yellowing_of_eyes",
    "dark_urine",
    "swollen_lymph_nodes",
    "night_sweats",
    "sensitivity_to_light",
    "stiff_neck",
    "confusion",
)

# disease -> {symptom: probability of presenting}
DISEASE_PROFILES: dict[str, dict[str, float]] = {
    "Common Cold": {
        "runny_nose": 0.92, "sneezing": 0.85, "sore_throat": 0.75, "cough": 0.65,
        "headache": 0.40, "fatigue": 0.45, "fever": 0.20, "body_ache": 0.25,
    },
    "Influenza": {
        "high_fever": 0.85, "fever": 0.90, "body_ache": 0.88, "fatigue": 0.85,
        "headache": 0.75, "chills": 0.70, "dry_cough": 0.65, "sore_throat": 0.50,
        "muscle_pain": 0.72, "sweating": 0.45,
    },
    "COVID-19": {
        "fever": 0.80, "dry_cough": 0.75, "fatigue": 0.78, "loss_of_smell": 0.62,
        "loss_of_taste": 0.58, "shortness_of_breath": 0.45, "headache": 0.55,
        "sore_throat": 0.42, "body_ache": 0.50, "diarrhoea": 0.20,
    },
    "Pneumonia": {
        "high_fever": 0.78, "productive_cough": 0.85, "shortness_of_breath": 0.80,
        "chest_pain": 0.70, "chills": 0.65, "fatigue": 0.72, "sweating": 0.50,
        "confusion": 0.18, "loss_of_appetite": 0.40,
    },
    "Asthma": {
        "wheezing": 0.90, "shortness_of_breath": 0.88, "chest_pain": 0.45,
        "dry_cough": 0.70, "fatigue": 0.35,
    },
    "Migraine": {
        "headache": 0.98, "sensitivity_to_light": 0.80, "nausea": 0.65,
        "vomiting": 0.35, "dizziness": 0.40, "blurred_vision": 0.32,
    },
    "Gastroenteritis": {
        "diarrhoea": 0.90, "vomiting": 0.72, "nausea": 0.80, "abdominal_pain": 0.82,
        "fever": 0.40, "fatigue": 0.50, "loss_of_appetite": 0.60,
    },
    "Type 2 Diabetes": {
        "excessive_thirst": 0.85, "frequent_urination": 0.88, "fatigue": 0.70,
        "blurred_vision": 0.55, "weight_loss": 0.45, "itching": 0.30,
    },
    "Malaria": {
        "high_fever": 0.92, "chills": 0.88, "sweating": 0.80, "headache": 0.70,
        "nausea": 0.55, "vomiting": 0.45, "body_ache": 0.62, "fatigue": 0.75,
    },
    "Dengue": {
        "high_fever": 0.90, "joint_pain": 0.85, "muscle_pain": 0.82, "headache": 0.78,
        "skin_rash": 0.60, "nausea": 0.50, "fatigue": 0.70, "vomiting": 0.40,
    },
    "Typhoid": {
        "fever": 0.90, "abdominal_pain": 0.70, "headache": 0.62, "fatigue": 0.75,
        "loss_of_appetite": 0.68, "diarrhoea": 0.45, "skin_rash": 0.30,
    },
    "Hepatitis": {
        "yellowing_of_eyes": 0.88, "dark_urine": 0.80, "fatigue": 0.78,
        "nausea": 0.65, "abdominal_pain": 0.60, "loss_of_appetite": 0.72,
        "vomiting": 0.42, "itching": 0.35,
    },
    "Tuberculosis": {
        "productive_cough": 0.85, "weight_loss": 0.78, "night_sweats": 0.75,
        "fatigue": 0.70, "fever": 0.65, "chest_pain": 0.50,
        "swollen_lymph_nodes": 0.40, "loss_of_appetite": 0.60,
    },
    "Meningitis": {
        "stiff_neck": 0.88, "high_fever": 0.82, "headache": 0.90,
        "sensitivity_to_light": 0.70, "confusion": 0.60, "nausea": 0.55,
        "vomiting": 0.50, "skin_rash": 0.30,
    },
}

DISEASES: tuple[str, ...] = tuple(DISEASE_PROFILES)

# Conditions that need same-day medical attention regardless of model confidence.
RED_FLAG_SYMPTOMS: frozenset[str] = frozenset(
    {"shortness_of_breath", "chest_pain", "stiff_neck", "confusion", "yellowing_of_eyes"}
)

URGENT_CONDITIONS: frozenset[str] = frozenset(
    {"Meningitis", "Pneumonia", "COVID-19", "Tuberculosis", "Hepatitis"}
)


def validate_knowledge_base() -> None:
    """Fail loudly if a profile references a symptom the feature vector does not have."""
    known = set(SYMPTOMS)
    for disease, profile in DISEASE_PROFILES.items():
        unknown = set(profile) - known
        if unknown:
            raise ValueError(f"{disease} references unknown symptoms: {sorted(unknown)}")
        for symptom, probability in profile.items():
            if not 0.0 < probability <= 1.0:
                raise ValueError(
                    f"{disease}/{symptom} probability {probability} is outside (0, 1]"
                )
