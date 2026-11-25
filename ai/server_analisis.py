"""
server_analisis.py
Server Python KALI-Sentinel: subscribe data node lewat MQTT, hitung skor Isolation Forest
dan pola Random Forest, lalu publish ke topik kalisentinel/analisis (format sesuai brief).

Mode:
  python server_analisis.py                       # jalan sungguhan ke EMQX Cloud (butuh: pip install paho-mqtt)
  python server_analisis.py --replay data.csv     # uji offline tanpa broker: putar ulang CSV, cetak hasil
  python server_analisis.py --broker h2117224.ala.us-east-1.emqxsl.com --port 8883 --username USER --password PASS

Model dibaca dari folder models/ (hasil train_model.py).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import deque
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from kalisentinel_core import PARAMS, build_features, decide_status, score_from_raw, to_grid

HERE = Path(__file__).resolve().parent
CFG = json.loads((HERE / "models" / "model_config.json").read_text())
ISO = joblib.load(HERE / "models" / "isolation_forest.joblib")
RF = joblib.load(HERE / "models" / "pattern_rf.joblib")
STEP = CFG["step_s"]                  # analisis selalu di grid 60 detik
KEEP = pd.Timedelta(hours=4)          # panjang buffer per node


class Analyzer:
    def __init__(self, prefix: str = "kalisentinel"):
        self.prefix = prefix
        self.buf = {"HULU": deque(), "HILIR": deque()}
        self.last_minute = None

    def add(self, msg: dict) -> dict | None:
        """Tambah satu pesan node. Mengembalikan pesan analisis bila menit baru selesai."""
        node = str(msg.get("node_id", "")).upper()
        if node not in self.buf:
            return None
        try:
            ts = pd.Timestamp(msg["timestamp"])
        except Exception:
            ts = pd.Timestamp.now(tz="Asia/Jakarta")
        if ts.tzinfo is None:
            ts = ts.tz_localize("Asia/Jakarta")
        row = {"timestamp": ts.isoformat()}
        for p in PARAMS:
            try:
                row[p] = float(msg.get(p))
            except (TypeError, ValueError):
                row[p] = np.nan
        b = self.buf[node]
        b.append(row)
        while b and ts - pd.Timestamp(b[0]["timestamp"]) > KEEP:
            b.popleft()
        minute = ts.floor("60s")
        if node != "HILIR" or minute == self.last_minute:
            return None
        self.last_minute = minute
        return self.analyze()

    def analyze(self) -> dict | None:
        if len(self.buf["HULU"]) < 5 or len(self.buf["HILIR"]) < 5:
            return None
        hu = to_grid(pd.DataFrame(self.buf["HULU"]), STEP)
        hi = to_grid(pd.DataFrame(self.buf["HILIR"]), STEP)
        try:
            f = build_features(hu, hi, STEP, CFG["rules"])
        except Exception:
            return None
        if f.empty:
            return None          # masa pemanasan (butuh ~45 menit data); website memakai aturan cadangan
        r = f.iloc[-1]
        x_if = r[CFG["if_features"]].values.astype(float).reshape(1, -1)
        x_rf = r[CFG["rf_features"]].values.astype(float).reshape(1, -1)
        score = float(score_from_raw(-ISO.score_samples(x_if), CFG["score_c"], CFG["score_k"])[0])
        pat_ml = str(RF.predict(x_rf)[0])
        proba = float(RF.predict_proba(x_rf).max())
        d = decide_status(r, score, CFG["threshold"], None, CFG["rules"])
        if d["status"] in ("AMAN", "INFO") and pat_ml == "sensor_rusak" and proba >= 0.6:
            d["pattern"] = "sensor_perlu_perawatan"
            d["message"] += " Model menduga ada sensor yang perlu dibersihkan atau dikalibrasi."
        return {
            "timestamp": f.index[-1].isoformat(),
            "status": d["status"],
            "anomaly_score": round(score, 3),
            "threshold": CFG["threshold"],
            "A_t": d["A_t"], "N_t": d["N_t"],
            "tau_min": CFG["rules"]["tau_min"],
            "delta": {p: round(float(r[f"d_{p}"]), 2) for p in PARAMS},
            "pattern": d["pattern"],
            "pattern_ml": pat_ml, "pattern_ml_confidence": round(proba, 2),
            "sensor_health": d["sensor_health"],
            "message": d["message"],
        }


def replay(path: str):
    df = pd.read_csv(path)
    an = Analyzer()
    last = None
    t0 = time.time()
    for rec in df.to_dict("records"):
        out = an.add(rec)
        if out and (out["status"], out["pattern"]) != last:
            last = (out["status"], out["pattern"])
            print(f'{out["timestamp"][11:16]}  {out["status"]:8s} skor {out["anomaly_score"]:.2f}  '
                  f'{out["pattern"]:30s} {out["message"]}')
    print(f"selesai dalam {time.time() - t0:.1f} detik")


def load_env(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def run(broker: str, port: int, prefix: str, username: str = "", password: str = "", use_tls: bool | None = None):
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        sys.exit("Pasang dulu: pip install paho-mqtt")
    an = Analyzer(prefix)
    try:  # paho-mqtt 2.x
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"ks-analisis-{int(time.time())}")
    except AttributeError:  # paho-mqtt 1.x
        client = mqtt.Client(client_id=f"ks-analisis-{int(time.time())}")

    if (port in (8883, 8884)) if use_tls is None else use_tls:
        client.tls_set()
    if username:
        client.username_pw_set(username, password)

    def on_connect(c, _u, _f, rc, *_):
        if getattr(rc, "is_failure", False) or (isinstance(rc, int) and rc != 0):
            print(f"koneksi ke {broker}:{port} ditolak ({rc})")
            return
        c.subscribe([(f"{prefix}/node/HULU", 1), (f"{prefix}/node/HILIR", 1)])
        print(f"terhubung ke {broker}:{port}, menunggu data ...")

    def on_message(c, _u, m):
        try:
            msg = json.loads(m.payload.decode())
        except Exception:
            return
        out = an.add(msg)
        if out:
            c.publish(f"{prefix}/analisis", json.dumps(out), qos=1)
            print(out["timestamp"][11:19], out["status"], out["anomaly_score"], out["pattern"])

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(broker, port, keepalive=60)
    client.loop_forever()


if __name__ == "__main__":
    load_env(HERE.parent / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", default=os.environ.get("MQTT_HOST", "h2117224.ala.us-east-1.emqxsl.com"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("MQTT_TLS_PORT", "8883")))
    ap.add_argument("--prefix", default=os.environ.get("MQTT_PREFIX", "kalisentinel"))
    ap.add_argument("--username", default=os.environ.get("MQTT_USERNAME", ""))
    ap.add_argument("--password", default=os.environ.get("MQTT_PASSWORD", ""))
    ap.add_argument("--no-tls", action="store_true", help="nonaktifkan TLS (mis. untuk broker TCP 1883)")
    ap.add_argument("--replay", help="putar ulang CSV tanpa broker")
    a = ap.parse_args()
    replay(a.replay) if a.replay else run(a.broker, a.port, a.prefix, a.username, a.password, False if a.no_tls else None)
