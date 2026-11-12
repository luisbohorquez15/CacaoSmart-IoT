"""
Genera infra/nodered/flows.json a partir del código JavaScript de infra/nodered/functions/*.js.
Mantener la lógica en archivos .js separados permite versionarla y revisarla en GitHub.
    python scripts/build_flows.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FN = ROOT / "infra" / "nodered" / "functions"
BROKER = "mqtt_broker"
nodes = []


def js(name):
    return (FN / f"{name}.js").read_text(encoding="utf-8")


def add(n):
    nodes.append(n)
    return n["id"]


def tab(id_, label, info):
    add({"id": id_, "type": "tab", "label": label, "disabled": False, "info": info})


def function(id_, z, name, code, outputs, wires, x, y):
    add({"id": id_, "type": "function", "z": z, "name": name, "func": code, "outputs": outputs, "timeout": 0,
         "noerr": 0, "initialize": "", "finalize": "", "libs": [], "x": x, "y": y, "wires": wires})


def mqtt_in(id_, z, name, topic, wires, x, y):
    add({"id": id_, "type": "mqtt in", "z": z, "name": name, "topic": topic, "qos": "1", "datatype": "json",
         "broker": BROKER, "nl": False, "rap": True, "rh": 0, "inputs": 0, "x": x, "y": y, "wires": [wires]})


def mqtt_out(id_, z, name, x, y):
    add({"id": id_, "type": "mqtt out", "z": z, "name": name, "topic": "", "qos": "", "retain": "", "respTopic": "",
         "contentType": "", "userProps": "", "correl": "", "expiry": "", "broker": BROKER, "x": x, "y": y, "wires": []})


def inject(id_, z, name, topic, repeat, once_delay, wires, x, y):
    add({"id": id_, "type": "inject", "z": z, "name": name, "props": [{"p": "topic", "vt": "str"}], "repeat": repeat,
         "crontab": "", "once": once_delay is not None, "onceDelay": once_delay or 0.1, "topic": topic,
         "x": x, "y": y, "wires": [wires]})


def http_request(id_, z, name, wires, x, y):
    add({"id": id_, "type": "http request", "z": z, "name": name, "method": "use", "ret": "obj", "paytoqs": "ignore",
         "url": "", "tls": "", "persist": False, "proxy": "", "insecureHTTPParser": False, "authType": "",
         "senderr": False, "headers": [], "x": x, "y": y, "wires": [wires]})


def comment(id_, z, name, info, x, y):
    add({"id": id_, "type": "comment", "z": z, "name": name, "info": info, "x": x, "y": y, "wires": []})


# ------------------------------------------------------------------ broker
add({"id": BROKER, "type": "mqtt-broker", "name": "Mosquitto CacaoSmart", "broker": "${MQTT_HOST}", "port": "${MQTT_PORT}",
     "clientid": "nodered-orquestador", "autoConnect": True, "usetls": False, "protocolVersion": "4", "keepalive": "30",
     "cleansession": True, "autoUnsubscribe": True, "birthTopic": "", "birthQos": "0", "birthPayload": "", "birthMsg": {},
     "closeTopic": "", "closeQos": "0", "closePayload": "", "closeMsg": {}, "willTopic": "", "willQos": "0",
     "willPayload": "", "willMsg": {}, "userProps": "", "sessionExpiry": ""})

# ------------------------------------------------------------------ TAB 1: APIs Azure Maps
T1 = "tab_api"
tab(T1, "1 · API Azure Maps (DEV-03/04)", "Dispositivos tipo API: consumen Azure Maps Weather por HTTPS/REST y publican por MQTT.")
comment("c1", T1, "DEV-03 Current Conditions · DEV-04 Hourly Forecast (HTTPS REST -> MQTT)",
        "Polling configurable por retroceso: SET_INTERVAL, POWER, SET_LOCATION, POLL_NOW, AHORRO_AGUA", 330, 40)
inject("inj_init", T1, "arranque", "", "", 3, ["fn_init"], 110, 100)
function("fn_init", T1, "Inicialización", js("init"), 2, [["fn_sched"], ["fn_sched"]], 290, 100)
inject("inj_03", T1, "tick DEV-03", "dev-03", "30", None, ["fn_sched"], 120, 160)
inject("inj_04", T1, "tick DEV-04", "dev-04", "30", None, ["fn_sched"], 120, 200)
function("fn_sched", T1, "Planificador de consultas", js("scheduler"), 1, [["http_azure"]], 500, 160)
http_request("http_azure", T1, "GET atlas.microsoft.com/weather", ["fn_map"], 760, 160)
function("fn_map", T1, "Normalizar JSON -> telemetría", js("map_azure"), 2, [["mq_out_api"], ["mq_out_api"]], 1030, 160)
mqtt_out("mq_out_api", T1, "publicar telemetry/status", 1290, 160)
mqtt_in("mq_in_apicmd", T1, "comandos DEV-03/04", "cacaosmart/+/clima/+/command", ["fn_apicmd"], 140, 280)
function("fn_apicmd", T1, "Retroceso de las APIs", js("api_commands"), 2, [["mq_out_api"], ["fn_sched"]], 400, 280)

# ------------------------------------------------------------------ TAB 2: Motor de reglas
T2 = "tab_rules"
tab(T2, "2 · Motor de reglas (retroceso)", "Lazos de control automáticos y alertas.")
comment("c2", T2, "Lazos: UV->polisombra · suelo+lluvia->riego · fermentación->volteo · marquesina->extractores", "", 360, 40)
mqtt_in("mq_in_tele", T2, "telemetría de todos", "cacaosmart/+/+/+/telemetry", ["fn_store", "fn_rules"], 140, 120)
mqtt_in("mq_in_stat", T2, "estado (shadow/LWT)", "cacaosmart/+/+/+/status", ["fn_store"], 140, 200)
function("fn_store", T2, "Último dato / shadow", js("store"), 1, [["mq_out_rules"]], 400, 200)
function("fn_rules", T2, "Motor de reglas", js("rules"), 2, [["mq_out_rules"], ["mq_out_rules", "fn_tg"]], 400, 120)
mqtt_out("mq_out_rules", T2, "comandos / alertas", 680, 140)
function("fn_tg", T2, "Formato Telegram", js("telegram"), 1, [["http_tg"]], 660, 260)
http_request("http_tg", T2, "POST api.telegram.org", [], 880, 260)

# ------------------------------------------------------------------ TAB 3: API REST
T3 = "tab_rest"
tab(T3, "3 · API REST (endpoints)", "Ingesta HTTP y comandos por REST. Publicado por Caddy en https://<dominio>/api/")
routes = [("GET", "/api/health"), ("GET", "/api/devices"), ("POST", "/api/ingest/:device"),
          ("POST", "/api/devices/:device/command")]
for i, (m, url) in enumerate(routes):
    add({"id": f"http_in_{i}", "type": "http in", "z": T3, "name": f"{m} {url}", "url": url, "method": m.lower(),
         "upload": False, "swaggerDoc": "", "x": 170, "y": 80 + i * 60, "wires": [["fn_rest"]]})
function("fn_rest", T3, "API REST", js("rest_api"), 2, [["mq_out_rest"], ["http_resp"]], 470, 170)
mqtt_out("mq_out_rest", T3, "publicar en broker", 720, 140)
add({"id": "http_resp", "type": "http response", "z": T3, "name": "respuesta", "statusCode": "", "headers": {},
     "x": 700, "y": 200, "wires": []})

out = ROOT / "infra" / "nodered" / "flows.json"
out.write_text(json.dumps(nodes, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"flows.json: {len(nodes)} nodos -> {out}")
