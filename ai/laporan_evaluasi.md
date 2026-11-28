# Laporan evaluasi model Jagakali

Dilatih 25 November 2026 22:33. Semua data sintetis yang dikalibrasi; angka ini mengukur logika dan model, bukan kinerja di sungai asli.

## Data

- Latih: 172,254 baris (30 hari hari 1–21, tiga run augmented berisi gangguan sensor, synthetic_v2 split latih + augmentasi).
- Uji: 70,140 baris dari run yang tidak pernah dilihat model (30 hari hari 22–30, synthetic_v2 split uji: nominal, noise, shift, telemetri, stress).
- Ambang skor θ = **0.795**.

## Ringkasan per profil uji

| profile   |   baris |   buangan tertangkap % |   buangan jadi BAHAYA % |   alarm palsu, sensor sehat % |   alarm palsu, saat gangguan sensor % |
|:----------|--------:|-----------------------:|------------------------:|------------------------------:|--------------------------------------:|
| asli      |   12960 |                   87.7 |                    54.8 |                           0.2 |                                   0.3 |
| noise     |   11436 |                   96.1 |                    81.3 |                           1.7 |                                  14   |
| nominal   |   11436 |                   93.8 |                    62.9 |                           0.2 |                                  11.1 |
| shift     |   11436 |                   95.9 |                    68.1 |                           1.1 |                                  12.7 |
| stress    |   11436 |                   86.5 |                    68.2 |                           1.9 |                                  17   |
| telemetri |   11436 |                   94.9 |                    89   |                           0.4 |                                   3.9 |

Kejadian buangan yang tertangkap minimal sekali: **100%** dari 84 kejadian; median waktu sampai alarm **3 menit**.

## Alarm palsu per jenis gangguan sensor (sungai sebenarnya normal/hujan)

| gangguan   |   alarm % |
|:-----------|----------:|
| bias       |      52.2 |
| drift      |      20   |
| intermiten |       0   |
| macet      |       6.4 |
| putus      |       0.6 |
| spike      |       2.1 |

## Status akhir per label (% baris uji)

| label        |   AMAN |   INFO |   WASPADA |   BAHAYA |
|:-------------|-------:|-------:|----------:|---------:|
| hujan        |   92.8 |    5.1 |       1.9 |      0.2 |
| normal       |   99.7 |    0   |       0.3 |      0   |
| pembuangan   |    6.8 |    0   |      20.3 |     73   |
| sensor_rusak |   83.4 |    2.8 |      11.7 |      2.1 |

## Klasifikasi pola (Random Forest)

```
              precision    recall  f1-score   support

      normal      0.816     0.956     0.880     37747
       hujan      0.776     0.728     0.751     17744
  pembuangan      0.929     0.940     0.935      5506
sensor_rusak      0.862     0.349     0.497      9143

    accuracy                          0.818     70140
   macro avg      0.846     0.743     0.766     70140
weighted avg      0.821     0.818     0.802     70140

```

|              |   normal |   hujan |   pembuangan |   sensor_rusak |
|:-------------|---------:|--------:|-------------:|---------------:|
| normal       |    36068 |    1207 |           68 |            404 |
| hujan        |     4703 |   12925 |           34 |             82 |
| pembuangan   |      229 |      75 |         5178 |             24 |
| sensor_rusak |     3203 |    2457 |          291 |           3192 |

## 10 fitur terpenting

- `zl_tds_ppm_est`: 0.109
- `dn_tds_ppm_est`: 0.099
- `zl_turbidity_ntu`: 0.078
- `dn_turbidity_ntu`: 0.076
- `zu_turbidity_ntu`: 0.068
- `zh_turbidity_ntu`: 0.046
- `zl_water_level_cm`: 0.040
- `dn_temperature_c`: 0.038
- `dn_ph`: 0.036
- `ex_tds_ppm_est`: 0.028