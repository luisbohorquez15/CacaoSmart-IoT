// Normaliza la respuesta JSON de Azure Maps al contrato de telemetría CacaoSmart y genera el estado.
// Salida 1 -> telemetry (MQTT)   Salida 2 -> status retenido (MQTT)
const dev = msg.device;
const cfg = flow.get(dev);
const zone = 'clima';
const nowIso = new Date().toISOString().replace(/\.\d+Z$/, 'Z');
const t = (k) => `cacaosmart/santander/${zone}/${dev}/${k}`;
const v = (o) => (o && typeof o.value === 'number') ? o.value : null;

function buildStatus() {
  const s = { online: cfg.ok ? 1 : 0, device: dev, name: cfg.name, type: 'api', power: cfg.power, interval_s: cfg.interval_s,
              mode: cfg.mode, lat: cfg.lat, lon: cfg.lon, ts: nowIso, source: 'Azure Maps Weather v1.1' };
  if (dev === 'dev-04') s.ahorro_agua = cfg.ahorro_agua ? 1 : 0;
  if (cfg.error) s.error = cfg.error;
  if (cfg.last_cmd) s.last_cmd = cfg.last_cmd;
  return JSON.stringify(s);
}

if (msg.statusCode !== 200 || !msg.payload || typeof msg.payload !== 'object') {
  cfg.ok = 0; cfg.error = `HTTP ${msg.statusCode}`; flow.set(dev, cfg);
  node.status({ fill: 'red', shape: 'ring', text: cfg.error });
  return [null, { topic: t('status'), payload: buildStatus(), qos: 1, retain: true }];
}
cfg.seq = (cfg.seq || 0) + 1; cfg.ok = 1; delete cfg.error;
let tele;
if (dev === 'dev-03') {
  const r = msg.payload.results[0];
  const ps = r.precipitationSummary || {};
  tele = {
    ts: nowIso, type: 'api', seq: cfg.seq,
    temp_c: v(r.temperature), sensacion_c: v(r.realFeelTemperature), punto_rocio_c: v(r.dewPoint),
    hr_pct: r.relativeHumidity, uv_index: r.uvIndex, viento_kmh: v(r.wind && r.wind.speed),
    viento_dir_deg: r.wind && r.wind.direction ? r.wind.direction.degrees : null,
    rafaga_kmh: v(r.windGust && r.windGust.speed), nubosidad_pct: r.cloudCover, presion_hpa: v(r.pressure),
    visibilidad_km: v(r.visibility), lluvia_1h_mm: v(ps.pastHour) || 0, lluvia_24h_mm: v(ps.past24Hours) || 0,
    es_dia: r.isDayTime ? 1 : 0, condition: r.phrase
  };
} else {
  const f = msg.payload.forecasts || [];
  const f0 = f[0] || {};
  const prob = (x) => x.precipitationProbability || 0;
  tele = {
    ts: nowIso, type: 'api', seq: cfg.seq,
    prob_lluvia_pct: prob(f0),
    prob_lluvia_3h_pct: Math.max(0, ...f.slice(0, 3).map(prob)),
    prob_lluvia_max_12h: Math.max(0, ...f.map(prob)),
    precip_12h_mm: Math.round(f.reduce((s, x) => s + (v(x.totalLiquid) || 0), 0) * 10) / 10,
    horas_lluvia_12h: f.filter(x => x.hasPrecipitation).length,
    nubosidad_pct: f0.cloudCover, temp_prox_h_c: v(f0.temperature),
    uv_max_12h: Math.max(0, ...f.map(x => x.uvIndex || 0)),
    ahorro_agua: cfg.ahorro_agua ? 1 : 0, condition: f0.iconPhrase
  };
}
for (const k of Object.keys(tele)) if (tele[k] === null || tele[k] === undefined) delete tele[k];
flow.set(dev, cfg);
node.status({ fill: 'green', shape: 'dot', text: `${dev} #${cfg.seq}: ${tele.condition || ''}` });
return [{ topic: t('telemetry'), payload: JSON.stringify(tele), qos: 1, retain: true },
        { topic: t('status'), payload: buildStatus(), qos: 1, retain: true }];
