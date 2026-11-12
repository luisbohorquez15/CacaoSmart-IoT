"""
Dispositivos tipo DataSet (DEV-09 y DEV-10): reproducen datos históricos como si fueran sensores.

DEV-09  Histórico climático cosecha 2025 (lote de control)  -> uplink MQTT
        Reproducción "sync": publica el valor medido a la MISMA hora del año anterior (now - 365 d),
        para comparar en vivo "este año vs. 2025". Reproducción "accelerated": avanza N veces más rápido.
DEV-10  Curva ideal de secado (benchmark de calidad)          -> uplink HTTP REST (POST /api/ingest/dev-10)
        Se sincroniza con el lote real de la marquesina (DEV-08): publica la humedad objetivo
        correspondiente a las horas transcurridas del lote, para superponer real vs. ideal.

Ambos aceptan comandos de retroceso por MQTT (PAUSE, RESUME, SET_SPEED, SET_REPLAY, INJECT_ANOMALY, SET_PROFILE...).
    python -m cacaosmart.run_datasets
"""
from __future__ import annotations

import bisect
import csv
import json
import logging
import os
import signal
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from .core import Device, REGION, utcnow_iso
from .models import COT

DATA = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parent.parent / "datasets" / "data"))
YEAR_S = 365 * 86400


def _num(v: str):
    try:
        return float(v)
    except ValueError:
        return v


class DatasetBase(Device):
    dtype = "dataset"
    default_interval = 60.0

    def __init__(self) -> None:
        super().__init__()
        self.paused = False

    def handle_dataset(self, cmd, p):
        if cmd == "PAUSE":
            self.paused = True
            return True, "reproducción en pausa"
        if cmd == "RESUME":
            self.paused = False
            return True, "reproducción reanudada"
        return None

    def extra_status(self):
        return {"paused": 1 if self.paused else 0}


# ------------------------------------------------------------------ DEV-09
class HistoricoClima(DatasetBase):
    device_id, zone, name = "dev-09", "historico", "Histórico climático cosecha 2025"
    FIELDS = ["temp_ref_c", "hr_ref_pct", "humedad_suelo_ref_pct", "humedad_suelo_20cm_pct", "et0_mm_h",
              "et0_dia_mm", "precipitacion_mm", "radiacion_wm2", "nubosidad_pct", "viento_kmh"]

    def __init__(self) -> None:
        super().__init__()
        rows = list(csv.DictReader(open(DATA / "historico_clima_cosecha_2025.csv", encoding="utf-8")))
        self.times = [datetime.fromisoformat(r["time"]).replace(tzinfo=COT).timestamp() for r in rows]
        self.rows = [{k: _num(r[k]) for k in self.FIELDS} for r in rows]
        self.replay = "sync"
        self.speed = 1.0
        self.cursor = None                 # tiempo del dataset en modo acelerado
        self.anomaly = (0.0, 0.0)          # (delta °C, vence_en)

    def dataset_time(self, now: float) -> float:
        if self.replay == "sync" or self.cursor is None:
            ts = now - YEAR_S
        else:
            ts = self.cursor
        span = self.times[-1] - self.times[0]
        return self.times[0] + (ts - self.times[0]) % span          # bucle sobre el rango disponible

    def step(self, dt, now):
        if self.replay == "accelerated" and not self.paused:
            self.cursor = (self.cursor or now - YEAR_S) + dt * self.speed

    def sample(self, now):
        if self.paused:
            return None
        ts = self.dataset_time(now)
        i = max(0, min(len(self.times) - 2, bisect.bisect_right(self.times, ts) - 1))
        f = (ts - self.times[i]) / (self.times[i + 1] - self.times[i])
        a, b = self.rows[i], self.rows[i + 1]
        out = {k: round(a[k] + (b[k] - a[k]) * f, 3) for k in self.FIELDS}
        out["precipitacion_mm"] = a["precipitacion_mm"]            # la lluvia no se interpola
        delta, until = self.anomaly
        if delta and now < until:
            out["temp_ref_c"] = round(out["temp_ref_c"] + delta, 3)
            out["anomalia"] = 1
        else:
            out["anomalia"] = 0
        out["dataset_hora"] = int(datetime.fromtimestamp(ts, tz=COT).strftime("%Y%m%d%H"))
        return out

    def handle_command(self, cmd, p):
        r = self.handle_dataset(cmd, p)
        if r:
            return r
        if cmd == "SET_SPEED":
            self.speed = max(1.0, min(1440.0, float(p.get("value", 1))))
            self.replay = "accelerated" if self.speed > 1 else "sync"
            self.cursor = None
            return True, f"velocidad x{self.speed:.0f} ({self.replay})"
        if cmd == "SET_REPLAY" and str(p.get("value")) in ("sync", "accelerated"):
            self.replay = str(p["value"])
            self.cursor = None
            return True, f"reproducción {self.replay}"
        if cmd == "INJECT_ANOMALY":
            delta = float(p.get("delta_c", 5.0))
            mins = float(p.get("minutes", 30))
            self.anomaly = (delta, time.time() + mins * 60)
            return True, f"anomalía térmica {delta:+.1f} °C por {mins:.0f} min"
        return False, f"comando desconocido: {cmd}"

    def extra_status(self):
        return {**super().extra_status(), "speed": self.speed, "replay": self.replay}


# ------------------------------------------------------------------ DEV-10
class CurvaIdealSecado(DatasetBase):
    device_id, zone, name = "dev-10", "historico", "Curva ideal de secado (benchmark)"
    TOPIC_DRYER = f"cacaosmart/{REGION}/beneficio/dev-08/status"

    def __init__(self) -> None:
        super().__init__()
        self.curves: dict[str, list[dict]] = {}
        for r in csv.DictReader(open(DATA / "curva_ideal_secado.csv", encoding="utf-8")):
            self.curves.setdefault(r["perfil"], []).append({k: _num(v) for k, v in r.items() if k != "perfil"})
        self.profile = "sol_intenso"
        self.batch_start = time.time()
        self.subscriptions = [self.TOPIC_DRYER]
        self.ingest_url = os.getenv("INGEST_URL", "http://localhost:1880/api/ingest").rstrip("/") + f"/{self.device_id}"
        self.token = os.getenv("API_TOKEN", "")
        self.http_ok = 0

    def on_external(self, topic, p):
        if topic == self.TOPIC_DRYER and p.get("batch_start"):
            self.batch_start = float(p["batch_start"])

    def sample(self, now):
        if self.paused:
            return None
        h = max(0.0, min(144.0, (now - self.batch_start) / 3600))
        row = self.curves[self.profile][int(round(h * 10))]
        return {"humedad_objetivo_pct": row["humedad_objetivo_pct"], "temp_optima_c": row["temp_optima_c"],
                "tasa_secado_pct_h": row["tasa_secado_pct_h"], "indice_calidad": row["indice_calidad"],
                "hora_curva": round(h, 2), "profile": self.profile}

    def publish_telemetry(self, data, ts=None):
        """Uplink por HTTP REST (no MQTT): demuestra un segundo protocolo de envío."""
        self.seq += 1
        body = {"ts": utcnow_iso(ts), "type": self.dtype, "seq": self.seq, **data}
        req = urllib.request.Request(self.ingest_url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                self.http_ok = 1 if r.status in (200, 201, 202) else 0
        except Exception as e:  # noqa: BLE001
            self.http_ok = 0
            self.log("POST %s falló: %s", self.ingest_url, e)

    def handle_command(self, cmd, p):
        r = self.handle_dataset(cmd, p)
        if r:
            return r
        if cmd == "SET_PROFILE":
            v = str(p.get("value", "")).lower()
            if v not in self.curves:
                return False, f"perfil inválido (use {', '.join(self.curves)})"
            self.profile = v
            return True, f"perfil de referencia: {v}"
        return False, f"comando desconocido: {cmd}"

    def extra_status(self):
        return {**super().extra_status(), "profile": self.profile, "http_ok": self.http_ok}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    devices = [HistoricoClima(), CurvaIdealSecado()]
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
