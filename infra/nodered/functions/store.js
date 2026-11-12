// Guarda el último dato y el último estado de cada dispositivo (vista en memoria / "digital shadow")
const parts = msg.topic.split('/');
const dev = parts[3], kind = parts[4];
if (typeof msg.payload !== 'object' || msg.payload === null) return null;
const key = kind === 'telemetry' ? 'latest' : 'shadow';
const all = global.get(key) || {};
all[dev] = kind === 'telemetry' ? { at: Date.now(), data: msg.payload } : msg.payload;
global.set(key, all);
if (kind === 'status') {
  // Alerta de dispositivo fuera de línea (Last Will publicado por el broker)
  const prev = context.get('online') || {};
  const was = prev[dev];
  prev[dev] = msg.payload.online;
  context.set('online', prev);
  if (was === 1 && msg.payload.online === 0) {
    const zones = global.get('zones') || {};
    return { topic: `cacaosmart/santander/${zones[dev] || parts[2]}/${dev}/alert`, qos: 1,
             payload: JSON.stringify({ ts: new Date().toISOString(), rule: 'offline', severity: 'warning',
                                       msg: `${dev} perdió conexión con el broker (LWT)`, value: 0 }) };
  }
}
return null;
