#!/usr/bin/env python3
"""Какие файлы входят в приложение ftree-app — по списку tools/APP_MANIFEST (единственное место, где это решено).

  rodo app-files            все файлы приложения (то, что в git, по строкам «app», без «skip» и «tree»)
  rodo app-files tree       что внутри приложения, но остаётся в данных (строки «tree») — с причиной
  rodo app-files check      строки списка, которым не нашлось ни одного файла в git (опечатка, переезд)

Читают как модуль: scan_personal.py app (сторож личного), leaks.py (gitleaks).
"""
from __future__ import annotations

import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

MANIFEST = paths.APP / "tools" / "APP_MANIFEST"
N = lambda s: unicodedata.normalize("NFC", s)  # noqa: E731


@dataclass
class Manifest:
    app: list[str] = field(default_factory=list)
    skip: list[str] = field(default_factory=list)
    tree: dict[str, str] = field(default_factory=dict)   # путь → почему остаётся в данных


def read(path: Path = MANIFEST) -> Manifest:
    m = Manifest()
    for no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line, _, why = raw.partition("#")
        if not line.strip():
            continue
        kind, _, where = line.strip().partition(" ")
        where = N(where.strip())
        if kind == "app":
            m.app.append(where)
        elif kind == "skip":
            m.skip.append(where)
        elif kind == "tree":
            m.tree[where] = why.strip()
        else:
            raise SystemExit(f"{path}:{no}: непонятная строка «{raw}» — ждём app / skip / tree")
    return m


def under(rel: str, prefixes) -> bool:
    return any(rel == p or (p.endswith("/") and rel.startswith(p)) for p in prefixes)


def tracked(root: Path = paths.APP) -> list[str]:
    out = subprocess.run(["git", "-C", str(root), "-c", "core.quotepath=false", "ls-files", "-z"],
                         capture_output=True, text=True, check=True).stdout
    return [N(x) for x in out.split("\0") if x]


def files(root: Path = paths.APP, m: Manifest | None = None) -> list[str]:
    """Файлы приложения от корня: в git, под строкой «app», не под «skip» и не под «tree», и есть на диске."""
    m = m or read()
    return [r for r in tracked(root)
            if under(r, m.app) and not under(r, m.skip) and not under(r, m.tree) and (root / r).is_file()]


def tree_files(root: Path = paths.APP, m: Manifest | None = None) -> list[str]:
    m = m or read()
    return [r for r in tracked(root) if under(r, m.tree)]


def main(argv: list[str]) -> int:
    m = read()
    mode = argv[0] if argv else "list"
    if mode == "list":
        print("\n".join(files(m=m)))
    elif mode == "tree":
        for where, why in m.tree.items():
            print(f"{where}  — {why}" if why else where)
    elif mode == "check":
        all_ = tracked()
        # приложение внутри дерева — у строк «tree» тоже должны быть файлы; приложение отдельно — их там быть не должно
        inside = (paths.APP / "ftree.toml").is_file()
        bad = [p for p in [*m.app, *(m.tree if inside else ())] if not any(under(r, [p]) for r in all_)]
        for p in bad:
            print(f"✗ в git нет ничего под «{p}»")
        if not inside:
            extra = [p for p in m.tree if any(under(r, [p]) for r in all_)]
            for p in extra:
                print(f"✗ «{p}» — о людях дерева (строка tree), в приложении быть не должно")
            bad += extra
        print("✅ Список приложения сходится с git." if not bad else f"⛔ {len(bad)} строк без файлов.")
        return 1 if bad else 0
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
