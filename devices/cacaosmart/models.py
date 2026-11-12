"""
Modelos físicos de los gemelos digitales de CacaoSmart IoT.

Son clases "puras" (sin red): reciben el clima (Weather) y avanzan con step(dt).
Las usan tanto los dispositivos en vivo (run_twins.py) como la simulación de
validación (analysis/backfill.py), así el comportamiento es idéntico en ambos.

Referencias de los modelos:
- Irradiancia de cielo despejado: Haurwitz (1945).   GHI_cs = 1098·sin(h)·exp(-0.057/sin(h))
- Atenuación por nubosidad: Kasten & Czeplak (1980). GHI = GHI_cs·(1 - 0.75·N^3.4)
- Secado del grano: cinética de capa delgada tipo Lewis/Page (Hii et al., 2009).
- Fermentación: fases levadura (anaeróbica) -> bacterias acéticas (aeróbica tras el volteo),
  temperaturas de 45-50 °C y pH de pulpa 3.8 -> 5.2 (Schwan & Wheals, 2004).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

LAT = 6.8817
LON = -73.4103
COT = timezone(timedelta(hours=-5))      # Colombia (sin horario de verano)


# =============================================================== clima y sol
def solar_elevation(ts: float, lat: float = LAT, lon: float = LON) -> float:
    """Elevación solar en grados (aprox. NOAA, suficiente para el gemelo)."""
    d = datetime.fromtimestamp(ts, tz=timezone.utc)
    doy = d.timetuple().tm_yday
    g = 2 * math.pi / 365 * (doy - 1 + (d.hour - 12) / 24)
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                    - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    tst = d.hour * 60 + d.minute + d.second / 60 + eqt + 4 * lon
    ha = math.radians(tst / 4 - 180)
    la = math.radians(lat)
    cz = math.sin(la) * math.sin(decl) + math.cos(la) * math.cos(decl) * math.cos(ha)
    return math.degrees(math.asin(max(-1.0, min(1.0, cz))))


def ghi(ts: float, cloud_pct: float) -> float:
    h = solar_elevation(ts)
    if h <= 0:
        return 0.0
    s = math.sin(math.radians(h))
    cs = 1098 * s * math.exp(-0.057 / s)
    return max(0.0, cs * (1 - 0.75 * (max(0.0, min(100.0, cloud_pct)) / 100) ** 3.4))


@dataclass
class Weather:
    """Estado del clima exterior. En vivo se alimenta de la API de Azure Maps (DEV-03/DEV-04)."""
    temp_c: float = 25.0
    rh: float = 80.0
    cloud: float = 50.0
    uv: float = 0.0
    wind_kmh: float = 5.0
    rain_prob: float = 20.0
    rain_mm_h: float = 0.0
    ts_update: float = 0.0
    live: bool = False

    def synthetic(self, ts: float) -> None:
        """Respaldo si la API no está disponible: ciclo diario típico de San Vicente de Chucurí."""
        hour = datetime.fromtimestamp(ts, tz=COT).hour + datetime.fromtimestamp(ts, tz=COT).minute / 60
        c = math.cos(2 * math.pi * (hour - 15) / 24)
        self.temp_c = 25.5 + 4.5 * c + random.gauss(0, 0.2)
        self.rh = min(98, max(55, 80 - 14 * c + random.gauss(0, 1)))
        self.cloud = max(5, min(100, self.cloud + random.gauss(0, 2)))
        self.uv = max(0.0, 11 * math.sin(math.radians(max(0, solar_elevation(ts)))) * (1 - 0.5 * self.cloud / 100))

    def ghi(self, ts: float) -> float:
        return ghi(ts, self.cloud)


def noise(sigma: float) -> float:
    return random.gauss(0, sigma)


# =============================================================== DEV-05 Polisombra
@dataclass
class ShadeModel:
    cierre: float = 30.0          # % de despliegue de la malla (0 = abierta/recogida, 100 = cerrada)
    objetivo: float = 30.0
    velocidad: float = 1.2        # %/s del motor
    corriente: float = 0.05
    rad_ext: float = 0.0
    rad_filtrada: float = 0.0
    factor_sombra: float = 0.70   # malla Raschel al 70 %

    def set_target(self, v: float) -> None:
        self.objetivo = max(0.0, min(100.0, v))

    def step(self, dt: float, ts: float, w: Weather) -> None:
        err = self.objetivo - self.cierre
        mov = max(-self.velocidad * dt, min(self.velocidad * dt, err))
        self.cierre += mov
        moving = abs(mov) > 1e-6
        self.corriente = (1.85 + 0.25 * abs(math.sin(ts)) + noise(0.04)) if moving else max(0.0, 0.05 + noise(0.01))
        self.rad_ext = w.ghi(ts)
        self.rad_filtrada = self.rad_ext * (1 - self.factor_sombra * self.cierre / 100)

    def read(self, w: Weather) -> dict:
        return {"cierre_pct": round(self.cierre, 1), "corriente_a": round(self.corriente, 3),
                "rad_ext_wm2": round(max(0.0, self.rad_ext + noise(3)) if self.rad_ext else 0.0, 1),
                "rad_filtrada_wm2": round(max(0.0, self.rad_filtrada + noise(2)) if self.rad_filtrada else 0.0, 1),
                "uv_index": round(w.uv, 1), "objetivo_pct": round(self.objetivo, 1)}


# =============================================================== DEV-06 Bomba de riego
@dataclass
class PumpModel:
    encendida: bool = False
    caudal_obj: float = 30.0      # L/min
    caudal: float = 0.0
    presion: float = 4.0          # PSI (columna estática con bomba apagada)
    consumo_dia: float = 0.0      # L
    consumo_total: float = 0.0
    fuga: bool = False
    apagar_en: float | None = None
    disparo_emergencia: bool = False
    _dia: int = -1

    def start(self, ts: float, minutos: float | None = None, caudal: float | None = None) -> None:
        self.encendida = True
        self.disparo_emergencia = False
        if caudal:
            self.caudal_obj = max(5.0, min(45.0, caudal))
        self.apagar_en = ts + minutos * 60 if minutos else None

    def stop(self) -> None:
        self.encendida = False
        self.apagar_en = None

    def step(self, dt: float, ts: float, w: Weather) -> str | None:
        """Devuelve un mensaje si el interlock de seguridad local actúa."""
        day = datetime.fromtimestamp(ts, tz=COT).toordinal()
        if day != self._dia:
            self._dia, self.consumo_dia = day, 0.0
        if self.apagar_en and ts >= self.apagar_en:
            self.stop()
        target = self.caudal_obj * (1.35 if self.fuga else 1.0) if self.encendida else 0.0
        self.caudal += (target - self.caudal) * min(1.0, dt / 4.0)        # rampa ~4 s
        # Curva de la bomba: P = P0 - a·Q²; una fuga hace caer la presión de línea
        if self.encendida:
            p = 38.0 - 0.012 * self.caudal ** 2
            if self.fuga:
                p *= 0.45
        else:
            p = 4.0
        self.presion += (p - self.presion) * min(1.0, dt / 3.0)
        litros = self.caudal * dt / 60
        self.consumo_dia += litros
        self.consumo_total += litros
        # Interlock local (edge): presión < 12 PSI con bomba encendida = fuga -> parada de emergencia
        if self.encendida and self.presion < 12.0 and self.caudal > 5:
            self.stop()
            self.disparo_emergencia = True
            return "PARADA DE EMERGENCIA: caída de presión (posible fuga)"
        return None

    def read(self) -> dict:
        on = self.caudal > 0.3
        return {"caudal_lpm": round(max(0.0, self.caudal + (noise(0.3) if on else 0)), 2),
                "presion_psi": round(self.presion + noise(0.15), 2),
                "consumo_l": round(self.consumo_dia, 1), "consumo_total_l": round(self.consumo_total, 1),
                "bomba": 1 if self.encendida else 0, "fuga": 1 if self.fuga else 0,
                "emergencia": 1 if self.disparo_emergencia else 0}


# =============================================================== DEV-07 Cajón de fermentación
def _sig(x: float) -> float:
    return 1 / (1 + math.exp(-x))


@dataclass
class FermenterModel:
    horas: float = 0.0
    temp: float = 26.0
    o2: float = 0.6               # oxigenación relativa de la masa (sube con cada volteo)
    volteos: int = 0
    ciclo: int = 1
    duracion_h: float = 144.0

    def voltear(self) -> None:
        self.temp -= 3.0          # el volteo enfría ~3 °C y oxigena
        self.o2 = 1.0
        self.volteos += 1

    def reset(self, t_amb: float = 26.0) -> None:
        self.horas, self.temp, self.o2, self.volteos = 0.0, t_amb + 1.0, 0.6, 0
        self.ciclo += 1

    def calor(self) -> float:
        h = self.horas
        levadura = 9.0 * math.exp(-((h - 30) / 16) ** 2)                       # fase anaeróbica
        acetica = 27.0 * _sig((h - 36) / 5) * (0.5 + 0.5 * self.o2) * (1 - _sig((h - 118) / 8))
        return levadura + acetica                                              # °C sobre ambiente en equilibrio

    def step(self, dt: float, ts: float, w: Weather) -> bool:
        """Devuelve True si terminó el ciclo (se inicia un nuevo lote)."""
        self.horas += dt / 3600
        t_amb = w.temp_c - 1.0                                   # bajo techo, a la sombra
        objetivo = t_amb + self.calor()
        self.temp += (objetivo - self.temp) * min(1.0, dt / (3.0 * 3600))     # constante térmica ~3 h
        self.o2 = max(0.0, self.o2 - dt / (24 * 3600) * self.o2)              # consumo de O2
        if self.horas >= self.duracion_h:
            self.reset(t_amb)
            return True
        return False

    def ph(self) -> float:
        return 3.8 + 1.4 * _sig((self.horas - 60) / 16) - 0.03

    def fase(self) -> str:
        if self.horas < 36:
            return "anaerobica"
        if self.horas < 110:
            return "acetica"
        return "maduracion"

    def read(self, w: Weather) -> dict:
        return {"temp_masa_c": round(self.temp + noise(0.08), 2), "ph_mucilago": round(self.ph() + noise(0.02), 3),
                "horas_fermentacion": round(self.horas, 2), "temp_ambiente_c": round(w.temp_c - 1.0, 2),
                "volteos": self.volteos, "ciclo": self.ciclo, "phase": self.fase()}


# =============================================================== DEV-08 Marquesina de secado
@dataclass
class DryerModel:
    humedad: float = 55.0         # % base húmeda del grano
    temp: float = 27.0
    hr: float = 80.0
    extractores: bool = False
    compuertas: bool = True       # abiertas = ventilación natural
    horas: float = 0.0
    lote: int = 1
    listo_desde: float | None = None

    def reset(self) -> None:
        self.humedad, self.horas, self.listo_desde = 55.0, 0.0, None
        self.lote += 1

    def step(self, dt: float, ts: float, w: Weather) -> bool:
        self.horas += dt / 3600
        g = w.ghi(ts)
        # Balance térmico simplificado del invernadero-marquesina (cubierta plástica)
        ganancia = 0.028 * g
        enfriamiento = (4.0 if self.extractores else 0.0) + (2.5 if self.compuertas else 0.0)
        t_obj = w.temp_c + ganancia - enfriamiento * (ganancia / (ganancia + 4) if ganancia else 0.3)
        self.temp += (t_obj - self.temp) * min(1.0, dt / 1200)
        # Humedad relativa interna: el aire se calienta (baja HR) y los extractores la renuevan
        hr_obj = w.rh - 2.2 * (self.temp - w.temp_c) - (8 if self.extractores else 0)
        if w.rain_mm_h > 0.2 and self.compuertas:
            hr_obj += 10
        self.hr += (max(25.0, min(99.0, hr_obj)) - self.hr) * min(1.0, dt / 900)
        # Cinética de secado tipo Lewis: dM/dt = -k(T,HR)·(M - Me)
        me = 4.0 + 0.09 * self.hr                     # humedad de equilibrio aprox.
        k = 0.026 * max(0.0, (self.temp - 18) / 12) ** 1.6 * (1.25 - self.hr / 100) * (1.25 if self.extractores else 1.0)
        self.humedad += -k * (self.humedad - me) * dt / 3600
        self.humedad = max(5.5, min(60.0, self.humedad))
        if self.humedad <= 7.0 and self.listo_desde is None:
            self.listo_desde = ts
        if self.listo_desde and ts - self.listo_desde > 10 * 3600:   # se descarga y entra un lote nuevo
            self.reset()
            return True
        return False

    def read(self) -> dict:
        return {"humedad_grano_pct": round(self.humedad + noise(0.05), 2), "temp_interna_c": round(self.temp + noise(0.1), 2),
                "hr_interna_pct": round(self.hr + noise(0.4), 1), "extractores": 1 if self.extractores else 0,
                "compuertas": 1 if self.compuertas else 0, "horas_secado": round(self.horas, 2), "lote": self.lote}


# =============================================================== Emuladores de los nodos reales
@dataclass
class MicroclimaModel:
    """Réplica de DEV-01 (ESP32 + DHT22 + LDR) para pruebas sin hardware."""
    led: bool = False

    def read(self, ts: float, w: Weather) -> dict:
        g = w.ghi(ts)
        sombra = 0.55                                       # bajo el dosel del cacaotal
        return {"temp_c": round(w.temp_c - 0.8 + noise(0.15), 2),
                "hr_pct": round(min(99.0, w.rh + 4 + noise(0.8)), 1),
                "luz_lux": round(max(0.0, g * 120 * sombra + noise(150 if g else 2)), 0),
                "rssi_dbm": int(-62 + noise(3)), "led": 1 if self.led else 0}


@dataclass
class SueloModel:
    """Réplica de DEV-02 (ESP32 + sensor capacitivo + relé) para pruebas sin hardware."""
    humedad: float = 48.0
    rele: bool = False
    rele_hasta: float | None = None
    bateria: float = 4.05
    umbral: float = 35.0

    def step(self, dt: float, ts: float, w: Weather) -> None:
        if self.rele_hasta and ts >= self.rele_hasta:
            self.rele, self.rele_hasta = False, None
        g = w.ghi(ts)
        et = (0.00018 * g + 0.004) * (1.2 - w.rh / 100)          # %/min de pérdida por evapotranspiración
        self.humedad -= et * dt / 60
        if self.rele:
            self.humedad += 0.55 * dt / 60                         # goteo
        if w.rain_mm_h > 0:
            self.humedad += 0.08 * w.rain_mm_h * dt / 60
        if self.humedad > 52.0:                                    # drenaje por encima de capacidad de campo
            self.humedad -= 0.012 * (self.humedad - 52.0) * dt / 60
        self.humedad = max(15.0, min(70.0, self.humedad))
        self.bateria += (0.0000010 * g - 0.00018) * dt / 60         # panel solar pequeño vs consumo del nodo
        self.bateria = max(3.3, min(4.2, self.bateria))

    def read(self) -> dict:
        return {"humedad_suelo_pct": round(self.humedad + noise(0.3), 2), "valvula": 1 if self.rele else 0,
                "bateria_v": round(self.bateria + noise(0.005), 3), "umbral_pct": self.umbral}
