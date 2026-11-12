"""Offline-only training and holdout evaluation for the V1 catalogue."""

import argparse
import hashlib
import json
import time
import tracemalloc
from importlib.metadata import version
from pathlib import Path

from backend.supervisor.contracts import CATALOGUE_VERSION, Intent
from backend.supervisor.dataset import TrainingExample, partition_examples
from backend.supervisor.policy import normalize_utterance
from backend.supervisor.synthetic import synthetic_examples

LABELS = tuple(Intent)


def train(examples: list[TrainingExample], output: Path, seed: int, kind: str) -> dict:
    partitions = partition_examples(examples)
    import joblib
    import numpy as np
    import sklearn
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import f1_score, precision_recall_fscore_support
    from sklearn.multiclass import OneVsRestClassifier
    from sklearn.pipeline import FeatureUnion

    if kind == "xgboost":
        from xgboost import XGBClassifier

    def arrays(rows):
        return (
            [normalize_utterance(row.text) for row in rows],
            np.asarray([[int(label in row.intents) for label in LABELS] for row in rows]),
        )

    features = FeatureUnion([
        ("word", TfidfVectorizer(ngram_range=(1, 2), lowercase=False, token_pattern=r"(?u)\b\w+\b")),
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), lowercase=False)),
    ])
    cpu_started = time.process_time()
    tracemalloc.start()
    try:
        train_text, train_y = arrays(partitions["train"])
        train_x = features.fit_transform(train_text)
        if kind == "baseline":
            parameters = {"random_state": seed, "max_iter": 500, "class_weight": "balanced"}
            estimator = OneVsRestClassifier(LogisticRegression(**parameters)).fit(train_x, train_y)
            predict = estimator.predict_proba
        else:
            parameters = {
                "random_state": seed, "n_estimators": 60, "max_depth": 3,
                "tree_method": "hist", "objective": "binary:logistic", "n_jobs": 1,
            }
            estimator = [XGBClassifier(**parameters).fit(train_x, y) for y in train_y.T]

            def predict(features_matrix):
                return np.column_stack([model.predict_proba(features_matrix)[:, 1] for model in estimator])
        _, python_heap_peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    fit_cpu_seconds = time.process_time() - cpu_started
    process_memory = None
    try:
        import psutil

        info = psutil.Process().memory_info()
        process_memory = getattr(info, "peak_wset", info.rss)
    except (ImportError, OSError):
        pass

    val_text, val_y = arrays(partitions["validation"])
    val_scores = predict(features.transform(val_text))
    thresholds = []
    for actual, scores in zip(val_y.T, val_scores.T, strict=True):
        options = np.unique(np.r_[0.05, scores, 1.0])
        thresholds.append(float(max(options, key=lambda threshold: (
            f1_score(actual, scores >= threshold, zero_division=0), threshold,
        ))))

    test_text, test_y = arrays(partitions["test"])
    scores = []
    latency = []
    for utterance in test_text:
        start = time.perf_counter()
        scores.append(predict(features.transform([utterance]))[0])
        latency.append((time.perf_counter() - start) * 1000)
    test_scores = np.asarray(scores)
    predicted = test_scores >= thresholds
    precision, recall, f1, support = precision_recall_fscore_support(test_y, predicted, zero_division=0)
    ood = ~test_y.any(axis=1)
    multilabel = test_y.sum(axis=1) > 1
    exact = (test_y == predicted).all(axis=1)
    canonical_rows = sorted(row.model_dump_json() for row in examples)
    fingerprint = hashlib.sha256("\n".join(canonical_rows).encode()).hexdigest()
    manifest = {
        "catalogue_version": CATALOGUE_VERSION,
        "model_version": f"{kind}-v1-{fingerprint[:12]}-{seed}",
        "label_index": [label.value for label in LABELS],
        "seed": seed,
        "dataset_sha256": fingerprint,
        "dataset_sources": sorted({row.source for row in examples}),
        "split_counts": {name: len(rows) for name, rows in partitions.items()},
        "sklearn_version": sklearn.__version__,
        "xgboost_version": version("xgboost") if kind == "xgboost" else None,
        "kind": kind,
        "parameters": parameters,
        "approval": "REQUIRED",
        "thresholds": dict(zip(LABELS, thresholds, strict=True)),
        "test": {
            "macro_f1": f1_score(test_y, predicted, average="macro", zero_division=0),
            "micro_f1": f1_score(test_y, predicted, average="micro", zero_division=0),
            "exact_match": float(exact.mean()),
            "multi_intent_exact_match": float(exact[multilabel].mean()) if multilabel.any() else None,
            "emergency_recall": float(recall[LABELS.index(Intent.ROADSIDE_EMERGENCY)]),
            "ood_false_accept": float(predicted[ood].any(axis=1).mean()),
            "brier_mean": float(np.mean((test_scores - test_y) ** 2)),
            "latency_ms_p50": float(np.percentile(latency, 50)),
            "latency_ms_p95": float(np.percentile(latency, 95)),
            "fit_cpu_seconds": fit_cpu_seconds,
            "fit_python_heap_peak_bytes": python_heap_peak,
            "process_working_set_bytes": process_memory,
            "per_intent": {
                label.value: {"precision": float(p), "recall": float(r), "f1": float(f), "support": int(n)}
                for label, p, r, f, n in zip(LABELS, precision, recall, f1, support, strict=True)
            },
            "errors": [
                {"row": index, "expected": [label.value for label, bit in zip(LABELS, y) if bit],
                 "predicted": [label.value for label, bit in zip(LABELS, result) if bit]}
                for index, (y, result) in enumerate(zip(test_y, predicted, strict=True)) if not exact[index]
            ],
        },
    }
    output.mkdir(parents=True, exist_ok=True)
    bundle = output / "model.joblib"
    joblib.dump({"features": features, "estimator": estimator, "manifest": manifest}, bundle)
    manifest["artifact_sha256"] = hashlib.sha256(bundle.read_bytes()).hexdigest()
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--synthetic", action="store_true")
    source.add_argument("--dataset", type=Path, help="Reviewed, anonymized and grouped JSONL.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--kind", choices=("baseline", "xgboost"), default="baseline")
    parser.add_argument("--baseline-manifest", type=Path)
    args = parser.parse_args()
    try:
        if args.synthetic:
            examples = synthetic_examples()
        else:
            examples = [
                TrainingExample.model_validate_json(line)
                for line in args.dataset.read_text(encoding="utf-8").splitlines() if line.strip()
            ]
        if args.kind == "xgboost":
            if not args.baseline_manifest:
                raise ValueError("XGBoost requires --baseline-manifest")
            baseline = json.loads(args.baseline_manifest.read_text(encoding="utf-8"))
            fingerprint = hashlib.sha256("\n".join(sorted(row.model_dump_json() for row in examples)).encode()).hexdigest()
            if (
                baseline.get("dataset_sha256") != fingerprint
                or baseline.get("catalogue_version") != CATALOGUE_VERSION
                or baseline.get("label_index") != list(LABELS)
                or baseline.get("seed") != args.seed
                or baseline.get("kind") != "baseline"
                or "test" not in baseline
            ):
                raise ValueError("baseline must use the same dataset, groups, catalogue and seed")
        result = train(examples, args.output, args.seed, args.kind)
    except (ImportError, ValueError, OSError) as exc:
        # Validation errors can include raw input; never print dataset rows.
        from pydantic import ValidationError

        reason = "invalid dataset schema" if isinstance(exc, ValidationError) else str(exc)
        parser.exit(2, f"HOLD: {reason}\n")
    summary = {k: v for k, v in result["test"].items() if k not in {"per_intent", "errors"}}
    print(json.dumps({"sources": result["dataset_sources"], "split_counts": result["split_counts"],
                      "model_version": result["model_version"], "test": summary}, indent=2))


if __name__ == "__main__":
    main()
