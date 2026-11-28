/*
 * tide.js: transisi ombak Jagakali.
 * Saat halaman dibuka: layar tertutup air lalu surut dengan tiga lapis gelombang.
 * Kunjungan pertama di sesi ini: logo tetes air terisi dulu sebelum surut.
 * Saat pindah halaman (beranda <-> dashboard): air pasang menutup layar, lalu pindah.
 * Butuh elemen <div id="tide"><canvas></canvas></div> di awal <body>.
 * Tanpa JavaScript, CSS halaman menyembunyikan #tide setelah 3 detik.
 */
(function () {
  'use strict';
  var el = document.getElementById('tide');
  var root = document.documentElement;
  var reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  function ready() { root.classList.add('ready'); window.dispatchEvent(new Event('tide:done')); }
  if (!el) { ready(); return; }
  el.style.animation = 'none'; el.style.visibility = 'visible';   // matikan pengaman CSS: JS yang mengatur
  if (reduce) { el.style.display = 'none'; ready(); return; }

  var cv = el.querySelector('canvas'), ctx = cv.getContext('2d'), W = 0, H = 0;
  var LAYERS = ['#12A5B5', '#1E6FB0', '#0B1F2E'];          // belakang, tengah, depan
  function size() {
    W = innerWidth; H = innerHeight;
    var d = Math.min(2, devicePixelRatio || 1);
    cv.width = W * d; cv.height = H * d; cv.style.width = W + 'px'; cv.style.height = H + 'px';
    ctx.setTransform(d, 0, 0, d, 0, 0);
  }
  size(); addEventListener('resize', size);
  var ease = function (t) { return t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; };
  var clamp = function (v) { return v < 0 ? 0 : v > 1 ? 1 : v; };

  // gelembung dan kawanan ikan kecil di dalam air transisi
  var BUB = [], FISH = [];
  for (var b = 0; b < 36; b++) BUB.push({ x: (b * 0.6180339) % 1, p: (b * 0.377) % 1, v: .35 + (b % 5) * .09, r: 1.5 + (b % 4) * 1.2, s: b });
  for (var f = 0; f < 14; f++) FISH.push({ dx: (f % 5) * 26 + (f * 13) % 17, dy: Math.floor(f / 5) * 15 + (f * 7) % 9 - 18, l: 7 + (f % 3) * 2, ph: f });
  function fish(t, a) {
    if (a <= 0) return;
    var cx = -160 + t * W * .62, cy = H * .76;
    ctx.fillStyle = 'rgba(255,255,255,' + (.16 * a) + ')'; ctx.beginPath();
    for (var i = 0; i < FISH.length; i++) {
      var q = FISH[i], x = cx + q.dx + Math.sin(t * 2 + q.ph) * 4, y = cy + q.dy + Math.sin(t * 3 + q.ph * 1.7) * 3, l = q.l, w = Math.sin(t * 14 + q.ph) * l * .22;
      ctx.moveTo(x + l, y); ctx.quadraticCurveTo(x, y - l * .4, x - l * .7, y + w * .3); ctx.lineTo(x - l * 1.15, y - l * .34 + w);
      ctx.lineTo(x - l * 1.15, y + l * .34 + w); ctx.lineTo(x - l * .7, y + w * .3); ctx.quadraticCurveTo(x, y + l * .4, x + l, y);
    }
    ctx.fill();
  }
  function bubbles(top, t) {
    ctx.strokeStyle = 'rgba(255,255,255,.28)'; ctx.lineWidth = 1.2;
    for (var i = 0; i < BUB.length; i++) {
      var q = BUB[i], y = H + 20 - ((t * q.v + q.p) % 1) * (H + 60), x = q.x * W + Math.sin(t * 3 + q.s) * 5;
      if (y < top + 24) continue;
      ctx.beginPath(); ctx.arc(x, y, q.r, 0, 7); ctx.stroke();
    }
  }
  function water(levels, t) {
    for (var i = 0; i < 3; i++) {
      var y = levels[i]; if (y > H + 40) continue;
      ctx.beginPath(); ctx.moveTo(0, H + 10);
      for (var x = 0; x <= W + 12; x += 12) {
        ctx.lineTo(x, y + Math.sin(x * .011 + t * 3.1 + i * 1.7) * 16 + Math.sin(x * .026 - t * 2.3 + i) * 8);
      }
      ctx.lineTo(W, H + 10); ctx.closePath(); ctx.fillStyle = LAYERS[i]; ctx.fill();
      if (i === 2) bubbles(y, t);
      // garis buih di puncak gelombang
      ctx.strokeStyle = 'rgba(255,255,255,' + (i === 2 ? .18 : .28) + ')'; ctx.lineWidth = 2; ctx.beginPath();
      for (x = 0; x <= W + 12; x += 12) {
        var yy = y + Math.sin(x * .011 + t * 3.1 + i * 1.7) * 16 + Math.sin(x * .026 - t * 2.3 + i) * 8;
        x ? ctx.lineTo(x, yy) : ctx.moveTo(x, yy);
      }
      ctx.stroke();
    }
  }
  function dropPath(cx, cy, s) {
    ctx.beginPath(); ctx.moveTo(cx, cy - s * 1.4);
    ctx.bezierCurveTo(cx + s * .35, cy - s * .9, cx + s, cy - s * .3, cx + s, cy + s * .2);
    ctx.arc(cx, cy + s * .2, s, 0, Math.PI, false);
    ctx.bezierCurveTo(cx - s, cy - s * .3, cx - s * .35, cy - s * .9, cx, cy - s * 1.4);
    ctx.closePath();
  }
  function logo(fill, alpha, t) {
    if (alpha <= 0) return;
    var cx = W / 2, cy = H / 2 - 30, s = 38;
    ctx.save(); ctx.globalAlpha = alpha;
    dropPath(cx, cy, s); ctx.save(); ctx.clip();
    var top = cy + s * 1.2 - fill * s * 2.65;
    var g = ctx.createLinearGradient(0, top, 0, cy + s * 1.2); g.addColorStop(0, '#3FD0DC'); g.addColorStop(1, '#1E6FB0');
    ctx.fillStyle = g; ctx.beginPath(); ctx.moveTo(cx - s - 4, cy + s * 1.3);
    for (var x = cx - s - 4; x <= cx + s + 4; x += 3) ctx.lineTo(x, top + Math.sin(x * .12 + t * 6) * 3);
    ctx.lineTo(cx + s + 4, cy + s * 1.3); ctx.closePath(); ctx.fill(); ctx.restore();
    dropPath(cx, cy, s); ctx.strokeStyle = '#fff'; ctx.lineWidth = 2.5; ctx.stroke();
    ctx.fillStyle = '#fff'; ctx.font = '600 26px Outfit, system-ui, sans-serif'; ctx.textAlign = 'center';
    ctx.fillText('Jagakali', cx, cy + s * 1.2 + 44);
    ctx.font = '400 14px "IBM Plex Sans", system-ui, sans-serif'; ctx.fillStyle = 'rgba(255,255,255,.7)';
    ctx.fillText('Menyiapkan pantauan Kali Surabaya', cx, cy + s * 1.2 + 70);
    ctx.restore();
  }

  function play(opts, done) {
    var t0 = performance.now();
    function frame(now) {
      var ms = now - t0, t = ms / 1000, fin = opts(ms, t);
      ctx.clearRect(0, 0, W, H); water(fin.levels, t); fish(t, fin.fish || 0); logo(fin.fill || 0, fin.logo || 0, t);
      if (fin.end) { done && done(); return; }
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  var arrived = false, first = true;
  try { arrived = sessionStorage.getItem('jk-tide') === '1'; sessionStorage.removeItem('jk-tide');
        first = !sessionStorage.getItem('jk-seen'); sessionStorage.setItem('jk-seen', '1'); } catch (e) {}
  var withLogo = first && !arrived;
  var FILL = withLogo ? 1000 : 0, HOLD = withLogo ? 260 : 120, DRAIN = 1050;

  function intro() {
    el.style.display = 'block'; el.classList.add('on');
    play(function (ms) {
      var lv = [], start = FILL + HOLD;
      for (var i = 0; i < 3; i++) {
        var p = clamp((ms - start - (2 - i) * 130) / DRAIN);       // lapis depan surut duluan
        lv.push(-70 + (H + 160) * ease(p));
      }
      if (ms > start + 120) root.classList.add('ready');
      return { levels: lv, fill: ease(clamp(ms / Math.max(FILL, 1))), logo: withLogo ? 1 - clamp((ms - start) / 260) : 0,
               fish: withLogo ? 1 - clamp((ms - start) / 300) : 0,
               end: ms > start + 2 * 130 + DRAIN };
    }, function () { el.style.display = 'none'; el.classList.remove('on'); ready(); });
  }

  var busy = false;
  function cover(cb) {
    if (busy) return; busy = true;
    el.style.display = 'block'; el.classList.add('on');
    play(function (ms) {
      var lv = [];
      for (var i = 0; i < 3; i++) { var p = clamp((ms - i * 90) / 640); lv.push(H + 90 - (H + 170) * ease(p)); }
      return { levels: lv, end: ms > 2 * 90 + 680 };
    }, cb);
  }

  // pindah halaman: hanya tautan ke halaman lain di situs yang sama
  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a[href]');
    if (!a || e.defaultPrevented || e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || a.target) return;
    var u; try { u = new URL(a.getAttribute('href'), location.href); } catch (x) { return; }
    if (u.origin !== location.origin || u.pathname === location.pathname) return;
    e.preventDefault();
    cover(function () { try { sessionStorage.setItem('jk-tide', '1'); } catch (x) {} location.href = u.href; });
  });
  // kembali lewat tombol back (bfcache): jangan biarkan layar tertutup air
  addEventListener('pageshow', function (e) { if (e.persisted) { busy = false; el.style.display = 'none'; ready(); } });

  intro();
  window.JagakaliTide = { cover: cover };
})();
