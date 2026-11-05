#!/usr/bin/env python3
"""Разметка печатного бланка метрики: колонки и строки записей — без ИИ (схема — документ дерева проект/МЕТРИКИ_СХЕМА.md).

Зачем: распознавателю легче прочесть одну клетку «родители» записи № 9, чем весь разворот. Бланк печатный:
линии разлиновки и шапка колонок напечатаны, их находим сами — линии по тёмным пикселям (numpy), подписи колонок —
по словам шапки, которые прочёл macOS Vision (с рамками). Паспорт граф — 3_research/archives/book_types.md.

    tools/py tools/scripts/form_layout.py show <скан.jpg> [--section births|marriages|deaths] [--out картинка.png]

`show` рисует найденное поверх скана: красные — границы колонок, синие — линии строк, жёлтые рамки — слова шапки,
подписи — поле паспорта. Картинку смотрит человек: верно ли нарезано.
"""
import argparse
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import paths  # noqa: E402
from paths import ROOT

VISION_SRC = paths.SCRIPTS / "gaso_vision.swift"
VISION_BIN = paths.CACHE / "etalon" / "vision"

# слова шапки → поля паспорта по порядку: первое «Звание…» в браках — жених, второе — невеста; «Лета» так же.
# Vision читает печатную вязь с ошибками («dtrà» = «Лета», «совершіль»), поэтому корни короткие.
COLUMN_WORDS = {
    "births": [(r"счет|мужеск|женск", ["act"]), (r"мес|д[еи]нь", ["born", "baptized"]), (r"имена", ["child"]),
               (r"родител", ["parents"]), (r"восприем|воспри", ["godparents"]),
               (r"соверш|совер|соввош|таи?н+с", ["priest"]), (r"рувоприв|приклад|подпис|свид", ["signatures"])],
    "marriages": [(r"счет|враков", ["act"]), (r"мес|д[еи]нь", ["date"]), (r"звани|тчест|фамил", ["groom", "bride"]),
                  (r"лета|dtra|лвта|ltra|atra|ета\b", ["groom_age", "bride_age"]),
                  (r"соверш|совер|таи?н+с", ["priest"]), (r"поруч|порвч", ["sureties"]),
                  (r"подпис|подан|свид", ["signatures"])],
    "deaths": [(r"счет", ["act"]), (r"мес|д[еи]нь|смерт|спер", ["died", "buried"]),
               (r"звани|звин|тчест|фамил|умерш", ["deceased"]),
               (r"лета|dtra|dit|лвта|ltra|atra|ета\b", ["age"]), (r"чег", ["cause"]),
               (r"испов|сповед|неповед|приобщ", ["priest"]),
               (r"собер|совер|где|гд[бв]\b|губ\b|сдб", ["burial_place"])]   # «Кто совершал погребение и где погребены»; «погребения» есть и в дате,
}


def normalize(text: str) -> str:
    text = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
                   or ch in "\u0306\u0308")      # ударения Vision — вон; «й», «ё» — оставить
    text = unicodedata.normalize("NFC", text).lower().translate(str.maketrans("aceopxyмtkbnhз", "асеорхумтквпнз"))   # латиница-двойники Vision
    for a, b in (("є", "е"), ("ѣ", "е"), ("і", "и"), ("ї", "и"), ("й", "и"), ("ё", "е"), ("ъ", ""), ("ь", ""),
                 ("б", "в"), ("к", "в")):      # Vision путает «в» с «б» и «к» в печатной вязи
        text = text.replace(a, b)
    return text


def vision(image: Path) -> list[dict]:
    if not VISION_BIN.exists():
        VISION_BIN.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["swiftc", "-O", "-o", str(VISION_BIN), str(VISION_SRC)], check=True)
    run = subprocess.run([str(VISION_BIN), str(image)], capture_output=True, text=True, check=True)
    return json.loads(run.stdout)["lines"]


def dark_mask(gray: np.ndarray) -> np.ndarray:
    """Тёмное относительно окрестности: чернила и типографские линии; водяной знак и фон — нет."""
    img = Image.fromarray(gray)
    local = np.asarray(img.filter(ImageFilter.BoxBlur(25)), dtype=np.int16)
    return (gray.astype(np.int16) < local - 18)


def runs(mask: np.ndarray, length: int, axis: int) -> np.ndarray:
    """Пиксели, лежащие на сплошном отрезке не короче length вдоль оси (0 — вертикаль, 1 — горизонталь).
    Разрешаем 10 % пропусков: линия бланка рвётся на сгибах и под водяным знаком."""
    m = mask.astype(np.int32)
    if axis == 1:
        m = m.T
    pad = np.zeros((1, m.shape[1]), np.int32)
    c = np.cumsum(np.vstack([pad, m]), axis=0)
    window = c[length:] - c[:-length]
    hit = window >= 0.9 * length
    out = np.zeros_like(m, bool)
    for shift in range(0, length, max(1, length // 8)):     # растянуть попадание на всё окно, с шагом
        out[shift:shift + hit.shape[0]] |= hit
    return out.T if axis == 1 else out


def peaks(profile: np.ndarray, min_value: float, min_gap: int) -> list[int]:
    """Положения максимумов профиля выше порога, не ближе min_gap друг к другу."""
    order = np.argsort(profile)[::-1]
    chosen: list[int] = []
    for i in order:
        if profile[i] < min_value:
            break
        if all(abs(i - j) >= min_gap for j in chosen):
            chosen.append(int(i))
    return sorted(chosen)


def lines(gray: np.ndarray, strict: float = 0.25) -> tuple[list[int], list[int]]:
    """Вертикальные и горизонтальные линии бланка. strict — какая доля высоты столбца должна лежать на длинных
    отрезках; шаблон книги (form_template) берёт мягче — случайные линии отсеет голосование страниц."""
    h, w = gray.shape
    mask = dark_mask(gray)
    # чуть размыть поперёк линии — бланк на скане бывает слегка наклонён
    wide_v = mask | np.roll(mask, 1, 1) | np.roll(mask, -1, 1) | np.roll(mask, 2, 1)
    wide_h = mask | np.roll(mask, 1, 0) | np.roll(mask, -1, 0) | np.roll(mask, 2, 0)
    v = runs(wide_v, h // 12, 0).sum(axis=0)        # сколько пикселей столбца лежит на длинной вертикали
    hz = runs(wide_h, w // 10, 1).sum(axis=1)
    return peaks(v, h * strict, w // 90), peaks(hz, w * 0.12, h // 120)


TITLE = r"метрич|етрич|книги|кнпги|часть|чисть|годъ|года|годк|родивш|брак[ао]соч|умерш|омерш"
HEAD_KEYS = r"звани|имя|има|счет|меся|лета|кто|поруч|подпис|восприем|родител|чего|погреб"


def header_words(ocr: list[dict], height: int, width: int) -> list[dict]:
    """Слова верхней части разворота в пикселях (верх картинки — 0)."""
    out = []
    for x in ocr:
        top = (1 - x["y"] - x["h"]) * height
        if top < height * 0.4:
            out.append({"text": x["text"], "x0": x["x"] * width, "x1": (x["x"] + x["w"]) * width,
                        "y0": top, "y1": (1 - x["y"]) * height})
    return out


def label_columns(verticals: list[int], words: list[dict], section: str) -> list[dict]:
    """Подпись колонки — правило, совпавшее со словами её шапки чаще всех (слова многих страниц — голосование).
    Поля правила раздаются по порядку: первое «Звание…» в браках — жених, второе — невеста; последнее повторяется."""
    rules = COLUMN_WORDS.get(section, [])
    left_over = {rx: list(fields) for rx, fields in rules}
    cols = []
    for left, right in zip(verticals, verticals[1:]):
        inside = [wd for wd in words if left - 5 <= (wd["x0"] + wd["x1"]) / 2 <= right + 5
                  and wd["x1"] - wd["x0"] <= (right - left) * 1.3]
        text = " ".join(wd["text"] for wd in sorted(inside, key=lambda d: (round(d["y0"] / 15), d["x0"])))
        norm, field = normalize(text), None
        hits = {rx: len(re.findall(normalize(rx), norm)) for rx, _ in rules}
        best = max(hits, key=hits.get, default=None)
        if best and hits[best]:
            fields = left_over[best]
            field = fields.pop(0) if len(fields) > 1 else fields[0]
        cols.append({"x0": left, "x1": right, "header": text[:80], "field": field})
    return cols


def record_starts(ink: np.ndarray, x0: int, x1: int, top: int, min_gap: int) -> list[int]:
    """Начала записей: где в колонках «Счёт» и «Месяц и день» появляются чернила после пустоты."""
    band = ink[top:, x0:x1].sum(axis=1) > 3
    starts, empty = [], min_gap
    for i, on in enumerate(band):
        if on and empty >= min_gap:
            starts.append(top + i)
        empty = 0 if on else empty + 1
    return starts


def analyse(image: Path, section: str) -> dict:
    gray = np.asarray(Image.open(image).convert("L"))
    h, w = gray.shape
    verticals, horizontals = lines(gray)
    allwords = header_words(vision(image), h, w)
    keyed = [wd for wd in allwords if re.search(normalize(HEAD_KEYS), normalize(wd["text"]))
             and not re.search(normalize(TITLE), normalize(wd["text"]))]
    head_low = max((wd["y1"] for wd in keyed), default=h * 0.2)
    head_high = min((wd["y0"] for wd in keyed), default=h * 0.1)
    header_bottom = min((y for y in horizontals if y >= head_low - 5), default=head_low + 5)
    words = [wd for wd in allwords if head_high - 10 <= wd["y0"] and wd["y1"] <= header_bottom + 5
             and not re.search(normalize(TITLE), normalize(wd["text"]))]
    columns = label_columns(verticals, words, section)
    # чернила без линий бланка
    mask = dark_mask(gray)
    for x in verticals:
        mask[:, max(0, x - 4):x + 5] = False
    for y in horizontals:
        mask[max(0, y - 4):y + 5, :] = False
    first = next((i for i, c in enumerate(columns) if c["field"] == "act"), 0)
    lead = columns[first:first + 2] or columns[:2]
    rows = record_starts(mask, lead[0]["x0"] + 6, lead[-1]["x1"] - 6, header_bottom + 8, h // 40) if lead else []
    return {"image": str(image), "size": [w, h], "verticals": verticals, "horizontals": horizontals,
            "header_bottom": round(header_bottom), "rows": rows, "columns": columns, "header_words": words}


def show(args) -> int:
    image = Path(args.image).expanduser()
    lay = analyse(image, args.section)
    img = Image.open(image).convert("RGB")
    draw = ImageDraw.Draw(img)
    w, h = lay["size"]
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 22)
    except OSError:
        font = ImageFont.load_default()
    for wd in lay["header_words"]:
        draw.rectangle([wd["x0"], wd["y0"], wd["x1"], wd["y1"]], outline=(230, 180, 0), width=2)
    for x in lay["verticals"]:
        draw.line([(x, 0), (x, h)], fill=(220, 0, 0), width=3)
    for y in lay["horizontals"]:
        draw.line([(0, y), (w, y)], fill=(150, 150, 255), width=2)
    for y in lay["rows"]:
        draw.line([(0, y - 6), (w, y - 6)], fill=(0, 60, 230), width=4)
    draw.line([(0, lay["header_bottom"]), (w, lay["header_bottom"])], fill=(0, 160, 0), width=2)
    for c in lay["columns"]:
        if c["field"]:
            draw.text((c["x0"] + 4, lay["header_bottom"] + 4), c["field"], fill=(200, 0, 120), font=font)
    out = Path(args.out) if args.out else image.with_suffix(".layout.png")
    img.save(out)
    summary = {k: lay[k] for k in ("size", "verticals", "horizontals", "header_bottom", "rows")}
    print(json.dumps(summary, ensure_ascii=False))
    for c in lay["columns"]:
        print(f"  {c['x0']:5}–{c['x1']:<5} {c['field'] or '—':15} {c['header']}")
    print(f"картинка: {out}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("show")
    s.add_argument("image")
    s.add_argument("--section", default="births", choices=list(COLUMN_WORDS))
    s.add_argument("--out")
    s.set_defaults(func=show)
    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
