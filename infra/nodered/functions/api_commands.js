// Retroceso para los dispositivos API (DEV-03, DEV-04): el "dispositivo" es la integración
// con Azure Maps, así que los comandos cambian cómo y cuándo se consulta la nube.
// Salida 1 -> status (ACK)  Salida 2 -> consulta inmediata
const dev = msg.topic.split('/')[3];
const cfg = flow.get(dev);
if (!cfg) return null;
const p = typeof msg.payload === 'object' ? msg.payload : {};
const cmd = String(p.cmd || p.action || '').toUpperCase();
let ok = true, txt = '', poll = false;
switch (cmd) {
  case 'SET_INTERVAL':
  case 'SET_POLLING': {
    // Azure Maps cobra por transacción: límite inferior de 60 s para no agotar la cuota
    const s = Math.max(60, Math.min(3600, Number(p.value || cfg.interval_s)));
    cfg.interval_s = s; txt = `polling cada ${s}s`; break;
  }
  case 'POWER':
    cfg.power = String(p.state || 'on').toLowerCase() === 'off' ? 'off' : 'on'; txt = `consultas ${cfg.power}`; break;
  case 'SET_LOCATION': {
    const lat = Number(p.lat), lon = Number(p.lon);
    if (isNaN(lat) || isNaN(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) { ok = false; txt = 'coordenadas inválidas'; break; }
    cfg.lat = lat; cfg.lon = lon; poll = true; txt = `ubicación ${lat},${lon}`; break;
  }
  case 'AHORRO_AGUA':
    if (dev !== 'dev-04') { ok = false; txt = 'sólo aplica a DEV-04'; break; }
    cfg.ahorro_agua = ['on', '1', 'true'].includes(String(p.state || 'on').toLowerCase()) ? 1 : 0;
    txt = `modo ahorro de agua ${cfg.ahorro_agua ? 'ACTIVO' : 'inactivo'}`; poll = true; break;
  case 'SET_MODE':
    cfg.mode = p.value === 'manual' ? 'manual' : 'auto'; txt = `modo ${cfg.mode}`; break;
  case 'POLL_NOW':
    poll = true; txt = 'consulta inmediata'; break;
  case 'PING':
    txt = 'pong'; break;
  default:
    ok = false; txt = `comando desconocido: ${cmd}`;
}
cfg.last_cmd = { cid: p.cid || '', cmd, src: p.src || 'desconocido', ok: ok ? 1 : 0, msg: txt, at: new Date().toISOString() };
flow.set(dev, cfg);
node.status({ fill: ok ? 'green' : 'red', shape: 'dot', text: `${dev} ${cmd}: ${txt}` });
const status = { online: cfg.ok ? 1 : 0, device: dev, name: cfg.name, type: 'api', power: cfg.power, interval_s: cfg.interval_s,
                 mode: cfg.mode, lat: cfg.lat, lon: cfg.lon, last_cmd: cfg.last_cmd, ts: new Date().toISOString() };
if (dev === 'dev-04') status.ahorro_agua = cfg.ahorro_agua;
return [{ topic: `cacaosmart/santander/clima/${dev}/status`, payload: JSON.stringify(status), qos: 1, retain: true },
        poll ? { topic: dev, force: true } : null];
