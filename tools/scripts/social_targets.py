#!/usr/bin/env python3
"""Кого искать в соцсетях и кто нашёлся в списке друзей — без модели (навык social-search).

Зачем. Живых потомков ищут не по одному: вся родня обычно друг у друга в друзьях и подписках. Поэтому сначала —
список, кого ищем (живые потомки предка и их супруги нужного возраста), потом один раз читаем список друзей
«якоря» (уже найденного родственника) и сверяем его с фамилиями и именами из дерева. Модель смотрит только на итог.

    tools/py tools/scripts/social_targets.py list "Иван Ясенев (1878)"              # таблица: кого искать
    tools/py tools/scripts/social_targets.py list "Иван Ясенев (1878)" --min 15 --max 55 --year 2026
    tools/py tools/scripts/social_targets.py match "Иван Ясенев (1878)" список.tsv [ещё.tsv …]
        # список.tsv — строки «аккаунт<TAB>имя на странице» (из js/ навыка); печатает совпадения по фамилиям и именам

Возраст: год из born; нет года — оценка по братьям и сёстрам (середина), родителям (+25) и детям (−28); не вышло — «?», такие идут в отбор.
Несовершеннолетних (младше 18) список помечает «мл.»: их не ищем по имени и ссылки в карточки не вносим.
"""
import argparse
import re
import sys
from pathlib import Path

import cards
import paths

# как фамилии рода пишут в соцсетях — своё у каждого дерева: ftree.toml, [social.surname_forms]; дополнять по мере надобности
SURNAME_FORMS = {k: list(v) for k, v in dict(paths.tree_conf("social.surname_forms", {})).items()}


def year(g):
    if not g:
        return None
    try:
        return (g.a or g.b).y
    except AttributeError:
        return None


def collect(tree, root_name):
    P = tree.people
    roots = [p for p in P.values() if p.stem == root_name or p.name == root_name]
    if not roots:
        sys.exit(f"нет карточки «{root_name}»")
    gen, queue = {roots[0].id: 0}, [roots[0].id]
    while queue:
        x = queue.pop(0)
        for c in P[x].children:
            if c in P and c not in gen:
                gen[c] = gen[x] + 1
                queue.append(c)
    spouses = {s: gen[d] for d in gen for s in P[d].spouses if s in P and s not in gen}
    return P, gen, spouses


def est_year(P, p):
    if (y := year(p.born)):
        return y, ""
    sib = sorted(y for x in p.father + p.mother if x in P for c in P[x].children
                 if c != p.id and c in P and (y := year(P[c].born)))
    if sib:  # братья и сёстры с годами — середина их рождений
        return sib[len(sib) // 2], "≈"
    par = [year(P[x].born) for x in p.father + p.mother if x in P]
    kid = [year(P[x].born) for x in p.children if x in P]
    if any(par):
        return max(y for y in par if y) + 25, "≈"
    if any(kid):
        return min(y for y in kid if y) - 28, "≈"
    for s in p.spouses:  # у супруга год есть — берём его
        if s in P and (y := year(P[s].born)):
            return y, "≈"
    return None, "?"


def cmd_list(a):
    tree = cards.load()
    P, gen, spouses = collect(tree, a.root)
    rows = []
    for i, g in list(gen.items()) + list(spouses.items()):
        p = P[i]
        if p.died or g == 0:
            continue
        y, mark = est_year(P, p)
        age = a.year - y if y else None
        if age is not None and (age > a.max + (5 if mark else 0) or age < a.min):
            continue
        minor = age is not None and age < 18
        links = len(re.findall(r"(?:facebook|instagram|linkedin)\.com/", p.body))
        rows.append((g, p.name, f"{mark}{y or ''}", "мл." if minor else "", "супруг(а)" if i in spouses else "", links, p.id))
    rows.sort(key=lambda r: (r[0], r[1]))
    print("| пок. | кто | год | | | соцсети в карточке |\n|---|---|---|---|---|---|")
    for g, n, y, mn, sp, ln, _ in rows:
        print(f"| {g} | {n} | {y} | {mn} | {sp} | {ln or ''} |")
    print(f"\nвсего {len(rows)}; несовершеннолетних {sum(1 for r in rows if r[3])}; уже со ссылкой {sum(1 for r in rows if r[5])}")


def cmd_match(a):
    tree = cards.load()
    P, gen, spouses = collect(tree, a.root)
    people = [P[i] for i in list(gen) + list(spouses) if not P[i].died]
    sur = {w.lower() for p in people for w in p.name.split()[1:] if len(w) > 3}
    forms = {f for s in sur for f in SURNAME_FORMS.get(s, [s])}
    first = {p.name.split()[0].lower() for p in people if len(p.name.split()[0]) > 3}
    rx_s = re.compile("|".join(map(re.escape, sorted(forms))), re.I)
    rx_f = re.compile(r"\b(" + "|".join(map(re.escape, sorted(first))) + r")\b", re.I)
    seen = set()
    for f in a.files:
        for line in Path(f).read_text().splitlines():
            acc, _, name = line.partition("\t")
            if not acc or acc in seen:
                continue
            seen.add(acc)
            text = f"{acc} {name}"
            if rx_s.search(text):
                print(f"фамилия  {acc} | {name}")
            elif a.names and rx_f.search(name) and not re.search("[а-яё]", name, re.I):
                print(f"имя      {acc} | {name}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    l = sub.add_parser("list")
    l.add_argument("root")
    l.add_argument("--min", type=int, default=15)
    l.add_argument("--max", type=int, default=55)
    l.add_argument("--year", type=int, default=2026)
    m = sub.add_parser("match")
    m.add_argument("root")
    m.add_argument("files", nargs="+")
    m.add_argument("--names", action="store_true", help="ещё и по именам без фамилии (шумно)")
    a = ap.parse_args()
    {"list": cmd_list, "match": cmd_match}[a.cmd](a)


if __name__ == "__main__":
    main()
