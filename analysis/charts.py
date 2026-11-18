"""
Gráficas y estadísticos del informe (promedio, máx., mín., desviación, por día, correlaciones, eventos).

    python analysis/charts.py --data analysis/data/real          # datos capturados en la nube (export_influx.py)
    python analysis/charts.py --data analysis/data/simulacion    # simulación de validación (backfill.py)

Salida: docs/figuras/*.png  y  docs/build/stats.json
Criterios de diseño: una sola escala Y por panel (variables de distinta unidad -> paneles apilados con eje X
compartido), paleta categórica validada para daltonismo, series de referencia en gris discontinuo,
leyenda siempre presente con >= 2 series y bandas de umbral sombreadas.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "docs" / "figuras"
BUILD = ROOT / "docs" / "build"
TZ = "America/Bogota"

# Paleta categórica (validada: lightness, chroma, CVD ΔE ≥ 21, contraste ≥ 3:1 sobre #fcfcfb)
P = ["#D9622B", "#2E7FC0", "#4C9A2A", "#8E4FC2", "#B8860B"]
REF = "#8B8D98"          # series de referencia (dataset / ideal / umbral): gris discontinuo
INK, MUTED, GRID = "#2A1D14", "#6F6259", "#E8E2DC"
BAND_OK, BAND_BAD = "#4C9A2A", "#D9622B"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": GRID, "axes.labelcolor": MUTED,
    "axes.titlesize": 10, "axes.titleweight": "bold", "axes.titlecolor": INK, "axes.titlelocation": "left",
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False, "legend.fontsize": 8,
    "figure.facecolor": "white", "axes.facecolor": "#FCFCFB", "lines.linewidth": 1.6, "savefig.dpi": 200,
})

VARS = {  # variable -> (etiqueta, unidad)
    "dev-01": {"ruido_dbfs": ("Nivel de ruido (micrófono)", "dBFS"), "movimiento": ("Movimiento / vibración", "m/s²")},
    "dev-02": {"cpu_pct": ("Carga de CPU", "%"), "ram_pct": ("Memoria RAM", "%"), "disco_pct": ("Uso de disco", "%"),
               "valvula": ("Electroválvula (actuador)", "0/1"), "led": ("LED aviso UV (actuador)", "0/1")},
    "dev-03": {"temp_c": ("Temperatura exterior", "°C"), "hr_pct": ("Humedad relativa", "%"), "uv_index": ("Índice UV", ""),
               "viento_kmh": ("Viento", "km/h"), "nubosidad_pct": ("Nubosidad", "%"), "presion_hpa": ("Presión", "hPa")},
    "dev-04": {"prob_lluvia_pct": ("Prob. lluvia próx. hora", "%"), "prob_lluvia_max_12h": ("Prob. lluvia máx. 12 h", "%"),
               "precip_12h_mm": ("Lluvia esperada 12 h", "mm"), "nubosidad_pct": ("Nubosidad", "%")},
    "dev-05": {"cierre_pct": ("Cierre de malla", "%"), "rad_ext_wm2": ("Radiación exterior", "W/m²"),
               "rad_filtrada_wm2": ("Radiación filtrada", "W/m²"), "corriente_a": ("Corriente motor", "A")},
    "dev-06": {"humedad_suelo_pct": ("Humedad del suelo", "%"), "caudal_lpm": ("Caudal", "L/min"), "presion_psi": ("Presión de línea", "PSI"), "consumo_l": ("Consumo diario", "L")},
    "dev-07": {"temp_masa_c": ("Temperatura de la masa", "°C"), "ph_mucilago": ("pH del mucílago", ""),
               "horas_fermentacion": ("Horas de fermentación", "h")},
    "dev-08": {"humedad_grano_pct": ("Humedad del grano", "%"), "temp_interna_c": ("Temperatura interna", "°C"),
               "hr_interna_pct": ("HR interna", "%")},
    "dev-09": {"temp_ref_c": ("Temperatura 2025", "°C"), "hr_ref_pct": ("HR 2025", "%"), "humedad_suelo_ref_pct": ("Suelo 2025", "%"),
               "et0_dia_mm": ("ET0 24 h", "mm/día")},
    "dev-10": {"humedad_objetivo_pct": ("Humedad objetivo", "%"), "temp_optima_c": ("Temperatura óptima", "°C"),
               "indice_calidad": ("Índice de calidad", "pts")},
}
NAMES = {"dev-01": "Nodo móvil de campo (iPhone real)", "dev-02": "Estación de borde y actuadores (PC real)", "dev-03": "Azure Maps · condiciones actuales",
         "dev-04": "Azure Maps · pronóstico", "dev-05": "Polisombra (gemelo)", "dev-06": "Bomba de goteo y suelo (gemelo)",
         "dev-07": "Cajón de fermentación (gemelo)", "dev-08": "Marquesina de secado (gemelo)",
         "dev-09": "Histórico climático 2025 (dataset)", "dev-10": "Curva ideal de secado (dataset)"}


def load(folder: Path):
    dfs = {}
    for dev in VARS:
        f = folder / f"{dev}.csv"
        if f.exists():
            df = pd.read_csv(f)
            df["time"] = pd.to_datetime(df["time"], utc=True, format="ISO8601").dt.tz_convert(TZ)
            df = df.set_index("time").sort_index()
            # DEV-01/02 son dispositivos reales (iPhone y PC) desde el 14-nov; antes había un emulador de prueba.
            first = {"dev-01": "ruido_dbfs", "dev-02": "cpu_pct"}.get(dev)
            if first and first in df and df[first].notna().any():
                df = df.loc[df[first].first_valid_index():, [c for c in VARS[dev] if c in df]]
            if dev == "dev-01" and "ruido_dbfs" in df:      # -120 dBFS = micrófono suspendido por iOS (no es silencio real)
                df.loc[df["ruido_dbfs"] <= -110, "ruido_dbfs"] = np.nan
            dfs[dev] = df
    ev = pd.read_csv(folder / "eventos.csv") if (folder / "eventos.csv").exists() else pd.DataFrame(columns=["time", "device", "kind", "name", "src", "msg"])
    if len(ev):
        ev["time"] = pd.to_datetime(ev["time"], utc=True, format="ISO8601").dt.tz_convert(TZ)
    return dfs, ev


def fmt_axis(ax):
    ax.xaxis.set_major_locator(mdates.DayLocator(tz=TZ))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b", tz=TZ))
    ax.xaxis.set_minor_locator(mdates.HourLocator(byhour=[6, 12, 18], tz=TZ))
    ax.grid(which="minor", color=GRID, linewidth=0.3)


def end_label(ax, s, color, fmt="{:.1f}"):
    """Etiqueta directa al final de la serie (identidad nunca sólo por color)."""
    s = s.dropna()
    if len(s):
        ax.annotate(fmt.format(s.iloc[-1]), (s.index[-1], s.iloc[-1]), xytext=(4, 0), textcoords="offset points",
                    fontsize=7.5, color=INK, va="center")


def panels(n, title, h=2.0):
    fig, axes = plt.subplots(n, 1, figsize=(10, 0.9 + h * n), sharex=True, constrained_layout=True)
    axes = np.atleast_1d(axes)
    fig.suptitle(title, x=0.01, ha="left", fontsize=12, fontweight="bold", color=INK)
    return fig, axes


def line(ax, s, label, color, ref=False, step=False, unit=""):
    kw = dict(color=REF if ref else color, label=label, linewidth=1.3 if ref else 1.6)
    if ref:
        kw["linestyle"] = (0, (5, 3))
    (ax.step(s.index, s.values, where="post", **kw) if step else ax.plot(s.index, s.values, **kw))
    end_label(ax, s, color)
    if unit:
        ax.set_ylabel(unit)


def save(fig, name):
    FIG.mkdir(parents=True, exist_ok=True)
    for ax in fig.axes:
        fmt_axis(ax)
        if len(ax.get_legend_handles_labels()[0]) >= 2:
            ax.legend(loc="upper left", ncol=4)
    fig.savefig(FIG / name, bbox_inches="tight")
    plt.close(fig)


def shade_on(ax, s, color, label):
    on = s.fillna(0) > 0.5
    if on.any():
        ax.fill_between(s.index, 0, 1, where=on, transform=ax.get_xaxis_transform(), color=color, alpha=0.35, step="post",
                        linewidth=0, label=label)


def figures(d, ev):
    r = lambda dev, c, rule="10min": d[dev][c].resample(rule).mean()  # noqa: E731

    if "dev-01" in d:
        fig, ax = panels(2, "DEV-01 · Nodo móvil de campo (iPhone real · micrófono y acelerómetro · MQTT sobre WSS)")
        line(ax[0], r("dev-01", "ruido_dbfs"), "Ruido promedio 10 min", P[3], unit="dBFS")
        ax[0].set_title("Nivel de ruido ambiental (más alto = más actividad: personas, maquinaria, lluvia)")
        line(ax[1], r("dev-01", "movimiento"), "Movimiento", P[1], unit="m/s²")
        ax[1].set_title("Movimiento / vibración del equipo (desviación de la aceleración)")
        if len(ev):
            for t in ev[(ev.device == "dev-01") & (ev.kind == "command") & (ev.time >= d["dev-01"].index[0])].time:
                ax[0].axvline(t, color=P[0], linewidth=1, alpha=0.7)
            ax[0].plot([], [], color=P[0], label="Alarma remota (retroceso)")
        save(fig, "dev01.png")

    if "dev-02" in d:
        fig, ax = panels(2, "DEV-02 · Estación de borde (PC real · python) con electroválvula y LED de aviso")
        line(ax[0], r("dev-02", "cpu_pct"), "CPU", P[0], unit="%")
        line(ax[0], r("dev-02", "ram_pct"), "RAM", P[1])
        line(ax[0], r("dev-02", "disco_pct"), "Disco", P[2])
        ax[0].set_title("Recursos del equipo de borde")
        v = d["dev-02"]["valvula"].resample("5min").max()
        l = d["dev-02"]["led"].resample("5min").max()
        ax[1].fill_between(v.index, 1.1, 1.1 + 0.8 * v.fillna(0).values, step="post", color=P[1], alpha=0.8, linewidth=0, label="Electroválvula abierta (riego)")
        ax[1].fill_between(l.index, 0, 0.8 * l.fillna(0).values, step="post", color=P[4], alpha=0.8, linewidth=0, label="LED aviso UV encendido")
        ax[1].set_yticks([0.4, 1.5], ["LED UV", "Válvula"]); ax[1].grid(False, axis="y")
        ax[1].set_title("Actuadores ejecutados por el retroceso (motor de reglas y panel)")
        save(fig, "dev02.png")

    if "dev-03" in d:
        fig, ax = panels(3, "DEV-03 · Azure Maps Weather · Condiciones actuales (HTTPS REST)")
        line(ax[0], r("dev-03", "temp_c", "30min"), "Temperatura", P[0], unit="°C")
        if "sensacion_c" in d["dev-03"]:
            line(ax[0], r("dev-03", "sensacion_c", "30min"), "Sensación térmica", P[3])
        if "dev-09" in d:
            line(ax[0], r("dev-09", "temp_ref_c", "1h"), "Mismo día 2025 (DEV-09)", P[0], ref=True)
        ax[0].set_title("Temperatura: actual vs. sensación térmica vs. mismo día de 2025")
        line(ax[1], r("dev-03", "uv_index", "30min"), "Índice UV", P[3], unit="índice")
        ax[1].axhline(8, color=P[0], linestyle=(0, (2, 2)), linewidth=1, label="UV 8: cierre de polisombra")
        ax[1].set_title("Índice UV (dispara el Lazo 1)")
        line(ax[2], r("dev-03", "hr_pct", "30min"), "Humedad relativa", P[1], unit="%")
        line(ax[2], r("dev-03", "nubosidad_pct", "30min"), "Nubosidad", REF, ref=True)
        ax[2].set_title("Humedad relativa y nubosidad")
        save(fig, "dev03.png")

    if "dev-04" in d:
        fig, ax = panels(2, "DEV-04 · Azure Maps Weather · Pronóstico horario (HTTPS REST)")
        line(ax[0], r("dev-04", "prob_lluvia_pct", "15min"), "Próxima hora", P[1], unit="%")
        line(ax[0], r("dev-04", "prob_lluvia_max_12h", "15min"), "Máximo próximas 12 h", P[1], ref=True)
        ax[0].axhspan(65, 100, color=P[1], alpha=0.07)
        ax[0].set_ylim(0, 100)
        ax[0].set_title("Probabilidad de lluvia (sombreado: > 65 %, riego inhibido)")
        ax[1].bar(d["dev-04"].index, d["dev-04"]["precip_12h_mm"], width=0.008, color=P[1], label="Lluvia esperada 12 h")
        ax[1].set_ylabel("mm"); ax[1].set_title("Precipitación esperada en las siguientes 12 h")
        save(fig, "dev04.png")

    if "dev-05" in d:
        fig, ax = panels(2, "DEV-05 · Gemelo digital de la polisombra motorizada")
        line(ax[0], r("dev-05", "rad_ext_wm2"), "Radiación exterior", P[4], unit="W/m²")
        line(ax[0], r("dev-05", "rad_filtrada_wm2"), "Radiación filtrada", P[2])
        ax[0].set_title("Radiación solar exterior vs. filtrada por la malla")
        line(ax[1], d["dev-05"]["cierre_pct"].resample("10min").last(), "Cierre de la malla", P[3], step=True, unit="%")
        ax[1].set_ylim(0, 100); ax[1].set_title("Cierre de la malla (respuesta al Lazo 1)")
        save(fig, "dev05.png")

    if "dev-06" in d:
        fig, ax = panels(4, "DEV-06 · Gemelo digital de la bomba de goteo y humedad del suelo", h=1.7)
        v2 = d["dev-02"]["valvula"].resample("5min").max() if "dev-02" in d else None
        if v2 is not None:
            shade_on(ax[3], v2, P[1], "Válvula DEV-02 abierta")
        line(ax[3], r("dev-06", "humedad_suelo_pct"), "Humedad del suelo", P[2], unit="%")
        if "umbral_pct" in d["dev-06"]:
            line(ax[3], d["dev-06"]["umbral_pct"].resample("10min").last(), "Umbral de riego", P[0], step=True)
        if "dev-09" in d:
            line(ax[3], r("dev-09", "humedad_suelo_ref_pct", "1h"), "Referencia 2025 (DEV-09)", P[2], ref=True)
        ax[3].set_title("Humedad del suelo y Lazo 2 (riego predictivo con pronóstico de Azure Maps)")
        q = d["dev-06"]["caudal_lpm"].resample("5min").max()
        ax[0].fill_between(q.index, 0, q.values, color=P[1], alpha=0.25, step="post", linewidth=0)
        line(ax[0], q, "Caudal", P[1], step=True, unit="L/min")
        ax[0].set_title("Caudal de riego (pulsos ordenados por el Lazo 2)")
        line(ax[1], d["dev-06"]["presion_psi"].resample("5min").max(), "Presión", P[3], step=True, unit="PSI")
        ax[1].axhline(12, color=P[0], linestyle=(0, (2, 2)), linewidth=1, label="Interlock 12 PSI")
        ax[1].set_title("Presión de línea")
        line(ax[2], d["dev-06"]["consumo_l"].resample("30min").max(), "Consumo acumulado del día", P[2], unit="L")
        ax[2].set_title("Consumo de agua acumulado por día")
        save(fig, "dev06.png")

    if "dev-07" in d:
        fig, ax = panels(2, "DEV-07 · Gemelo digital del cajón de fermentación", h=2.3)
        ax[0].axhspan(45, 50, color=BAND_OK, alpha=0.10, label="Banda óptima 45-50 °C")
        line(ax[0], r("dev-07", "temp_masa_c"), "Masa de cacao", P[0], unit="°C")
        line(ax[0], r("dev-07", "temp_ambiente_c"), "Ambiente bajo techo", P[0], ref=True)
        if len(ev):
            for t in ev[(ev.device == "dev-07") & (ev.kind == "command")].time:
                ax[0].axvline(t, color=P[3], linewidth=1, alpha=0.8)
            ax[0].plot([], [], color=P[3], label="Volteo (retroceso)")
        ax[0].set_title("Temperatura de la masa: fases anaeróbica, acética y maduración")
        line(ax[1], r("dev-07", "ph_mucilago"), "pH del mucílago", P[3], unit="pH")
        ax[1].set_title("pH del mucílago (acidez decreciente con la fermentación)")
        save(fig, "dev07.png")

    if "dev-08" in d:
        fig, ax = panels(3, "DEV-08 · Marquesina de secado solar vs. DEV-10 · Curva ideal (benchmark)", h=1.9)
        line(ax[0], r("dev-08", "humedad_grano_pct"), "Real (DEV-08)", P[4], unit="%")
        if "dev-10" in d:
            line(ax[0], r("dev-10", "humedad_objetivo_pct"), "Ideal sol intenso (DEV-10)", P[4], ref=True)
        ax[0].axhspan(0, 7, color=BAND_OK, alpha=0.10, label="Meta ≤ 7 % (NTC 1252)")
        ax[0].set_ylim(0, 60); ax[0].set_title("Humedad del grano: real vs. curva ideal")
        line(ax[1], r("dev-08", "temp_interna_c"), "Temperatura interna", P[0], unit="°C")
        if "dev-10" in d:
            line(ax[1], r("dev-10", "temp_optima_c"), "Temperatura óptima (DEV-10)", P[0], ref=True)
        ax[1].axhspan(45, max(50, ax[1].get_ylim()[1]), color=BAND_BAD, alpha=0.08)
        ax[1].set_title("Temperatura de secado (sombreado: > 45 °C, Lazo 5 activa extractores)")
        e = d["dev-08"]["extractores"].resample("5min").max()
        c = d["dev-08"]["compuertas"].resample("5min").min()
        ax[2].fill_between(e.index, 1.1, 1.1 + 0.8 * e.values, step="post", color=P[0], alpha=0.8, linewidth=0, label="Extractores ON")
        ax[2].fill_between(c.index, 0, 0.8 * c.values, step="post", color=P[2], alpha=0.8, linewidth=0, label="Compuertas abiertas")
        ax[2].set_yticks([0.4, 1.5], ["Compuertas", "Extractores"]); ax[2].grid(False, axis="y")
        ax[2].set_title("Actuadores comandados por el motor de reglas")
        save(fig, "dev08_10.png")

    if "dev-09" in d:
        fig, ax = panels(2, "DEV-09 · Dataset histórico climático cosecha 2025 (ERA5 · Open-Meteo)")
        line(ax[0], r("dev-09", "temp_ref_c", "1h"), "Temperatura 2025", P[0], unit="°C")
        if "dev-03" in d:
            line(ax[0], r("dev-03", "temp_c", "1h"), "Temperatura 2026 (DEV-03)", P[1])
        ax[0].set_title("Comparación interanual a la misma hora")
        line(ax[1], r("dev-09", "et0_dia_mm", "1h"), "ET0 acumulada 24 h", P[2], unit="mm")
        ax[1].set_title("Evapotranspiración de referencia FAO-56 (demanda hídrica del cultivo)")
        save(fig, "dev09.png")

    # ---------------------------------------------------------- correlación (UV vs cierre / ambiente vs grano)
    if {"dev-03", "dev-05"} <= d.keys():
        h = pd.concat({"uv": d["dev-03"]["uv_index"].resample("1h").mean(),
                       "cierre": d["dev-05"]["cierre_pct"].resample("1h").mean()}, axis=1).dropna()
        fig, ax = plt.subplots(1, 2, figsize=(10, 3.4), constrained_layout=True)
        ax[0].scatter(h.uv, h.cierre, s=22, color=P[3], alpha=0.7, edgecolor="white", linewidth=0.6)
        ax[0].set_xlabel("Índice UV (DEV-03, Azure)"); ax[0].set_ylabel("Cierre de malla % (DEV-05)")
        ax[0].set_title("Lazo 1: UV vs. cierre de la polisombra (por hora)")
        keys = [("dev-03", "temp_c", "T ext"), ("dev-03", "hr_pct", "HR ext"), ("dev-03", "uv_index", "UV"),
                ("dev-06", "humedad_suelo_pct", "Suelo"), ("dev-05", "rad_filtrada_wm2", "Rad filt"),
                ("dev-08", "temp_interna_c", "T marq"), ("dev-07", "temp_masa_c", "T masa"), ("dev-09", "temp_ref_c", "T 2025")]
        m = pd.concat({k[2]: d[k[0]][k[1]].resample("1h").mean() for k in keys if k[0] in d}, axis=1).corr()
        cmap = matplotlib.colors.LinearSegmentedColormap.from_list("div", ["#2E7FC0", "#F2F0EE", "#D9622B"])
        im = ax[1].imshow(m.values, cmap=cmap, vmin=-1, vmax=1)
        ax[1].set_xticks(range(len(m)), m.columns, rotation=45, ha="right"); ax[1].set_yticks(range(len(m)), m.index)
        ax[1].grid(False)
        for i in range(len(m)):
            for j in range(len(m)):
                ax[1].text(j, i, f"{m.values[i, j]:.2f}", ha="center", va="center", fontsize=6.5, color=INK)
        ax[1].set_title("Correlación de Pearson (series horarias)")
        fig.colorbar(im, ax=ax[1], shrink=0.8)
        fig.savefig(FIG / "correlaciones.png", bbox_inches="tight"); plt.close(fig)
        corr = {"uv_vs_cierre": round(float(h.corr().iloc[0, 1]), 3), "matriz": m.round(3).to_dict()}
    else:
        corr = {}

    # ---------------------------------------------------------- línea de tiempo de eventos (retroceso + alertas)
    if len(ev):
        fig, ax = plt.subplots(figsize=(10, 3.2), constrained_layout=True)
        devs = sorted(ev.device.unique())
        for i, dv in enumerate(devs):
            e = ev[ev.device == dv]
            cm, al = e[e.kind == "command"], e[e.kind == "alert"]
            ax.scatter(cm.time, [i] * len(cm), marker="|", s=160, color=P[1], linewidths=1.6, label="Comando de retroceso" if i == 0 else None)
            ax.scatter(al.time, [i + 0.25] * len(al), marker="v", s=28, color=P[0], label="Alerta" if i == 0 else None)
        ax.set_yticks(range(len(devs)), [x.upper() for x in devs]); ax.set_ylim(-0.6, len(devs) - 0.2)
        ax.set_title("Bitácora del motor de reglas: comandos de retroceso y alertas por dispositivo")
        fmt_axis(ax); ax.legend(loc="upper left", ncol=2, bbox_to_anchor=(0, -0.12))
        fig.savefig(FIG / "eventos.png", bbox_inches="tight"); plt.close(fig)
    return corr


def statistics(d, ev):
    out = {"periodo": {}, "dispositivos": {}, "diario": {}, "eventos": {}}
    starts = [df.index.min() for df in d.values()]; ends = [df.index.max() for df in d.values()]
    out["periodo"] = {"inicio": str(min(starts)), "fin": str(max(ends)),
                      "dias": round((max(ends) - min(starts)).total_seconds() / 86400, 2)}
    for dev, vars_ in VARS.items():
        if dev not in d:
            continue
        df = d[dev]
        out["dispositivos"][dev] = {"nombre": NAMES[dev], "muestras": int(len(df)), "variables": {}}
        for c, (lab, unit) in vars_.items():
            if c not in df:
                continue
            s = df[c].dropna()
            out["dispositivos"][dev]["variables"][c] = {
                "etiqueta": lab, "unidad": unit, "promedio": round(float(s.mean()), 2), "max": round(float(s.max()), 2),
                "min": round(float(s.min()), 2), "desv": round(float(s.std()), 2),
                "t_max": str(s.idxmax()), "t_min": str(s.idxmin())}
        daily = df[[c for c in vars_ if c in df]].resample("1D").agg(["mean", "max", "min"]).round(2)
        out["diario"][dev] = {str(k.date()): {f"{a}_{b}": v for (a, b), v in row.items()} for k, row in daily.iterrows()}
    if len(ev):
        out["eventos"] = {"comandos": int((ev.kind == "command").sum()), "alertas": int((ev.kind == "alert").sum()),
                          "por_tipo": ev.groupby(["kind", "name"]).size().rename("n").reset_index().to_dict("records")}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "analysis" / "data" / "simulacion"))
    args = ap.parse_args()
    folder = Path(args.data)
    d, ev = load(folder)
    corr = figures(d, ev)
    st = statistics(d, ev)
    st["correlaciones"] = corr
    st["fuente"] = folder.name
    BUILD.mkdir(parents=True, exist_ok=True)
    (BUILD / "stats.json").write_text(json.dumps(st, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"{len(list(FIG.glob('*.png')))} figuras en {FIG} · estadísticos en {BUILD / 'stats.json'} · periodo {st['periodo']}")


if __name__ == "__main__":
    main()
