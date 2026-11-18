// =====================================================================
//  DEV-01 · Nodo móvil de campo (iPhone real: página web de sensores en Safari, o apps compatibles)
//  El celular envía sus sensores REALES (luz, presión, micrófono, acelerómetro, batería) por:
//    · MQTT  -> cacaosmart/santander/lote1/dev-01/raw   (usuario "celular", sólo puede escribir ahí)
//    · HTTP  -> POST /api/phone/dev-01?token=...         (alternativa)
//  Esta función actúa como GATEWAY / "device shadow": normaliza el formato de Sensor Logger,
//  promedia el lote, aplica calibración y publica la telemetría estándar con el intervalo
//  configurado. El retroceso (POWER, SET_INTERVAL, CALIBRATE…) se ejecuta en este gateway,
//  porque la app del celular no puede recibir comandos.
//  Salida 1 -> MQTT (telemetry / status)    Salida 2 -> respuesta HTTP
// =====================================================================
const T = (k) => `cacaosmart/santander/lote1/dev-01/${k}`;
const nowIso = () => new Date().toISOString().replace(/\.\d+Z$/, 'Z');
const now = Date.now();
const st = flow.get('dev01') || { power: 'on', interval_s: 30, offsets: {}, mode: 'auto', seq: 0, lastData: 0, lastPub: 0, online: 0,
                                   buf: { luz: [], pres: [], db: [], acc: [], brillo: [], bat: null, carga: null } };
const out = [];
let http = null;

function status() {
  const s = { online: st.online, device: 'dev-01', name: 'Nodo móvil de campo (iPhone · web de sensores)', type: 'real', power: st.power,
              interval_s: st.interval_s, mode: st.mode, offsets: st.offsets, ts: nowIso(), gateway: 'node-red', app: 'sensor.html (Safari, MQTT sobre WSS)' };
  if (st.last_cmd) s.last_cmd = st.last_cmd;
  return { topic: T('status'), payload: JSON.stringify(s), qos: 1, retain: true };
}
const mean = (a) => a.reduce((x, y) => x + y, 0) / a.length;
const r = (x, d) => Math.round(x * 10 ** d) / 10 ** d;
const off = (k) => (k in st.offsets ? st.offsets[k] : (st.offsets[k.split('_')[0]] || 0));

// ------------------------------------------------------------------ 1) datos del celular
function ingest(body) {
  const items = Array.isArray(body && body.payload) ? body.payload : [];
  for (const it of items) {
    const name = String(it.name || '').toLowerCase();
    const v = it.values || {};
    const num = Object.values(v).find(x => typeof x === 'number');
    if (name.includes('light') || name.includes('lux') || name.includes('illuminance')) {
      const lux = v.lux ?? v.illuminance ?? v.light ?? num;
      if (typeof lux === 'number') st.buf.luz.push(lux);
    } else if (name === 'barometer' || name.includes('pressure')) {
      let p = v.pressure ?? num;
      if (typeof p === 'number') { if (p < 200) p *= 10; st.buf.pres.push(p); }       // kPa -> hPa (iOS)
      if (typeof v.relativeAltitude === 'number') (st.buf.alt = st.buf.alt || []).push(v.relativeAltitude);
    } else if (name === 'microphone') {
      if (typeof v.dBFS === 'number') st.buf.db.push(v.dBFS);
    } else if (name === 'accelerometer') {
      if ([v.x, v.y, v.z].every(n => typeof n === 'number')) st.buf.acc.push(Math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z));
    } else if (name === 'brightness') {                                            // brillo automático de pantalla (iOS), 0-1
      if (typeof v.brightness === 'number') st.buf.brillo.push(v.brightness <= 1 ? v.brightness * 100 : v.brightness);
    } else if (name === 'battery') {
      if (typeof v.batteryLevel === 'number') st.buf.bat = v.batteryLevel <= 1 ? v.batteryLevel * 100 : v.batteryLevel;
      if (v.batteryState) st.buf.carga = ['charging', 'full'].includes(v.batteryState) ? 1 : 0;
    }
  }
  st.lastData = now;
  if (!st.online) { st.online = 1; out.push(status()); }
  return items.length;
}

// ------------------------------------------------------------------ 2) publicación periódica
function flush(force) {
  if (st.power !== 'on' || (!force && now - st.lastPub < st.interval_s * 1000)) return;
  const b = st.buf, tele = { ts: nowIso(), type: 'real', seq: ++st.seq };
  if (b.luz.length) tele.luz_lux = r(mean(b.luz) + off('luz_lux'), 1);
  if (b.pres.length) tele.presion_hpa = r(mean(b.pres) + off('presion_hpa'), 2);
  if (b.db.length) tele.ruido_dbfs = r(mean(b.db) + off('ruido_dbfs'), 1);
  if (b.acc.length > 1) {                                                          // movimiento = variabilidad de |a|
    const m = mean(b.acc);
    tele.movimiento = r(Math.sqrt(mean(b.acc.map(a => (a - m) ** 2))), 3);
  }
  if ((b.alt || []).length) tele.altura_rel_m = r(mean(b.alt) + off('altura_rel_m'), 3);
  if ((b.brillo || []).length) tele.brillo_pct = r(mean(b.brillo), 1);
  if (b.bat !== null) tele.bateria_pct = r(b.bat, 1);
  if (b.carga !== null) tele.cargando = b.carga;
  st.buf = { luz: [], pres: [], db: [], acc: [], brillo: [], bat: b.bat, carga: b.carga };
  if (Object.keys(tele).length > 3) { out.push({ topic: T('telemetry'), payload: JSON.stringify(tele), qos: 1 }); st.lastPub = now; }
}

// ------------------------------------------------------------------ 3) retroceso
function command(p) {
  const cmd = String(p.cmd || '').toUpperCase();
  let ok = true, txt = '';
  switch (cmd) {
    case 'POWER': st.power = String(p.state || 'on').toLowerCase() === 'off' ? 'off' : 'on'; txt = `telemetría ${st.power === 'on' ? 'encendida' : 'apagada'}`; break;
    case 'SET_INTERVAL': st.interval_s = Math.max(5, Math.min(3600, Number(p.value) || st.interval_s)); txt = `intervalo = ${st.interval_s}s`; break;
    case 'CALIBRATE': {
      const ch = [];
      for (const [k, v] of Object.entries(p.offsets || {})) { st.offsets[k] = Number(v); ch.push(k); }
      for (const [k, v] of Object.entries(p)) if (k.endsWith('_offset')) { st.offsets[k.slice(0, -7)] = Number(v); ch.push(k.slice(0, -7)); }
      if (p.interval_sec) { st.interval_s = Math.max(5, Math.min(3600, Number(p.interval_sec))); ch.push('intervalo'); }
      txt = ch.length ? 'calibrado: ' + ch.join(', ') : 'sin cambios'; break;
    }
    case 'RESET_CALIBRATION': st.offsets = {}; txt = 'offsets borrados'; break;
    case 'SET_MODE': st.mode = p.value === 'manual' ? 'manual' : 'auto'; txt = `modo ${st.mode}`; break;
    case 'LED':
    case 'ALARMA': txt = `alarma en el iPhone ${String(p.state || 'on').toLowerCase() === 'off' ? 'desactivada' : 'ACTIVADA'} (pantalla naranja + sonido)`; break;
    case 'MEASURE': txt = `medición del iPhone ${String(p.state || 'start')} (ejecutado por el gateway del PC)`; break;
    case 'CLEAR': txt = 'buffers del iPhone limpiados (gateway del PC)'; break;
    case 'PING': txt = st.online ? 'pong (celular transmitiendo)' : 'pong (celular sin datos)'; break;
    default: ok = false; txt = `comando desconocido: ${cmd}`;
  }
  st.last_cmd = { cid: p.cid || '', cmd, src: p.src || 'desconocido', ok: ok ? 1 : 0, msg: txt, at: nowIso() };
  out.push(status());
}

// ------------------------------------------------------------------ enrutamiento
if (msg.req) {                                                                     // HTTP
  const token = msg.req.query.token || (msg.req.headers.authorization || '').replace('Bearer ', '');
  if (token !== env.get('PHONE_TOKEN')) {
    http = { ...msg, statusCode: 499, payload: 'Token inválido: revise la URL de envío' };   // 499: la app muestra el texto
  } else {
    const n = ingest(msg.payload);
    flush(false);
    http = { ...msg, statusCode: 200, payload: { ok: true, lecturas: n } };
  }
} else if (msg.topic === 'tick') {
  if (st.online && now - st.lastData > 120000) { st.online = 0; out.push(status()); }        // sin datos 2 min = offline
  flush(false);
} else if (msg.topic && msg.topic.endsWith('/raw')) {
  ingest(typeof msg.payload === 'object' ? msg.payload : {});
  flush(false);
} else if (msg.topic && msg.topic.endsWith('/command')) {
  command(typeof msg.payload === 'object' ? msg.payload : {});
} else if (msg.topic === 'init') {
  out.push(status());
}
flow.set('dev01', st);
node.status({ fill: st.online ? 'green' : 'grey', shape: 'dot', text: `celular ${st.online ? 'transmitiendo' : 'sin datos'} · #${st.seq}` });
return [out, http];
