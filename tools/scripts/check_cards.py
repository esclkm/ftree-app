#!/usr/bin/env python3
"""Проверка карточек перед выгрузкой сайта: всё ли записано так, чтобы из карточки получился JSON по схеме web/schema/.

Читает дерево тем же разбором, что и сборка (пакет cards), и показывает каждую запись не по правилам — с карточкой и
строкой: строка факта без ссылки на источник, дата не по правилу, уверенность не из трёх слов, место без эпох…
Ошибки останавливают сборку сайта; предупреждения — нет.

Карточка человека проверяется и по образцу (3_research/templates/Карточка человека — устройство.md, пакет cards.layout):
разделы по порядку, пустых нет, строка факта — только в «Фактах», свободный текст — в «Заметках».

Запуск:  python3 tools/scripts/check_cards.py          # всё, код выхода 1, если есть ошибки
         python3 tools/scripts/check_cards.py --quiet  # одна строка-итог
         python3 tools/scripts/check_cards.py --fix    # механическое по образцу: порядок, пустые разделы, что не на месте
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cards  # noqa: E402


def fix():
    """Карточки, где разделы не по образцу, — переписать по образцу (слова те же; меняется только место)."""
    import paths
    from cards import layout
    from cards.notes import card_path, read_note
    fixed = []
    for f in sorted((paths.TREE / "people").glob("*.md")):
        note = read_note(f)
        if not note.fm.get("cr_id") or not layout.check(note, card_path(f)):
            continue
        text = f.read_text(encoding="utf-8")
        head = text[: len(text) - len(text.split("\n---\n", 1)[1])] if text.startswith("---\n") else ""
        f.write_text(head + "\n" + layout.fix(text[len(head):]), encoding="utf-8")
        fixed.append(note.stem)
    print(f"По образцу переписано карточек: {len(fixed)}" + (f" — {', '.join(fixed)}" if fixed else ""))


def main():
    if "--fix" in sys.argv:
        fix()
    tree = cards.load()
    errors, warnings = tree.errors, [p for p in tree.problems if p.level != "error"]
    if "--quiet" not in sys.argv:
        for p in errors + warnings:
            print(p)
    print(f"Карточки для сайта: людей {len(tree.people)}, фактов {sum(len(p.facts) for p in tree.people.values())}, "
          f"ошибок {len(errors)}, предупреждений {len(warnings)}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
