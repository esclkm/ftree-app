#!/usr/bin/env python3
"""Ветка рода → файл GEDCOM для общего дерева FamilySearch и список работ к нему (сам скрипт на сайт не пишет).

Зачем. В общем дереве FamilySearch (Family Tree) один человек — одна карточка на весь мир. Кто там есть, к тому сайт сам
подбирает записи из указателей (у нас — метрики Гродненской губернии, коллекция 4166194), и его видят другие
исследователи. Писать в дерево программой нельзя: доступ к API дают только организациям, а робот в браузере нарушает
условия сайта. Официальный путь — загрузить GEDCOM на familysearch.org и сравнить с деревом: сайт делит людей на
«возможно, уже есть», «уже есть» и «добавить», решение по каждому — за Павлом. Этот скрипт готовит файл и список.

Кто попадает:
- кровная родня веток (`lineage` в карточке; по умолчанию — `branches` из ftree.toml [familysearch.export]), родство «доказано»
  или «вероятно» (cards/kinship.py); «возможно» и ниже — нет: в общем дереве догадка быстро становится фактом;
- только те, кого сайт покажет умершими: есть дата смерти или рождён больше 110 лет назад (год рождения неизвестен —
  оценка по старшему ребёнку: родитель старше хотя бы на 15 лет). Старше AGE (70) без даты смерти сайт считает живыми и
  прячет — они не идут (ключ `--living` — пустить);
- супруги вошедших — на тех же условиях (без их родителей);
- без заглушек («Первая жена …», «Unknown») и без людей с одним именем («Агата», «Witold») — сайту не с чем сверять.

Источники — только найденные документы (происхождение «найдено»), с местом в источнике из фактов. Семейные записи
разговоров и заметки в файл не идут.

    tools/py tools/scripts/familysearch_export.py build [--branch Ясеневы,Дубняки] [--proven] [--living [--age 70]]
    tools/py tools/scripts/familysearch_export.py bridge [--branch Ясеневы,Дубняки] [--depth 4]   # мост от Павла
    tools/py tools/scripts/familysearch_export.py link "<имя карточки>" <FamilySearch ID>   # после сверки на сайте

Выход: `3_research/tree_data/familysearch/<ветка>.ged` и `<ветка> — список.md` (сборка, не в git). Сверенные номера
FamilySearch — `3_research/tree_data/familysearch_match.json` (в git): при следующей сборке человек помечен «уже связан».
"""
import argparse
import json
import re
import sys
from datetime import date

from cards import kinship
from cards.tree import load
from myheritage_update import split_name, write_ged
from paths import TREE_DATA, tree_conf

OUT = TREE_DATA / "familysearch"
MATCH = TREE_DATA / "familysearch_match.json"
GOOD = ("proven", "likely")
LEVEL_RU = {"proven": "доказано", "likely": "вероятно"}
GAP = 15      # родитель старше ребёнка хотя бы на столько лет
DEAD = 110    # рождён раньше — FamilySearch и так считает умершим
FS_ID = re.compile(r"^[A-Z0-9]{4}-[A-Z0-9]{2,4}$")
# заглушки («Первая жена Прокопа Ясенева», «Unknown …») в общее дерево не идут — как и на Familio (familio_sync.py pack)
STUB = re.compile(r"(Unknown|\?|Первая|Первый|Вторая|Второй|Муж|Жена|Неизвестн\w*)\b")


def stub(p):
    """Заглушка или имя без фамилии («Агата», «Witold», «Дубняк») — сайту не с чем сверять."""
    return bool(STUB.match(p.name)) or len(re.sub(r"\s*\(.*?\)", "", p.name).split()) < 2


def alias_ok(a, given_names):
    """Другое имя — только «Имя Фамилия»: без отчества (правило проекта) и без пояснений «żona Witolda», «córka …».
    Отчество на месте фамилии тоже не берём: «Анна Прокоповна», «Агата Прокопова» (дочь Прокопа) — не фамилии."""
    w = re.sub(r"\s*\(.*?\)", "", str(a)).split()
    if len(w) != 2 or not all(x[:1].isupper() for x in w):
        return False
    sur = w[1]
    return not (re.search(r"(овна|евна|ична)$", sur) or re.sub(r"(ова|ева)$", "", sur) in given_names)


def birth_bound(T, p):
    """Самый поздний возможный год рождения: из карточки, иначе старший ребёнок минус GAP; не знаем — None."""
    if p.born and p.born.last_year:
        return p.born.last_year
    kids = [T.people[c].born.first_year for c in p.children if c in T.people and T.people[c].born]
    kids = [y for y in kids if y]
    return min(kids) - GAP if kids else None


def place(T, pid):
    """«Вербичи, Беларусь» — место и всё, что выше него."""
    parts = []
    while pid and pid in T.places and len(parts) < 8:
        parts.append(T.places[pid].name)
        pid = T.places[pid].parent
    return ", ".join(parts)


def select(T, branches, age, good=GOOD, living=False):
    """→ (вошли: {cr_id: причина}, не вошли: [(человек, причина)], сколько молодых без года не перечислено).
    living=False — только те, кого сайт покажет умершим (deceased); иначе ещё и старше AGE, о смерти которых не знаем."""
    K = kinship.levels(T)
    cutoff = date.today().year - age - 1   # «больше AGE лет»: в 2026 при AGE 70 — рождён не позже 1955
    take, skip, quiet = {}, [], 0

    def fits(p):
        if deceased(T, p):
            return True
        b = birth_bound(T, p)
        return living and b is not None and b <= cutoff

    def maybe_dead(p):
        """Года нет, но родитель родился до 1916 — человек мог умереть: стоит найти год, тогда войдёт."""
        par = [T.people[x] for x in p.father[:1] + p.mother[:1] if x in T.people]
        return any((birth_bound(T, x) or 9999) < 1916 for x in par)

    for p in T.people.values():
        if not set(branches) & set(p.fm.get("lineage") or []) or stub(p):
            continue
        lvl = K[p.id][0]
        b = birth_bound(T, p)
        if lvl not in good:
            skip.append((p, f"родство «{lvl}»"))
        elif fits(p):
            take[p.id] = "ветка"
        elif b is None:
            if maybe_dead(p):
                skip.append((p, "нет года и даты смерти (родители — до 1916, мог умереть)"))
            else:
                quiet += 1
        elif b <= cutoff:
            skip.append((p, f"старше {age}, о смерти не знаем — на сайте был бы скрыт"))
        # моложе AGE и живы — не перечисляем
    for pid in list(take):
        for s in T.people[pid].spouses:
            sp = T.people.get(s)
            if sp and s not in take and not stub(sp) and K[s][0] in good and fits(sp):
                take[s] = "супруг"
    return take, skip, quiet


def deceased(T, p):
    b = birth_bound(T, p)
    return bool(p.died) or (b is not None and b <= date.today().year - DEAD)


def build(branches, age, proven=False, living=False):
    T = load()
    take, skip, quiet = select(T, branches, age, GOOD[:1] if proven else GOOD, living)
    head = [f"Живые моложе {age + 1} лет и {quiet} человек без года, у кого и родители без года или моложе 1916, — "
            "не перечислены."]
    write(T, take, skip, "+".join(branches), head)


def bridge(branches, depth):
    """Мост Павел → родители → предки: Павел, его прямые предки до depth-го колена (живые тоже — на сайте скрыты) и
    умершие братья и сёстры предков из веток branches (не глубже прадедов Павла). Живых, кроме прямых, и супругов
    боковых — нет. Родители и деды Павла — из любой ветки: без них мост не сойдётся."""
    T = load()
    K = kinship.levels(T)
    me = next(p for p in T.people.values() if p.fm.get("gedcom_id") == kinship.ROOT)
    take, skip, gen = {me.id: "я"}, [], {me.id: 0}
    todo = [me.id]
    while todo:
        p = T.people[todo.pop()]
        for x in p.father[:1] + p.mother[:1]:
            q = T.people.get(x)
            if not q or x in gen or gen[p.id] + 1 > depth or stub(q):
                continue
            gen[x] = gen[p.id] + 1
            lines = set(q.fm.get("lineage") or [])
            if gen[x] <= 2 or lines & set(branches):   # родители и деды — всегда: без них мост не сойдётся
                if K[x][0] in GOOD:
                    take[x] = f"прямой предок, колено {gen[x]}"
                    todo.append(x)
                else:
                    skip.append((q, f"родство «{K[x][0]}»"))
    for a in [x for x in take if 2 <= gen.get(x, 0) <= 3 and set(T.people[x].fm.get("lineage") or []) & set(branches)]:
        for c in T.people[a].children:
            q = T.people.get(c)
            if q and c not in take and not stub(q) and K[c][0] in GOOD and deceased(T, q):
                take[c] = "умер; брат или сестра прямого предка"
    head = ["**Живые из этого файла в общее дерево не перейдут** — FamilySearch из GEDCOM их не переносит. Павла, отца и",
            "мать связать руками на своей карточке («Add father» / «Add mother»), дальше — сравнение (Compare) файла."]
    write(T, take, skip, "мост_" + "+".join(branches), head)


def write(T, take, skip, branch, head):
    match = json.loads(MATCH.read_text()) if MATCH.exists() else {}
    order = sorted(take, key=lambda i: (birth_bound(T, T.people[i]) or 9999, T.people[i].name))
    xref = {pid: f"@I{n}@" for n, pid in enumerate(order, 1)}
    used_src = {}

    # семьи: пара родителей (или один родитель) → дети; пары без детей — тоже семья
    fams = {}
    for pid in order:
        p = T.people[pid]
        par = tuple(x for x in (p.father[:1] + p.mother[:1]) if x in take)
        if par:
            fams.setdefault(frozenset(par), []).append(pid)
        for s in p.spouses:
            if s in take:
                fams.setdefault(frozenset((pid, s)), [])
    fx = {k: f"@F{n}@" for n, k in enumerate(fams, 1)}

    L = ["0 HEAD", "1 SOUR ftree", f"2 NAME {tree_conf('familysearch.export.title') or tree_conf('tree.title', 'ftree')}", "1 GEDC", "2 VERS 5.5.1", "2 FORM LINEAGE-LINKED",
         "1 CHAR UTF-8", f"1 DATE {date.today().strftime('%d %b %Y').upper()}", "1 SUBM @U1@",
         "0 @U1@ SUBM", f"1 NAME {tree_conf('familysearch.export.submitter', 'ftree')}"]
    rows = []
    given_names = {split_name(x.name)[0] for x in T.people.values() if split_name(x.name)}
    for pid in order:
        p = T.people[pid]
        given, surname = split_name(p.name) or (p.name, "")
        L += [f"0 {xref[pid]} INDI", f"1 NAME {given} /{surname}/", f"2 GIVN {given}", f"2 SURN {surname}"]
        for a in (a for a in p.fm.get("aliases") or [] if alias_ok(a, given_names)):
            ga = split_name(a)
            if ga and f"{ga[0]} {ga[1]}" != f"{given} {surname}":
                L += [f"1 NAME {ga[0]} /{ga[1]}/", "2 TYPE aka"]
        L.append(f"1 SEX {p.sex}")
        if p.born or p.birth_place:
            L.append("1 BIRT")
            L += [f"2 DATE {p.born.gedcom()}"] if p.born and p.born.kind != "PHRASE" else []
            L += [f"2 PLAC {place(T, p.birth_place)}"] if p.birth_place else []
        dead = deceased(T, p)
        if p.died or p.death_place:
            L.append("1 DEAT")
            L += [f"2 DATE {p.died.gedcom()}"] if p.died and p.died.kind != "PHRASE" else []
            L += [f"2 PLAC {place(T, p.death_place)}"] if p.death_place else []
        elif dead:
            L.append("1 DEAT Y")
        docs = []
        for sid in dict.fromkeys(p.sources):
            S = T.sources.get(sid)
            if not S or S.provenance != "found":
                continue
            used_src.setdefault(sid, f"@S{len(used_src) + 1}@")
            locs = dict.fromkeys(r.locator for f in p.facts for r in f.refs if r.source == sid and r.locator)
            L.append(f"1 SOUR {used_src[sid]}")
            if locs:
                L.append(f"2 PAGE {'; '.join(locs)}"[:240])
            docs.append(S.title)
        for k, members in fams.items():
            if pid in members:
                L.append(f"1 FAMC {fx[k]}")
            if pid in k:
                L.append(f"1 FAMS {fx[k]}")
        b = p.born.ru() if p.born else (f"до {birth_bound(T, p)} (по детям)" if birth_bound(T, p) else "?")
        d = p.died.ru() if p.died else ("умер(ла)" if dead else "жив(а) → на сайте скрыт, связать руками")
        rows.append((p, b, d, take[pid], docs))

    for k, members in fams.items():
        L.append(f"0 {fx[k]} FAM")
        for x in sorted(k, key=lambda i: T.people[i].sex != "M"):
            L.append(f"1 {'HUSB' if T.people[x].sex == 'M' else 'WIFE'} {xref[x]}")
        L += [f"1 CHIL {xref[c]}" for c in members]
    for sid, x in used_src.items():
        S = T.sources[sid]
        L += [f"0 {x} SOUR", f"1 TITL {S.title}"] + ([f"1 REPO {S.repository}"[:240]] if S.repository else [])
    L.append("0 TRLR")
    # REPO в GEDCOM 5.5.1 — ссылка на запись; программы читают и текст, но надёжнее NOTE
    L = [re.sub(r"^1 REPO ", "1 NOTE Хранится: ", l) for l in L]

    OUT.mkdir(parents=True, exist_ok=True)
    ged = OUT / f"{branch}.ged"
    write_ged(ged, L)
    md = OUT / f"{branch} — список.md"
    md.write_text(worklist(branch, head, rows, skip, match), encoding="utf-8")
    print(f"{ged.relative_to(TREE_DATA.parent.parent)}: людей {len(order)}, семей {len(fams)}, документов {len(used_src)}")
    print(f"{md.relative_to(TREE_DATA.parent.parent)}: не вошли {len(skip)}")


def worklist(branch, head, rows, skip, match):
    title = f"мост от Павла и ветки «{branch[5:]}»" if branch.startswith("мост_") else f"ветка «{branch}»"
    out = [f"# FamilySearch — {title}: список работ ({date.today():%d.%m.%Y})", "",
           "Сборка `familysearch_export.py build` — не править руками. Порядок — от старших к младшим: сначала связать",
           "предков, тогда сайт подскажет совпадения для их детей. Найден на сайте — `familysearch_export.py link`.", ""]
    out += head + ["", "| № | Человек | Родился | Умер | Почему | Документов | FamilySearch |", "|---|---|---|---|---|---|---|"]
    for n, (p, b, d, why, docs) in enumerate(rows, 1):
        fs = match.get(p.id, {}).get("fs", "")
        out.append(f"| {n} | [[{p.stem}]] | {b} | {d} | {why} | {len(docs)} | {fs or '—'} |")
    out += ["", "## Не вошли", ""] if skip else []
    out += [f"- [[{p.stem}]] — {why}" for p, why in sorted(skip, key=lambda r: r[0].name)]
    return "\n".join(out) + "\n"


def link(stem, fs):
    if not FS_ID.match(fs):
        sys.exit(f"«{fs}» — не номер FamilySearch (вида G1Q1-MKT)")
    T = load()
    p = next((x for x in T.people.values() if x.stem == stem), None)
    if not p:
        sys.exit(f"нет карточки «{stem}»")
    match = json.loads(MATCH.read_text()) if MATCH.exists() else {}
    match[p.id] = {"stem": p.stem, "fs": fs, "date": f"{date.today():%Y-%m-%d}"}
    MATCH.write_text(json.dumps(match, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{p.stem} → {fs}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--branch", default=tree_conf("familysearch.export.branches", ""),
                   help="ветки через запятую (ftree.toml; по умолчанию — [familysearch.export] branches)")
    b.add_argument("--age", type=int, default=70)
    b.add_argument("--proven", action="store_true", help="только «доказано», без «вероятно»")
    b.add_argument("--living", action="store_true",
                   help="и старше --age без даты смерти (на сайте — скрытые «живые»; по умолчанию не идут)")
    m = sub.add_parser("bridge", help="мост от Павла к предкам + неглубоко другие ветки")
    m.add_argument("--branch", default=tree_conf("familysearch.export.bridge_branches", ""),
                   help="ветки через запятую (ftree.toml; по умолчанию — [familysearch.export] bridge_branches)")
    m.add_argument("--depth", type=int, default=4, help="колен вверх от Павла (4 — прапрадеды)")
    k = sub.add_parser("link")
    k.add_argument("stem")
    k.add_argument("fs")
    a = ap.parse_args()
    if a.cmd in ("build", "bridge") and not a.branch:
        ap.error("нужен --branch (или [familysearch.export] в ftree.toml)")
    if a.cmd == "build":
        build(a.branch.split(","), a.age, a.proven, a.living)
    elif a.cmd == "bridge":
        bridge(a.branch.split(","), a.depth)
    else:
        link(a.stem, a.fs)


if __name__ == "__main__":
    main()
