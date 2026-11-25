"""Fitur yang dapat dihitung dari telemetri hingga menit prediksi."""
import numpy as np
import pandas as pd

from kalisentinel_core import FLOOR, PARAMS, RF_FEATURES, build_features

STEP = 60
HISTORY = 180
SOURCE_COLUMNS = ["timestamp", "node_id", *PARAMS]


def paired_grid(raw):
    data = raw[SOURCE_COLUMNS].copy()
    if not {"HULU", "HILIR"}.issubset(data.node_id):
        raise ValueError("Rekaman harus memuat node HULU dan HILIR.")
    data["timestamp"] = pd.to_datetime(data.timestamp, utc=True, format="ISO8601")
    # Urutkan waktu pembacaan sehingga data terlambat tidak menggantikan nilai lebih baru.
    data = data.sort_values("timestamp", kind="stable")
    data["timestamp"] = data.timestamp.dt.floor("min")
    end = data.timestamp.max()
    grid = pd.date_range(data.timestamp.min(), end, freq="min")
    return [data.loc[data.node_id.eq(node)].drop_duplicates("timestamp", keep="last")
            .set_index("timestamp")[PARAMS].reindex(grid) for node in ("HULU", "HILIR")]


def quality_control(values):
    invalid = values.notna() & ~np.isfinite(values)
    invalid["ph"] |= ~values.ph.between(0, 14) & values.ph.notna()
    invalid["temperature_c"] |= values.temperature_c <= -100
    for p in ("turbidity_ntu", "tds_ppm_est"):
        invalid[p] |= values[p] < 0
    valid = values.mask(invalid)
    filled = valid.ffill(limit=2)
    return filled, invalid, valid.isna() & filled.notna()


def features(hu, hi, clean=True, enhanced=True, historic=False):
    if not clean:
        return build_features(hu, hi, STEP, None if historic else {"baseline_min": HISTORY})[RF_FEATURES]
    hulu, bad_u, _ = quality_control(hu)
    hilir, bad_h, _ = quality_control(hi)
    base = build_features(hulu, hilir, STEP, {"baseline_min": HISTORY})[RF_FEATURES]
    if not enhanced:
        return base
    extra = {}
    for node, values, original, invalid in (("u", hulu, hu, bad_u), ("h", hilir, hi, bad_h)):
        for p in PARAMS:
            signal = values[p]
            history = signal.shift(1).rolling(20, min_periods=4)
            recent = signal.rolling(6, min_periods=3)
            missing = original[p].isna() | invalid[p]
            extra[f"{node}_missing_{p}"] = missing.astype(float)
            extra[f"{node}_invalid_{p}"] = invalid[p].astype(float)
            extra[f"{node}_missing20_{p}"] = missing.rolling(20, min_periods=1).mean()
            extra[f"{node}_roc_{p}"] = signal.diff(1) / FLOOR[p]
            extra[f"{node}_lag15_{p}"] = signal.diff(15) / FLOOR[p]
            extra[f"{node}_mean_shift_{p}"] = (recent.mean() - history.mean()) / FLOOR[p]
            extra[f"{node}_volatility_{p}"] = recent.std() / history.std().clip(lower=FLOOR[p])
            extra[f"{node}_flat_fraction_{p}"] = signal.diff().eq(0).rolling(15, min_periods=1).mean()
        extra[f"{node}_rain_proxy"] = values.turbidity_ntu.diff().rolling(25, min_periods=8).corr(
            values.water_level_cm.diff())
    for p in PARAMS:
        downstream = hilir[p].diff()
        upstream = hulu[p].diff()
        agreement = [downstream.rolling(35, min_periods=10).corr(upstream.shift(lag))
                     for lag in (7, 12, 20, 27)]
        extra[f"upstream_agreement_{p}"] = pd.concat(agreement, axis=1).max(axis=1)
    extra = pd.DataFrame(extra, index=hu.index).loc[base.index]
    return pd.concat([base, extra.replace([np.inf, -np.inf], np.nan).clip(-300, 300).fillna(0)], axis=1)
