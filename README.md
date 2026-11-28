# Jagakali: paket lengkap website, data, AI, dan MQTT

![Jagakali](brand/jagakali-logo.png)

Versi 7.0, 26 November 2026. Dulu bernama KALI-Sentinel. BINUS Robotics Cup 2026 (AIoT).

## Isi paket

```
jagakali/
├── web/                         ← upload folder ini ke Vercel/Netlify (tautan publik untuk juri)
│   ├── index.html               beranda: scroll = menyelam ke dasar Kali Surabaya
│   ├── dashboard.html           dashboard lengkap F1–F13
│   ├── tide.js                  transisi gelombang saat halaman dibuka dan pindah halaman
│   ├── jagakali_demo_video_5detik.csv   dipakai tombol "Putar dataset video"
│   └── jagakali-logo-480.png, jagakali-logo-white-480.png, favicon.png, og.png   aset logo
├── data/
│   ├── jagakali_training_30hari.csv            86.400 baris, 60 detik, berlabel
│   ├── jagakali_training_30hari_clean.csv      sama, gangguan sensor diganti nilai sebenarnya
│   ├── jagakali_training_30hari_augmented.csv  + 3 salinan hari 1–21 dengan gangguan sensor tambahan
│   ├── jagakali_synthetic_v2.csv.gz            19 run × 4 hari, 5 profil, 6 jenis gangguan, split latih/uji
│   ├── jagakali_demo_video_5detik.csv          4.080 baris, 5 detik, skenario video
│   └── jagakali_events.csv                     daftar kejadian di data 30 hari
├── ai/
│   ├── jagakali_core.py         fitur + aturan status (dipakai training dan server)
│   ├── datasets.py              memuat semua dataset sebagai run terpisah
│   ├── generate_dataset.py      pembuat dataset (bisa diubah lalu dijalankan ulang)
│   ├── train_model.py           latih Isolation Forest + Random Forest
│   ├── server_analisis.py       server MQTT: publish ke jagakali/analisis
│   ├── models/                  model siap pakai + model_config.json (θ = 0,795)
│   ├── laporan_evaluasi.md      hasil uji model
│   ├── hasil_uji.csv.gz         status per menit di semua run uji
│   └── requirements.txt
├── mqtt/
│   ├── jagakali-mqtt.js         pembungkus mqtt.js untuk browser (berkomentar lengkap)
│   ├── contoh-subscribe.html    halaman uji: tampilkan pesan mentah
│   ├── simulator-publisher.js   pengganti ESP32: putar CSV ke broker
│   └── package.json
├── esp32/jagakali_node/jagakali_node.ino   firmware contoh node
├── brand/                       logo Jagakali (PNG transparan) dan simbol tetes air
└── docs/SUMBER_DATA.md          dasar kalibrasi dataset dan tautan sumber
```

## 1. Upload website (5 menit)

1. Buka https://vercel.com, masuk, pilih **Add New → Project → Deploy** dari folder, atau seret folder `web/` ke https://app.netlify.com/drop.
2. Pastikan semua isi folder `web/` ikut terupload dalam satu folder, terutama `tide.js` dan `jagakali-logo-white-480.png`. Tanpa `tide.js` halaman tetap jalan (ada pengaman 3,6 detik), tetapi transisi gelombangnya hilang.
3. Buka tautan publiknya. Beranda (`index.html`) menjelaskan sistem; tombol **Buka dashboard** membawa ke dashboard. Di dashboard, tombol **DEMO** sudah aktif dan label **DATA SIMULASI** selalu terlihat.
4. Untuk juri yang langsung ke dashboard, bagikan tautan `.../dashboard.html`.

Untuk video: pilih kecepatan **60×** lalu klik **Putar dataset video**. Urutannya: AMAN → INFO HUJAN (±10.02) → AMAN → WASPADA/BAHAYA (±10.40) → AMAN → "perlu perawatan" sensor pH HILIR (±11.40). Di 60× seluruhnya ±3 menit; di 10× ±17 menit. Tombol skenario (Normal, Hujan, Pembuangan di hilir, Sensor rusak) tetap bisa dipakai kapan saja.

## 2. MQTT, dijelaskan dengan sederhana

Bayangkan **broker** sebagai kantor pos, **topik** sebagai alamat kotak surat.

| Siapa | Melakukan | Topik | Lewat |
|---|---|---|---|
| ESP32 HULU | publish data tiap 60 detik | `jagakali/node/HULU` | TCP port 1883 |
| ESP32 HILIR | publish data tiap 60 detik | `jagakali/node/HILIR` | TCP port 1883 |
| Server Python | subscribe dua topik di atas, publish hasil | `jagakali/analisis` | TCP port 1883 |
| Website | subscribe ketiga topik | semua di atas | WebSocket `wss://broker.hivemq.com:8884/mqtt` |

Browser tidak bisa memakai port 1883, karena itu website memakai WebSocket. Semua pihak bertemu di broker yang sama, jadi tidak ada yang perlu tahu alamat IP pihak lain.

Contoh pesan node (yang dikirim ESP32):

```json
{"node_id":"HULU","timestamp":"2026-12-01T10:15:00+07:00","ph":7.1,"temperature_c":28.4,
 "turbidity_ntu":42.0,"tds_ppm_est":210,"water_level_cm":85.0,"rssi":-61}
```

Kode subscribe paling sederhana di browser (lihat `mqtt/jagakali-mqtt.js` untuk versi lengkap):

```html
<script src="https://unpkg.com/mqtt@5.10.1/dist/mqtt.min.js"></script>
<script>
  const client = mqtt.connect('wss://broker.hivemq.com:8884/mqtt');
  client.on('connect', () => client.subscribe(['jagakali/node/+', 'jagakali/analisis']));
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
python train_model.py               # latih model, tulis laporan_evaluasi.md
python server_analisis.py --replay ../data/jagakali_demo_video_5detik.csv   # uji tanpa broker
python server_analisis.py           # jalan sungguhan, subscribe/publish ke broker.hivemq.com
```

**Cara kerja singkat**

- **Fitur**: HILIR dibandingkan dengan HULU yang digeser τ = 12 menit (massa air yang sama). Untuk tiap parameter dihitung z-score terhadap 30 menit terakhir (simpangan baku robust), selisih Δ terhadap kebiasaannya, dan apakah HULU ikut berubah. Nilai dilewatkan filter median-5 supaya lonjakan sesaat tidak memicu alarm.
- **Isolation Forest** dilatih hanya pada data normal + hujan, jadi hujan tidak dianggap anomali. Skornya dinormalkan ke 0–1 dan dikirim sebagai `anomaly_score`; ambang `threshold` = 0,795.
- **Random Forest** mengenali pola (normal, hujan, pembuangan, sensor_rusak), dikirim sebagai `pattern_ml`. Jika model ini yakin (≥ 0,6) polanya gangguan sensor dan yang berubah hanya satu parameter, alarm diredam dan status menjadi "sensor perlu perawatan".
- **Data latih**: 172 ribu menit dari 30 hari (hari 1–21), tiga run augmented, dan synthetic_v2 split latih + augmentasi. **Data uji**: 70 ribu menit dari run terpisah (30 hari hari 22–30 dan synthetic_v2 split uji).
- **Status akhir** memakai aturan yang sama dengan aturan cadangan di website, jadi demo tetap konsisten bila server mati.

**Hasil uji pada run yang tidak pernah dilihat model**

| Profil uji | Buangan memicu alarm | Alarm palsu, sensor sehat | Alarm palsu, saat gangguan sensor |
|---|---|---|---|
| Asli (30 hari, hari 22–30) | 87,7 % | 0,2 % | 0,3 % |
| Nominal | 93,8 % | 0,2 % | 11,1 % |
| Sensor berisik | 96,1 % | 1,7 % | 14,0 % |
| Musim bergeser | 95,9 % | 1,1 % | 12,7 % |
| Telemetri (paket hilang) | 94,9 % | 0,4 % | 3,9 % |
| Kondisi berat | 86,5 % | 1,9 % | 17,0 % |

Semua 84 kejadian buangan di data uji tertangkap, dengan median 3 menit sejak buangan mulai. Persentase baris di bawah 100 % karena masa pemulihan setelah buangan berhenti tetap dilabel buangan.

Alarm palsu per jenis gangguan sensor: bias 52,2 %, drift 20,0 %, macet 6,4 %, spike 2,1 %, putus 0,6 %, intermiten 0 %.

Kelemahan yang perlu diketahui juri: **bias pada sensor HILIR** (pergeseran tetap di satu sensor) tampak sama persis dengan buangan kecil yang hanya mengubah satu parameter. Tanpa sensor cadangan, data tidak bisa membedakannya, jadi kalibrasi rutin tetap wajib. Random Forest juga baru mengenali 34 % baris sensor rusak; aturan 15 menit datar, rentang fisik, dan paket hilang menutup sebagian besar sisanya. Rincian ada di `ai/laporan_evaluasi.md`.

Format pesan yang dipublish server sudah sesuai brief, ditambah `pattern_ml` dan `pattern_ml_confidence`:

```json
{"timestamp":"2026-12-01T10:43:00+07:00","status":"BAHAYA","anomaly_score":0.993,"threshold":0.795,
 "A_t":0,"N_t":2,"tau_min":12,"delta":{"ph":-0.42,"temperature_c":0.38,"turbidity_ntu":44.5,
 "tds_ppm_est":122.0,"water_level_cm":1.3},"pattern":"anomali_multiparameter_hilir",
 "pattern_ml":"pembuangan","pattern_ml_confidence":0.5,"sensor_health":{"HULU":"ok","HILIR":"ok"},
 "message":"pH dan TDS berubah bersamaan hanya di HILIR. Prioritas inspeksi: segmen antara Node HULU dan HILIR."}
```

Server butuh ±45 menit data (30 menit jendela + τ) sebelum mengirim analisis pertama. Selama itu website memakai aturan cadangan.

## 4. ESP32

Buka `esp32/jagakali_node/jagakali_node.ino` di Arduino IDE, pasang library PubSubClient, ArduinoJson, OneWire, DallasTemperature. Isi WiFi, set `NODE_ID` ke `HULU` atau `HILIR`, lalu **ganti angka kalibrasi** dengan hasil kalibrasi alat tim (buffer pH 4/7, larutan TDS standar, tinggi pemasangan sensor jarak).

## 5. Versi 7.0: sungai yang hidup

**Penghuni sungai di beranda**
- Kawanan ikan wader berenang berkelompok (saling menjaga jarak, searah, dan merapat), ditambah ikan nila yang berenang sendiri dan kawanan jauh yang samar di air dalam.
- Ikan bereaksi: kabur kalau kursor digerakkan cepat atau air diklik, menyelam saat perahu lewat di atasnya, dan di air dalam mendekati cahaya senter kursor yang tenang.
- Saat skenario buangan, kawanan di antara dua node terkena kepulan: sebagian megap-megap ke permukaan dengan gelembung kecil, sisanya kabur ke arah hulu. Ini cara visual menjelaskan kenapa HULU tetap normal.
- Perahu dayung dengan pendayung bercaping dan perahu motor bergantian lewat, lengkap dengan riak jejak dan bayangan di air. Eceng gondok hanyut terbawa arus, burung melintas, awan bergeser, ada cahaya matahari pagi.
- Di dasar sungai ada ikan sapu-sapu yang merayap dan mengaduk lumpur, yuyu yang berjalan menyamping dan lari kalau didekati, dan rumput air yang tersibak oleh kursor.
- Paket data terbang dari antena pelampung ke kolom HULU/HILIR di panel pembacaan, menggambarkan pesan MQTT setiap pembacaan. Kapsul sensor di dalam air berdenyut saat mengukur.
- Di air dalam kursor menjadi senter penyelam. Saat permukaan terlewati ketika menggulir, muncul semburan gelembung. Tombol **Naik ke permukaan** di dasar membawa pembaca kembali ke atas bersama gelembung.

**Komponen**
- Judul hero muncul per kata dari balik garis. Tombol utama sedikit tertarik ke arah kursor dan terisi air bergelombang saat disentuh.
- Panel pembacaan: jam simulasi berjalan, panah arah simpangan di nilai HILIR, tepi kartu berubah warna mengikuti status, grafik mini dengan area dan titik berdenyut.
- Pilihan skenario memakai indikator yang bergeser; tombol putar otomatis punya cincin progres per skenario.
- Garis progres kedalaman di header, batang hasil uji terisi sambil angkanya menghitung.
- Status sempat berkedip WASPADA saat berpindah dari hujan ke buangan; sekarang status hanya naik setelah air buangan benar-benar sampai di HILIR.

**Dashboard**
- Angka di kartu sensor dan skor AI bergulir ke nilai baru, tidak melompat.
- Indikator bergeser di navigasi, LIVE/DEMO, kecepatan, tab parameter, dan rentang waktu.
- Garis HILIR tergambar ulang saat parameter atau rentang diganti. Kartu yang melewati ambang bernapas pelan dengan cahaya merah.
- Peta skema: penanda node berdenyut dan ikan kecil hanyut mengikuti sungai. Label segmen prioritas tidak lagi menimpa penanda HULU.

**Transisi**: lapisan gelombang sekarang berisi gelembung yang naik, dan kunjungan pertama dibuka dengan kawanan ikan yang melintas.

**Hasil uji di browser**: 60 fps di 1440 px (beranda atas dan dasar), urutan status AMAN → WASPADA → BAHAYA tanpa kedip, mode kurangi animasi tetap menampilkan status yang benar, tanpa geser horizontal di 1440 px, 390 px, dan 375 px, tanpa error konsol.

## 6. Versi 6.0: menyelam ke sungai, transisi gelombang, simulasi bercerita

**Beranda**
- Konsepnya satu: menggulir halaman sama dengan menyelam. Di atas ada langit dan siluet kota, lalu muka air, lalu kolom air yang makin gelap, dan footer duduk di dasar sungai dengan rumput air dan batu.
- Satu kanvas penuh layar di belakang halaman menggambar semuanya: cahaya matahari yang menembus air, partikel melayang di tiga lapis kedalaman (parallax), gelembung, riak saat kursor menyentuh air, dan hujan.
- Mistar ukur di sisi kanan (layar ≥ 1380 px) menunjukkan kedalaman saat ini, dari "Di atas muka air" sampai ±4 m di dasar.
- Teks hero dan panel pembacaan bergerak dengan kecepatan berbeda saat digulir. Di HP parallax hero dimatikan supaya panel tidak menimpa tombol.

**Simulasi**
- Skenario buangan sekarang bercerita: asap buangan keluar dari pipa, terbawa arus ke kanan, dan baru saat sampai di pelampung HILIR angka berubah bertahap. TDS dan suhu dulu, kekeruhan 1,6 detik kemudian, pH 2,6 detik kemudian. Status naik AMAN → WASPADA → BAHAYA mengikuti urutan itu.
- Hujan: langit meredup, rintik dan riak muncul, air keruh merata di dua node, status INFO HUJAN.
- Sensor HILIR macet: nilai pH HILIR membeku, lampu pelampung HILIR padam, dan pesan meminta sensor dibersihkan atau dikalibrasi. Status sungai tetap AMAN karena yang bermasalah alatnya, bukan airnya.
- **Putar otomatis** memutar semua skenario berurutan (cocok untuk video), berhenti saat pengunjung menekan tombol lain.

**Transisi halaman (`tide.js`)**
- Kunjungan pertama: logo tetes air terisi air, lalu tiga lapis gelombang surut ke bawah dan membuka halaman.
- Pindah dari beranda ke dashboard (dan sebaliknya): gelombang naik menutup layar, halaman baru terbuka dengan gelombang surut.
- Pengunjung yang memilih "kurangi animasi" di sistemnya langsung melihat halaman tanpa transisi.

**Dashboard**
- Banner status sekarang tetap di tempat. Saat status berubah, warna baru menyebar dari ikon status seperti air meluap, bukan berkedip ulang setiap data masuk.

**Hasil uji di browser**: urutan status skenario buangan AMAN → WASPADA → BAHAYA, hujan INFO HUJAN, mistar mencapai 3,8 m di dasar, tidak ada geser horizontal di 1440 px maupun 375 px, navigasi gelombang ke dashboard berhasil, tanpa error konsol.

## 7. Versi 5.0: dataset tim, model lebih tahan gangguan, tampilan baru

**Model**
- Dilatih ulang pada semua dataset (30 hari, augmented, synthetic_v2). Pipeline sekarang memproses tiap run terpisah, jadi file dengan beberapa deret waktu tidak tercampur.
- Bug diperbaiki: data kosong saat sensor putus sebelumnya diisi angka 0, sehingga pH terbaca 0 dan memicu BAHAYA. Sekarang nilai kosong dan nilai mustahil (suhu −127 °C, kekeruhan negatif) ditandai sebagai gangguan alat. Alarm palsu saat sensor putus turun dari 25,8 % ke 0,6 %.
- Aturan baru: HILIR harus benar-benar berubah dibanding kebiasaannya sendiri. Bias di sensor HULU tidak lagi terbaca sebagai buangan di HILIR.
- Dashboard memakai aturan yang sama, jadi status di browser dan di server tetap konsisten.

**Tampilan**
- Beranda baru dengan penampang Kali Surabaya interaktif: pengunjung memilih Normal, Hujan deras, Buangan, atau Sensor macet, lalu melihat air, pelampung sensor, dan angka pembacaan berubah.
- Huruf Outfit (senada dengan wordmark logo) dan IBM Plex Sans, warna kabut, navy, dan teal dari logo. Garis tegas menggantikan bayangan dan kartu kaca.
- Hasil uji model ditampilkan apa adanya di beranda, termasuk kelemahan bias sensor.

## 8. Versi 4.0: ganti nama menjadi Jagakali

- Semua teks, judul halaman, notifikasi, nama file, dan nama modul memakai nama Jagakali.
- Logo dipasang di navbar beranda dan dashboard, plus favicon dan gambar pratinjau tautan (`og.png`).
- Warna aksen mengikuti logo: gradasi biru tua ke teal untuk tombol utama, teal untuk garis HILIR, aqua-biru untuk ilustrasi.
- **Penting untuk tim IoT dan AI: awalan topik MQTT ikut berubah** dari `kalisentinel/...` menjadi `jagakali/node/HULU`, `jagakali/node/HILIR`, dan `jagakali/analisis`. Firmware ESP32, simulator, server Python, dan dashboard di paket ini sudah memakai topik baru. Jika perangkat lama masih mengirim ke topik `kalisentinel/...`, ubah firmware-nya, atau sementara isi "Awalan topik" di halaman Pengaturan dashboard dengan `kalisentinel` dan jalankan server dengan `--prefix kalisentinel`.
- Dataset dan model dibuat ulang dengan nama file baru; hasil evaluasinya sama persis.

## 9. Versi 3.0: design system soft-gradient

- Landing page baru mengikuti PRD: navbar kaca dengan drawer di HP, hero split 55/45, seksi manfaat 35/65 dengan carousel (tombol dan panah keyboard), metrics bar, showcase 3 kolom, footer.
- Dashboard memakai token yang sama: Plus Jakarta Sans, kanvas #F4F6FA, kartu radius 24px, bayangan ambien, tombol pill, tombol utama bergradasi.
- Penyesuaian dari dokumen demi aksesibilitas (target WCAG AA di PRD): gradasi tombol utama digelapkan supaya teks putih kontras ≥ 4,5:1, teks eyebrow memakai lavender tua, dan warna status (hijau, kuning, merah, biru) tidak diganti pastel karena status harus terbaca jelas.
- Angka contoh di PRD (+12K pengguna, 98% kepuasan) diganti metrik proyek yang benar, dengan catatan bahwa angka uji berasal dari dataset sintetis.
- Belum dikerjakan dari PRD: sitemap.xml, event analytics, dan pengujian Lighthouse. Tambahkan setelah domain hosting final diketahui.

## 10. Perbaikan di versi 2.0

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

Status Jagakali adalah peringatan dini berbasis sensor murah. Sistem hanya menyatakan nilai melampaui ambang acuan, bukan melanggar baku mutu; penetapan pelanggaran adalah wewenang instansi setelah analisis laboratorium terakreditasi. Sistem tidak mengukur DO, amonia, COD, BOD, logam berat, deterjen, atau zat warna.
