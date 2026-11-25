"""
train_model.py
Melatih dua model KALI-Sentinel dari data/kalisentinel_training_30hari.csv:

  1. Isolation Forest (tanpa label)  -> skor anomali s_t 0..1 untuk F5
     dilatih hanya pada data normal + hujan, supaya hujan tidak dianggap anomali.
  2. Random Forest (berlabel)        -> pola: normal / hujan / pembuangan / sensor_rusak

Pembagian waktu: hari 1-21 untuk latih, hari 22-30 untuk uji (tidak diacak, supaya jujur).
Ambang theta dipilih dari data latih, lalu diuji di data uji.

Keluaran:
  models/isolation_forest.joblib, models/pattern_rf.joblib, models/model_config.json
  laporan_evaluasi.md

Jalankan:  python train_model.py  [path_csv_lain]
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix, f1_score, precision_recall_curve

from kalisentinel_core import (DEFAULT_CFG, IF_FEATURES, RF_FEATURES, build_features,
                               decide_status, score_from_raw, to_grid)

HERE = Path(__file__).resolve().parent
DATA = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent / "data" / "kalisentinel_training_30hari.csv"
MODELS = HERE / "models"
MODELS.mkdir(exist_ok=True)
STEP = 60


def load(path: Path):
    raw = pd.read_csv(path)
    raw["timestamp"] = pd.to_datetime(raw["timestamp"], format="ISO8601")
    scenarios = dict(tuple(raw.groupby("skenario", sort=False))) if "skenario" in raw else {"asli": raw}
    source = scenarios.pop("asli")
    split = source.timestamp.min() + pd.Timedelta(days=21)
    features = features_for_scenario(source)
    tr = [features[features.index < split]]
    te = features[features.index >= split]
    for name, variant in scenarios.items():
        if variant.timestamp.max() >= split:
            raise ValueError(f"Skenario {name} mencakup periode uji.")
        extra = features_for_scenario(variant)
        # Tambahkan gangguan dan konteks setelahnya. Segmen normal/hujan yang
        # identik dengan skenario asli tidak perlu dihitung berulang.
        fault = extra.label.eq("sensor_rusak")
        recent_fault = fault.rolling(30, min_periods=1).max().astype(bool)
        tr.append(extra.loc[recent_fault])
    return tr[0], pd.concat(tr), te


def features_for_scenario(raw: pd.DataFrame) -> pd.DataFrame:
    hu = to_grid(raw[raw.node_id == "HULU"], STEP)
    hi = to_grid(raw[raw.node_id == "HILIR"], STEP)
    feats = build_features(hu, hi, STEP)
    lab = {}
    for node in ("HULU", "HILIR"):
        s = raw[raw.node_id == node]
        lab[node] = s.set_index("timestamp")["label"].reindex(feats.index).fillna("normal")
    # label baris fitur: gangguan HILIR diutamakan, lalu sensor di kedua node, lalu hujan
    y = np.where(lab["HILIR"] == "pembuangan", "pembuangan",
         np.where((lab["HILIR"] == "sensor_rusak") | (lab["HULU"] == "sensor_rusak"), "sensor_rusak",
          np.where((lab["HILIR"] == "hujan") | (lab["HULU"] == "hujan"), "hujan", "normal")))
    feats["label"] = y
    return feats


def fit_pattern(training: pd.DataFrame) -> RandomForestClassifier:
    model = RandomForestClassifier(n_estimators=300, max_depth=18, min_samples_leaf=3,
                                   class_weight="balanced_subsample", n_jobs=-1, random_state=42)
    return model.fit(training[RF_FEATURES].values, training.label.values)


def main():
    base, tr, te = load(DATA)
    print(f"latih RF {len(tr)} baris, latih dasar {len(base)} baris, uji {len(te)} baris")
    print(tr.label.value_counts().to_dict(), te.label.value_counts().to_dict())

    # ---------- 1. Isolation Forest -----------------------------------------------
    clean = base[base.label.isin(["normal", "hujan"])]
    iso = IsolationForest(n_estimators=300, max_samples=4096, contamination="auto", random_state=42)
    iso.fit(clean[IF_FEATURES].values)
    raw_tr = -iso.score_samples(base[IF_FEATURES].values)
    raw_clean = -iso.score_samples(clean[IF_FEATURES].values)
    c = float(np.quantile(raw_clean, 0.995))
    k = float(max((c - np.quantile(raw_clean, 0.5)) / 4, 1e-4))
    s_tr = score_from_raw(raw_tr, c, k)
    # theta: F1 terbaik untuk memisahkan pembuangan dari normal+hujan di data latih
    m = base.label.isin(["normal", "hujan", "pembuangan"]).values
    prec, rec, th = precision_recall_curve((base.label.values[m] == "pembuangan").astype(int), s_tr[m])
    f1 = 2 * prec * rec / np.maximum(prec + rec, 1e-9)
    theta = float(np.clip(th[np.argmax(f1[:-1])], 0.3, 0.9))

    # ---------- 2. Random Forest pola ---------------------------------------------
    rf = fit_pattern(tr)

    # ---------- evaluasi di data uji ----------------------------------------------
    s_te = score_from_raw(-iso.score_samples(te[IF_FEATURES].values), c, k)
    pred = rf.predict(te[RF_FEATURES].values)
    rep = classification_report(te.label, pred, digits=3, zero_division=0)
    labels = ["normal", "hujan", "pembuangan", "sensor_rusak"]
    cm = confusion_matrix(te.label, pred, labels=labels)
    statuses = [decide_status(r, s, theta, None)["status"] for (_, r), s in zip(te.iterrows(), s_te)]
    te = te.assign(score=s_te, status=statuses, pred=pred)
    tab = pd.crosstab(te.label, te.status).reindex(columns=["AMAN", "INFO", "WASPADA", "BAHAYA"], fill_value=0)
    pct = (tab.div(tab.sum(axis=1), axis=0) * 100).round(1)

    # waktu deteksi tiap kejadian pembuangan di data uji
    lat = []
    lab_ev = (te.label == "pembuangan").astype(int)
    starts = te.index[(lab_ev.diff() == 1).values]
    for st in starts:
        seg = te.loc[st: st + pd.Timedelta(minutes=120)]
        seg = seg[seg.label == "pembuangan"]
        hit = seg[seg.status.isin(["WASPADA", "BAHAYA"])]
        lat.append((st, (hit.index[0] - st).total_seconds() / 60 if len(hit) else None,
                    bool((seg.status == "BAHAYA").any())))
    auc_like = f1_score((te.label == "pembuangan").astype(int), (s_te > theta).astype(int))

    joblib.dump(iso, MODELS / "isolation_forest.joblib")
    joblib.dump(rf, MODELS / "pattern_rf.joblib")
    cfg = {"created": datetime.now().isoformat(timespec="seconds"), "step_s": STEP,
           "if_features": IF_FEATURES, "rf_features": RF_FEATURES, "score_c": c, "score_k": k,
           "threshold": round(theta, 3), "rules": DEFAULT_CFG, "classes": list(rf.classes_),
           "trained_on": DATA.name}
    (MODELS / "model_config.json").write_text(json.dumps(cfg, indent=2))

    imp = sorted(zip(RF_FEATURES, rf.feature_importances_), key=lambda x: -x[1])[:10]
    lines = [
        "# Laporan evaluasi model KALI-Sentinel", "",
        f"Data latih dari hari 1–21 di `{DATA.name}` ({len(base)} baris dasar, {len(tr)} baris untuk Random Forest).",
        f"Data uji dari skenario asli hari 22–30 ({len(te)} baris). Interval {STEP} detik.",
        "Dataset sintetis terkalibrasi; angka ini mengukur logika dan model, bukan kinerja di sungai asli.", "",
        "## Skor anomali (Isolation Forest)",
        f"- Ambang θ terpilih: **{theta:.3f}** (dipakai sebagai field `threshold`).",
        f"- F1 pembuangan vs lainnya di data uji, memakai s_t > θ saja: **{auc_like:.3f}**.",
        f"- Median skor di data uji: normal {np.median(s_te[te.label=='normal']):.3f}, hujan {np.median(s_te[te.label=='hujan']):.3f}, pembuangan {np.median(s_te[te.label=='pembuangan']):.3f}.", "",
        "## Status akhir per label (persentase baris data uji)", "",
        pct.to_markdown(), "",
        "Yang diharapkan: pembuangan → WASPADA/BAHAYA, hujan → INFO/AMAN, sensor_rusak → bukan BAHAYA.", "",
        "## Waktu deteksi pembuangan (data uji)", "",
        "| Mulai | Menit sampai WASPADA/BAHAYA | Pernah BAHAYA |", "|---|---|---|",
        *[f"| {s:%d/%m %H:%M} | {('%.0f' % l) if l is not None else 'tidak terdeteksi'} | {'ya' if b else 'tidak'} |" for s, l, b in lat], "",
        "## Klasifikasi pola (Random Forest)", "", "```", rep, "```", "",
        "Matriks kebingungan (baris = label asli, kolom = prediksi):", "",
        pd.DataFrame(cm, index=labels, columns=labels).to_markdown(), "",
        "## 10 fitur terpenting", "", *[f"- `{n}`: {v:.3f}" for n, v in imp],
    ]
    (HERE / "laporan_evaluasi.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
