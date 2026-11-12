"""
Núcleo común de todos los dispositivos de software de CacaoSmart IoT.

Cada dispositivo (gemelo digital, réplica de dataset o emulador) es un cliente MQTT
independiente que implementa el MISMO contrato que el firmware de los ESP32 reales:

  Uplink    cacaosmart/<region>/<zona>/<id>/telemetry   QoS 1   JSON {ts, type, seq, <variables>}
  Shadow    cacaosmart/<region>/<zona>/<id>/status      QoS 1   retenido (estado + ACK del último comando)
  Downlink  cacaosmart/<region>/<zona>/<id>/command     QoS 1   JSON {cmd, cid, src, ...parámetros}
  LWT       status <- {"online": 0}                     retenido (el broker lo publica si el equipo cae)

Comandos comunes (retroceso) soportados por TODOS los dispositivos:
  POWER {state: on|off}        apaga/enciende el envío de telemetría
  SET_INTERVAL {value: s}      ajusta el periodo de muestreo
  CALIBRATE {offsets: {var: x}} | {<var>_offset: x} | {interval_sec: s}
  RESET_CALIBRATION            borra los offsets
  PING                         responde con el estado actual
Cada dispositivo añade sus comandos propios en handle_command().
"""
from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import paho.mqtt.client as mqtt

REGION = os.getenv("REGION", "santander")
log = logging.getLogger("cacaosmart")


def utcnow_iso(ts: float | None = None) -> str:
    ts = time.time() if ts is None else ts
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def topic(zone: str, device_id: str, kind: str) -> str:
    return f"cacaosmart/{REGION}/{zone}/{device_id}/{kind}"


class Device:
    device_id = "dev-00"
    zone = "lote1"
    dtype = "twin"            # real | twin | api | dataset
    name = "Dispositivo"
    default_interval = 30.0   # s
    tick = 1.0                # s, paso de simulación física
    interval_bounds = (5.0, 3600.0)

    def __init__(self) -> None:
        self.power = True
        self.interval = float(os.getenv(f"{self.device_id.upper().replace('-', '_')}_INTERVAL", self.default_interval))
        self.offsets: dict[str, float] = {}
        self.mode = "auto"
        self.seq = 0
        self.last_cmd: dict[str, Any] | None = None
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self.device_id, clean_session=False)
        self.client.username_pw_set(os.getenv("MQTT_DEVICE_USER", "device"), os.getenv("MQTT_DEVICE_PASS", "device"))
        self.client.will_set(self.t("status"), json.dumps({"online": 0, "device": self.device_id}), qos=1, retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(1, 30)
        self.subscriptions: list[str] = []   # tópicos extra (p.ej. clima para los gemelos)

    # ------------------------------------------------------------------ helpers
    def t(self, kind: str) -> str:
        return topic(self.zone, self.device_id, kind)

    def log(self, msg: str, *a) -> None:
        log.info(f"[{self.device_id}] " + msg, *a)

    # ------------------------------------------------------------------ MQTT
    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        self.log("conectado al broker (rc=%s)", reason_code)
        client.subscribe(self.t("command"), qos=1)
        for s in self.subscriptions:
            client.subscribe(s, qos=1)
        self.publish_status()

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode() or "{}")
        except json.JSONDecodeError:
            self.log("payload inválido en %s", msg.topic)
            return
        if msg.topic == self.t("command"):
            self._dispatch(payload)
        else:
            try:
                self.on_external(msg.topic, payload)
            except Exception:  # noqa: BLE001
                log.exception("on_external")

    def _dispatch(self, p: dict[str, Any]) -> None:
        cmd = str(p.get("cmd") or p.get("action") or "").upper()
        src = p.get("src", "desconocido")
        with self._lock:
            try:
                ok, msg = self._common_command(cmd, p)
                if ok is None:
                    ok, msg = self.handle_command(cmd, p)
            except Exception as e:  # noqa: BLE001
                ok, msg = False, f"error: {e}"
            self.last_cmd = {"cid": p.get("cid", ""), "cmd": cmd, "src": src, "ok": 1 if ok else 0,
                             "msg": msg, "at": utcnow_iso()}
        self.log("comando %s de %s -> %s (%s)", cmd, src, "OK" if ok else "RECHAZADO", msg)
        self.publish_status()

    def _common_command(self, cmd: str, p: dict[str, Any]):
        if cmd == "POWER":
            self.power = str(p.get("state", "on")).lower() in ("on", "1", "true")
            return True, f"telemetría {'encendida' if self.power else 'apagada'}"
        if cmd in ("SET_INTERVAL", "SET_POLLING"):
            v = float(p.get("value", self.interval))
            lo, hi = self.interval_bounds
            self.interval = max(lo, min(hi, v))
            return True, f"intervalo = {self.interval:.0f}s"
        if cmd == "CALIBRATE":
            changed = []
            for k, v in (p.get("offsets") or {}).items():
                self.offsets[k] = float(v); changed.append(k)
            for k, v in p.items():
                if k.endswith("_offset"):
                    self.offsets[k[:-7]] = float(v); changed.append(k[:-7])
            if "interval_sec" in p:
                self._common_command("SET_INTERVAL", {"value": p["interval_sec"]})
                changed.append("intervalo")
            return True, "calibrado: " + ", ".join(changed) if changed else "sin cambios"
        if cmd == "RESET_CALIBRATION":
            self.offsets.clear()
            return True, "offsets borrados"
        if cmd == "SET_MODE":
            m = str(p.get("value", "auto")).lower()
            if m not in ("auto", "manual"):
                return False, "modo inválido"
            self.mode = m
            return True, f"modo {m}"
        if cmd == "PING":
            return True, "pong"
        return None, ""

    def rules_allowed(self, p: dict[str, Any]) -> bool:
        """En modo manual el operador manda: se rechazan comandos automáticos del motor de reglas."""
        return not (self.mode == "manual" and p.get("src") == "rules")

    def publish_status(self) -> None:
        st = {"online": 1, "device": self.device_id, "name": self.name, "type": self.dtype,
              "power": "on" if self.power else "off", "interval_s": self.interval, "mode": self.mode,
              "offsets": self.offsets, "ts": utcnow_iso()}
        st.update(self.extra_status())
        if self.last_cmd:
            st["last_cmd"] = self.last_cmd
        self.client.publish(self.t("status"), json.dumps(st), qos=1, retain=True)

    def publish_telemetry(self, data: dict[str, Any], ts: float | None = None) -> None:
        self.seq += 1
        out: dict[str, Any] = {"ts": utcnow_iso(ts), "type": self.dtype, "seq": self.seq}
        for k, v in data.items():
            # "temp_offset" calibra "temp_c", "hr_offset" calibra "hr_pct", etc.
            off = self.offsets.get(k, self.offsets.get(k.rsplit("_", 1)[0], 0.0))
            if isinstance(v, float) or (isinstance(v, int) and not isinstance(v, bool) and off):
                v = round(v + off, 3)
            out[k] = v
        self.client.publish(self.t("telemetry"), json.dumps(out), qos=1)

    # ------------------------------------------------------------------ ciclo de vida
    def start(self) -> None:
        host = os.getenv("MQTT_HOST", "localhost")
        port = int(os.getenv("MQTT_PORT", "1883"))
        self.client.connect_async(host, port, keepalive=30)
        self.client.loop_start()
        threading.Thread(target=self._run, name=self.device_id, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        self.client.publish(self.t("status"), json.dumps({"online": 0, "device": self.device_id}), qos=1, retain=True)
        self.client.loop_stop()

    def _run(self) -> None:
        last_pub = 0.0
        last_tick = time.time()
        time.sleep(random.uniform(0, 3))       # desfase para no saturar el broker
        while not self._stop.is_set():
            now = time.time()
            try:
                with self._lock:
                    self.step(now - last_tick, now)
                if self.power and now - last_pub >= self.interval and self.client.is_connected():
                    with self._lock:
                        data = self.sample(now)
                    if data:
                        self.publish_telemetry(data, now)
                    last_pub = now
            except Exception:  # noqa: BLE001  - un error de un ciclo no debe "matar" al dispositivo
                log.exception("[%s] error en el ciclo", self.device_id)
            last_tick = now
            self._stop.wait(self.tick)

    # ------------------------------------------------------------------ a implementar
    def step(self, dt: float, now: float) -> None:
        """Avanza el modelo físico dt segundos."""

    def sample(self, now: float) -> dict[str, Any]:
        raise NotImplementedError

    def handle_command(self, cmd: str, p: dict[str, Any]):
        return False, f"comando desconocido: {cmd}"

    def extra_status(self) -> dict[str, Any]:
        return {}

    def on_external(self, topic: str, payload: dict[str, Any]) -> None:
        """Mensajes de otros tópicos suscritos (acoplamiento entre dispositivos)."""


def new_cid() -> str:
    return uuid.uuid4().hex[:8]
