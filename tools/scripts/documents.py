#!/usr/bin/env python3
"""Документы человека (правила — навык card-rules, раздел «Документы человека»): PDF со страницами по датам и рядом — текст и описание.

Документ — то, что о человеке держат в руках как одну вещь: трудовая книжка, паспорт, «все метрики Сергия».
Лежит в 2_transcripts/documents/<Имя карточки>/ двумя файлами с одним именем:
  <годы> — <Вид>[ — вариант].pdf   страницы по датам (собирает этот скрипт из картинок страниц);
  <годы> — <Вид>[ — вариант].md    описание (свойства) + текст страниц слово в слово.
У большинства людей документов нет — тогда и папки нет, и это не ошибка.

Свойства описания (.md):
  cr_type: document · cr_id · title · kind (см. KINDS) · variant (у метрик: crops — вырезки записей,
  spreads — развороты целиком) · person + person_id (чей документ) · people (кто ещё назван) ·
  order: book — страницы в порядке самой книжки, а не по датам (трудовая: записи о работе и о поощрениях идут отдельно) ·
  access: closed — не для сайта (здоровье и т. п.) ·
  origin (семья / найдено) · obtained (откуда взято: архив и шифр или «дом на Садовой») ·
  pages — список по порядку дат: file (картинка страницы), date (GEDCOM), what, source ([[карточка источника]]), locator.
Текст — раздел «## <n>. <дата> — <что>» на страницу; у разворотов текста нет (текст — у вырезок).

    tools/py tools/scripts/documents.py build "<путь к .md>"   # собрать PDF по описанию
    tools/py tools/scripts/documents.py check                  # все документы: страницы, даты, PDF, люди
"""
import argparse
import re
import sys
from pathlib import Path

import dates
from cards.notes import LOADER
from paths import ROOT, SOURCES, TRANSCRIPTS, TREE, rel
import yaml

DOCUMENTS = TRANSCRIPTS / "documents"
# Вид → как называется в имени файла; группировка — решение Павла 02.10.2026
KINDS = {
    "metrics": "Метрики",                         # все метрики человека одним документом (когда работа по ним закончена)
    "civil": "Свидетельство ЗАГС",                # каждое отдельно
    "passport": "Паспорт",                        # каждый отдельно
    "labor": "Трудовая книжка",                   # каждая отдельно
    "military": "Военные документы",              # военный билет, учётная карточка, наградной лист — вместе
    "education": "Образование",                   # дипломы, аттестаты — вместе
    "awards": "Награды",                          # ордена, медали, удостоверения — вместе
    "personal": "Анкеты и характеристики",        # анкета, характеристика, автобиография — вместе, иногда отдельно
    "certificate": "Справка",                     # архивная, о реабилитации… — каждая отдельно
    "letter": "Письмо",                           # каждое отдельно
    "lists": "Списки",                            # перепись, исповедная ведомость, ревизская сказка — вместе
    "other": "Другое",
}
VARIANTS = {"crops": "вырезки", "spreads": "развороты"}
FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def read(md: Path) -> tuple[dict, str]:
    text = md.read_text(encoding="utf-8")
    m = FRONT.match(text)
    if not m:
        raise ValueError(f"{md}: нет свойств между ---")
    return yaml.load(m[1], Loader=LOADER) or {}, text[m.end():]


def media_file(link: str) -> Path | None:
    """[[имя.jpg]] → файл в проекте (по имени, как Obsidian)."""
    name = re.sub(r"^\[\[|\]\]$", "", str(link)).split("|")[0]
    for top in (SOURCES, TRANSCRIPTS):      # от ROOT: тесты подменяют корень
        found = next((ROOT / rel(top)).rglob(name), None)
        if found:
            return found
    return None


def problems(md: Path) -> list[str]:
    fm, body = read(md)
    out = []
    kind = fm.get("kind")
    if fm.get("cr_type") != "document":
        out.append("cr_type не document")
    if kind not in KINDS:
        out.append(f"kind «{kind}» — не из списка: {', '.join(KINDS)}")
    if kind == "metrics" and fm.get("variant") not in VARIANTS:
        out.append("у метрик variant: crops (вырезки) или spreads (развороты)")
    person = re.sub(r"^\[\[|\]\]$", "", str(fm.get("person", ""))).split("|")[0]
    if not (TREE / "people" / f"{person}.md").exists():
        out.append(f"нет карточки человека «{person}»")
    if md.parent.name != person:
        out.append(f"лежит в папке «{md.parent.name}», а документ — «{person}»")
    if not fm.get("obtained"):
        out.append("нет obtained — откуда взято")
    pages = fm.get("pages") or []
    if not pages:
        out.append("нет страниц")
    for i, page in enumerate(pages, 1):
        if not media_file(page.get("file", "")):
            out.append(f"стр. {i}: нет файла {page.get('file')}")
        try:
            dates.parse_card(str(page.get("date", "")))
        except Exception as exc:  # noqa: BLE001
            out.append(f"стр. {i}: дата «{page.get('date')}» не по правилу ({exc})")
        if not page.get("source"):
            out.append(f"стр. {i}: нет source")
    years = [dates.year(str(p.get("date", ""))) or 0 for p in pages]
    if years != sorted(years) and fm.get("order") != "book":
        out.append("страницы не по датам (у трудовой книжки — order: book, порядок самой книжки)")
    pdf = md.with_suffix(".pdf")
    if not pdf.exists():
        out.append("нет PDF — documents.py build")
    elif any((f := media_file(p.get("file", ""))) and f.stat().st_mtime > pdf.stat().st_mtime for p in pages) \
            or md.stat().st_mtime > pdf.stat().st_mtime + 1:
        out.append("PDF старее описания или страниц — documents.py build")
    if fm.get("variant") != "spreads" and pages and not re.search(r"^## \d+\. ", body, re.M):
        out.append("нет текста страниц (разделы «## 1. <дата> — <что>»)")
    return out


def build(md: Path) -> Path:
    from PIL import Image
    fm, _ = read(md)
    pages = fm.get("pages") or []
    files = [media_file(p["file"]) for p in pages]
    if not all(files):
        raise FileNotFoundError(f"нет страниц: {[p['file'] for p, f in zip(pages, files) if not f]}")
    images = [Image.open(f).convert("RGB") for f in files]
    pdf = md.with_suffix(".pdf")
    images[0].save(pdf, save_all=True, append_images=images[1:], resolution=200,
                   title=fm.get("title", md.stem), author=str(fm.get("obtained", "")))
    return pdf


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build").add_argument("md")
    sub.add_parser("check")
    args = parser.parse_args()
    if args.command == "build":
        md = Path(args.md).resolve()
        pdf = build(md)
        print(f"Собрано: {pdf.relative_to(ROOT)}; страниц {len(read(md)[0].get('pages') or [])}")
        return 0
    docs = sorted(DOCUMENTS.rglob("*.md")) if DOCUMENTS.exists() else []
    bad = 0
    for md in docs:
        for msg in problems(md):
            print(f"{md.relative_to(ROOT)}: {msg}")
            bad += 1
    people = len({md.parent.name for md in docs})
    print(f"Документы: {len(docs)} у {people} человек, ошибок {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
