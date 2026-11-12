// Planificador de consultas a Azure Maps. Respeta el intervalo configurable por retroceso
// (SET_INTERVAL) y el encendido/apagado (POWER). msg.force = consulta inmediata (POLL_NOW).
const dev = msg.topic;
const cfg = flow.get(dev);
if (!cfg) return null;
const now = Date.now();
if (!msg.force && (cfg.power !== 'on' || now - cfg.last < cfg.interval_s * 1000)) return null;
const key = env.get('AZURE_MAPS_KEY');
if (!key || key.startsWith('pon-aqui')) { node.status({ fill: 'red', shape: 'ring', text: 'falta AZURE_MAPS_KEY' }); return null; }
cfg.last = now;
flow.set(dev, cfg);
const q = `${cfg.lat},${cfg.lon}`;
const base = 'https://atlas.microsoft.com/weather';
const out = { device: dev, method: 'GET', headers: { Accept: 'application/json' } };
out.url = dev === 'dev-03'
  ? `${base}/currentConditions/json?api-version=1.1&query=${q}&details=true&language=es-419&subscription-key=${key}`
  : `${base}/forecast/hourly/json?api-version=1.1&query=${q}&duration=12&language=es-419&subscription-key=${key}`;
node.status({ fill: 'blue', shape: 'dot', text: `${dev} consultado ${new Date().toISOString().slice(11, 19)}Z` });
return out;
