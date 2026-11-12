"""
Construye los dos datasets que reproducen DEV-09 y DEV-10.

DEV-09  historico_clima_cosecha_2025.csv
        Datos REALES horarios (oct-dic 2025) del reanálisis ERA5/ERA5-Land servido por Open-Meteo
        para San Vicente de Chucurí (6.88 N, -73.41 W, 642 m): temperatura, HR, humedad de suelo,
        evapotranspiración FAO-56, lluvia y radiación. Licencia CC BY 4.0.
DEV-10  curva_ideal_secado.csv
        Curva de referencia de secado de cacao (0-144 h) generada con el modelo de capa delgada de
        Page  MR = exp(-k·t^n)  para dos perfiles climáticos (sol intenso / nublado), con humedad
        inicial 55 % y meta comercial <= 7 % (NTC 1252).
Uso:  python devices/datasets/build_datasets.py
"""
import csv
import math
from pathlib import Path

D = Path(__file__).parent / "data"

# ----------------------------------------------------------------- DEV-09
rows = list(csv.reader(open(D / "openmeteo_2025_raw.csv", encoding="utf-8")))
hdr_i = next(i for i, r in enumerate(rows) if r and r[0] == "time")
data = rows[hdr_i + 1:]
out = []
et_window = []
for r in data:
    t, temp, rh, pr, rad, sm0, sm7, et0, cc, ws = r
    et_window.append(float(et0)); et_window = et_window[-24:]
    out.append({"time": t, "temp_ref_c": temp, "hr_ref_pct": rh,
                "humedad_suelo_ref_pct": round(float(sm0) * 100, 1), "humedad_suelo_20cm_pct": round(float(sm7) * 100, 1),
                "et0_mm_h": et0, "et0_dia_mm": round(sum(et_window), 2), "precipitacion_mm": pr,
                "radiacion_wm2": rad, "nubosidad_pct": cc, "viento_kmh": ws})
with open(D / "historico_clima_cosecha_2025.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
print("DEV-09:", len(out), "filas")

# ----------------------------------------------------------------- DEV-10
M0, ME = 55.0, 6.0
PERFILES = {"sol_intenso": dict(k=0.0204, n=1.10, t_mid=37.0, t_amp=5.0, q_base=95.0),
            "nublado":     dict(k=0.0136, n=1.10, t_mid=34.0, t_amp=3.0, q_base=88.0)}
out = []
for perfil, p in PERFILES.items():
    prev = M0
    for tenth in range(0, 1441):
        h = tenth / 10
        m = ME + (M0 - ME) * math.exp(-p["k"] * h ** p["n"]) if h > 0 else M0
        rate = (prev - m) * 10 if h > 0 else 0.0
        prev = m
        temp = p["t_mid"] + p["t_amp"] * math.sin(2 * math.pi * (h - 3) / 24)
        # Índice de calidad esperado: penaliza secado muy rápido (acidez) o lento con grano húmedo (moho)
        q = p["q_base"] - 20 * max(0.0, rate - 0.7) - (4 if (h > 72 and m > 25) else 0)
        out.append({"perfil": perfil, "hora": h, "humedad_objetivo_pct": round(m, 2),
                    "temp_optima_c": round(min(42, max(32, temp)), 2), "tasa_secado_pct_h": round(rate, 3),
                    "indice_calidad": round(max(0, min(100, q)), 1)})
with open(D / "curva_ideal_secado.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
print("DEV-10:", len(out), "filas")
