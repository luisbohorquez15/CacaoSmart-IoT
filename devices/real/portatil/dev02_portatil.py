"""
CacaoSmart IoT · DEV-02 · Estación de borde del lote (PORTÁTIL REAL)  —  "real device python.py"

Dispositivo REAL: lee sensores físicos del portátil y actúa sobre su pantalla y parlante.
Además es el GATEWAY DE BORDE del iPhone (DEV-01): lee su barómetro y acelerómetro por Wi-Fi local con la app
phyphox (acceso remoto HTTP) y los reenvía a la nube; los comandos POWER/MEASURE/CLEAR de DEV-01 inician o
detienen la medición en el iPhone (retroceso real).
  Sensores  : batería (%), cargador (0/1), señal Wi-Fi (%), uso de CPU (%), uso de RAM (%), disco (%)
  Actuadores: VÁLVULA DE RIEGO (relé) y LED DE AVISO UV, mostrados en una ventana + pitido
  Protocolo : MQTT 3.1.1 sobre TCP 1883, QoS 1, Last Will retenido, client-id = dev-02 (ACL del broker)

  Uplink   cacaosmart/santander/lote1/dev-02/telemetry
  Shadow   cacaosmart/santander/lote1/dev-02/status   (retenido, con ACK del último comando)
  Downlink cacaosmart/santander/lote1/dev-02/command
     {"cmd":"RELAY","state":"ON","duration_min":15}   {"cmd":"LED","state":"on"}
     {"cmd":"SET_INTERVAL","value":30}  {"cmd":"POWER","state":"off"}  {"cmd":"CALIBRATE","wifi_offset":-5}
     {"cmd":"SET_MODE","value":"manual"}  {"cmd":"PING"}

Instalación (Windows):  pip install paho-mqtt psutil      Ejecución:  python dev02_portatil.py
"""
from __future__ import annotations

import ctypes
import json
import platform
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
import psutil

# ------------------------------- CONFIGURACIÓN -------------------------------
MQTT_HOST = "cacaosmart-iot.northcentralus.cloudapp.azure.com"
MQTT_PORT = 1883
MQTT_USER = "device"
MQTT_PASS = "CLAVE_MQTT_DEVICE"
DEVICE_ID = "dev-02"
# Gateway del iPhone (DEV-01) con la app gratuita phyphox, experimento "Ascensor" (Elevator).
# En phyphox: menú ⋮ -> "Permitir acceso remoto" y copie aquí la dirección que muestra (ej. http://192.168.1.50).
PHYPHOX_URL = ""                     # vacío = gateway del iPhone desactivado
PHONE_MQTT_USER = "celular"
PHONE_MQTT_PASS = "CLAVE_MQTT_CELULAR"
# ------------------------------------------------------------------------------

BASE = f"cacaosmart/santander/lote1/{DEVICE_ID}"
ui_q: "queue.Queue[dict]" = queue.Queue()
S = {"power": True, "interval": 15.0, "offsets": {}, "mode": "auto", "seq": 0, "valvula": False, "valvula_hasta": None,
     "led": False, "last_cmd": None, "connected": False, "last": {}}


def iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def keep_awake() -> None:
    """Evita que Windows suspenda el portátil mientras toma datos."""
    if platform.system() == "Windows":
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)   # ES_CONTINUOUS | ES_SYSTEM_REQUIRED


def beep(freq: int = 880, ms: int = 180) -> None:
    try:
        import winsound
        winsound.Beep(freq, ms)
    except Exception:  # noqa: BLE001
        print("\a", end="", flush=True)


def wifi_signal() -> float | None:
    """Señal Wi-Fi real (%) leída del adaptador (Windows: netsh)."""
    try:
        if platform.system() == "Windows":
            txt = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, text=True,
                                 encoding="utf-8", errors="ignore", timeout=5).stdout
            m = re.search(r"(Signal|Señal|Se.al)\s*:\s*(\d+)\s*%", txt)
            return float(m.group(2)) if m else None
        txt = open("/proc/net/wireless").read().splitlines()[2:]
        return float(txt[0].split()[2].strip(".")) * 100 / 70 if txt else None
    except Exception:  # noqa: BLE001
        return None


def read_sensors() -> dict:
    d: dict = {"cpu_pct": psutil.cpu_percent(interval=0.5), "ram_pct": psutil.virtual_memory().percent,
               "disco_pct": psutil.disk_usage("C:\\" if platform.system() == "Windows" else "/").percent}
    b = psutil.sensors_battery()
    if b is not None:
        d["bateria_pct"] = float(b.percent)
        d["cargador"] = 1 if b.power_plugged else 0
    w = wifi_signal()
    if w is not None:
        d["wifi_pct"] = w
    for k, v in list(d.items()):                       # calibración: "wifi_offset" corrige "wifi_pct", etc.
        off = S["offsets"].get(k, S["offsets"].get(k.split("_")[0], 0.0))
        if off and isinstance(v, float):
            d[k] = round(v + off, 2)
    d["valvula"] = 1 if S["valvula"] else 0
    d["led"] = 1 if S["led"] else 0
    return d


# ----------------------------------------------------------------- MQTT
if hasattr(mqtt, "CallbackAPIVersion"):          # paho-mqtt 2.x
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=DEVICE_ID, clean_session=False)
else:                                             # paho-mqtt 1.x
    client = mqtt.Client(client_id=DEVICE_ID, clean_session=False)
client.username_pw_set(MQTT_USER, MQTT_PASS)
client.will_set(f"{BASE}/status", json.dumps({"online": 0, "device": DEVICE_ID}), qos=1, retain=True)
client.reconnect_delay_set(1, 30)


def publish_status() -> None:
    st = {"online": 1, "device": DEVICE_ID, "name": "Estación de borde del lote (PC)", "type": "real",
          "power": "on" if S["power"] else "off", "interval_s": S["interval"], "mode": S["mode"], "offsets": S["offsets"],
          "valvula": 1 if S["valvula"] else 0, "led": 1 if S["led"] else 0, "host": platform.node(), "ts": iso()}
    if S["last_cmd"]:
        st["last_cmd"] = S["last_cmd"]
    client.publish(f"{BASE}/status", json.dumps(st), qos=1, retain=True)


def on_connect(c, u, flags, rc, props=None):
    S["connected"] = (rc == 0) if isinstance(rc, int) else not rc.is_failure
    c.subscribe(f"{BASE}/command", qos=1)
    c.subscribe(f"{PHONE_BASE}/command", qos=1)            # retroceso hacia el iPhone
    publish_status()
    ui_q.put({"evt": "conn"})


def on_disconnect(c, u, *args):
    S["connected"] = False
    ui_q.put({"evt": "conn"})


def on_message(c, u, msg):
    try:
        p = json.loads(msg.payload.decode() or "{}")
    except json.JSONDecodeError:
        return
    if msg.topic.endswith("dev-01/command"):
        if PHYPHOX_URL:
            threading.Thread(target=phone_command, args=(p,), daemon=True).start()
        return
    if not isinstance(p, dict) or not p.get("cmd"):
        return                                   # mensaje sin comando (p. ej. eco de otro cliente): se ignora
    cmd = str(p.get("cmd", "")).upper()
    on = str(p.get("state", "on")).lower() in ("on", "1", "true", "open")
    ok, txt = True, ""
    if cmd in ("RELAY", "RIEGO"):
        if on and S["mode"] == "manual" and p.get("src") == "rules":
            ok, txt = False, "modo manual: se ignora la regla automática"
        else:
            mins = float(p.get("duration_min", 15)) if on else 0
            S["valvula"], S["valvula_hasta"] = on, (time.time() + mins * 60 if on else None)
            txt = f"válvula ABIERTA {mins:.0f} min" if on else "válvula CERRADA"
            beep(1000 if on else 500)
    elif cmd == "LED":
        S["led"] = on
        txt = f"LED de aviso {'ON' if on else 'OFF'}"
        beep(1200 if on else 600, 120)
    elif cmd == "POWER":
        S["power"] = on
        txt = f"telemetría {'encendida' if on else 'apagada'}"
    elif cmd == "SET_INTERVAL":
        S["interval"] = max(5.0, min(3600.0, float(p.get("value", S["interval"]))))
        txt = f"intervalo = {S['interval']:.0f}s"
    elif cmd == "CALIBRATE":
        ch = []
        for k, v in (p.get("offsets") or {}).items():
            S["offsets"][k] = float(v); ch.append(k)
        for k, v in p.items():
            if k.endswith("_offset"):
                S["offsets"][k[:-7]] = float(v); ch.append(k[:-7])
        if "interval_sec" in p:
            S["interval"] = max(5.0, min(3600.0, float(p["interval_sec"]))); ch.append("intervalo")
        txt = "calibrado: " + ", ".join(ch) if ch else "sin cambios"
    elif cmd == "RESET_CALIBRATION":
        S["offsets"].clear(); txt = "offsets borrados"
    elif cmd == "SET_MODE":
        S["mode"] = "manual" if p.get("value") == "manual" else "auto"; txt = f"modo {S['mode']}"
    elif cmd == "PING":
        txt = "pong"
    else:
        ok, txt = False, f"comando desconocido: {cmd}"
    S["last_cmd"] = {"cid": p.get("cid", ""), "cmd": cmd, "src": p.get("src", "desconocido"), "ok": 1 if ok else 0,
                     "msg": txt, "at": iso()}
    print(f"[{datetime.now():%H:%M:%S}] {cmd} de {p.get('src')} -> {'OK' if ok else 'RECHAZADO'}: {txt}")
    publish_status()
    ui_q.put({"evt": "cmd", "txt": f"{cmd} ({p.get('src', '?')}): {txt}", "ok": ok})


client.on_connect, client.on_disconnect, client.on_message = on_connect, on_disconnect, on_message

# ----------------------------------------------------------------- Gateway del iPhone (DEV-01 vía phyphox)
PHONE_BASE = "cacaosmart/santander/lote1/dev-01"
P = {"ok": False, "want_on": True, "measuring": False, "last": {}, "msg_id": 0, "error": ""}
if hasattr(mqtt, "CallbackAPIVersion"):
    phone_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="dev01-gateway-phyphox")
else:
    phone_client = mqtt.Client(client_id="dev01-gateway-phyphox")
phone_client.username_pw_set(PHONE_MQTT_USER, PHONE_MQTT_PASS)
phone_client.reconnect_delay_set(1, 30)


def phyphox(path: str) -> dict:
    with urllib.request.urlopen(PHYPHOX_URL.rstrip("/") + path, timeout=4) as r:
        return json.loads(r.read().decode())


def phone_command(p: dict) -> None:
    """Retroceso REAL sobre el iPhone: inicia / detiene / limpia la medición en phyphox."""
    cmd = str(p.get("cmd", "")).upper()
    state = str(p.get("state", "on")).lower()
    try:
        if cmd == "POWER" or cmd == "MEASURE":
            P["want_on"] = state in ("on", "start", "1", "true")
            phyphox("/control?cmd=" + ("start" if P["want_on"] else "stop"))
        elif cmd == "CLEAR":
            phyphox("/control?cmd=clear")
            if P["want_on"]:
                phyphox("/control?cmd=start")
        else:
            return
        ui_q.put({"evt": "cmd", "txt": f"iPhone <- {cmd} {state}", "ok": True})
    except Exception as e:  # noqa: BLE001
        ui_q.put({"evt": "cmd", "txt": f"iPhone no responde a {cmd}: {e}", "ok": False})


def phyphox_loop() -> None:
    """Lee el iPhone por la red local y publica lotes crudos (formato Sensor Logger) en .../dev-01/raw."""
    batch, last_send = [], time.time()
    while True:
        if not PHYPHOX_URL:
            time.sleep(5); continue
        try:
            d = phyphox("/get?pressure&h&a")
            st, b = d.get("status", {}), d.get("buffer", {})
            P["measuring"] = bool(st.get("measuring"))
            if P["want_on"] and not P["measuring"]:
                phyphox("/control?cmd=start")
            last = lambda k: (b.get(k, {}).get("buffer") or [None])[-1]  # noqa: E731
            pr, h, a = last("pressure"), last("h"), last("a")
            t = time.time_ns()
            if P["measuring"]:
                if pr is not None:
                    batch.append({"name": "barometer", "time": t, "values": {"pressure": pr, "relativeAltitude": h if h is not None else 0}})
                if a is not None:
                    batch.append({"name": "accelerometer", "time": t, "values": {"x": 0.0, "y": 0.0, "z": a}})
            P["ok"], P["error"] = True, ""
            P["last"] = {"presion_hpa": pr, "altura_m": h, "acel_ms2": a}
        except Exception as e:  # noqa: BLE001
            P["ok"], P["error"] = False, str(e)[:60]
        if batch and time.time() - last_send >= 5:
            P["msg_id"] += 1
            phone_client.publish(f"{PHONE_BASE}/raw", json.dumps({"messageId": P["msg_id"], "sessionId": "phyphox",
                                 "deviceId": "iphone", "payload": batch}), qos=1)
            batch, last_send = [], time.time()
        time.sleep(1)


def sampler() -> None:
    """Hilo de muestreo: lee sensores y publica según el intervalo configurado."""
    last = 0.0
    while True:
        if S["valvula"] and S["valvula_hasta"] and time.time() >= S["valvula_hasta"]:
            S["valvula"], S["valvula_hasta"] = False, None
            S["last_cmd"] = {"cid": "edge", "cmd": "AUTO_OFF", "src": "edge", "ok": 1, "msg": "riego finalizado", "at": iso()}
            beep(500); publish_status(); ui_q.put({"evt": "cmd", "txt": "AUTO_OFF: riego finalizado", "ok": True})
        if S["power"] and time.time() - last >= S["interval"] and S["connected"]:
            d = read_sensors()
            S["seq"] += 1
            client.publish(f"{BASE}/telemetry", json.dumps({"ts": iso(), "type": "real", "seq": S["seq"], **d}), qos=1)
            S["last"] = d
            last = time.time()
            ui_q.put({"evt": "tele"})
        time.sleep(1)


# ----------------------------------------------------------------- Ventana (actuadores visibles)
def build_ui() -> tk.Tk:
    root = tk.Tk()
    root.title("CacaoSmart · DEV-02 · Estación de borde (PC real) + gateway iPhone")
    root.configure(bg="#1a1410")
    root.geometry("580x470")
    font = ("Segoe UI", 11)
    tk.Label(root, text="🍫 CacaoSmart IoT · DEV-02", fg="#d4a24c", bg="#1a1410", font=("Segoe UI", 16, "bold")).pack(pady=(14, 2))
    conn = tk.Label(root, text="conectando…", fg="#b5a497", bg="#1a1410", font=font); conn.pack()
    row = tk.Frame(root, bg="#1a1410"); row.pack(pady=14)
    valv = tk.Label(row, text="VÁLVULA\nCERRADA", width=14, height=4, font=("Segoe UI", 14, "bold"), bg="#3a2d24", fg="#f3ece6")
    valv.grid(row=0, column=0, padx=10)
    led = tk.Label(row, text="LED AVISO UV\nOFF", width=14, height=4, font=("Segoe UI", 14, "bold"), bg="#3a2d24", fg="#f3ece6")
    led.grid(row=0, column=1, padx=10)
    data = tk.Label(root, text="", fg="#f3ece6", bg="#1a1410", font=("Consolas", 10), justify="left"); data.pack()
    phone = tk.Label(root, text="", fg="#b5a497", bg="#1a1410", font=font); phone.pack(pady=(6, 0))
    last = tk.Label(root, text="Último comando: —", fg="#b5a497", bg="#1a1410", font=font, wraplength=520); last.pack(pady=10)

    def refresh():
        while not ui_q.empty():
            e = ui_q.get()
            if e["evt"] == "cmd":
                last.config(text="Último comando: " + e["txt"], fg="#7fb069" if e["ok"] else "#e5484d")
        conn.config(text=("● conectado a " + MQTT_HOST) if S["connected"] else "● sin conexión (reintentando…)",
                    fg="#7fb069" if S["connected"] else "#e5484d")
        rest = f"\n{int((S['valvula_hasta'] - time.time()) // 60) + 1} min" if S["valvula"] and S["valvula_hasta"] else ""
        valv.config(text=("VÁLVULA\nABIERTA" + rest) if S["valvula"] else "VÁLVULA\nCERRADA",
                    bg="#2E7FC0" if S["valvula"] else "#3a2d24")
        led.config(text="LED AVISO UV\nON" if S["led"] else "LED AVISO UV\nOFF", bg="#F5A524" if S["led"] else "#3a2d24",
                   fg="#1a1410" if S["led"] else "#f3ece6")
        if PHYPHOX_URL:
            lp = P["last"]
            phone.config(text=(f"📱 iPhone (phyphox): {'midiendo' if P['measuring'] else 'detenido'} · "
                               f"{(lp.get('presion_hpa') or 0):.2f} hPa · altura {(lp.get('altura_m') or 0):.2f} m")
                         if P["ok"] else f"📱 iPhone sin respuesta: {P['error']}", fg="#7fb069" if P["ok"] else "#e5484d")
        d = S["last"]
        data.config(text="\n".join(f"{k:<12} {v}" for k, v in d.items()) +
                    f"\n\nintervalo {S['interval']:.0f}s · telemetría {'ON' if S['power'] else 'OFF'} · modo {S['mode']} · #{S['seq']}")
        root.after(500, refresh)

    refresh()
    return root


if __name__ == "__main__":
    if MQTT_PASS == "CLAVE_MQTT_DEVICE":
        sys.exit("Configure MQTT_PASS (clave MQTT_DEVICE_PASS del .env de la nube) al inicio del archivo.")
    keep_awake()
    client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
    client.loop_start()
    threading.Thread(target=sampler, daemon=True).start()
    if PHYPHOX_URL:
        phone_client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
        phone_client.loop_start()
        threading.Thread(target=phyphox_loop, daemon=True).start()
    ui = build_ui()
    try:
        ui.mainloop()
    finally:
        client.publish(f"{BASE}/status", json.dumps({"online": 0, "device": DEVICE_ID}), qos=1, retain=True)
        time.sleep(0.5)
        client.loop_stop()
