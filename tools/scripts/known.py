#!/usr/bin/env python3
"""Что мы уже знаем — найти человека или факт во всём, что проект уже собрал, ДО того, как назвать его находкой.

Зачем. Одни и те же люди уже описаны в отчётах `findings/`, плане поиска, карточках и расшифровках, но часто без
своей карточки — `tree.py mentions` их не видит. Без этой сверки старое выдаётся за «нашлось» (09.10.2026: двое
братьев «нашлись», хотя были в отчёте 30.09).

Как ищет. Каждое слово запроса — основа (без окончания, первые 5 букв, «ё» = «е»); строка подходит, если в ней есть
все основы. Так «Прокоп Ясенев» найдёт и «Прокопа Ясенева», а «Прокопа Ясинева» не найдёт — поэтому варианты написания даём
отдельно через `|`: «Прокоп Ясен|Прокоп Ясин|Прокоп Есен».

    tools/py tools/scripts/known.py "Прокоп Ясен|Прокоп Ясин"        # где уже есть
    tools/py tools/scripts/known.py "Иван Ясенев 1878" --all         # все строки, не только первые 3 на файл
    tools/py tools/scripts/known.py "Ясенев" "Wierzbowska" "Дубняк"  # несколько запросов разом

Ответ: по каждому запросу — файлы (сначала отчёты и план, потом карточки и расшифровки), в каждом — номер строки и
кусок текста. «Нигде» — значит, действительно новое.
"""
import re, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import paths  # noqa: E402

ROOT = paths.ROOT
WHERE = [  # (папка, подпись) — по порядку важности для сверки
    (paths.PAVEL, "поиск и отчёты"),
    (paths.PEOPLE, "карточки"),
    (paths.TREE_SOURCES, "источники"),
    (paths.BIOS, "биографии"),
    (paths.TRANSCRIPTS, "расшифровки"),
    (paths.FOUND, "найдено (выписки)"),
    (paths.INBOX, "входящие"),
    (paths.OUTPUTS_PAVEL, "анкеты и выдача"),
]
EXT = {".md", ".txt", ".tsv", ".csv"}


def norm(s: str) -> str:
    return s.lower().replace("ё", "е")


def stems(q: str):
    return [norm(w)[:5] for w in re.findall(r"[\wА-Яа-яЁё]+", q) if len(w) > 1]


def search(query: str, show_all=False, per_file=3):
    variants = [stems(v) for v in query.split("|") if v.strip()]
    hits = []
    for folder, label in WHERE:
        base = ROOT / folder
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if p.suffix not in EXT or not p.is_file():
                continue
            try:
                lines = p.read_text(encoding="utf-8").splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            found = []
            for n, line in enumerate(lines, 1):
                low = norm(line)
                if any(all(s in low for s in v) for v in variants):
                    found.append((n, line.strip()))
            if found:
                hits.append((label, p.relative_to(ROOT), found))
    return hits


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    show_all = "--all" in sys.argv
    if not args:
        print(__doc__)
        sys.exit(1)
    for q in args:
        hits = search(q)
        total = sum(len(f) for _, _, f in hits)
        print(f"\n=== «{q}» — файлов {len(hits)}, строк {total}" + ("  → НИГДЕ: новое" if not hits else ""))
        for label, rel, found in hits:
            print(f"  [{label}] {rel}")
            for n, line in (found if show_all else found[:3]):
                print(f"      {n}: {line[:160]}")
            if not show_all and len(found) > 3:
                print(f"      … ещё {len(found) - 3}")


if __name__ == "__main__":
    main()
