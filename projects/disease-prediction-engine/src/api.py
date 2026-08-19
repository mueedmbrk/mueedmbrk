"""Optional REST API — exposes the engine over HTTP for other services."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .knowledge_base import DISEASES, SYMPTOMS
from .predict import DiseasePredictor

app = FastAPI(
    title="Disease Prediction Engine",
    description="Preliminary symptom-based screening support. Not a diagnostic device.",
    version="1.0.0",
)

_predictor: DiseasePredictor | None = None


def get_predictor() -> DiseasePredictor:
    """Load the model once on first use, not on import — keeps startup fast and testable."""
    global _predictor
    if _predictor is None:
        _predictor = DiseasePredictor()
    return _predictor


class SymptomRequest(BaseModel):
    symptoms: list[str] = Field(..., min_length=1, examples=[["fever", "dry_cough", "fatigue"]])
    top_k: int = Field(3, ge=1, le=10)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/symptoms")
def list_symptoms() -> dict:
    """The vocabulary a client should offer — free text will not match."""
    return {"symptoms": list(SYMPTOMS), "count": len(SYMPTOMS)}


@app.get("/conditions")
def list_conditions() -> dict:
    return {"conditions": list(DISEASES), "count": len(DISEASES)}


@app.post("/predict")
def predict(request: SymptomRequest) -> dict:
    try:
        assessment = get_predictor().predict(request.symptoms, top_k=request.top_k)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "predictions": [
            {"disease": p.disease, "probability": round(p.probability, 4), "confidence": p.confidence}
            for p in assessment.predictions
        ],
        "urgent": assessment.urgent,
        "recognised_symptoms": assessment.recognised_symptoms,
        "unknown_symptoms": assessment.unknown_symptoms,
        "advice": assessment.advice,
        "disclaimer": "Preliminary screening support only — not a medical diagnosis.",
    }
