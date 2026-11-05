#!/usr/bin/env python3
"""Нарезка домашнего архива семьи на документы (правила — навык card-rules, «Документы человека»).

17 семейных PDF — «папки всё подряд» из фотографий подлинников (сейф у бабушки). Этот скрипт берёт описание
разбивки (YAML), достаёт из PDF нужные страницы-картинки без пересжатия, при нужде поворачивает без потерь,
кладёт их в 2_transcripts/photos_processed/family_archive/ под названием по содержанию, пишет описание документа
(свойства + текст из файла `body`) в 2_transcripts/documents/<Имя карточки>/ и собирает PDF.
Оригиналы PDF не трогает.

Описание разбивки (YAML): список `documents`, у каждого —
  name        имя файла без расширения («1953–2005 — Трудовая книжка — Иван Ясенев»)
  kind        вид из documents.KINDS;  title — заголовок;  person — карточка; people — кто ещё назван
  variant     у метрик: crops (вырезки) или spreads (развороты)
  order       book — страницы в порядке самой книжки (иначе по датам)
  access      closed — не для сайта (здоровье и т. п.)
  obtained    откуда (по умолчанию — ftree.toml, [split_archive] obtained)
  body        путь к файлу с текстом (разделы «## n. дата — что») — относительно файла описания
  pages       список: pdf (номер DocNN), page, rot (градусы по часовой), file (имя картинки без .jpg), date, what;
              или готовый снимок: image (имя файла с расширением, где угодно в 1_sources/2_transcripts), locator, date, what
  where, author, repository — для документов не из домашнего архива (откуда снимки, чьи)
Команды:
    tools/py tools/scripts/split_archive.py pages <spec.yaml>   # только картинки страниц
    tools/py tools/scripts/split_archive.py build <spec.yaml>   # картинки + описания + PDF
"""
import argparse
import random
import re
import string
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

import documents
import paths
from paths import FAMILY_ARCHIVE, PHOTOS_PROCESSED, ROOT, TREE

OUT_IMAGES = PHOTOS_PROCESSED / "family_archive"
# Сам домашний архив — ftree.toml дерева, [split_archive]: карточка-хранилище, откуда взято ({pdf} — номера PDF),
# подпись снимков ({card} — карточка), автор и метка источника. Без раздела — общие слова.
ARCHIVE_CARD = paths.tree_conf("split_archive.archive_card", "Домашний архив")
SOURCE_TYPES = {"civil": "vital_record", "letter": "letter"}
OBTAINED = paths.tree_conf("split_archive.obtained", "домашний архив: фотография подлинника; вошла в семейный PDF {pdf}")
WHERE = paths.tree_conf("split_archive.where", "Фотографии подлинников из домашнего архива — [[{card}]].")
AUTHOR = paths.tree_conf("split_archive.author", "семья")
TAG = paths.tree_conf("split_archive.tag", "Архив-домашний")


def find_pdf(num: str) -> Path:
    found = sorted(FAMILY_ARCHIVE.glob(f"Doc{num} *.pdf"))
    if len(found) != 1:
        raise FileNotFoundError(f"Doc{num}: PDF в {FAMILY_ARCHIVE} — {len(found)} шт.")
    return found[0]


def page_image(pdf: Path, page: int, tmp: Path) -> Path:
    """Картинка страницы как лежит в PDF (jpeg без пересжатия)."""
    prefix = tmp / f"{pdf.stem[:8]}-{page}"
    subprocess.run(["pdfimages", "-j", "-f", str(page), "-l", str(page), str(pdf), str(prefix)], check=True)
    files = sorted(tmp.glob(f"{prefix.name}-*.jpg"))
    if len(files) != 1:
        raise RuntimeError(f"{pdf.name}, стр. {page}: картинок {len(files)}, нужна одна")
    return files[0]


def person_id(name: str) -> str:
    text = (TREE / "people" / f"{name}.md").read_text(encoding="utf-8")
    return re.search(r"^cr_id: (\S+)", text, re.M)[1]


def source_name(doc: dict) -> str:
    """«1953–2005 — Трудовая книжка — Иван Ясенев» → «Трудовая книжка — Иван Ясенев (1953–2005)»."""
    years, _, rest = doc["name"].partition(" — ")
    return f"{rest} ({years})"


def write_source_card(doc: dict) -> Path:
    """Карточка источника на документ: на неё ссылаются факты в карточках (check_cards ждёт карточку в sources/)."""
    rnd = random.Random(doc["cr_id"])
    cr_id = "-".join(["".join(rnd.choice(string.ascii_lowercase) for _ in range(3)), "%03d" % rnd.randint(0, 999),
                      "".join(rnd.choice(string.ascii_lowercase) for _ in range(3)), "%03d" % rnd.randint(0, 999)])
    name = source_name(doc)
    text = f"""---
cr_id: {cr_id}
cr_type: source
origin: "семья"
title: "{name}"
source_type: {SOURCE_TYPES.get(doc["kind"], "custom")}
author: "{doc.get("author", AUTHOR)}"
repository: "{doc.get("repository", ARCHIVE_CARD)}"
repository_type: "Private"
source_medium: "Electronic"
confidence: high
tags:
  - Происхождение-семья
  - {TAG}
---
# {name}

{doc["title"]}. {doc.get("where") or WHERE.format(card=ARCHIVE_CARD)}

**Документ (страницы, текст слово в слово):** [[{doc["name"]}]] — `2_transcripts/documents/{doc["person"]}/`.
"""
    path = TREE / "sources" / f"{name}.md"
    path.write_text(text, encoding="utf-8")
    return path


def make_pages(doc: dict) -> None:
    OUT_IMAGES.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as t:
        for page in doc["pages"]:
            if page.get("image"):  # готовый снимок (не из PDF): берём как есть, по имени файла
                continue
            out = OUT_IMAGES / f"{page['file']}.jpg"
            if out.exists():
                continue
            src = page_image(find_pdf(str(page["pdf"])), int(page["page"]), Path(t))
            rot = int(page.get("rot", 0)) % 360
            if rot:
                subprocess.run(["jpegtran", "-rotate", str(rot), "-copy", "all", "-outfile", str(out), str(src)],
                               check=True)
            else:
                out.write_bytes(src.read_bytes())


def page_ranges(nums) -> str:
    """[13, 14, 15, 17] → «13–15, 17»."""
    nums, out = sorted(set(nums)), []
    for n in nums:
        if out and n == out[-1][1] + 1:
            out[-1][1] = n
        else:
            out.append([n, n])
    return ", ".join(str(a) if a == b else f"{a}–{b}" for a, b in out)


def pdf_line(doc: dict) -> tuple[str, list[str]]:
    """Откуда взяты страницы: ссылка на семейный PDF и номера страниц — чтобы можно было сверить с оригиналом."""
    by_pdf: dict[str, list[int]] = {}
    for p in doc["pages"]:
        if p.get("image"):
            continue
        by_pdf.setdefault(str(p["pdf"]), []).append(int(p["page"]))
    if not by_pdf:
        return "", []
    parts, short = [], []
    for num, pages in by_pdf.items():
        pdf = find_pdf(num)
        parts.append(f"[[{pdf.relative_to(ROOT).as_posix()}]], стр. {page_ranges(pages)}")
        short.append(f"Doc{num}: {page_ranges(pages)}")
    return "**Из семейного PDF (для сверки):** " + "; ".join(parts) + ".", short


def write_description(doc: dict, base: Path) -> Path:
    person = doc["person"]
    folder = documents.DOCUMENTS / person
    folder.mkdir(parents=True, exist_ok=True)
    pdfs = sorted({f"Doc{p['pdf']}" for p in doc["pages"] if not p.get("image")})
    fm = {
        "cr_type": "document",
        "cr_id": doc["cr_id"],
        "title": doc["title"],
        "kind": doc["kind"],
        "person": f"[[{person}]]",
        "person_id": person_id(person),
    }
    if doc.get("people"):
        fm["people"] = [f"[[{p}]]" for p in doc["people"]]
    if doc.get("access"):
        fm["access"] = doc["access"]
    if doc.get("variant"):
        fm["variant"] = doc["variant"]
    if doc.get("order"):
        fm["order"] = doc["order"]
    line, short = pdf_line(doc)
    if short:
        fm["pdf_pages"] = short
    fm["origin"] = "семья"
    fm["obtained"] = doc.get("obtained") or OBTAINED.format(pdf=", ".join(pdfs))
    fm["pages"] = [
        {"file": f"[[{p['image'] if p.get('image') else p['file'] + '.jpg'}]]", "date": str(p["date"]), "what": p["what"],
         "source": f"[[{source_name(doc)}]]",
         "locator": p.get("locator") or f"Doc{p['pdf']}, стр. {p['page']} PDF"}
        for p in doc["pages"]
    ]
    body = (base / doc["body"]).read_text(encoding="utf-8").strip()
    first, _, rest = body.partition("\n")  # после заголовка «# …» — откуда страницы
    body = f"{first}\n\n{line}\n\n{rest.strip()}" if line else body
    head = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False, width=200)
    md = folder / f"{doc['name']}.md"
    md.write_text(f"---\n{head}---\n\n{body}\n", encoding="utf-8")
    return md


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["pages", "build"])
    parser.add_argument("spec")
    args = parser.parse_args()
    spec_path = Path(args.spec).resolve()
    docs = yaml.safe_load(spec_path.read_text(encoding="utf-8"))["documents"]
    for doc in docs:
        make_pages(doc)
        if args.command == "build":
            write_source_card(doc)
            md = write_description(doc, spec_path.parent)
            pdf = documents.build(md)
            print(f"{md.relative_to(ROOT)}: страниц {len(doc['pages'])}, PDF {pdf.stat().st_size // 1024} КБ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
