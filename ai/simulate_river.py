"""Simulasi skenario independen dengan rekaman observasi dan referensi per kanal."""
from pathlib import Path

import numpy as np
import pandas as pd

from generate_dataset import NOISE, OFFSET_HILIR, PARAMS, ar1, rain_profile, river_signal

DATA = Path(__file__).resolve().parent.parent / "data"
DATASET = DATA / "kalisentinel_synthetic_v2.csv.gz"
MINUTES = 4 * 1440
# Faktor noise, perubahan lingkungan, dan tekanan telemetri.
PROFILES = {"nominal": (1.0, 0.0, 1), "noise": (3.0, 0.0, 1),
            "shift": (1.0, 1.0, 1), "telemetri": (1.0, 0.0, 3),
            "stress": (3.0, 1.0, 3)}
RESOLUTION = np.array([0.01, 0.0625, 0.1, 1, 0.1])
MODES = ("macet", "putus", "spike", "drift", "intermiten", "bias")


def simulate(seed, start, profile, first_flush=False):
    weather, device = [np.random.default_rng(s) for s in np.random.SeedSequence(seed).spawn(2)]
    noise, shift, loss = PROFILES[profile]
    lag = int(weather.integers(7, 20) + 8 * shift)
    t = np.arange(-lag, MINUTES)
    latent = river_signal(t, weather)
    latent["temperature_c"] += weather.uniform(-0.6, 0.6) - 1.4 * shift
    latent["ph"] += weather.uniform(-0.3, 0.3) - 0.2 * shift
    latent["tds_ppm_est"] *= weather.uniform(0.75, 1.25) * (1 + 0.22 * shift)
    latent["turbidity_ntu"] *= weather.uniform(0.75, 1.45) * (1 + 0.65 * shift)
    latent["water_level_cm"] += weather.uniform(-14, 14) + 11 * shift

    storm = np.zeros(t.size)
    sediment = np.zeros(t.size)
    for day in range(4):
        if weather.random() < 0.18:
            continue
        onset = day * 1440 + weather.integers(280, 1150)
        peak = weather.uniform(0.35, 1.65) * (1 + 0.35 * shift)
        storm += peak * rain_profile(t, onset, weather.uniform(25, 95), weather.uniform(100, 340))
        sediment += peak * rain_profile(t, onset, weather.uniform(10, 45), weather.uniform(60, 250))
    latent["water_level_cm"] += weather.uniform(12, 37) * storm
    latent["turbidity_ntu"] += weather.uniform(120, 410) * sediment
    latent["temperature_c"] -= weather.uniform(0.3, 1.4) * storm
    # Campuran sederhana air sungai dan limpasan, dengan fraksi dari respons hidrologi.
    fraction = np.minimum(0.45, 0.2 * storm)
    latent["tds_ppm_est"] *= (1 - 0.8 * fraction)
    latent["ph"] = -np.log10((1 - fraction) * 10 ** -latent["ph"] + fraction * 10 ** -6.9)

    hulu = np.column_stack([latent[p][lag:] for p in PARAMS])
    hilir = np.column_stack([latent[p][:-lag] + OFFSET_HILIR[p] for p in PARAMS])
    # Limpasan lokal menambah sedimen dan muka air sebelum gelombang HULU tiba.
    hilir[:, 2] += 19 * sediment[lag:]
    hilir[:, 4] += 3 * storm[lag:]
    env = [np.where(s > 0.10, "hujan", "normal").astype(object)
           for s in (storm[lag:], np.maximum(storm[:-lag], 0.2 * storm[lag:]))]
    if first_flush:
        # Skenario eksternal: respons awal limpasan lokal kaya sedimen dan ion.
        pulse = np.maximum(0, pd.Series(sediment[lag:]).diff(6).fillna(0).to_numpy())
        hilir[:, 2] += 390 * pulse
        hilir[:, 3] += 520 * pulse
        hilir[:, 4] += 25 * pulse
        env[1][pulse > 0.035] = "hujan"
    for day in range(4):
        for hour in (5, 15):
            start_minute = day * 1440 + hour * 60 + weather.integers(-100, 101)
            duration = weather.integers(20, 125)
            elapsed = np.arange(MINUTES) - start_minute
            rise = np.clip(elapsed / weather.uniform(4, 22), 0, 1)
            fall = np.clip((duration - elapsed) / weather.uniform(8, 30), 0, 1)
            plume = rise * fall * weather.uniform(0.32, 1.0)
            plume_ph = weather.choice([5.4, 6.2, 7.1, 8.8, 10.4])
            hilir[:, 0] = -np.log10((1 - plume) * 10 ** -hilir[:, 0] + plume * 10 ** -plume_ph)
            hilir[:, 1] += plume * weather.uniform(-1.2, 3.0)
            hilir[:, 2] += plume * weather.uniform(5, 390)
            hilir[:, 3] += plume * weather.uniform(40, 810)
            env[1][plume > 0.03] = "pembuangan"

    timestamps = pd.date_range(start, periods=MINUTES, freq="min", tz="Asia/Jakarta")
    frames = []
    for node, water, labels in zip(("HULU", "HILIR"), (hulu, hilir), env):
        base_noise = np.array([NOISE[p] for p in PARAMS])
        scale = np.tile(base_noise, (MINUTES, 1))
        scale[:, 2] += 0.018 * water[:, 2]
        ref = water + device.normal(0, scale * noise)
        ref += np.column_stack([ar1(MINUTES, sd * 1.5, 0.995, device) for sd in base_noise])
        ref += device.normal(0, base_noise * 1.5)
        ref = np.round(ref / RESOLUTION) * RESOLUTION
        ref[:, 2:] = np.maximum(0, ref[:, 2:])
        ref[:, 3] = np.minimum(1000, ref[:, 3])
        observed = ref.copy()
        fault = np.full(MINUTES, "", dtype=object)
        channel = fault.copy()
        for k, mode in enumerate(device.permutation(MODES)):
            offset = int(k * MINUTES / len(MODES) + device.integers(80, 550))
            span = int(device.integers(18, 150))
            j = PARAMS.index("turbidity_ntu") if mode == "spike" else int(device.integers(len(PARAMS)))
            window = slice(offset, offset + span)
            fault[window], channel[window] = mode, PARAMS[j]
            vals = observed[window, j]
            amplitude = device.uniform(1, 4) * [0.24, 0.5, 32, 40, 8][j]
            if mode == "macet":
                vals[:] = vals[0]
            elif mode == "putus":
                vals[:] = -127 if j == 1 else np.nan
            elif mode == "spike":
                hits = device.random(span) < 0.17
                hits[0] = True
                vals[hits] += device.lognormal(np.log(180), 0.8, hits.sum())
            elif mode == "intermiten":
                vals[np.arange(span) % (2 * loss + 2) < loss + 1] = np.nan
            elif mode == "drift":
                vals[:] += device.choice([-1, 1]) * amplitude * np.linspace(0, 1, span)
            else:
                vals[:] += device.choice([-1, 1]) * amplitude
        # Kehilangan paket sporadis dibedakan dari kerusakan kanal.
        packet_missing = device.random(MINUTES) < 0.0015 * loss
        for day in range(4):
            offset = day * 1440 + device.integers(100, 1250)
            packet_missing[offset:offset + int(device.integers(1, 4) * loss)] = True
        observed[packet_missing] = np.nan
        frame = pd.DataFrame(observed, columns=PARAMS)
        frame.insert(0, "node_id", node)
        frame.insert(0, "timestamp", timestamps)
        frame["label"] = np.where(fault != "", "sensor_rusak", labels)
        frame["label_lingkungan"] = labels
        frame["gangguan"] = fault
        frame["kanal_gangguan"] = channel
        frame["paket_hilang"] = packet_missing
        for j, p in enumerate(PARAMS):
            frame[f"ref_{p}"] = ref[:, j]
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def main():
    design = [("latih", p) for p in ("nominal", "nominal", "noise", "nominal", "noise", "nominal")]
    design += [("augmentasi", p) for p in ("shift", "telemetri", "stress")]
    design += [("uji", p) for p in PROFILES for _ in range(2)]
    runs = []
    for i, (partition, profile) in enumerate(design):
        seed = 4101 + i
        start = pd.Timestamp("2026-01-01") + pd.Timedelta(days=4 * i)
        frame = simulate(seed, start, profile)
        runs.append(frame.assign(skenario=f"run_{seed}", profil=profile, split=partition, seed=seed))
    pd.concat(runs, ignore_index=True).to_csv(DATASET, index=False, compression={"method": "gzip", "mtime": 0})
    print(f"{len(runs)} skenario tersimpan di {DATASET}")


if __name__ == "__main__":
    main()
