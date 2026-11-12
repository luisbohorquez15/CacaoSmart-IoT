"""
Análisis de gráficas y comportamiento con IA (Claude, modelo multimodal).

Envía a Claude los estadísticos del periodo (docs/build/stats.json) y las GRÁFICAS generadas
(docs/figuras/*.png, como imágenes) y obtiene un informe técnico en español que describe el
comportamiento de cada dispositivo, correlaciones, efectos del retroceso y recomendaciones.

    pip install anthropic
    set ANTHROPIC_API_KEY=...            (o `ant auth login`)
    python analysis/ai_analyst.py        -> docs/analisis_ia.md
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import anthropic

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "docs" / "figuras"
OUT = ROOT / "docs" / "analisis_ia.md"

SYSTEM = """Eres un ingeniero agrónomo y de IoT que redacta la sección "Análisis de gráficas y comportamiento"
de un informe universitario sobre CacaoSmart IoT: monitoreo de un cultivo y beneficio de cacao en San Vicente de
Chucurí (Santander, Colombia) con 10 dispositivos (2 ESP32 reales, 2 APIs de Azure Maps, 4 gemelos digitales y
2 datasets) y un motor de reglas que ejecuta acciones de retroceso.

Redacta en español, en Markdown, con un subtítulo (###) por dispositivo o grupo de dispositivos y una sección final
de hallazgos transversales y recomendaciones. Para cada gráfica describe: tendencia y ciclo diario, valores
promedio/máximo/mínimo con unidades y la hora en que ocurrieron, eventos atípicos, y qué acciones de retroceso
se observan y su efecto. Usa únicamente cifras presentes en los estadísticos o legibles en las gráficas; si algo
no se puede afirmar con los datos, dilo. Sé concreto y técnico; entre 900 y 1400 palabras."""


def main() -> None:
    stats = json.loads((ROOT / "docs" / "build" / "stats.json").read_text(encoding="utf-8"))
    content: list[dict] = []
    for png in sorted(FIG.glob("*.png")):
        content.append({"type": "text", "text": f"Figura: {png.name}"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                    "data": base64.b64encode(png.read_bytes()).decode()}})
    content.append({"type": "text", "text": "Estadísticos del periodo (JSON):\n" + json.dumps(stats, ensure_ascii=False)})
    content.append({"type": "text", "text": "Redacta ahora la sección de análisis."})

    client = anthropic.Anthropic()
    with client.beta.messages.stream(
        model="claude-opus-5-5",
        max_tokens=64000,
        system=SYSTEM,
        output_config={"effort": "high"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",                     # si el modelo declina, el servidor reintenta con un modelo de respaldo
        messages=[{"role": "user", "content": content}],
    ) as stream:
        msg = stream.get_final_message()

    if msg.stop_reason == "refusal":
        raise SystemExit("El modelo declinó la solicitud; revise el contenido enviado.")
    text = "".join(b.text for b in msg.content if b.type == "text")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"análisis escrito en {OUT} ({len(text.split())} palabras, modelo {msg.model})")


if __name__ == "__main__":
    main()
