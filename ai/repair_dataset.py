"""Pulihkan pembacaan dataset sintetis 30 hari menggunakan generator sumbernya."""
import numpy as np
import pandas as pd

from generate_dataset import OUT, PARAMS, build, random_events


def main():
    source = OUT / "kalisentinel_training_30hari.csv"
    target = source.with_stem(source.stem + "_clean")
    raw = pd.read_csv(source)
    events = random_events(30, np.random.default_rng(2026))

    def replay(scenarios):
        return build(30, 60, "2026-11-01T00:00:00", scenarios, seed=7)

    # Validasi asal data hingga nilai setiap sel sebelum memakai referensi sintetis.
    pd.testing.assert_frame_equal(raw, replay(events), check_exact=True)
    reference = replay([e for e in events if e["type"] != "sensor_rusak"])
    keys = ["timestamp", "node_id"]
    pd.testing.assert_frame_equal(raw[keys], reference[keys])
    changed = raw[PARAMS].ne(reference[PARAMS])
    fault = raw.label.eq("sensor_rusak")
    if changed.loc[~fault].any().any():
        raise ValueError("Referensi mengubah pengukuran di luar kejadian kerusakan.")

    # label menggambarkan sinyal bersih, label_asli menyimpan riwayat gangguan.
    clean = reference.assign(label_asli=raw.label)
    clean.to_csv(target, index=False)
    pd.testing.assert_frame_equal(pd.read_csv(target), clean, check_exact=True)
    print(f"{target.name}: {len(clean)} baris, {fault.sum()} baris berlabel sensor_rusak.")
    print(f"{changed.any(axis=1).sum()} baris dipulihkan. Per parameter:")
    print(changed.sum().to_string())


if __name__ == "__main__":
    main()
