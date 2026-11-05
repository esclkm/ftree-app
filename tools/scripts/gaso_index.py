#!/usr/bin/env python3
"""Карта метрики ГАСО: сканы → редкие локальные пробы → проверенные опоры.

    python3 tools/scripts/gaso_index.py catalog --book 517
    python3 tools/scripts/gaso_index.py sample --book 517 --count 8
    python3 tools/scripts/gaso_index.py probe --book 517 --pages 60,100
    python3 tools/scripts/gaso_index.py probe --book 517 --pages 60,100 --run
    python3 tools/scripts/gaso_index.py verify --book 517 --page 60 --year 1894 \
        --section births --evidence "год и часть прочитаны на оригинале"
    python3 tools/scripts/gaso_index.py locate --book 517 --year 1894 --section births

Модель предлагает опоры, но не подтверждает их. Номер файла НЕ является номером листа.
Сбившаяся последовательность запрещает бинарный поиск по всей книге.

Где что лежит (с 02.10.2026, документ дерева проект/ХРАНЕНИЕ.md):
  каталог дела (git)  3_research/archives/catalog/gaso/<дело>.jsonl — у файла строка «check»: статус (proposed / verified),
                      год, раздел, месяц, лист, акты — разобранные из ответа модели (proposed) или проверенные по
                      оригиналу; в evidence чужих имён не писать — только что сверено;
  слова модели        $ARCHIVES_LOCAL/text/gaso/<дело>/probes.json — ответы и промпты (в них бывают имена).
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import unicodedata

import archives
import gaso_find as finder
import gaso_flow as flow
from paths import ARCHIVES_TEXT, NoRaw

TEXT = ARCHIVES_TEXT / "gaso"
TEXT_KEYS = ("response", "header_response", "candidate_read", "prompt")   # слова модели — только в text/
CHECK_KEYS = ("state", "model", "year", "section", "month", "folio", "acts", "evidence")
SECTIONS = {"родив": "births", "рожд": "births", "брак": "marriages", "бракосоч": "marriages",
            "умер": "deaths", "смерт": "deaths"}
MONTHS = ("январ", "феврал", "март", "апрел", "ма", "июн", "июл", "август", "сентябр", "октябр", "ноябр", "декабр")
PROMPT = (
    "Метрическая книга XIX века. Определи ТОЛЬКО то, что явно видно на этом развороте: "
    "год, часть книги (о родившихся/бракосочетавшихся/умерших), месяц, номера актов и номер листа. "
    "Ничего не угадывай из порядка страниц. Ответи одной строкой: "
    "ГОД: <цифры или НРЗБ>; РАЗДЕЛ: <рождения/браки/смерти/НРЗБ>; "
    "МЕСЯЦ: <название или НРЗБ>; АКТЫ: <номера или НРЗБ>; ЛИСТ: <номер или НРЗБ>. "
    "Если на странице нет года, пиши НРЗБ."
)
HEADER_PROMPT = (
    "Прочитай только ЯВНО НАПИСАННЫЕ заголовки и даты в верхней части скана метрической книги. "
    "Если год/месяц/раздел НЕ виден, напиши НРЗБ; НЕ вычисляй по номеру листа или контексту. "
    "Ответь: ГОД: <цифры/НРЗБ>; РАЗДЕЛ: <рождения/браки/смерти/НРЗБ>; МЕСЯЦ: <название/НРЗБ>."
)
READ_PROMPT = (
    "Найди на этом кропе ТОЛЬКО запись, где имя ребёнка Сергий или Сергей. "
    "Если она здесь есть, перепиши коротко ДОСЛОВНО: имя ребёнка, имя и отчество отца, "
    "имя матери, деревню, дату и номер акта. Не делай выводов из соседних записей "
    "и не додумывай фамилию. Если родителей прочитать нельзя, напиши НРЗБ. "
    "Если записи Сергия здесь нет, напиши НЕТ."
)


def case(book: int, opis: int = 6) -> str:
    return f"ф48_оп{opis}_д{book}"


def probes_path(book: int, opis: int = 6):
    return TEXT / case(book, opis) / "probes.json"


def scan_dir(book: int, opis: int = 6):
    return finder.SCANS / case(book, opis)   # сканы — вне проекта (paths.GASO_RAW)


def parsed(response: str | None) -> dict:
    """Только числа и слова-ярлыки из ответа модели «ГОД: …; РАЗДЕЛ: …» — без имён, годится в каталог."""
    if not response:
        return {}
    field = lambda name: (m[1].strip() if (m := re.search(rf"{name}\s*:\s*([^;\n]*)", response, re.I)) else "")
    out = {}
    if year := re.fullmatch(r"(1[789]\d\d)", field("ГОД")):
        out["year"] = int(year[1])
    section = field("РАЗДЕЛ").lower()
    for stem, name in SECTIONS.items():
        if section.startswith(stem):
            out["section"] = name
    month = field("МЕСЯЦ").lower()
    for number, stem in enumerate(MONTHS, 1):
        if month.startswith(stem) and (stem != "ма" or month.startswith(("май", "мая"))):
            out["month"] = number
    if (acts := field("АКТЫ")) and re.fullmatch(r"[\d\s,–-]+", acts):
        out["acts"] = re.sub(r"\s+", " ", acts).strip()
    if folio := re.fullmatch(r"(\d+(?:\s*об\.?)?)", field("ЛИСТ")):
        out["folio"] = folio[1]
    return out


def load(book: int, opis: int = 6) -> dict:
    """Дело как раньше одним словарём: files (номер → имя копии) и anchors (каталог + слова модели)."""
    name = case(book, opis)
    info = archives.book("gaso", name)
    if not info:
        raise FileNotFoundError(f"Дела {name} нет в каталоге {archives.CATALOG / 'gaso'}; "
                                f"скачать — навык archive-gaso, затем catalog --book {book}")
    rows = archives.pages(name)
    stored = probes_path(book, opis)
    probes = json.loads(stored.read_text(encoding="utf-8")) if stored.exists() else {}
    anchors = {}
    for number, row in rows.items():
        check = {k: v for k, v in row.get("check", {}).items() if k in CHECK_KEYS}
        if check or str(number) in probes:
            anchors[str(number)] = {"sha256": row["sha256"], **check, **probes.get(str(number), {})}
    return {"version": 1, "fond": 48, "opis": opis, "book": book, "anchors": anchors,
            "files": {str(n): archives.local_name(info, n) for n in sorted(rows)}}


def store(book: int, opis: int, data: dict) -> None:
    """Обратно: статус и разобранное — в строки каталога (git), слова модели — в text/ (только этот Mac)."""
    name = case(book, opis)
    rows = archives.pages(name)
    probes = {}
    for number, anchor in data["anchors"].items():
        row = rows.get(int(number))
        if row is None or anchor["sha256"] != row["sha256"]:
            raise RuntimeError(f"{name}, файл {number}: нет в каталоге или сумма другая — индекс не записан")
        check = {k: anchor[k] for k in CHECK_KEYS if anchor.get(k) is not None}
        if proposal := parsed(anchor.get("response")):
            check["proposed"] = proposal
        if header := parsed(anchor.get("header_response")):
            check["proposed_header"] = header
        row["check"] = check
        if text := {k: anchor[k] for k in TEXT_KEYS if k in anchor}:
            probes[number] = text
    archives.write_pages(name, rows)
    if probes:
        flow.save(probes_path(book, opis), dict(sorted(probes.items(), key=lambda item: int(item[0]))))


def catalog(book: int, opis: int = 6) -> dict:
    """Опись дела по копии на этом Mac (archives.py build): суммы опорных файлов должны совпасть."""
    archives.build_gaso(case(book, opis))
    if not archives.book("gaso", case(book, opis)):
        finder.scans()
        raise FileNotFoundError(f"Нет дела ф48 оп. {opis} д. {book}: {scan_dir(book, opis)}")
    return load(book, opis)


def fingerprint(image) -> str:
    return hashlib.sha256(image.read_bytes()).hexdigest()


def sample(data: dict, count: int) -> list[int]:
    if not 1 <= count <= 20:
        raise ValueError("1–20 опорных страниц за один план")
    available = [int(n) for n in data["files"] if n not in data["anchors"]]
    if len(available) <= count:
        return available
    if count == 1:
        return [available[len(available) // 2]]
    return [available[i * (len(available) - 1) // (count - 1)] for i in range(count)]


def selected(value: str) -> list[int]:
    if not re.fullmatch(r"\d+(,\d+)*", value):
        raise argparse.ArgumentTypeError("передайте номера файлов через запятую: 60,100")
    numbers = list(dict.fromkeys(int(x) for x in value.split(",")))
    if not 1 <= len(numbers) <= 20 or min(numbers) < 1:
        raise argparse.ArgumentTypeError("от 1 до 20 разных положительных номеров")
    return numbers


def full_crop(image) -> tuple[int, int, int, int]:
    result = subprocess.run(
        ["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(image)],
        check=True, capture_output=True, text=True,
    ).stdout
    width = re.search(r"pixelWidth:\s*(\d+)", result)
    height = re.search(r"pixelHeight:\s*(\d+)", result)
    if not width or not height:
        raise RuntimeError(f"Не определён размер изображения: {image}")
    return (0, 0, int(width[1]), int(height[1]))


def probe(book: int, opis: int, pages: list[int], run: bool, header: bool = False) -> None:
    data = load(book, opis)
    scans = []
    for number in pages:
        name = data["files"].get(str(number))
        if not name:
            raise FileNotFoundError(f"Нет файла {number} в д. {book}; обновите catalog")
        scans.append((number, scan_dir(book, opis) / name))
    print(f"Д. {book}, оп. {opis}; {len(scans)} локальных проб; "
          f"сегодня выполнено: {flow.used_today()}; дневного лимита нет; облако: нет")
    if not run:
        print("Это план, модель не вызвана. Для запуска добавьте --run.")
        return
    def settings(image):
        crop = full_crop(image)
        return ((0, 0, crop[2], min(480, crop[3])), HEADER_PROMPT) if header else (crop, PROMPT)

    for number, image in scans:
        crop, prompt = settings(image)
        answer = flow.model_call(f"index-{opis}-{book}", image, crop, prompt)
        record = data["anchors"].setdefault(str(number), {
            "sha256": fingerprint(image), "state": "proposed", "model": finder.MODEL,
        })
        if record["sha256"] != fingerprint(image):
            raise RuntimeError(f"Скан {number} изменён после первого просмотра")
        record["header_response" if header else "response"] = answer
        store(book, opis, data)
        print(f"Файл {number} [НЕ ПРОВЕРЕНО; {'верх' if header else 'весь разворот'}]: {answer}", flush=True)


def verify(args) -> None:
    data = load(args.book, args.opis)
    name = data["files"].get(str(args.page))
    if not name:
        raise FileNotFoundError(f"Нет скана {args.page} в каталоге")
    image = scan_dir(args.book, args.opis) / name
    existing = data["anchors"].get(str(args.page), {})
    if existing and existing["sha256"] != fingerprint(image):
        raise RuntimeError("Скан изменился с момента пробы")
    if not args.checked_original:
        raise ValueError("Проверенная опора требует --checked-original")
    data["anchors"][str(args.page)] = {
        **existing, "sha256": fingerprint(image), "state": "verified",
        "year": args.year, "section": args.section, "month": args.month,
        "folio": args.folio, "acts": args.acts, "evidence": args.evidence,
    }
    store(args.book, args.opis, data)
    print(f"Проверено: д. {args.book}, файл {args.page}, {args.year}, {args.section}")


def read_candidate(book: int, opis: int, page: int, crop: tuple[int, int, int, int], run: bool) -> None:
    data = load(book, opis)
    name = data["files"].get(str(page))
    if not name:
        raise FileNotFoundError(f"Файл {page} не найден в каталоге")
    image = scan_dir(book, opis) / name
    print(f"Целевой акт: д. {book}, файл {page}, кроп {crop}; модель локальная, результат непроверенный")
    if not run:
        print("Добавьте --run после проверки расположения записи.")
        return
    answer = flow.model_call(f"read-{opis}-{book}", image, crop, READ_PROMPT)
    anchor = data["anchors"].setdefault(str(page), {
        "sha256": fingerprint(image), "state": "proposed", "model": finder.MODEL,
    })
    if anchor["sha256"] != fingerprint(image):
        raise RuntimeError("Исходный скан изменился после индексации")
    anchor["candidate_read"] = {"response": answer, "crop": crop, "prompt": READ_PROMPT}
    store(book, opis, data)
    print("НЕПРОВЕРЕННАЯ подсказка:\n" + answer)


def locate(book: int, opis: int, year: int, section: str) -> None:
    data = load(book, opis)
    verified = [
        (int(n), a) for n, a in data["anchors"].items()
        if a.get("state") == "verified" and a.get("year") == year and a.get("section") == section
    ]
    if not verified:
        print("Нет проверенных опор для года/раздела; отсутствие записей не установлено.")
    for number, anchor in sorted(verified):
        print(f"Файл {number}, месяц {anchor.get('month') or '?'}, акты {anchor.get('acts') or '?'}, "
              f"лист {anchor.get('folio') or '?'}; {anchor.get('evidence')}")
    print("Между опорами могут быть вклейки/смена раздела; НЕ исключать неразмеченные страницы.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("catalog", "sample", "probe", "verify", "locate", "read"):
        part = sub.add_parser(command)
        if command == "catalog":
            scope = part.add_mutually_exclusive_group(required=True)
            scope.add_argument("--book", type=int)
            scope.add_argument("--all", action="store_true", help="опись всех локальных дел без чтения JPG")
        else:
            part.add_argument("--book", type=int, required=True)
        part.add_argument("--opis", type=int, default=6)
        if command == "sample":
            part.add_argument("--count", type=int, default=8)
        if command == "probe":
            part.add_argument("--pages", type=selected, required=True)
            part.add_argument("--header", action="store_true", help="независимое чтение только верхней части")
            part.add_argument("--run", action="store_true")
        if command == "verify":
            part.add_argument("--page", type=int, required=True)
            part.add_argument("--checked-original", action="store_true")
            part.add_argument("--year", type=int, required=True)
            part.add_argument("--section", choices=("births", "marriages", "deaths", "other"), required=True)
            part.add_argument("--month", type=int, choices=range(1, 13))
            part.add_argument("--folio")
            part.add_argument("--acts")
            part.add_argument("--evidence", required=True)
        if command == "read":
            part.add_argument("--page", type=int, required=True)
            part.add_argument("--crop", type=finder.crop_arg, required=True)
            part.add_argument("--run", action="store_true")
        if command == "locate":
            part.add_argument("--year", type=int, required=True)
            part.add_argument("--section", choices=("births", "marriages", "deaths", "other"), required=True)
    args = parser.parse_args()
    try:
        dispatch(args)
    except NoRaw as exc:
        sys.exit(str(exc))


def dispatch(args):
    with flow.flow_lock():
        if args.command == "catalog":
            directories = (
                sorted(finder.scans().glob("ф48_оп*_д*"))
                if args.all else [scan_dir(args.book, args.opis)]
            )
            total = 0
            for directory in directories:
                match = re.fullmatch(r"ф48_оп(\d+)_д(\d+)", directory.name)
                if not match or not directory.is_dir():
                    raise ValueError(f"Неизвестное дело в архиве: {directory}")
                opis, book = map(int, match.groups())
                data = catalog(book, opis)
                numbers = [int(n) for n in data["files"]]
                total += len(numbers)
                gaps = max(numbers) - min(numbers) + 1 - len(numbers)
                print(f"Оп. {opis}, д. {book}: {len(numbers)} JPG, файлы "
                      f"{min(numbers)}–{max(numbers)}, отсутствуют локальные номера {gaps}, "
                      f"проверенных опор {sum(a.get('state') == 'verified' for a in data['anchors'].values())}")
            print(f"ИТОГО: {len(directories)} дел, {total} JPG; пропуски номеров НЕ равны утраченным листам")
        elif args.command == "sample":
            data = load(args.book, args.opis)
            for number in sample(data, args.count):
                print(f"{number}: {scan_dir(args.book, args.opis) / data['files'][str(number)]}")
        elif args.command == "probe":
            probe(args.book, args.opis, args.pages, args.run, args.header)
        elif args.command == "verify":
            verify(args)
        elif args.command == "read":
            read_candidate(args.book, args.opis, args.page, args.crop, args.run)
        else:
            locate(args.book, args.opis, args.year, args.section)


if __name__ == "__main__":
    main()
