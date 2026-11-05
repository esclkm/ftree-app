#!/usr/bin/env python3
"""Ветки рода по дедушкам и бабушкам: поле `lineage` в карточках людей (3_research/tree/people).

Правило (так делают Family Tree Maker и RootsMagic — «разметка по четырём дедушкам и бабушкам»):
  человек входит в ветку деда или бабушки G, если он кровный родственник через G, то есть
  предок G или потомок кого-то из предков G (сюда попадают братья G, их дети, двоюродные и т.д.).
  Ниже точки слияния родов веток несколько: у отца — ветки двух его родов, у его детей — все четыре.
  Супруги, пришедшие в род со стороны, и их кровная родня (свойственники) получают
  `lineage_by_marriage`, а не `lineage`.
Скрипт пересчитывает поля заново при каждом запуске — вручную их не правим.

Запуск: python3 tools/scripts/assign_lineage.py [--dry]
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

PEOPLE = paths.TREE / "people"
# ветка → карточка деда или бабушки (имя файла без .md) — в ftree.toml, раздел [[branch]]
LINES = paths.LINES
LINK = re.compile(r"\[\[([^\]|]+)")


def frontmatter(text):
    m = re.match(r"---\n(.*?)\n---", text, re.S)
    return m.group(1) if m else ""


def field_links(fm, key):
    """Все ссылки [[…]] в поле key — одной строкой или списком."""
    m = re.search(rf"^{key}:(.*(?:\n  - .*)*)", fm, re.M)
    return LINK.findall(m.group(1)) if m else []


def main():
    notes = {p.stem: p for p in PEOPLE.glob("*.md")}
    parents, children, spouses = defaultdict(set), defaultdict(set), defaultdict(set)
    for name, p in notes.items():
        fm = frontmatter(p.read_text(encoding="utf-8"))
        for key in ("father", "mother"):
            for par in field_links(fm, key):
                if par in notes:
                    parents[name].add(par)
                    children[par].add(name)
        for key in ("spouse", "spouse1", "spouse2", "spouse3"):
            for s in field_links(fm, key):
                if s in notes:
                    spouses[name].add(s)
                    spouses[s].add(name)

    def closure(start, step):
        seen, stack = set(), [start]
        while stack:
            for nxt in step[stack.pop()]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return seen

    lineage, by_marriage = defaultdict(list), defaultdict(list)
    blood_of = {}
    for line, g in LINES.items():
        if g not in notes:
            sys.exit(f"нет карточки «{g}» для ветки {line}")
        ancestors = {g} | closure(g, parents)
        blood = set(ancestors)
        for a in ancestors:
            blood |= closure(a, children)
        blood_of[line] = blood
        for x in sorted(blood):
            lineage[x].append(line)
    in_some_line = set(lineage)
    for line, blood in blood_of.items():
        # пришедший в род супруг — «по браку»; его кровная родня (свойственники) — тоже,
        # но только если сама не состоит ни в одной ветке (иначе у папы появились бы ветки Вики)
        married_in = {s for x in blood for s in spouses[x] if s not in blood}
        for s in married_in:
            kin = {s} | closure(s, parents)
            for a in list(kin):
                kin |= closure(a, children)
            for k in {s} | (kin - in_some_line):
                if k not in blood and line not in by_marriage[k]:
                    by_marriage[k].append(line)

    order = list(LINES)
    changed = 0
    for name, p in notes.items():
        text = p.read_text(encoding="utf-8")
        fm = frontmatter(text)
        new_fm = re.sub(r"^(lineage|lineage_by_marriage):.*(?:\n  - .*)*\n?", "", fm, flags=re.M).rstrip("\n")
        for key, vals in (("lineage", lineage.get(name)), ("lineage_by_marriage", by_marriage.get(name))):
            if vals:
                vals = sorted(set(vals), key=order.index)
                new_fm += f"\n{key}:\n" + "\n".join(f'  - "{v}"' for v in vals)
        if new_fm != fm:
            changed += 1
            if "--dry" not in sys.argv:
                p.write_text(text.replace(fm, new_fm, 1), encoding="utf-8")

    counts = defaultdict(int)
    for vals in lineage.values():
        for v in vals:
            counts[v] += 1
    none = [n for n in notes if n not in lineage and n not in by_marriage]
    print("По веткам (кровные):", ", ".join(f"{k} {counts[k]}" for k in order))
    print("Несколько веток:", sum(1 for v in lineage.values() if len(v) > 1),
          "· только по браку:", sum(1 for n in by_marriage if n not in lineage),
          "· вне веток:", len(none), "· карточек изменено:", changed)
    if "--list-none" in sys.argv:
        print("\n".join(sorted(none)))


if __name__ == "__main__":
    main()
