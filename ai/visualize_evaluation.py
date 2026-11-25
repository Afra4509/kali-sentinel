"""Buat laporan visual dari model tersimpan dan dataset KALI-Sentinel."""
import json
from pathlib import Path

import joblib
import matplotlib
import numpy as np
import pandas as pd
from sklearn.metrics import (accuracy_score, average_precision_score, confusion_matrix,
                             f1_score, precision_recall_curve, precision_score, recall_score)

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.ticker import PercentFormatter

from kalisentinel_core import PARAMS, score_from_raw
from train_model import fit_pattern, load

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
OUT = HERE / "visualisasi"
LABELS = ["normal", "hujan", "pembuangan", "sensor_rusak"]
NAMES = ["Normal", "Hujan", "Pembuangan", "Sensor rusak"]
SENSORS = ["pH", "Suhu", "Kekeruhan", "TDS", "Tinggi air"]
UNITS = ["pH", "°C", "NTU", "ppm", "cm"]
BLUE, TEAL, RED = "#395d9c", "#087f78", "#b64936"


def figure(title, subtitle, rows=1, columns=2, height=5):
    fig, axes = plt.subplots(rows, columns, figsize=(11.7, height), layout="constrained")
    fig.suptitle(title + "\n" + subtitle, x=0.02, ha="left", fontsize=15, linespacing=1.55)
    return fig, axes


def heatmap(ax, values, annotations, rows, columns, vmax, cmap):
    image = ax.imshow(values, cmap=cmap, vmin=0, vmax=vmax, aspect="auto")
    ax.set_xticks(range(len(columns)), columns, rotation=18, ha="right")
    ax.set_yticks(range(len(rows)), rows)
    for (i, j), value in np.ndenumerate(values):
        ax.text(j, i, annotations[i, j], ha="center", va="center", fontsize=9,
                color="white" if value > vmax * 0.6 else "#172b42")
    return image


def confusion_figure(labels, predictions):
    fig, axes = figure("Kelas mana yang sering tertukar?",
                       f"Uji sintetis hari 22–30 · {len(labels):,} sampel · Persentase per label asli", height=5.5)
    for ax, (name, pred) in zip(axes, predictions.items()):
        counts = confusion_matrix(labels, pred, labels=LABELS)
        rates = counts / counts.sum(axis=1, keepdims=True)
        notes = np.array([f"{n:,}\n{r:.1%}" for n, r in zip(counts.flat, rates.flat)]).reshape(counts.shape)
        image = heatmap(ax, rates, notes, NAMES, NAMES, 1, "Blues")
        ax.set(title=name, xlabel="Prediksi Random Forest", ylabel="Label asli")
    fig.colorbar(image, ax=axes, format=PercentFormatter(1), shrink=0.85)
    return fig


def performance_figure(labels, predictions, scores, threshold):
    fig, (ax, pr) = figure("Perubahan kinerja setelah augmentasi",
                           "Kedua model Random Forest dievaluasi pada sampel uji yang sama", height=5.5)
    metric_names = ["Akurasi", "Macro F1", "F1 hujan", "F1 pembuangan",
                    "Recall sensor rusak", "Presisi sensor rusak"]
    positions = np.arange(len(metric_names))
    for (name, pred), offset, color in zip(predictions.items(), (-0.18, 0.18), (BLUE, TEAL)):
        f1 = f1_score(labels, pred, labels=LABELS, average=None, zero_division=0)
        binary_true, binary_pred = labels == "sensor_rusak", pred == "sensor_rusak"
        values = [accuracy_score(labels, pred), f1.mean(), f1[1], f1[2],
                  recall_score(binary_true, binary_pred, zero_division=0),
                  precision_score(binary_true, binary_pred, zero_division=0)]
        bars = ax.barh(positions + offset, values, height=0.31, label=name, color=color)
        ax.bar_label(bars, labels=[f"{v:.1%}" for v in values], padding=3, fontsize=8)
    ax.set(yticks=positions, yticklabels=metric_names, xlim=(0, 1.15), title="Metrik Random Forest")
    ax.set_xticks(np.linspace(0, 1, 6))
    ax.xaxis.set_major_formatter(PercentFormatter(1))
    ax.invert_yaxis()
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncols=2)

    positive = labels == "pembuangan"
    precision, recall, _ = precision_recall_curve(positive, scores)
    ap = average_precision_score(positive, scores)
    pr.step(recall, precision, where="post", color=TEAL, label=f"Average precision {ap:.3f}")
    pr.axhline(positive.mean(), color=BLUE, linestyle=":", label=f"Proporsi pembuangan {positive.mean():.1%}")
    flagged = scores > threshold
    pr.scatter(recall_score(positive, flagged), precision_score(positive, flagged, zero_division=0),
               color=RED, zorder=3, label=f"Ambang operasional {threshold:.3f}")
    pr.set(title="Isolation Forest · deteksi pembuangan", xlabel="Recall", ylabel="Presisi",
           xlim=(0, 1.02), ylim=(0, 1.05))
    pr.legend(loc="upper right", fontsize=8)
    return fig


def dataset_figure(base, augmented, changed, raw):
    fig, (ax, repairs) = figure("Komposisi data latih dan hasil cleaning",
                                "Kiri menunjukkan sampel fitur latih RF. Kanan menunjukkan sel sensor yang dipulihkan.",
                                height=5.1)
    positions = np.arange(len(NAMES))
    for frame, name, offset, color in ((base, "Data asli", -0.19, BLUE),
                                      (augmented, "Dengan augmentasi", 0.19, TEAL)):
        counts = frame.label.value_counts().reindex(LABELS, fill_value=0)
        bars = ax.barh(positions + offset, counts, height=0.33, label=name, color=color)
        ax.bar_label(bars, labels=[f"{n:,}" for n in counts], padding=3, fontsize=8)
    ax.set(title="Sampel latih per kelas", xlabel="Jumlah sampel", yticks=positions, yticklabels=NAMES,
           xlim=(0, augmented.label.value_counts().max() * 1.25))
    ax.invert_yaxis()
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncols=2)
    nodes = ["HULU", "HILIR"]
    counts = changed.groupby(raw.node_id).sum().loc[nodes].to_numpy()
    heatmap(repairs, counts, counts, nodes, SENSORS, counts.max(), "GnBu")
    repairs.set(title=f"Perbaikan sensor · {changed.any(axis=1).sum():,} baris berubah", xlabel="Parameter")
    return fig


def cleaning_figure(raw, clean, changed):
    fig, axes = figure("Pembacaan sebelum dan sesudah cleaning",
                       "Empat contoh berpusat pada koreksi terbesar setiap parameter", rows=2, height=7)
    timestamps = pd.to_datetime(raw.timestamp, format="ISO8601")
    params = [(p, name, unit) for p, name, unit in zip(PARAMS, SENSORS, UNITS) if changed[p].any()]
    for ax, (param, name, unit) in zip(axes.flat, params):
        center = (raw[param] - clean[param]).abs().idxmax()
        node, time = raw.node_id[center], timestamps[center]
        window = (raw.node_id == node) & ((timestamps - time).abs() <= pd.Timedelta(minutes=45))
        ax.plot(timestamps[window], raw.loc[window, param], color=RED, linewidth=1.2, label="Pembacaan asli")
        ax.plot(timestamps[window], clean.loc[window, param], color=TEAL, linewidth=1.6, label="Setelah cleaning")
        ax.set(title=f"{name} · {node} · {time:%d/%m/%Y}", xlabel="Waktu (WIB)", ylabel=unit)
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=3, maxticks=6, tz=time.tz))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=time.tz))
        ax.legend(loc="best", fontsize=8)
    return fig


def main():
    plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False,
                         "axes.titleweight": "bold", "axes.labelcolor": "#172b42",
                         "font.family": "DejaVu Sans", "pdf.fonttype": 42})
    models = HERE / "models"
    cfg = json.loads((models / "model_config.json").read_text(encoding="utf-8"))
    source = DATA / "kalisentinel_training_30hari.csv"
    base, _, baseline_test = load(source)
    _, augmented, test = load(DATA / "kalisentinel_training_30hari_augmented.csv")
    pd.testing.assert_frame_equal(baseline_test, test)
    if cfg["trained_on"] != "kalisentinel_training_30hari_augmented.csv":
        raise ValueError("Model tersimpan harus dilatih dengan dataset augmented.")

    rf_input = test[cfg["rf_features"]].to_numpy()
    predictions = {"Data asli": fit_pattern(base).predict(rf_input),
                   "Dengan augmentasi": joblib.load(models / "pattern_rf.joblib").predict(rf_input)}
    iso = joblib.load(models / "isolation_forest.joblib")
    scores = score_from_raw(-iso.score_samples(test[cfg["if_features"]].to_numpy()),
                            cfg["score_c"], cfg["score_k"])
    raw = pd.read_csv(source)
    clean = pd.read_csv(source.with_stem(source.stem + "_clean"))
    keys = ["timestamp", "node_id"]
    pd.testing.assert_frame_equal(raw[keys], clean[keys])
    changed = raw[PARAMS].ne(clean[PARAMS])

    OUT.mkdir(exist_ok=True)
    figures = {
        "heatmap_klasifikasi": confusion_figure(test.label, predictions),
        "kinerja_model": performance_figure(test.label, predictions, scores, cfg["threshold"]),
        "komposisi_dan_perbaikan": dataset_figure(base, augmented, changed, raw),
        "contoh_cleaning": cleaning_figure(raw, clean, changed),
    }
    with PdfPages(OUT / "laporan_visual.pdf") as pdf:
        for name, fig in figures.items():
            fig.savefig(OUT / f"{name}.png", dpi=180, facecolor="white")
            pdf.savefig(fig, facecolor="white")
            plt.close(fig)
    print(f"{len(figures)} grafik dan PDF tersimpan di {OUT}")


if __name__ == "__main__":
    main()
