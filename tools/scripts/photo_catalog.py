#!/usr/bin/env python3
"""Каталог всех фото проекта: одна страница в Obsidian — 3_research/КАТАЛОГ_ФОТО.md.

Фото лежат по происхождению (чей архив, откуда пришло), а к людям привязываются ссылкой
из поля media в карточке человека. Каталог собирает обе стороны:
  — по людям: у кого какие снимки (миниатюры);
  — не привязанные к людям семейные фото — список «кого ещё опознать»;
  — фото мест по странам и городам; иллюстрации по темам; обработанные копии.
Файл создаётся заново при каждом запуске — руками не правим.

Запуск: python3 tools/scripts/photo_catalog.py
"""
import os
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

N = lambda s: unicodedata.normalize("NFC", s)
IMG = (".jpg", ".jpeg", ".png", ".webp", ".svg")
OUT = paths.RESEARCH / "КАТАЛОГ_ФОТО.md"


def images(folder):
    out = []
    for d, ds, fs in os.walk(folder):
        if "social_export" in d:
            ds[:] = []
            continue
        out += [Path(d) / f for f in sorted(fs) if f.lower().endswith(IMG)]
    return out


def rel(p):
    return N(p.relative_to(paths.ROOT).as_posix())


def main():
    by_person = {}
    linked = set()
    for p in sorted((paths.TREE / "people").glob("*.md")):
        t = p.read_text(encoding="utf-8")
        m = re.search(r"^media:(.*(?:\n  - .*)*)", t, re.M)
        if not m:
            continue
        files = [N(os.path.basename(x)) for x in re.findall(r"\[\[([^\]|]+)", m.group(1))]
        if files:
            by_person[p.stem] = files
            linked.update(files)
    # страницы документов (2_transcripts/documents, ДОК1–ДОК2) — не «фото без человека», они уже в документе
    for d in sorted((paths.TRANSCRIPTS / "documents").rglob("*.md")):
        linked.update(N(os.path.basename(x)) for x in re.findall(r"file: '?\"?\[\[([^\]|]+)", d.read_text(encoding="utf-8")))

    L = ["# Каталог фото", "",
         "> Собирается скриптом `rodo photo-catalog` — руками не править.",
         "> **Как устроено.** Оригиналы лежат по происхождению: `1_sources/family/` — от семьи, "
         "`1_sources/found/` — найдено в открытых источниках, `1_sources/others_trees/` — из MyHeritage и чужих деревьев. "
         "Обработанные копии (реставрация, уменьшенные для книги) — `2_transcripts/photos_processed/`, оригинал не трогаем. "
         "К человеку фото привязывается строкой в поле `media` его карточки; первое фото в списке — портрет на схеме.",
         "> **Имя файла:** `Кто_что_дата-№.jpg`; не уверены, кто на снимке, — `(предп)`; оборот — `_ОБОРОТ`; "
         "обработанная копия — `_restored` или `_мал`.", ""]

    fam = images(paths.FAMILY) + images(paths.OTHERS_TREES)
    if linked and not fam and not images(paths.PHOTOS_PROCESSED):
        # карточки ссылаются на фото, а на диске нет ни одного: копия дерева без медиа (вторая рабочая копия, свежий
        # клон) — каталог не переписывать, иначе он опустеет и уйдёт так в коммит
        print(f"{rel(OUT)}: фото на этом диске нет (копия без медиа — rodo media pull) — каталог не переписан")
        return
    # людей на снимке нет: скриншоты переписки, обложки, исходные кадры с телефона (из них вырезаны документы)
    skip = lambda p: "_chat_" in p.name or p.name.startswith("обложка") or "_originals" in p.parts
    orphans = [p for p in fam if N(p.name) not in linked and not skip(p)]
    L += [f"## Кого ещё привязать — {len(orphans)} семейных фото без человека", ""]
    for p in orphans:
        L.append(f"- ![[{rel(p)}|80]] `{rel(p)}`")
    L.append("")

    L += [f"## По людям — {len(by_person)} человек", ""]
    for person, files in sorted(by_person.items()):
        L.append(f"### [[{person}]] — {len(files)}")
        L.append(" ".join(f"![[{f}|90]]" for f in files))
        L.append("")

    places = defaultdict(list)
    for p in images(paths.PHOTOS_PLACES):
        parts = p.relative_to(paths.PHOTOS_PLACES).parts
        places[" / ".join(parts[:2]) if len(parts) > 2 else parts[0]].append(p)
    L += [f"## Места — {sum(map(len, places.values()))} фото, {len(places)} мест", "",
          "Описи с источником и тем, насколько снимок «наш»: `1_sources/found/photos_places/00_ОПИСЬ_*.md`.", "",
          "| Место | Фото | Пример |", "|---|---|---|"]
    for k, v in sorted(places.items()):
        L.append(f"| {k} | {len(v)} | ![[{rel(v[0])}\\|80]] |")  # «\\|» — чтобы таблица не рвалась
    L.append("")

    themes = defaultdict(list)
    for p in images(paths.PHOTOS_HISTORY):
        themes[p.relative_to(paths.PHOTOS_HISTORY).parts[0]].append(p)
    L += ["## Иллюстрации к главам (найдено в открытых источниках)", "", "| Тема | Фото |", "|---|---|"]
    for k, v in sorted(themes.items()):
        L.append(f"| `{k}` | {len(v)} |")
    L.append("")

    proc = images(paths.PHOTOS_PROCESSED)
    L += [f"## Обработанные копии — {len(proc)}", ""] + [f"- `{rel(p)}`" for p in proc] + [""]

    OUT.write_text("\n".join(L), encoding="utf-8")
    print(f"{rel(OUT)}: людей с фото {len(by_person)}, без человека {len(orphans)}, мест {len(places)}")


if __name__ == "__main__":
    main()
