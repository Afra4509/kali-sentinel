#!/usr/bin/env node
/*
 * simulator-publisher.js
 * Pengganti ESP32 saat uji: membaca CSV Jagakali lalu mengirimnya ke broker MQTT,
 * persis seperti dua node asli. Dashboard mode LIVE dan server_analisis.py akan menerimanya.
 *
 * Pasang sekali:   npm install
 * Jalankan:        node simulator-publisher.js
 * Opsi:
 *   --file  ../data/jagakali_demo_video_5detik.csv   (default)
 *   --speed 10            kali lebih cepat dari waktu di CSV (default 1)
 *   --broker mqtt://127.0.0.1:1883
 *   --prefix jagakali
 *   --keep-time           pakai timestamp asli CSV. Default: timestamp diganti waktu sekarang,
 *                         supaya dashboard menganggap data ini "live".
 *   --loop                ulang dari awal setelah selesai
 */
'use strict';
const fs = require('fs');
const path = require('path');
const mqtt = require('mqtt');

const args = process.argv.slice(2);
const opt = (name, def) => { const i = args.indexOf('--' + name); return i >= 0 && args[i + 1] && !args[i + 1].startsWith('--') ? args[i + 1] : def; };
const flag = (name) => args.includes('--' + name);

const FILE = path.resolve(__dirname, opt('file', '../data/jagakali_demo_video_5detik.csv'));
const SPEED = Math.max(0.1, Number(opt('speed', '1')));
const BROKER = opt('broker', 'mqtt://127.0.0.1:1883');
const PREFIX = opt('prefix', 'jagakali');
const KEEP_TIME = flag('keep-time');
const LOOP = flag('loop');
const PARAMS = ['ph', 'temperature_c', 'turbidity_ntu', 'tds_ppm_est', 'water_level_cm'];

// --- baca CSV sederhana (tanpa koma di dalam nilai) ---------------------------------
const lines = fs.readFileSync(FILE, 'utf8').trim().split(/\r?\n/);
const head = lines.shift().split(',');
const rows = lines.map((ln) => {
  const c = ln.split(','), o = {};
  head.forEach((h, i) => { o[h] = c[i]; });
  o.t = Date.parse(o.timestamp);
  return o;
}).filter((r) => !isNaN(r.t)).sort((a, b) => a.t - b.t);
if (!rows.length) { console.error('CSV kosong atau kolom timestamp tidak terbaca'); process.exit(1); }

// Waktu WIB dalam format ISO, contoh 2026-12-01T10:15:00+07:00
const isoWIB = (ms) => new Date(ms + 7 * 3600e3).toISOString().slice(0, 19) + '+07:00';

const client = mqtt.connect(BROKER, { clientId: 'ks-sim-' + Math.random().toString(16).slice(2, 8), reconnectPeriod: 3000 });
client.on('error', (e) => console.error('MQTT galat:', e.message));
client.on('connect', () => {
  console.log(`terhubung ke ${BROKER}. Memutar ${rows.length} baris dari ${path.basename(FILE)} pada ${SPEED}x.`);
  play();
});

function play() {
  const t0csv = rows[0].t, t0real = Date.now();
  let i = 0;
  const tick = () => {
    const nowCsv = t0csv + (Date.now() - t0real) * SPEED;
    while (i < rows.length && rows[i].t <= nowCsv) {
      const r = rows[i++];
      const msg = { node_id: r.node_id, timestamp: KEEP_TIME ? r.timestamp : isoWIB(Date.now()) };
      PARAMS.forEach((k) => { msg[k] = r[k] === '' ? null : Number(r[k]); });
      client.publish(`${PREFIX}/node/${r.node_id}`, JSON.stringify(msg), { qos: 0 });
      if (r.node_id === 'HILIR') {
        process.stdout.write(`\r${r.timestamp.slice(11, 19)}  HILIR pH ${msg.ph}  TDS ${msg.tds_ppm_est}  NTU ${msg.turbidity_ntu}  label: ${r.label || '-'}        `);
      }
    }
    if (i >= rows.length) {
      console.log('\nselesai.');
      if (LOOP) return play();
      return setTimeout(() => client.end(), 500);
    }
    setTimeout(tick, 100);
  };
  tick();
}
