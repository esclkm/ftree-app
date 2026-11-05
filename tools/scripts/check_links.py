#!/usr/bin/env python3
"""Проверка ссылок внутри проекта: какие ссылки ведут на несуществующий файл.

Три вида ссылок:
  1. markdown и html: [текст](путь), ![фото](путь), src="путь", href="путь" — путь от файла;
  2. Obsidian: [[Имя заметки]], [[файл.jpg]], [[<папка поиска>/…md]] — по имени где угодно
     в хранилище или путь от корня проекта (весь проект — одно хранилище Obsidian);
  3. пути от корня проекта в `обратных кавычках`: `1_sources/…`, `tools/scripts/…`;
  4. сырьё архивов вне проекта, только на этом Mac: `$ARCHIVES_LOCAL/raw/…` и `…/text/…`
     (paths.ARCHIVES_LOCAL; другие пути в этой папке — планы, не проверяем).
     Файл там есть — ссылка цела; нет файла — битая; нет всей папки архивов (другой компьютер) — «не проверено».

Запуск:  python3 tools/scripts/check_links.py          # сводка + список битых
         python3 tools/scripts/check_links.py --quiet  # только числа
"""
import os
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import unquote

import paths
from paths import ARCHIVES_HOME, ARCHIVES_LOCAL, ROOT, archive_path, rel

SKIP = (rel(paths.SITE), rel(paths.SITE_EXPORT), "tools/tree-viewer", rel(paths.AI_WEIGHTS), rel(paths.GRAMPS_ARCHIVE), ".git", ".obsidian", ".wbh-profile",
        ".claude/worktrees", rel(paths.SOCIAL_EXPORT), "node_modules", "web/node_modules", "web/dist",
        rel(paths.CACHE))   # tools/.cache — виртуальные окружения пакетов, не наши файлы
NO_CHECK = (rel(paths.TEMPLATES) + "/", rel(paths.DOSSIERS) + "/", rel(paths.SEARCH / "_archive"),
            "tools/init_template/")  # есть, но не проверяем; init_template — образец для нового дерева, его пути — не наши
TOP = (*(rel(p) + "/" for p in (paths.SOURCES, paths.TRANSCRIPTS, paths.RESEARCH, paths.OUTPUTS)), "tools/")

LINK = re.compile(r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)|(?:src|href)=\"([^\"]+)\"|<<IMG:([^|>]+)")  # <<IMG:путь|подпись>> — картинки в книгах
WIKI = re.compile(r"\[\[([^\]|#^\n]+)(?=[\]|#^])")   # через перенос строки — не ссылка
TICK = re.compile(r"`([^`\n]+)`")
N = lambda s: unicodedata.normalize("NFC", s)
OUTSIDE = {"есть": 0, "не проверено": 0}   # ссылки на сырьё вне проекта (п. 4)


def outside(s):
    """`$ARCHIVES_LOCAL/…` — есть ли файл на этом Mac. True/False; None — папки архивов тут нет."""
    if not ARCHIVES_LOCAL.is_dir():
        return None
    target = archive_path(s.rstrip("/"))
    return target.exists() or Path(unicodedata.normalize("NFD", str(target))).exists()


APP = paths.APP.resolve()
# код — в приложении (tools/, web/, навыки), когда оно отдельно от дерева: дерево ссылается на него теми же путями от
# корня, что и до раздела; файлы приложения — цели ссылок, их самих не проверяем
APP_TOPS = ("tools", "web", ".claude", ".github") if APP != ROOT.resolve() else ()


def index():
    """→ (имена, пути дерева, пути приложения) — пути от корня."""
    names, own, app = set(), set(), set()
    _walk(ROOT, ROOT, names, own)
    for top in APP_TOPS:
        if (APP / top).is_dir():
            _walk(APP / top, APP, names, app)
    return names, own, app


def _walk(start, base, names, paths):
    for d, ds, fs in os.walk(start):
        r = os.path.relpath(d, base)
        if r.startswith(SKIP):
            ds[:] = []
            continue
        for f in fs:
            p = N(os.path.normpath(os.path.join(r, f)))
            paths.add(p)
            names.add(N(f))
            names.add(N(os.path.splitext(f)[0]))
        for x in ds:
            paths.add(N(os.path.normpath(os.path.join(r, x))))


def broken(f, names, paths):
    raw = N(f.read_text(encoding="utf-8", errors="replace"))
    # примеры в коде (`…`, ```…```) — не ссылки; пути в `обратных кавычках` проверяются отдельно ниже
    text = re.sub(r"```.*?```|`[^`\n]*`", "", raw, flags=re.S)
    here = N(os.path.relpath(f.parent, ROOT))
    out = []
    for m in LINK.finditer(text):
        t = (m.group(1) or m.group(2) or m.group(3)).strip()
        if re.match(r"^(https?:|mailto:|data:|#|file:|tel:|app:|obsidian:)", t) or "{" in t or "<" in t:
            continue
        t = unquote(t.split("#")[0].split("?")[0])
        if t and os.path.normpath(os.path.join(here, t)) not in paths:
            out.append(t)
    if f.suffix == ".md":
        for t in WIKI.findall(text):
            t = t.strip().rstrip("\\")
            if "…" in t:   # [[…]] — пример в тексте
                continue
            if t in names or os.path.basename(t) in names or os.path.normpath(t) in paths \
                    or os.path.normpath(t) + ".md" in paths:
                continue
            out.append(f"[[{t}]]")
    for m in re.finditer(r"`(\.\./[^`\n]+)`", raw):     # `../папка/файл` — путь от файла
        s = m.group(1).strip()
        if " " not in s and "*" not in s and "<" not in s and "…" not in s and "..." not in s[3:] \
                and os.path.normpath(os.path.join(here, unquote(s))) not in paths:   # «Doc31_…» — сокращение, не путь
            out.append(s)
    for m in TICK.finditer(raw):
        s = m.group(1).strip()
        if s.startswith(ARCHIVES_HOME + "/"):   # сырьё и текст — проверяем; прочее там (`_tmp/`, профиль браузера) — нет
            if not s.startswith((ARCHIVES_HOME + "/raw/", ARCHIVES_HOME + "/text/")) or any(c in s for c in "*<…{"):   # шаблоны имён — не путь
                continue
            found = outside(s)
            if found is False:
                out.append(s)
            else:
                OUTSIDE["есть" if found else "не проверено"] += 1
            continue
        if s.startswith(TOP) and not any(c in s for c in " *<…") and "..." not in s \
                and os.path.normpath(s) not in paths \
                and not (s.startswith(SKIP) and (ROOT / s).exists()):   # папки из SKIP не в индексе — смотрим на диск
            out.append(s)
    return out


def main():
    names, own, app = index()
    paths = own | app
    total, rows = 0, []
    for p in sorted(own):
        # шаблоны состоят из заглушек {{…}} — их не проверяем, но файлы шаблонов существуют
        if not p.endswith((".md", ".html")) or p.startswith(SKIP) or "/_chunks/" in p \
                or p.startswith(NO_CHECK) or (p.startswith(TOP[0]) and p.endswith(".html")):
            continue  # .html в 1_sources — сохранённые страницы чужих сайтов: их ссылки вели на тот сайт
        b = broken(ROOT / p, names, paths)
        if b:
            total += len(b)
            rows.append((p, b))
    if "--quiet" not in sys.argv:
        for r, b in rows:
            print(f"{r}  ({len(b)})")
            for t in b[:8]:
                print(f"    → {t}")
    print(f"Битых ссылок: {total} в {len(rows)} файлах")
    if any(OUTSIDE.values()):
        print(f"Сырьё вне проекта ({ARCHIVES_HOME}, только на этом Mac): есть {OUTSIDE['есть']}"
              + (f", не проверено {OUTSIDE['не проверено']} — нет папки {ARCHIVES_LOCAL}" if OUTSIDE["не проверено"] else ""))


if __name__ == "__main__":
    main()
