"""Benchmark v2. Seleksi model memakai blok skenario latih berurutan."""
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from imblearn.ensemble import BalancedRandomForestClassifier
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, IsolationForest, RandomForestClassifier
from sklearn.metrics import (accuracy_score, average_precision_score, balanced_accuracy_score,
                             classification_report, f1_score)
from sklearn.model_selection import TimeSeriesSplit
from sklearn.utils.class_weight import compute_sample_weight
from threadpoolctl import threadpool_limits
from xgboost import XGBClassifier

from kalisentinel_core import IF_FEATURES, PARAMS, RF_FEATURES
from river_features import features, paired_grid, quality_control
from simulate_river import DATASET

OUT = Path(__file__).resolve().parent / "eksperimen_v2"
MODELS = OUT.parent / "models"
CLASSES = ["normal", "hujan", "pembuangan", "sensor_rusak"]
FAULT = CLASSES.index("sensor_rusak")
DISCHARGE = CLASSES.index("pembuangan")
SEED = 42
THREADS = 4


def pair_labels(run, index):
    labels = run.pivot(index="timestamp", columns="node_id", values="label").reindex(index)
    if labels.isna().any().any():
        raise ValueError("Label HULU/HILIR tidak lengkap di manifest simulasi.")
    upstream, downstream = labels.HULU, labels.HILIR
    return np.select([(upstream == "sensor_rusak") | (downstream == "sensor_rusak"),
                      downstream == "pembuangan", (upstream == "hujan") | (downstream == "hujan")],
                     [FAULT, DISCHARGE, 1], default=0)


def prepare(raw):
    frames = {stage: [] for stage in ("historis", "mentah", "qc", "fitur")}
    logs = []
    for scenario, run in raw.groupby("skenario", sort=True):
        hu, hi = paired_grid(run)
        for stage in frames:
            frame = features(hu, hi, clean=stage in ("qc", "fitur"), enhanced=stage == "fitur",
                             historic=stage == "historis")
            frame = frame.assign(truth=pair_labels(run, frame.index), skenario=scenario,
                                 profil=run.profil.iloc[0], split=run.split.iloc[0])
            frames[stage].append(frame)
        for node, grid in zip(("HULU", "HILIR"), (hu, hi)):
            clean, invalid, filled = quality_control(grid)
            rows, cols = np.where((invalid | filled).to_numpy())
            logs.append(pd.DataFrame({"skenario": scenario, "timestamp": grid.index[rows], "node": node,
                                      "parameter": np.asarray(PARAMS)[cols],
                                      "sebelum": grid.to_numpy()[rows, cols],
                                      "sesudah": clean.to_numpy()[rows, cols],
                                      "invalid": invalid.to_numpy()[rows, cols],
                                      "ffill": filled.to_numpy()[rows, cols]}))
    pd.concat(logs, ignore_index=True).to_csv(OUT / "audit_qc.csv.gz", index=False)
    return {stage: pd.concat(parts).sort_index() for stage, parts in frames.items()}


def estimator(family, depth, leaf, trees=90):
    options = {"max_depth": depth, "random_state": SEED}
    if family == "HistGradientBoosting":
        return HistGradientBoostingClassifier(**options, min_samples_leaf=leaf, max_iter=trees,
                                              early_stopping=False, class_weight="balanced")
    if family == "XGBoost":
        return XGBClassifier(**options, min_child_weight=leaf, n_estimators=trees, n_jobs=THREADS,
                             learning_rate=0.12, tree_method="hist", subsample=0.9, colsample_bytree=0.8)
    common = {**options, "min_samples_leaf": leaf, "n_estimators": trees, "n_jobs": THREADS}
    if family == "Extra Trees":
        return ExtraTreesClassifier(**common, class_weight="balanced", max_features="sqrt")
    if family == "Balanced Random Forest":
        return BalancedRandomForestClassifier(**common)
    return RandomForestClassifier(**common, class_weight="balanced_subsample")


def fit(family, depth, leaf, frame, cols, trees=90):
    model = estimator(family, depth, leaf, trees)
    x, y = frame[cols].to_numpy(np.float32), frame.truth.to_numpy()
    weights = compute_sample_weight("balanced", y) if family == "XGBoost" else None
    return model.fit(x, y, sample_weight=weights)


def classify(probability, threshold=None):
    if threshold is None:
        return probability.argmax(axis=1)
    best_other = probability[:, :FAULT].argmax(axis=1)
    return np.where(probability[:, FAULT] >= threshold, FAULT, best_other)


def metrics(y, prob, threshold=None):
    pred = classify(prob, threshold)
    rep = classification_report(y, pred, labels=range(len(CLASSES)), target_names=CLASSES,
                                zero_division=0, output_dict=True)
    return {"akurasi": accuracy_score(y, pred), "akurasi_berimbang": balanced_accuracy_score(y, pred),
            "macro_f1": rep["macro avg"]["f1-score"], "f1_hujan": rep["hujan"]["f1-score"],
            "f1_pembuangan": rep["pembuangan"]["f1-score"], "f1_sensor": rep["sensor_rusak"]["f1-score"],
            "presisi_sensor": rep["sensor_rusak"]["precision"], "recall_sensor": rep["sensor_rusak"]["recall"],
            "ap_sensor": average_precision_score(y == FAULT, prob[:, FAULT]),
            "ap_pembuangan": average_precision_score(y == DISCHARGE, prob[:, DISCHARGE])}


def optimize(training, cols):
    families = ["Random Forest", "Extra Trees", "XGBoost", "HistGradientBoosting", "Balanced Random Forest"]
    groups = training.skenario.unique()
    folds = list(TimeSeriesSplit(n_splits=3, test_size=2).split(groups))
    results = []
    for family in families:
        for depth, leaf in ((6, 8), (12, 4)):
            observed, predicted = [], []
            for earlier, later in folds:
                fit_data = training[training.skenario.isin(groups[earlier])]
                validation = training[training.skenario.isin(groups[later])]
                assert fit_data.index.max() < validation.index.min()
                model = fit(family, depth, leaf, fit_data, cols)
                predicted.append(model.predict_proba(validation[cols].to_numpy(np.float32)))
                observed.append(validation.truth.to_numpy())
            y, prob = np.concatenate(observed), np.concatenate(predicted)
            for threshold in (None, 0.30, 0.40, 0.50, 0.60):
                result = metrics(y, prob, threshold)
                results.append({"keluarga": family, "depth": depth, "leaf": leaf, "ambang_sensor": threshold,
                                **result})
            print(f"CV {family}, depth={depth}, leaf={leaf}", flush=True)
    # Presisi minimal 70% di OOF jika ada kandidat yang memenuhi.
    return pd.DataFrame(results).sort_values(["macro_f1", "f1_sensor"], ascending=False)


def selected(cv):
    eligible = cv[cv.presisi_sensor >= 0.70]
    return (eligible if len(eligible) else cv).iloc[0]


def threshold_of(row):
    val = row.ambang_sensor
    return None if pd.isna(val) else float(val)


def main():
    OUT.mkdir(exist_ok=True)
    raw = pd.read_csv(DATASET, dtype={"skenario": str})
    raw["timestamp"] = pd.to_datetime(raw.timestamp, utc=True, format="ISO8601")
    assert not raw.duplicated(["skenario", "timestamp", "node_id"]).any()
    manifest = raw.groupby(["skenario", "split", "profil", "seed"], as_index=False).agg(
        mulai=("timestamp", "min"), akhir=("timestamp", "max"), baris=("timestamp", "size"))
    assert manifest.seed.is_unique
    assert manifest.loc[manifest.split.ne("uji"), "akhir"].max() < manifest.loc[manifest.split.eq("uji"), "mulai"].min()
    manifest.to_csv(OUT / "manifest.csv", index=False)
    frames = prepare(raw)
    feature_cols = [c for c in frames["fitur"] if c not in ("truth", "skenario", "profil", "split")]
    train = frames["fitur"].query("split != 'uji'")
    cv = optimize(train, feature_cols)
    cv.to_csv(OUT / "validasi_cv.csv", index=False)
    winner = selected(cv)
    rf_tuned = selected(cv[cv.keluarga.eq("Random Forest")])
    print(f"Model dipilih dari CV: {winner.keluarga}, ambang={threshold_of(winner)}", flush=True)

    test = frames["fitur"].query("split == 'uji'")
    y = test.truth.to_numpy()
    scores = {}
    thresholds = {}
    history = frames["historis"].query("split == 'uji'")
    historical_model = joblib.load(MODELS / "pattern_rf.joblib")
    labels_to_index = [list(historical_model.classes_).index(c) for c in CLASSES]
    scores["Model lama"] = historical_model.predict_proba(history[RF_FEATURES].to_numpy())[:, labels_to_index]
    thresholds["Model lama"] = None
    for name, stage, extra, tuning in (
        ("Baseline v2", "mentah", False, None), ("Cleaning", "qc", False, None),
        ("Fitur temporal", "fitur", False, None), ("Augmentasi", "fitur", True, None),
        ("RF dioptimasi", "fitur", True, rf_tuned), ("Model final", "fitur", True, winner),
    ):
        frame = frames[stage]
        training = frame[frame.split.isin(["latih", "augmentasi"] if extra else ["latih"])]
        testing = frame.query("split == 'uji'")
        pd.testing.assert_series_equal(testing.truth, test.truth)
        cols = feature_cols if stage == "fitur" else RF_FEATURES
        family, depth, leaf = ("Random Forest", 18, 3) if tuning is None else (
            tuning.keluarga, int(tuning.depth), int(tuning.leaf))
        model = fit(family, depth, leaf, training, cols)
        scores[name] = model.predict_proba(testing[cols].to_numpy(np.float32))
        thresholds[name] = threshold_of(tuning) if tuning is not None else None
    final = model
    joblib.dump({"model": final, "features": feature_cols, "classes": CLASSES,
                 "sensor_threshold": thresholds["Model final"]}, OUT / "model_final.joblib", compress=3)
    ablation = pd.DataFrame({name: metrics(y, prob, thresholds[name]) for name, prob in scores.items()}).T
    ablation.to_csv(OUT / "ablasi.csv", index_label="tahap")
    robustness = []
    for column in ("profil", "skenario"):
        for group in test[column].unique():
            mask = test[column].eq(group).to_numpy()
            for name in ("Model lama", "Baseline v2", "Model final"):
                robustness.append({"tingkat": column, "grup": group, "model": name, "sampel": int(mask.sum()),
                                   **metrics(y[mask], scores[name][mask], thresholds[name])})
    robustness = pd.DataFrame(robustness)
    robustness.to_csv(OUT / "robustness.csv", index=False)
    final_predictions = classify(scores["Model final"], thresholds["Model final"])
    prediction_log = test[["skenario", "profil", "truth"]].assign(prediksi=final_predictions)
    for i, cls in enumerate(CLASSES):
        prediction_log[f"prob_{cls}"] = scores["Model final"][:, i]
    prediction_log.to_csv(OUT / "prediksi_uji.csv.gz", index_label="timestamp")
    pd.DataFrame(classification_report(y, final_predictions, labels=range(4), target_names=CLASSES,
                                       output_dict=True, zero_division=0)).T.to_csv(OUT / "per_kelas.csv")

    iso = IsolationForest(n_estimators=160, max_samples=2048, random_state=SEED, n_jobs=THREADS)
    iso.fit(train[train.truth.isin([0, 1])][IF_FEATURES].to_numpy())
    old_iso = joblib.load(MODELS / "isolation_forest.joblib")
    anomaly = {"Isolation Forest lama": -old_iso.score_samples(history[IF_FEATURES].to_numpy()),
               "Isolation Forest v2": -iso.score_samples(test[IF_FEATURES].to_numpy())}
    joblib.dump({"model": iso, "features": IF_FEATURES}, OUT / "isolation_forest_v2.joblib", compress=3)
    summary = {"model": winner.keluarga, "depth": int(winner.depth), "leaf": int(winner.leaf),
               "ambang_sensor": thresholds["Model final"], "macro_f1_cv": float(winner.macro_f1),
               "train": len(train), "test": len(test), "seed_model": SEED,
               "av_precision_iso": {name: average_precision_score(y == DISCHARGE, prob)
                                    for name, prob in anomaly.items()}}
    (OUT / "ringkasan.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    test_matrix = test[feature_cols].to_numpy(np.float32)
    from plot_river_experiment import render

    render(raw, y, scores, thresholds, anomaly, robustness, ablation, final, test_matrix, feature_cols)
    print(ablation.round(3).to_string())


if __name__ == "__main__":
    with threadpool_limits(limits=THREADS):
        main()
