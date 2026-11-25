# Laporan evaluasi model KALI-Sentinel

Data latih dari hari 1–21 di `kalisentinel_training_30hari_augmented.csv` (30198 baris dasar, 35448 baris untuk Random Forest).
Data uji dari skenario asli hari 22–30 (12960 baris). Interval 60 detik.
Dataset sintetis terkalibrasi; angka ini mengukur logika dan model, bukan kinerja di sungai asli.

## Skor anomali (Isolation Forest)
- Ambang θ terpilih: **0.862** (dipakai sebagai field `threshold`).
- F1 pembuangan vs lainnya di data uji, memakai s_t > θ saja: **0.717**.
- Median skor di data uji: normal 0.019, hujan 0.031, pembuangan 0.968.

## Status akhir per label (persentase baris data uji)

| label        |   AMAN |   INFO |   WASPADA |   BAHAYA |
|:-------------|-------:|-------:|----------:|---------:|
| hujan        |   94.1 |    4.8 |       1.1 |      0   |
| normal       |  100   |    0   |       0   |      0   |
| pembuangan   |   12.6 |    0   |      32.6 |     54.8 |
| sensor_rusak |   92.1 |    7.9 |       0   |      0   |

Yang diharapkan: pembuangan → WASPADA/BAHAYA, hujan → INFO/AMAN, sensor_rusak → bukan BAHAYA.

## Waktu deteksi pembuangan (data uji)

| Mulai | Menit sampai WASPADA/BAHAYA | Pernah BAHAYA |
|---|---|---|
| 23/11 02:07 | 2 | ya |
| 27/11 13:09 | 2 | ya |
| 28/11 14:33 | 3 | tidak |
| 29/11 21:49 | 3 | ya |

## Klasifikasi pola (Random Forest)

```
              precision    recall  f1-score   support

       hujan      0.902     0.676     0.773      2128
      normal      0.932     0.995     0.963     10089
  pembuangan      1.000     0.953     0.976       365
sensor_rusak      0.804     0.521     0.632       378

    accuracy                          0.928     12960
   macro avg      0.910     0.786     0.836     12960
weighted avg      0.925     0.928     0.922     12960

```

Matriks kebingungan (baris = label asli, kolom = prediksi):

|              |   normal |   hujan |   pembuangan |   sensor_rusak |
|:-------------|---------:|--------:|-------------:|---------------:|
| normal       |    10040 |       3 |            0 |             46 |
| hujan        |      688 |    1438 |            0 |              2 |
| pembuangan   |       16 |       1 |          348 |              0 |
| sensor_rusak |       29 |     152 |            0 |            197 |

## 10 fitur terpenting

- `dn_turbidity_ntu`: 0.121
- `zu_turbidity_ntu`: 0.107
- `dn_tds_ppm_est`: 0.107
- `zh_turbidity_ntu`: 0.060
- `zh_tds_ppm_est`: 0.050
- `dn_temperature_c`: 0.047
- `ex_tds_ppm_est`: 0.042
- `slh_tds_ppm_est`: 0.037
- `flath_ph`: 0.034
- `flatu_ph`: 0.033