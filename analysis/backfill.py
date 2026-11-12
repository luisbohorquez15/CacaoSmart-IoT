"""
Simulación de validación de 6 días (backfill) de CacaoSmart IoT.

Ejecuta EXACTAMENTE los mismos modelos de los gemelos (devices/cacaosmart/models.py), alimentados con el
clima REAL horario de la finca de los últimos días (Open-Meteo, mismo punto que Azure Maps), y una
réplica en Python del motor de reglas de Node-RED. Sirve para:
  1) validar los modelos y las reglas antes de desplegar,
  2) poblar Grafana en local para pruebas,
  3) generar el borrador del informe mientras se capturan los 6 días reales en la nube.
Los datos de este script quedan marcados con la etiqueta source=simulacion en InfluxDB.

    python analysis/backfill.py                      # CSV en analysis/data/simulacion/
    python analysis/backfill.py --influx             # además escribe en InfluxDB local (http://localhost:8086)
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "devices"))
from cacaosmart.models import (COT, DryerModel, FermenterModel, MicroclimaModel, PumpModel,  # noqa: E402
                               ShadeModel, SueloModel, Weather)

random.seed(42)
DATA = ROOT / "analysis" / "data"
OUTDIR = DATA / "simulacion"


def load_weather():
    h = json.load(open(DATA / "clima_ultimos_dias_openmeteo.json", encoding="utf-8"))["hourly"]
    ts = [datetime.fromisoformat(t).replace(tzinfo=COT).timestamp() for t in h["time"]]
    return ts, h


def interp(ts_list, h, key, t):
    i = max(0, min(len(ts_list) - 2, int((t - ts_list[0]) // 3600)))
    f = (t - ts_list[i]) / 3600
    a, b = h[key][i], h[key][i + 1]
    if a is None or b is None:
        return a if a is not None else b
    return a + (b - a) * f


def load_ds09():
    rows = list(csv.DictReader(open(ROOT / "devices/datasets/data/historico_clima_cosecha_2025.csv", encoding="utf-8")))
    return {r["time"]: r for r in rows}


def load_ds10():
    c = {}
    for r in csv.DictReader(open(ROOT / "devices/datasets/data/curva_ideal_secado.csv", encoding="utf-8")):
        c.setdefault(r["perfil"], []).append({k: float(v) for k, v in r.items() if k != "perfil"})
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=6.0)
    ap.add_argument("--influx", action="store_true")
    args = ap.parse_args()

    wts, wh = load_weather()
    ds09, ds10 = load_ds09(), load_ds10()
    end = datetime.now(COT).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=args.days)
    t0, t1 = start.timestamp(), end.timestamp()

    w = Weather()
    shade, pump, ferm, dry = ShadeModel(), PumpModel(), FermenterModel(), DryerModel()
    micro, suelo = MicroclimaModel(), SueloModel(humedad=44.0)
    batch_start = t0
    ahorro = True
    st = {}                                     # estado del motor de reglas (cooldowns)
    rows = {f"dev-{i:02d}": [] for i in range(1, 11)}
    events = []
    dev04 = {}

    def cool(k, minutes, now):
        if k in st and now - st[k] < minutes * 60:
            return False
        st[k] = now
        return True

    def cmd(now, dev, c, **kw):
        events.append({"time": now, "device": dev, "kind": "command", "name": c, "src": "rules",
                       "msg": json.dumps({"cmd": c, **kw}, ensure_ascii=False)})

    def alert(now, dev, rule, sev, msg, cd=60):
        if cool(f"al:{rule}:{dev}", cd, now):
            events.append({"time": now, "device": dev, "kind": "alert", "name": rule, "src": sev, "msg": msg})

    dt = 30.0
    t = t0
    step = 0
    while t <= t1:
        # ---------------------------------------------------- clima real interpolado (lo que entrega DEV-03)
        w.temp_c = interp(wts, wh, "temperature_2m", t)
        w.rh = interp(wts, wh, "relative_humidity_2m", t)
        w.cloud = interp(wts, wh, "cloud_cover", t)
        w.uv = interp(wts, wh, "uv_index", t)
        w.wind_kmh = interp(wts, wh, "wind_speed_10m", t)
        w.rain_mm_h = wh["precipitation"][max(0, min(len(wts) - 1, int((t - wts[0]) // 3600)))] or 0.0
        w.rain_prob = interp(wts, wh, "precipitation_probability", t) or 0

        # ---------------------------------------------------- física de los gemelos
        shade.step(dt, t, w)
        alarma = pump.step(dt, t, w)
        if alarma:
            alert(t, "dev-06", "fuga", "critical", alarma, 30)
        ferm_new = ferm.step(dt, t, w)
        if dry.step(dt, t, w):
            batch_start = t
        suelo.step(dt, t, w)

        minute = int((t - t0) // 60)
        # ---------------------------------------------------- muestreo y motor de reglas cada 5 min
        if step % 10 == 0:
            iso = t
            r03 = {"temp_c": w.temp_c + random.gauss(0, 0.1), "sensacion_c": interp(wts, wh, "apparent_temperature", t),
                   "punto_rocio_c": interp(wts, wh, "dew_point_2m", t), "hr_pct": w.rh, "uv_index": round(w.uv),
                   "viento_kmh": w.wind_kmh, "rafaga_kmh": interp(wts, wh, "wind_gusts_10m", t), "nubosidad_pct": w.cloud,
                   "presion_hpa": interp(wts, wh, "pressure_msl", t), "lluvia_1h_mm": w.rain_mm_h,
                   "es_dia": int(interp(wts, wh, "is_day", t) > 0.5)}
            if minute % 10 == 0:
                rows["dev-03"].append({"time": iso, **r03})
            if minute % 15 == 0:
                i = int((t - wts[0]) // 3600)
                probs = [wh["precipitation_probability"][min(len(wts) - 1, i + k)] or 0 for k in range(12)]
                prec = [wh["precipitation"][min(len(wts) - 1, i + k)] or 0 for k in range(12)]
                dev04 = {"prob_lluvia_pct": probs[0], "prob_lluvia_3h_pct": max(probs[:3]), "prob_lluvia_max_12h": max(probs),
                         "precip_12h_mm": round(sum(prec), 1), "horas_lluvia_12h": sum(1 for p in prec if p > 0.1),
                         "nubosidad_pct": w.cloud, "temp_prox_h_c": interp(wts, wh, "temperature_2m", t + 3600),
                         "uv_max_12h": max(wh["uv_index"][min(len(wts) - 1, i + k)] or 0 for k in range(12)),
                         "ahorro_agua": int(ahorro)}
                rows["dev-04"].append({"time": iso, **dev04})
            r01 = micro.read(t, w)
            r02 = suelo.read()
            rows["dev-01"].append({"time": iso, **r01})
            rows["dev-02"].append({"time": iso, **r02})
            rows["dev-05"].append({"time": iso, **shade.read(w)})
            rows["dev-06"].append({"time": iso, **pump.read()})
            r07 = ferm.read(w); r07.pop("phase")
            rows["dev-07"].append({"time": iso, **r07})
            r08 = dry.read()
            rows["dev-08"].append({"time": iso, **r08})
            # DEV-09: mismo instante hace 365 días
            k = datetime.fromtimestamp(t - 365 * 86400, tz=COT).strftime("%Y-%m-%dT%H:00")
            if k in ds09:
                r = ds09[k]
                rows["dev-09"].append({"time": iso, **{c: float(r[c]) for c in r if c != "time"}, "anomalia": 0})
            # DEV-10: curva ideal sincronizada con el lote de la marquesina
            hcur = max(0.0, min(144.0, (t - batch_start) / 3600))
            c10 = ds10["sol_intenso"][int(round(hcur * 10))]
            rows["dev-10"].append({"time": iso, "humedad_objetivo_pct": c10["humedad_objetivo_pct"], "temp_optima_c": c10["temp_optima_c"],
                                   "tasa_secado_pct_h": c10["tasa_secado_pct_h"], "indice_calidad": c10["indice_calidad"], "hora_curva": round(hcur, 2)})

            # ------------------------------------------------ réplica del motor de reglas (rules.js)
            uv = r03["uv_index"]
            deseado = 80 if uv >= 8 else (30 if uv <= 5 else None)
            if deseado is not None and shade.objetivo != deseado and cool("shade", 5, t):
                shade.set_target(deseado); micro.led = deseado == 80
                cmd(t, "dev-05", "SET_SHADE", value=deseado); cmd(t, "dev-01", "LED", state="on" if micro.led else "off")
                if deseado == 80:
                    alert(t, "dev-03", "uv_alto", "warning", f"Índice UV {uv} ≥ 8: polisombra al 80 %", 180)
            if r02["humedad_suelo_pct"] < suelo.umbral and not suelo.rele and cool("riego", 45, t):
                prob = dev04.get("prob_lluvia_3h_pct")
                if prob is not None and prob > 65 and ahorro:
                    alert(t, "dev-02", "riego_inhibido", "info", f"Suelo {r02['humedad_suelo_pct']} % pero lluvia {prob} %: riego bloqueado", 60)
                else:
                    mins = 15 if (prob is None or prob < 30) else 8
                    suelo.rele, suelo.rele_hasta = True, t + mins * 60
                    pump.start(t, mins, 30)
                    cmd(t, "dev-02", "RELAY", state="ON", duration_min=mins); cmd(t, "dev-06", "START", duration_min=mins)
                    alert(t, "dev-02", "riego_auto", "info", f"Riego automático {mins} min (suelo {r02['humedad_suelo_pct']} %, lluvia {prob} %)", 30)
            if r01["hr_pct"] > 88 and r01["temp_c"] > 26:
                st["monil"] = st.get("monil") or t
                if t - st["monil"] >= 4 * 3600:
                    alert(t, "dev-01", "moniliasis", "critical", "Riesgo de Moniliasis: HR > 88 % y T > 26 °C por 4 h", 360)
            else:
                st["monil"] = None
            tm, hf, nv = r07["temp_masa_c"], r07["horas_fermentacion"], r07["volteos"]
            if tm > 50 and cool("volteo", 120, t):
                ferm.voltear(); cmd(t, "dev-07", "VOLTEO")
                alert(t, "dev-07", "fermentacion_alta", "warning", f"Masa a {tm} °C (> 50 °C): volteo automático", 120)
            elif ((hf >= 48 and nv < 1) or (hf >= 96 and nv < 2)) and cool("volteo_prog", 60, t):
                ferm.voltear(); cmd(t, "dev-07", "VOLTEO")
            ti = r08["temp_interna_c"]
            lluvia = w.rain_mm_h > 0 or dev04.get("prob_lluvia_pct", 0) >= 65
            ext_d = 1 if ti > 45 else (0 if ti < 40 else int(dry.extractores))
            comp_d = 1 if ti > 45 else (0 if lluvia else 1)
            if ext_d != int(dry.extractores) and cool("ext", 5, t):
                dry.extractores = bool(ext_d); cmd(t, "dev-08", "EXTRACTORES", state="on" if ext_d else "off")
            if comp_d != int(dry.compuertas) and cool("comp", 5, t):
                dry.compuertas = bool(comp_d); cmd(t, "dev-08", "COMPUERTAS", state="open" if comp_d else "close")
            if ti > 46:
                alert(t, "dev-08", "sobrecalentamiento", "critical", f"Marquesina a {ti} °C (> 46 °C)", 60)
            if r08["humedad_grano_pct"] - c10["humedad_objetivo_pct"] > 8:
                alert(t, "dev-08", "secado_retrasado", "info", "Grano > 8 pts sobre la curva ideal", 360)
            if r08["humedad_grano_pct"] <= 7:
                alert(t, "dev-08", "lote_listo", "info", f"Lote #{r08['lote']} seco ≤ 7 % (NTC 1252)", 720)
        t += dt
        step += 1

    # -------------------------------------------------------- escritura
    OUTDIR.mkdir(parents=True, exist_ok=True)
    for dev, rs in rows.items():
        if not rs:
            continue
        keys = list(rs[0].keys())
        with open(OUTDIR / f"{dev}.csv", "w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, fieldnames=keys)
            wr.writeheader()
            for r in rs:
                wr.writerow({k: (datetime.fromtimestamp(r[k], tz=COT).isoformat() if k == "time" else
                                 (round(r[k], 3) if isinstance(r[k], float) else r[k])) for k in keys})
    with open(OUTDIR / "eventos.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=["time", "device", "kind", "name", "src", "msg"])
        wr.writeheader()
        for e in sorted(events, key=lambda e: e["time"]):
            wr.writerow({**e, "time": datetime.fromtimestamp(e["time"], tz=COT).isoformat()})
    print(f"simulación {start:%Y-%m-%d %H:%M} -> {end:%Y-%m-%d %H:%M}: "
          f"{sum(len(v) for v in rows.values())} registros, {len(events)} eventos -> {OUTDIR}")

    if args.influx:
        write_influx(rows, events)


def write_influx(rows, events):
    env = {}
    for line in open(ROOT / ".env", encoding="utf-8"):
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1); env[k] = v
    zones = {"dev-01": "lote1", "dev-02": "lote1", "dev-05": "lote1", "dev-06": "lote1", "dev-03": "clima", "dev-04": "clima",
             "dev-07": "beneficio", "dev-08": "beneficio", "dev-09": "historico", "dev-10": "historico"}
    types = {"dev-01": "real", "dev-02": "real", "dev-03": "api", "dev-04": "api", "dev-09": "dataset", "dev-10": "dataset"}
    lines = []
    for dev, rs in rows.items():
        for r in rs:
            fields = ",".join(f"{k}={float(v)}" for k, v in r.items() if k != "time" and isinstance(v, (int, float)))
            lines.append(f"telemetry,device={dev},zone={zones[dev]},region=santander,type={types.get(dev, 'twin')},source=simulacion {fields} {int(r['time'])}")
    for e in events:
        esc = lambda s: str(s).replace('"', "'")  # noqa: E731
        if e["kind"] == "command":
            lines.append(f'command,device={e["device"]},zone={zones[e["device"]]},source=simulacion cmd="{e["name"]}",src="rules" {int(e["time"])}')
        else:
            lines.append(f'alert,device={e["device"]},zone={zones[e["device"]]},source=simulacion rule="{e["name"]}",severity="{e["src"]}",msg="{esc(e["msg"])}",value=0 {int(e["time"])}')
    url = f"http://localhost:8086/api/v2/write?org={env['INFLUX_ORG']}&bucket={env['INFLUX_BUCKET']}&precision=s"
    for i in range(0, len(lines), 5000):
        req = urllib.request.Request(url, data="\n".join(lines[i:i + 5000]).encode(), method="POST",
                                     headers={"Authorization": f"Token {env['INFLUX_TOKEN']}", "Content-Type": "text/plain"})
        urllib.request.urlopen(req, timeout=30).read()
    print(f"InfluxDB: {len(lines)} líneas escritas (source=simulacion)")


if __name__ == "__main__":
    main()
