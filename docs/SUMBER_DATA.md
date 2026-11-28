# Sumber data dan dasar kalibrasi

## Kenapa datasetnya sintetis

Tidak ada data sensor per menit Kali Surabaya yang terbuka untuk publik. Yang tersedia adalah hasil sampling penelitian (beberapa titik, beberapa hari) dan berita kejadian. Jadi dataset di folder `data/` dibuat oleh `ai/generate_dataset.py`, lalu **rentang nilai, siklus harian, dan besaran kejadiannya dikalibrasi ke sumber di bawah**. Begitu sensor tim merekam data asli, simpan dengan kolom yang sama dan latih ulang (`python train_model.py data_asli.csv`).

Sampaikan ini apa adanya ke juri: model dilatih pada data sintetis terkalibrasi, bukan data lapangan.

## Nilai acuan yang dipakai

| Parameter | Nilai normal di dataset | Dasar |
|---|---|---|
| pH | rata-rata HULU 7,48, HILIR 7,41 (sekitar 7,1–7,8); siklus harian ±0,12 (fotosintesis siang) | Kali Surabaya, 5 titik DAM Rolag–intake IPAM Karangpilang, Juni 2026: pH 7,65–8,15 (Jurnal Rekayasa Teknik Sipil dan Lingkungan, UKI, 2026). Sungai Jagir Des 2022–Nov 2023: pH 6,70–7,38, lebih rendah di musim hujan (Envirotek UPN Jatim). Dataset memakai nilai tengah karena simulasinya November (awal musim hujan). |
| Suhu | 28–31,5 °C, siklus harian ±0,9 °C, puncak sekitar 15.00 | Kali Surabaya 28,75–32,25 °C (UKI 2026); Jagir 28,9–34,3 °C (Envirotek). |
| TDS | HULU sekitar 276 ppm, HILIR sekitar 294 ppm | Jagir 270–310 ppm sepanjang tahun, beda musim kecil (Envirotek). |
| Kekeruhan | 12–69 NTU saat normal | Air baku kanal IPAM Ngagel (PDAM Surya Sembada), Juli–September 2023: sekitar 9–29 NTU (laporan magang UPN Jatim). |
| Kekeruhan saat hujan | naik 120–520 NTU | Musim hujan bisa mencapai ±900 NTU dan kemarau ±100 NTU di IPA Kedunguling Sidoarjo (Jurnal Teknik ITS); kejadian ekstrem di Kali Surabaya pernah tercatat sampai 3.000 NTU akibat longsoran sawah (Beritajatim). |
| Tinggi muka air | 85 cm ± 3 cm (relatif), naik 12–48 cm saat hujan | Tidak ada data publik per menit; Kali Surabaya diatur pintu air (Mlirip, Gunungsari, Jagir), jadi dipakai nilai relatif. |
| Ambang | pH 6–9, TDS 1000 mg/L, deviasi suhu 3 °C | PP 22/2021 Lampiran VI, baku mutu air sungai kelas II (sesuai brief). |

## Skenario kejadian (asumsi tim, bukan data terukur)

| Skenario | Perubahan di HILIR saja | Catatan |
|---|---|---|
| Pembuangan asam | pH −1,4 s.d. −2,3; TDS +380–720; kekeruhan +80–220; suhu +0,3–1,5 °C | Bentuk naik cepat 3–8 menit, berdenyut, berlangsung 15–110 menit |
| Pembuangan basa | pH +1,8 s.d. +2,6; TDS +320–700; kekeruhan +60–200; suhu +1,5–4,5 °C | |
| Pembuangan ringan | TDS +110–230; kekeruhan +15–45 | Contoh kasus yang seharusnya WASPADA |
| Hujan | kekeruhan, tinggi air naik di kedua node; TDS turun 8–20 % (pengenceran) | HULU lebih dulu, HILIR menyusul setelah τ = 12 menit |
| Sensor rusak | pH/TDS/tinggi air macet (nilai identik), DS18B20 −127 °C, lonjakan kekeruhan 1.500–3.000 NTU sesaat | Harus jadi "perlu perawatan", bukan BAHAYA |

## Tautan sumber

- Kualitas air Kali Surabaya (pH, suhu, DO, TSS, Pb, Cd), 2026: https://ejournal.uki.ac.id/index.php/cen/article/download/8542/3983/35197
- Variasi musiman Sungai Jagir (TDS, EC, pH, suhu), Des 2022–Nov 2023: https://envirotek.upnjatim.ac.id/index.php/envirotek/article/download/1926/159/1661
- Kekeruhan air baku harian PDAM Surya Sembada, Juli–September 2023: https://repository.upnjatim.ac.id/32424/4/BAB%202%20Magang_Nara.pdf
- Kekeruhan musim hujan vs kemarau, IPA Kedunguling Sidoarjo: https://ejurnal.its.ac.id/index.php/teknik/article/download/4427/1158
- Kekeruhan 3.000 NTU di Kali Surabaya (berita): https://beritajatim.com/?p=655534

## Dataset tambahan dari tim (versi 5.0)

- `jagakali_training_30hari_clean.csv` dan `jagakali_training_30hari_augmented.csv` adalah turunan dari data 30 hari di atas: versi tanpa gangguan sensor, dan versi dengan tiga salinan hari 1–21 yang diberi gangguan sensor tambahan.
- `jagakali_synthetic_v2.csv.gz` berisi 19 run masing-masing 4 hari, dengan profil nominal, noise, shift, telemetri, dan stress. Kolom `ref_*` menyimpan nilai sebenarnya sebelum gangguan sensor, `label_lingkungan` menyimpan keadaan sungai sebenarnya, dan `split` menentukan run untuk latih, augmentasi, atau uji.
- Ketiganya juga sintetis. Nilai di synthetic_v2 sedikit lebih lebar (pH 5,3–9,4, tinggi air rata-rata 92 cm) daripada data 30 hari, sehingga berguna untuk menguji ketahanan model di luar rentang latihnya.
