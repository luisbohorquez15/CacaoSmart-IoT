"""
Genera los dashboards y las reglas de alerta de Grafana (provisioning como código).
    python scripts/build_dashboards.py
Salida: infra/grafana/dashboards/*.json  e  infra/grafana/provisioning/alerting/rules.yaml
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "infra" / "grafana" / "dashboards"
DS = {"type": "influxdb", "uid": "influx-cacao"}
B = 'from(bucket: "cacaosmart")\n  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n'

C = dict(temp="#E8743B", hr="#4FA3D1", luz="#F2C14E", suelo="#7FB069", rad="#F2A65A", filt="#C8A165", uv="#B565D8",
         pres="#8E9AAF", flow="#3BA99C", cacao="#8B5A2B", gold="#D4A24C", ideal="#9FD8CB", red="#E5484D",
         green="#46A758", grey="#8B8D98", ph="#E54D9F", prob="#5B8DEF")

ANNOTATIONS = {"list": [
    {"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"}, "enable": True, "hide": True,
     "iconColor": "rgba(0, 211, 255, 1)", "name": "Annotations & Alerts", "type": "dashboard"},
    {"datasource": DS, "enable": False, "iconColor": "#D4A24C", "name": "Retroceso (comandos)",
     "target": {"refId": "Anno", "query": B + '  |> filter(fn: (r) => r._measurement == "command" and r._field == "cmd")\n'
                '  |> map(fn: (r) => ({_time: r._time, text: r.device + " ← " + r._value}))'}},
    {"datasource": DS, "enable": False, "iconColor": "#E5484D", "name": "Alertas",
     "target": {"refId": "Anno2", "query": B + '  |> filter(fn: (r) => r._measurement == "alert" and r._field == "msg")\n'
                '  |> map(fn: (r) => ({_time: r._time, text: r.device + ": " + r._value}))'}},
]}


def series_query(series, fn="mean"):
    cond = " or\n      ".join(f'(r.device == "{d}" and r._field == "{f}")' for d, f, *_ in series)
    return (B + '  |> filter(fn: (r) => r._measurement == "telemetry")\n'
            f'  |> filter(fn: (r) => {cond})\n'
            f'  |> aggregateWindow(every: v.windowPeriod, fn: {fn}, createEmpty: false)\n'
            '  |> map(fn: (r) => ({r with _field: r.device + "/" + r._field}))\n'
            '  |> group()\n  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")')


def override(name, **props):
    p = []
    if "label" in props: p.append({"id": "displayName", "value": props["label"]})
    if "color" in props: p.append({"id": "color", "value": {"mode": "fixed", "fixedColor": props["color"]}})
    if "unit" in props: p.append({"id": "unit", "value": props["unit"]})
    if props.get("right"): p.append({"id": "custom.axisPlacement", "value": "right"})
    if props.get("dash"): p.append({"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [10, 6]}})
    if props.get("step"): p.append({"id": "custom.lineInterpolation", "value": "stepAfter"})
    if props.get("bars"):
        p += [{"id": "custom.drawStyle", "value": "bars"}, {"id": "custom.fillOpacity", "value": 60}]
    if "min" in props: p.append({"id": "min", "value": props["min"]})
    if "max" in props: p.append({"id": "max", "value": props["max"]})
    return {"matcher": {"id": "byName", "options": name}, "properties": p}


class Dash:
    def __init__(self, uid, title, desc, tags):
        self.d = {"uid": uid, "title": title, "description": desc, "tags": ["cacaosmart"] + tags, "timezone": "America/Bogota",
                  "editable": True, "graphTooltip": 1, "refresh": "1m", "schemaVersion": 39, "version": 1,
                  "time": {"from": "now-6d", "to": "now"}, "timepicker": {"refresh_intervals": ["30s", "1m", "5m", "15m"]},
                  "annotations": ANNOTATIONS, "panels": [], "templating": {"list": []},
                  "links": [{"title": "Dashboards CacaoSmart", "type": "dashboards", "tags": ["cacaosmart"], "asDropdown": True,
                             "icon": "external link", "includeVars": False, "keepTime": True, "targetBlank": False},
                            {"title": "Panel de control", "type": "link", "url": "/", "icon": "dashboard", "targetBlank": True}]}
        self.id = 1
        self.y = 0

    def add(self, panel, w, h, x=None):
        if x is None:
            x = getattr(self, "_x", 0)
        if x + w > 24:
            x = 0
            self.y += getattr(self, "_rowh", 0)
            self._rowh = 0
        panel.update({"id": self.id, "gridPos": {"h": h, "w": w, "x": x, "y": self.y}, "datasource": DS})
        self.id += 1
        self._x = x + w
        self._rowh = max(getattr(self, "_rowh", 0), h)
        self.d["panels"].append(panel)
        return panel

    def row(self, title):
        self.y += getattr(self, "_rowh", 0)
        self._x, self._rowh = 0, 0
        self.d["panels"].append({"id": self.id, "type": "row", "title": title, "collapsed": False,
                                 "gridPos": {"h": 1, "w": 24, "x": 0, "y": self.y}, "panels": []})
        self.id += 1
        self.y += 1

    def text(self, html, w=24, h=3):
        self.add({"type": "text", "title": "", "transparent": True,
                  "options": {"mode": "html", "content": html}}, w, h)

    def ts(self, title, series, unit=None, w=12, h=8, desc="", thresholds=None, fn="mean", stack=False, minv=None, maxv=None):
        ov = []
        for s in series:
            dev, field, label, color, *rest = s
            opts = rest[0] if rest else {}
            ov.append(override(f"{dev}/{field}", label=label, color=color, **opts))
        defaults = {"unit": unit or "short", "color": {"mode": "palette-classic"},
                    "custom": {"lineWidth": 2, "fillOpacity": 10, "gradientMode": "opacity", "spanNulls": 3600000,
                               "showPoints": "never", "lineInterpolation": "smooth", "axisSoftMin": minv,
                               "thresholdsStyle": {"mode": "line+area" if thresholds else "off"},
                               "stacking": {"mode": "normal" if stack else "none"}}}
        if minv is not None: defaults["min"] = minv
        if maxv is not None: defaults["max"] = maxv
        if thresholds:
            defaults["thresholds"] = {"mode": "absolute", "steps": thresholds}
        return self.add({"type": "timeseries", "title": title, "description": desc,
                         "targets": [{"refId": "A", "query": series_query(series, fn)}],
                         "fieldConfig": {"defaults": defaults, "overrides": ov},
                         "options": {"legend": {"displayMode": "table", "placement": "bottom", "showLegend": True,
                                                "calcs": ["mean", "max", "min", "lastNotNull"]},
                                     "tooltip": {"mode": "multi", "sort": "none"}}}, w, h)

    def stat(self, title, dev, field, unit, steps, w=4, h=4, decimals=1, desc="", fn="last", spark=True):
        q = (B + f'  |> filter(fn: (r) => r._measurement == "telemetry" and r.device == "{dev}" and r._field == "{field}")\n'
             '  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)\n  |> keep(columns: ["_time", "_value"])')
        return self.add({"type": "stat", "title": title, "description": desc, "targets": [{"refId": "A", "query": q}],
                         "fieldConfig": {"defaults": {"unit": unit, "decimals": decimals, "color": {"mode": "thresholds"},
                                                      "thresholds": {"mode": "absolute", "steps": steps}}, "overrides": []},
                         "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                                     "colorMode": "background_solid" if not spark else "value", "graphMode": "area" if spark else "none",
                                     "textMode": "value", "justifyMode": "center", "wideLayout": True,
                                     "showPercentChange": True, "percentChangeColorMode": "standard"}}, w, h)

    def gauge(self, title, dev, field, unit, steps, minv, maxv, w=4, h=6, desc=""):
        q = (B + f'  |> filter(fn: (r) => r._measurement == "telemetry" and r.device == "{dev}" and r._field == "{field}")\n'
             '  |> last()\n  |> keep(columns: ["_time", "_value"])')
        return self.add({"type": "gauge", "title": title, "description": desc, "targets": [{"refId": "A", "query": q}],
                         "fieldConfig": {"defaults": {"unit": unit, "min": minv, "max": maxv, "decimals": 1,
                                                      "thresholds": {"mode": "absolute", "steps": steps}}, "overrides": []},
                         "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                                     "showThresholdLabels": False, "showThresholdMarkers": True, "sizing": "auto"}}, w, h)

    def state(self, title, series, w=12, h=6, labels=("OFF", "ON")):
        ov = [override(f"{d}/{f}", label=l) for d, f, l in series]
        return self.add({"type": "state-timeline", "title": title,
                         "targets": [{"refId": "A", "query": series_query([(d, f) for d, f, _ in series], "last")}],
                         "fieldConfig": {"defaults": {"color": {"mode": "thresholds"},
                                                      "thresholds": {"mode": "absolute", "steps": [{"color": "#3A3F47", "value": None}, {"color": C["green"], "value": 0.5}]},
                                                      "mappings": [{"type": "value", "options": {"0": {"text": labels[0]}, "1": {"text": labels[1]}}}],
                                                      "custom": {"fillOpacity": 80, "lineWidth": 0}}, "overrides": ov},
                         "options": {"showValue": "never", "rowHeight": 0.8, "mergeValues": True, "alignValue": "left",
                                     "legend": {"showLegend": False}}}, w, h)

    def table(self, title, query, w=12, h=8, overrides=None, desc=""):
        return self.add({"type": "table", "title": title, "description": desc, "targets": [{"refId": "A", "query": query}],
                         "fieldConfig": {"defaults": {"custom": {"align": "auto", "cellOptions": {"type": "auto"}, "filterable": True}},
                                         "overrides": overrides or []},
                         "options": {"showHeader": True, "cellHeight": "sm", "footer": {"show": False}}}, w, h)

    def save(self, name):
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / name).write_text(json.dumps(self.d, indent=1, ensure_ascii=False), encoding="utf-8")
        print("dashboard:", name, len(self.d["panels"]), "paneles")


def stats_query(pairs):
    cond = " or\n      ".join(f'(r.device == "{d}" and r._field == "{f}")' for d, f in pairs)
    return ('d = ' + B + f'  |> filter(fn: (r) => r._measurement == "telemetry")\n  |> filter(fn: (r) => {cond})\n'
            '  |> group(columns: ["device", "_field"])\n'
            'a = d |> mean() |> set(key: "stat", value: "Promedio")\n'
            'b = d |> max() |> drop(columns: ["_time"]) |> set(key: "stat", value: "Máximo")\n'
            'c = d |> min() |> drop(columns: ["_time"]) |> set(key: "stat", value: "Mínimo")\n'
            'n = d |> count() |> map(fn: (r) => ({r with _value: float(v: r._value)})) |> set(key: "stat", value: "Muestras")\n'
            'union(tables: [a, b, c, n])\n  |> keep(columns: ["device", "_field", "stat", "_value"])\n  |> group()\n'
            '  |> pivot(rowKey: ["device", "_field"], columnKey: ["stat"], valueColumn: "_value")\n'
            '  |> sort(columns: ["device", "_field"])')


def events_query(measurement, fields):
    return (B + f'  |> filter(fn: (r) => r._measurement == "{measurement}")\n'
            f'  |> filter(fn: (r) => contains(value: r._field, set: {json.dumps(fields)}))\n'
            '  |> pivot(rowKey: ["_time", "device"], columnKey: ["_field"], valueColumn: "_value")\n'
            '  |> group()\n'
            f'  |> keep(columns: ["_time", "device", {", ".join(json.dumps(f) for f in fields)}])\n'
            '  |> sort(columns: ["_time"], desc: true)\n  |> limit(n: 200)')


HEADER = """<div style="display:flex;align-items:center;gap:18px;padding:6px 4px">
<div style="font-size:38px">🍫</div>
<div><div style="font-size:22px;font-weight:700;letter-spacing:.3px">CacaoSmart IoT · {title}</div>
<div style="opacity:.75;font-size:13px">{sub}</div></div></div>"""

# ======================================================================== 01 Visión general
d = Dash("cacao-general", "CacaoSmart · 01 Visión general", "Estado global de los 10 dispositivos, KPIs, alertas y retroceso.", ["general"])
d.text(HEADER.format(title="Visión general", sub="San Vicente de Chucurí, Santander · 10 dispositivos (2 reales · 2 API · 4 gemelos · 2 datasets) · MQTT + HTTPS/REST"), h=3)
d.row("Estado de conexión (LWT / device shadow)")
online_q = ('from(bucket: "cacaosmart")\n  |> range(start: -30d)   // estado ACTUAL: no depende del selector de tiempo\n'
            '  |> filter(fn: (r) => r._measurement == "status" and r._field == "online")\n'
            '  |> group(columns: ["device"])\n  |> last()\n  |> group()\n  |> keep(columns: ["device", "_value"])\n'
            '  |> pivot(rowKey: [], columnKey: ["device"], valueColumn: "_value")')
d.add({"type": "stat", "title": "Dispositivos en línea", "targets": [{"refId": "A", "query": online_q}],
       "fieldConfig": {"defaults": {"mappings": [{"type": "value", "options": {"0": {"text": "OFFLINE", "color": C["red"]},
                                                                               "1": {"text": "ONLINE", "color": C["green"]}}}],
                                    "color": {"mode": "thresholds"},
                                    "thresholds": {"mode": "absolute", "steps": [{"color": C["red"], "value": None}, {"color": C["green"], "value": 1}]}},
                       "overrides": []},
       "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}, "colorMode": "background",
                   "graphMode": "none", "textMode": "value_and_name", "justifyMode": "center", "orientation": "vertical",
                   "wideLayout": True}}, 24, 3)
d.row("Indicadores clave (último valor · variación en el periodo)")
d.stat("🌡️ T. exterior (Azure)", "dev-03", "temp_c", "celsius", [{"color": C["hr"], "value": None}, {"color": C["green"], "value": 21}, {"color": C["temp"], "value": 30}, {"color": C["red"], "value": 34}])
d.stat("☀️ Índice UV", "dev-03", "uv_index", "none", [{"color": C["green"], "value": None}, {"color": C["luz"], "value": 3}, {"color": C["temp"], "value": 6}, {"color": C["red"], "value": 8}], decimals=0)
d.stat("🌧️ Prob. lluvia 1 h", "dev-04", "prob_lluvia_pct", "percent", [{"color": C["green"], "value": None}, {"color": C["luz"], "value": 30}, {"color": C["prob"], "value": 65}], decimals=0)
d.stat("🌱 Humedad suelo", "dev-02", "humedad_suelo_pct", "percent", [{"color": C["red"], "value": None}, {"color": C["green"], "value": 35}, {"color": C["hr"], "value": 60}])
d.stat("🔥 Masa fermentación", "dev-07", "temp_masa_c", "celsius", [{"color": C["hr"], "value": None}, {"color": C["luz"], "value": 35}, {"color": C["green"], "value": 45}, {"color": C["red"], "value": 50}])
d.stat("🫘 Humedad grano", "dev-08", "humedad_grano_pct", "percent", [{"color": C["green"], "value": None}, {"color": C["gold"], "value": 7.01}, {"color": C["cacao"], "value": 25}])
d.row("Tendencias del periodo")
d.ts("Clima exterior en vivo vs. mismo día de 2025", [
    ("dev-03", "temp_c", "T. exterior hoy (DEV-03 Azure)", C["temp"]),
    ("dev-09", "temp_ref_c", "T. hace un año (DEV-09 dataset)", C["grey"], {"dash": True}),
    ("dev-03", "hr_pct", "HR hoy (DEV-03)", C["hr"], {"unit": "percent", "right": True}),
], unit="celsius", desc="Compara el clima actual (API Azure Maps) con el histórico real ERA5 de 2025 a la misma hora.")
d.ts("Cadena de beneficio: fermentación y secado", [
    ("dev-07", "temp_masa_c", "T. masa fermentación (DEV-07)", C["cacao"]),
    ("dev-08", "temp_interna_c", "T. marquesina (DEV-08)", C["temp"]),
    ("dev-08", "humedad_grano_pct", "Humedad grano (DEV-08)", C["gold"], {"unit": "percent", "right": True}),
], unit="celsius")
d.row("Motor de reglas: alertas y bitácora de retroceso")
sev_ov = [{"matcher": {"id": "byName", "options": "severity"}, "properties": [
    {"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "basic"}},
    {"id": "mappings", "value": [{"type": "value", "options": {"critical": {"color": C["red"], "text": "CRÍTICA"},
                                                                "warning": {"color": "#F5A524", "text": "ADVERTENCIA"},
                                                                "info": {"color": C["prob"], "text": "INFO"}}}]},
    {"id": "custom.width", "value": 120}, {"id": "displayName", "value": "Severidad"}]},
    {"matcher": {"id": "byName", "options": "_time"}, "properties": [{"id": "displayName", "value": "Hora"}, {"id": "custom.width", "value": 170}]},
    {"matcher": {"id": "byName", "options": "device"}, "properties": [{"id": "displayName", "value": "Disp."}, {"id": "custom.width", "value": 70}]},
    {"matcher": {"id": "byName", "options": "msg"}, "properties": [{"id": "displayName", "value": "Mensaje"}]},
    {"matcher": {"id": "byName", "options": "rule"}, "properties": [{"id": "displayName", "value": "Regla"}, {"id": "custom.width", "value": 150}]}]
d.table("🚨 Alertas del motor de reglas", events_query("alert", ["severity", "rule", "msg"]), w=14, h=9, overrides=sev_ov)
cmd_ov = [{"matcher": {"id": "byName", "options": "src"}, "properties": [
    {"id": "displayName", "value": "Origen"}, {"id": "custom.cellOptions", "value": {"type": "color-text"}},
    {"id": "mappings", "value": [{"type": "value", "options": {"rules": {"color": C["gold"], "text": "⚙ reglas"},
                                                                "panel": {"color": C["green"], "text": "👤 panel"},
                                                                "api": {"color": C["prob"], "text": "🔌 API REST"}}}]}]},
    {"matcher": {"id": "byName", "options": "_time"}, "properties": [{"id": "displayName", "value": "Hora"}, {"id": "custom.width", "value": 170}]},
    {"matcher": {"id": "byName", "options": "device"}, "properties": [{"id": "displayName", "value": "Disp."}, {"id": "custom.width", "value": 70}]},
    {"matcher": {"id": "byName", "options": "cmd"}, "properties": [{"id": "displayName", "value": "Comando"}]}]
d.table("↩️ Bitácora de retroceso (comandos enviados)", events_query("command", ["cmd", "src"]), w=10, h=9, overrides=cmd_ov)
d.row("Procesamiento: estadísticos del periodo seleccionado (ajuste con el selector de tiempo)")
d.table("📊 Promedio · Máximo · Mínimo por variable", stats_query([
    ("dev-01", "temp_c"), ("dev-01", "hr_pct"), ("dev-01", "luz_lux"), ("dev-02", "humedad_suelo_pct"), ("dev-02", "bateria_v"),
    ("dev-03", "temp_c"), ("dev-03", "hr_pct"), ("dev-03", "uv_index"), ("dev-03", "viento_kmh"),
    ("dev-04", "prob_lluvia_pct"), ("dev-04", "nubosidad_pct"), ("dev-05", "cierre_pct"), ("dev-05", "rad_filtrada_wm2"),
    ("dev-06", "caudal_lpm"), ("dev-06", "presion_psi"), ("dev-07", "temp_masa_c"), ("dev-07", "ph_mucilago"),
    ("dev-08", "humedad_grano_pct"), ("dev-08", "temp_interna_c"), ("dev-09", "temp_ref_c"), ("dev-09", "et0_dia_mm"),
    ("dev-10", "humedad_objetivo_pct"), ("dev-10", "indice_calidad")]), w=24, h=12,
    overrides=[{"matcher": {"id": "byType", "options": "number"}, "properties": [{"id": "decimals", "value": 2}]},
               {"matcher": {"id": "byName", "options": "Muestras"}, "properties": [{"id": "decimals", "value": 0}]},
               {"matcher": {"id": "byName", "options": "device"}, "properties": [{"id": "displayName", "value": "Dispositivo"}]},
               {"matcher": {"id": "byName", "options": "_field"}, "properties": [{"id": "displayName", "value": "Variable"}]}])
d.save("01-vision-general.json")

# ======================================================================== 02 Lote de cultivo
d = Dash("cacao-lote", "CacaoSmart · 02 Lote de cultivo", "Microclima, suelo, riego y sombra (DEV-01, 02, 05, 06).", ["cultivo"])
d.text(HEADER.format(title="Lote 1 · Cultivo", sub="Nodos ESP32 reales (DEV-01, DEV-02) · Gemelos de polisombra (DEV-05) y bomba de goteo (DEV-06)"), h=3)
d.row("DEV-01 · Nodo microclima (ESP32 + DHT22 + LDR) · MQTT")
d.ts("Temperatura y humedad relativa del dosel", [
    ("dev-01", "temp_c", "Temperatura", C["temp"]), ("dev-01", "hr_pct", "Humedad relativa", C["hr"], {"unit": "percent", "right": True})],
    unit="celsius", w=16, desc="Riesgo de Moniliasis: HR > 88 % y T > 26 °C sostenidos 4 h.",
    thresholds=[{"color": "transparent", "value": None}, {"color": "#E5484D22", "value": 26}])
d.gauge("HR actual (umbral Moniliasis 88 %)", "dev-01", "hr_pct", "percent", [{"color": C["luz"], "value": None}, {"color": C["green"], "value": 70}, {"color": C["red"], "value": 88}], 40, 100, w=8, h=8)
d.ts("Luminosidad bajo el dosel", [("dev-01", "luz_lux", "Luz (lux)", C["luz"])], unit="lux", w=16, h=7)
d.state("LED de aviso UV (actuador, Lazo 1)", [("dev-01", "led", "LED DEV-01")], w=8, h=7)
d.row("DEV-02 · Nodo suelo y riego (ESP32 + sensor capacitivo + relé) · MQTT")
d.ts("Humedad volumétrica del suelo vs umbral de riego", [
    ("dev-02", "humedad_suelo_pct", "Humedad suelo", C["suelo"]), ("dev-02", "umbral_pct", "Umbral de riego", C["red"], {"dash": True}),
    ("dev-09", "humedad_suelo_ref_pct", "Suelo ref. 2025 (DEV-09)", C["grey"], {"dash": True})],
    unit="percent", w=16, desc="Lazo 2: si la humedad cae bajo el umbral se consulta la lluvia de DEV-04 antes de regar.")
d.ts("Batería del nodo", [("dev-02", "bateria_v", "Batería 18650", C["gold"])], unit="volt", w=8, h=8,
     thresholds=[{"color": "#E5484D33", "value": None}, {"color": "transparent", "value": 3.5}])
d.state("Electroválvula (relé) y bomba", [("dev-02", "valvula", "Válvula DEV-02"), ("dev-06", "bomba", "Bomba DEV-06")], w=24, h=5)
d.row("DEV-05 · Gemelo digital polisombra motorizada")
d.ts("Radiación exterior vs filtrada por la malla", [
    ("dev-05", "rad_ext_wm2", "Radiación exterior", C["rad"]), ("dev-05", "rad_filtrada_wm2", "Radiación filtrada", C["filt"]),
    ("dev-05", "cierre_pct", "Cierre malla", C["cacao"], {"unit": "percent", "right": True, "step": True})], unit="watt", w=16)
d.ts("Corriente del motor e índice UV", [
    ("dev-05", "corriente_a", "Corriente motor", C["pres"], {"unit": "amp"}), ("dev-05", "uv_index", "Índice UV", C["uv"], {"right": True, "unit": "none"})], w=8)
d.row("DEV-06 · Gemelo digital bomba y caudalímetro de goteo")
d.ts("Caudal y presión de línea", [
    ("dev-06", "caudal_lpm", "Caudal (L/min)", C["flow"]), ("dev-06", "presion_psi", "Presión (PSI)", C["pres"], {"right": True, "unit": "pressurepsi"})],
    unit="short", w=16, desc="Interlock local: presión < 12 PSI con la bomba encendida = fuga -> parada de emergencia.")
d.ts("Consumo de agua del día", [("dev-06", "consumo_l", "Consumo diario (L)", C["hr"])], unit="litre", w=8, fn="max")
d.save("02-lote-cultivo.json")

# ======================================================================== 03 Beneficio
d = Dash("cacao-beneficio", "CacaoSmart · 03 Beneficio (poscosecha)", "Fermentación (DEV-07) y secado solar (DEV-08) vs curva ideal (DEV-10).", ["poscosecha"])
d.text(HEADER.format(title="Beneficio · Fermentación y secado", sub="Gemelos digitales DEV-07 y DEV-08 · Benchmark de calidad DEV-10 (dataset, HTTP REST)"), h=3)
d.row("DEV-07 · Cajón de fermentación #1")
d.ts("Temperatura de la masa (banda óptima 45-50 °C)", [
    ("dev-07", "temp_masa_c", "T. masa", C["cacao"]), ("dev-07", "temp_ambiente_c", "T. ambiente (bajo techo)", C["grey"], {"dash": True})],
    unit="celsius", w=16, thresholds=[{"color": "transparent", "value": None}, {"color": "#46A75733", "value": 45}, {"color": "#E5484D33", "value": 50}],
    desc="Lazo 4: > 50 °C o a las 48/96 h -> VOLTEO automático (enfría 3 °C y oxigena).")
d.gauge("T. masa actual", "dev-07", "temp_masa_c", "celsius", [{"color": C["hr"], "value": None}, {"color": C["luz"], "value": 35}, {"color": C["green"], "value": 45}, {"color": C["red"], "value": 50}], 20, 55, w=8, h=8)
d.ts("pH del mucílago y horas de fermentación", [
    ("dev-07", "ph_mucilago", "pH mucílago", C["ph"]), ("dev-07", "horas_fermentacion", "Horas de fermentación", C["gold"], {"right": True, "unit": "none"})], w=16)
d.ts("Volteos realizados", [("dev-07", "volteos", "Volteos en el ciclo", C["gold"], {"step": True})], w=8, fn="max")
d.row("DEV-08 · Marquesina de secado solar  vs  DEV-10 · Curva ideal")
d.ts("Humedad del grano: real vs curva ideal (meta ≤ 7 % NTC 1252)", [
    ("dev-08", "humedad_grano_pct", "Real (DEV-08)", C["gold"]), ("dev-10", "humedad_objetivo_pct", "Ideal (DEV-10)", C["ideal"], {"dash": True})],
    unit="percent", w=16, h=9, thresholds=[{"color": "#46A75733", "value": None}, {"color": "transparent", "value": 7}],
    desc="Desviación > 8 puntos genera alerta 'secado retrasado'. El perfil de DEV-10 se cambia con SET_PROFILE.")
d.gauge("Humedad del grano", "dev-08", "humedad_grano_pct", "percent", [{"color": C["green"], "value": None}, {"color": C["gold"], "value": 7.01}, {"color": C["cacao"], "value": 25}], 0, 60, w=8, h=9)
d.ts("Temperatura interna vs óptima de secado", [
    ("dev-08", "temp_interna_c", "T. marquesina (DEV-08)", C["temp"]), ("dev-10", "temp_optima_c", "T. óptima (DEV-10)", C["ideal"], {"dash": True}),
    ("dev-08", "hr_interna_pct", "HR interna", C["hr"], {"unit": "percent", "right": True})],
    unit="celsius", w=16, thresholds=[{"color": "transparent", "value": None}, {"color": "#E5484D33", "value": 45}],
    desc="Lazo 5: > 45 °C -> extractores ON y compuertas abiertas; < 40 °C -> extractores OFF; lluvia -> compuertas cerradas.")
d.ts("Índice de calidad esperado (benchmark)", [("dev-10", "indice_calidad", "Índice de calidad", C["green"])], unit="none", w=8, minv=70, maxv=100)
d.state("Actuadores de la marquesina", [("dev-08", "extractores", "Extractores"), ("dev-08", "compuertas", "Compuertas")], w=24, h=5)
d.save("03-beneficio.json")

# ======================================================================== 04 Clima, API y datasets
d = Dash("cacao-clima", "CacaoSmart · 04 Clima: API Azure Maps y datasets", "DEV-03/04 (HTTPS REST) y DEV-09 (histórico ERA5 2025).", ["clima"])
d.text(HEADER.format(title="Clima · API Azure Maps y Datasets", sub="DEV-03 Current Conditions · DEV-04 Hourly Forecast (polling HTTPS/REST) · DEV-09 Histórico 2025 (replay MQTT)"), h=3)
d.row("DEV-03 · Condiciones actuales (Azure Maps)")
d.ts("Temperatura, sensación térmica y punto de rocío", [
    ("dev-03", "temp_c", "Temperatura", C["temp"]), ("dev-03", "sensacion_c", "Sensación (RealFeel)", C["red"], {"dash": True}),
    ("dev-03", "punto_rocio_c", "Punto de rocío", C["hr"])], unit="celsius", w=12)
d.ts("Índice UV y nubosidad", [
    ("dev-03", "uv_index", "Índice UV", C["uv"], {"unit": "none"}), ("dev-03", "nubosidad_pct", "Nubosidad", C["grey"], {"unit": "percent", "right": True})],
    w=12, thresholds=[{"color": "transparent", "value": None}, {"color": "#B565D833", "value": 8}], desc="Lazo 1: UV ≥ 8 cierra la polisombra al 80 %.")
d.ts("Viento y ráfagas", [("dev-03", "viento_kmh", "Viento", C["flow"]), ("dev-03", "rafaga_kmh", "Ráfaga", C["pres"], {"dash": True})], unit="velocitykmh", w=12)
d.ts("Presión y lluvia observada", [("dev-03", "presion_hpa", "Presión", C["pres"], {"unit": "pressurehpa"}),
                                    ("dev-03", "lluvia_1h_mm", "Lluvia última hora", C["prob"], {"unit": "lengthmm", "right": True, "bars": True})], w=12, fn="max")
d.row("DEV-04 · Pronóstico horario (Azure Maps)")
d.ts("Probabilidad de lluvia (próxima hora, 3 h y máx. 12 h)", [
    ("dev-04", "prob_lluvia_pct", "Próxima hora", C["prob"]), ("dev-04", "prob_lluvia_3h_pct", "Máx. 3 h", C["hr"]),
    ("dev-04", "prob_lluvia_max_12h", "Máx. 12 h", C["grey"], {"dash": True})], unit="percent", w=16, minv=0, maxv=100,
    thresholds=[{"color": "transparent", "value": None}, {"color": "#F5A52422", "value": 30}, {"color": "#5B8DEF33", "value": 65}],
    desc="< 30 % riego normal (15 min) · 30-65 % riego reducido (8 min) · > 65 % riego inhibido (ahorro hídrico).")
d.ts("Lluvia esperada 12 h", [("dev-04", "precip_12h_mm", "Precipitación 12 h", C["prob"], {"bars": True})], unit="lengthmm", w=8, fn="max")
d.row("DEV-09 · Histórico climático cosecha 2025 (ERA5 vía Open-Meteo) · replay")
d.ts("Temperatura y HR de referencia 2025", [("dev-09", "temp_ref_c", "T. 2025", C["temp"]), ("dev-09", "hr_ref_pct", "HR 2025", C["hr"], {"unit": "percent", "right": True})], unit="celsius", w=12)
d.ts("Evapotranspiración FAO-56 y humedad de suelo 2025", [
    ("dev-09", "et0_dia_mm", "ET0 acumulada 24 h", C["suelo"], {"unit": "lengthmm"}), ("dev-09", "humedad_suelo_ref_pct", "Suelo 0-7 cm", C["cacao"], {"unit": "percent", "right": True})], w=12)
d.ts("Radiación y lluvia 2025", [("dev-09", "radiacion_wm2", "Radiación", C["rad"], {"unit": "watt"}), ("dev-09", "precipitacion_mm", "Lluvia", C["prob"], {"unit": "lengthmm", "right": True, "bars": True})], w=24, h=7)
d.save("04-clima-api-datasets.json")


# ======================================================================== Reglas de alerta de Grafana
def rule(uid, title, flux, op, value, for_, summary, severity):
    return {"uid": uid, "title": title, "condition": "C", "for": for_, "noDataState": "OK", "execErrState": "OK",
            "annotations": {"summary": summary}, "labels": {"severity": severity, "proyecto": "cacaosmart"},
            "data": [
                {"refId": "A", "relativeTimeRange": {"from": 21600, "to": 0}, "datasourceUid": "influx-cacao",
                 "model": {"refId": "A", "query": flux, "intervalMs": 60000, "maxDataPoints": 43200}},
                {"refId": "B", "datasourceUid": "__expr__", "model": {"refId": "B", "type": "reduce", "expression": "A", "reducer": "last",
                                                                      "settings": {"mode": "dropNN"}}},
                {"refId": "C", "datasourceUid": "__expr__", "model": {"refId": "C", "type": "threshold", "expression": "B",
                                                                      "conditions": [{"evaluator": {"type": op, "params": [value]}}]}}]}


def fq(dev, field, window="5m", fn="mean"):
    return ('from(bucket: "cacaosmart") |> range(start: -' + window + ')\n'
            f'  |> filter(fn: (r) => r._measurement == "telemetry" and r.device == "{dev}" and r._field == "{field}")\n'
            f'  |> {fn}()')


rules = {"apiVersion": 1, "groups": [{"orgId": 1, "name": "cacaosmart-reglas", "folder": "CacaoSmart", "interval": "1m", "rules": [
    rule("al-monilia", "Riesgo de Moniliasis (HR > 88 % por 4 h)", fq("dev-01", "hr_pct", "4h", "min"), "gt", 88, "5m",
         "La humedad relativa del dosel lleva 4 h por encima de 88 %: condiciones favorables para Moniliophthora roreri.", "critical"),
    rule("al-marquesina", "Sobrecalentamiento en marquesina (> 46 °C)", fq("dev-08", "temp_interna_c"), "gt", 46, "2m",
         "Temperatura interna de secado > 46 °C: riesgo de acidez y grano arrebatado.", "critical"),
    rule("al-fermentacion", "Fermentación fuera de rango (> 50 °C)", fq("dev-07", "temp_masa_c"), "gt", 50, "5m",
         "La masa de cacao supera 50 °C: se requiere volteo.", "warning"),
    rule("al-presion", "Presión de riego baja (< 12 PSI con bomba)", fq("dev-06", "presion_psi", "2m", "min") +
         ' |> map(fn: (r) => ({r with _value: if r._value < 12.0 then r._value else 99.0}))', "lt", 12, "1m",
         "Posible fuga en la línea de goteo.", "critical"),
    rule("al-suelo", "Suelo seco (< 30 %)", fq("dev-02", "humedad_suelo_pct", "15m"), "lt", 30, "10m",
         "La humedad del suelo está por debajo de 30 % por más de 10 min.", "warning"),
]}]}
alert_dir = ROOT / "infra" / "grafana" / "provisioning" / "alerting"
alert_dir.mkdir(parents=True, exist_ok=True)
(alert_dir / "rules.yaml").write_text(json.dumps(rules, indent=1, ensure_ascii=False), encoding="utf-8")
print("alertas:", len(rules["groups"][0]["rules"]), "reglas")
