#!/usr/bin/env python3
"""На чём держится каждое звено нашей родословной — документ, слова родных или вывод из архивов.

Зачем. Связь «ребёнок → отец / мать» в карточке — одна строка `father:`. По ней не видно, почему мы так решили:
метрика прямо назвала родителей, папа так сказал, или мы вывели это по отчеству и деревне. Через месяц это
забывается, и вывод начинает выглядеть как документ. Скрипт собирает основания из уже записанных фактов — у каждого
факта есть происхождение и источник — и показывает их у каждого звена.

Основание звена — лучшее из фактов, которые о нём говорят:
    📄 документ  — найденная запись (метрика, справка), где родители названы прямо
    👪 семья     — слова родных (разговоры, рукописи, семейное дерево)
    🧮 вывод     — наш вывод из архивов: по отчеству, годам, деревне; или «вывод проекта»
    🌳 чужое дерево — только из чужих деревьев (подсказка, не доказательство)
    ⚠ без основания — связь в карточке есть, а факта о ней нет: записать, откуда она

    tools/py tools/scripts/proof.py                      # все предки Павла по поколениям
    tools/py tools/scripts/proof.py "Прокоп Ясенев"      # цепочка вверх от человека
    tools/py tools/scripts/proof.py --write              # то же в файл 3_research/tree/_ДОКАЗАТЕЛЬСТВА.md
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import cards  # noqa: E402
import paths  # noqa: E402
from cards.kinship import ROOT, _near, levels  # noqa: E402

OUT = paths.TREE / "_ДОКАЗАТЕЛЬСТВА.md"
NEAR_IDS = set()   # кто не дальше прадедов Павла — их связи семья знает сама
ORDER = ["doc", "family", "tree", "inference", "other_tree"]
MARK = {"doc": "📄 документ", "family": "👪 семья", "tree": "🗂 старое семейное дерево", "inference": "🧮 вывод",
        "other_tree": "🌳 чужое дерево", None: "⚠ без основания"}
LEVEL_RU = {"proven": "доказано", "likely": "вероятно", "possible": "возможно", "unlikely": "маловероятно", "no": "не родня"}
DERIVED = re.compile(r"по отчеству|вывод|по годам|по возрасту|вероятн|предполож|скорее всего|видимо|по деревне", re.I)
BIRTH = re.compile(r"рожд|крещ", re.I)
UP = re.compile(r"отец|отца|отцом|мать|матер|родител", re.I)        # в карточке ребёнка — о родителе
DOWN = re.compile(r"сын|дочь|дочер|дет[иья]|ребён|родил", re.I)     # в карточке родителя — о ребёнке
FAMILY_TREE = re.compile(r"I[59]\d{5}$")                            # первая выгрузка семейного дерева


def kind_of(tree, owner, f, child):
    """Чем является факт как основание связи «child → родитель». Документ — только запись о рождении или крещении
    ребёнка, где родители названы прямо; отчество в браке или смерти, годы, деревня — это уже наш вывод."""
    if f.provenance == "family":
        return "family"
    if any(tree.sources[r.source].fm.get("our_tree") is True for r in f.refs if r.source in tree.sources):
        return "tree"
    if f.provenance == "other_tree":
        return "other_tree"
    if f.provenance != "found" or f.label.lower().startswith("родство") or DERIVED.search(f.label + " " + f.reasoning):
        return "inference"
    head = f.label + " " + f.text[:60]
    if owner is child and BIRTH.search(head) and not DERIVED.search(f.text[:200]):
        return "doc"
    return "inference"


def given(p):
    return (p.name or p.stem).split()[0].lower().replace("ё", "е")


def evidence(tree, child, parent):
    """Факты о связи: в карточке ребёнка — со ссылкой на родителя или с его именем рядом со словом «отец / мать /
    родители» (или в записи о рождении); в карточке родителя — со ссылкой на ребёнка или его именем рядом со словом
    «сын / дочь / дети»."""
    out = []
    for f in child.facts:
        low = f.text.lower().replace("ё", "е")
        if f"[[{parent.stem}" in f.text or (given(parent) in low and (UP.search(f.text) or BIRTH.search(f.label))):
            out.append((child, f))
    for f in parent.facts:
        low = f.text.lower().replace("ё", "е")
        if f"[[{child.stem}" in f.text or (given(child) in low and DOWN.search(f.text)):
            out.append((parent, f))
    return out


def from_family_tree(child, parent):
    """Связь пришла из первой выгрузки семейного дерева (MyHeritage, gedcom_id I500…) — без источника у связи."""
    return all(FAMILY_TREE.match(str(x.fm.get("gedcom_id") or "")) for x in (child, parent))


def ref_text(tree, owner, f):
    srcs = [tree.sources[r.source].stem + (f", {r.locator}" if r.locator else "") for r in f.refs if r.source in tree.sources]
    return ("; ".join(srcs) or "источник не указан") + f" — карточка «{owner.stem}», строка {f.line}"


def edge(tree, child, parent):
    ev = evidence(tree, child, parent)
    k = lambda o, f: kind_of(tree, o, f, child)  # noqa: E731
    kinds = sorted({k(o, f) for o, f in ev}, key=ORDER.index)
    shown = [(k(o, f), ref_text(tree, o, f), f.text[:160]) for o, f in sorted(ev, key=lambda x: ORDER.index(k(*x)))[:3]]
    if child.id in NEAR_IDS and parent.id in NEAR_IDS:
        kinds = sorted(set(kinds) | {"family"}, key=ORDER.index)
        shown.insert(0, ("family", "семья знает лично (не дальше прадедов Павла)", "свои"))
    if from_family_tree(child, parent):
        if "tree" not in kinds:
            kinds = sorted(kinds + ["tree"], key=ORDER.index)
        shown.append(("tree", "первое семейное дерево (MyHeritage, " + str(child.fm.get("gedcom_id")) + " → "
                      + str(parent.fm.get("gedcom_id")) + ")", "связь пришла из старого дерева, источника у неё нет"))
    return (kinds[0] if kinds else None), kinds, shown


def chain(tree, start):
    """Предки от человека: [(поколение, ребёнок, родитель, «отец|мать»)] в порядке обхода."""
    out, todo, seen = [], [(0, start)], set()
    while todo:
        gen, p = todo.pop(0)
        if p.id in seen:
            continue
        seen.add(p.id)
        for role, ids in (("отец", p.father), ("мать", p.mother)):
            for pid in ids:
                if pid in tree.people:
                    out.append((gen + 1, p, tree.people[pid], role))
                    todo.append((gen + 1, tree.people[pid]))
    return out


def candidates(tree, p):
    """Кого подозреваем родителем, если связи нет: maybe_kin с relation parent и maybe_same."""
    return [(x.kind, tree.people[x.person]) for x in p.possible if x.person in tree.people
            and (x.kind == "same" or (x.kind == "kin" and x.relation == "parent"))]


def report(tree, start, lv):
    lines = []
    for gen, child, parent, role in chain(tree, start):
        best, kinds, ev = edge(tree, child, parent)
        level = LEVEL_RU.get((lv.get(parent.id) or ("?",))[0], "?")
        lines.append(f"\n**{gen}. {child.stem} → {role}: {parent.stem}** — {MARK[best]}"
                     + (f" (ещё: {', '.join(MARK[k] for k in kinds[1:])})" if len(kinds) > 1 else "")
                     + f"; родство {parent.stem.split(' (')[0]} — {level}")
        for k, where, text in ev:
            lines.append(f"  - {MARK[k]}: {text}… — {where}")
        if best is None:
            lines.append("  - связь записана, а факта о ней нет — дописать в карточку ребёнка, откуда она")
    ends = [p for p in [start] + [x[2] for x in chain(tree, start)] if not p.father or not p.mother]
    for p in ends:
        miss = [r for r, ids in (("отец", p.father), ("мать", p.mother)) if not ids]
        cand = candidates(tree, p)
        lines.append(f"\n— {p.stem}: {', '.join(miss)} неизвестны"
                     + (f"; кандидаты (не доказано): {'; '.join(('возможно, он же — ' if k == 'same' else 'возможно, родитель — ') + c.stem + (' (у того отец ' + tree.people[c.father[0]].stem + ')' if c.father and c.father[0] in tree.people else '') for k, c in cand)}" if cand else ""))
    return lines


def find(tree, name):
    hits = [p for p in tree.people.values() if p.stem == name or p.id == name]
    hits = hits or [p for p in tree.people.values() if name.lower() in p.stem.lower()]
    if len(hits) != 1:
        sys.exit(f"«{name}»: найдено {len(hits)} — уточните (имя карточки или cr_id): "
                 + "; ".join(p.stem for p in hits[:8]))
    return hits[0]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("person", nargs="?")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    tree = cards.load()
    lv = levels(tree)
    NEAR_IDS.update(_near(tree))
    root = next(p for p in tree.people.values() if p.fm.get("gedcom_id") == ROOT)
    start = find(tree, a.person) if a.person else root
    lines = report(tree, start, lv)
    stats = {}
    for line in lines:
        m = re.match(r"\n\*\*\d+\. .*?\*\* — (.+?)(?: \(ещё|;)", line)
        if m:
            stats[m.group(1)] = stats.get(m.group(1), 0) + 1
    head = [f"# На чём держится родословная — {start.stem}",
            "",
            "Каждое звено «ребёнок → отец / мать»: на чём оно держится. 📄 документ — запись о рождении или крещении прямо называет родителей;",
            "👪 семья — слова родных; 🗂 старое семейное дерево — пришло из MyHeritage без источника; 🧮 вывод — наш вывод из архивов",
            "(по отчеству в браке или смерти, годам, деревне); 🌳 чужое дерево;",
            "⚠ — связь есть, основания не записано. Собрано скриптом `rodo proof` из фактов карточек —",
            "руками не править: править факты в карточках.",
            "",
            "Звеньев: " + ", ".join(f"{k} — {v}" for k, v in sorted(stats.items(), key=lambda x: -x[1]))]
    text = "\n".join(head + lines) + "\n"
    if a.write:
        OUT.write_text(text, encoding="utf-8")
        print(f"записано: {OUT.relative_to(paths.ROOT)} ({len(lines)} строк)")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
