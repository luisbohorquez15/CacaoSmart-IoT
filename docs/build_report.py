"""
Genera el informe final en PDF: docs/Informe_CacaoSmart_IoT.pdf

    python docs/build_report.py            (usa docs/build/stats.json, docs/figuras/*.png y docs/analisis_ia.md)

Edite docs/informe.config.json (integrantes, URL, repositorio) antes de generar la versión final.
El PDF se imprime con Microsoft Edge / Google Chrome en modo headless (sin dependencias extra).
"""
from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

DOCS = Path(__file__).resolve().parent
BUILD = DOCS / "build"
CFG = json.loads((DOCS / "informe.config.json").read_text(encoding="utf-8"))
ST = json.loads((BUILD / "stats.json").read_text(encoding="utf-8"))
E = html.escape


def md(text: str) -> str:
    """Conversor Markdown mínimo (###, listas numeradas/viñetas, **negrita**, `código`)."""
    out, lst = [], None
    for raw in text.splitlines():
        line = raw.strip()
        inline = lambda s: re.sub(r"`([^`]+)`", r"<code>\1</code>", re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", E(s)))  # noqa: E731
        m_ol, m_ul = re.match(r"^\d+\.\s+(.*)", line), re.match(r"^[-*]\s+(.*)", line)
        if lst and not (m_ol and lst == "ol" or m_ul and lst == "ul"):
            out.append(f"</{lst}>"); lst = None
        if line.startswith("### "):
            out.append(f"<h3>{inline(line[4:])}</h3>")
        elif m_ol or m_ul:
            tag = "ol" if m_ol else "ul"
            if not lst:
                out.append(f"<{tag}>"); lst = tag
            out.append(f"<li>{inline((m_ol or m_ul).group(1))}</li>")
        elif line:
            out.append(f"<p>{inline(line)}</p>")
    if lst:
        out.append(f"</{lst}>")
    return "\n".join(out)


def table(headers, rows, cls=""):
    th = "".join(f"<th>{h}</th>" for h in headers)
    trs = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>'


def fig(name, caption, n):
    p = DOCS / "figuras" / name
    if not p.exists():
        return ""
    return f'<figure><img src="{p.as_uri()}"><figcaption><b>Figura {n}.</b> {caption}</figcaption></figure>'


def stats_rows(dev):
    d = ST["dispositivos"].get(dev)
    if not d:
        return ""
    rows = []
    for v in d["variables"].values():
        u = v["unidad"]
        f = lambda x: f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")  # noqa: E731
        rows.append([E(v["etiqueta"]), E(u), f(v["promedio"]), f"{f(v['max'])} <span class='muted'>({v['t_max'][5:16].replace('T', ' ')})</span>",
                     f"{f(v['min'])} <span class='muted'>({v['t_min'][5:16].replace('T', ' ')})</span>", f(v["desv"])])
    return table(["Variable", "Unidad", "Promedio", "Máximo (fecha hora)", "Mínimo (fecha hora)", "Desv. est."], rows, "stats") + \
        f"<p class='note'>{d['muestras']:,} muestras en el periodo.</p>".replace(",", ".")


DEVICES = [
    ("DEV-01", "Nodo microclima lote 1", "Real", "ESP32 + DHT22 + LDR + LED",
     "Temperatura (°C)<br>Humedad relativa (%)<br>Luminosidad (lux)<br>RSSI Wi-Fi (dBm)", "21 – 30 °C<br>70 – 85 %<br>10k – 40k lux<br>−80 – −40 dBm",
     "MQTT/TCP 1883, QoS 1, LWT", "CALIBRATE (offset T/HR, muestreo 5–60 s), LED, POWER, REBOOT"),
    ("DEV-02", "Nodo suelo y actuación", "Real", "ESP32 + sensor capacitivo v1.2 + relé + 18650",
     "Humedad volumétrica suelo (%)<br>Electroválvula (0/1)<br>Batería (V)", "35 – 60 %<br>0 / 1<br>3,3 – 4,2 V",
     "MQTT/TCP 1883, QoS 1, LWT", "RELAY ON/OFF + duración, SET_THRESHOLD, SET_MODE, CALIBRATE seco/húmedo"),
    ("DEV-03", "Estación meteo exterior", "API", "Azure Maps · Get Current Conditions",
     "Temperatura y sensación (°C)<br>HR (%) · punto de rocío<br>Índice UV · nubosidad (%)<br>Viento/ráfaga (km/h) · presión (hPa)<br>Lluvia 1 h / 24 h (mm)",
     "18 – 34 °C<br>40 – 100 %<br>0 – 11+ · 0 – 100 %<br>0 – 25 km/h · 1005 – 1020 hPa<br>0 – 50 mm", "HTTPS REST (polling 10 min) → MQTT",
     "SET_INTERVAL (60–3600 s), SET_LOCATION, POLL_NOW, POWER"),
    ("DEV-04", "Pronóstico de precipitación", "API", "Azure Maps · Get Hourly Forecast (12 h)",
     "Prob. lluvia 1 h / 3 h / 12 h (%)<br>Lluvia esperada 12 h (mm)<br>Nubosidad (%) · UV máx.", "0 – 100 %<br>0 – 50 mm<br>0 – 100 %",
     "HTTPS REST (polling 15 min) → MQTT", "AHORRO_AGUA on/off (inhibe riego si lluvia > 65 %), SET_INTERVAL, POLL_NOW"),
    ("DEV-05", "Polisombra motorizada", "Gemelo digital", "Modelo: geometría solar + Kasten-Czeplak",
     "Cierre de malla (%)<br>Corriente motor (A)<br>Radiación exterior / filtrada (W/m²)", "0 – 100 %<br>0,0 – 2,5 A<br>0 – 1000 / 200 – 600 W/m²",
     "MQTT/TCP", "SET_SHADE 0–100 %, SET_MODE auto/manual"),
    ("DEV-06", "Bomba y caudalímetro de goteo", "Gemelo digital", "Modelo: curva de bomba P = P0 − aQ²",
     "Caudal (L/min)<br>Presión de línea (PSI)<br>Consumo diario (L)", "0 – 45 L/min<br>15 – 35 PSI<br>0 – 5000 L",
     "MQTT/TCP", "START/STOP + duración, SET_FLOW, LEAK (prueba de interlock), RESET_TOTAL"),
    ("DEV-07", "Cajón de fermentación #1", "Gemelo digital", "Modelo: fases levadura → acética",
     "Temperatura de la masa (°C)<br>pH del mucílago<br>Horas de fermentación (h) · volteos", "35 – 50 °C<br>3,8 – 5,2<br>0 – 144 h",
     "MQTT/TCP", "VOLTEO (−3 °C, oxigena), RESET_CYCLE, SET_MODE"),
    ("DEV-08", "Marquesina de secado solar", "Gemelo digital", "Modelo: balance térmico + cinética de Lewis",
     "Humedad del grano (%)<br>Temperatura / HR interna<br>Extractores · compuertas (0/1)", "55 → 7 %<br>28 – 48 °C · 25 – 99 %<br>0 / 1",
     "MQTT/TCP", "EXTRACTORES on/off, COMPUERTAS open/close, RESET_BATCH, SET_MODE"),
    ("DEV-09", "Histórico climático cosecha 2025", "Dataset", "ERA5/ERA5-Land vía Open-Meteo (2 208 h)",
     "Temperatura / HR de referencia<br>Humedad de suelo 0–7 y 7–28 cm (%)<br>ET0 FAO-56 (mm/día) · lluvia · radiación",
     "20 – 31 °C · 65 – 100 %<br>30 – 65 %<br>2,5 – 5,5 mm/día", "MQTT (replay sincronizado t − 365 d)",
     "PAUSE/RESUME, SET_SPEED (×1–×1440), INJECT_ANOMALY (Δ °C, min)"),
    ("DEV-10", "Curva ideal de secado (benchmark)", "Dataset", "Modelo de Page, 2 perfiles × 1 441 puntos",
     "Humedad objetivo (%)<br>Temperatura óptima (°C)<br>Índice de calidad (pts)", "55 → 7 %<br>32 – 42 °C<br>80 – 100 pts",
     "HTTP REST POST /api/ingest", "SET_PROFILE sol_intenso/nublado, PAUSE/RESUME"),
]


def build():
    per = ST["periodo"]
    ini, fin = per["inicio"][:16].replace("T", " "), per["fin"][:16].replace("T", " ")
    sim = ST.get("fuente") == "simulacion"
    ev = ST.get("eventos", {})
    tipos = {(x["kind"], x["name"]): x["n"] for x in ev.get("por_tipo", [])}
    n = iter(range(1, 50))
    arch = (DOCS / "arquitectura.svg").read_text(encoding="utf-8")
    integrantes = "".join(f"<li>{E(x)}</li>" for x in CFG["integrantes"])
    banner = ("<div class='callout warn'><b>Borrador con datos de simulación de validación.</b> Las cifras de las secciones 5 y 6 "
              "provienen de <code>analysis/backfill.py</code> (mismos modelos y motor de reglas, alimentados con el clima real de la finca). "
              "Para la entrega final se regeneran con los 6 días capturados en la nube: <code>export_influx.py → charts.py → ai_analyst.py → build_report.py</code>.</div>") if sim else ""

    body = f"""
<section class="cover">
  <div class="cover-top">Universidad Autónoma de Bucaramanga · {E(CFG['curso'])}</div>
  <div class="cover-mid">
    <div class="emoji">🍫</div>
    <h1>CacaoSmart <span>IoT</span></h1>
    <p class="subtitle">Agricultura de precisión para el cultivo y beneficio de cacao fino de aroma en Santander</p>
    <p class="kicker">Proyecto final · IoT a la medida</p>
  </div>
  <div class="cover-grid">
    <div><h4>Integrantes</h4><ul>{integrantes}</ul></div>
    <div><h4>Plataforma</h4><p><b>Panel:</b><br><a class="url" href="{E(CFG['url'])}/">{E(CFG['url'])}/</a><br><b>Grafana:</b><br><a class="url" href="{E(CFG['url'])}/grafana/">{E(CFG['url'])}/grafana/</a><br><b>GitHub:</b><br><a class="url" href="{E(CFG['github'])}">{E(CFG['github'])}</a></p>
    <p><b>Periodo de datos:</b> {ini} → {fin} ({per['dias']} días)<br><b>Docente:</b> {E(CFG['docente'])}<br><b>Fecha:</b> {E(CFG['fecha'])}</p></div>
  </div>
</section>

<section class="toc">
<h2>Contenido</h2>
<ol>
<li>Descripción y contexto</li><li>Arquitectura de referencia IoT</li><li>Sensores y dispositivos</li>
<li>Comunicación: bróker y protocolos</li><li>Nube y servicios utilizados</li><li>Visualización y procesamiento de datos</li>
<li>Análisis de gráficas y comportamiento (con IA)</li><li>Retroceso: control bidireccional</li><li>Conclusiones</li><li>Referencias</li>
</ol>
<div class="kpis">
<div><b>10</b><span>dispositivos</span></div><div><b>4</b><span>tipos: real · API · gemelo · dataset</span></div>
<div><b>{sum(len(d['variables']) for d in ST['dispositivos'].values())}+</b><span>variables graficadas</span></div>
<div><b>{per['dias']}</b><span>días de datos</span></div><div><b>{ev.get('comandos', 0)}</b><span>comandos de retroceso</span></div>
<div><b>{ev.get('alertas', 0)}</b><span>alertas generadas</span></div></div>
{banner}
</section>

<h2>1. Descripción y contexto</h2>
<h3>Problemática</h3>
<p>Colombia es reconocida por producir <b>cacao fino de aroma</b>, y Santander es el principal departamento productor (cerca del 40 % de la producción nacional según Fedecacao), con San Vicente de Chucurí como su capital cacaotera. Aun así, el cultivo y el beneficio del grano se manejan de forma empírica y pierden calidad y rendimiento por la variabilidad climática:</p>
<ul>
<li><b>Cultivo (vivero y lote).</b> El cacao es una planta umbrófila, sensible al estrés hídrico y al exceso de humedad. La humedad relativa alta sostenida con temperaturas cálidas favorece enfermedades como la <b>Moniliasis</b> (<i>Moniliophthora roreri</i>) y la Escoba de Bruja, responsables de pérdidas de hasta el 80 % de la cosecha en lotes sin manejo.</li>
<li><b>Poscosecha (beneficio).</b> La calidad de exportación depende de que la <b>fermentación</b> alcance 45–50 °C de forma controlada (con volteos que oxigenan la masa) y de que el <b>secado</b> en marquesina reduzca la humedad del grano del 55 % al 7 % (NTC 1252) sin sobrecalentarlo ni rehumedecerlo con lluvias repentinas.</li>
</ul>
<h3>Propuesta de solución</h3>
<p><b>CacaoSmart IoT</b> es un ecosistema de agricultura de precisión desplegado en infraestructura propia en la nube (Azure) con URL propia y HTTPS. Integra telemetría en tiempo real de campo (2 nodos ESP32 reales y 4 gemelos digitales), condiciones y pronósticos meteorológicos hiperlocales (API Azure Maps Weather), datos históricos (datasets ERA5 de la cosecha 2025 y una curva ideal de secado) y un <b>motor de reglas</b> que ejecuta <b>acciones de retroceso</b> sobre riego, sombreo, fermentación y secado. Toda la información se visualiza en Grafana con estadísticos ajustables en el tiempo, y un panel web permite operar cada dispositivo (encender, apagar, calibrar, ajustar).</p>
<h3>Objetivos</h3>
<ol><li>Monitorear en tiempo real 10 dispositivos con múltiples variables durante al menos 4–6 días.</li>
<li>Automatizar decisiones críticas con 5 lazos de control: protección solar, riego predictivo, calibración remota, volteo de fermentación y control de secado.</li>
<li>Comparar el comportamiento actual con referencias históricas (2025) e ideales (benchmark de secado).</li>
<li>Desplegar la solución completa en la nube, reproducible con un solo comando y documentada en GitHub.</li></ol>

<h2>2. Arquitectura de referencia IoT</h2>
<p>La solución sigue una arquitectura de <b>cuatro capas</b> (percepción, transporte, procesamiento y aplicación), alineada con la arquitectura de referencia vista en clase: dispositivos heterogéneos → bróker de mensajería → servicios en la nube (front, back, base de datos y análisis) → visualización. Todos los servicios corren como contenedores Docker en una máquina virtual de Azure.</p>
<figure class="arch">{arch}<figcaption><b>Figura {next(n)}.</b> Arquitectura de referencia de CacaoSmart IoT: flujo de datos (uplink), retroceso (downlink) y servicios.</figcaption></figure>
{table(["Capa", "Componentes", "Función"], [
    ["1 · Percepción y actuación", "ESP32 (DEV-01/02), gemelos Python (DEV-05…08), adaptadores API (DEV-03/04), reproductores de datasets (DEV-09/10)", "Medir variables, ejecutar comandos (relé, LED, motor, extractores) y confirmar con ACK"],
    ["2 · Transporte", "Eclipse Mosquitto 2.0 (MQTT 3.1.1 sobre TCP y WebSocket)", "Publicación/suscripción desacoplada, QoS 1, mensajes retenidos (device shadow), LWT, ACL"],
    ["3 · Procesamiento y persistencia", "Node-RED 4, Telegraf 1.32, InfluxDB 2.7", "Integración con Azure Maps, motor de reglas, API REST, ingesta y almacenamiento de series de tiempo"],
    ["4 · Aplicación", "Grafana 11, panel web (MQTT.js), Caddy 2", "Dashboards, estadísticos, alertas, control remoto y publicación HTTPS con URL propia"]])}
<h3>Flujo de un dato y de un comando</h3>
<ol><li><b>Uplink:</b> el ESP32 publica <code>cacaosmart/santander/lote1/dev-02/telemetry</code> (JSON, QoS 1) → Mosquitto → Telegraf lo escribe en InfluxDB (medición <i>telemetry</i>, etiquetas <i>device, zone, type</i>) y Node-RED lo evalúa en el motor de reglas.</li>
<li><b>Decisión:</b> si la humedad del suelo &lt; umbral, Node-RED consulta el último pronóstico de DEV-04 (Azure Maps) y decide regar, reducir o inhibir el riego.</li>
<li><b>Downlink (retroceso):</b> Node-RED publica <code>{{"cmd":"RELAY","state":"ON","duration_min":15,"src":"rules","cid":"…"}}</code> en <code>…/dev-02/command</code> y <code>START</code> en la bomba DEV-06.</li>
<li><b>ACK:</b> el dispositivo ejecuta y responde en <code>…/status</code> (retenido) con <code>last_cmd.cid</code>, <code>ok</code> y <code>msg</code>; el panel y Grafana muestran la confirmación.</li></ol>

<h2>3. Sensores y dispositivos</h2>
<p>Se implementan <b>10 dispositivos</b> distribuidos en los cuatro tipos exigidos, todos con múltiples variables y capacidad de retroceso. Los gemelos digitales no son señales aleatorias: son <b>modelos físicos</b> alimentados con el clima real que entrega la API de Azure Maps.</p>
{table(["ID", "Dispositivo", "Tipo", "Hardware / fuente", "Variables", "Rangos normales", "Protocolo", "Retroceso (control)"],
       [[f"<b>{a}</b>", b, f"<span class='tag {c.split()[0].lower()}'>{c}</span>", d, e, f, g, h] for a, b, c, d, e, f, g, h in DEVICES], "devices")}

<h2>4. Comunicación: bróker y protocolos</h2>
<h3>Bróker: Eclipse Mosquitto 2.0</h3>
<p>Se eligió <b>MQTT 3.1.1</b> como protocolo principal por su cabecera mínima (2 bytes), el patrón publicación/suscripción que desacopla productores y consumidores, los niveles de calidad de servicio y el soporte nativo de <i>Last Will</i> y mensajes retenidos, características ideales para nodos con batería y conectividad rural intermitente. Mosquitto expone dos listeners: <b>1883 (MQTT/TCP)</b> para dispositivos y servicios, y <b>9001 (MQTT sobre WebSocket)</b>, publicado por Caddy como <code>wss://…/mqtt</code> para el panel web.</p>
{table(["Aspecto", "Diseño"], [
    ["Jerarquía de tópicos", "<code>cacaosmart/&lt;region&gt;/&lt;zona&gt;/&lt;dispositivo&gt;/&lt;tipo&gt;</code> con zonas <i>lote1, clima, beneficio, historico</i>"],
    ["Uplink", "<code>…/telemetry</code> (QoS 1, JSON con <code>ts</code> ISO-8601, <code>type</code>, <code>seq</code> y variables)"],
    ["Estado / ACK", "<code>…/status</code> retenido = <i>device shadow</i>: online, power, intervalo, modo, offsets de calibración y <code>last_cmd</code> {{cid, cmd, src, ok, msg}}"],
    ["Downlink (retroceso)", "<code>…/command</code> QoS 1: <code>{{\"cmd\": \"…\", parámetros, \"cid\", \"src\": \"panel|rules|api\"}}</code>"],
    ["Alertas", "<code>…/alert</code>: regla, severidad (info/warning/critical), mensaje y valor"],
    ["Detección de caída", "LWT retenido <code>{{\"online\":0}}</code> en <code>…/status</code>; Node-RED genera la alerta <i>offline</i>"],
    ["Seguridad", "Sin acceso anónimo; usuarios <i>device, service, viewer, operador</i>; ACL: cada dispositivo sólo publica en sus tópicos (client-id = id); el visor sólo lee; sólo el operador publica comandos; TLS en todo el tráfico web (HTTPS/WSS)"]])}
<div class="code"><b>Ejemplo de telemetría (DEV-07):</b><br><code>cacaosmart/santander/beneficio/dev-07/telemetry</code><br>
<code>{{"ts":"2026-11-08T19:00:00Z","type":"twin","seq":2881,"temp_masa_c":46.89,"ph_mucilago":4.62,"horas_fermentacion":64.0,"volteos":1}}</code></div>
<h3>Otros protocolos del sistema</h3>
{table(["Enlace", "Protocolo", "Envío / recepción"], [
    ["Node-RED → Azure Maps (DEV-03/04)", "HTTPS REST (GET JSON, <code>api-version=1.1</code>, <code>subscription-key</code>)", "Polling configurable (10/15 min, mín. 60 s por cuota); la respuesta se normaliza y se publica por MQTT"],
    ["DEV-10 → plataforma", "HTTP REST <code>POST /api/ingest/dev-10</code> con token Bearer", "Node-RED valida, responde 202 y re-publica en MQTT; el retroceso llega por MQTT"],
    ["Panel web ↔ bróker", "MQTT sobre WebSocket seguro (WSS)", "Suscripción en vivo y publicación de comandos con rol operador"],
    ["Sistemas externos → comandos", "HTTP REST <code>POST /api/devices/:id/command</code>", "Integración con otros sistemas (p. ej. curl, apps móviles)"],
    ["Telegraf ↔ InfluxDB", "HTTP (line protocol)", "Escritura por lotes cada 5 s"]])}
<h3>¿Por qué MQTT y no otro protocolo?</h3>
{table(["Criterio", "MQTT", "HTTP/REST", "CoAP", "AMQP"], [
    ["Modelo", "Pub/Sub vía bróker", "Request/response", "Request/response (+observe)", "Colas/intercambios"],
    ["Transporte", "TCP / WebSocket", "TCP", "UDP", "TCP"],
    ["Sobrecarga", "Muy baja (2 B)", "Alta (cabeceras texto)", "Muy baja (4 B)", "Media-alta"],
    ["Downlink al dispositivo", "Nativo (suscripción)", "Requiere polling", "Observe", "Nativo"],
    ["Presencia (LWT/retenidos)", "Sí", "No", "No", "Parcial"],
    ["Soporte ESP32 / navegador", "Excelente", "Excelente", "Limitado en navegador", "Limitado en ESP32"],
    ["Uso en CacaoSmart", "<b>Principal</b>", "APIs externas, ingesta y API de comandos", "No usado", "No usado"]], "cmp")}

<h2>5. Nube y servicios utilizados</h2>
<p>La plataforma se despliega en una <b>máquina virtual Ubuntu 24.04 (B2s, 2 vCPU, 4 GB) de Microsoft Azure</b> con nombre DNS propio (<code>{E(CFG['url'])}</code>) y certificado TLS de Let's Encrypt emitido automáticamente por Caddy. El grupo de seguridad de red sólo abre 80/443 (web) y 1883 (MQTT para los ESP32). El despliegue completo es <i>infraestructura como código</i>: <code>docker compose up -d</code>.</p>
{table(["Servicio", "Imagen / versión", "Rol en la arquitectura", "Exposición"], [
    ["Mosquitto", "eclipse-mosquitto:2.0.20", "Bróker MQTT (capa 2)", "1883 público · 9001 vía /mqtt"],
    ["Node-RED", "nodered/node-red:4.0.5", "Orquestador: Azure Maps, motor de reglas, API REST", "/api, /nodered (con clave)"],
    ["Telegraf", "telegraf:1.32.3", "Ingesta MQTT → InfluxDB", "interno"],
    ["InfluxDB", "influxdb:2.7.11", "Base de datos de series de tiempo (retención 30 d)", "interno"],
    ["Grafana", "grafana/grafana:11.3.1", "Dashboards, estadísticos y alertas", "/grafana (lectura anónima)"],
    ["twins", "python:3.12-slim + paho-mqtt", "Gemelos digitales DEV-05…08", "interno"],
    ["datasets", "python:3.12-slim + paho-mqtt", "Reproductores DEV-09 (MQTT) y DEV-10 (HTTP)", "interno"],
    ["Caddy", "caddy:2.8.4", "Proxy inverso, HTTPS automático, panel web estático", "80 / 443"],
    ["Azure Maps", "Weather API v1.1 (SaaS)", "Fuente de datos de DEV-03 y DEV-04", "externo"],
    ["Anthropic Claude", "API Messages (claude-opus-5-5)", "Análisis de gráficas con IA", "externo (fuera de línea)"]])}

<h2>6. Visualización y procesamiento de datos</h2>
<p>Grafana se aprovisiona como código con <b>4 dashboards</b> (Visión general, Lote de cultivo, Beneficio y Clima/API/datasets). Todos los paneles de series de tiempo muestran en la leyenda el <b>promedio, máximo, mínimo y último valor</b>, recalculados automáticamente según el <b>selector de tiempo</b> (por defecto 6 días; ajustable a cualquier rango, con agregación dinámica <code>aggregateWindow(v.windowPeriod)</code>). Una tabla Flux calcula promedio, máximo, mínimo y número de muestras de 23 variables para el rango elegido; las anotaciones muestran cada comando de retroceso y cada alerta sobre las gráficas.</p>
<h3>Reglas y alertas</h3>
{table(["Regla (motor Node-RED / Grafana)", "Condición", "Acción de retroceso / notificación"], [
    ["Lazo 1 · Protección solar", "UV (DEV-03) ≥ 8 · histéresis hasta UV ≤ 5", "SET_SHADE 80 % en DEV-05 + LED ON en DEV-01 (y vuelta a 30 %)"],
    ["Lazo 2 · Riego predictivo", "Suelo (DEV-02) &lt; umbral (35 %)", "Lluvia &lt; 30 %: riego 15 min · 30–65 %: 8 min · &gt; 65 %: riego inhibido (ahorro hídrico) — relé DEV-02 + bomba DEV-06"],
    ["Lazo 3 · Calibración remota", "Orden del operador (panel o API REST)", "CALIBRATE offset T/HR e intervalo 5–60 s en el ESP32 (persistido en NVS)"],
    ["Lazo 4 · Fermentación", "Masa (DEV-07) &gt; 50 °C, o 48 h / 96 h sin volteo", "VOLTEO automático"],
    ["Lazo 5 · Secado", "Marquesina (DEV-08) &gt; 45 °C · &lt; 40 °C · lluvia", "Extractores ON + compuertas abiertas · extractores OFF · compuertas cerradas"],
    ["Alerta Moniliasis (crítica)", "HR &gt; 88 % y T &gt; 26 °C sostenidos 4 h (DEV-01)", "Alerta + Telegram + regla Grafana"],
    ["Alerta sobrecalentamiento (crítica)", "Marquesina &gt; 46 °C", "Alerta + Telegram + regla Grafana"],
    ["Alerta fuga (crítica)", "Presión &lt; 12 PSI con bomba encendida", "Interlock local en DEV-06 (parada de emergencia) + alerta"],
    ["Secado retrasado (info)", "Humedad real − ideal (DEV-10) &gt; 8 puntos", "Alerta informativa"],
    ["Dispositivo fuera de línea", "LWT <code>online = 0</code>", "Alerta warning"]])}
<p class="note">El motor de reglas usa un patrón de <b>reconciliación</b> (compara el estado deseado con el reportado en <code>status</code>) con tiempos de enfriamiento, lo que evita oscilaciones y respeta el <b>modo manual</b>: si el operador pone un dispositivo en manual, las órdenes automáticas son rechazadas por el propio dispositivo.</p>

<h2>7. Análisis de gráficas y comportamiento (con IA)</h2>
<p>Periodo analizado: <b>{ini} → {fin}</b> ({per['dias']} días). Para cada dispositivo se presentan las gráficas y los estadísticos calculados con <code>analysis/charts.py</code>. El texto de análisis fue generado por un modelo de lenguaje multimodal (<b>Claude, Anthropic</b>) a partir de las gráficas y los estadísticos (<code>analysis/ai_analyst.py</code>) y revisado por el equipo.</p>
{banner}
<h3>7.1 Clima exterior · DEV-03 y DEV-04 (API Azure Maps)</h3>
{fig("dev03.png", "Condiciones actuales de Azure Maps: temperatura vs. sensación térmica vs. 2025, índice UV y humedad/nubosidad.", next(n))}
{stats_rows("dev-03")}
{fig("dev04.png", "Pronóstico horario de Azure Maps: probabilidad de lluvia y precipitación esperada.", next(n))}
{stats_rows("dev-04")}
<h3>7.2 Microclima y suelo · DEV-01 y DEV-02 (ESP32 reales)</h3>
{fig("dev01.png", "Nodo microclima: temperatura, humedad relativa y luminosidad bajo el dosel.", next(n))}
{stats_rows("dev-01")}
{fig("dev02.png", "Nodo de suelo: humedad volumétrica, umbral, eventos de riego y batería.", next(n))}
{stats_rows("dev-02")}
<h3>7.3 Polisombra y riego · DEV-05 y DEV-06 (gemelos digitales)</h3>
{fig("dev05.png", "Gemelo de la polisombra: radiación exterior vs. filtrada y cierre de la malla.", next(n))}
{stats_rows("dev-05")}
{fig("dev06.png", "Gemelo de la bomba de goteo: caudal, presión y consumo diario.", next(n))}
{stats_rows("dev-06")}
<h3>7.4 Fermentación · DEV-07 (gemelo digital)</h3>
{fig("dev07.png", "Gemelo del cajón de fermentación: temperatura de la masa, volteos y pH.", next(n))}
{stats_rows("dev-07")}
<h3>7.5 Secado · DEV-08 (gemelo) vs. DEV-10 (dataset benchmark)</h3>
{fig("dev08_10.png", "Marquesina de secado frente a la curva ideal y actuadores comandados por el motor de reglas.", next(n))}
{stats_rows("dev-08")}
{stats_rows("dev-10")}
<h3>7.6 Histórico 2025 · DEV-09 (dataset)</h3>
{fig("dev09.png", "Dataset histórico ERA5: comparación interanual y evapotranspiración FAO-56.", next(n))}
{stats_rows("dev-09")}
<h3>7.7 Correlaciones</h3>
{fig("correlaciones.png", "Respuesta del Lazo 1 (UV vs. cierre de malla) y matriz de correlación de Pearson entre series horarias.", next(n))}
<div class="ai"><div class="ai-head">✦ Análisis generado con IA (Claude · Anthropic) a partir de las gráficas y estadísticos</div>
{md((DOCS / "analisis_ia.md").read_text(encoding="utf-8"))}</div>

<h2>8. Retroceso: control bidireccional</h2>
<p>Todos los dispositivos aceptan comandos comunes (<code>POWER</code>, <code>SET_INTERVAL</code>, <code>CALIBRATE</code>, <code>RESET_CALIBRATION</code>, <code>SET_MODE</code>, <code>PING</code>) y comandos propios. Los comandos llegan por tres vías —motor de reglas, panel web (operador autenticado) y API REST— y siempre se confirman en el tópico <code>status</code>.</p>
{fig("eventos.png", "Bitácora del motor de reglas: comandos de retroceso y alertas por dispositivo durante el periodo.", next(n))}
{table(["Tipo", "Evento", "Cantidad"], [[("Comando" if k == "command" else "Alerta"), f"<code>{nm}</code>", v] for (k, nm), v in sorted(tipos.items())])}
<h3>Prueba funcional en vivo (sustentación)</h3>
{table(["Prueba", "Cómo se ejecuta", "Resultado esperado"], [
    ["Calibración del ESP32", "Panel → DEV-01 → CALIBRATE offset −0,8 °C, muestreo 15 s", "ACK ✔ en ~1 s, el valor de temperatura baja 0,8 °C y llega cada 15 s"],
    ["Riego predictivo", "Panel → DEV-02 → SET_THRESHOLD 60 %", "En la siguiente lectura el motor ordena RELAY ON + START bomba (alerta “riego automático”)"],
    ["Interlock de fuga", "Panel → DEV-06 → START y luego LEAK on", "Presión &lt; 12 PSI → parada de emergencia local + alerta crítica en el panel"],
    ["Modo manual", "DEV-05 → SET_MODE manual; esperar UV ≥ 8", "La orden automática SET_SHADE es rechazada (ACK ✖ “modo manual”)"],
    ["Apagado de sensor", "POWER off en cualquier dispositivo", "La serie se interrumpe en Grafana; POWER on la reanuda"],
    ["Dataset", "DEV-09 → INJECT_ANOMALY +6 °C 20 min · DEV-10 → SET_PROFILE nublado", "Alerta de anomalía y cambio de curva de referencia en Grafana"],
    ["API REST", "<code>curl -X POST {E(CFG['url'])}/api/devices/dev-03/command -H 'Authorization: Bearer …' -d '{{\"cmd\":\"POLL_NOW\"}}'</code>", "202 Accepted y nueva consulta a Azure Maps"]])}

<h2>9. Conclusiones</h2>
<ul>
<li>Se construyó una solución IoT completa y desplegable en la nube con los elementos fundamentales: <b>sensores</b> (reales, gemelos, API y datasets), <b>datos y variables</b> (más de 40 variables), <b>protocolos</b> (MQTT/TCP, MQTT/WSS, HTTPS REST), <b>plataforma</b> (Mosquitto, Node-RED, InfluxDB) y <b>visualización</b> (Grafana y panel propio).</li>
<li>El <b>retroceso</b> es el núcleo del sistema: cinco lazos de control conectan variables de distintos dispositivos (p. ej. el pronóstico de Azure Maps decide si un relé físico se activa) y cada orden queda confirmada (ACK) y trazada.</li>
<li>Los <b>gemelos digitales basados en física</b> y alimentados con clima real producen comportamientos interpretables (ciclos diarios, fases de fermentación, secado escalonado) que permiten validar reglas antes de llevarlas al campo.</li>
<li>La comparación con <b>referencias históricas e ideales</b> (datasets) convierte los datos en decisiones: detectar un secado retrasado o un año más cálido de lo normal.</li>
<li>Trabajo futuro: TLS en el puerto MQTT de los ESP32 (8883), modelos predictivos de Moniliasis con aprendizaje automático y despliegue de una malla de sombra sobre la marquesina.</li>
</ul>

<h2>10. Referencias</h2>
<ol class="refs">
<li>Allen, R. G., Pereira, L. S., Raes, D., &amp; Smith, M. (1998). <i>Crop evapotranspiration: Guidelines for computing crop water requirements</i> (FAO Irrigation and Drainage Paper 56). FAO.</li>
<li>Anthropic. (2026). <i>Claude API documentation</i>. https://docs.claude.com</li>
<li>Banks, A., &amp; Gupta, R. (Eds.). (2014). <i>MQTT Version 3.1.1</i>. OASIS Standard. http://docs.oasis-open.org/mqtt/mqtt/v3.1.1/mqtt-v3.1.1.html</li>
<li>Federación Nacional de Cacaoteros – Fedecacao. (2025). <i>Información económica del sector cacaotero</i>. https://www.fedecacao.com.co</li>
<li>Grafana Labs. (2025). <i>Grafana documentation</i>. https://grafana.com/docs/grafana/latest/</li>
<li>Haurwitz, B. (1945). Insolation in relation to cloudiness and cloud density. <i>Journal of Meteorology, 2</i>(3), 154–166.</li>
<li>Hersbach, H., et al. (2020). The ERA5 global reanalysis. <i>Quarterly Journal of the Royal Meteorological Society, 146</i>(730), 1999–2049.</li>
<li>Hii, C. L., Law, C. L., &amp; Cloke, M. (2009). Modeling using a new thin layer drying model and product quality of cocoa. <i>Journal of Food Engineering, 90</i>(2), 191–198.</li>
<li>ICONTEC. (2021). <i>NTC 1252: Cacao en grano</i>. Instituto Colombiano de Normas Técnicas y Certificación.</li>
<li>InfluxData. (2025). <i>InfluxDB OSS v2 documentation</i> y <i>Telegraf MQTT Consumer plugin</i>. https://docs.influxdata.com</li>
<li>Kasten, F., &amp; Czeplak, G. (1980). Solar and terrestrial radiation dependent on the amount and type of cloud. <i>Solar Energy, 24</i>(2), 177–189.</li>
<li>Light, R. A. (2017). Mosquitto: Server and client implementation of the MQTT protocol. <i>Journal of Open Source Software, 2</i>(13), 265.</li>
<li>Microsoft. (2025). <i>Azure Maps Weather REST API (2025-01-01)</i>. https://learn.microsoft.com/es-es/rest/api/maps/weather</li>
<li>Open-Meteo. (2025). <i>Historical Weather API</i>. https://open-meteo.com/en/docs/historical-weather-api</li>
<li>OpenJS Foundation. (2025). <i>Node-RED documentation</i>. https://nodered.org/docs/</li>
<li>Phillips-Mora, W., &amp; Wilkinson, M. J. (2007). Frosty pod of cacao: A disease with a limited geographic range but unlimited potential for damage. <i>Phytopathology, 97</i>(12), 1644–1647.</li>
<li>Schwan, R. F., &amp; Wheals, A. E. (2004). The microbiology of cocoa fermentation and its role in chocolate quality. <i>Critical Reviews in Food Science and Nutrition, 44</i>(4), 205–221.</li>
<li>Tao, F., Zhang, H., Liu, A., &amp; Nee, A. Y. C. (2019). Digital twin in industry: State-of-the-art. <i>IEEE Transactions on Industrial Informatics, 15</i>(4), 2405–2415.</li>
</ol>
"""
    css = (DOCS / "informe.css").read_text(encoding="utf-8")
    page = f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Informe CacaoSmart IoT</title>
<style>{css}</style></head><body>{body}</body></html>"""
    BUILD.mkdir(exist_ok=True)
    out_html = BUILD / "informe.html"
    out_html.write_text(page, encoding="utf-8")
    pdf = DOCS / "Informe_CacaoSmart_IoT.pdf"
    browser = next((p for p in [shutil.which("msedge"), shutil.which("chrome"), shutil.which("google-chrome"), shutil.which("chromium"),
                                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                                r"C:\Program Files\Google\Chrome\Application\chrome.exe"] if p and Path(p).exists()), None)
    if not browser:
        print(f"HTML generado en {out_html}; ábralo e imprímalo a PDF (no se encontró Edge/Chrome)")
        return
    subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={pdf}",
                    out_html.as_uri()], check=True, capture_output=True, timeout=180)
    print(f"PDF: {pdf} ({pdf.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    build()
