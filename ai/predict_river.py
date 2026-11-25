"""Replay lokal CSV 5 kanal ESP32 dengan model eksperimen; hasil ke CSV."""
import argparse
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from river_features import features, paired_grid

MODEL = Path(__file__).resolve().parent / "eksperimen_v2" / "model_final.joblib"


def predict(model, raw):
    frame = features(*paired_grid(raw))
    if frame.empty:
        raise ValueError("Rekaman harus memuat lebih dari 42 menit.")
    probability = model["model"].predict_proba(frame[model["features"]].to_numpy(np.float32))
    labels = np.asarray(model["classes"])
    fault = list(labels).index("sensor_rusak")
    threshold = model["sensor_threshold"]
    prediction = probability.argmax(axis=1)
    if threshold is not None:
        other = probability.copy()
        other[:, fault] = -np.inf
        prediction = np.where(probability[:, fault] >= threshold, fault, other.argmax(axis=1))
    output = pd.DataFrame(probability, columns=[f"prob_{label}" for label in labels],
                          index=frame.index.tz_convert("Asia/Jakarta"))
    return output.assign(prediksi=labels[prediction])


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("source", type=Path)
    cli.add_argument("output", type=Path)
    args = cli.parse_args()
    if args.source.resolve() == args.output.resolve():
        cli.error("Output harus berbeda dari sumber.")
    raw = pd.read_csv(args.source)
    model = joblib.load(MODEL)
    if "skenario" in raw:
        result = pd.concat([predict(model, run).assign(skenario=scenario)
                            for scenario, run in raw.groupby("skenario")])
    else:
        result = predict(model, raw)
    result.to_csv(args.output, index_label="timestamp")


if __name__ == "__main__":
    main()
