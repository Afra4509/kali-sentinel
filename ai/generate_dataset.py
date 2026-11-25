"""
generate_dataset.py
Membuat dataset sintetis KALI-Sentinel yang dikalibrasi ke data terbitan Kali Surabaya.

PENTING: tidak ada data sensor per-menit Kali Surabaya yang terbuka untuk publik.
Dataset ini sintetis, tetapi rentang nilai, siklus harian, dan besaran kejadian
diambil dari sumber di docs/SUMBER_DATA.md. Ganti/tambah dengan data asli sensor
tim begitu tersedia (format kolom sama).

Keluaran (folder data/):
  kalisentinel_training_30hari.csv   data mentah 60 detik, 30 hari, berlabel
  kalisentinel_demo_video_5detik.csv data 5 detik, 2 jam, skenario untuk video & mode DEMO
  kalisentinel_events.csv            daftar kejadian (waktu mulai/selesai, jenis, node)

Jalankan:  python generate_dataset.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent.parent / "data"
OUT.mkdir(exist_ok=True)
PARAMS = ["ph", "temperature_c", "turbidity_ntu", "tds_ppm_est", "water_level_cm"]
WIB = "+07:00"

# --- kalibrasi (lihat docs/SUMBER_DATA.md) -------------------------------------------
BASE_HULU = {"ph": 7.45, "temperature_c": 29.6, "turbidity_ntu": 22.0,
             "tds_ppm_est": 275.0, "water_level_cm": 85.0}
# HILIR = air HULU yang tiba tau menit kemudian + sedikit beban lokal (permukiman)
OFFSET_HILIR = {"ph": -0.08, "temperature_c": 0.25, "turbidity_ntu": 3.0,
                "tds_ppm_est": 18.0, "water_level_cm": -1.2}
NOISE = {"ph": 0.02, "temperature_c": 0.04, "turbidity_ntu": 0.8,
         "tds_ppm_est": 2.0, "water_level_cm": 0.3}
TAU_MIN = 12


def ar1(n: int, sd: float, phi: float, rng) -> np.ndarray:
    """Proses AR(1) untuk drift lambat."""
    e = rng.normal(0, sd * np.sqrt(1 - phi ** 2), n)
    x = np.empty(n)
    x[0] = rng.normal(0, sd)
    for i in range(1, n):
        x[i] = phi * x[i - 1] + e[i]
    return x


def ramp(x: np.ndarray, dur: float) -> np.ndarray:
    y = np.clip(x / max(dur, 1e-9), 0, 1)
    return (1 - np.cos(np.pi * y)) / 2


def river_signal(t_min: np.ndarray, rng) -> dict[str, np.ndarray]:
    """Sinyal sungai di titik HULU (sebelum noise sensor)."""
    n = len(t_min)
    hour = (t_min / 60.0) % 24
    day = t_min / 1440.0
    diurnal = np.sin(2 * np.pi * (hour - 9) / 24)            # puncak sekitar 15.00
    s = {
        "temperature_c": BASE_HULU["temperature_c"] + 0.9 * diurnal + 0.02 * day + ar1(n, 0.3, 0.9995, rng),
        "ph": BASE_HULU["ph"] + 0.12 * diurnal + ar1(n, 0.08, 0.9995, rng),  # fotosintesis siang
        "tds_ppm_est": BASE_HULU["tds_ppm_est"] + ar1(n, 10, 0.9995, rng),
        "turbidity_ntu": BASE_HULU["turbidity_ntu"] * np.exp(ar1(n, 0.18, 0.999, rng)),
        "water_level_cm": BASE_HULU["water_level_cm"] + ar1(n, 3, 0.9997, rng),
    }
    return s


def rain_profile(t_min, start, rise, decay):
    x = t_min - start
    up = ramp(x, rise)
    down = np.where(x > rise, np.exp(-(x - rise) / decay), 1.0)
    return np.where(x < 0, 0.0, up * down)


def apply_rain(sig, t_min, ev, frac=1.0):
    r = rain_profile(t_min, ev["start"], ev["rise"], ev["decay"]) * frac
    sig["turbidity_ntu"] += ev["ntu"] * r
    sig["water_level_cm"] += ev["lvl"] * r
    sig["tds_ppm_est"] *= 1 - ev["dil"] * r
    sig["temperature_c"] -= ev["cool"] * r
    sig["ph"] -= ev["acid"] * r
    return r


def dump_profile(t_min, ev, rng):
    x = t_min - ev["start"]
    up = ramp(x, ev["rise"])
    tail = ev["rise"] + ev["dur"]
    down = 1 - ramp(x - tail, ev["fall"])
    pulse = 1 + 0.12 * np.sin(2 * np.pi * x / rng.uniform(6, 14))   # buangan berdenyut
    return np.where((x < 0) | (x > tail + ev["fall"]), 0.0, up * down * pulse)


def sensorize(sig: dict, rng) -> dict:
    out = {}
    for p in PARAMS:
        v = sig[p] + rng.normal(0, NOISE[p], len(sig[p]))
        if p == "turbidity_ntu":
            v = np.maximum(0, v * (1 + rng.normal(0, 0.02, len(v))))
        out[p] = v
    out["temperature_c"] = np.round(out["temperature_c"] / 0.0625) * 0.0625  # resolusi DS18B20
    out["tds_ppm_est"] = np.clip(np.round(out["tds_ppm_est"]), 0, 1000)      # sensor jenuh 1000
    out["ph"] = np.round(out["ph"], 2)
    out["turbidity_ntu"] = np.round(out["turbidity_ntu"], 1)
    out["water_level_cm"] = np.round(out["water_level_cm"], 1)
    return out


def build(days: float, step_s: int, start: str, events: list[dict], seed: int):
    rng = np.random.default_rng(seed)
    # waktu kejadian ditulis dalam jam keluaran; geser karena ada ekstra tau di depan
    events = [{**e, "start": e["start"] + (TAU_MIN if e["type"] != "sensor_rusak" else 0)} for e in events]
    n = int(days * 86400 / step_s)
    tau_rows = int(TAU_MIN * 60 / step_s)
    t_min = np.arange(n + tau_rows) * step_s / 60.0          # ekstra di depan untuk pergeseran tau
    hulu = river_signal(t_min, rng)
    label_hu = np.full(len(t_min), "normal", dtype=object)
    lab_rain = np.zeros(len(t_min))
    for ev in events:
        if ev["type"] == "hujan":
            r = apply_rain(hulu, t_min, ev)
            lab_rain = np.maximum(lab_rain, r)
    # HILIR menerima air HULU tau menit kemudian
    hilir = {p: np.roll(hulu[p], tau_rows) + OFFSET_HILIR[p] for p in PARAMS}
    for p in PARAMS:
        hilir[p] += ar1(len(t_min), NOISE[p] * 1.5, 0.995, rng)
    lab_rain_hi = np.roll(lab_rain, tau_rows)
    label_hi = np.full(len(t_min), "normal", dtype=object)
    for ev in events:
        if ev["type"] == "hujan":   # limpasan lokal kecil di segmen antara dua node
            r = rain_profile(t_min, ev["start"] + TAU_MIN * 0.6, ev["rise"], ev["decay"]) * 0.15
            hilir["turbidity_ntu"] += ev["ntu"] * r
            hilir["water_level_cm"] += ev["lvl"] * r
    label_hu[lab_rain > 0.08] = "hujan"
    label_hi[lab_rain_hi > 0.08] = "hujan"
    for ev in events:
        if ev["type"] == "pembuangan":
            d = dump_profile(t_min, ev, rng)
            for p, amp in ev["amp"].items():
                hilir[p] += amp * d
            m = d > 0.01
            if m.any():
                last = np.where(m)[0][-1]
                m[last:last + int(10 * 60 / (t_min[1] - t_min[0]) / 60)] = True
            label_hi[m] = "pembuangan"
    # potong bagian awal (dipakai untuk pergeseran)
    sl = slice(tau_rows, None)
    t_min = t_min[sl] - t_min[tau_rows]
    hulu = {p: v[sl] for p, v in hulu.items()}
    hilir = {p: v[sl] for p, v in hilir.items()}
    label_hu, label_hi = label_hu[sl], label_hi[sl]
    hu_s, hi_s = sensorize(hulu, rng), sensorize(hilir, rng)
    # gangguan sensor (setelah noise, karena ini perilaku perangkat)
    for ev in events:
        if ev["type"] != "sensor_rusak":
            continue
        tgt, lab = (hu_s, label_hu) if ev["node"] == "HULU" else (hi_s, label_hi)
        m = (t_min >= ev["start"]) & (t_min < ev["start"] + ev["dur"])
        if not m.any():
            continue
        i0 = np.argmax(m)
        if ev["mode"] == "macet":
            tgt[ev["param"]][m] = tgt[ev["param"]][i0]
        elif ev["mode"] == "putus":
            tgt["temperature_c"][m] = -127.0
        elif ev["mode"] == "lonjakan":
            idx = np.where(m)[0]
            pick = rng.choice(idx, size=max(1, len(idx) // 4), replace=False)
            tgt["turbidity_ntu"][pick] = np.round(rng.uniform(1500, 3000, len(pick)), 1)
        elif ev["mode"] == "drift":
            k = np.cumsum(m) / m.sum()
            tgt["ph"][m] = np.round(tgt["ph"][m] - ev.get("amount", 0.6) * k[m], 2)
        lab[m] = "sensor_rusak"
    ts = pd.Timestamp(start) + pd.to_timedelta(np.round(t_min * 60).astype(np.int64), unit="s")
    tstr = ts.strftime("%Y-%m-%dT%H:%M:%S") + WIB
    rows = []
    for node, s, lab in (("HULU", hu_s, label_hu), ("HILIR", hi_s, label_hi)):
        d = pd.DataFrame({"timestamp": tstr, "node_id": node, **{p: s[p] for p in PARAMS}, "label": lab})
        rows.append(d)
    df = pd.concat(rows).sort_values(["timestamp", "node_id"], kind="stable").reset_index(drop=True)
    return df


def random_events(days: int, rng) -> list[dict]:
    """Kejadian disebar merata per blok 10 hari supaya data latih dan uji sama-sama memuatnya."""
    ev, used = [], []
    blocks = [(b * 10, min(days, (b + 1) * 10)) for b in range((days + 9) // 10)]

    def free_slot(lo, hi, gap):
        for _ in range(500):
            st = float(rng.uniform(lo * 1440 + 120, hi * 1440 - 240))
            if all(abs(st - u) > gap for u in used):
                used.append(st)
                return st
        return float(rng.uniform(lo * 1440 + 120, hi * 1440 - 240))

    for lo, hi in blocks:
        # hujan: musim hujan Nov-Des, cenderung sore
        for d in rng.choice(np.arange(lo, hi), size=3, replace=False):
            start = float(d * 1440 + rng.uniform(13, 19) * 60)
            ev.append({"type": "hujan", "start": start, "rise": float(rng.uniform(20, 45)),
                       "decay": float(rng.uniform(120, 320)), "ntu": float(rng.uniform(120, 520)),
                       "lvl": float(rng.uniform(12, 48)), "dil": float(rng.uniform(0.08, 0.2)),
                       "cool": float(rng.uniform(0.4, 1.2)), "acid": float(rng.uniform(0.08, 0.25))})
        for kind in ["asam", "basa", "ringan", rng.choice(["asam", "basa"])]:
            start = free_slot(lo, hi, 600)
            if kind == "asam":
                amp = {"ph": -rng.uniform(1.4, 2.3), "tds_ppm_est": rng.uniform(380, 720),
                       "turbidity_ntu": rng.uniform(80, 220), "temperature_c": rng.uniform(0.3, 1.5)}
            elif kind == "basa":
                amp = {"ph": rng.uniform(1.8, 2.6), "tds_ppm_est": rng.uniform(320, 700),
                       "turbidity_ntu": rng.uniform(60, 200), "temperature_c": rng.uniform(1.5, 4.5)}
            else:
                amp = {"tds_ppm_est": rng.uniform(110, 230), "turbidity_ntu": rng.uniform(15, 45)}
            ev.append({"type": "pembuangan", "kind": str(kind), "node": "HILIR", "start": start,
                       "rise": float(rng.uniform(3, 8)), "dur": float(rng.uniform(15, 110)),
                       "fall": float(rng.uniform(6, 18)), "amp": {k: float(v) for k, v in amp.items()}})
        faults = [("macet", "ph", "HILIR"), ("macet", rng.choice(["tds_ppm_est", "water_level_cm", "turbidity_ntu"]), str(rng.choice(["HULU", "HILIR"]))),
                  ("putus", "temperature_c", str(rng.choice(["HULU", "HILIR"]))), ("lonjakan", "turbidity_ntu", str(rng.choice(["HULU", "HILIR"]))),
                  ("macet", "ph", "HULU")]
        for mode, p, node in faults:
            start = free_slot(lo, hi, 500)
            dur = {"macet": rng.uniform(40, 180), "putus": rng.uniform(5, 25), "lonjakan": rng.uniform(20, 60)}[mode]
            ev.append({"type": "sensor_rusak", "mode": mode, "param": str(p), "node": node,
                       "start": start, "dur": float(dur)})
    return ev


def main():
    rng = np.random.default_rng(2026)
    days = 30
    events = random_events(days, rng)
    start = "2026-11-01T00:00:00"
    df = build(days, 60, start, events, seed=7)
    df.to_csv(OUT / "kalisentinel_training_30hari.csv", index=False)
    t0 = pd.Timestamp(start)
    ev_rows = []
    for e in events:
        end = e["start"] + e.get("dur", e.get("rise", 0) + 3 * e.get("decay", 0)) + e.get("rise", 0) + e.get("fall", 0)
        ev_rows.append({"mulai": (t0 + pd.Timedelta(minutes=e["start"])).strftime("%Y-%m-%dT%H:%M") + WIB,
                        "selesai_perkiraan": (t0 + pd.Timedelta(minutes=end)).strftime("%Y-%m-%dT%H:%M") + WIB,
                        "jenis": e["type"], "detail": e.get("kind", e.get("mode", "")),
                        "node": e.get("node", "KEDUANYA"), "parameter": json.dumps(e.get("amp", e.get("param", "")))})
    pd.DataFrame(ev_rows).sort_values("mulai").to_csv(OUT / "kalisentinel_events.csv", index=False)

    # --- dataset demo video: 2 jam, 5 detik, skenario berurutan -------------------
    demo_ev = [
        {"type": "hujan", "start": 50.0, "rise": 15.0, "decay": 60.0, "ntu": 260.0, "lvl": 24.0,
         "dil": 0.12, "cool": 0.6, "acid": 0.12},
        {"type": "pembuangan", "kind": "asam", "node": "HILIR", "start": 100.0, "rise": 4.0, "dur": 22.0,
         "fall": 6.0, "amp": {"tds_ppm_est": 620.0, "turbidity_ntu": 170.0, "ph": -1.7, "temperature_c": 0.6}},
        {"type": "sensor_rusak", "mode": "macet", "param": "ph", "node": "HILIR", "start": 145.0, "dur": 25.0},
    ]
    # 09.00 normal · 09.50 hujan · 10.40 pembuangan di hilir · 11.25 sensor pH HILIR macet · selesai 11.50
    demo = build(170.0 / 1440, 5, "2026-12-01T09:00:00", demo_ev, seed=11)
    demo.to_csv(OUT / "kalisentinel_demo_video_5detik.csv", index=False)
    print("training rows:", len(df), "| demo rows:", len(demo))
    print(df.groupby(["node_id", "label"]).size())


if __name__ == "__main__":
    main()
