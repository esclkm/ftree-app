#!/usr/bin/env python3
"""Переписать в документах вызовы скриптов по пути на одну команду `rodo <имя>`.

Зачем: после раздела проекта на данные и приложение путь `tools/scripts/x.py` в документах сломается, а `rodo x`
останется верным (rodo сам знает, где лежат скрипты). Переписывает только тексты .md — код не трогает.

Что считается командой и как переписывается:
  tools/py tools/scripts/x.py …      → rodo x …
  python3 tools/scripts/x.py …       → rodo x …
  ./tools/scripts/x.py …             → rodo x …
  node tools/scripts/x.mjs …         → rodo x …
  sh tools/scripts/x.sh …            → rodo x …
  `tools/scripts/x.py аргументы`     → `rodo x аргументы`   (путь в начале кода в обратных кавычках, за ним слова)
  tools/scripts/x.py аргументы       → rodo x аргументы     (в блоке кода ``` — в начале строки или после && ; |)
  tools/py -m unittest discover … tools/scripts/tests …  → rodo test
Имя — через дефис: check_cards.py → rodo check-cards.

Что остаётся как есть — речь о самом файле, а не о команде:
  `tools/scripts/x.py` один в кавычках («пути — `tools/scripts/paths.py`», «впиши в таблицу в …»);
  путь с другим Python (`~/.relatives_ai_venv/bin/python tools/scripts/…`), `git show :tools/scripts/…`, `grep … tools/scripts/…`;
  папки (`tools/scripts/cards/`, `tools/scripts/tests/…`), не-скрипты (.swift, .js, .pem);
  скрипт, которого уже нет в tools/scripts (старые отчёты) — показывается отдельно.

Не трогает: 1_sources/ (оригиналы), карточки и биографии (3_research/tree/people|biographies), файлы,
которые собирает скрипт («руками не править» или «собрано скриптом» в первых 10 строках):
их текст пишет сам скрипт, правка руками пропала бы при пересборке.

Запуск:  rodo rodo-docs              — показать, что поменяется (по файлам и всего)
         rodo rodo-docs --apply      — переписать
         rodo rodo-docs --list-left  — что осталось с tools/scripts/ после правки и почему
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
S = ROOT / "tools" / "scripts"
SKIP_PREFIX = ("1_sources/", "3_research/tree/people/", "3_research/tree/biographies/")
GENERATED = re.compile(r"руками не править|не править руками|руками не правим|собрано скриптом", re.I)

SCRIPTS = {p.name for p in S.iterdir() if p.suffix in (".py", ".mjs", ".sh") and not p.name.startswith("_")}

NAME = r"(?P<name>[A-Za-z0-9_]+)\.(?P<ext>py|mjs|sh)"
# 1) с явным запускателем
RUNNER = re.compile(r"(?:tools/py|python3|node|sh) tools/scripts/" + NAME + r"|\./tools/scripts/" + NAME.replace("name", "name2").replace("ext", "ext2"))
# 2) тесты
TESTS = re.compile(r"tools/py -m unittest discover(?: -s)? tools/scripts/tests(?: -q)?")
# 3) голый путь в начале `…` и за ним слова до закрывающей кавычки
INLINE = re.compile(r"`tools/scripts/" + NAME + r"(?= [^`\n]+`)")
# 4) голый путь в блоке кода: начало строки или после && ; |
FENCED = re.compile(r"(?P<pre>^[ \t]*|&& |; |\| )tools/scripts/" + NAME + r"(?=[ \n]|$)", re.M)


def dash(n):
    return n.replace("_", "-")


def files():
    out = subprocess.run(["git", "ls-files", "-z", "--", "*.md"], cwd=ROOT, capture_output=True, text=True).stdout
    for rel in out.split("\0"):
        if not rel or rel.startswith(SKIP_PREFIX):
            continue
        p = ROOT / rel
        if p.is_file():
            yield rel, p


def rewrite(text):
    """→ (новый текст, число замен, имена несуществующих скриптов)"""
    n = 0
    missing = []

    def ok(name, ext):
        if f"{name}.{ext}" in SCRIPTS:
            return True
        missing.append(f"{name}.{ext}")
        return False

    def runner(m):
        nonlocal n
        name, ext = (m["name"], m["ext"]) if m["name"] else (m["name2"], m["ext2"])
        if not ok(name, ext):
            return m[0]
        n += 1
        return "rodo " + dash(name)

    def tests(m):
        nonlocal n
        n += 1
        return "rodo test"

    def inline(m):
        nonlocal n
        if not ok(m["name"], m["ext"]):
            return m[0]
        n += 1
        return "`rodo " + dash(m["name"])

    def fenced(m):
        nonlocal n
        if not ok(m["name"], m["ext"]):
            return m[0]
        n += 1
        return m["pre"] + "rodo " + dash(m["name"])

    text = TESTS.sub(tests, text)
    text = RUNNER.sub(runner, text)
    text = INLINE.sub(inline, text)
    # блоки кода ``` — только внутри них
    parts = re.split(r"(^```[^\n]*\n.*?^```)", text, flags=re.M | re.S)
    for i, part in enumerate(parts):
        if part.startswith("```"):
            parts[i] = FENCED.sub(fenced, part)
    return "".join(parts), n, missing


def main():
    apply = "--apply" in sys.argv
    if "--list-left" in sys.argv:
        out = subprocess.run(["git", "grep", "-n", "tools/scripts/", "--", "*.md"], cwd=ROOT,
                             capture_output=True, text=True).stdout
        print(out, end="")
        return
    total, nfiles, gone = 0, 0, {}
    skipped_gen = []
    for rel, p in files():
        text = p.read_text(encoding="utf-8")
        if "tools/scripts/" not in text:
            continue
        if GENERATED.search("\n".join(text.splitlines()[:10])):
            skipped_gen.append(rel)
            continue
        new, n, missing = rewrite(text)
        for m in missing:
            gone.setdefault(m, set()).add(rel)
        if n:
            total += n
            nfiles += 1
            print(f"{n:4}  {rel}")
            if apply:
                p.write_text(new, encoding="utf-8")
    print(f"\n{'Переписано' if apply else 'Будет переписано'}: {total} в {nfiles} файлах.")
    if skipped_gen:
        print("Не тронуты (собирает скрипт): " + ", ".join(skipped_gen))
    if gone:
        print("Скриптов уже нет — ссылки оставлены: " + "; ".join(f"{k} ({len(v)})" for k, v in sorted(gone.items())))
    if not apply and total:
        print("Переписать: rodo rodo-docs --apply")


if __name__ == "__main__":
    main()
