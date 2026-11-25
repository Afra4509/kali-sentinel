# KALI-Sentinel · Eksperimen Sungai Gembong

## Audit sistem awal

| Temuan | Dampak | Perubahan v2 |
|---|---|---|
| Dasar simulasi lama menggunakan acuan Surabaya dan Jagir, dengan bentuk kejadian berulang | Nilai dasar, pola hujan, dan dinamika kejadian bisa terlalu seragam untuk Gembong | Independen per skenario dengan variasi latar, kondisi hujan, waktu tempuh dan gangguan alat |
| Augmentasi lama memakai ulang lintasan lingkungan | Menambah variasi fault sambil mempertahankan pola air yang sama. Uji lama juga berasal dari satu generator dan satu realisasi dasar. | Tiga skenario augmentasi dengan seed dan lintasan baru. Uji memakai sepuluh seed lain. |
| `to_grid` lama memakai pencocokan terdekat dalam toleransi satu interval | Sampel setelah waktu target dapat dipakai saat ada celah | Grid menit v2 memakai sampel pada menit yang bersangkutan. Fitur diterbitkan setelah menit tersebut selesai. |
| Cleaning lama melakukan rekonstruksi dari seed | Tepat untuk data lama dengan asal-usul yang terverifikasi. Rekonstruksi persis memerlukan akses ke generator. | QC pada telemetri ESP32 di pipeline Python, batas pengisian dua menit, dan log tindakan. |
| Telemetri hampir lengkap dan kerusakan terkonsentrasi pada macet, lonjakan besar, serta sentinel suhu | Model bisa belajar ciri injeksi tertentu dan melewatkan bias, drift atau pembacaan intermiten | Enam jenis fault, telemetri hilang, noise yang berubah, dan referensi sintetis per kanal |
| Baseline diferensial lama melihat sampai 24 jam saat evaluasi. Buffer server sekitar empat jam. | Fitur pelatihan dan inferensi bisa berbeda untuk sinyal lambat | Baseline v2 180 menit. Replay CSV memakai fungsi fitur eksperimen yang sama. |

## Dasar ilmiah dan asumsi simulasi

- Penelitian gabungan Hilir Coban dan Hulu Gembong melaporkan pH 7,97–8,66, suhu 27,39–32,42 °C, TDS 101–343 mg/L, dan kekeruhan 34,30–115 NTU. Hasil pengukuran muara Gembong di publikasi lain mencatat pH 7,5 dan suhu 28,5 °C. Studi gabungan Welang–Gembong–Rejoso mencatat pH 7,05–7,35 dan suhu 28,1–30,5 °C. Rentang gabungan memberi pembanding untuk orde besaran dan variasi lokasi. Dataset v2 mulai dari latar lama sekitar pH 7,45, 29,6 °C, 275 ppm dan 22 NTU, lalu memvariasikan latar tersebut per skenario. Kekeruhan dasar yang rendah dan hubungan ppm estimasi terhadap TDS lab masih perlu kalibrasi lokal. [Hilir Coban dan Hulu Gembong](https://jtresda.ub.ac.id/index.php/jtresda/article/download/1112/666/5015) · [Muara Gembong](https://ppjp.ulm.ac.id/journal/index.php/es/article/download/20460/pdf) · [Studi tiga sungai](https://scholar.ub.ac.id/en/publications/water-quality-assessment-and-pollution-status-using-the-storet-me/)
- Sinyal air memakai siklus diurnal dan komponen AR(1). Badai menghasilkan respons muka air dan sedimen dengan onset dan peluruhan berbeda, penurunan suhu, serta pengenceran TDS. HILIR menerima sinyal tertunda plus limpasan lokal. Pembuangan mengubah beberapa parameter dari satu profil plume. pH memakai pendekatan pencampuran konsentrasi ion hidrogen. Model pencampuran ini mengabaikan alkalinitas, buffering, pasang surut, dan geometri sungai. Seluruh profil badai, pembuangan, waktu tempuh 7–27 menit, dan datum tinggi air adalah asumsi.
- Noise alat terdiri dari variasi pembacaan, bias perangkat, komponen lambat dan kuantisasi. Dengan naiknya kekeruhan, simulasi menambah komponen variasi optik. Suhu dikuantisasi pada 0,0625 °C, sesuai resolusi DS18B20 mode 12-bit. Kanal TDS dibatasi 1000 ppm mengikuti firmware. Variasi durasi, amplitudo fault, frekuensi putus paket, dan drift dikonfigurasi untuk stress test. Protokol USGS mendasari pemantauan drift, fouling dan kalibrasi, sedangkan besar injeksi masih asumsi. [USGS TM 1–D3](https://pubs.usgs.gov/publication/tm1D3) · [Analog Devices DS18B20](https://www.analog.com/en/resources/design-notes/1wire-protocol-pdf-of-ds18s20-vs-ds18b20-digital-themormeters.html)
- Nilai `ref_*` adalah pembacaan sintetis dengan noise latar sebelum injeksi fault. `gangguan`, `kanal_gangguan`, `label_lingkungan`, dan `paket_hilang` mencatat kondisi sumber untuk audit. Label sensor rusak menandai durasi fault, termasuk menit di dalam periode spike dan intermiten ketika sampel sesaat tampak normal. Untuk tugas klasifikasi tunggal, sensor rusak diprioritaskan jika bersamaan dengan kejadian lingkungan. Metadata sumber, profil, seed, timestamp numerik, dan referensi dikecualikan dari input model.

## QC, fitur, dan validasi

QC menandai nilai non-finite, pH di luar 0–14, sentinel suhu ≤ −100 °C, serta kekeruhan/TDS negatif. QC mempertahankan spike numerik yang masih memungkinkan, pembacaan ekstrem lingkungan, dan TDS jenuh. Celah diisi dari pembacaan sebelumnya selama maksimal dua menit. Gap lebih panjang tetap hilang pada deret sensor. Fungsi fitur memakai nilai penanda numerik dan indikator missing pada fitur v2. CSV audit menyimpan waktu, node, kanal, nilai asal/hasil dan jenis tindakan. `ref_*` hanya membantu diagnosis sintetis.

Fitur baru memakai rerata dan simpangan baku rolling, perbedaan satu dan 15 menit, persistensi nilai datar, riwayat ketersediaan, hubungan perubahan HULU–HILIR dengan beberapa lag, dan korelasi perubahan kekeruhan dengan tinggi air. Korelasi terakhir hanya proxy limpasan. Curah hujan eksternal diperlukan untuk fitur hujan terukur.

Dataset memuat 19 blok empat hari, terdiri dari 6 latih dasar, 3 augmentasi latih, dan 10 uji. Setelah 42 menit pemanasan tiap blok, uji mencakup 57.180 menit berpasangan. Tiap profil nominal, noise, shift, telemetri, dan stress memiliki dua seed uji. Noise mengalikan variasi alat dengan 3. Shift mengubah baseline air, kekuatan badai, dan waktu tempuh. Telemetri menaikkan tekanan loss. Stress menggabungkan ketiganya. Profil memakai seed berbeda, sehingga selisih metrik antarpaket mengandung variasi kejadian selain efek profil. Seluruh profil masih berasal dari keluarga generator yang sama.

Optimasi memakai tiga lipatan expanding-window, masing-masing dengan dua skenario validasi yang seluruhnya sesudah blok latih. Lima keluarga model diuji pada dua konfigurasi kedalaman/leaf dan lima aturan prediksi sensor. Seleksi memakai Macro F1 out-of-fold dan F1 sensor sebagai pemecah seri, dengan batas presisi sensor 70% bila tersedia. Skor presisi, recall, F1, balanced accuracy, AP, dan confusion matrix dihitung pada blok uji yang sama untuk setiap tahap. AP adalah average precision, ringkasan non-interpolatif kurva precision–recall. Model lama dinilai ulang pada skenario uji v2. Skor historis 92,8% dan Macro F1 0,836 berasal dari uji v1 yang berbeda.

Ablasi menambahkan QC, fitur, augmentasi, optimasi Random Forest, lalu model pemenang CV. Baseline v2 memakai Random Forest pada data mentah v2 dengan horizon yang sama dengan tahap QC. Isolation Forest v2 dilatih pada label normal/hujan. AP pembuangan kedua Isolation Forest memakai target yang sama. Permutation importance dan SHAP membantu membaca keterkaitan fitur dan prediksi, dengan interpretasi terbatas saat fitur berkorelasi.

Uji tambahan memakai dua seed baru dengan pasangan lintasan nominal dan limpasan awal kaya sedimen/ion. Perlakuan tambahan mengubah respons lokal HILIR saat sedimen naik cepat. Amplitudo adalah asumsi stress test. Kedua model dibekukan untuk uji ini. [Observasi limpasan awal USGS](https://pubs.usgs.gov/publication/sir20225111/full) · [Observasi konduktivitas saat limpasan USGS](https://pubs.usgs.gov/sir/2008/5001/pdf/sir20085001.pdf)

## Hasil dan keputusan

XGBoost dipilih dari CV dengan kedalaman 6, `min_child_weight` 8, 90 estimator, dan ambang skor sensor 0,40. Macro F1 CV 0,7776. HistGradientBoosting menghasilkan Macro F1 CV yang hampir sama pada grid pencarian ini. Skor model adalah keluaran klasifikasi dan ambang dipilih di CV. Kalibrasi probabilitas untuk penggunaan lapangan masih perlu pengujian.

| Tahap | Akurasi | Balanced accuracy | Macro F1 | Presisi sensor | Recall sensor |
|---|---:|---:|---:|---:|---:|
| Model lama | 71,5% | 66,0% | 0,628 | 88,0% | 13,4% |
| Baseline v2 | 73,7% | 68,5% | 0,684 | 75,9% | 24,8% |
| Cleaning | 73,9% | 68,3% | 0,682 | 77,7% | 23,7% |
| Fitur temporal | 75,6% | 71,4% | 0,717 | 81,4% | 33,8% |
| Augmentasi | 76,8% | 72,9% | 0,734 | 84,7% | 38,7% |
| RF dioptimasi | 75,2% | 71,3% | 0,714 | 83,0% | 33,6% |
| Model final | 79,7% | 77,8% | 0,784 | 83,9% | 56,7% |

QC mencatat 5.863 sel yang ditandai atau diisi. Cleaning saja sedikit menurunkan Macro F1. Fitur temporal dan indikator kualitas memperbaiki deteksi berikutnya. Optimasi RF pada grid ini juga kurang baik daripada RF augmentasi tanpa tuning pada uji independen. XGBoost mendeteksi 5.305 dari 9.362 sampel sensor rusak. F1 sensor naik dari 0,233 ke 0,676 dan AP sensor dari 0,410 ke 0,706. Recall sensor terendah terjadi pada profil shift (48,0%). Presisi sensor terendah terjadi pada profil telemetri (73,5%), konsisten dengan tantangan membedakan paket hilang dan fault kanal.

Pada challenge limpasan awal, Macro F1 rerata dua seed turun dari 0,780 menjadi 0,765 pada model final. F1 pembuangan turun dari 0,878 ke 0,829. Isolation Forest v2 juga turun ke AP pembuangan 0,617 dari 0,745 pada model Isolation Forest lama ketika keduanya diuji pada v2. Hasil ini mendukung evaluasi lanjut atas pemisahan limpasan dan pembuangan sebelum adopsi operasional.

Replay 5.718 menit dari satu skenario uji menghasilkan skor yang cocok dengan log benchmark. Pemeriksaan kausal membandingkan fitur dari rekaman penuh dengan fitur ketika rekaman dipotong saat prediksi. Tree SHAP dihitung pada 180 menit uji.

## Validasi lapangan dengan ESP32

1. Tetapkan lokasi HULU dan HILIR, datum tinggi air, dan jarak sepanjang aliran. Sinkronkan waktu ke UTC, simpan timestamp node dan waktu tiba di broker, serta gunakan nomor urut paket untuk membedakan pembacaan hilang, duplikat dan keterlambatan.
2. Rekam lima kanal asli beserta ADC/mV yang tersedia, RSSI, tegangan suplai, reset, versi firmware, seri probe, dan jadwal pembersihan/kalibrasi. Lakukan kalibrasi sebelum dan sesudah deployment. Catat satuan TDS estimasi dan simpan konduktivitas mentah atau terkoreksi 25 °C jika tersedia.
3. Kumpulkan periode kering dan hujan. Pasangkan alat referensi atau pengukuran manual berkala. Saat terjadi perubahan mencolok, simpan catatan lapangan, presipitasi, debit/tinggi air, dan sampel lab bila tersedia. DLHKP Kota Pasuruan mendokumentasikan pemantauan Gembong berbasis pengambilan sampel dan analisis laboratorium. [Pemantauan Gembong 2026](https://dlhkp.pasuruankota.go.id/2026/04/21/pemantauan-kualitas-air-di-sungai-gembong-tahun-2026/)
4. Pisahkan label kondisi air dan kesehatan alat. Tandai kejadian yang belum bisa dikonfirmasi sebagai tidak pasti. Uji gangguan alat terkontrol dengan data lab/meja uji terpisah, lalu ukur keterlambatan deteksi, alarm palsu per hari, dan recall per kejadian pada periode lapangan yang dibekukan.
5. Mulai dengan replay CSV dan jalankan penilaian paralel pada data lapangan sebelum memakai hasil klasifikasi untuk keputusan operasional. Model eksperimen berada di `ai/eksperimen_v2`. Pipeline MQTT di repo masih memuat artefak historis dari `ai/models`.

## Reproduksi

Jalankan dari root repositori menggunakan Python 3.13.

```sh
python -m pip install -r ai/requirements-experiment.txt
python ai/simulate_river.py
python ai/experiment_river.py
python ai/challenge_river.py
python ai/predict_river.py data/kalisentinel_synthetic_v2.csv.gz hasil_replay.csv
```

Luaran mencakup [CSV sintetis](../data/kalisentinel_synthetic_v2.csv.gz), [manifest](../ai/eksperimen_v2/manifest.csv), [audit QC](../ai/eksperimen_v2/audit_qc.csv.gz), [validasi CV](../ai/eksperimen_v2/validasi_cv.csv), [ablasi](../ai/eksperimen_v2/ablasi.csv), [metrik per kelas](../ai/eksperimen_v2/per_kelas.csv), [hasil per profil dan seed](../ai/eksperimen_v2/robustness.csv), [uji limpasan awal](../ai/eksperimen_v2/challenge_first_flush.csv), dan [laporan visual](../ai/eksperimen_v2/laporan_visual_v2.pdf).
