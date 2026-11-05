#!/usr/bin/env python3
"""Шаблон бланка для книги: одна книга — свой шаблон на каждую часть (рождения, браки, смерти). Без ИИ.

Зачем: на одной странице линии колонок находятся не все, а шапку macOS Vision читает с ошибками — разметка по одной
странице ненадёжна (проба 02.10: верно 1 из 17). Но в одной книге бланк напечатан одинаково. Поэтому:
  1) берём ~80 разворотов книги, по печатной шапке делим на части (etalon.classify);
  2) на каждом находим вертикальные линии (form_layout.lines);
  3) подгоняем страницы друг к другу — сдвиг и масштаб (скан лежит не всегда одинаково);
  4) линия, которая есть на большинстве страниц, — линия бланка; случайный росчерк — нет;
  5) подписи колонок — голосованием по шапкам многих страниц;
  6) страница, которая на шаблон не ложится, — особая: другой тип листа, вклейка или ошибка разбора;
  7) таких страниц много и они похожи друг на друга — второй бланк той же части (другой тираж): свой шаблон
     в "variants", place берёт тот, что лёг лучше.

    tools/py tools/scripts/form_template.py build ф48_оп6_д596          # шаблоны всех частей книги
    tools/py tools/scripts/form_template.py check ф48_оп6_д596          # как ложатся выборочные страницы
    tools/py tools/scripts/form_template.py show <скан.jpg> --book ф48_оп6_д596 --section marriages --out x.png

Шаблон — 3_research/archives/catalog/gaso/<дело>.forms.json (в git: только положения линий и печатные подписи
граф, без имён людей).
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import etalon
import form_layout as fl

SECTIONS = ("births", "marriages", "deaths")
SAMPLE = 80           # разворотов на книгу для шаблона (браков в книге мало — на 40 их бывает 4)
TOL = 10              # пикселей: две линии совпали
GOOD_FIT = 0.6        # доля линий шаблона, нашедших пару на странице: ниже — страница особая
MIN_VARIANT = 6       # страниц: столько не легло на главный шаблон и легло на свой — второй бланк в книге
PEOPLE = {"births": {"parents", "godparents"}, "marriages": {"groom", "bride", "sureties"}, "deaths": {"deceased"}}
PEOPLE = {"births": {"parents", "godparents"}, "marriages": {"groom", "bride", "sureties"}, "deaths": {"deceased"}}


def fit(template: list[float], xs: list[int]) -> tuple[float, float, float]:
    """Лучшие масштаб и сдвиг x' = s·x + d, при которых линии шаблона ложатся на линии страницы.
    Возвращает (доля совпавших линий шаблона, s, d)."""
    if not template or not xs:
        return 0.0, 1.0, 0.0
    page = np.array(xs, float)
    best = (0, 1.0, 0.0)
    for s in np.linspace(0.92, 1.08, 33):
        for a in template:
            for b in xs:
                d = b - s * a
                if abs(d) > 300:
                    continue
                mapped = s * np.array(template) + d
                hit = int((np.abs(mapped[:, None] - page[None, :]).min(axis=1) < TOL).sum())
                if hit > best[0] or (hit == best[0] and abs(d) < abs(best[2])):   # при равенстве — меньший сдвиг
                    best = (hit, s, d)
    if best[0] <= 1:          # одна линия ничего не доказывает: оставить как есть (правая страница — от сгиба)
        best = (best[0], 1.0, 0.0)
    return best[0] / len(template), best[1], best[2]


def sample_pages(book: dict) -> dict[str, list[Path]]:
    """Развороты книги по частям — по печатной шапке."""
    lo, hi = book["first"] + 2, book["last"] - 2
    numbers = sorted({round(lo + (hi - lo) * (i + 0.5) / SAMPLE) for i in range(SAMPLE)})
    images = [etalon.scan(book, n) for n in numbers if etalon.scan(book, n).exists()]
    parts = defaultdict(list)
    for path, words in etalon.vision(images).items():
        c = etalon.classify(words)
        if c["section"] in SECTIONS and c["lines"] >= 40:
            parts[c["section"]].append(Path(path))
    return parts


WIDTH = 2000          # все развороты приводим к этой ширине: сканы бывают разного разрешения


def detect(path: Path) -> tuple[list[int], list[int], int, int, float]:
    """Линии разворота в координатах ширины WIDTH; k — во сколько раз картинка меньше (1333 → k = 1.5)."""
    gray = np.asarray(Image.open(path).convert("L"))
    v, h = fl.lines(gray, strict=0.12)
    k = WIDTH / gray.shape[1]
    return [round(x * k) for x in v], [round(y * k) for y in h], WIDTH, round(gray.shape[0] * k), k


def fold_of(xs: list[int]) -> float:
    fold = [x for x in xs if 0.44 * WIDTH <= x <= 0.56 * WIDTH]
    return float(np.mean(fold)) if fold else WIDTH / 2


def halves(xs: list[int]) -> tuple[list[int], list[int], float]:
    """Разворот — две страницы, и сгиб на каждом скане в своём месте (961–1051 на д. 596): каждую половину
    подгоняем отдельно. Левая — от левого края картинки, правая — **от сгиба**: так правая страница с одной
    найденной линией всё равно встаёт на место. Линии у самого сгиба (корешок, край листа) в шаблон не берём."""
    middle = fold_of(xs)
    return ([x for x in xs if x < middle - 25], [round(x - middle) for x in xs if x > middle + 25], middle)


def consensus(pages: list[list[int]]) -> tuple[list[float], list[int]]:
    """Линии, которые есть на многих страницах (после подгонки к опорной), и сколько страниц за каждую."""
    usable = [xs for xs in pages if len(xs) >= 2]
    if len(usable) < 3:
        return [], []
    score = [sum(fit(a, b)[0] for b in usable if b is not a) for a in usable]
    ref = usable[int(np.argmax(score))]
    clusters = [[float(x)] for x in ref]
    for xs in usable:
        if xs is ref:
            continue
        share, sc, d = fit(ref, xs)
        if share < 0.4:
            continue
        for x in xs:
            x_ref = (x - d) / sc
            near = min(clusters, key=lambda c: abs(np.median(c) - x_ref))
            if abs(np.median(near) - x_ref) < TOL:
                near.append(x_ref)
            else:
                clusters.append([x_ref])
    need = max(3, len(usable) / 3)
    keep = sorted((c for c in clusters if len(c) >= need), key=np.median)
    return [round(float(np.median(c)), 1) for c in keep], [len(c) for c in keep]


def header_band(words: list[dict], horizontals: list[int], height: int) -> list[dict]:
    """Слова шапки колонок: между заголовком книги и линией под шапкой (как в form_layout.analyse)."""
    norm = fl.normalize
    keyed = [w for w in words if re.search(norm(fl.HEAD_KEYS), norm(w["text"]))
             and not re.search(norm(fl.TITLE), norm(w["text"]))]
    if not keyed:
        return []
    low, high = max(w["y1"] for w in keyed), min(w["y0"] for w in keyed)
    bottom = min((y for y in horizontals if y >= low - 5), default=low + 5)
    return [w for w in words if high - 10 <= w["y0"] and w["y1"] <= bottom + 5
            and not re.search(norm(fl.TITLE), norm(w["text"]))]


def build_section(pages: list[Path], section: str) -> dict | None:
    found = {p: detect(p) for p in pages}
    split = {p: halves(found[p][0]) for p in pages}
    left, left_n = consensus([split[p][0] for p in pages])   # split: (левая, правая от сгиба, сгиб)
    right, right_n = consensus([split[p][1] for p in pages])
    if len(left) + len(right) < 4:
        return None
    # подписи — голосованием: слова шапки многих страниц переносим на шаблон
    words = []
    for p in pages[:10]:
        v, hz, w, h, k = found[p]
        page_words = fl.header_words(fl.vision(p), round(h / k), round(w / k))
        page_words = [{**wd, "x0": wd["x0"] * k, "x1": wd["x1"] * k, "y0": wd["y0"] * k, "y1": wd["y1"] * k}
                      for wd in page_words]
        band = header_band(page_words, hz, h)
        middle = split[p][2]
        for side, half, xs, origin in (("left", left, split[p][0], 0.0), ("right", right, split[p][1], middle)):
            share, sc, d = fit(half, xs)
            if share < GOOD_FIT or not half:
                continue
            lo, hi = (0, middle) if side == "left" else (0, WIDTH - middle)     # вся страница, до сгиба и от него
            for wd in band:
                x0, x1 = wd["x0"] - origin, wd["x1"] - origin
                if lo <= (x0 + x1) / 2 <= hi:
                    words.append({**wd, "side": side, "x0": (x0 - d) / sc, "x1": (x1 - d) / sc})
    # сгиб — тоже граница: колонка «Родители» доходит до него слева, «Восприемники» начинаются от него справа
    fold = float(np.median([split[p][2] for p in pages]))
    columns = []
    for side, half in (("left", left + [round(fold - 25)]), ("right", [25] + right)):
        for c in fl.label_columns(half, [w for w in words if w["side"] == side], section):
            columns.append({**c, "half": side, "header": c["header"][:120]})
    return {"left": left, "right": right, "fold": round(fold), "support": {"left": left_n, "right": right_n},
            "columns": columns, "pages": len(pages)}


def forms_path(book_id: str) -> Path:
    return book_by_id(book_id)["catalog"] / f"{book_id}.forms.json"


def book_by_id(book_id: str) -> dict:
    return next(b for b in etalon.books() if b["id"] == book_id)


def build(args) -> int:
    for book_id in args.books:
        book = book_by_id(book_id)
        parts = sample_pages(book)
        out = {"book": book_id, "title": book["title"], "sample": SAMPLE, "sections": {}, "variants": {}}
        for section in SECTIONS:
            tpl = build_section(parts.get(section, []), section) if parts.get(section) else None
            more = variants(book, section, tpl) if tpl else []
            if tpl:
                out["sections"][section] = tpl
            if more:
                out["variants"][section] = more
            for i, t in enumerate([tpl] + more):
                fields = " ".join(c["field"] or "·" for c in t["columns"]) if t else "—"
                print(f"{book_id} {section:9}{'' if not i else f' бланк {i + 1}':8} страниц {t['pages'] if t else 0:3} → "
                      f"линий {len(t['left']) if t else 0:2}+{len(t['right']) if t else 0:2} | {fields}")
        forms_path(book_id).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


def place(path: Path, book_id: str, section: str) -> dict:
    """Шаблон, приложенный к странице: колонки в пикселях этой картинки и доля совпавших линий. В книге бывает
    несколько бланков одной части (другой тираж — другие колонки): берём тот, что лёг лучше."""
    doc = json.loads(forms_path(book_id).read_text(encoding="utf-8"))
    found = detect(path)
    tpls = [doc["sections"][section]] + doc.get("variants", {}).get(section, [])
    results = [place_tpl(tpl, found) | {"variant": i} for i, tpl in enumerate(tpls)]
    return max(results, key=lambda r: (r["ok"], min(r["sides"].values(), default=0), r["share"]))


def place_tpl(tpl: dict, found: tuple) -> dict:
    v, hz, w, h, k = found
    left, right, middle = halves(v)
    sides = {"left": left, "right": right}
    origin = {"left": 0.0, "right": middle}
    fits = {side: fit(tpl[side], sides[side]) for side in sides}
    # половина, где линий почти не видно (бледный скан): подгонка по 1–2 случайным линиям хуже, чем место из шаблона
    placed = {side: (f if f[0] >= 0.4 else (f[0], 1.0, 0.0)) for side, f in fits.items()}
    cols = []
    for c in tpl["columns"]:
        share, sc, d = placed[c["half"]]
        o = origin[c["half"]]
        x0, x1 = sc * c["x0"] + d + o, sc * c["x1"] + d + o
        if c["half"] == "left" and c["x1"] >= tpl["fold"] - 30:
            x1 = middle - 25                          # до сгиба этой страницы
        if c["half"] == "right" and c["x0"] <= 30:
            x0 = middle + 25
        cols.append({**c, "x0": round(x0 / k), "x1": round(x1 / k)})
    lines_total = len(tpl["left"]) + len(tpl["right"])
    share = sum(fits[s_][0] * len(tpl[s_]) for s_ in fits) / max(1, lines_total)
    return {"share": round(share, 2), "ok": min(f[0] for s_, f in fits.items() if tpl[s_]) >= GOOD_FIT,
            "sides": {s_: round(f[0], 2) for s_, f in fits.items() if tpl[s_]}, "columns": cols,
            "verticals": [round(x / k) for x in v], "size": [round(w / k), round(h / k)]}


def variants(book: dict, section: str, main: dict) -> list[dict]:
    """Другие бланки той же части: все страницы части, что не легли на главный шаблон, — снова в шаблон; что
    легло на него — второй бланк; повторить с остатком. 10.10.2026: в fs_7767676 развороты 194–222 — другой бланк."""
    numbers = [n for n in range(book["first"], book["last"] + 1) if etalon.scan(book, n).exists()]
    paths = [etalon.scan(book, n) for n in numbers]
    vis = etalon.vision(paths)
    pages = [p for p in paths if (c := etalon.classify(vis[str(p)]))["section"] == section and c["lines"] >= 40]
    found = {p: detect(p) for p in pages}
    left = [p for p in pages if not place_tpl(main, found[p])["ok"]]
    out = []
    while len(left) >= MIN_VARIANT and len(out) < 3:
        tpl = build_section(left[:SAMPLE], section)
        if not tpl or not PEOPLE[section] <= {c["field"] for c in tpl["columns"]}:
            break                                     # колонки с людьми не опознаны — читать по нему хуже, чем по главному
        fits = [p for p in left if place_tpl(tpl, found[p])["ok"]]
        if len(fits) < MIN_VARIANT:
            break
        out.append(tpl | {"pages": len(fits)})
        left = [p for p in left if p not in fits]
    return out


def check(args) -> int:
    for book_id in args.books:
        book = book_by_id(book_id)
        for section, pages in sample_pages(book).items():
            if section not in json.loads(forms_path(book_id).read_text(encoding="utf-8"))["sections"]:
                continue
            for p in pages:
                r = place(p, book_id, section)
                print(f"{book_id} {section:9} {p.name:32} совпало {r['share']:.0%} {r['sides']} "
                      f"{'' if r['ok'] else '← не ложится'}")
    return 0


def show(args) -> int:
    path = Path(args.image).expanduser()
    r = place(path, args.book, args.section)
    img = Image.open(path).convert("RGB")
    draw = ImageDraw.Draw(img)
    w, h = r["size"]
    font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 22)
    for x in r["verticals"]:
        draw.line([(x, 0), (x, h)], fill=(160, 160, 160), width=1)
    for c in r["columns"]:
        draw.line([(c["x0"], 0), (c["x0"], h)], fill=(220, 0, 0), width=3)
        if c["field"]:
            draw.text((c["x0"] + 4, h * 0.27), c["field"], fill=(200, 0, 120), font=font)
    img.save(args.out)
    print(f"совпало {r['share']:.0%} {r['sides']} → {args.out}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("build")
    s.add_argument("books", nargs="+")
    s.set_defaults(func=build)
    s = sub.add_parser("check")
    s.add_argument("books", nargs="+")
    s.set_defaults(func=check)
    s = sub.add_parser("show")
    s.add_argument("image")
    s.add_argument("--book", required=True)
    s.add_argument("--section", required=True, choices=SECTIONS)
    s.add_argument("--out", required=True)
    s.set_defaults(func=show)
    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
