"""
Exporta los datos REALES capturados en la nube (InfluxDB) al mismo formato CSV que usa charts.py.

En la VM de Azure (InfluxDB escucha sólo en 127.0.0.1:8086):
    python3 analysis/export_influx.py --days 6
Desde su PC, con un túnel SSH:
    ssh -L 8086:localhost:8086 azureuser@<dominio>      (en otra terminal)
    python analysis/export_influx.py --days 6
Salida: analysis/data/real/dev-XX.csv + eventos.csv   ->   python analysis/charts.py --data analysis/data/real
Excluye los puntos de la simulación (etiqueta source=simulacion).
"""
from __future__ import annotations

import argparse
import csv
import io
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def env():
    e = {}
    for line in open(ROOT / ".env", encoding="utf-8"):
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.strip().split("=", 1)
            e[k] = v
    return e


def query(e, flux, url):
    req = urllib.request.Request(f"{url}/api/v2/query?org={e['INFLUX_ORG']}", data=flux.encode(), method="POST",
                                 headers={"Authorization": f"Token {e['INFLUX_TOKEN']}", "Content-Type": "application/vnd.flux",
                                          "Accept": "application/csv"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            text = r.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        raise SystemExit(f"InfluxDB {err.code}: {err.read().decode()}")
    rows = []
    for block in text.strip().split("\r\n\r\n"):
        rows += list(csv.DictReader(io.StringIO(block.strip())))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=6)
    ap.add_argument("--url", default="http://localhost:8086")
    ap.add_argument("--every", default="1m", help="ventana de agregación (reduce volumen)")
    a = ap.parse_args()
    e = env()
    out = ROOT / "analysis" / "data" / "real"
    out.mkdir(parents=True, exist_ok=True)
    rng = f'range(start: -{int(a.days * 24)}h)'
    flux = ('import "types"\n'
            f'from(bucket: "{e["INFLUX_BUCKET"]}") |> {rng}\n'
            ' |> filter(fn: (r) => r._measurement == "telemetry" and (not exists r.source or r.source != "simulacion"))\n'
            ' |> filter(fn: (r) => r._field != "seq" and types.isType(v: r._value, type: "float"))\n'
            f' |> aggregateWindow(every: {a.every}, fn: mean, createEmpty: false)\n'
            ' |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")\n'
            ' |> group(columns: ["device"])')
    by_dev = defaultdict(list)
    for r in query(e, flux, a.url):
        dev = r.get("device")
        if not dev:
            continue
        rec = {"time": r["_time"]}
        rec.update({k: v for k, v in r.items() if k and not k.startswith("_") and k not in
                    ("result", "table", "device", "zone", "region", "type", "source", "topic", "")})
        by_dev[dev].append(rec)
    for dev, rows in by_dev.items():
        keys = sorted({k for r in rows for k in r} - {"time"})
        with open(out / f"{dev}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["time"] + keys)
            w.writeheader()
            w.writerows(sorted(rows, key=lambda r: r["time"]))
        print(f"{dev}: {len(rows)} filas")
    ev_flux = (f'from(bucket: "{e["INFLUX_BUCKET"]}") |> {rng}\n'
               ' |> filter(fn: (r) => (r._measurement == "command" and r._field == "cmd") or (r._measurement == "alert" and r._field == "rule"))\n'
               ' |> filter(fn: (r) => not exists r.source or r.source != "simulacion")')
    with open(out / "eventos.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["time", "device", "kind", "name", "src", "msg"])
        w.writeheader()
        n = 0
        for r in query(e, ev_flux, a.url):
            if r.get("device"):
                w.writerow({"time": r["_time"], "device": r["device"], "kind": r["_measurement"], "name": r["_value"], "src": "", "msg": ""})
                n += 1
    print(f"eventos: {n} -> {out}")


if __name__ == "__main__":
    main()
