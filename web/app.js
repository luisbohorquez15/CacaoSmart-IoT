/* =====================================================================
 *  CacaoSmart IoT · Panel de control (front)
 *  Cliente MQTT 3.1.1 sobre WebSocket seguro (wss://<dominio>/mqtt) usando MQTT.js.
 *  - Suscribe: cacaosmart/+/+/+/telemetry | status | alert | command
 *  - Publica (sólo operador): cacaosmart/<region>/<zona>/<dev>/command  QoS 1
 *  - Confirma el retroceso comparando el "cid" del comando con status.last_cmd.cid (ACK)
 * ===================================================================== */
const REGION = 'santander';
const VIEWER = { username: 'viewer', password: 'viewer' };   // usuario público de sólo lectura (ACL)
const WS_URL = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/mqtt`;

const T = { real: 'Real · ESP32', api: 'API · Azure Maps', twin: 'Gemelo digital', dataset: 'Dataset' };
const ACCENT = { real: '#7fb069', api: '#5b8def', twin: '#b565d8', dataset: '#d4a24c' };
const PROTO = { real: 'MQTT/TCP', api: 'HTTPS REST → MQTT', twin: 'MQTT/TCP', dataset: 'MQTT', 'dev-10': 'HTTP REST' };

// ---------------------------------------------------------------- catálogo de dispositivos
const N = (name, cmd, extra = {}) => ({ name, cmd, ...extra });
const num = (name, label, def, min, max, step = 1) => ({ name, label, type: 'number', def, min, max, step });
const sel = (name, label, options, def) => ({ name, label, type: 'select', options, def: def ?? options[0] });
const rng = (name, label, def, min, max, step = 1) => ({ name, label, type: 'range', def, min, max, step });
const COMMON = [N('Intervalo de muestreo', 'SET_INTERVAL', { fields: [num('value', 'segundos', 30, 5, 3600)] }),
                N('Encender / apagar telemetría', 'POWER', { fields: [sel('state', 'estado', ['on', 'off'])] }),
                N('Ping (verifica ACK)', 'PING')];

const DEVICES = {
  'dev-01': { zone: 'lote1', type: 'real', title: 'Nodo microclima lote 1', hw: 'ESP32 + DHT22 + LDR',
    vars: [['temp_c', 'Temperatura', '°C', 1], ['hr_pct', 'Humedad rel.', '%', 1], ['luz_lux', 'Luz', 'lux', 0], ['rssi_dbm', 'Wi-Fi RSSI', 'dBm', 0]],
    ctl: [N('Calibración remota (Lazo 3)', 'CALIBRATE', { desc: 'Offset de temperatura y frecuencia de muestreo sin reprogramar el ESP32.',
            fields: [num('temp_offset', 'offset T (°C)', -0.8, -5, 5, 0.1), num('hr_offset', 'offset HR (%)', 0, -10, 10, 0.5), num('interval_sec', 'muestreo (s)', 10, 5, 60)] }),
          N('LED indicador', 'LED', { fields: [sel('state', 'estado', ['on', 'off'])] }),
          N('Borrar calibración', 'RESET_CALIBRATION'), N('Reiniciar nodo', 'REBOOT', { danger: true })] },
  'dev-02': { zone: 'lote1', type: 'real', title: 'Nodo suelo y riego', hw: 'ESP32 + capacitivo + relé',
    vars: [['humedad_suelo_pct', 'Humedad suelo', '%', 1], ['valvula', 'Electroválvula', '', 0, true], ['bateria_v', 'Batería', 'V', 2], ['umbral_pct', 'Umbral riego', '%', 0]],
    ctl: [N('Riego manual (relé)', 'RELAY', { fields: [sel('state', 'relé', ['ON', 'OFF']), num('duration_min', 'minutos', 15, 1, 120)] }),
          N('Umbral mínimo de disparo', 'SET_THRESHOLD', { fields: [num('value', '% humedad', 35, 10, 60)] }),
          N('Modo de operación', 'SET_MODE', { desc: 'En manual el nodo ignora las órdenes automáticas del motor de reglas.', fields: [sel('value', 'modo', ['auto', 'manual'])] }),
          N('Calibrar sensor capacitivo', 'CALIBRATE', { fields: [num('dry_raw', 'ADC en aire', 3050, 0, 4095), num('wet_raw', 'ADC en agua', 1250, 0, 4095)] })] },
  'dev-03': { zone: 'clima', type: 'api', title: 'Estación meteo exterior', hw: 'Azure Maps · Current Conditions',
    vars: [['temp_c', 'Temperatura', '°C', 1], ['hr_pct', 'Humedad rel.', '%', 0], ['uv_index', 'Índice UV', '', 0], ['viento_kmh', 'Viento', 'km/h', 1]],
    ctl: [N('Intervalo de polling', 'SET_INTERVAL', { desc: 'Mínimo 60 s para cuidar la cuota de Azure Maps.', fields: [num('value', 'segundos', 600, 60, 3600, 60)] }),
          N('Consultar ahora', 'POLL_NOW'),
          N('Cambiar coordenadas', 'SET_LOCATION', { fields: [num('lat', 'latitud', 6.8817, -90, 90, 0.0001), num('lon', 'longitud', -73.4103, -180, 180, 0.0001)] }),
          N('Encender / apagar consultas', 'POWER', { fields: [sel('state', 'estado', ['on', 'off'])] })], noCommon: true },
  'dev-04': { zone: 'clima', type: 'api', title: 'Pronóstico de precipitación', hw: 'Azure Maps · Hourly Forecast',
    vars: [['prob_lluvia_pct', 'Lluvia próx. hora', '%', 0], ['prob_lluvia_max_12h', 'Máx. 12 h', '%', 0], ['precip_12h_mm', 'Lluvia 12 h', 'mm', 1], ['nubosidad_pct', 'Nubosidad', '%', 0]],
    ctl: [N('Modo "Ahorro de agua"', 'AHORRO_AGUA', { desc: 'Inhibe el riego automático si la probabilidad de lluvia es > 65 %.', fields: [sel('state', 'estado', ['on', 'off'])] }),
          N('Intervalo de polling', 'SET_INTERVAL', { fields: [num('value', 'segundos', 900, 60, 3600, 60)] }),
          N('Consultar ahora', 'POLL_NOW')], noCommon: true },
  'dev-05': { zone: 'lote1', type: 'twin', title: 'Polisombra motorizada', hw: 'Gemelo · malla Raschel 70 %',
    vars: [['cierre_pct', 'Cierre malla', '%', 0], ['rad_filtrada_wm2', 'Rad. filtrada', 'W/m²', 0], ['rad_ext_wm2', 'Rad. exterior', 'W/m²', 0], ['corriente_a', 'Corriente motor', 'A', 2]],
    ctl: [N('Cierre de la polisombra', 'SET_SHADE', { fields: [rng('value', '% de cierre', 50, 0, 100, 5)] }),
          N('Modo de operación', 'SET_MODE', { fields: [sel('value', 'modo', ['auto', 'manual'])] })] },
  'dev-06': { zone: 'lote1', type: 'twin', title: 'Bomba y caudalímetro de goteo', hw: 'Gemelo · bomba centrífuga',
    vars: [['caudal_lpm', 'Caudal', 'L/min', 1], ['presion_psi', 'Presión', 'PSI', 1], ['consumo_l', 'Consumo hoy', 'L', 0], ['bomba', 'Bomba', '', 0, true]],
    ctl: [N('Encender bomba', 'START', { fields: [num('duration_min', 'minutos', 10, 1, 120), num('flow', 'L/min', 30, 5, 45)] }),
          N('Apagar bomba', 'STOP'),
          N('Caudal objetivo', 'SET_FLOW', { fields: [rng('value', 'L/min', 30, 5, 45)] }),
          N('Simular fuga (prueba del interlock)', 'LEAK', { desc: 'La presión cae < 12 PSI y la bomba se apaga sola (seguridad en el borde).', fields: [sel('state', 'fuga', ['on', 'off'])], danger: true })] },
  'dev-07': { zone: 'beneficio', type: 'twin', title: 'Cajón de fermentación #1', hw: 'Gemelo · masa de cacao',
    vars: [['temp_masa_c', 'T. masa', '°C', 1], ['ph_mucilago', 'pH mucílago', '', 2], ['horas_fermentacion', 'Horas', 'h', 1], ['volteos', 'Volteos', '', 0]],
    ctl: [N('Voltear la masa', 'VOLTEO', { desc: 'Enfría ~3 °C y oxigena (activa la fase acética).' }),
          N('Iniciar nuevo ciclo', 'RESET_CYCLE', { danger: true }),
          N('Modo de operación', 'SET_MODE', { fields: [sel('value', 'modo', ['auto', 'manual'])] })] },
  'dev-08': { zone: 'beneficio', type: 'twin', title: 'Marquesina de secado solar', hw: 'Gemelo · secador tipo invernadero',
    vars: [['humedad_grano_pct', 'Humedad grano', '%', 1], ['temp_interna_c', 'T. interna', '°C', 1], ['hr_interna_pct', 'HR interna', '%', 0], ['extractores', 'Extractores', '', 0, true]],
    ctl: [N('Extractores', 'EXTRACTORES', { fields: [sel('state', 'estado', ['on', 'off'])] }),
          N('Compuertas', 'COMPUERTAS', { fields: [sel('state', 'estado', ['open', 'close'])] }),
          N('Nuevo lote (55 %)', 'RESET_BATCH', { danger: true }),
          N('Modo de operación', 'SET_MODE', { fields: [sel('value', 'modo', ['auto', 'manual'])] })] },
  'dev-09': { zone: 'historico', type: 'dataset', title: 'Histórico climático cosecha 2025', hw: 'Dataset ERA5 (Open-Meteo)',
    vars: [['temp_ref_c', 'T. 2025', '°C', 1], ['humedad_suelo_ref_pct', 'Suelo 2025', '%', 1], ['et0_dia_mm', 'ET0 24 h', 'mm', 2], ['hr_ref_pct', 'HR 2025', '%', 0]],
    ctl: [N('Pausar reproducción', 'PAUSE'), N('Reanudar', 'RESUME'),
          N('Velocidad de inyección', 'SET_SPEED', { desc: '1 = sincronizado con hace un año; > 1 = acelerado.', fields: [num('value', 'x veces', 60, 1, 1440)] }),
          N('Inyectar anomalía térmica', 'INJECT_ANOMALY', { fields: [num('delta_c', 'Δ °C', 6, -15, 15, 0.5), num('minutes', 'minutos', 20, 1, 240)] })] },
  'dev-10': { zone: 'historico', type: 'dataset', title: 'Curva ideal de secado', hw: 'Dataset benchmark (Page)',
    vars: [['humedad_objetivo_pct', 'Humedad ideal', '%', 1], ['temp_optima_c', 'T. óptima', '°C', 1], ['indice_calidad', 'Índice calidad', '', 0], ['hora_curva', 'Hora del lote', 'h', 1]],
    ctl: [N('Perfil de referencia', 'SET_PROFILE', { fields: [sel('value', 'perfil', ['sol_intenso', 'nublado'])] }),
          N('Pausar', 'PAUSE'), N('Reanudar', 'RESUME')] },
};

// ---------------------------------------------------------------- estado
const S = { client: null, operator: false, msgs: 0, cmds: 0, alerts: 0, filter: 'all', pending: new Map(),
            data: {}, status: {}, hist: {}, lastSeen: {}, open: null };
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const topic = (dev, kind) => `cacaosmart/${REGION}/${DEVICES[dev].zone}/${dev}/${kind}`;
const hhmm = (d = new Date()) => d.toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

// ---------------------------------------------------------------- MQTT
function connect(creds) {
  if (S.client) S.client.end(true);
  const c = mqtt.connect(WS_URL, { ...creds, clientId: `panel-${creds.username}-${Math.random().toString(16).slice(2, 8)}`,
                                   protocolVersion: 4, clean: true, reconnectPeriod: 3000, connectTimeout: 8000 });
  S.client = c;
  c.on('connect', () => {
    setConn(true);
    c.subscribe(['cacaosmart/+/+/+/telemetry', 'cacaosmart/+/+/+/status', 'cacaosmart/+/+/+/alert', 'cacaosmart/+/+/+/command'], { qos: 1 });
  });
  c.on('reconnect', () => setConn(false, 'reconectando…'));
  c.on('close', () => setConn(false));
  c.on('error', (e) => {
    setConn(false, 'error');
    if (/auth|Not authorized|Bad user/i.test(e.message)) { toast('Usuario o contraseña incorrectos'); S.operator = false; connect(VIEWER); }
  });
  c.on('message', onMessage);
}

function onMessage(t, buf) {
  S.msgs++; $('#kpi-msgs .k-val').textContent = S.msgs.toLocaleString('es-CO');
  const [, , , dev, kind] = t.split('/');
  if (!DEVICES[dev]) return;
  let p; try { p = JSON.parse(buf.toString()); } catch { return; }
  if (kind === 'telemetry') {
    S.data[dev] = p; S.lastSeen[dev] = Date.now();
    const h = (S.hist[dev] ||= {});
    for (const [k, v] of Object.entries(p)) if (typeof v === 'number') { (h[k] ||= []).push(v); if (h[k].length > 60) h[k].shift(); }
    renderCard(dev, true);
  } else if (kind === 'status') {
    S.status[dev] = p;
    const lc = p.last_cmd;
    if (lc && lc.cid) resolveAck(lc);   // ACK de comandos del panel, de la API y del motor de reglas
    renderCard(dev); updateOnline();
    if (S.open === dev) renderState(dev);
  } else if (kind === 'alert') {
    addAlert(dev, p);
  } else if (kind === 'command') {
    S.cmds++; $('#kpi-cmds .k-val').textContent = S.cmds;
    if (!S.pending.has(p.cid)) addCmd(dev, p, 'pending');
  }
}

function send(dev, cmd, params = {}) {
  if (!S.operator) { openLogin(); return; }
  const cid = 'p' + Date.now().toString(36);
  const body = { cmd, ...params, cid, src: 'panel', ts: new Date().toISOString() };
  S.pending.set(cid, { dev, cmd, at: Date.now() });
  addCmd(dev, body, 'pending');
  S.client.publish(topic(dev, 'command'), JSON.stringify(body), { qos: 1 }, (err) => { if (err) toast('No autorizado para publicar'); });
  setTimeout(() => { if (S.pending.has(cid)) { S.pending.delete(cid); markCmd(cid, 'fail', 'sin ACK en 15 s (¿dispositivo fuera de línea?)'); } }, 15000);
}

function resolveAck(lc) {
  S.pending.delete(lc.cid);
  markCmd(lc.cid, lc.ok ? 'ok' : 'fail', lc.msg);
}

// ---------------------------------------------------------------- render
function setConn(on, txt) {
  const el = $('#conn');
  el.className = 'pill ' + (on ? 'pill-on' : 'pill-off');
  el.textContent = on ? `● en línea · ${S.operator ? 'operador' : 'lectura'}` : `● ${txt || 'desconectado'}`;
}

function spark(arr) {
  if (!arr || arr.length < 2) return '';
  const min = Math.min(...arr), max = Math.max(...arr), r = max - min || 1;
  const pts = arr.map((v, i) => `${(i / (arr.length - 1)) * 100},${20 - ((v - min) / r) * 18}`).join(' ');
  return `<svg viewBox="0 0 100 22" preserveAspectRatio="none"><polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="1.6" vector-effect="non-scaling-stroke" opacity=".75"/></svg>`;
}

function renderGrid() {
  const g = $('#grid');
  g.innerHTML = '';
  for (const [dev, d] of Object.entries(DEVICES)) {
    if (S.filter !== 'all' && d.type !== S.filter) continue;
    const el = document.createElement('article');
    el.className = 'card'; el.id = `card-${dev}`; el.style.setProperty('--accent', ACCENT[d.type]);
    g.appendChild(el);
    renderCard(dev);
  }
}

function renderCard(dev, flash) {
  const el = $(`#card-${dev}`); if (!el) return;
  const d = DEVICES[dev], st = S.status[dev] || {}, data = S.data[dev] || {}, h = S.hist[dev] || {};
  const online = st.online === 1;
  const seen = S.lastSeen[dev] ? `hace ${Math.round((Date.now() - S.lastSeen[dev]) / 1000)} s` : 'sin datos aún';
  el.classList.toggle('offline', !online);
  el.innerHTML = `
    <div class="card-head">
      <div>
        <div class="card-id">${dev.toUpperCase()}</div>
        <h3>${esc(d.title)}</h3>
        <div class="badges"><span class="badge ${d.type}">${T[d.type]}</span><span class="badge">${PROTO[dev] || PROTO[d.type]}</span>
        ${st.mode === 'manual' ? '<span class="badge" style="color:var(--amber)">manual</span>' : ''}
        ${st.power === 'off' ? '<span class="badge" style="color:var(--red)">apagado</span>' : ''}</div>
      </div>
      <span class="dot ${online ? 'on' : ''}" title="${online ? 'en línea' : 'fuera de línea'}"></span>
    </div>
    <div class="vars">${d.vars.map(([k, n, u, dec, bool]) => {
      const v = data[k];
      const txt = v === undefined ? '–' : bool ? (v ? 'ON' : 'OFF') : Number(v).toFixed(dec);
      return `<div class="var" style="color:${ACCENT[d.type]}"><div class="n">${n}</div>
        <div class="v" style="color:var(--text)">${txt}<span class="u">${v === undefined || bool ? '' : u}</span></div>${bool ? '' : spark(h[k])}</div>`;
    }).join('')}</div>
    <div class="card-foot"><span>${esc(d.hw)} · ${seen}</span><button class="btn btn-sm" data-open="${dev}">Controlar ↩</button></div>`;
  if (flash) { el.classList.add('flash'); setTimeout(() => el.classList.remove('flash'), 600); }
}

function updateOnline() {
  const n = Object.keys(DEVICES).filter(d => (S.status[d] || {}).online === 1).length;
  $('#kpi-online .k-val').textContent = `${n}/10`;
}

function feedPush(ul, li) {
  const empty = ul.querySelector('.empty'); if (empty) empty.remove();
  ul.prepend(li);
  while (ul.children.length > 60) ul.lastChild.remove();
}

function addAlert(dev, a) {
  S.alerts++; $('#kpi-alerts .k-val').textContent = S.alerts;
  const li = document.createElement('li');
  li.className = a.severity || 'info';
  li.innerHTML = `<div class="t"><span>${dev.toUpperCase()} · ${esc(a.rule)}</span><span>${hhmm()}</span></div>${esc(a.msg)}`;
  feedPush($('#alerts'), li);
}

function addCmd(dev, c, cls) {
  const li = document.createElement('li');
  li.className = cls; li.dataset.cid = c.cid;
  const params = Object.entries(c).filter(([k]) => !['cmd', 'cid', 'src', 'ts'].includes(k)).map(([k, v]) => `${k}=${v}`).join(' ');
  const src = { rules: '⚙ reglas', panel: '👤 panel', api: '🔌 API' }[c.src] || c.src;
  li.innerHTML = `<div class="t"><span>${dev.toUpperCase()} ← <b>${esc(c.cmd)}</b> ${esc(params)}</span><span>${src} · ${hhmm()}</span></div><span class="ack">esperando ACK…</span>`;
  feedPush($('#cmdlog'), li);
}

function markCmd(cid, cls, msg) {
  const li = $(`#cmdlog li[data-cid="${cid}"]`); if (!li) return;
  li.className = cls;
  li.querySelector('.ack').textContent = (cls === 'ok' ? '✔ ACK: ' : '✖ ') + msg;
}

// ---------------------------------------------------------------- drawer de control
function openCtl(dev) {
  const d = DEVICES[dev];
  S.open = dev;
  $('#ctrl-type').className = `badge ${d.type}`; $('#ctrl-type').textContent = T[d.type];
  $('#ctrl-title').textContent = `${dev.toUpperCase()} · ${d.title}`;
  $('#ctrl-topic').textContent = topic(dev, 'command');
  renderState(dev);
  const ctls = d.noCommon ? d.ctl : [...d.ctl, ...COMMON];
  $('#ctrl-body').innerHTML = ctls.map((c, i) => `
    <form class="ctl" data-i="${i}">
      <h4>${esc(c.name)}</h4>${c.desc ? `<p>${esc(c.desc)}</p>` : ''}
      <div class="fields">
        ${(c.fields || []).map(f => f.type === 'select'
          ? `<label>${f.label}<select name="${f.name}">${f.options.map(o => `<option ${o === f.def ? 'selected' : ''}>${o}</option>`).join('')}</select></label>`
          : f.type === 'range'
          ? `<label>${f.label}: <b data-out="${f.name}">${f.def}</b><input type="range" name="${f.name}" min="${f.min}" max="${f.max}" step="${f.step}" value="${f.def}"></label>`
          : `<label>${f.label}<input type="number" name="${f.name}" min="${f.min}" max="${f.max}" step="${f.step}" value="${f.def}"></label>`).join('')}
        <button class="btn btn-sm ${c.danger ? 'btn-danger' : 'btn-gold'}">Enviar ${esc(c.cmd)}</button>
      </div>
    </form>`).join('');
  $('#ctrl-body').querySelectorAll('form').forEach(f => {
    f.addEventListener('input', e => { if (e.target.type === 'range') f.querySelector(`[data-out="${e.target.name}"]`).textContent = e.target.value; });
    f.addEventListener('submit', e => {
      e.preventDefault();
      const c = ctls[Number(f.dataset.i)];
      const params = {};
      for (const fl of c.fields || []) {
        const v = f.elements[fl.name].value;
        params[fl.name] = fl.type === 'select' ? v : Number(v);
      }
      send(dev, c.cmd, params);
    });
  });
  $('#ctrl-hint').innerHTML = S.operator ? 'Los comandos viajan con QoS 1 y el dispositivo confirma en su tópico <code>status</code> (retenido).'
                                         : '🔒 Inicia sesión como operador para enviar comandos.';
  $('#ctrl').showModal();
}

function renderState(dev) {
  const st = S.status[dev] || {};
  const lc = st.last_cmd || {};
  const off = st.offsets && Object.keys(st.offsets).length ? Object.entries(st.offsets).map(([k, v]) => `${k}: ${v}`).join(', ') : '—';
  $('#ctrl-state').innerHTML = `
    <div><b>Conexión</b><br>${st.online === 1 ? '🟢 en línea' : '🔴 fuera de línea'}</div>
    <div><b>Telemetría</b><br>${st.power || '–'} · cada ${st.interval_s ?? '–'} s</div>
    <div><b>Modo</b><br>${st.mode || '–'}</div>
    <div><b>Calibración</b><br>${esc(off)}</div>
    <div style="grid-column:1/-1"><b>Último comando</b><br>${lc.cmd ? `${esc(lc.cmd)} (${esc(lc.src)}) → ${lc.ok ? '✔' : '✖'} ${esc(lc.msg)}` : '—'}</div>`;
}

// ---------------------------------------------------------------- sesión
function openLogin() { $('#login').showModal(); }
$('#loginBtn').addEventListener('click', () => {
  if (S.operator) { S.operator = false; $('#role').textContent = 'Lectura'; $('#loginBtn').textContent = 'Iniciar sesión de operador'; connect(VIEWER); }
  else openLogin();
});
$('#loginCancel').addEventListener('click', () => $('#login').close());
$('#loginForm').addEventListener('submit', (e) => {
  e.preventDefault();
  const f = e.target;
  S.operator = true;
  connect({ username: f.u.value, password: f.p.value });
  $('#role').textContent = `Operador (${f.u.value})`;
  $('#loginBtn').textContent = 'Cerrar sesión';
  $('#login').close();
  if (S.open) $('#ctrl-hint').textContent = 'Sesión de operador activa.';
});

function toast(msg) {
  const t = document.createElement('div'); t.className = 'toast'; t.textContent = msg;
  document.body.appendChild(t); setTimeout(() => t.remove(), 3500);
}

document.addEventListener('click', (e) => {
  const o = e.target.closest('[data-open]'); if (o) openCtl(o.dataset.open);
  const chip = e.target.closest('.chip');
  if (chip) { document.querySelectorAll('.chip').forEach(c => c.classList.remove('active')); chip.classList.add('active'); S.filter = chip.dataset.f; renderGrid(); }
});
$('#ctrl').addEventListener('close', () => { S.open = null; });
setInterval(() => Object.keys(DEVICES).forEach(d => { const el = $(`#card-${d} .card-foot span`); if (el && S.lastSeen[d]) el.textContent = `${DEVICES[d].hw} · hace ${Math.round((Date.now() - S.lastSeen[d]) / 1000)} s`; }), 5000);

renderGrid();
connect(VIEWER);
