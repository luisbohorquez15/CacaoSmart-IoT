"""
Gemelos digitales DEV-05 a DEV-08 (Capa 1 - Percepción y Actuación).

Cada gemelo es un cliente MQTT independiente con su propio client-id, LWT y tópico de
comandos. Todos comparten el clima REAL que publica la API de Azure Maps (DEV-03 y DEV-04)
a través del broker: así el gemelo responde a las condiciones verdaderas de la finca.

    python -m cacaosmart.run_twins
"""
from __future__ import annotations

import logging
import signal
import threading
import time

from .core import Device, REGION
from .models import DryerModel, FermenterModel, PumpModel, ShadeModel, Weather

WEATHER = Weather()
TOPIC_WEATHER_NOW = f"cacaosmart/{REGION}/clima/dev-03/telemetry"
TOPIC_WEATHER_FC = f"cacaosmart/{REGION}/clima/dev-04/telemetry"


class TwinBase(Device):
    dtype = "twin"
    default_interval = 30.0

    def __init__(self) -> None:
        super().__init__()
        self.subscriptions = [TOPIC_WEATHER_NOW, TOPIC_WEATHER_FC]

    def on_external(self, topic: str, p: dict) -> None:
        if topic == TOPIC_WEATHER_NOW:
            WEATHER.temp_c = float(p.get("temp_c", WEATHER.temp_c))
            WEATHER.rh = float(p.get("hr_pct", WEATHER.rh))
            WEATHER.cloud = float(p.get("nubosidad_pct", WEATHER.cloud))
            WEATHER.uv = float(p.get("uv_index", WEATHER.uv))
            WEATHER.wind_kmh = float(p.get("viento_kmh", WEATHER.wind_kmh))
            WEATHER.rain_mm_h = float(p.get("lluvia_1h_mm", WEATHER.rain_mm_h))
            WEATHER.ts_update, WEATHER.live = time.time(), True
        elif topic == TOPIC_WEATHER_FC:
            WEATHER.rain_prob = float(p.get("prob_lluvia_pct", WEATHER.rain_prob))

    def step(self, dt: float, now: float) -> None:
        if now - WEATHER.ts_update > 1800:         # sin datos de la API en 30 min -> modelo de respaldo
            WEATHER.live = False
            WEATHER.synthetic(now)
        self.step_model(dt, now)

    def step_model(self, dt: float, now: float) -> None: ...

    def extra_status(self) -> dict:
        return {"weather_live": 1 if WEATHER.live else 0}


# ------------------------------------------------------------------ DEV-05
class Polisombra(TwinBase):
    device_id, zone, name = "dev-05", "lote1", "Polisombra motorizada"

    def __init__(self) -> None:
        super().__init__()
        self.m = ShadeModel()

    def step_model(self, dt, now):
        self.m.step(dt, now, WEATHER)

    def sample(self, now):
        return self.m.read(WEATHER)

    def handle_command(self, cmd, p):
        if cmd == "SET_SHADE":
            if not self.rules_allowed(p):
                return False, "modo manual: se ignora la regla automática"
            self.m.set_target(float(p.get("value", 50)))
            return True, f"malla -> {self.m.objetivo:.0f}% de cierre"
        return False, f"comando desconocido: {cmd}"

    def extra_status(self):
        return {**super().extra_status(), "objetivo_pct": self.m.objetivo}


# ------------------------------------------------------------------ DEV-06
class BombaRiego(TwinBase):
    device_id, zone, name = "dev-06", "lote1", "Bomba y caudalímetro de goteo"
    default_interval = 15.0

    def __init__(self) -> None:
        super().__init__()
        self.m = PumpModel()

    def step_model(self, dt, now):
        alarma = self.m.step(dt, now, WEATHER)
        if alarma:
            self.log(alarma)
            self.last_cmd = {"cid": "interlock", "cmd": "EMERGENCY_STOP", "src": "edge", "ok": 1, "msg": alarma}
            self.publish_status()

    def sample(self, now):
        return self.m.read()

    def handle_command(self, cmd, p):
        if cmd in ("START", "RIEGO", "RELAY") and str(p.get("state", "ON")).upper() != "OFF":
            if not self.rules_allowed(p):
                return False, "modo manual: se ignora la regla automática"
            self.m.start(time.time(), p.get("duration_min"), p.get("flow"))
            return True, f"bomba encendida {p.get('duration_min', '∞')} min @ {self.m.caudal_obj:.0f} L/min"
        if cmd in ("STOP", "RELAY", "RIEGO"):
            self.m.stop()
            return True, "bomba apagada"
        if cmd == "SET_FLOW":
            self.m.caudal_obj = max(5.0, min(45.0, float(p.get("value", 30))))
            return True, f"caudal objetivo {self.m.caudal_obj:.0f} L/min"
        if cmd == "LEAK":
            self.m.fuga = str(p.get("state", "on")).lower() in ("on", "1", "true")
            return True, f"fuga simulada {'ACTIVA' if self.m.fuga else 'reparada'}"
        if cmd == "RESET_TOTAL":
            self.m.consumo_total = self.m.consumo_dia = 0.0
            return True, "totalizador en cero"
        return False, f"comando desconocido: {cmd}"

    def extra_status(self):
        return {**super().extra_status(), "bomba": 1 if self.m.encendida else 0, "caudal_obj": self.m.caudal_obj,
                "fuga": 1 if self.m.fuga else 0}


# ------------------------------------------------------------------ DEV-07
class CajonFermentacion(TwinBase):
    device_id, zone, name = "dev-07", "beneficio", "Cajón de fermentación #1"
    default_interval = 60.0

    def __init__(self) -> None:
        super().__init__()
        self.m = FermenterModel()

    def step_model(self, dt, now):
        if self.m.step(dt, now, WEATHER):
            self.log("ciclo de fermentación completo -> nuevo lote")
            self.publish_status()

    def sample(self, now):
        return self.m.read(WEATHER)

    def handle_command(self, cmd, p):
        if cmd == "VOLTEO":
            if not self.rules_allowed(p):
                return False, "modo manual: se ignora la regla automática"
            self.m.voltear()
            return True, f"volteo #{self.m.volteos} realizado (-3 °C, masa oxigenada)"
        if cmd == "RESET_CYCLE":
            self.m.reset(WEATHER.temp_c - 1)
            return True, f"nuevo ciclo #{self.m.ciclo}"
        return False, f"comando desconocido: {cmd}"

    def extra_status(self):
        return {**super().extra_status(), "ciclo": self.m.ciclo, "volteos": self.m.volteos,
                "horas": round(self.m.horas, 2)}


# ------------------------------------------------------------------ DEV-08
class MarquesinaSecado(TwinBase):
    device_id, zone, name = "dev-08", "beneficio", "Marquesina de secado solar"
    default_interval = 60.0

    def __init__(self) -> None:
        super().__init__()
        self.m = DryerModel()
        self.batch_start = time.time()

    def step_model(self, dt, now):
        if self.m.step(dt, now, WEATHER):
            self.batch_start = now
            self.log("lote seco (<=7%) descargado -> nuevo lote")
            self.publish_status()

    def sample(self, now):
        return self.m.read()

    def handle_command(self, cmd, p):
        on = str(p.get("state", "on")).lower() in ("on", "1", "true", "open", "abrir")
        if cmd == "EXTRACTORES":
            if not self.rules_allowed(p):
                return False, "modo manual: se ignora la regla automática"
            self.m.extractores = on
            return True, f"extractores {'ON' if on else 'OFF'}"
        if cmd == "COMPUERTAS":
            if not self.rules_allowed(p):
                return False, "modo manual: se ignora la regla automática"
            self.m.compuertas = on
            return True, f"compuertas {'abiertas' if on else 'cerradas'}"
        if cmd == "RESET_BATCH":
            self.m.reset()
            self.batch_start = time.time()
            return True, f"lote #{self.m.lote} iniciado (55%)"
        return False, f"comando desconocido: {cmd}"

    def extra_status(self):
        return {**super().extra_status(), "lote": self.m.lote, "batch_start": int(self.batch_start),
                "extractores": 1 if self.m.extractores else 0, "compuertas": 1 if self.m.compuertas else 0}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    devices = [Polisombra(), BombaRiego(), CajonFermentacion(), MarquesinaSecado()]
    for d in devices:
        d.start()
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    stop.wait()
    for d in devices:
        d.stop()


if __name__ == "__main__":
    main()
