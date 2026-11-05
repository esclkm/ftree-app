#!/usr/bin/env python3
"""Каталог скачанного из архивов: что у нас уже есть, где лежит копия и где оригинал.

Оригинал — всегда в архиве (у ГАСО — разворот на portal.gaso-smolensk.ru, у НЭБ — карточка книги на rusneb.ru).
Копия — в $ARCHIVES_LOCAL (paths.ARCHIVES_LOCAL), только на этом Mac. Между ними — каталог в git
(3_research/archives/catalog/<архив>/): по нему видно, что уже скачано, ещё до захода на сайт архива, и куда идти,
если копии на этом Mac нет. Чужих имён в каталоге нет — только номера, адреса и контрольные суммы.

    tools/py tools/scripts/archives.py have gaso               # все дела: в каталоге / на этом Mac
    tools/py tools/scripts/archives.py have gaso ф48_оп6_д526  # одно дело — перед тем как качать
    tools/py tools/scripts/archives.py where gaso ф48_оп6_д581 72   # копия на Mac или адрес на сервере
    tools/py tools/scripts/archives.py check                   # копии против каталога (размеры; --sha — суммы)
    tools/py tools/scripts/archives.py lint                    # каталог сам с собой: файлов в деле = строк страниц
    tools/py tools/scripts/archives.py build gaso              # каталог по скачанному (после нового скачивания)
"""
import argparse
import hashlib
import json
import re
import sys
import unicodedata
import urllib.parse
from pathlib import Path

from paths import ARCHIVES_HOME, ARCHIVES_RAW, RESEARCH, RUSNEB_RAW, need_raw, tree_conf

CATALOG = RESEARCH / "archives" / "catalog"
GASO_BASE = "https://portal.gaso-smolensk.ru/thumbnails/metrics_smolensky/"
GASO_SITE = "https://portal.gaso-smolensk.ru"

# Каталог дел этого дерева — ftree.toml, раздел [archives]: дела ГАСО — код → (название, папка на сервере, шаблон
# имени разворота, сверен ли шаблон); адрес разворота = папка + имя, {n} — номер файла на сервере (он же в имени нашей
# копии; это НЕ номер листа). Книги НЭБ — код → (название, имя PDF в RUSNEB_RAW); страница книги —
# https://rusneb.ru/catalog/<код>/. Нет раздела — пусто: видно только то, что уже есть в каталоге.
GASO = {k: tuple(v) for k, v in tree_conf("archives.gaso", {}).items()}
RUSNEB = {k: tuple(v) for k, v in tree_conf("archives.rusneb", {}).items()}
N = lambda s: unicodedata.normalize("NFC", s)


def book_path(archive: str, case: str) -> Path:
    return CATALOG / archive / f"{case}.book.json"


def book(archive: str, case: str) -> dict | None:
    path = book_path(archive, case)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _pages_path(case: str) -> Path:
    """Строки дела: ГАСО — catalog/gaso, плёнки FamilySearch (fs_<плёнка>) — catalog/familysearch."""
    fs = CATALOG / "familysearch" / f"{case}.book.json"
    return (fs.parent if fs.exists() else CATALOG / "gaso") / f"{case}.jsonl"


def pages(case: str) -> dict[int, dict]:
    path = _pages_path(case)
    if not path.exists():
        return {}
    rows = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return {row["n"]: row for row in rows}


def write_pages(case: str, rows: dict[int, dict]) -> None:
    """Строки дела в каталог: по файлу на строку, по номеру. «check» — что известно о развороте (gaso_index.py)."""
    path = _pages_path(case)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text("".join(json.dumps(rows[n], ensure_ascii=False) + "\n" for n in sorted(rows)),
                         encoding="utf-8")
    temporary.replace(path)


def gaso_url(case: str, n: int) -> str | None:
    """Адрес разворота на сервере ГАСО (по каталогу, иначе по таблице выше)."""
    info = book("gaso", case) or {}
    folder, name = info.get("folder"), info.get("name_template")
    if not folder and case in GASO:
        _, folder, name, _ = GASO[case]
    if not folder:
        return None
    return GASO_BASE + urllib.parse.quote(folder) + "/" + urllib.parse.quote(name.format(n=n))


def local_name(info: dict, n: int) -> str:
    return info["local_template"].format(n=n)


def locate(case: str, n: int) -> tuple[Path | None, str | None]:
    """Разворот ГАСО: (копия на этом Mac или None, адрес на сервере)."""
    info = book("gaso", case)
    if info:
        local = ARCHIVES_RAW / "gaso" / case / local_name(info, n)
        if local.exists():
            return local, gaso_url(case, n)
    directory = ARCHIVES_RAW / "gaso" / case
    if directory.is_dir():
        for file in directory.glob(f"*_{n:03}.jpg"):
            return file, gaso_url(case, n)
    return None, gaso_url(case, n)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_gaso(only: str | None) -> None:
    root = need_raw(ARCHIVES_RAW / "gaso")
    for directory in sorted(root.iterdir()):
        case = N(directory.name)
        if not directory.is_dir() or (only and case != only):
            continue
        if case not in GASO:
            raise ValueError(f"{case}: нет в ftree.toml, раздел [archives.gaso] — впишите название и шаблон адреса с сервера")
        title, folder, name, checked = GASO[case]
        files = {}
        for file in directory.glob("*.jpg"):
            match = re.fullmatch(r"(.+_)(\d{3})\.jpg", N(file.name))
            if not match:
                raise ValueError(f"Неизвестное имя файла: {file}")
            files[int(match[2])] = (match[1], file)
        prefixes = {prefix for prefix, _ in files.values()}
        if len(prefixes) != 1:
            raise ValueError(f"{case}: разные начала имён файлов {sorted(prefixes)} — каталогу нужно одно")
        old = pages(case)
        rows = []
        for n in sorted(files):
            file = files[n][1]
            row = {**old.get(n, {}), "n": n, "sha256": sha(file), "bytes": file.stat().st_size}  # «check» — сохраняем
            if n in old and old[n]["sha256"] != row["sha256"]:
                raise RuntimeError(f"{case}, файл {n} изменён: копия не совпадает с каталогом — каталог не переписан")
            rows.append(row)
        fond, opis, delo = map(int, re.fullmatch(r"ф(\d+)_оп(\d+)_д(\d+)", case).groups())
        (CATALOG / "gaso").mkdir(parents=True, exist_ok=True)
        info = {
            "version": 1, "archive": "ГАСО (Государственный архив Смоленской области)", "site": GASO_SITE,
            "fond": fond, "opis": opis, "delo": delo, "title": title,
            "folder": folder, "name_template": name, "url_checked": checked,
            "local": f"{ARCHIVES_HOME}/raw/gaso/{case}/", "local_template": prefixes.pop() + "{n:03d}.jpg",
            "files": len(rows), "first": rows[0]["n"], "last": rows[-1]["n"],
            "bytes": sum(r["bytes"] for r in rows), "downloaded": "2026-10-01",
            "access": "абонемент «Удалённое использование» (платный час), навык archive-gaso",
        }
        book_path("gaso", case).write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_pages(case, {r["n"]: r for r in rows})
        print(f"{case}: {len(rows)} файлов, {info['bytes'] / 2**20:.0f} МБ")


def build_rusneb() -> None:
    root = need_raw(RUSNEB_RAW)
    (CATALOG / "rusneb").mkdir(parents=True, exist_ok=True)
    for code, (title, name) in RUSNEB.items():
        file = root / name
        info = {"version": 1, "archive": "НЭБ (Национальная электронная библиотека)",
                "site": f"https://rusneb.ru/catalog/{code}/", "code": code, "title": title,
                "local": f"{ARCHIVES_HOME}/raw/{RUSNEB_RAW.name}/{name}", "sha256": sha(file),
                "bytes": file.stat().st_size, "downloaded": RUSNEB_RAW.name.split("_")[-1],
                "access": "сайт открыт только из России — навык archive-rusneb"}
        book_path("rusneb", code).write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{code}: {title}, {info['bytes'] / 2**20:.0f} МБ")


def have(archive: str, case: str | None) -> None:
    books = sorted((CATALOG / archive).glob("*.book.json"))
    if case:
        books = [b for b in books if b.name == f"{case}.book.json"]
        if not books:
            print(f"{case}: в каталоге нет — значит, не скачивали. Качать по навыку archive-{archive}.")
            return
    for path in books:
        info = json.loads(path.read_text(encoding="utf-8"))
        local = Path(info["local"].replace(ARCHIVES_HOME, str(ARCHIVES_RAW.parent), 1))
        if archive == "gaso":
            here = len(list(local.glob("*.jpg"))) if local.is_dir() else 0
            state = "все на этом Mac" if here == info["files"] else f"на этом Mac {here}"
            print(f"{path.name[:-10]}: {info['title']}; скачано {info['downloaded']}: {info['files']} файлов "
                  f"({info['first']}–{info['last']}); {state}")
        else:
            print(f"{info['code']}: {info['title']}; {'есть на этом Mac' if local.exists() else 'на этом Mac нет'}"
                  f" — {info['site']}")


def where(case: str, n: int) -> None:
    local, url = locate(case, n)
    if local:
        print(local)
    else:
        print(f"на этом Mac нет; на сервере ГАСО: {url or '? (нет в каталоге)'}")
        print("  открыть сканы можно только при действующем абонементе — навык archive-gaso")


def lint() -> list[str]:
    """Каталог сам с собой (без сканов, годится для проверок на GitHub): у каждого дела ГАСО число файлов в .book.json —
    столько же, сколько строк страниц."""
    out = []
    for path in sorted((CATALOG / "gaso").glob("*.book.json")):
        case = path.name[:-10]
        info = json.loads(path.read_text(encoding="utf-8"))
        rows = pages(case)
        if rows and info.get("files") != len(rows):
            out.append(f"{case}: в каталоге files={info.get('files')}, строк страниц {len(rows)}")
    return out


def check(full: bool) -> int:
    problems = 0
    for path in sorted((CATALOG / "gaso").glob("*.book.json")):
        case = path.name[:-10]
        info = json.loads(path.read_text(encoding="utf-8"))
        directory = ARCHIVES_RAW / "gaso" / case
        if not directory.is_dir():
            print(f"{case}: на этом Mac нет")
            problems += 1
            continue
        for n, row in pages(case).items():
            file = directory / local_name(info, n)
            if not file.exists() or file.stat().st_size != row["bytes"] or (full and sha(file) != row["sha256"]):
                print(f"{case}, файл {n}: {'нет' if not file.exists() else 'не совпадает'}")
                problems += 1
    print(f"Сверка копий с каталогом: расхождений {problems}")
    return 1 if problems else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("have"); p.add_argument("archive", choices=("gaso", "rusneb")); p.add_argument("case", nargs="?")
    p = sub.add_parser("where"); p.add_argument("archive", choices=("gaso",)); p.add_argument("case")
    p.add_argument("n", type=int)
    p = sub.add_parser("check"); p.add_argument("--sha", action="store_true")
    sub.add_parser("lint")
    p = sub.add_parser("build"); p.add_argument("archive", choices=("gaso", "rusneb")); p.add_argument("case", nargs="?")
    args = parser.parse_args()
    if args.command == "have":
        have(args.archive, args.case)
    elif args.command == "where":
        where(args.case, args.n)
    elif args.command == "check":
        return check(args.sha)
    elif args.command == "lint":
        problems = lint()
        print("\n".join(problems) or "Каталог архивов: расхождений 0")
        return 1 if problems else 0
    elif args.archive == "gaso":
        build_gaso(args.case)
    else:
        build_rusneb()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        sys.exit(str(exc))
