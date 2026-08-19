<h1 align="center">🩺 Disease Prediction Engine</h1>

<p align="center">
  <b>🧬 Symptom-based screening support that ranks probable conditions and flags the urgent ones</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/scikit--learn-1.4-F7931E?logo=scikitlearn&logoColor=white" alt="scikit-learn">
  <img src="https://img.shields.io/badge/FastAPI-0.110-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/accuracy-95%25-brightgreen" alt="95% accuracy">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
</p>

---

## 📖 Overview

Triage is a ranking problem before it is a diagnosis problem. A clinician seeing a
patient with fever, joint pain and a rash does not need a machine to name one
disease — they need the shortlist, in the right order, with anything dangerous
pushed to the top.

This engine takes reported symptoms and returns exactly that: a ranked shortlist of
probable conditions with calibrated probabilities, plus an **independent red-flag
check** that escalates urgent presentations even when the model ranks something mild
first.

## ✨ Features

- 🎯 **Ranked shortlist, not a single guess** — top-*k* conditions with probabilities and confidence bands
- 🚨 **Red-flag escalation outside the model** — rule-based urgency that a misranked classifier cannot suppress
- 🔬 **Automatic model selection** — Random Forest, Logistic Regression and Bernoulli Naive Bayes compete on cross-validated score
- 🧬 **Reproducible synthetic cohort** — realistic training data with no patient privacy exposure
- 📉 **Honest noise model** — background symptoms and under-reporting keep the task from being trivially separable
- 🔑 **Symptom importance** — see which symptoms actually drive the model
- 🛡️ **Feature-order safety check** — a model trained on a different symptom set is rejected at load, not silently served
- 🌐 **Optional REST API** — FastAPI service with a symptom vocabulary endpoint
- 🧪 **15 unit tests** covering the knowledge base, encoding, ranking and triage rules

## 🧠 How It Works

```
🗣️  Reported symptoms  ["high_fever", "joint_pain", "skin_rash"]
        │
        ▼
┌─────────────────────────┐
│  encode_symptoms  🔤    │  normalise → validate against vocabulary
│                         │  unknown names reported back, never dropped
└───────────┬─────────────┘
            │  named binary feature frame
            ▼
┌─────────────────────────┐
│  Classifier  🔬         │  predict_proba → rank → top-k
└───────────┬─────────────┘
            │
            ├──────────────────────────────┐
            ▼                              ▼
┌─────────────────────────┐    ┌─────────────────────────┐
│  Ranked predictions 📊  │    │  Red-flag check  🚨     │
│  Dengue        0.81     │    │  rule-based, model-     │
│  Malaria       0.11     │    │  independent escalation │
│  Typhoid       0.04     │    └───────────┬─────────────┘
└───────────┬─────────────┘                │
            └──────────────┬───────────────┘
                           ▼
                  🩺 Assessment + advice
```

### 🚨 Why the red-flag check sits outside the model

A classifier can only predict labels it was trained on, and it can be confidently
wrong. So symptoms like `stiff_neck`, `chest_pain`, `shortness_of_breath`,
`confusion` and `yellowing_of_eyes` escalate to urgent **by rule**, regardless of
what the model ranked first. A missed red flag costs far more than an unnecessary
referral — that asymmetry is encoded deliberately rather than left to the model.

## 📊 Results

Trained on a balanced 2,100-patient cohort across 14 conditions:

| Model | Accuracy | Top-3 Accuracy | 5-Fold CV |
|---|---|---|---|
| 🏆 **Bernoulli Naive Bayes** | 0.948 | 0.995 | **0.957 ±0.008** |
| Logistic Regression | 0.950 | 0.998 | 0.953 ±0.007 |
| Random Forest | 0.933 | 0.995 | 0.942 ±0.010 |

Naive Bayes winning is the expected result, not an accident — it is the textbook fit
for binary presence/absence features, and it is included precisely to stop a heavier
model being adopted when it is not earning its complexity.

**Top-3 accuracy (99.5%) matters more than top-1 here.** Conditions with overlapping
presentations — influenza and COVID-19, typhoid and malaria — will legitimately trade
places at rank 1. Getting the right condition into a shortlist a clinician reviews is
the actual job.

## 🚀 Quick Start

```bash
# 1️⃣ Clone and enter
git clone https://github.com/mueedmbrk/disease-prediction-engine.git
cd disease-prediction-engine

# 2️⃣ Environment and dependencies
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3️⃣ Train (writes artifacts/disease_model.joblib)
python -m src.train

# 4️⃣ Predict
python -c "
from src.predict import DiseasePredictor
a = DiseasePredictor().predict(['high_fever','joint_pain','skin_rash','headache'])
for p in a.predictions:
    print(f'{p.disease:20} {p.probability:.3f}  ({p.confidence})')
print('Urgent:', a.urgent)
print(a.advice)
"
```

### 🏋️ Training options

```bash
python -m src.train                       # synthetic cohort, 400 patients per condition
python -m src.train --samples 1000        # larger cohort
python -m src.train --csv data/real.csv   # train on a real dataset instead
python -m src.train --output models/v2.joblib
```

### 🌐 Running the API

```bash
uvicorn src.api:app --reload
```

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | Liveness probe |
| `/symptoms` | GET | The recognised symptom vocabulary |
| `/conditions` | GET | Conditions the model can predict |
| `/predict` | POST | Ranked assessment for reported symptoms |

```bash
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"symptoms": ["high_fever", "chills", "sweating"], "top_k": 3}'
```

Interactive docs at **http://localhost:8000/docs**.

## 🧬 The Knowledge Base

`src/knowledge_base.py` holds 14 conditions across 40 symptoms as **presentation
likelihoods** — the probability a patient with a condition reports a given symptom.
It is data, not rules, so a clinician can review and extend the table without
touching any training code.

```python
"Dengue": {
    "high_fever": 0.90, "joint_pain": 0.85, "muscle_pain": 0.82,
    "headache": 0.78, "skin_rash": 0.60, ...
}
```

Adding a condition is a dictionary entry plus a retrain. `validate_knowledge_base()`
fails loudly on typos and out-of-range probabilities before training starts.

## 📉 On the Synthetic Data

Real symptom-checker training data is patient data and cannot ship in a public repo,
so the cohort is generated from the knowledge base with two kinds of noise:

| Noise | Rate | Why it is there |
|---|---|---|
| 🎲 **Background symptoms** | 2% | Patients report unrelated symptoms, so no single symptom is proof |
| 🤐 **Under-reporting** | 8% | Patients forget or downplay symptoms, so the model must work from partial evidence |

Without these the classifier scores ~100% and tells you nothing. Pass `--csv` to
train on a real dataset with the same schema whenever one is available.

## 🧪 Testing

```bash
pytest -v
```

15 tests cover knowledge-base consistency, cohort balance, symptom encoding and
normalisation, ranking order, red-flag escalation, confidence bands, and model
persistence round-tripping.

## 📁 Project Structure

```
disease-prediction-engine/
├── src/
│   ├── knowledge_base.py  🧬  Conditions, symptoms, red flags
│   ├── dataset.py         📊  Cohort generation and CSV loading
│   ├── model.py           🔬  Candidates, evaluation, persistence
│   ├── predict.py         🎯  Encoding, ranking, triage advice
│   ├── train.py           🏋️  Training CLI
│   └── api.py             🌐  FastAPI service
├── tests/test_engine.py
├── requirements.txt
└── README.md
```

## ⚠️ Medical Disclaimer

This engine provides **preliminary screening support only**. It is not a diagnostic
device, it is not a substitute for professional medical judgement, and it must not be
used as the sole basis for any clinical decision. Always consult a qualified clinician.

## 🗺️ Roadmap

- [ ] 📅 Symptom duration and severity as features, not just presence
- [ ] 👤 Patient context (age, sex, comorbidities, travel history)
- [ ] 🔍 SHAP explanations per prediction
- [ ] 📈 Probability calibration curves and reliability diagrams
- [ ] 🏥 Training pipeline for a real de-identified clinical dataset

## 📄 License

Released under the [MIT License](LICENSE).

## 👤 Author

**Mueed Mubarak** — AI Automation Engineer · Machine Learning Developer

[![Portfolio](https://img.shields.io/badge/Portfolio-mueedmbrk.github.io-22d3ee)](https://mueedmbrk.github.io/mueedmbrk/)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-mueed--mubarak-0A66C2?logo=linkedin&logoColor=white)](https://www.linkedin.com/in/mueed-mubarak/)
[![Email](https://img.shields.io/badge/Email-mueedmbrk%40gmail.com-EA4335?logo=gmail&logoColor=white)](mailto:mueedmbrk@gmail.com)

<p align="center">⭐ If this project is useful to you, a star is very welcome!</p>
