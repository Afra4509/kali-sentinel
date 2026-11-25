"""Tambah variasi gangguan sintetis khusus untuk periode latih."""
import numpy as np
import pandas as pd

from generate_dataset import OUT, PARAMS, build, random_events

START = "2026-11-01T00:00:00"
TRAIN_DAYS = 21


def training_faults(seed):
    rng = np.random.default_rng(seed)
    # Satu slot per hari, terpisah dari kejadian gangguan hari sebelumnya.
    channels = [(node, param) for node in ("HULU", "HILIR") for param in PARAMS]
    slots = [(node, "macet", param) for node, param in channels]
    slots += [(node, mode, param) for node in ("HULU", "HILIR")
              for mode, param in [("putus", "temperature_c"), ("lonjakan", "turbidity_ntu"),
                                  ("drift", "ph")]]
    for day, i in enumerate(rng.permutation(len(slots))):
        node, mode, param = slots[i]
        duration = {"macet": (12, 180), "putus": (3, 25),
                    "lonjakan": (12, 60), "drift": (35, 120)}[mode]
        yield {"type": "sensor_rusak", "node": node, "mode": mode, "param": param,
               "start": day * 1440 + int(rng.integers(360, 1080)),
               "dur": int(rng.integers(*duration)), "amount": float(rng.uniform(0.2, 0.8))}


def main():
    source = OUT / "kalisentinel_training_30hari.csv"
    original = pd.read_csv(source)
    events = random_events(30, np.random.default_rng(2026))
    pd.testing.assert_frame_equal(original, build(30, 60, START, events, seed=7), check_exact=True)
    environment = [event for event in events if event["type"] != "sensor_rusak"]
    clean = build(30, 60, START, environment, seed=7)
    end = 2 * TRAIN_DAYS * 1440
    frames = [original.assign(skenario="asli")]
    for seed in (101, 102, 103):
        variant = build(30, 60, START, [*environment, *training_faults(seed)], seed=7)
        pd.testing.assert_frame_equal(variant.iloc[end:], clean.iloc[end:], check_exact=True)
        frames.append(variant.iloc[:end].assign(skenario=f"gangguan_{seed}"))
    augmented = pd.concat(frames, ignore_index=True)
    augmented.to_csv(source.with_stem(source.stem + "_augmented"), index=False)
    print(augmented.groupby(["skenario", "label"]).size().unstack(fill_value=0).to_string())


if __name__ == "__main__":
    main()
