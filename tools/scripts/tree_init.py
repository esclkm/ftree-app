#!/usr/bin/env python3
"""Новое пустое дерево: папки, ftree.toml, настройщик, git — одной командой.

Зачем. Дерево — это папка данных (карточки людей, мест, источников), а код, который их проверяет и собирает сайт, —
отдельно, в приложении. Чтобы начать новое дерево (своё, друга, вымышленное для тестов), не копируя чужое, эта
команда кладёт пустую раскладку по образцу `tools/init_template/`:

  ftree.toml            — отметка корня дерева, название, пример ветки (закомментирован), настройки сайта — пустые
  1_sources/ … 4_outputs/   — четыре этажа: оригиналы, расшифровки, исследование, выдача
  3_research/tree/people|places|sources|events|biographies — само дерево
  3_research/search/    — планы поиска и журнал (имя папки — tree.research_dir в ftree.toml)
  setup/                — setup.toml (откуда приложение, что включено), env.example, пустые словари сторожа личного
  CLAUDE.md, .gitignore — правила дерева для Claude и что не хранить в git
  .githooks/pre-commit  — перед коммитом: rodo check-tree и check-cards (git config core.hooksPath .githooks)

Папку, где уже есть ftree.toml, не трогает (отказ). Существующие файлы в папке не перезаписывает.

  rodo init <папка> [--title "Родословная Ясеневых"] [--name yasenev] [--no-git]
Потом — `rodo import gedcom <файл>` (загрузить чужое дерево) и `rodo setup` (рабочее место).
"""
import argparse
import datetime
import re
import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[2]          # приложение: здесь tools/ (движок) и web/ (сайт)
TEMPLATE = APP / "tools" / "init_template"
DIRS = ("1_sources/family", "1_sources/found", "1_sources/others_trees", "1_sources/inbox", "2_transcripts",
        "3_research/tree/people", "3_research/tree/places", "3_research/tree/sources", "3_research/tree/events",
        "3_research/tree/biographies", "3_research/search/findings", "4_outputs", "setup")
def app_version() -> str:
    """Версия приложения из pyproject.toml — её новое дерево записывает себе в setup.toml ([app] version)."""
    import tomllib
    return str(tomllib.loads((APP / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"])


# файл образца → куда в дереве; в тексте {title} {name} {date} {app} {version} {root} {rodo} заменяются
FILES = {"ftree.toml": "ftree.toml", "CLAUDE.md": "CLAUDE.md", "gitignore": ".gitignore",
         "setup.toml": "setup/setup.toml", "env.example": "setup/env.example", "scan_deny.txt": "setup/scan_deny.txt",
         "scan_allow.txt": "setup/scan_allow.txt", "pre-commit": ".githooks/pre-commit",
         "claude_settings.json": ".claude/settings.json"}   # навыки Claude — плагин ftree@ftree-app


def slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "tree"


def create(folder, title=None, name=None, git=True, out=print):
    """Создать дерево в folder. → список созданных путей (от folder). Есть ftree.toml — SystemExit."""
    folder = Path(folder).expanduser().resolve()
    if (folder / "ftree.toml").exists():
        raise SystemExit(f"{folder}: здесь уже дерево (есть ftree.toml) — ничего не трогаю")
    title = title or f"Родословная {folder.name}"
    values = {"title": title, "name": name or slug(folder.name), "date": datetime.date.today().strftime("%d.%m.%Y"),
              "app": str(APP), "version": app_version(), "root": str(folder), "rodo": str(APP / "tools" / "rodo")}
    made = []
    for d in DIRS:
        p = folder / d
        if not p.exists():
            p.mkdir(parents=True)
            made.append(d + "/")
        if not any(p.iterdir()):
            (p / ".gitkeep").touch()
    for src, dst in FILES.items():
        p = folder / dst
        if p.exists():
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        text = (TEMPLATE / src).read_text(encoding="utf-8")
        p.write_text(re.sub(r"\{(\w+)\}", lambda m: values.get(m[1], m[0]), text), encoding="utf-8")
        if dst.startswith(".githooks/"):
            p.chmod(0o755)
        made.append(dst)
    if git:
        if not (folder / ".git").exists():
            subprocess.run(["git", "init", "-q", str(folder)], check=True)
            made.append(".git/")
        subprocess.run(["git", "-C", str(folder), "config", "core.hooksPath", ".githooks"], check=True)
    out(f"Дерево «{title}» — {folder}")
    for m in made:
        out(f"  + {m}")
    out("Дальше: rodo import gedcom <файл.ged> (из этой папки или с FTREE_ROOT=" + str(folder) + "), потом rodo setup")
    return made


def main(argv=None):
    ap = argparse.ArgumentParser(description="Новое пустое дерево")
    ap.add_argument("folder")
    ap.add_argument("--title", help="название дерева («Родословная Ясеневых»)")
    ap.add_argument("--name", help="короткое имя латиницей (по умолчанию — от имени папки)")
    ap.add_argument("--no-git", action="store_true", help="без git init и хуков")
    a = ap.parse_args(argv)
    create(a.folder, a.title, a.name, git=not a.no_git)
    return 0


if __name__ == "__main__":
    sys.exit(main())
