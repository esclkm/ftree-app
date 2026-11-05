#!/usr/bin/env python3
"""Прочитать папку сканов Manuscript-OCR целыми разворотами — для дел без бланка (ревизские сказки, описи), где
metric_filter.py с его колонками метрик не подходит. Один разворот — один .txt: строки «y<TAB>x<TAB>текст» сверху вниз.
Прочитанное не трогает (продолжает с места). Токенов ноль: работает на Mac, воркер — metric_ocr_worker.py.

  tools/py tools/scripts/ocr_folder.py ф10_оп5_д1241 ф10_оп5_д1242      # дела из ГАСО: raw/gaso/<дело> → text/gaso/<дело>
  tools/py tools/scripts/ocr_folder.py --src <папка> --out <папка>        # любая папка
  tools/py tools/scripts/ocr_folder.py ф10_оп5_д1242 --top 0.22           # только шапки: какая деревня на развороте
  tools/py tools/scripts/ocr_folder.py ф10_оп5_д1242 --only 70-80         # только эти развороты
  tools/py tools/scripts/ocr_folder.py фР3315_оп2_д396 --strips 4          # бланки ЗАГС: каждая страница — 4 полосы,
                                                                          # ×2 и контраст; текст — в <дело>_полосы
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402
from paths import ARCHIVES_TEXT, GASO_RAW, ROOT  # noqa: E402

VENV_PY = paths.CACHE / "venv-manuscript" / "bin" / "python"
WORKER = Path(__file__).resolve().parent / "metric_ocr_worker.py"


def ask(worker, job: dict) -> dict:
    worker.stdin.write(json.dumps(job) + "\n")
    worker.stdin.flush()
    return json.loads(worker.stdout.readline())


def read_strips(worker, img: Path, n: int, tmp: Path) -> tuple[list, list]:
    """Бланк ЗАГС: каждая страница — n полос с нахлёстом, ×2, автоконтраст. Целиком колонки путаются, а мелкий почерк
    теряется; на пробе 29.10.2026 «Андрей Прокопович» стал «Андрей Прокоповал». Координаты — в масштабе разворота."""
    page = Image.open(img).convert("L")
    w, h = page.size
    lines, errors = [], []
    for x0, x1 in ((0, w // 2 + w // 50), (w // 2 - w // 50, w)):
        for i in range(n):
            y0, y1 = max(0, h * i // n - h // 40), min(h, h * (i + 1) // n + h // 40)
            crop = ImageOps.autocontrast(page.crop((x0, y0, x1, y1)), cutoff=1)
            crop = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
            path = tmp / "strip.jpg"
            crop.save(path, quality=95)
            r = ask(worker, {"id": img.name, "image": str(path), "box": [0, 0, crop.width, crop.height]})
            lines += [{**l, "y": y0 + l["y"] / 2, "x": x0 + l["x"] / 2} for l in sorted(r["lines"], key=lambda l: (l["y"], l["x"]))]
            if r["error"]:
                errors.append(r["error"])
    return lines, errors


def read_folder(worker, folder: Path, out: Path, top: float = 1.0, only=None, strips: int = 0) -> int:
    out.mkdir(parents=True, exist_ok=True)
    done = 0
    for img in sorted(folder.glob("*.jpg")):
        if only and int(img.stem.rsplit("_", 1)[-1]) not in only:
            continue
        dst = out / (img.stem + ".txt")
        if dst.exists():
            continue
        if strips:
            with tempfile.TemporaryDirectory() as tmp:
                lines, errors = read_strips(worker, img, strips, Path(tmp))
        else:
            w, h = Image.open(img).size
            r = ask(worker, {"id": img.name, "image": str(img), "box": [0, 0, w, int(h * top)]})
            lines, errors = sorted(r["lines"], key=lambda l: (l["y"], l["x"])), [r["error"]] if r["error"] else []
        text = "\n".join(f"{l['y']:.0f}\t{l['x']:.0f}\t{l['text']}" for l in lines)
        dst.write_text(text + "".join("\nERROR " + e for e in errors), encoding="utf-8")
        done += 1
        print(img.name, len(lines), flush=True)
    return done


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("delo", nargs="*", help="папки дел в raw/gaso (ф10_оп5_д1241)")
    ap.add_argument("--src", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--top", type=float, default=1.0,
                    help="читать только верхнюю долю разворота (шапка сказки с деревней: 0.22); "
                         "текст тогда идёт в папку <дело>_шапки, а не к полному")
    ap.add_argument("--only", help="номера разворотов: 70-80,95")
    ap.add_argument("--strips", type=int, default=0,
                    help="бланки ЗАГС: резать каждую страницу на N полос, ×2 с контрастом; текст — в <дело>_полосы")
    a = ap.parse_args()
    suffix = "_шапки" if a.top < 1 else "_полосы" if a.strips else ""
    jobs = [(GASO_RAW / d, ARCHIVES_TEXT / "gaso" / (d + suffix)) for d in a.delo]
    only = None
    if a.only:
        only = set()
        for part in filter(None, a.only.split(",")):
            lo, _, hi = part.partition("-")
            only.update(range(int(lo), int(hi or lo) + 1))
    if a.src:
        jobs.append((a.src, a.out or ARCHIVES_TEXT / a.src.name))
    if not jobs:
        ap.error("нужно дело или --src")
    worker = subprocess.Popen([str(VENV_PY), str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert json.loads(worker.stdout.readline()).get("ready")
    for src, out in jobs:
        n = read_folder(worker, src, out, a.top, only, a.strips)
        print(f"== {src.name}: прочитано новых {n}, всего {len(list(out.glob('*.txt')))}", flush=True)
    worker.stdin.close()
    worker.wait()
    return 0


if __name__ == "__main__":
    sys.exit(main())
