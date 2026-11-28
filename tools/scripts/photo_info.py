#!/usr/bin/env python3
"""Всё, что известно о снимке: строка описи (00_ОПИСЬ*.md рядом со снимками) и метки внутри jpg.

Сайт показывает это в окне просмотра фото человека: подпись, все колонки строки описи («Кто», «Где и когда»…),
из какой описи строка и что записано в самом файле (описание, дата, место, ключевые слова).

Строку описи снимок находит двумя путями:
  1. имя файла названо в строке — `Анна-Ковальчик_с-дочерью_1933.jpg` (оригинал или копия, в любой колонке);
  2. копия из присылки — имя кончается на «_присылка-2026-11-28-архив-37»: опись в папке присылки
     1_sources/family/messages/2026-11-28_…, строка № 37 в разделе, где есть слово «архив» (у присылки с одной
     таблицей — «_присылка-2026-11-23-13», без слова).

    tools/py tools/scripts/photo_info.py "<имя снимка.jpg>" [...]   # что найдено о снимке
    tools/py tools/scripts/photo_info.py --missing                    # фото из карточек людей, о которых описи нет
"""
from __future__ import annotations

import functools
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

import paths

IMG = r"\.(?:jpe?g|png|webp)"
NAME = re.compile(rf"([^\s`|\[\]()«»„“\"']+{IMG})", re.I)
PRESYLKA = re.compile(r"присылка-(\d{4}-\d{2}-\d{2})(?:-([^\W\d_]+))?-(\d+)$", re.I)
# колонки, что не показываем посетителю: номер строки и имена файлов
SKIP = ("№", "#", "файл", "оригинал", "кадр", "вырезк", "копи", "снимок")
CAPTION = ("подпись", "что")


def N(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _cells(line: str) -> list[str]:
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


@functools.cache
def rows() -> list[dict]:
    """Все строки таблиц описей: {"inv", "title", "section", "header", "cells"}."""
    out = []
    invs = [p for base in (paths.SOURCES, paths.TRANSCRIPTS) if base.exists() for p in base.rglob("00_ОПИСЬ*.md")]
    for inv in sorted(invs):
        title, section, header = inv.stem, "", None
        for line in N(inv.read_text(encoding="utf-8")).splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
            if line.startswith("#"):
                section, header = line.lstrip("#").strip(), None
                continue
            if not line.startswith("|"):
                header = None if not line.strip() else header
                continue
            if re.fullmatch(r"[\s|:-]+", line):
                continue
            cells = _cells(line)
            if header is None:
                header = cells
                continue
            out.append({"inv": inv, "title": title, "section": section, "header": header, "cells": cells})
    return out


@functools.cache
def _index():
    by_name, by_num = {}, {}
    for r in rows():
        for c in r["cells"]:
            for m in NAME.findall(c):
                by_name.setdefault(N(Path(m).name), r)
        date = re.match(r"\d{4}-\d{2}-\d{2}", r["inv"].parent.name)
        if date and r["header"][0].strip() in ("№", "#") and (num := re.match(r"\d+", r["cells"][0])):
            by_num.setdefault((date[0], int(num[0])), []).append(r)
    return by_name, by_num


def row_for(name: str) -> dict | None:
    """Строка описи о снимке или None."""
    by_name, by_num = _index()
    name = N(Path(name).name)
    if name in by_name:
        return by_name[name]
    m = PRESYLKA.search(Path(name).stem)
    if not m:
        return None
    hits = by_num.get((m[1], int(m[3])), [])
    if m[2]:
        hits = [r for r in hits if m[2].lower()[:4] in r["section"].lower()]
    return hits[0] if len(hits) == 1 else None


def from_row(r: dict) -> dict:
    """{"caption": подпись, "rows": [(колонка, значение)], "origin": «опись · раздел, № N»} — строки как в описи."""
    pairs = [(h.strip(), c) for h, c in zip(r["header"], r["cells"]) if c and c not in ("—", "-")]
    keep = [(h, c) for h, c in pairs if not h.lower().startswith(SKIP)]
    ci = next((i for i, (h, _) in enumerate(keep) if h.lower().startswith(CAPTION)), 0)
    num = r["cells"][0] if r["header"][0].strip() in ("№", "#") else ""
    where = " · ".join(x for x in (r["title"], r["section"] if r["section"] != r["title"] else "") if x)
    return {"caption": keep[ci][1] if keep else "", "rows": [x for i, x in enumerate(keep) if i != ci],
            "origin": f"{where}{f', № {num}' if num else ''}"}


# метки внутри jpg: (что, теги exiftool по порядку — берём первый непустой)
TAGS = [("Описание в файле", ("XMP-dc:Description", "IPTC:Caption-Abstract", "EXIF:ImageDescription")),
        ("Название в файле", ("XMP-dc:Title", "IPTC:ObjectName")),
        ("Дата в файле", ("XMP-photoshop:DateCreated", "EXIF:DateTimeOriginal", "IPTC:DateCreated")),
        ("Место в файле", ("XMP-iptcExt:LocationShownCity", "XMP-iptcCore:Location", "XMP-photoshop:City", "IPTC:City")),
        ("Страна в файле", ("XMP-photoshop:Country", "IPTC:Country-PrimaryLocationName")),
        ("Ключевые слова", ("XMP-dc:Subject", "IPTC:Keywords")),
        ("Автор", ("XMP-dc:Creator", "EXIF:Artist", "IPTC:By-line")),
        ("Источник", ("XMP-photoshop:Source", "XMP-dc:Source", "IPTC:Source", "XMP-photoshop:Credit")),
        ("Примечание в файле", ("EXIF:UserComment", "XMP-exif:UserComment"))]


def tags(files: list[Path]) -> dict[Path, list[tuple[str, str]]]:
    """Метки внутри файлов: {путь: [(что, значение)]}; нет exiftool — пусто."""
    exe, files = shutil.which("exiftool"), [f for f in files if f.exists()]
    if not exe or not files:
        return {}
    want = sorted({t for _, ts in TAGS for t in ts})
    out = {}
    for i in range(0, len(files), 400):
        part = files[i:i + 400]
        res = subprocess.run([exe, "-json", "-G1", "-charset", "filename=utf8", *[f"-{t}" for t in want], *map(str, part)],
                             capture_output=True, text=True)
        for d in json.loads(res.stdout or "[]"):
            rows_ = []
            for label, ts in TAGS:
                v = next((d[t] for t in ts if d.get(t) not in (None, "", [])), None)
                if v is not None:
                    v = ", ".join(map(str, v)) if isinstance(v, list) else str(v)
                    if label.startswith("Дата"):
                        v = re.sub(r"^(\d{4}):(\d{2}):(\d{2}).*", r"\3.\2.\1", v)
                    rows_.append((label, N(v)))
            out[Path(N(d["SourceFile"]))] = rows_
    return out


GED_TAGS = {"TITL": "Название", "DATE": "Дата", "PLAC": "Место", "NOTE": "Примечание"}


@functools.cache
def gedcom() -> dict[str, list[tuple[str, str]]]:
    """Подписи снимков в выгрузках дерева (GEDCOM: OBJE → FILE, TITL, DATE, PLAC, NOTE): {имя файла: [(что, значение)]}.
    Это снимки, скачанные с MyHeritage (I500999_01_….jpg), — у них нет описи, но есть название с сайта."""
    files = sorted((paths.SOURCES / "others_trees" / "myheritage").glob("*.ged")) + sorted(paths.RESEARCH.glob("tree_data/*.ged"))
    out = {}
    for ged in files:
        block, lvl = None, 0
        for line in N(ged.read_text(encoding="utf-8", errors="replace")).splitlines():
            m = re.match(r"(\d+) (\S+) ?(.*)", line.strip())
            if not m:
                continue
            n, tag, val = int(m[1]), m[2], m[3].strip()
            if tag == "OBJE":
                block, lvl = {"files": [], "rows": []}, n
                continue
            if block is None:
                continue
            if n <= lvl:
                for f in block["files"]:
                    if block["rows"]:
                        out.setdefault(f, block["rows"])
                block = None
                continue
            if tag == "FILE" and val:
                block["files"].append(N(re.split(r"[\\/]", val)[-1]))
            elif tag in GED_TAGS and val and n == lvl + 1 or (tag in ("DATE", "PLAC") and val):
                block["rows"].append((GED_TAGS[tag], val))
    return out


def info(name: str, path: Path | None = None, file_tags: list | None = None) -> dict | None:
    """Всё о снимке: {"caption", "rows", "origin"} — из описи, выгрузки дерева и меток файла; ничего нет — None."""
    r = row_for(name)
    out = from_row(r) if r else {"caption": "", "rows": [], "origin": ""}
    for label, v in gedcom().get(N(Path(name).name), []):
        if label == "Название" and not out["caption"]:
            out["caption"] = v
            out["origin"] = out["origin"] or "выгрузка дерева (GEDCOM)"
        elif v not in (out["caption"], *[x for _, x in out["rows"]]):
            out["rows"].append((label, v))
    if file_tags is None and path:
        file_tags = tags([path]).get(Path(N(str(path))), [])
    for label, v in file_tags or []:
        if label.startswith("Описание") and not out["caption"]:
            out["caption"] = v
        elif v not in (out["caption"], *[x for _, x in out["rows"]]):
            out["rows"].append((label, v))
    return out if out["caption"] or out["rows"] else None


def main(argv: list[str]) -> None:
    import avatar
    where = avatar.media_paths()
    if argv[:1] == ["--missing"]:
        import photo_faces
        names = sorted(photo_faces.media_of_people())
        miss = [n for n in names if not info(n)]
        print(f"фото в карточках людей: {len(names)}, ничего не известно: {len(miss)}")
        print("\n".join(miss))
        return
    for name in argv:
        print(f"== {name}")
        got = info(name, where.get(N(Path(name).name)))
        if not got:
            print("  ничего не найдено")
            continue
        print(f"  подпись: {got['caption']}")
        for h, v in got["rows"]:
            print(f"  {h}: {v}")
        print(f"  откуда: {got['origin']}")


if __name__ == "__main__":
    if not sys.argv[1:] or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
    else:
        main(sys.argv[1:])
