"""
datasets.py
Memuat semua dataset Jagakali sebagai kumpulan "run" (deret waktu tak terputus),
lalu mengubah tiap run menjadi fitur berlabel. Dipakai train_model.py.

Kenapa per run: file augmented dan synthetic_v2 berisi beberapa deret dengan
timestamp yang tumpang tindih atau terpisah. Fitur (rata-rata 30 menit, pergeseran tau)
harus dihitung di dalam satu deret saja, tidak boleh menyeberang antar-run.

Sumber yang dikenali (folder data/):
  jagakali_training_30hari.csv            1 run; hari 1-21 latih, hari 22-30 uji
  jagakali_training_30hari_augmented.csv  run "gangguan_*" (hari 1-21) masuk latih
  jagakali_synthetic_v2.csv.gz            19 run; kolom split = latih / augmentasi / uji
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from jagakali_core import build_features, to_grid

DATA = Path(__file__).resolve().parent.parent / "data"
STEP = 60


@dataclass
class Run:
    source: str
    run_id: str
    split: str          # latih / uji
    profile: str        # nominal, noise, shift, telemetri, stress, gangguan, asli
    raw: pd.DataFrame


def _runs_30hari() -> list[Run]:
    df = pd.read_csv(DATA / "jagakali_training_30hari.csv")
    ts = pd.to_datetime(df.timestamp, format="ISO8601")
    cut = ts.min() + pd.Timedelta(days=21)
    # bagian uji diberi 45 menit data sebelumnya sebagai pemanasan, lalu baris pemanasan dibuang saat evaluasi
    warm = cut - pd.Timedelta(minutes=45)
    return [Run("30hari", "30hari_latih", "latih", "asli", df[ts < cut].copy()),
            Run("30hari", "30hari_uji", "uji", "asli", df[ts >= warm].copy())]


def _runs_augmented() -> list[Run]:
    p = DATA / "jagakali_training_30hari_augmented.csv"
    if not p.exists():
        return []
    df = pd.read_csv(p)
    out = []
    for sk, g in df.groupby("skenario"):
        if sk == "asli":
            continue  # sama dengan file 30 hari, sudah dimuat
        out.append(Run("augmented", sk, "latih", "gangguan", g.drop(columns="skenario")))
    return out


def _runs_v2() -> list[Run]:
    p = DATA / "jagakali_synthetic_v2.csv.gz"
    if not p.exists():
        return []
    df = pd.read_csv(p)
    out = []
    for sk, g in df.groupby("skenario", sort=True):
        split = "uji" if g.split.iloc[0] == "uji" else "latih"   # latih + augmentasi dipakai melatih
        out.append(Run("v2", sk, split, g.profil.iloc[0], g.copy()))
    return out


def all_runs() -> list[Run]:
    return _runs_30hari() + _runs_augmented() + _runs_v2()


def featurize(run: Run, cfg: dict | None = None) -> pd.DataFrame:
    raw = run.raw
    hu = to_grid(raw[raw.node_id == "HULU"], STEP)
    hi = to_grid(raw[raw.node_id == "HILIR"], STEP)
    f = build_features(hu, hi, STEP, cfg)
    lab, env, gang = {}, {}, {}
    for node in ("HULU", "HILIR"):
        s = raw[raw.node_id == node].copy()
        s["timestamp"] = pd.to_datetime(s["timestamp"], format="ISO8601")
        s = s.drop_duplicates("timestamp", keep="last").set_index("timestamp")
        lab[node] = s["label"].reindex(f.index).fillna("normal")
        env[node] = (s["label_lingkungan"] if "label_lingkungan" in s else s["label"]).reindex(f.index).fillna("normal")
        gang[node] = (s["gangguan"] if "gangguan" in s else pd.Series(index=s.index, dtype=object)).reindex(f.index)
    # label baris fitur: buangan di HILIR diutamakan, lalu sensor di salah satu node, lalu hujan
    f["label"] = np.where(lab["HILIR"] == "pembuangan", "pembuangan",
                  np.where((lab["HILIR"] == "sensor_rusak") | (lab["HULU"] == "sensor_rusak"), "sensor_rusak",
                   np.where((lab["HILIR"] == "hujan") | (lab["HULU"] == "hujan"), "hujan", "normal")))
    # label lingkungan: apa yang sebenarnya terjadi di sungai, terlepas dari gangguan sensor
    f["env"] = np.where(env["HILIR"] == "pembuangan", "pembuangan",
                np.where((env["HILIR"] == "hujan") | (env["HULU"] == "hujan"), "hujan", "normal"))
    f["gangguan"] = gang["HILIR"].fillna(gang["HULU"]).fillna("")
    f["run"], f["profile"], f["split"], f["source"] = run.run_id, run.profile, run.split, run.source
    if run.run_id == "30hari_uji":
        cut = pd.to_datetime(run.raw.timestamp, format="ISO8601").min() + pd.Timedelta(minutes=45)
        f = f[f.index >= cut]
    return f
