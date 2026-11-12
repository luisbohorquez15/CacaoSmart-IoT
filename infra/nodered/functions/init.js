// Inicialización: mapa dispositivo -> zona (jerarquía de tópicos) y configuración de las APIs
const zones = {
  'dev-01': 'lote1', 'dev-02': 'lote1', 'dev-05': 'lote1', 'dev-06': 'lote1',
  'dev-03': 'clima', 'dev-04': 'clima',
  'dev-07': 'beneficio', 'dev-08': 'beneficio',
  'dev-09': 'historico', 'dev-10': 'historico'
};
global.set('zones', zones);
global.set('region', 'santander');
const base = { power: 'on', mode: 'auto', lat: Number(env.get('FARM_LAT') || 6.8817), lon: Number(env.get('FARM_LON') || -73.4103), last: 0, seq: 0, ok: 1 };
if (!flow.get('dev-03')) flow.set('dev-03', { ...base, interval_s: 600, name: 'Estación meteo exterior (Azure Maps Current Conditions)' });
if (!flow.get('dev-04')) flow.set('dev-04', { ...base, interval_s: 900, ahorro_agua: 1, name: 'Pronóstico de precipitación (Azure Maps Hourly Forecast)' });
// Al arrancar se fuerza una consulta inmediata de ambas APIs
const c3 = flow.get('dev-03'); c3.last = 0; flow.set('dev-03', c3);
const c4 = flow.get('dev-04'); c4.last = 0; flow.set('dev-04', c4);
node.status({ fill: 'green', shape: 'dot', text: 'inicializado' });
return [{ topic: 'dev-03', force: true }, { topic: 'dev-04', force: true }];
