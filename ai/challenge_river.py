"""Uji limpasan awal berpasangan pada dua seed baru, setelah seleksi model."""
import joblib
import pandas as pd

from experiment_river import CLASSES, MODELS, OUT, metrics, pair_labels
from kalisentinel_core import RF_FEATURES
from river_features import features, paired_grid
from simulate_river import simulate


def main():
    old = joblib.load(MODELS / "pattern_rf.joblib")
    final = joblib.load(OUT / "model_final.joblib")
    order = [list(old.classes_).index(cls) for cls in CLASSES]
    results = []
    for seed in (9001, 9002):
        for flush in (False, True):
            trace = simulate(seed, "2026-06-01", "nominal", first_flush=flush)
            trace["timestamp"] = trace.timestamp.dt.tz_convert("UTC")
            hu, hi = paired_grid(trace)
            baseline = features(hu, hi, clean=False, historic=True)
            evolved = features(hu, hi)
            truth = pair_labels(trace, evolved.index)
            comparison = [
                ("Model lama", old.predict_proba(baseline[RF_FEATURES].to_numpy())[:, order], None),
                ("Model final", final["model"].predict_proba(evolved[final["features"]].to_numpy()),
                 final["sensor_threshold"]),
            ]
            for name, prob, threshold in comparison:
                results.append({"seed": seed, "limpasan_awal": flush, "model": name,
                                **metrics(truth, prob, threshold)})
    result = pd.DataFrame(results)
    result.to_csv(OUT / "challenge_first_flush.csv", index=False)
    print(result.groupby(["model", "limpasan_awal"])[["macro_f1", "f1_hujan", "f1_pembuangan"]]
          .mean().round(3).to_string())


if __name__ == "__main__":
    main()
