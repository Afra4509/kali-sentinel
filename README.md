# KALI-Sentinel: paket lengkap website, data, AI, dan MQTT

Versi 3.0 · 25 November 2026 · BINUS Robotics Cup 2026 (AIoT)

## Isi paket

```
kalisentinel/
├── web/                         ← upload folder ini ke Vercel/Netlify (tautan publik untuk juri)
│   ├── index.html               landing page (design system soft-gradient + PRD)
│   ├── dashboard.html           dashboard lengkap F1–F13
│   └── kalisentinel_demo_video_5detik.csv   dipakai tombol "Putar dataset video"
├── data/
│   ├── kalisentinel_training_30hari.csv     86.400 baris, 60 detik, berlabel (untuk latih AI)
│   ├── kalisentinel_demo_video_5detik.csv   4.080 baris, 5 detik, skenario video
│   └── kalisentinel_events.csv              daftar kejadian di data training
├── ai/
│   ├── kalisentinel_core.py     fitur + aturan status (dipakai training dan server)
│   ├── generate_dataset.py      pembuat dataset (bisa diubah lalu dijalankan ulang)
│   ├── train_model.py           latih Isolation Forest + Random Forest
│   ├── server_analisis.py       server MQTT: publish ke kalisentinel/analisis
│   ├── models/                  model siap pakai + model_config.json (θ = 0,776)
│   ├── laporan_evaluasi.md      hasil uji model
│   └── requirements.txt
├── mqtt/
│   ├── kalisentinel-mqtt.js     pembungkus mqtt.js untuk browser (berkomentar lengkap)
│   ├── contoh-subscribe.html    halaman uji: tampilkan pesan mentah
│   ├── simulator-publisher.js   pengganti ESP32: putar CSV ke broker
│   └── package.json
├── esp32/kalisentinel_node/kalisentinel_node.ino   firmware contoh node
└── docs/SUMBER_DATA.md          dasar kalibrasi dataset dan tautan sumber
```

## 1. Upload website (5 menit)

1. Buka https://vercel.com, masuk, pilih **Add New → Project → Deploy** dari folder, atau seret folder `web/` ke https://app.netlify.com/drop.
2. Pastikan `index.html`, `dashboard.html`, dan `kalisentinel_demo_video_5detik.csv` ada di folder yang sama.
3. Buka tautan publiknya. Beranda (`index.html`) menjelaskan sistem; tombol **Buka dashboard** membawa ke dashboard. Di dashboard, tombol **DEMO** sudah aktif dan label **DATA SIMULASI** selalu terlihat.
4. Untuk juri yang langsung ke dashboard, bagikan tautan `.../dashboard.html`.

Untuk video: pilih kecepatan **60×** lalu klik **Putar dataset video**. Urutannya: AMAN → INFO HUJAN (±10.02) → AMAN → WASPADA/BAHAYA (±10.40) → AMAN → "perlu perawatan" sensor pH HILIR (±11.40). Di 60× seluruhnya ±3 menit; di 10× ±17 menit. Tombol skenario (Normal, Hujan, Pembuangan di hilir, Sensor rusak) tetap bisa dipakai kapan saja.

## 2. MQTT, dijelaskan dengan sederhana

Bayangkan **broker** sebagai kantor pos, **topik** sebagai alamat kotak surat.

| Siapa | Melakukan | Topik | Lewat |
|---|---|---|---|
| ESP32 HULU | publish data tiap 60 detik | `kalisentinel/node/HULU` | TLS port 8883 |
| ESP32 HILIR | publish data tiap 60 detik | `kalisentinel/node/HILIR` | TLS port 8883 |
| Server Python | subscribe dua topik di atas, publish hasil | `kalisentinel/analisis` | TLS port 8883 |
| Website | subscribe ketiga topik | semua di atas | WebSocket TLS `wss://h2117224.ala.us-east-1.emqxsl.com:8084/mqtt` |

Browser tidak bisa memakai port 8883, karena itu website memakai WebSocket TLS (port 8084). Semua pihak bertemu di broker EMQX Cloud (`h2117224.ala.us-east-1.emqxsl.com`) dan memakai username/password klien dari menu **Access Control → Authentication** di EMQX Cloud (isi di `.env` untuk simulator & server Python, di `kalisentinel_node.ino` untuk ESP32, dan di tab **Pengaturan** dashboard untuk browser).

Contoh pesan node (yang dikirim ESP32):

```json
{"node_id":"HULU","timestamp":"2026-12-01T10:15:00+07:00","ph":7.1,"temperature_c":28.4,
 "turbidity_ntu":42.0,"tds_ppm_est":210,"water_level_cm":85.0,"rssi":-61}
```

Kode subscribe paling sederhana di browser (lihat `mqtt/kalisentinel-mqtt.js` untuk versi lengkap):

```html
<script src="https://unpkg.com/mqtt@5.10.1/dist/mqtt.min.js"></script>
<script>
  const client = mqtt.connect('wss://h2117224.ala.us-east-1.emqxsl.com:8084/mqtt', {
    username: 'USER_MQTT',
    password: 'PASSWORD_MQTT'
  });
  client.on('connect', () => client.subscribe(['kalisentinel/node/+', 'kalisentinel/analisis']));
  client.on('message', (topic, payload) => {
    const data = JSON.parse(payload.toString());
    console.log(topic, data);          // di sinilah dashboard memperbarui kartu dan grafik
  });
</script>
```

### Uji MQTT tanpa ESP32

1. Pasang Node.js 18+, lalu di folder `mqtt/` jalankan `npm install`.
2. Jalankan `node simulator-publisher.js --speed 10`. Simulator mengirim dataset video ke broker, dengan timestamp diganti waktu sekarang.
3. Buka `contoh-subscribe.html` (cukup dobel klik) lalu klik **Hubungkan**. Pesan HULU/HILIR akan muncul.
4. Buka dashboard, pilih **LIVE**. Kartu dan grafik terisi dalam ±1 detik.

Catatan: pratinjau dashboard di claude.ai memblokir WebSocket, jadi mode LIVE hanya bisa diuji dari hosting sendiri (Vercel/Netlify) atau dari file lokal.

## 3. AI: model, data, dan server

```bash
cd ai
pip install -r requirements.txt
python generate_dataset.py          # opsional: buat ulang dataset
python repair_dataset.py            # pulihkan pembacaan sintetis ke CSV bersih
python augment_dataset.py           # tambah variasi gangguan pada hari latih
python train_model.py ../data/kalisentinel_training_30hari_augmented.csv
python server_analisis.py --replay ../data/kalisentinel_demo_video_5detik.csv   # uji tanpa broker
python server_analisis.py           # jalan sungguhan, subscribe/publish ke EMQX Cloud (baca .env)
```

**Cara kerja singkat**

- **Dataset latih** memuat skenario asli dan tiga variasi gangguan sensor. Variasi mencakup sensor macet pada semua parameter, koneksi suhu terputus, lonjakan kekeruhan, dan drift pH. Fitur dihitung per skenario. Random Forest memakai kejadian tambahan dan konteks sesudahnya. Pengujian memakai skenario asli hari 22–30.
- **Fitur**: HILIR dibandingkan dengan HULU yang digeser τ = 12 menit (massa air yang sama). Untuk tiap parameter dihitung z-score terhadap 30 menit terakhir (simpangan baku robust), selisih Δ terhadap kebiasaannya, dan apakah HULU ikut berubah. Nilai dilewatkan filter median-5 supaya lonjakan sesaat tidak memicu alarm.
- **Isolation Forest** dilatih pada data normal dan hujan dari skenario asli. Skornya dinormalkan ke 0–1 dan dikirim sebagai `anomaly_score`. Ambang hasil pelatihan tersimpan di `ai/models/model_config.json`.
- **Random Forest** mengenali pola (normal, hujan, pembuangan, sensor_rusak), dikirim sebagai `pattern_ml`.
- **Status akhir** memakai aturan yang sama dengan aturan cadangan di website, jadi demo tetap konsisten bila server mati.

**Hasil uji (hari 22–30, tidak ikut dilatih)**

| Label asli | Hasil status |
|---|---|
| Pembuangan | 87,4 % baris WASPADA/BAHAYA; semua kejadian tertangkap dalam 2–3 menit. Sisanya adalah masa pemulihan setelah buangan berhenti. |
| Hujan | 0 % BAHAYA, 1,1 % WASPADA |
| Normal | 0 % alarm |
| Sensor rusak | 0 % BAHAYA |

Pada periode uji sintetis yang sama, penambahan variasi gangguan menaikkan recall sensor rusak dari 35,2% menjadi 52,1%. Presisi kelas ini turun dari 86,9% menjadi 80,4%. Rincian ada di `ai/laporan_evaluasi.md`.

[Laporan visual](ai/visualisasi/laporan_visual.pdf) memuat heatmap klasifikasi, perbandingan metrik, kurva precision–recall Isolation Forest, komposisi data latih, dan contoh cleaning. Untuk membuat ulang PDF dan PNG setelah training, jalankan `pip install matplotlib` lalu `python visualize_evaluation.py` dari folder `ai`.

[Eksperimen Sungai Gembong v2](docs/EKSPERIMEN_GEMBONG.md) mendokumentasikan generator baru, benchmark temporal lima keluarga model, replay CSV ESP32, dan rencana validasi lapangan.

Format pesan yang dipublish server sudah sesuai brief, ditambah `pattern_ml` dan `pattern_ml_confidence`:

```json
{"timestamp":"2026-12-01T10:43:00+07:00","status":"BAHAYA","anomaly_score":0.932,"threshold":0.862,
 "A_t":0,"N_t":2,"tau_min":12,"delta":{"ph":-0.42,"temperature_c":0.38,"turbidity_ntu":44.5,
 "tds_ppm_est":122.0,"water_level_cm":1.3},"pattern":"anomali_multiparameter_hilir",
 "sensor_health":{"HULU":"ok","HILIR":"ok"},
 "message":"pH dan TDS berubah bersamaan hanya di HILIR. Prioritas inspeksi: segmen antara Node HULU dan HILIR."}
```

Server butuh ±45 menit data (30 menit jendela + τ) sebelum mengirim analisis pertama. Selama itu website memakai aturan cadangan.

## 4. ESP32

Buka `esp32/kalisentinel_node/kalisentinel_node.ino` di Arduino IDE, pasang library PubSubClient, ArduinoJson, OneWire, DallasTemperature. Isi WiFi, set `NODE_ID` ke `HULU` atau `HILIR`, lalu **ganti angka kalibrasi** dengan hasil kalibrasi alat tim (buffer pH 4/7, larutan TDS standar, tinggi pemasangan sensor jarak).

## 5. Versi 3.0: design system soft-gradient

- Landing page baru mengikuti PRD: navbar kaca dengan drawer di HP, hero split 55/45, seksi manfaat 35/65 dengan carousel (tombol dan panah keyboard), metrics bar, showcase 3 kolom, footer.
- Dashboard memakai token yang sama: Plus Jakarta Sans, kanvas #F4F6FA, kartu radius 24px, bayangan ambien, tombol pill, tombol utama bergradasi.
- Penyesuaian dari dokumen demi aksesibilitas (target WCAG AA di PRD): gradasi tombol utama digelapkan supaya teks putih kontras ≥ 4,5:1, teks eyebrow memakai lavender tua, dan warna status (hijau, kuning, merah, biru) tidak diganti pastel karena status harus terbaca jelas.
- Angka contoh di PRD (+12K pengguna, 98% kepuasan) diganti metrik proyek yang benar, dengan catatan bahwa angka uji berasal dari dataset sintetis.
- Belum dikerjakan dari PRD: sitemap.xml, event analytics, dan pengujian Lighthouse. Tambahkan setelah domain hosting final diketahui.

## 6. Perbaikan di versi 2.0

- Lonjakan sesaat (gelembung, kabel) tidak lagi memicu alarm: filter median-5 dan deteksi "lonjakan sesaat berulang" sebagai perlu perawatan.
- Nilai yang kembali normal setelah kejadian tidak lagi dibaca sebagai penyimpangan baru.
- Buangan yang berlangsung lama tetap terdeteksi setelah rata-rata 30 menit menyesuaikan.
- Saat hujan aktif, kenaikan kekeruhan/tinggi air di HILIR tidak lagi memicu WASPADA.
- Kartu kekeruhan/tinggi air tidak lagi merah saat air surut setelah hujan; saat hujan ditandai biru "naik di kedua node".
- Notifikasi tidak lagi error bila server analisis masuk sebelum ada data node.
- Data simulasi website dikalibrasi ke nilai Kali Surabaya.
- Tombol "Putar dataset video" dan log dikosongkan saat memuat CSV baru.
- Tampilan baru: tipografi Geist dan Geist Mono, kartu status dengan statistik Nt/At/skor, kartu sensor diperbarui di tempat sehingga perubahan warna berjalan halus, mode gelap.

## Disclaimer (wajib, ada di halaman Tentang)

Status KALI-Sentinel adalah peringatan dini berbasis sensor murah. Sistem hanya menyatakan nilai melampaui ambang acuan, bukan melanggar baku mutu; penetapan pelanggaran adalah wewenang instansi setelah analisis laboratorium terakreditasi. Sistem tidak mengukur DO, amonia, COD, BOD, logam berat, deterjen, atau zat warna.
