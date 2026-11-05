#!/usr/bin/env python3
"""Наши люди против их записей в чужих деревьях MyHeritage — что там иначе или чего у нас нет. Сети не касается.

Зачем. У подтверждённого совпадения (Smart Match) чужое дерево часто пишет человека иначе: другое написание имени
(«Jasieniew» — «Ясенев»), девичью фамилию, год и место рождения, жительство, родню. Кнопка MyHeritage «Extract info»
перенесла бы это прямо на сайт — без источника и уверенности. Здесь то же сравнение, но список идёт Павлу на выбор,
а отмеченное вносим в карточки (aliases, факт «по чужому дереву», уверенность низкая).

Как. Снимок делает `node tools/scripts/myheritage_tree.mjs watch` (3_research/tree_data/mh_web/others/<дата>.json).
Скрипт берёт последний снимок, находит карточку по номеру на сайте (gedcom_id I25 = 125, новые — по
<папка поиска>/myheritage_ids.json) и пишет отчёт `<папка поиска>/findings/_MyHeritage_сверка_<дата>.md`:
у каждого человека и дерева — строки `- [ ]`: другое имя · год рождения/смерти · место · другие события · родня,
которой у нас нет. Совпадающее не пишется.

  tools/py tools/scripts/myheritage_compare.py                 # все люди снимка
  tools/py tools/scripts/myheritage_compare.py --ancestors     # только прямые предки Павла и Вики
  tools/py tools/scripts/myheritage_compare.py --snapshot <файл.json>
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402
import tree as T  # noqa: E402
from cards.tree import load  # noqa: E402
from myheritage_plan import COUNTRY, LAT, norm, place_text, same_place, site_no  # noqa: E402

ROOT = paths.ROOT
OTHERS = paths.MH_OTHERS
IDS = paths.MYHERITAGE_IDS
OUT = paths.FINDINGS
YEAR = re.compile(r"\b(1[5-9]\d\d|20\d\d)\b")


def year(s):
    m = YEAR.search(s or "")
    return int(m.group(1)) if m else None


def key(s):
    """Написание без скобок, знаков и алфавита: «Jasieniew (Wierzbowska)» и «Ясенев» → сравнимые латинские ключи."""
    s = norm(re.sub(r"\(.*?\)", " ", s or ""))
    s = "".join(LAT.get(ch, ch) for ch in s)
    s = s.replace("sz", "sh").replace("w", "v").replace("cz", "ch").replace("ct", "kt").replace("y", "i").replace("j", "i")
    return re.sub(r"[^a-z ]", "", s).split()


def names_of(p):
    out = [p.name] + list(p.fm.get("aliases") or [])
    if p.fm.get("maiden_name"):
        out.append(f"{p.name.split()[0]} {p.fm['maiden_name']}")
    return out


def known_name(their, ours):
    """Их имя уже есть среди наших написаний (с поправкой на алфавит и скобки)?"""
    raw = {norm(re.sub(r"\s*\(.*?\)", "", n)) for n in ours}
    if norm(re.sub(r"\s*\(.*?\)", "", their)) in raw:
        return True
    k = key(their)
    return any(key(n) == k for n in ours)


def relatives(tree, p):
    ids = list(p.father) + list(p.mother) + list(p.spouses) + list(p.children)
    for par in list(p.father) + list(p.mother):
        if par in tree.people:
            ids += [c for c in tree.people[par].children if c != p.id]
    return [tree.people[i] for i in dict.fromkeys(ids) if i in tree.people]


def first_key(name):
    k = key(name)
    return k[0][:4] if k else ""


def ancestors(tree):
    stem = {x.stem: k for k, x in tree.people.items()}
    # чьи предки — ftree.toml [myheritage.ours]: ancestor_roots — карточки; ancestor_couple — двое, кто у человека
    # оба в дедах (так находится второй супруг, у которого своей карточки-корня нет)
    roots = [stem.get(s) for s in paths.tree_conf("myheritage.ours.ancestor_roots", [])]
    couple = [stem.get(s) for s in paths.tree_conf("myheritage.ours.ancestor_couple", [])]
    if len(couple) == 2 and all(couple):
        oz, ki = couple
        for k in tree.people:
            a = T.ancestors(tree, k)
            if oz in a and ki in a and a[oz][0] == 2 and a[ki][0] == 2:
                roots.append(k)
    out = set()
    for r in filter(None, roots):
        out |= {a for a, (n, _) in T.ancestors(tree, r).items() if n}
    return out


def main():
    args = sys.argv[1:]
    snap = Path(args[args.index("--snapshot") + 1]) if "--snapshot" in args else max(OTHERS.glob("????-??-??.json"), default=None)
    if not snap:
        sys.exit("нет снимка: сначала node tools/scripts/myheritage_tree.mjs watch")
    people = json.loads(snap.read_text())["people"]
    tree = load()
    by_site = {site_no(p): k for k, p in tree.people.items() if site_no(p)}
    if IDS.exists():
        by_site.update({str(v): k for k, v in json.loads(IDS.read_text()).items()})
    only = ancestors(tree) if "--ancestors" in args else None

    L = [f"# MyHeritage — наши люди в чужих деревьях: что там иначе ({date.today():%d.%m.%Y})", "",
         f"Снимок `{snap.name}` (`myheritage_tree.mjs watch`), сравнение — `myheritage_compare.py"
         f"{' --ancestors' if only else ''}`. Совпадающее не показано. Отметь `[x]`, что брать: имя — в aliases, "
         "остальное — фактом «по чужому дереву» с уверенностью «низкая».", ""]
    shown = 0
    skip = re.compile(r"^(<|unknown\b|entry page)", re.I)
    for our, it in sorted(people.items(), key=lambda x: x[1]["name"]):
        pid = by_site.get(str(our))
        if not pid or (only is not None and pid not in only):
            continue
        p = tree.people[pid]
        ours = names_of(p)
        rel_keys = {first_key(n) for r in relatives(tree, p) for n in names_of(r)}
        rows = {}                                    # строка → деревья, где она есть (одно и то же — одной строкой)

        def add(row, tree_name):
            rows.setdefault(row, []).append(tree_name)
        for m in it["matches"]:
            src, prof = f"{m['site_name'].strip()} ({m['manager']})", m.get("profile") or {}
            for nm in dict.fromkeys([m["name"], prof.get("name") or ""]):
                if nm and not skip.match(nm) and not known_name(nm, ours):
                    add(f"имя: **{nm}**", src)
            facts = prof.get("facts") or []
            if not facts:   # профиль не открывали (watch без --deep) — годы и места из самого совпадения: «BIRT 1930 Беларусь; DEAT …»
                for part in (m.get("events") or "").split("; "):
                    code, _, rest = part.partition(" ")
                    if code in ("BIRT", "DEAT"):
                        d = YEAR.search(rest)
                        date_txt = rest[:d.end()] if d else ""
                        place = rest[len(date_txt):].strip()
                        place = "" if re.fullmatch(r"\d{1,2}\s+[A-Za-z]{3}", place) else place   # «1938 2 SEP» — хвост даты, не место
                        facts.append({"type": code, "title": code, "date": date_txt, "place": place,
                                      "content": "", "sources": []})
            for code, label, mine, place in (("BIRT", "рождение", p.fm.get("born"), p.birth_place), ("DEAT", "смерть", p.fm.get("died"), p.death_place)):
                f = next((x for x in facts if x["type"] == code), None)
                if not f:
                    continue
                y, my = year(f["date"]), year(str(mine or ""))
                if y and y != my:
                    add(f"{label}: **{f['date']}** (у нас: {mine or '—'})", src)
                country_only = "," not in f["place"] and re.sub(r"\W", "", norm(f["place"])) in COUNTRY
                if f["place"] and not country_only and not (place and same_place(f["place"], tree, place)):
                    add(f"{label}, место: **{f['place']}** (у нас: {place_text(tree, place) if place else '—'})", src)
            for f in facts:
                txt = " ".join(x for x in (f["date"], f["place"], f"«{f['content']}»" if f["content"] else "") if x)
                if f["type"] not in ("BIRT", "DEAT") and txt:
                    add(f"{f['title'].lower().rstrip(':')}: {txt}" + (f" [{'; '.join(f['sources'])}]" if f["sources"] else ""), src)
            for x in prof.get("family") or []:
                if x["name"] and not skip.match(x["name"]) and first_key(x["name"]) not in rel_keys:
                    add(f"родня — {x['rel']}: {x['name']} {x['lifespan']}".rstrip(), src)
        if rows:
            shown += 1
            trees = list(dict.fromkeys(f"{m['site_name'].strip()} ({m['manager']}, {m['country']}) #{m['id']}" for m in it["matches"]))
            L += [f"## [[{p.stem}]] — у нас: {p.fm.get('born') or '?'} – {p.fm.get('died') or '?'}; на сайте #{our}", "",
                  f"Деревья ({len(trees)}): " + " · ".join(trees), ""]
            L += [f"- [ ] {r} — *{', '.join(dict.fromkeys(s))}*" for r, s in rows.items()] + [""]
    if not shown:
        L.append("Расхождений нет.")
    OUT.mkdir(parents=True, exist_ok=True)
    rep = OUT / f"_MyHeritage_сверка{'_предки' if only else ''}_{date.today():%Y-%m-%d}.md"
    rep.write_text("\n".join(L).rstrip() + "\n")
    print(f"людей с расхождениями: {shown}; отчёт: {rep.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
