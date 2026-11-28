const mqtt = require('mqtt');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { rootCertificates } = require('node:tls');

module.exports = async function live(req, res) {
  if (req.method !== 'GET') {
    res.setHeader('Allow', 'GET');
    return res.status(405).end();
  }

  const { MQTT_HOST, MQTT_TLS_PORT, MQTT_USERNAME, MQTT_PASSWORD, MQTT_PREFIX } = process.env;
  if (!MQTT_HOST || !MQTT_USERNAME || !MQTT_PASSWORD || !MQTT_PREFIX || /[+#]/.test(MQTT_PREFIX)) {
    return res.status(503).end('Konfigurasi MQTT belum siap.');
  }
  const topics = ['node/HULU', 'node/HILIR', 'analisis'].map(name => MQTT_PREFIX + '/' + name);
  const client = mqtt.connect({
    protocol: 'mqtts',
    host: MQTT_HOST,
    port: Number(MQTT_TLS_PORT || 8883),
    username: MQTT_USERNAME,
    password: MQTT_PASSWORD,
    ca: [...rootCertificates, readFileSync(join(process.cwd(), 'emqxsl-ca.crt'))],
    reconnectPeriod: 0,
    connectTimeout: 8000
  });

  res.writeHead(200, {
    'Content-Type': 'text/event-stream; charset=utf-8',
    'Cache-Control': 'no-store, no-transform'
  });
  res.write('retry: 2000\n\n');
  await new Promise(resolve => {
    let finished = false;
    const timeout = setTimeout(finish, 54000);
    function finish() {
      if (finished) return;
      finished = true;
      clearTimeout(timeout);
      client.end(true);
      res.end();
      resolve();
    }
    res.once('close', finish);
    client.once('close', finish);
    client.on('error', finish);
    client.on('connect', () => {
      client.subscribe(topics, (error, grants) => {
        if (finished) return;
        if (error || grants.length !== topics.length || grants.some(g => g.qos > 2)) return finish();
        res.write('event: ready\ndata: {}\n\n');
      });
    });
    client.on('message', (topic, payload) => {
      if (!finished && topics.includes(topic)) {
        res.write('data: ' + JSON.stringify([topic, payload.toString()]) + '\n\n');
      }
    });
  });
};
