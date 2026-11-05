#!/usr/bin/env python3
"""Рабочий процесс Manuscript-OCR для metric_filter.py. Запускается Python-ом из tools/.cache/venv-manuscript
(своё окружение, в проектном .venv этих библиотек нет); сам ничего не решает.

Читает со стандартного входа по строке JSON: {"id": ..., "image": путь, "box": [x0, y0, x1, y1]};
отвечает строкой JSON: {"id": ..., "lines": [{"y": .., "x": .., "text": .., "conf": ..}], "error": null | "…"}.
Координаты строк — в картинке целиком (y — середина строки, x — левый край). Модель грузится один раз.
"""
import json
import sys
from pathlib import Path

# Папка скриптов проекта стоит первой в sys.path, а в ней coverage.py (сводка документов) — numba внутри manuscript
# брала его вместо библиотеки coverage и падала (20.10.2026). Чужое окружение скрипты проекта видеть не должно.
sys.path = [p for p in sys.path if Path(p or ".").resolve() != Path(__file__).resolve().parent]

from PIL import Image  # noqa: E402


def main() -> int:
    real, sys.stdout = sys.stdout, sys.stderr          # библиотека печатает в stdout — а там у нас протокол
    from manuscript import Pipeline
    pipe = Pipeline()
    print(json.dumps({"ready": True}), file=real, flush=True)
    for raw in sys.stdin:
        if not raw.strip():
            continue
        job = json.loads(raw)
        out = {"id": job["id"], "lines": [], "error": None}
        try:
            x0, y0, x1, y1 = job["box"]
            crop = Image.open(job["image"]).convert("RGB").crop((x0, y0, x1, y1))
            page = pipe.predict(crop)["page"]
            for block in page.blocks:
                for line in block.lines:
                    words = [w for w in line.words if w.text]
                    if not words:
                        continue
                    ys = [float(p[1]) for w in words for p in w.polygon]
                    xs = [float(p[0]) for w in words for p in w.polygon]
                    conf = [float(w.recognition_confidence or 0) for w in words]
                    out["lines"].append({"y": round(y0 + sum(ys) / len(ys), 1), "x": round(x0 + min(xs), 1),
                                         "text": " ".join(w.text for w in words),
                                         "conf": round(sum(conf) / len(conf), 3)})
        except Exception as e:  # noqa: BLE001 — одна клетка не должна ронять остальные
            out["error"] = f"{type(e).__name__}: {e}"
        print(json.dumps(out, ensure_ascii=False), file=real, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
