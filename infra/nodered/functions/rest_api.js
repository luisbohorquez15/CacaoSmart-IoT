// API REST de CacaoSmart (endpoints HTTP sobre Node-RED, publicados por Caddy en https://<dominio>/api/...)
//   POST /api/ingest/:device            ingesta de telemetría por HTTP (DEV-10)      [Bearer API_TOKEN]
//   POST /api/devices/:device/command   envía un comando de retroceso                [Bearer API_TOKEN]
//   GET  /api/devices                   último dato + estado de los 10 dispositivos  [público]
//   GET  /api/health                    estado del servicio                           [público]
// Salida 1 -> MQTT   Salida 2 -> respuesta HTTP
const zones = global.get('zones') || {};
const route = msg.req.route.path;
const method = msg.req.method;
const res = (code, body) => [null, { ...msg, statusCode: code, payload: body, headers: { 'Content-Type': 'application/json' } }];
const authed = (msg.req.headers.authorization || '') === `Bearer ${env.get('API_TOKEN')}`;

if (route === '/api/health') {
  return res(200, { ok: true, service: 'cacaosmart-nodered', time: new Date().toISOString(), devices: Object.keys(zones).length });
}
if (route === '/api/devices' && method === 'GET') {
  const latest = global.get('latest') || {}, shadow = global.get('shadow') || {};
  const out = {};
  for (const d of Object.keys(zones).sort()) {
    out[d] = { zone: zones[d], status: shadow[d] || null, last: latest[d] ? latest[d].data : null,
               last_seen_s: latest[d] ? Math.round((Date.now() - latest[d].at) / 1000) : null };
  }
  return res(200, out);
}
if (!authed) return res(401, { error: 'token inválido o ausente (Authorization: Bearer <API_TOKEN>)' });

const dev = msg.req.params.device;
if (!zones[dev]) return res(404, { error: `dispositivo desconocido: ${dev}` });
const body = typeof msg.payload === 'object' && msg.payload !== null ? msg.payload : null;
if (!body) return res(400, { error: 'se esperaba un cuerpo JSON' });

if (route === '/api/ingest/:device') {
  body.ts = body.ts || new Date().toISOString().replace(/\.\d+Z$/, 'Z');
  const topic = `cacaosmart/santander/${zones[dev]}/${dev}/telemetry`;
  node.status({ fill: 'green', shape: 'dot', text: `ingest ${dev} #${body.seq || ''}` });
  return [{ topic, payload: JSON.stringify(body), qos: 1 }, { ...msg, statusCode: 202, payload: { accepted: true, topic } }];
}
if (route === '/api/devices/:device/command') {
  if (!body.cmd) return res(400, { error: 'falta el campo "cmd"' });
  const cid = body.cid || ('a' + Date.now().toString(36));
  const out = { ...body, cmd: String(body.cmd).toUpperCase(), cid, src: 'api', ts: new Date().toISOString() };
  const topic = `cacaosmart/santander/${zones[dev]}/${dev}/command`;
  node.status({ fill: 'blue', shape: 'dot', text: `cmd ${dev} ${out.cmd}` });
  return [{ topic, payload: JSON.stringify(out), qos: 1 }, { ...msg, statusCode: 202, payload: { sent: true, cid, topic, command: out } }];
}
return res(404, { error: 'ruta no encontrada' });
