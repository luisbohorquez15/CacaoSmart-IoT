// =====================================================================
//  MOTOR DE REGLAS CacaoSmart IoT  (retroceso automático / lazos de control)
//  Se ejecuta con CADA mensaje de telemetría. Patrón de "reconciliación": compara el estado
//  deseado con el estado real reportado por el dispositivo (status retenido) y sólo envía
//  comandos cuando difieren, con tiempos de enfriamiento para evitar oscilaciones.
//
//  Lazo 1  Protección solar ......... UV (DEV-03) >= 8 -> polisombra DEV-05 al 80 % + LED DEV-01
//  Lazo 2  Riego predictivo ......... suelo DEV-02 < umbral -> consulta lluvia DEV-04 -> relé DEV-02 + bomba DEV-06
//  Lazo 4  Fermentación ............. masa DEV-07 > 50 °C o 48/96 h -> VOLTEO
//  Lazo 5  Secado ................... marquesina DEV-08 > 45 °C -> extractores + compuertas; lluvia -> cerrar
//  Alertas Moniliasis, fuga, sobrecalentamiento, desviación vs. curva ideal (DEV-10), anomalía DEV-09
//  (El Lazo 3, calibración remota, lo ejecuta el operador desde el panel o la API REST.)
//  Salida 1 -> comandos (MQTT .../command)   Salida 2 -> alertas (MQTT .../alert)
// =====================================================================
const p = msg.payload;
if (typeof p !== 'object' || p === null) return null;
const dev = msg.topic.split('/')[3];
const zones = global.get('zones') || {};
const latest = global.get('latest') || {};
const shadow = global.get('shadow') || {};
const st = context.get('st') || {};
const now = Date.now();
const cmds = [], alerts = [];
const iso = () => new Date().toISOString().replace(/\.\d+Z$/, 'Z');

function cmd(target, body) {
  const cid = 'r' + now.toString(36) + Math.floor(Math.random() * 1296).toString(36);
  cmds.push({ topic: `cacaosmart/santander/${zones[target]}/${target}/command`, qos: 1,
              payload: JSON.stringify({ ...body, src: 'rules', cid, ts: iso() }) });
}
function alert(target, rule, severity, text, value, cooldownMin) {
  const k = `al:${rule}:${target}`;
  if (st[k] && now - st[k] < (cooldownMin || 60) * 60000) return;
  st[k] = now;
  alerts.push({ topic: `cacaosmart/santander/${zones[target]}/${target}/alert`, qos: 1,
                payload: JSON.stringify({ ts: iso(), rule, severity, msg: text, value: Number(value) || 0 }) });
}
function cool(k, min) {               // true si ya pasó el enfriamiento (y lo reinicia)
  if (st[k] && now - st[k] < min * 60000) return false;
  st[k] = now; return true;
}
const data = (d) => (latest[d] && latest[d].data) || {};
const fresh = (d, maxMin) => !!latest[d] && now - latest[d].at < (maxMin || 30) * 60000;
const sh = (d) => shadow[d] || {};
const manual = (d) => sh(d).mode === 'manual';
const online = (d) => sh(d).online === 1;

switch (dev) {
  // ---------------------------------------------------------- LAZO 1: protección solar
  case 'dev-03': {
    const uv = Number(p.uv_index);
    let deseado = null;
    if (uv >= 8) deseado = 80;
    else if (uv <= 5) deseado = 30;                         // histéresis 5..8
    const actual = sh('dev-05').objetivo_pct;
    if (deseado !== null && online('dev-05') && !manual('dev-05') && actual !== deseado && cool('shade', 5)) {
      cmd('dev-05', { cmd: 'SET_SHADE', value: deseado });
      cmd('dev-01', { cmd: 'LED', state: deseado === 80 ? 'on' : 'off' });
      if (deseado === 80) alert('dev-03', 'uv_alto', 'warning', `Índice UV ${uv} ≥ 8: polisombra al 80 % y LED de aviso encendido`, uv, 180);
    }
    if (Number(p.temp_c) >= 34) alert('dev-03', 'calor_extremo', 'warning', `Temperatura exterior ${p.temp_c} °C: riesgo de estrés térmico en plántulas`, p.temp_c, 240);
    break;
  }
  // ---------------------------------------------------------- LAZO 2: riego predictivo
  case 'dev-02': {
    const h = Number(p.humedad_suelo_pct);
    const umbral = Number(p.umbral_pct || 35);
    if (h < umbral && !p.valvula && !manual('dev-02') && cool('riego', 45)) {
      const fc = data('dev-04');
      const prob = fresh('dev-04', 60) ? Number(fc.prob_lluvia_3h_pct ?? fc.prob_lluvia_pct) : null;
      const ahorro = sh('dev-04').ahorro_agua !== 0;
      if (prob !== null && prob > 65 && ahorro) {
        alert('dev-02', 'riego_inhibido', 'info', `Suelo ${h} % < ${umbral} %, pero lluvia ${prob} % > 65 %: riego bloqueado (ahorro hídrico)`, h, 60);
      } else {
        const mins = (prob === null || prob < 30) ? 15 : 8;   // lluvia incierta 30-65 % -> riego reducido
        cmd('dev-02', { cmd: 'RELAY', state: 'ON', duration_min: mins });
        cmd('dev-06', { cmd: 'START', duration_min: mins, flow: 30 });
        alert('dev-02', 'riego_auto', 'info', `Riego automático ${mins} min (suelo ${h} %, prob. lluvia ${prob === null ? 's/d' : prob + ' %'})`, h, 30);
      }
    }
    if (Number(p.bateria_v) > 0 && Number(p.bateria_v) < 3.5) alert('dev-02', 'bateria_baja', 'warning', `Batería del nodo ${p.bateria_v} V`, p.bateria_v, 360);
    break;
  }
  // ---------------------------------------------------------- Moniliasis (microclima)
  case 'dev-01': {
    const riesgo = Number(p.hr_pct) > 88 && Number(p.temp_c) > 26;
    if (riesgo) {
      st.monil = st.monil || now;
      const horas = (now - st.monil) / 3600000;
      if (horas >= 4) alert('dev-01', 'moniliasis', 'critical', `Riesgo de Moniliasis: HR > 88 % y T > 26 °C sostenidos ${horas.toFixed(1)} h`, p.hr_pct, 360);
    } else st.monil = null;
    break;
  }
  // ---------------------------------------------------------- Bomba (fugas)
  case 'dev-06': {
    if (Number(p.emergencia) === 1) alert('dev-06', 'fuga', 'critical', `Parada de emergencia de la bomba: presión ${p.presion_psi} PSI (posible fuga)`, p.presion_psi, 30);
    else if (Number(p.bomba) === 1 && Number(p.presion_psi) < 15) alert('dev-06', 'presion_baja', 'warning', `Presión de línea baja ${p.presion_psi} PSI`, p.presion_psi, 30);
    break;
  }
  // ---------------------------------------------------------- LAZO 4: fermentación
  case 'dev-07': {
    const t = Number(p.temp_masa_c), h = Number(p.horas_fermentacion), v = Number(p.volteos);
    if (!manual('dev-07')) {
      if (t > 50 && cool('volteo', 120)) {
        cmd('dev-07', { cmd: 'VOLTEO' });
        alert('dev-07', 'fermentacion_alta', 'warning', `Masa a ${t} °C (> 50 °C): volteo automático`, t, 120);
      } else if ((h >= 48 && v < 1) || (h >= 96 && v < 2)) {
        if (cool('volteo_prog', 60)) cmd('dev-07', { cmd: 'VOLTEO' });
      }
    }
    if (h > 60 && h < 110 && t < 35) alert('dev-07', 'fermentacion_fria', 'warning', `Fermentación fría (${t} °C en fase acética): revisar masa`, t, 240);
    break;
  }
  // ---------------------------------------------------------- LAZO 5: secado
  case 'dev-08': {
    const t = Number(p.temp_interna_c);
    const lluvia = Number(data('dev-03').lluvia_1h_mm || 0) > 0 ||
                   (fresh('dev-04', 60) && Number(data('dev-04').prob_lluvia_pct) >= 65);
    let ext = Number(p.extractores), comp = Number(p.compuertas);
    let extD = ext, compD = comp;
    if (t > 45) { extD = 1; compD = 1; }
    else if (t < 40) extD = 0;
    if (t <= 45) compD = lluvia ? 0 : 1;
    if (!manual('dev-08')) {
      if (extD !== ext && cool('ext', 5)) cmd('dev-08', { cmd: 'EXTRACTORES', state: extD ? 'on' : 'off' });
      if (compD !== comp && cool('comp', 5)) cmd('dev-08', { cmd: 'COMPUERTAS', state: compD ? 'open' : 'close' });
    }
    if (t > 46) alert('dev-08', 'sobrecalentamiento', 'critical', `Marquesina a ${t} °C (> 46 °C): riesgo de acidez y grano arrebatado`, t, 60);
    const ideal = data('dev-10');
    if (fresh('dev-10', 30) && ideal.humedad_objetivo_pct !== undefined) {
      const desv = Number(p.humedad_grano_pct) - Number(ideal.humedad_objetivo_pct);
      if (desv > 8) alert('dev-08', 'secado_retrasado', 'info', `Grano ${desv.toFixed(1)} pts por encima de la curva ideal (${ideal.profile})`, desv, 360);
    }
    if (Number(p.humedad_grano_pct) <= 7) alert('dev-08', 'lote_listo', 'info', `Lote #${p.lote} seco: ${p.humedad_grano_pct} % (≤ 7 %, NTC 1252)`, p.humedad_grano_pct, 720);
    break;
  }
  // ---------------------------------------------------------- Dataset: anomalía inyectada
  case 'dev-09': {
    if (Number(p.anomalia) === 1) alert('dev-09', 'anomalia_dataset', 'warning', `Anomalía térmica inyectada en el histórico: ${p.temp_ref_c} °C`, p.temp_ref_c, 30);
    const actual = data('dev-03').temp_c;
    if (actual !== undefined && fresh('dev-03', 30) && Math.abs(Number(actual) - Number(p.temp_ref_c)) > 6)
      alert('dev-09', 'desviacion_historica', 'info', `Temperatura actual ${actual} °C vs ${p.temp_ref_c} °C hace un año`, Number(actual) - Number(p.temp_ref_c), 360);
    break;
  }
}
context.set('st', st);
if (cmds.length || alerts.length) node.status({ fill: 'yellow', shape: 'dot', text: `${dev}: ${cmds.length} cmd, ${alerts.length} alertas` });
return [cmds, alerts];
