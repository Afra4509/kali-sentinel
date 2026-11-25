/*
 * kalisentinel-mqtt.js
 * Pembungkus kecil mqtt.js untuk browser. Dipakai oleh contoh-subscribe.html,
 * dan logikanya sama dengan yang ada di web/index.html (mode LIVE).
 *
 * CARA KERJA MQTT SINGKATNYA
 *   - Broker  = "kantor pos" (EMQX Cloud: h2117224.ala.us-east-1.emqxsl.com). Semua pihak terhubung ke sini.
 *   - Topik   = "alamat kotak surat", misalnya kalisentinel/node/HILIR.
 *   - Publish = mengirim pesan ke sebuah topik (dilakukan ESP32 dan server Python).
 *   - Subscribe = berlangganan topik; setiap pesan baru langsung diteruskan ke kita (dilakukan website).
 *   Browser tidak bisa memakai TCP/TLS biasa (port 8883), jadi website memakai MQTT lewat WebSocket TLS
 *   (wss://h2117224.ala.us-east-1.emqxsl.com:8084/mqtt). ESP32 dan Python memakai port 8883 (TLS).
 *
 * PEMAKAIAN
 *   <script src="https://unpkg.com/mqtt@5.10.1/dist/mqtt.min.js"></script>
 *   <script src="kalisentinel-mqtt.js"></script>
 *   <script>
 *     const ks = KaliSentinelMQTT.connect({
 *       username:   'USER_MQTT',
 *       password:   'PASS_MQTT',
 *       onNode:     (node, data) => console.log(node, data.ph, data.tds_ppm_est),
 *       onAnalisis: (a)          => console.log(a.status, a.anomaly_score),
 *       onStatus:   (s)          => console.log('koneksi:', s)
 *     });
 *     // ks.disconnect();
 *   </script>
 */
(function (global) {
  'use strict';

  var DEFAULTS = {
    broker: 'wss://h2117224.ala.us-east-1.emqxsl.com:8084/mqtt', // EMQX Cloud WebSocket TLS (port 8084)
    username: 'ks-web',                          // akun subscribe-only untuk browser
    password: 'KS-Web-Sub!2026',
    prefix: 'kalisentinel',                      // awalan topik
    onNode: function () {},                      // dipanggil saat data HULU/HILIR masuk
    onAnalisis: function () {},                  // dipanggil saat hasil server AI masuk
    onStatus: function () {},                    // 'menghubungkan' | 'terhubung' | 'terputus' | 'galat: ...'
    onError: function (e) { console.warn('[KALI-Sentinel MQTT]', e); }
  };

  var PARAMS = ['ph', 'temperature_c', 'turbidity_ntu', 'tds_ppm_est', 'water_level_cm'];

  /** Ubah teks JSON dari ESP32 menjadi objek yang rapi dan aman dipakai. */
  function parseNode(topic, text) {
    var j = JSON.parse(text);
    var node = String(j.node_id || topic.split('/').pop()).toUpperCase();
    if (node !== 'HULU' && node !== 'HILIR') throw new Error('node_id tidak dikenal: ' + node);
    var t = Date.parse(j.timestamp);
    var out = { node_id: node, timestamp: j.timestamp, t: isNaN(t) ? Date.now() : t };
    PARAMS.forEach(function (k) {
      var v = Number(j[k]);
      out[k] = j[k] != null && isFinite(v) ? v : NaN; // NaN = data kosong / rusak
    });
    if (j.rssi != null) out.rssi = Number(j.rssi);   // kekuatan sinyal WiFi (opsional)
    return out;
  }

  function connect(options) {
    var o = Object.assign({}, DEFAULTS, options || {});
    if (!global.mqtt) {
      o.onStatus('galat: mqtt.js belum dimuat');
      throw new Error('Muat dulu https://unpkg.com/mqtt@5.10.1/dist/mqtt.min.js');
    }
    var topics = [o.prefix + '/node/HULU', o.prefix + '/node/HILIR', o.prefix + '/analisis'];

    o.onStatus('menghubungkan');
    var mqttOpts = {
      clientId: 'ks-web-' + Math.random().toString(16).slice(2, 10), // harus unik per pengunjung
      reconnectPeriod: 5000,   // coba sambung ulang tiap 5 detik bila putus
      connectTimeout: 8000,
      clean: true
    };
    if (o.username) mqttOpts.username = o.username;
    if (o.password) mqttOpts.password = o.password;
    var client = global.mqtt.connect(o.broker, mqttOpts);

    client.on('connect', function () {
      o.onStatus('terhubung');
      client.subscribe(topics, { qos: 0 }, function (err) {
        if (err) o.onError(err);
      });
    });
    client.on('reconnect', function () { o.onStatus('menghubungkan'); });
    client.on('close', function () { o.onStatus('terputus'); });
    client.on('error', function (e) { o.onStatus('galat: ' + e.message); o.onError(e); });

    client.on('message', function (topic, payload) {
      var text = payload.toString();
      try {
        if (topic === o.prefix + '/analisis') o.onAnalisis(JSON.parse(text));
        else { var d = parseNode(topic, text); o.onNode(d.node_id, d); }
      } catch (e) {
        o.onError('Pesan di ' + topic + ' tidak bisa dibaca: ' + e.message);
      }
    });

    return {
      client: client,
      /** Kirim pesan uji (misalnya dari tombol di halaman). */
      publish: function (node, data) {
        client.publish(o.prefix + '/node/' + node, JSON.stringify(Object.assign({ node_id: node }, data)));
      },
      disconnect: function () { client.end(true); }
    };
  }

  global.KaliSentinelMQTT = { connect: connect, parseNode: parseNode, PARAMS: PARAMS };
})(typeof window !== 'undefined' ? window : globalThis);
