"""Visualisasi hasil benchmark sintetis v2."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.ticker import PercentFormatter
from sklearn.inspection import permutation_importance
from sklearn.metrics import (average_precision_score, confusion_matrix, f1_score, precision_recall_curve,
                             roc_auc_score, roc_curve)

from experiment_river import CLASSES, DISCHARGE, FAULT, OUT, classify
from kalisentinel_core import PARAMS

NAMES = ["Normal", "Hujan", "Pembuangan", "Sensor rusak"]
COLORS = ["#456393", "#258880", "#b7663b", "#98568f"]
STYLES = ["-", "--", "-.", ":"]
SENSORS = ["pH", "Suhu (°C)", "Kekeruhan (NTU)", "TDS estimasi (ppm)", "Tinggi air (cm)"]


def confusion_page(y, scores, thresholds):
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), layout="constrained")
    fig.suptitle("Klasifikasi pada skenario uji yang sama")
    for ax, name in zip(axes, ("Model lama", "Model final")):
        matrix = confusion_matrix(y, classify(scores[name], thresholds[name]), labels=range(4))
        rates = matrix / matrix.sum(axis=1, keepdims=True)
        image = ax.imshow(rates, vmin=0, vmax=1, cmap="Blues", aspect="auto")
        for (i, j), count in np.ndenumerate(matrix):
            ax.text(j, i, f"{count:,}\n{rates[i, j]:.1%}", ha="center", va="center",
                    color="white" if rates[i, j] > .6 else "#132840")
        ax.set(title=name, ylabel="Label asli", xlabel="Prediksi", yticks=range(4), yticklabels=NAMES)
        ax.set_xticks(range(4), NAMES, rotation=18, ha="right")
    fig.colorbar(image, ax=axes, format=PercentFormatter(1), label="Proporsi per label asli")
    return fig


def diagnostics_page(y, scores, anomaly):
    fig, (roc, pr, iso) = plt.subplots(1, 3, figsize=(14, 4.2), layout="constrained")
    fig.suptitle("Kurva klasifikasi satu kelas vs kelas lainnya")
    for i, (color, style) in enumerate(zip(COLORS, STYLES)):
        target, probability = y == i, scores["Model final"][:, i]
        fpr, tpr, _ = roc_curve(target, probability)
        precision, recall, _ = precision_recall_curve(target, probability)
        roc.plot(fpr, tpr, color=color, ls=style, label=f"{NAMES[i]} {roc_auc_score(target, probability):.3f}")
        pr.plot(recall, precision, color=color, ls=style,
                label=f"{NAMES[i]} {average_precision_score(target, probability):.3f}")
    target = y == DISCHARGE
    for (name, score), color, style in zip(anomaly.items(), COLORS, STYLES):
        precision, recall, _ = precision_recall_curve(target, score)
        iso.plot(recall, precision, color=color, ls=style,
                 label=f"{name} {average_precision_score(target, score):.3f}")
    iso.axhline(target.mean(), color="#777777", ls=":", label=f"Proporsi kejadian {target.mean():.1%}")
    roc.plot([0, 1], [0, 1], color="#777777", ls=":")
    roc.set(title="ROC · ROC-AUC per kelas", xlabel="False positive rate", ylabel="True positive rate")
    pr.set(title="Model final · average precision", xlabel="Recall", ylabel="Presisi")
    iso.set(title="Isolation Forest · pembuangan", xlabel="Recall", ylabel="Presisi")
    for ax in (roc, pr, iso):
        ax.set(xlim=(0, 1), ylim=(0, 1.02))
        ax.legend(fontsize=8, loc="lower left")
    return fig


def benchmark_page(ablation, robustness):
    fig, (ax, stress) = plt.subplots(1, 2, figsize=(13, 5.1), layout="constrained")
    fig.suptitle("Dampak tiap tahap dan ketahanan model")
    x = np.arange(len(ablation))
    for i, (col, name) in enumerate((("macro_f1", "Macro F1"), ("presisi_sensor", "Presisi sensor"),
                                      ("recall_sensor", "Recall sensor"))):
        ax.plot(x, ablation[col], marker=("o", "s", "^")[i], color=COLORS[i], label=name)
    ax.set_xticks(x, ablation.index, rotation=32, ha="right")
    ax.set(title="Ablasi pada uji independen", ylim=(0, 1.05), ylabel="Skor")
    subset = robustness[robustness.tingkat.eq("profil")].pivot(index="grup", columns="model", values="macro_f1")
    for i, name in enumerate(("Model lama", "Baseline v2", "Model final")):
        bars = stress.bar(np.arange(len(subset)) + (i - 1) * .25, subset[name], width=.23,
                          color=COLORS[i], label=name)
        stress.bar_label(bars, fmt="%.2f", fontsize=7, padding=2)
    stress.set_xticks(np.arange(len(subset)), subset.index, rotation=20, ha="right")
    stress.set(title="Macro F1 menurut profil uji", ylim=(0, 1.13), ylabel="Macro F1")
    for panel in (ax, stress):
        panel.grid(axis="y", alpha=.18)
        panel.legend(loc="lower right", fontsize=8)
    return fig


def distribution_page(raw):
    fig, axes = plt.subplots(2, 3, figsize=(13, 7), layout="constrained")
    fig.suptitle("Distribusi antarskenario uji · pembacaan referensi sintetis")
    test = raw[raw.split.eq("uji")]
    groups = list(test.groupby("profil"))
    for ax, param, name in zip(axes.flat, PARAMS, SENSORS):
        ax.boxplot([group[f"ref_{param}"].to_numpy() for _, group in groups],
                   showfliers=False, whis=(5, 95), tick_labels=[key for key, _ in groups], orientation="horizontal")
        ax.set(xlabel=name, title="Median, kuartil, persentil 5–95")
    axes.flat[-1].set_visible(False)
    return fig


def fault_page(raw):
    fig, axes = plt.subplots(2, 2, figsize=(12, 7), layout="constrained")
    fig.suptitle("Anomali sensor pada skenario uji")
    test = raw[raw.split.eq("uji")]
    for ax, mode in zip(axes.flat, ("macet", "putus", "spike", "drift")):
        event = test.loc[test.gangguan.eq(mode)].iloc[0]
        series = test[test.skenario.eq(event.skenario) & test.node_id.eq(event.node_id)]
        offset = (series.timestamp - event.timestamp).dt.total_seconds() / 60
        local = offset.between(-35, 170)
        p = event.kanal_gangguan
        ax.plot(offset[local], series.loc[local, f"ref_{p}"], color=COLORS[1], label="Referensi")
        ax.plot(offset[local], series.loc[local, p], color=COLORS[2], ls="--", label="Observasi")
        missing = local & series[p].isna()
        if missing.any():
            ax.scatter(offset[missing], np.full(missing.sum(), .06), transform=ax.get_xaxis_transform(),
                       marker="|", color=COLORS[3], label="Data hilang")
        ax.axvline(0, color="#666666", linewidth=1, linestyle=":")
        ax.set(title=f"{mode.title()} · {event.node_id} · {event.skenario}",
               xlabel="Menit sejak awal gangguan", ylabel=SENSORS[PARAMS.index(p)])
        ax.legend(fontsize=8)
    return fig


def importance_page(model, x, y, columns, threshold):
    fig, (ax, sx) = plt.subplots(1, 2, figsize=(13, 5.3), layout="constrained")
    fig.suptitle("Fitur yang berpengaruh pada prediksi")
    rng = np.random.default_rng(42)
    rows = rng.choice(len(x), size=min(2400, len(x)), replace=False)
    def score(estimator, samples, truth):
        return f1_score(truth, classify(estimator.predict_proba(samples), threshold), average="macro")

    imp = permutation_importance(model, x[rows], y[rows], scoring=score, n_repeats=3,
                                 random_state=42)
    idx = imp.importances_mean.argsort()[-12:]
    ax.barh(np.array(columns)[idx], imp.importances_mean[idx], xerr=imp.importances_std[idx],
            color=COLORS[0])
    ax.set(title="Permutation importance pada uji", xlabel="Penurunan Macro F1")
    try:
        import shap
        values = shap.TreeExplainer(model)(x[rows[:180]], check_additivity=False).values
        importance = np.abs(values[:, :, FAULT]).mean(axis=0)
    except (ImportError, ValueError, TypeError, AttributeError, NotImplementedError) as exc:
        reason = f"SHAP tidak tersedia untuk model ini ({type(exc).__name__})."
        sx.text(.5, .5, reason, ha="center", va="center", wrap=True)
        sx.set_axis_off()
        (OUT / "shap_status.txt").write_text(f"{reason}\n{exc}", encoding="utf-8")
    else:
        idx = importance.argsort()[-12:]
        sx.barh(np.array(columns)[idx], importance[idx], color=COLORS[1])
        sx.set(title="Tree SHAP · kelas sensor rusak", xlabel="Rata-rata nilai absolut SHAP")
        (OUT / "shap_status.txt").write_text("Tree SHAP pada 180 sampel uji.", encoding="utf-8")
    return fig


def render(raw, y, scores, thresholds, anomaly, robustness, ablation, model, x, columns):
    plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False, "pdf.fonttype": 42})
    figures = {
        "heatmap": confusion_page(y, scores, thresholds),
        "ablasi_dan_robustness": benchmark_page(ablation, robustness),
        "roc_pr": diagnostics_page(y, scores, anomaly),
        "distribusi": distribution_page(raw),
        "gangguan_sensor": fault_page(raw),
        "feature_importance": importance_page(model, x, y, columns, thresholds["Model final"]),
    }
    with PdfPages(OUT / "laporan_visual_v2.pdf") as pdf:
        for name, fig in figures.items():
            fig.savefig(OUT / f"{name}.png", dpi=170)
            pdf.savefig(fig)
            plt.close(fig)
