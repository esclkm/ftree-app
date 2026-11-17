#!/usr/bin/env python3
"""Книги ЗАГС 1918–1926 (ГАСО, ф. Р-3315): вырезать из каждого разворота только поля с людьми и сложить по нескольку
актов на одну картинку — модель читает меньше и дешевле.

Зачем. Акт ЗАГС — печатный бланк: слева от граф напечатаны подписи «№ записи», «Число и месяц…», «Фамилия и имя»,
«Возраст…», «Постоянное местожительство», «Род занятий». Vision читает печатные подписи надёжно, а рукопись — нет.
По подписям на каждом развороте находим, где лежат графы с именами (скан лежит не всегда одинаково), и вырезаем
только полосу от «ЗАПИСЬ» до «Род занятий» правее подписей. Это ≈15 % разворота. Вырезки складываем столбиком по
`--per` штук и подписываем номером файла — одна картинка на модель вместо нескольких разворотов.

    tools/py tools/scripts/zags_crops.py tiles <папка дела> [--per 6]        # → <папка>/tiles/tile_NNN.jpg + tiles.json
    tools/py tools/scripts/zags_crops.py read  <папка дела> [--model copilot:claude-sonnet-5.5]   # → <папка>/tiles/read.jsonl
    tools/py tools/scripts/zags_crops.py find  <папка дела> Лесовск Заречь

Нужен `vision.jsonl` в папке дела (`rodo velikie ocr <папка>`). Разворот без подписей бланка (обложка, опись,
пустой лист) пропускается и попадает в список `skipped` в tiles.json.
"""
import argparse
import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFile, ImageFont

ImageFile.LOAD_TRUNCATED_IMAGES = True  # снимок, у которого оборван хвост, всё равно годится для вырезки

sys.path.insert(0, str(Path(__file__).resolve().parent))

TOP = re.compile(r"ЗАПИСЬ|записи\.")
BOTTOM = re.compile(r"Род занят")
NAME = re.compile(r"(?i)фамилия и|фамилия, имя и отч")  # 1925: «Фамилия, имя и отчество умершего»
TABLE = re.compile(r"Имя, фамил\w+ и род")
DOCTOR = re.compile(r"Фамилия, имя и место")
WIDTH = 1400  # ширина вырезки на плитке, пикселей


def boxes(folder: Path) -> tuple[list[tuple[str, tuple[float, float, float, float]]], list[str]]:
    """Для каждого разворота — рамка полей с людьми в долях картинки (x0, y0, x1, y1; y сверху вниз)."""
    out, skipped = [], []
    for line in (folder / "vision.jsonl").read_text().splitlines():
        r = json.loads(line)
        name = Path(r["image"]).name
        lab = {k: [x for x in r["lines"] if rx.search(x["text"])] for k, rx in
               (("top", TOP), ("bottom", BOTTOM), ("name", NAME))}
        if not (lab["top"] and lab["bottom"] and lab["name"]):
            # книга-таблица (смерти 1921): несколько умерших строками; графы с людьми — левая полоса до
            # «Фамилия, имя и местожительство врача», под шапкой и до низа
            tab = [x for x in r["lines"] if TABLE.search(x["text"])]
            doc = [x for x in r["lines"] if DOCTOR.search(x["text"])]
            if tab:
                head = max(1 - x["y"] for x in tab) + 0.06
                x1 = (min(x["x"] for x in doc) - 0.005) if doc else 0.38
                out.append((name, (0.0, head, x1, 1.0)))
                continue
            skipped.append(name)
            continue
        # Vision: y — от низа картинки; переводим в «сверху»
        top = min(1 - x["y"] - x["h"] for x in lab["top"])
        bottom = max(1 - x["y"] for x in lab["bottom"])
        nm = lab["name"][0]
        x0 = max(0.0, nm["x"] - 0.01)          # с самой подписью «Фамилия и имя» — модели видно, где какая графа
        box = (x0, max(0.0, top - 0.01), 1.0, min(1.0, bottom + 0.01))
        if box[3] - box[1] < 0.2 or box[2] - box[0] < 0.1:  # подписи перепутались (чужая страница, вклейка)
            skipped.append(name)
            continue
        out.append((name, box))
    # подписи не прочитались (бледный разворот) — берём среднюю рамку книги: бланк один и тот же
    if out and skipped:
        med = tuple(sorted(b[i] for _, b in out)[len(out) // 2] for i in range(4))
        order = {n: i for i, n in enumerate(sorted([n for n, _ in out] + skipped))}
        out = sorted(out + [(n, med) for n in skipped], key=lambda x: order[x[0]])
    return out, skipped


def crops(folder: Path) -> None:
    """Каждый акт — своя вырезка (для Manuscript-OCR на Mac: токенов ноль) → <папка>/crops/<файл>.jpg."""
    cdir = folder / "crops"
    cdir.mkdir(exist_ok=True)
    items, skipped = boxes(folder)
    for name, (x0, y0, x1, y1) in items:
        out = cdir / name
        if out.exists():
            continue
        im = Image.open(folder / name).convert("L")
        W, H = im.size
        im.crop((int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H))).save(out, quality=90)
    print(f"вырезок: {len(items)} (рамка по средней: {len(skipped)}) → {cdir}")


def tiles(folder: Path, per: int) -> None:
    tdir = folder / "tiles"
    tdir.mkdir(exist_ok=True)
    items, skipped = boxes(folder)
    font = ImageFont.load_default(size=36)
    index = []
    for t in range(0, len(items), per):
        crops = []
        for name, (x0, y0, x1, y1) in items[t:t + per]:
            im = Image.open(folder / name).convert("L")
            W, H = im.size
            c = im.crop((int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H)))
            c = c.resize((WIDTH, int(c.height * WIDTH / c.width)))
            crops.append((name, c))
        hdr = 50
        tile = Image.new("L", (WIDTH, sum(c.height + hdr for _, c in crops)), 255)
        d = ImageDraw.Draw(tile)
        y = 0
        for name, c in crops:
            num = re.search(r"(\d+)\.jpe?g$", name, re.I)
            d.text((10, y + 5), f"ФАЙЛ {num.group(1) if num else name}", fill=0, font=font)
            tile.paste(c, (0, y + hdr))
            y += c.height + hdr
        out = tdir / f"tile_{t // per + 1:03d}.jpg"
        tile.save(out, quality=85)
        index.append({"tile": out.name, "files": [n for n, _ in crops]})
    (tdir / "tiles.json").write_text(json.dumps({"per": per, "tiles": index, "skipped": skipped},
                                                ensure_ascii=False, indent=1))
    print(f"разворотов: {len(items)}, из них рамка по средней (подписи не прочитались): {len(skipped)}, плиток: {len(index)} → {tdir}")


PROMPT = """На картинке столбиком {n} вырезок из книги ЗАГС 1920-х годов (Смоленский уезд). Над каждой вырезкой — «ФАЙЛ NNN».
В вырезке — левая колонка с печатными подписями граф (№ записи, число и месяц, фамилия и имя, возраст, постоянное
местожительство) и правее — рукописные записи (в акте о браке две колонки: жених и невеста; в акте о смерти — одна).
Перепиши рукопись как написано, ничего не исправляя и не додумывая. Неясные буквы — [?].
Ответ — только JSON-массив, по объекту на вырезку:
[{{"file": "NNN", "no": "...", "date": "...", "persons": [{{"role": "жених|невеста|умерший|ребёнок|отец|мать",
"name": "фамилия имя отчество как написано", "age_or_birth": "...", "residence": "..."}}]}}]"""


def read(folder: Path, model: str) -> None:
    import llm
    tdir = folder / "tiles"
    idx = json.loads((tdir / "tiles.json").read_text())
    done_path = tdir / "read.jsonl"
    done = {json.loads(l)["tile"] for l in done_path.read_text().splitlines()} if done_path.exists() else set()
    for t in idx["tiles"]:
        if t["tile"] in done:
            continue
        ans = llm.ask("zags_crops", PROMPT.format(n=len(t["files"])), "Ты переписываешь архивные рукописи.",
                      model=model, image=tdir / t["tile"])
        with done_path.open("a") as f:
            f.write(json.dumps({"tile": t["tile"], "files": t["files"], "model": model, "answer": ans},
                               ensure_ascii=False) + "\n")
        print(t["tile"], "ok")


def find(folder: Path, terms: list[str]) -> None:
    rx = re.compile("|".join(terms), re.I)
    for line in (folder / "tiles" / "read.jsonl").read_text().splitlines():
        r = json.loads(line)
        for row in re.findall(r"\{[^{}]*\"file\"[^\[]*\[[^\]]*\][^{}]*\}", r["answer"]) or [r["answer"]]:
            if rx.search(row):
                print(r["tile"], re.sub(r"\s+", " ", row)[:400])


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("crops").add_argument("folder", type=Path)
    a = sub.add_parser("tiles"); a.add_argument("folder", type=Path); a.add_argument("--per", type=int, default=6)
    b = sub.add_parser("read"); b.add_argument("folder", type=Path)
    b.add_argument("--model", default="copilot:claude-sonnet-5.5")
    c = sub.add_parser("find"); c.add_argument("folder", type=Path); c.add_argument("terms", nargs="+")
    a_ = p.parse_args()
    if a_.cmd == "crops":
        crops(a_.folder)
    elif a_.cmd == "tiles":
        tiles(a_.folder, a_.per)
    elif a_.cmd == "read":
        read(a_.folder, a_.model)
    else:
        find(a_.folder, a_.terms)
    return 0


if __name__ == "__main__":
    sys.exit(main())
