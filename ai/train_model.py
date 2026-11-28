"""
train_model.py
Melatih dua model Jagakali dari SEMUA dataset di folder data/ (lihat datasets.py):

  1. Isolation Forest (tanpa label)  -> skor anomali s_t 0..1
     dilatih hanya pada baris normal + hujan, supaya hujan tidak dianggap anomali.
  2. Random Forest (berlabel)        -> pola: normal / hujan / pembuangan / sensor_rusak.
     Dipakai juga untuk meredam alarm bila yang berubah hanya satu sensor dan polanya mirip gangguan alat.

Pembagian:
  latih = 30 hari (hari 1-21) + augmented gangguan_101..103 + synthetic_v2 split latih & augmentasi
  uji   = 30 hari (hari 22-30) + synthetic_v2 split uji (profil nominal, noise, shift, telemetri, stress)
  Tidak ada run yang sama dipakai di latih dan uji.

Keluaran: models/*.joblib, models/model_config.json, laporan_evaluasi.md
Jalankan:  python train_model.py
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix, precision_recall_curve

from datasets import STEP, all_runs, featurize
from jagakali_core import DEFAULT_CFG, IF_FEATURES, RF_FEATURES, decide_status, score_from_raw

HERE = Path(__file__).resolve().parent
MODELS = HERE / "models"
MODELS.mkdir(exist_ok=True)
LABELS = ["normal", "hujan", "pembuangan", "sensor_rusak"]
STATUSES = ["AMAN", "INFO", "WASPADA", "BAHAYA"]


def statuses(df, score, theta, pred, proba):
    out = [decide_status(r, s, theta, pm, DEFAULT_CFG, pp)
           for (_, r), s, pm, pp in zip(df.iterrows(), score, pred, proba)]
    return [o["status"] for o in out], [o["pattern"] for o in out]


def main():
    t0 = time.time()
    runs = all_runs()
    feats = [featurize(r) for r in runs]
    F = pd.concat(feats)
    tr, te = F[F.split == "latih"], F[F.split == "uji"]
    print(f"{len(runs)} run · latih {len(tr)} baris · uji {len(te)} baris · fitur {time.time()-t0:.0f} dtk")

    # ---------- 1. Isolation Forest ------------------------------------------------
    clean = tr[tr.label.isin(["normal", "hujan"])]
    iso = IsolationForest(n_estimators=300, max_samples=8192, contamination="auto", random_state=42)
    iso.fit(clean[IF_FEATURES].values)
    raw_clean = -iso.score_samples(clean[IF_FEATURES].values)
    c = float(np.quantile(raw_clean, 0.995))
    k = float(max((c - np.quantile(raw_clean, 0.5)) / 4, 1e-4))
    s_tr = score_from_raw(-iso.score_samples(tr[IF_FEATURES].values), c, k)
    m = tr.label.isin(["normal", "hujan", "pembuangan"]).values
    prec, rec, th = precision_recall_curve((tr.label.values[m] == "pembuangan").astype(int), s_tr[m])
    f1 = 2 * prec * rec / np.maximum(prec + rec, 1e-9)
    theta = float(np.clip(th[np.argmax(f1[:-1])], 0.3, 0.9))

    # ---------- 2. Random Forest pola ---------------------------------------------
    rf = RandomForestClassifier(n_estimators=300, max_depth=20, min_samples_leaf=3,
                                class_weight="balanced_subsample", n_jobs=-1, random_state=42)
    rf.fit(tr[RF_FEATURES].values, tr.label.values)

    # ---------- evaluasi ------------------------------------------------------------
    s_te = score_from_raw(-iso.score_samples(te[IF_FEATURES].values), c, k)
    pr = rf.predict_proba(te[RF_FEATURES].values)
    pred = rf.classes_[pr.argmax(1)]
    st, pat = statuses(te, s_te, theta, pred, pr.max(1))
    te = te.assign(score=s_te, pred=pred, status=st, pattern=pat)
    te["alarm"] = te.status.isin(["WASPADA", "BAHAYA"])
    print(f"evaluasi selesai {time.time()-t0:.0f} dtk")

    rep = classification_report(te.label, pred, labels=LABELS, digits=3, zero_division=0)
    cm = pd.DataFrame(confusion_matrix(te.label, pred, labels=LABELS), index=LABELS, columns=LABELS)
    by_prof = te.groupby("profile").apply(lambda g: pd.Series({
        "baris": len(g),
        "buangan tertangkap %": 100 * g[g.env == "pembuangan"].alarm.mean(),
        "buangan jadi BAHAYA %": 100 * (g[g.env == "pembuangan"].status == "BAHAYA").mean(),
        "alarm palsu, sensor sehat %": 100 * g[(g.env != "pembuangan") & (g.gangguan == "")].alarm.mean(),
        "alarm palsu, saat gangguan sensor %": 100 * g[(g.env != "pembuangan") & (g.gangguan != "") | (g.label == "sensor_rusak") & (g.env != "pembuangan")].alarm.mean(),
    }), include_groups=False).round(1)
    fault = te[(te.env != "pembuangan") & (te.gangguan != "")].groupby("gangguan").alarm.mean().mul(100).round(1)
    tab = pd.crosstab(te.label, te.status, normalize="index").mul(100).round(1).reindex(columns=STATUSES, fill_value=0)

    # waktu deteksi per kejadian buangan (semua run uji)
    lat = []
    for run, g in te.groupby("run"):
        ev = (g.env == "pembuangan").astype(int)
        for st_ in g.index[(ev.diff() == 1).values]:
            seg = g.loc[st_: st_ + pd.Timedelta(minutes=180)]
            seg = seg[seg.env == "pembuangan"]
            hit = seg[seg.alarm]
            lat.append((run, (hit.index[0] - st_).total_seconds() / 60 if len(hit) else np.nan))
    lat = pd.DataFrame(lat, columns=["run", "menit"])
    caught = lat.menit.notna().mean() * 100

    joblib.dump(iso, MODELS / "isolation_forest.joblib", compress=3)
    joblib.dump(rf, MODELS / "pattern_rf.joblib", compress=3)
    cfg = {"created": datetime.now().isoformat(timespec="seconds"), "step_s": STEP,
           "if_features": IF_FEATURES, "rf_features": RF_FEATURES, "score_c": c, "score_k": k,
           "threshold": round(theta, 3), "rules": DEFAULT_CFG, "classes": list(rf.classes_),
           "trained_on": sorted({r.source for r in runs}), "train_rows": int(len(tr))}
    (MODELS / "model_config.json").write_text(json.dumps(cfg, indent=2))

    imp = sorted(zip(RF_FEATURES, rf.feature_importances_), key=lambda x: -x[1])[:10]
    L = [
        "# Laporan evaluasi model Jagakali", "",
        f"Dilatih {datetime.now():%d %B %Y %H:%M}. Semua data sintetis yang dikalibrasi; angka ini mengukur logika dan model, bukan kinerja di sungai asli.", "",
        "## Data", "",
        f"- Latih: {len(tr):,} baris (30 hari hari 1–21, tiga run augmented berisi gangguan sensor, synthetic_v2 split latih + augmentasi).",
        f"- Uji: {len(te):,} baris dari run yang tidak pernah dilihat model (30 hari hari 22–30, synthetic_v2 split uji: nominal, noise, shift, telemetri, stress).",
        f"- Ambang skor θ = **{theta:.3f}**.", "",
        "## Ringkasan per profil uji", "", by_prof.to_markdown(), "",
        f"Kejadian buangan yang tertangkap minimal sekali: **{caught:.0f}%** dari {len(lat)} kejadian; median waktu sampai alarm **{lat.menit.median():.0f} menit**.", "",
        "## Alarm palsu per jenis gangguan sensor (sungai sebenarnya normal/hujan)", "", fault.to_frame("alarm %").to_markdown(), "",
        "## Status akhir per label (% baris uji)", "", tab.to_markdown(), "",
        "## Klasifikasi pola (Random Forest)", "", "```", rep, "```", "", cm.to_markdown(), "",
        "## 10 fitur terpenting", "", *[f"- `{n}`: {v:.3f}" for n, v in imp],
    ]
    (HERE / "laporan_evaluasi.md").write_text("\n".join(L), encoding="utf-8")
    te[["run", "profile", "label", "env", "gangguan", "score", "pred", "status", "alarm"]].to_csv(HERE / "hasil_uji.csv.gz")
    print("\n".join(L))


if __name__ == "__main__":
    main()
