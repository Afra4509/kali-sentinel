"""
jagakali_core.py
Logika bersama untuk training (train_model.py) dan server analisis (server_analisis.py).

Isi:
  - konstanta parameter, ambang PP 22/2021 kelas II
  - build_features(): mengubah data mentah HULU + HILIR menjadi fitur per waktu HILIR
  - decide_status(): aturan AMAN / WASPADA / BAHAYA / INFO, sama dengan aturan cadangan di website

Semua fungsi kausal: nilai pada waktu t hanya memakai data sampai t.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

PARAMS = ["ph", "temperature_c", "turbidity_ntu", "tds_ppm_est", "water_level_cm"]
SHORT = {"ph": "pH", "temperature_c": "suhu", "turbidity_ntu": "kekeruhan",
         "tds_ppm_est": "TDS", "water_level_cm": "tinggi air"}

# batas bawah simpangan baku agar z-score tidak meledak saat sinyal sangat tenang
FLOOR = {"ph": 0.05, "temperature_c": 0.1, "turbidity_ntu": 2.0,
         "tds_ppm_est": 8.0, "water_level_cm": 0.4}
# skala untuk menormalkan selisih hulu-hilir
DSCALE = {"ph": 0.1, "temperature_c": 0.3, "turbidity_ntu": 15.0,
          "tds_ppm_est": 20.0, "water_level_cm": 2.0}

DEFAULT_CFG = {
    "ph_min": 6.0, "ph_max": 9.0,        # PP 22/2021 Lampiran VI kelas II
    "tds_max": 1000.0,                   # mg/L, kelas II; sensor jenuh di 1000
    "dtemp_max": 3.0,                    # deviasi 3 dari keadaan alamiah
    "tau_min": 12,                       # waktu tempuh HULU -> HILIR (placeholder)
    "sd_k": 3.0,                         # batas simpangan
    "flat_min": 15,                      # nilai identik selama ini = sensor macet
    "dn_min": 2.0,
    "dn_strong": 6.0,
    "sensor_gate": 0.6,                  # keyakinan minimal model pola untuk menandai gangguan sensor                    # selisih hulu-hilir yang dianggap menyimpang walau bertahan lama                       # selisih hulu-hilir minimal (dalam skala DSCALE)
}

IF_FEATURES = [f"ex_{p}" for p in PARAMS] + [f"dn_{p}" for p in PARAMS]
RF_FEATURES = (IF_FEATURES
               + [f"zh_{p}" for p in PARAMS] + [f"zu_{p}" for p in PARAMS]
               + [f"slh_{p}" for p in PARAMS]
               + [f"flath_{p}" for p in PARAMS] + [f"flatu_{p}" for p in PARAMS]
               + [f"spkh_{p}" for p in PARAMS] + [f"spku_{p}" for p in PARAMS]
               + [f"missh_{p}" for p in PARAMS] + [f"missu_{p}" for p in PARAMS]
               + [f"zl_{p}" for p in PARAMS]
               + ["rangebad_h", "rangebad_u"])


def to_grid(df_node: pd.DataFrame, step_s: int) -> pd.DataFrame:
    """Data satu node -> grid waktu teratur (index DatetimeIndex WIB)."""
    d = df_node.copy()
    d["timestamp"] = pd.to_datetime(d["timestamp"], format="ISO8601")
    d = d.set_index("timestamp").sort_index()[PARAMS]
    d = d[~d.index.duplicated(keep="last")]
    full = pd.date_range(d.index[0].floor(f"{step_s}s"), d.index[-1], freq=f"{step_s}s")
    return d.reindex(full, method="nearest", tolerance=pd.Timedelta(seconds=step_s))


def _rows(minutes: float, step_s: int) -> int:
    return max(1, int(round(minutes * 60 / step_s)))


def node_z(s: pd.Series, p: str, step_s: int) -> pd.Series:
    """z-score terhadap rata-rata jendela [t-30, t-3] menit.
    Simpangan baku dihitung robust dari median selisih berurutan, jadi tidak
    membengkak ketika jendela memuat lonjakan."""
    lag, w = _rows(3, step_s), _rows(27, step_s)
    mp = max(3, w // 3)
    mean = s.shift(lag).rolling(w, min_periods=mp).mean()
    sd = s.diff().abs().shift(lag).rolling(w, min_periods=mp).median() * 1.4826 / np.sqrt(2)
    z = (s - mean) / np.maximum(sd.fillna(0), FLOOR[p])
    return z.fillna(0.0)


def flat_minutes(s: pd.Series, step_s: int) -> pd.Series:
    """Berapa menit nilai tidak berubah sama sekali (run-length)."""
    grp = (s != s.shift()).cumsum()
    return s.groupby(grp).cumcount() * step_s / 60.0


def spikes(s: pd.Series, thr: float) -> pd.Series:
    """Puncak terisolasi: sampel sebelumnya melonjak lalu langsung kembali.
    Kenaikan bertahap (buangan, hujan) tidak terhitung."""
    a, b, c = s.shift(2), s.shift(1), s
    up = (b - a > thr) & (b - c > thr)
    dn = (a - b > thr) & (c - b > thr)
    return (up | dn).astype(int)


def _sanitize(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    d.loc[(d.ph < 0) | (d.ph > 14), "ph"] = np.nan
    d.loc[d.temperature_c <= -100, "temperature_c"] = np.nan
    for p in ("turbidity_ntu", "tds_ppm_est", "water_level_cm"):
        d.loc[d[p] < 0, p] = np.nan
    return d


def build_features(hu: pd.DataFrame, hi: pd.DataFrame, step_s: int,
                   cfg: dict | None = None) -> pd.DataFrame:
    """hu, hi: keluaran to_grid() untuk HULU dan HILIR pada grid yang sama."""
    cfg = {**DEFAULT_CFG, **(cfg or {})}
    idx = hi.index.intersection(hu.index)
    hu, hi = hu.loc[idx], hi.loc[idx]
    tau = _rows(cfg["tau_min"], step_s)
    look = _rows(cfg["tau_min"] + 2, step_s)
    f = pd.DataFrame(index=idx)
    f["rangebad_h"] = ((hi.ph < 0) | (hi.ph > 14) | (hi.temperature_c <= -100)).astype(int)
    f["rangebad_u"] = ((hu.ph < 0) | (hu.ph > 14) | (hu.temperature_c <= -100)).astype(int)
    # nilai mustahil secara fisik (DS18B20 -127, pH di luar 0-14, nilai negatif) diperlakukan sebagai data kosong
    hi, hu = _sanitize(hi), _sanitize(hu)
    # filter median-5 kausal: menahan lonjakan satu-dua sampel (gelembung, gangguan kabel)
    hif = hi.rolling(5, min_periods=1).median()
    huf = hu.rolling(5, min_periods=1).median()
    win = _rows(30, step_s)
    for p in PARAMS:
        f[f"spkh_{p}"] = spikes(hi[p], 10 * DSCALE[p]).rolling(win, min_periods=1).sum()
        f[f"spku_{p}"] = spikes(hu[p], 10 * DSCALE[p]).rolling(win, min_periods=1).sum()
    for p in PARAMS:
        # berapa dari 5 sampel terakhir yang kosong (paket hilang / sensor putus)
        f[f"missh_{p}"] = hi[p].isna().astype(int).rolling(5, min_periods=1).sum()
        f[f"missu_{p}"] = hu[p].isna().astype(int).rolling(5, min_periods=1).sum()
    raw_hi, raw_hu = hi, hu
    hi, hu = hif, huf
    for p in PARAMS:
        zh = node_z(hi[p], p, step_s)
        zu = node_z(hu[p], p, step_s)
        # HULU dianggap ikut berubah bila menyimpang searah dalam rentang waktu tempuh
        zu_max = zu.rolling(look, min_periods=1).max()
        zu_min = zu.rolling(look, min_periods=1).min()
        zu_sel = np.where(zh >= 0, zu_max, zu_min)
        ex = np.sign(zh) * np.maximum(0.0, np.abs(zh) - np.maximum(0.0, np.sign(zh) * zu_sel))
        d = hi[p] - hu[p].shift(tau)
        d_med = d.rolling(_rows(24 * 60, step_s), min_periods=_rows(60, step_s)).median()
        f[f"hi_{p}"] = hi[p]
        f[f"hu_{p}"] = hu[p]
        f[f"d_{p}"] = d
        f[f"zh_{p}"] = zh.clip(-60, 60)
        f[f"zu_{p}"] = pd.Series(zu_sel, index=idx).clip(-60, 60)
        dn = ((d - d_med) / DSCALE[p]).clip(-60, 60).fillna(0)
        # lonjakan khusus HILIR hanya dihitung bila selisih hulu-hilir juga tidak biasa;
        # nilai yang kembali normal setelah kejadian (dn kecil) tidak dianggap anomali
        f[f"ex_{p}"] = pd.Series(np.where(dn.abs() > 1.0, ex, 0.0), index=idx).clip(-60, 60)
        f[f"dn_{p}"] = dn
        f[f"slh_{p}"] = (hi[p].diff(_rows(5, step_s)) / DSCALE[p]).clip(-60, 60).fillna(0)
        # HILIR dibanding kebiasaannya sendiri (median 24 jam): memastikan HILIR memang berubah,
        # bukan HULU yang bergeser (misalnya bias sensor HULU)
        hmed = hi[p].rolling(_rows(24 * 60, step_s), min_periods=_rows(60, step_s)).median()
        f[f"zl_{p}"] = ((hi[p] - hmed) / DSCALE[p]).clip(-60, 60).fillna(0)
        f[f"flath_{p}"] = flat_minutes(raw_hi[p], step_s).clip(0, 600)
        f[f"flatu_{p}"] = flat_minutes(raw_hu[p], step_s).clip(0, 600)
    # buang masa pemanasan (jendela belum penuh)
    warm = _rows(30 + cfg["tau_min"], step_s)
    f = f.iloc[warm:]
    # nilai mentah (hi_, hu_, d_) dibiarkan kosong bila memang kosong; fitur model diisi 0
    keep = [c for c in f.columns if c.startswith(("hi_", "hu_", "d_"))]
    rest = [c for c in f.columns if c not in keep]
    f[rest] = f[rest].fillna(0.0)
    return f


def sensor_bad(row: pd.Series, node: str, cfg: dict) -> set[str]:
    """Parameter yang dianggap sensor bermasalah pada satu node."""
    key = "h" if node == "HILIR" else "u"
    raw = "hi" if node == "HILIR" else "hu"
    bad = set()
    for p in PARAMS:
        v = row[f"{raw}_{p}"]
        if not np.isfinite(v) or row[f"miss{key}_{p}"] >= 3 or (p in ("ph", "temperature_c") and row[f"rangebad_{key}"] and row[f"miss{key}_{p}"] >= 1):
            bad.add(p)          # sensor putus / paket hilang beruntun
        elif p == "ph" and (v < 0 or v > 14):
            bad.add(p)
        elif p in ("turbidity_ntu", "tds_ppm_est", "water_level_cm") and v < 0:
            bad.add(p)          # nilai negatif tidak mungkin secara fisik
        elif p == "temperature_c" and v <= -100:
            bad.add(p)
        elif p == "tds_ppm_est" and v >= 1000:
            continue  # jenuh, bukan macet
        elif row[f"flat{key}_{p}"] >= cfg["flat_min"] or row[f"spk{key}_{p}"] >= 3:
            bad.add(p)
    return bad


def decide_status(row: pd.Series, score: float, theta: float, pattern_ml: str | None = None,
                  cfg: dict | None = None, proba_ml: float = 0.0) -> dict:
    """Aturan status. Sama dengan aturan cadangan di website (F1)."""
    cfg = {**DEFAULT_CFG, **(cfg or {})}
    k = cfg["sd_k"]
    bad_h, bad_u = sensor_bad(row, "HILIR", cfg), sensor_bad(row, "HULU", cfg)
    # menyimpang = lonjakan khusus HILIR (ex) DAN selisih hulu-hilir tidak biasa (dn).
    # Syarat dn mencegah alarm saat nilai kembali normal setelah kejadian.
    # Atau: selisih hulu-hilir sangat tidak biasa (dn besar) dan HULU tidak ikut berubah searah,
    # supaya buangan yang berlangsung lama tetap terdeteksi setelah rata-rata 30 menit menyesuaikan.
    dev = [p for p in PARAMS if p not in bad_h and (
        (abs(row[f"ex_{p}"]) > k and abs(row[f"dn_{p}"]) > cfg["dn_min"])
        or (abs(row[f"dn_{p}"]) > cfg["dn_strong"]
            and np.sign(row[f"zl_{p}"]) == np.sign(row[f"dn_{p}"]) and abs(row[f"zl_{p}"]) > cfg["dn_min"]
            and not (np.sign(row[f"zu_{p}"]) == np.sign(row[f"dn_{p}"]) and abs(row[f"zu_{p}"]) > k)))]
    A = []
    for node, raw, bad in (("HULU", "hu", bad_u), ("HILIR", "hi", bad_h)):
        ph = row[f"{raw}_ph"]
        if "ph" not in bad and np.isfinite(ph) and (ph < cfg["ph_min"] or ph > cfg["ph_max"]):
            A.append(("ph", node))
    if "tds_ppm_est" not in bad_h and row["hi_tds_ppm_est"] >= cfg["tds_max"]:
        A.append(("tds_ppm_est", "HILIR"))
    if ("temperature_c" not in bad_h and "temperature_c" not in bad_u and np.isfinite(row["hu_temperature_c"])
            and row["hu_temperature_c"] > -100 and cfg["dtemp_max"] < row["d_temperature_c"] < 20):
        # selisih > 20 °C mustahil di sungai: itu sensor suhu putus (-127) di salah satu node
        A.append(("temperature_c", "HILIR"))
    rain = (row["zh_turbidity_ntu"] > k and row["zu_turbidity_ntu"] > k
            and row["zh_water_level_cm"] > k and row["zu_water_level_cm"] > k)
    # saat pola hujan aktif, kenaikan kekeruhan/tinggi air di HILIR dianggap bagian dari hujan
    if rain and set(dev) <= {"turbidity_ntu", "water_level_cm"}:
        dev = []
    N = len(dev)
    # Model pola yakin ini gangguan sensor, dan yang berubah hanya satu parameter:
    # jangan alarm pencemaran, tandai perlu perawatan. Buangan nyata mengubah beberapa parameter.
    sensor_suspect = (pattern_ml == "sensor_rusak" and proba_ml >= cfg.get("sensor_gate", 0.6)
                      and len(set(dev) | {p for p, _ in A}) <= 1)
    if sensor_suspect:
        dev, A, N = [], [], 0
        score = min(score, theta)
    if A or N >= 2:
        status = "BAHAYA"
    elif N == 1 or (score > theta and not rain):
        status = "WASPADA"
    elif rain:
        status = "INFO"
    else:
        status = "AMAN"

    if status == "INFO":
        pattern = "hujan_limpasan"
        msg = "Kekeruhan dan tinggi air naik di kedua node. Pola mengarah ke hujan atau limpasan, bukan dugaan pembuangan."
    elif status == "BAHAYA" and N >= 2:
        pattern = "anomali_multiparameter_hilir"
        names = [SHORT[p] for p in dev]
        msg = f"{_join(names)} berubah bersamaan hanya di HILIR. Prioritas inspeksi: segmen antara Node HULU dan HILIR."
    elif status == "BAHAYA":
        pattern = "ambang_acuan_terlampaui"
        msg = "Ambang acuan terlampaui: " + ", ".join(f"{SHORT[p]} {n}" for p, n in A) + "."
    elif status == "WASPADA" and N == 1:
        pattern = "perubahan_tunggal_hilir"
        msg = f"{_join([SHORT[dev[0]]])} HILIR menyimpang dari rata-rata 30 menit terakhir, HULU stabil. Pantau perkembangan."
    elif status == "WASPADA":
        pattern = pattern_ml or "skor_anomali_di_atas_ambang"
        msg = "Skor anomali melewati ambang. Pantau perkembangan."
    elif sensor_suspect:
        pattern = "sensor_perlu_perawatan"
        msg = "Perubahan hanya di satu sensor dan polanya mirip gangguan alat. Periksa dan kalibrasi sensor sebelum menyimpulkan."
    else:
        pattern = "normal"
        msg = "Tidak ada penyimpangan."
    health = {"HULU": "ok" if not bad_u else "perlu perawatan: " + ", ".join(SHORT[p] for p in sorted(bad_u)),
              "HILIR": "ok" if not bad_h else "perlu perawatan: " + ", ".join(SHORT[p] for p in sorted(bad_h))}
    return {"status": status, "A_t": int(bool(A)), "N_t": N, "pattern": pattern,
            "message": msg, "sensor_health": health, "params": dev + [p for p, _ in A]}


def _join(a: list[str]) -> str:
    a = list(dict.fromkeys(a))
    s = a[0] if len(a) == 1 else (" dan ".join(a) if len(a) == 2 else ", ".join(a[:-1]) + ", dan " + a[-1])
    return s[0].upper() + s[1:] if not s.startswith("pH") and not s.startswith("TDS") else s


def score_from_raw(raw: np.ndarray, c: float, k: float) -> np.ndarray:
    """Skor Isolation Forest mentah -> 0..1 (0,5 tepat di titik c)."""
    return 1.0 / (1.0 + np.exp(-(raw - c) / k))
