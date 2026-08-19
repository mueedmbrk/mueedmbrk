"""CLI: build a cohort, compare models, save the best one."""

from __future__ import annotations

import argparse
import logging
import sys

from .dataset import generate_cohort, load_csv
from .knowledge_base import validate_knowledge_base
from .model import MODEL_PATH, save_model, symptom_importance, train_best_model

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train the disease prediction engine")
    parser.add_argument("--csv", help="Train on a real dataset instead of a synthetic cohort")
    parser.add_argument("--samples", type=int, default=400, help="Synthetic samples per disease")
    parser.add_argument("--output", default=str(MODEL_PATH), help="Where to save the model")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    validate_knowledge_base()

    if args.csv:
        logger.info("📂 Loading dataset from %s", args.csv)
        frame = load_csv(args.csv)
    else:
        logger.info("🧬 Generating synthetic cohort (%d samples per disease)", args.samples)
        frame = generate_cohort(samples_per_disease=args.samples, random_state=args.seed)

    logger.info("📊 Dataset: %d patients across %d conditions\n", len(frame), frame["disease"].nunique())

    model, best, reports = train_best_model(frame, random_state=args.seed)

    logger.info("🔬 Model comparison")
    for report in sorted(reports, key=lambda r: r.cv_mean, reverse=True):
        marker = "🏆" if report.model_name == best.model_name else "  "
        logger.info("  %s %s", marker, report.summary())

    logger.info("\n📈 Classification report for %s\n%s", best.model_name, best.report)

    importance = symptom_importance(model)
    if importance:
        logger.info("🔑 Most informative symptoms")
        for symptom, score in importance:
            logger.info("   %-24s %.4f", symptom, score)

    path = save_model(model, args.output)
    logger.info("\n💾 Saved %s to %s", best.model_name, path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
