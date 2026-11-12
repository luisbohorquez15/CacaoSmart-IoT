"""
Emulador de los nodos REALES DEV-01 y DEV-02 (sólo para desarrollo y pruebas sin hardware).

En producción estos dispositivos son ESP32 físicos (ver devices/real/). Este emulador implementa
EXACTAMENTE el mismo contrato MQTT del firmware, para probar reglas, panel y dashboards.
    python -m cacaosmart.run_emulator
"""
from __future__ import annotations

import logging
import signal
import threading
import time

from .core import Device
from .models import MicroclimaModel, SueloModel
from .run_twins import TwinBase, WEATHER


class EmuBase(TwinBase):
    dtype = "real"
    default_interval = 10.0

    def extra_status(self):
        return {**super().extra_status(), "emulado": 1, "fw": "emulator-1.0"}


class Microclima(EmuBase):
    device_id, zone, name = "dev-01", "lote1", "Nodo microclima lote 1 (ESP32+DHT22+LDR)"

    def __init__(self):
        super().__init__()
        self.m = MicroclimaModel()

    def sample(self, now):
        return self.m.read(now, WEATHER)

    def handle_command(self, cmd, p):
        if cmd == "LED":
            self.m.led = str(p.get("state", "on")).lower() in ("on", "1", "true")
            return True, f"LED indicador {'ON' if self.m.led else 'OFF'}"
        if cmd == "REBOOT":
            threading.Timer(1.0, self.client.reconnect).start()
            return True, "reiniciando..."
        return False, f"comando desconocido: {cmd}"


class Suelo(EmuBase):
    device_id, zone, name = "dev-02", "lote1", "Nodo suelo y riego (ESP32+capacitivo+relé)"

    def __init__(self):
        super().__init__()
        self.m = SueloModel()

    def step_model(self, dt, now):
        self.m.step(dt, now, WEATHER)

    def sample(self, now):
        return self.m.read()

    def handle_command(self, cmd, p):
        if cmd in ("RELAY", "RIEGO"):
            on = str(p.get("state", p.get("relay", "ON"))).upper() == "ON"
            if on and not self.rules_allowed(p):
                return False, "modo manual: se ignora la regla automática"
            self.m.rele = on
            mins = float(p.get("duration_min", 15)) if on else 0
            self.m.rele_hasta = time.time() + mins * 60 if on else None
            return True, f"relé {'ON ' + str(int(mins)) + ' min' if on else 'OFF'}"
        if cmd == "SET_THRESHOLD":
            self.m.umbral = max(10.0, min(60.0, float(p.get("value", 35))))
            return True, f"umbral de riego {self.m.umbral:.0f}%"
        return False, f"comando desconocido: {cmd}"

    def extra_status(self):
        return {**super().extra_status(), "valvula": 1 if self.m.rele else 0, "umbral_pct": self.m.umbral}


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    devs = [Microclima(), Suelo()]
    for d in devs:
        d.start()
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    stop.wait()
    for d in devs:
        d.stop()


if __name__ == "__main__":
    main()
