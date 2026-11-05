#!/usr/bin/env python3
"""Переезды файлов — по истории git, без ручных таблиц.

Git помнит каждое переименование и удаление. Этот скрипт:
  where <старый путь>   — где файл сейчас (цепочка переездов) или в каком коммите удалён и как вернуть;
  table                 — пересобрать 3_research/tree_data/MOVED.csv (все переезды: дата, коммит, было, стало) — для чтения;
  fix [--apply]         — найти ссылки, сломанные переездами, и показать/исправить их по истории git;
  fix-staged            — для pre-commit: файлы, переименованные в этом коммите, → поправить ссылки на них
                          во всех текстах и добавить исправления в коммит.

Ссылки, которые понимает: [текст](путь), src="путь", <<IMG:путь|…>>, [[путь/файл.md]], `путь/от/корня`.
Ссылки по одному имени ([[Прокоп Ясенев]], [[фото.jpg]]) Obsidian ищет сам — их правят, только если файл
переименован (новое имя), а не просто перенесён.

Запуск:  python3 tools/scripts/moves.py where output/rod/61_БИО_Ясеневы.md
         python3 tools/scripts/moves.py fix            # показать
         python3 tools/scripts/moves.py fix --apply    # исправить
"""
import csv
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

import paths
from paths import ROOT  # корень дерева — папка с ftree.toml (paths.find_root)
N = lambda s: unicodedata.normalize("NFC", s)
TEXT = (".md", ".html", ".base", ".canvas", ".csv", ".py", ".sh", ".json")
SKIP = (paths.rel(paths.AI_WEIGHTS), paths.rel(paths.SOCIAL_EXPORT), ".obsidian/plugins",
        paths.rel(paths.GRAMPS_ARCHIVE), paths.rel(paths.TREE_DATA) + "/MOVED")   # история и архив не переписываем


# Старая история проекта, если дерево однажды начали с чистого git, а прежний лежит резервной копией. Переезды ищем
# сначала там, потом в своём git. Где копия — переменная MOVES_REPO или [moves] old_repo в ftree.toml; нет — только свой git.
OLD_REPO = paths.setting_path("MOVES_REPO", "", toml="moves.old_repo") if paths.setting("MOVES_REPO", "", toml="moves.old_repo") else None
OLD = set()   # коммиты из старой истории — у них «вернуть» идёт с git -C <резервная копия>


def git(*args, cwd=ROOT):
    return subprocess.run(["git", "-c", "core.quotePath=false", *args], cwd=cwd,
                          capture_output=True, text=True).stdout


def history():
    """[(дата, коммит, 'R'|'D', было, стало)] по порядку — из git log (старая история, затем своя)."""
    out, cur = [], ("", "")
    log = ("log", "--reverse", "-M30%", "-l0", "--name-status", "--diff-filter=RD", "--format=@@%h %ad", "--date=short")
    old = git(*log, cwd=OLD_REPO) if OLD_REPO and OLD_REPO.resolve() != ROOT.resolve() and (OLD_REPO / ".git").exists() else ""
    OLD.update(l[2:].split(" ", 1)[0] for l in old.splitlines() if l.startswith("@@"))
    for line in (old + "\n" + git(*log)).splitlines():
        if line.startswith("@@"):
            h, d = line[2:].split(" ", 1)
            cur = (d, h)
        elif line.startswith("R"):
            _, a, b = line.split("\t")
            out.append((cur[0], cur[1], "R", N(a), N(b)))
        elif line.startswith("D"):
            out.append((cur[0], cur[1], "D", N(line.split("\t", 1)[1]), ""))
    return out


def resolver(hist=None):
    hist = hist if hist is not None else history()
    moved, deleted = {}, {}
    for d, h, k, a, b in hist:
        if k == "R":
            moved[a] = b
            deleted.pop(b, None)
        else:
            deleted[a] = (d, h)
    # переезд папки: почти все её файлы (≥80 %) уехали в одну и ту же папку с теми же именами
    from collections import Counter, defaultdict
    by_dir = defaultdict(Counter)
    for x, y in moved.items():               # все уровни папок с одинаковым «хвостом» пути
        xa, ya = x.split("/"), y.split("/")
        k = 0
        while k < min(len(xa), len(ya)) - 1 and xa[-1 - k] == ya[-1 - k]:
            k += 1
            by_dir["/".join(xa[:-k])]["/".join(ya[:-k])] += 1
    dirs = {}
    for pa, c in by_dir.items():
        pb, n = c.most_common(1)[0]
        if n >= 0.8 * sum(c.values()) and pb != pa and not pb.startswith(pa + "/"):
            dirs[pa] = pb

    # запасной источник: ручная таблица переездов 26.09.2026 — для того, что git не узнал
    # (папки вне git, удалённые дубли, файлы, переписанные в том же коммите, обмен имён через временное)
    manual = {}
    legacy = paths.MOVED_LEGACY
    if legacy.exists():
        for r in csv.DictReader(open(legacy, encoding="utf-8")):
            manual.setdefault(N(r["было"]), N(r["стало"].split("  (")[0]))

    def where(old):
        new, gone = _where(old)
        if new or old not in manual:
            return new, gone
        return _where(manual[N(old)])

    def _where(old):
        p, seen = N(old).strip("/"), set()
        for _ in range(30):
            if p in seen:
                break
            seen.add(p)
            if p in moved:                       # сам файл переехал
                p = moved[p]
                continue
            if (ROOT / p).exists() or p in deleted:
                break
            parts = p.split("/")                 # иначе — не переехала ли его папка (самая длинная)
            for i in range(len(parts), 0, -1):
                pre = "/".join(parts[:i])
                if pre in dirs:
                    p = dirs[pre] + ("/" + "/".join(parts[i:]) if parts[i:] else "")
                    break
            else:
                break
        if (ROOT / p).exists():
            return p, None
        gone = deleted.get(p)
        return None, (gone + (p,)) if gone else None
    where.split = by_dir
    return where, moved


LINK = re.compile(r"(\]\()([^)\s]+)((?:\s+\"[^\"]*\")?\))|((?:src|href)=\")([^\"]+)(\")|(<<IMG:)([^|>]+)()")
WIKI = re.compile(r"(\[\[)([^\]|#]+/[^\]|#]+)((?:#[^\]|]*)?(?:\|[^\]]*)?\]\])")
TICK = re.compile(r"(`)((?:1_sources|2_transcripts|3_research|4_outputs|tools|output|data|audio|plans|scripts)/[^`\s*<]+)(`)")
TICK_REL = re.compile(r"(`)(\.\./[^`\s*<]+)(`)")   # `../rod/файл.md` — путь от файла


def text_files():
    for line in git("ls-files").splitlines():
        p = N(line)
        if p.endswith(TEXT) and not p.startswith(SKIP) and (ROOT / p).exists():
            yield p


def fix_text(path, text, where, prev=None):
    here = Path(path).parent
    # прежние места этого файла (по истории git) — старые относительные ссылки считались от них
    olds, q = [], path
    while prev and q in prev and len(olds) < 10:
        q = prev[q]
        olds.append(Path(q).parent)
    fixes = []

    def rel_fix(target):
        t = target.split("#")[0]
        if not t or re.match(r"^(https?:|mailto:|data:|#|/|app:|obsidian:)", t) or "{" in t:
            return None
        from urllib.parse import unquote
        abs_old = os.path.normpath((here / unquote(t)).as_posix())
        if (ROOT / abs_old).exists():
            return None
        for base in [here] + olds:
            new, _ = where(os.path.normpath((base / unquote(t)).as_posix()))
            if new:
                return os.path.relpath(new, here) + target[len(t):]
        return None

    def root_fix(t):
        if (ROOT / t).exists():
            return None
        new, _ = where(t.rstrip("/"))
        return new if new else None

    def sub_link(m):
        g = [x for x in m.groups()]
        for a, b, c in ((0, 1, 2), (3, 4, 5), (6, 7, 8)):
            if g[a]:
                new = rel_fix(g[b].strip())
                if new:
                    fixes.append((g[b].strip(), new))
                    return g[a] + new + (g[c] or "")
                return m.group(0)
        return m.group(0)

    text = LINK.sub(sub_link, text)

    def sub_tick_rel(m):
        new = rel_fix(m.group(2))
        if new:
            fixes.append((m.group(2), new))
            return m.group(1) + new + m.group(3)
        return m.group(0)
    text = TICK_REL.sub(sub_tick_rel, text)
    for rx in (WIKI, TICK):
        def sub_root(m):
            new = root_fix(m.group(2))
            if new:
                fixes.append((m.group(2), new))
                return m.group(1) + new + m.group(3)
            return m.group(0)
        text = rx.sub(sub_root, text)
    return text, fixes


def cmd_fix(apply, only=None):
    where, moved = resolver()
    prev = {b: a for a, b in moved.items()}
    total, files = 0, []
    for p in text_files():
        if only and p not in only:
            continue
        s = (ROOT / p).read_text(encoding="utf-8", errors="replace")
        s2, fixes = fix_text(p, s, where, prev)
        if fixes:
            total += len(fixes)
            files.append(p)
            for a, b in fixes[:5]:
                print(f"  {p}: {a} → {b}")
            if apply:
                (ROOT / p).write_text(s2, encoding="utf-8")
    print(f"{'Исправлено' if apply else 'Можно исправить'}: {total} ссылок в {len(files)} файлах")
    return files


def cmd_fix_staged():
    """pre-commit: если в коммите есть переименования — поправить ссылки на старые пути во всех текстах."""
    staged = git("diff", "--cached", "-M", "-l0", "--name-status", "--diff-filter=R").splitlines()
    if not staged:
        return
    pairs = [tuple(N(x) for x in l.split("\t")[1:3]) for l in staged if l.startswith("R")]
    renamed_names = {Path(a).name: Path(b).name for a, b in pairs if Path(a).name != Path(b).name}
    # старое имя занято другим файлом — такие ссылки не трогаем. Проверка — один раз на имя: раньше обход всего
    # проекта шёл для каждого файла × каждого переименования, и коммит с 52 переездами висел больше часа (29.09.2026)
    renamed_names = {a: b for a, b in renamed_names.items() if not any(True for _ in ROOT.rglob(a))}
    where, _ = resolver()
    base = dict(pairs)
    where_staged = lambda old: ((base[old], None) if old in base and (ROOT / base[old]).exists() else where(old))
    changed = []
    for p in text_files():
        s = (ROOT / p).read_text(encoding="utf-8", errors="replace")
        s2, fixes = fix_text(p, s, where_staged)
        for a, b in renamed_names.items():          # [[старое имя]] → [[новое имя]] для переименованных
            s2 = re.sub(rf"\[\[{re.escape(Path(a).stem)}(\]\]|\||#)", lambda m: f"[[{Path(b).stem}{m.group(1)}", s2)
            s2 = s2.replace(f"[[{a}", f"[[{b}")
            s2 = s2.replace(f"[{a}](", f"[{b}](")         # подпись ссылки = старое имя файла
            s2 = s2.replace(f"`{a}`", f"`{b}`")           # имя файла, упомянутое в тексте
        if s2 != s:
            (ROOT / p).write_text(s2, encoding="utf-8")
            changed.append(p)
    if changed:
        git("add", "--", *changed)
        print(f"moves: переименовано {len(pairs)} файлов — ссылки поправлены в {len(changed)} файлах и добавлены в коммит")


def cmd_table():
    hist = history()
    with open(paths.MOVED_TABLE, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["дата", "коммит", "что", "было", "стало"])
        for d, h, k, a, b in hist:
            w.writerow([d, h, "переезд" if k == "R" else "удалён", a, b])
    print(f"{paths.rel(paths.MOVED_TABLE)}: {sum(1 for x in hist if x[2] == 'R')} переездов, {sum(1 for x in hist if x[2] == 'D')} удалений")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    if cmd == "where":
        where, _ = resolver()
        for old in sys.argv[2:]:
            new, gone = where(old)
            if new:
                print(f"{old}\n  → {new}")
            elif gone:
                print(f"{old}\n  → удалён {gone[0]} в коммите {gone[1]} (последний путь: {gone[2]})\n    вернуть: {'git -C ' + str(OLD_REPO) + ' show ' + gone[1] + '^:' + repr(gone[2]) + ' > ' + repr(gone[2]) if gone[1] in OLD else 'git checkout ' + gone[1] + '^ -- ' + repr(gone[2])}")
            else:
                c = where.split.get(unicodedata.normalize("NFC", old).strip("/"))
                if c:
                    now = __import__("collections").Counter()
                    for dst, n in c.items():
                        now[where(dst)[0] or dst] += n
                    print(f"{old}\n  → папка разошлась по {len(now)} местам:")
                    for dst, n in now.most_common(10):
                        print(f"     {n:4} → {dst}")
                else:
                    print(f"{old}\n  → в истории git не найден")
    elif cmd == "fix":
        cmd_fix("--apply" in sys.argv)
    elif cmd == "fix-staged":
        cmd_fix_staged()
    elif cmd == "table":
        cmd_table()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
