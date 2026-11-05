#!/usr/bin/env python3
"""Ссылки на заголовки — [[Прокоп Ясенев — биография.md#Почему остался]] — не должны рваться.

Зачем. Карточка человека встраивает свой раздел биографии по ЗАГОЛОВКУ. Переименовали заголовок в биографии —
ссылка ведёт в пустоту, и рассказ о человеке молча пропадает с сайта, из переводов и из «Рассказа» в карточке.
check_links.py такие ссылки не видит: файл-то на месте.

  check        — найти ссылки на несуществующие заголовки (код 1, если есть);
  fix          — заголовки, переименованные после последнего коммита, → поправить ссылки на них;
  fix-staged   — для pre-commit: то же по заголовкам, переименованным в этом коммите, + добавить исправления в коммит.

Переименование узнаём по git: в старой и новой версии файла заголовки сравниваются по порядку; заголовок,
который стоял на том же месте, — новое имя старого. Если раздел удалён, а не переименован, — только сообщаем.

Запуск:  python3 tools/scripts/anchors.py check
"""
import difflib
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

import paths
from paths import ROOT, rel  # корень дерева — папка с ftree.toml (paths.find_root)
N = lambda s: unicodedata.normalize("NFC", s)
SCAN = tuple(map(rel, (paths.RESEARCH, paths.OUTPUTS, paths.TRANSCRIPTS)))
SKIP = (rel(paths.SITE) + "/", rel(paths.SITE_EXPORT) + "/", "/_generated/", rel(paths.DOSSIERS) + "/", rel(paths.TEMPLATES) + "/")
NESTED = re.compile(r"\[\[([^\[\]]+?)\s*\[\[[^\]]*\]\]([^\[\]]*)\]\]")   # как в site_export.py
LINK = re.compile(r"(!?\[\[)([^\]|#\n]+)#([^\]|\n^][^\]|\n]*)(\|[^\]\n]*)?\]\]")
HEAD = re.compile(r"^#+\s+(.+?)\s*$", re.M)


def plain(h):
    """Заголовок без разметки — так его сравнивают сайт и Obsidian."""
    return re.sub(r"\s+", " ", re.sub(r"\[\[[^\]]*\]\]|[\[\]*_`]", "", N(h))).strip()


def git(*args, check=False):
    r = subprocess.run(["git", "-c", "core.quotePath=false", *args], cwd=ROOT, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 or not check else None


def md_files():
    for top in SCAN:
        for p in (ROOT / top).rglob("*.md"):
            rel = N(p.relative_to(ROOT).as_posix())
            if not any(s in "/" + rel for s in SKIP):
                yield rel, p


class Index:
    def __init__(self):
        self.files = dict(md_files())
        self.by_stem = {}
        for rel in self.files:
            self.by_stem.setdefault(Path(rel).stem, rel)
        self.heads = {}

    def resolve(self, target, here):
        t = N(target).strip().removesuffix(".md")
        for cand in (t + ".md", N((Path(here).parent / (t + ".md")).as_posix())):
            if cand in self.files:
                return cand
        return self.by_stem.get(t.split("/")[-1])

    def headings(self, rel):
        if rel not in self.heads:
            self.heads[rel] = {plain(h) for h in HEAD.findall(N(self.files[rel].read_text(encoding="utf-8")))}
        return self.heads[rel]


def links(text):
    """Ссылки на заголовок: (начало, конец, файл, [части заголовка]). Вложенные [[…[[…]]…]] — как на сайте."""
    flat = NESTED.sub(lambda m: "[[" + m.group(1) + " " + m.group(2) + "]]", text) if "[[" in text else text
    if flat != text:  # вложенные ссылки меняют длину строки — позиции берём только из «плоских» строк
        return [(None, None, m.group(2), m.group(3).split("#")) for m in LINK.finditer(flat)]
    return [(m.start(3), m.end(3), m.group(2), m.group(3).split("#")) for m in LINK.finditer(text)]


def broken(ix=None):
    """[(файл со ссылкой, файл-цель, заголовок)] — заголовка в цели нет."""
    ix = ix or Index()
    out = []
    for rel, p in ix.files.items():
        text = N(p.read_text(encoding="utf-8"))
        if "#" not in text or "[[" not in text:
            continue
        for _, _, target, parts in links(text):
            dest = ix.resolve(target, rel)
            if not dest:
                continue  # нет самого файла — это забота check_links.py / moves.py
            for part in parts:
                if part.strip() and plain(part) not in ix.headings(dest):
                    out.append((rel, dest, part.strip()))
    return out


def renames(old, new):
    """Старые и новые заголовки файла → {старый: новый} для тех, что стоят на одном месте."""
    a, b = [plain(h) for h in HEAD.findall(N(old))], [plain(h) for h in HEAD.findall(N(new))]
    out = {}
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "replace" and i2 - i1 == j2 - j1:
            out.update({x: y for x, y in zip(a[i1:i2], b[j1:j2]) if x not in b})
    return out


def fix(staged):
    changed = git("diff", "--cached" if staged else "HEAD", "--name-only", "--diff-filter=M", "--", "*.md").splitlines()
    maps = {}
    for rel in map(N, changed):
        old = git("show", f"HEAD:{rel}", check=True)
        new = git("show", f":{rel}", check=True) if staged else (ROOT / rel).read_text(encoding="utf-8")
        if old is not None and new is not None:
            m = renames(old, new)
            if m:
                maps[rel] = m
    if not maps:
        return 0
    ix, fixed = Index(), set()
    for rel, p in ix.files.items():
        text = N(p.read_text(encoding="utf-8"))
        if "[[" not in text:
            continue
        new_text = text
        for a, b, target, parts in sorted(links(text), key=lambda x: x[0] or 0, reverse=True):
            dest = ix.resolve(target, rel)
            if a is None or dest not in maps:
                continue
            m = maps[dest]
            if any(plain(x) in m for x in parts):
                repl = "#".join(m.get(plain(x), x) for x in parts)
                new_text = new_text[:a] + repl + new_text[b:]
        if new_text != text:
            p.write_text(new_text, encoding="utf-8")
            fixed.add(rel)
    if fixed:
        if staged:
            git("add", "--", *sorted(fixed))
        print(f"Ссылки на переименованные заголовки поправлены в {len(fixed)} файлах: " + ", ".join(sorted(fixed)[:8]))
    return len(fixed)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd in ("fix", "fix-staged"):
        fix(cmd == "fix-staged")
    bad = broken()
    for rel, dest, head in bad[:40]:
        print(f"  {rel}\n    → {dest} # {head}")
    print(f"Ссылок на несуществующие заголовки: {len(bad)}")
    return 1 if bad and cmd == "check" else 0


if __name__ == "__main__":
    sys.exit(main())
