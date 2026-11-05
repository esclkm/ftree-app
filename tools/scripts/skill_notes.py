#!/usr/bin/env python3
"""Заметки этого дерева к навыку Claude.

Навык (.claude/skills/<имя>/SKILL.md) — метод: как устроен архив или сайт, как искать и читать, правила. Он общий для
любого дерева и уйдёт в приложение. Что именно искали в этом дереве, какие дела смотрели, что нашли, чьи решения —
в данных: <папка поиска>/навыки/<имя>.md (папка поиска — tree.research_dir в ftree.toml).

  rodo skill-notes <навык>     путь к заметкам и их текст (нет файла — так и пишет)
  rodo skill-notes --path <навык>   только путь
  rodo skill-notes --embed <навык>  для строки !`…` в начале SKILL.md: заголовок и текст заметок; нет заметок или
                                    дерева — пусто (навык вызвали вне дерева — ничего лишнего)
  rodo skill-notes             у каких навыков есть заметки

Папка заметок — [skills] notes_dir в ftree.toml дерева.
"""
import sys

import paths


def main(argv: list[str]) -> int:
    only_path = "--path" in argv
    embed = "--embed" in argv
    args = [a for a in argv if a not in ("--path", "--embed")]
    if not args:
        files = sorted(paths.SKILL_NOTES.glob("*.md")) if paths.SKILL_NOTES.is_dir() else []
        names = [f.stem for f in files if not f.stem.startswith("00_")]
        print(f"Заметки к навыкам — {paths.rel(paths.SKILL_NOTES)}/: " + (", ".join(names) or "пока нет"))
        return 0
    name = args[0].strip("/").split("/")[-1]
    f = paths.SKILL_NOTES / f"{name}.md"
    if only_path:
        print(paths.rel(f))
        return 0 if f.is_file() else 1
    if embed:
        if f.is_file():
            print(f"## Заметки этого дерева — {paths.rel(f)}\n\n" + f.read_text(encoding="utf-8").strip())
        return 0
    if not f.is_file():
        print(f"У навыка {name} заметок этого дерева нет ({paths.rel(f)}) — работать по навыку.")
        return 0
    print(f"# {paths.rel(f)}\n")
    print(f.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
