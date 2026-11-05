#!/usr/bin/env python3
"""Возможные связи — сверка руками: страница «Сверка» и три решения.

Зачем. Человек из метрики может оказаться нашим («Сергий 1894 из Вербичей — наш Сергей Ясенев?»), но пока это только
подозрение. Оно записано полем в карточке (maybe_same / maybe_kin, подробно — tools/scripts/cards/possible.py). Здесь —
все такие пары на одной странице, карточки рядом (годы, места, родители, источники), и под каждой — три готовые команды:

  одно лицо    → merge_cards.py: две карточки сливаются в одну, с доказательством;
  родня — да   → possible.py yes: настоящая связь (отец, мать, сын, дочь, муж, жена) по документу;
  нет          → possible.py no: проверено «нет» (not_same / not_kin) — пара больше не всплывёт ни в одном поиске.
Ниже — пары, которые никто не отмечал, но похожи (auto: одно имя, та же фамилия или место, годы не спорят); у них
четвёртое решение — possible.py maybe: отметить «возможно» (maybe_same / maybe_kin с --as) с причиной.
То же — на сайте: «Источники → Сверка» (data/review.json, страница web/src/app/pages/OtherPages.tsx).

  tools/py tools/scripts/possible.py                   # страница 3_research/tree/_СВЕРКА.md, в ответ — сколько пар
  tools/py tools/scripts/possible.py no "Сергий (д581, 1894)" "Сергей Ясенев" --why "[[ГАСО — …]], д. 600: другой отец"
  tools/py tools/scripts/possible.py yes "<карточка>" "<кто>" --as отец --why "[[Источник]], стр. 3: «сын Ивана»"
  … --apply   # без него — только показать, что поменяется

Брат, сестра, дядя — не одной связью, а через общего родителя: сначала его карточка, потом yes … --as отец.
Решение — коммитом; после — check_tree.py (сам, хуком), а после yes — ещё assign_lineage.py.
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cards  # noqa: E402
import paths  # noqa: E402
from cards.notes import N, as_list, link_target  # noqa: E402
from name_forms import GIVEN  # noqa: E402 — ряды равных имён, общие с поиском по метрикам

PAGE = paths.TREE / "_СВЕРКА.md"
PEOPLE = paths.TREE / "people"
KIN_RU = {"parent": "отец / мать", "child": "сын / дочь", "sibling": "брат / сестра", "pibling": "дядя / тётя",
          "nibling": "племянник / племянница", "cousin": "двоюродный брат / сестра", "grandparent": "дед / бабушка",
          "grandchild": "внук / внучка", "spouse": "муж / жена", "kin": "родня"}
# yes --as: кем «кто» приходится карточке → (поле в карточке, поле у «кто»)
LINKS = {"отец": ("father", "children"), "мать": ("mother", "children"), "сын": ("children", "father"),
         "дочь": ("children", "mother"), "муж": ("spouse", "spouse"), "жена": ("spouse", "spouse")}


# ─── похожие пары, которых никто не отмечал ─────────────────────────────────────────────────────────────────────

UNNAMED = ("unknown", "неизвестн", "без связей")
# одно имя в разных формах: церковная (метрики) ↔ бытовая ↔ польская; сравниваем по первой форме ряда
CANON = {v: row[0] for row in GIVEN for v in row}


def given_match(a, b):
    import tree as T
    a, b = CANON.get(a.lower(), a), CANON.get(b.lower(), b)
    return T.word_match(a, b)


def related(a, b):
    """Уже связаны: родитель, ребёнок, супруг или общий родитель."""
    return b.id in a.father + a.mother + a.children + a.spouses or bool(set(a.father + a.mother) & set(b.father + b.mother))


def auto(tree, limit=80):
    """Пары, похожие на одного человека, но ещё не отмеченные (maybe_same), не связанные и не отвергнутые (not_same):
    одно имя по написанию (Сергей = Сергий = Siarhei), та же фамилия — или фамилии у одного нет, но место рождения то же,
    годы не спорят (рождение и смерть — не дальше 2 лет), и есть хоть одно совпадение сверх имени: год, место, имя отца
    или матери. Разные известные отцы с разными именами — не он. → [(a, b, [что совпало], очки)], сильные — первыми."""
    import tree as T
    year = lambda g: g.first_year if g else None
    place = lambda i: tree.places[i].stem if i in tree.places else ""
    first = lambda p: next(iter(T.tokens(p.name)), "")
    people = [p for p in tree.people.values() if p.name and not any(u in p.name.lower() for u in UNNAMED)]
    buckets = {}
    for p in people:
        for k in T.keys(CANON.get(first(p).lower(), first(p))) if first(p) else ():
            buckets.setdefault(T.stem_key(k), []).append(p)
    seen, out = set(), []
    for group in buckets.values():
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                pair = frozenset((a.id, b.id))
                if pair in seen or a.sex != b.sex or related(a, b) or tree.ruled_out(a.id, b.id, "same") or \
                        any(x.person == b.id for x in a.possible):
                    continue
                seen.add(pair)
                ta, tb = T.tokens(a.name), T.tokens(b.name)
                if not given_match(ta[0], tb[0]):
                    continue
                sa, sb = (ta[-1] if len(ta) > 1 else ""), (tb[-1] if len(tb) > 1 else "")
                why = ["имя"]
                if sa and sb:
                    if not T.word_match(sa, sb):
                        continue
                    why.append("фамилия")
                elif not (a.birth_place and a.birth_place == b.birth_place):
                    continue   # фамилии у одного нет — нужно хотя бы то же место рождения
                if any(x is not None and y is not None and abs(x - y) > 2 for x, y in
                       ((year(a.born), year(b.born)), (year(a.died), year(b.died)))):
                    continue
                fa, fb = a.father[:1], b.father[:1]
                if fa and fb and fa != fb and not given_match(first(tree.people[fa[0]]), first(tree.people[fb[0]])):
                    continue
                score = 0
                if year(a.born) and year(a.born) == year(b.born):
                    why.append(f"год рождения {year(a.born)}"); score += 2
                if a.birth_place and a.birth_place == b.birth_place:
                    why.append(f"место рождения {place(a.birth_place)}"); score += 2
                if year(a.died) and year(a.died) == year(b.died):
                    why.append(f"год смерти {year(a.died)}"); score += 1
                if a.death_place and a.death_place == b.death_place:
                    why.append(f"место смерти {place(a.death_place)}"); score += 1
                for key, word in (("father", "отец"), ("mother", "мать")):
                    x, y = getattr(a, key)[:1], getattr(b, key)[:1]
                    if x and y and (x == y or given_match(first(tree.people[x[0]]), first(tree.people[y[0]]))):
                        why.append(f"{word} {first(tree.people[x[0]])}"); score += 2
                alone = lambda p: not (p.father or p.mother or p.spouses or p.children)
                if score or (len(why) > 1 and (alone(a) or alone(b))):   # одинокая карточка — дубль или найденный
                    a, b = sorted((a, b), key=lambda p: (bool(p.fm.get("gedcom_id")), p.stem))   # найденная — слева
                    out.append((a, b, why, score))
    return sorted(out, key=lambda r: (-r[3], r[0].stem))[:limit]


# ─── страница ──────────────────────────────────────────────────────────────────────────────────────────────────────

def pairs(tree):
    """[(a, b, Possible)] — каждая пара один раз, со стороны той карточки, где записана."""
    out, seen = [], set()
    for p in sorted(tree.people.values(), key=lambda p: p.stem):
        for x in p.possible:
            if not x.back and (x.kind, frozenset((p.id, x.person))) not in seen:   # записано в обеих — один раз
                seen.add((x.kind, frozenset((p.id, x.person))))
                out.append((p, tree.people[x.person], x))
    return sorted(out, key=lambda t: (t[2].kind != "same", t[0].stem))


def life(p):
    b, d = p.born.ru() if p.born else "?", p.died.ru() if p.died else ""
    return f"{b}–{d}" if d else (b if p.born else "—")


def column(tree, p):
    place = lambda i: tree.places[i].stem if i in tree.places else ""
    names = lambda ids: ", ".join(f"[[{tree.people[i].stem}]]" for i in ids) or "—"
    srcs = list(dict.fromkeys(p.sources + [r.source for f in p.facts for r in f.refs]))
    return {"Карточка": f"[[{p.stem}]] · `{p.id}`" + (f" · {str(p.fm['gedcom_id']).strip('@')}" if p.fm.get("gedcom_id") else ""),
            "Годы": life(p),
            "Родился": place(p.birth_place) or "—", "Умер": place(p.death_place) or "—",
            "Родители": names(p.father + p.mother), "Супруги": names(p.spouses), "Дети": names(p.children),
            "Ветка": ", ".join(map(str, as_list(p.fm.get("lineage")) + as_list(p.fm.get("lineage_by_marriage")))) or "—",
            "Источники": "; ".join(f"[[{tree.sources[s].stem}]]" for s in srcs[:4]) + (f"; … ещё {len(srcs) - 4}" if len(srcs) > 4 else "")
            if srcs else "—"}


def keep_drop(a, b):
    """Какую карточку оставить при слиянии (как в merge_cards.py): с gedcom_id; иначе связанную с семьёй."""
    score = lambda p: (bool(p.fm.get("gedcom_id")), bool(p.father or p.mother or p.spouses or p.children))
    return (b, a) if score(b) > score(a) else (a, b)


def commands(a, b, kind="same", marked=True):
    """Три решения по паре — готовые команды (страница «Сверка» и сайт); у найденной скриптом — ещё «отметить»."""
    keep, drop = keep_drop(a, b)
    run = "rodo "
    out = {"same": f'{run}merge-cards "{drop.stem}" "{keep.stem}" --why "[[Источник]], стр.: что совпало"',
           "no": f'{run}possible no "{a.stem}" "{b.stem}"{"" if marked else " --same"} --why "почему нет: документ, что не сошлось"'}
    if marked:
        out["yes"] = (f'{run}possible yes "{a.stem}" "{b.stem}" --as <отец|мать|сын|дочь|муж|жена> '
                      '--why "[[Источник]], стр.: что сказано"')
    else:
        out["mark"] = f'{run}possible maybe "{a.stem}" "{b.stem}" --why "на чём держится, что докажет"'
    return out


def page(tree):
    rows = pairs(tree)
    out = ["# Сверка — возможные связи", "",
           "> Собрано `rodo possible` — не править руками: пересоберётся. Подозрение записано полем "
           "`maybe_same` / `maybe_kin` в карточке; на чём держится — строка в её «Фактах» или «Открытых вопросах».", "",
           f"**Что это.** Пары карточек, про которые подозреваем: это один человек или родня. Карточки рядом — сравнить "
           f"годы, места, родителей, источники. Под каждой парой — три решения командой (сначала без `--apply` — "
           f"посмотреть). Решение — коммитом. Пар: **{len(rows)}**.", ""]
    for n, (a, b, x) in enumerate(rows, 1):
        what = "возможно, тот же человек" if x.kind == "same" else f"возможно, {KIN_RU.get(x.relation, 'родня')}"
        out += [f"## {n}. {a.stem} ↔ {b.stem} — {what}", ""]
        if x.kind == "kin":
            out += [f"«{b.stem}» приходится «{a.stem}»: {KIN_RU.get(x.relation, 'родня')}?", ""]
        ca, cb = column(tree, a), column(tree, b)
        out += ["| | A | B |", "|---|---|---|"] + [f"| {k} | {ca[k]} | {cb[k]} |" for k in ca] + [""]
        out += [f"**На чём держится:** {x.reason or '— не записано (строка со ссылкой в «Открытых вопросах» карточки A)'}", ""]
        c = commands(a, b, x.kind)
        out += ["**Решения:**", "", f"- одно лицо — `{c['same']}`", f"- родня — да — `{c['yes']}`", f"- нет — `{c['no']}`", ""]
    found = auto(tree)
    out += [f"## Найдено автоматически — {len(found)}", "",
            "Никто не отмечал, но похожи: одно имя (с церковными и польскими формами), та же фамилия или то же место "
            "рождения, годы не спорят. Сначала посмотреть карточки; похоже — отметить (`maybe_same`), нет — `not_same`.", ""]
    for n, (a, b, why, _) in enumerate(found, 1):
        c = commands(a, b, marked=False)
        ca, cb = column(tree, a), column(tree, b)
        out += [f"### {n}. {a.stem} ↔ {b.stem}", "", f"Совпало: {', '.join(why)}.", "",
                "| | A | B |", "|---|---|---|"] + [f"| {k} | {ca[k]} | {cb[k]} |" for k in ca] + [""]
        out += [f"- отметить «возможно» — `{c['mark']}`", f"- одно лицо — `{c['same']}`", f"- нет — `{c['no']}`", ""]
    no = sorted({(min(p.stem, tree.people[i].stem), max(p.stem, tree.people[i].stem), k)
                 for p in tree.people.values() for k, i in p.ruled_out})
    out += [f"## Проверено — нет ({len(no)})", "",
            "Эти пары поиск больше не предлагает (`not_same` / `not_kin`); почему — зачёркнутая строка в «Открытых "
            "вопросах» карточки.", ""]
    out += [f"- [[{a}]] ↔ [[{b}]] — {'не одно лицо' if k == 'same' else 'не родня'}" for a, b, k in no] or ["- пока нет"]
    return out, len(rows)


# ─── правка свойств карточки (строками: остальное в шапке не трогаем) ───────────────────────────────────────────

def split(text):
    m = re.match(r"---\n(.*?)\n---\n?", text, re.S)
    return m.group(1).split("\n"), text[m.end():]


def get_list(fm, key):
    """Значения свойства как в файле: 'key: x' или 'key:' + строки '  - x' (кавычки сняты)."""
    for i, ln in enumerate(fm):
        if ln == f"{key}:" or ln.startswith(f"{key}: "):
            if ln != f"{key}:":
                return [ln.split(": ", 1)[1].strip().strip('"')]
            out = []
            for nxt in fm[i + 1:]:
                if not nxt.startswith("  - "):
                    break
                out.append(nxt[4:].strip().strip('"'))
            return out
    return []


def set_list(fm, key, vals, after=None):
    """Заменить свойство (или убрать, если vals пуст). Новое — после after или перед sources."""
    q = lambda v: f'"{v}"' if str(v).startswith("[[") else str(v)
    block = [] if not vals else [f"{key}: {q(vals[0])}"] if len(vals) == 1 else [f"{key}:"] + [f"  - {q(v)}" for v in vals]
    for i, ln in enumerate(fm):
        if ln == f"{key}:" or ln.startswith(f"{key}: "):
            j = i + 1
            while j < len(fm) and fm[j].startswith("  - "):
                j += 1
            return fm[:i] + block + fm[j:]
    at = next((i for i, ln in enumerate(fm) if after and ln.startswith(f"{after}")), None)
    if at is not None:
        at += 1
        while at < len(fm) and fm[at].startswith("  - "):
            at += 1
    else:
        at = next((i for i, ln in enumerate(fm) if ln.startswith("sources:")), len(fm))
    return fm[:at] + block + fm[at:]


def drop_pair(fm, key, stem, cid):
    """Убрать из maybe_*/not_* ссылку на stem (и её номер)."""
    names, ids = get_list(fm, key), get_list(fm, key + "_id")
    keep = [(n, ids[i] if len(ids) == len(names) else None) for i, n in enumerate(names)
            if link_target(n) != stem and (len(ids) != len(names) or ids[i] != cid)]
    fm = set_list(fm, key, [n for n, _ in keep])
    return set_list(fm, key + "_id", [i for _, i in keep if i] if all(i for _, i in keep) else [])


def add_pair(fm, key, value, cid):
    names, ids = get_list(fm, key), get_list(fm, key + "_id")
    if len(ids) != len(names):
        ids = []
    fm = set_list(fm, key, names + [value])
    return set_list(fm, key + "_id", ids + [cid] if ids or not names else [], after=key)


def add_line(body, title, line):
    """Строку — в конец раздела «### title»; нет раздела — новый, перед «Заметками» или «## …» (порядок — check_cards)."""
    m = re.search(rf"^### {re.escape(title)}\n(.*?)(?=^#{{1,3}} |\Z)", body, re.S | re.M)
    if m:
        end = m.start(1) + len(m.group(1).rstrip("\n"))
        return body[:end] + "\n" + line + body[end:]
    facts = body.find("### Факты")
    anchor = re.compile(r"^### Заметки|^## ", re.M).search(body, facts + 1) if facts >= 0 else \
        re.compile(r"^## Источники", re.M).search(body)
    sec = f"### {title}\n\n{line}\n\n"
    return body[:anchor.start()] + sec + body[anchor.start():] if anchor else body.rstrip() + "\n\n" + sec


def card(tree, stem):
    p = tree.person(N(stem))
    if not p:
        sys.exit(f"нет карточки: {stem}")
    path = PEOPLE / f"{p.stem}.md"
    return p, path, N(path.read_text(encoding="utf-8"))


def save(path, fm, body, apply, changes):
    changes.append(path)
    if apply:
        path.write_text("---\n" + "\n".join(fm) + "\n---\n" + body, encoding="utf-8")


def decide_no(tree, a, b, why, kind, apply):
    pa, path_a, ta = card(tree, a)
    pb, path_b, tb = card(tree, b)
    kinds = {x.kind for x in pa.possible if x.person == pb.id}
    kind = kind or (kinds.pop() if len(kinds) == 1 else None)
    if not kind:
        sys.exit("пара не стоит в maybe_* — укажите --same или --kin")
    fa, ba = split(ta)
    fb, bb = split(tb)
    fa, fb = drop_pair(fa, f"maybe_{kind}", pb.stem, pb.id), drop_pair(fb, f"maybe_{kind}", pa.stem, pa.id)
    fa = add_pair(fa, f"not_{kind}", f"[[{pb.stem}]]", pb.id)
    q = "тот же человек" if kind == "same" else "родня"
    ba = add_line(ba, "Открытые вопросы", f"- ✅ ~~[[{pb.stem}]] — {q}?~~ Нет: {why}")
    changes = []
    save(path_a, fa, ba, apply, changes)
    if fb != split(tb)[0]:
        save(path_b, fb, bb, apply, changes)
    return changes, f"not_{kind}: [[{pb.stem}]] — в карточку «{pa.stem}», почему — строкой ✅ в «Открытых вопросах»"


def decide_maybe(tree, a, b, why, role, apply):
    """Отметить пару: maybe_same (или maybe_kin «[[B]] — брат?») в карточке A и строку со ссылкой в её «Открытых вопросах»."""
    pa, path_a, ta = card(tree, a)
    pb, _, _ = card(tree, b)
    fa, ba = split(ta)
    if role:
        fa = add_pair(fa, "maybe_kin", f"[[{pb.stem}]] — {role}?", pb.id)
        q = f"{role}?"
    else:
        fa = add_pair(fa, "maybe_same", f"[[{pb.stem}]]", pb.id)
        q = "тот же человек?"
    ba = add_line(ba, "Открытые вопросы", f"- [[{pb.stem}]] — {q} {why}")
    changes = []
    save(path_a, fa, ba, apply, changes)
    return changes, f"{'maybe_kin' if role else 'maybe_same'}: [[{pb.stem}]] — в карточку «{pa.stem}», причина — в «Открытых вопросах»"


def decide_yes(tree, a, b, role, why, apply):
    if role not in LINKS:
        sys.exit(f"--as {role}: одной связью — только {', '.join(LINKS)}; брат, сестра, дядя — через общего родителя")
    if not why.startswith("[["):
        sys.exit("--why: нужна ссылка на карточку источника и место в нём: \"[[Источник]], стр. 3: «сын Ивана»\"")
    pa, path_a, ta = card(tree, a)
    pb, path_b, tb = card(tree, b)
    mine, theirs = LINKS[role]
    sex = {"father": "M", "mother": "F"}
    if mine in sex and pb.sex != sex[mine] or theirs in sex and pa.sex != sex[theirs]:
        sys.exit("пол не подходит к связи — проверьте, кто кому кем приходится")
    if mine in ("father", "mother") and getattr(pa, mine):
        sys.exit(f"у «{pa.stem}» уже есть {mine} — решить руками")
    if theirs in ("father", "mother") and getattr(pb, theirs):
        sys.exit(f"у «{pb.stem}» уже есть {theirs} — решить руками")
    fa, ba = split(ta)
    fb, bb = split(tb)
    for fm, key, other in ((fa, mine, pb), (fb, theirs, pa)):
        names, ids = get_list(fm, key), get_list(fm, key + "_id")
        many = key in ("children", "spouse")
        new_names = (names if many else []) + [f"[[{other.stem}]]"]
        new_ids = (ids if many and len(ids) == len(names) else []) + [other.id]
        fm[:] = set_list(set_list(fm, key, new_names), key + "_id", new_ids, after=key)
    for key in ("maybe_kin", "maybe_same"):
        fa, fb = drop_pair(fa, key, pb.stem, pb.id), drop_pair(fb, key, pa.stem, pa.id)
    ba = add_line(ba, "Факты (с источником)",
                  f"- **Родство:** [[{pb.stem}]] — {role} — *источник: {why} · уверенность: обычная*")
    changes = []
    save(path_a, fa, ba, apply, changes)
    save(path_b, fb, bb, apply, changes)
    return changes, f"{mine}: [[{pb.stem}]] у «{pa.stem}», {theirs}: [[{pa.stem}]] у «{pb.stem}»; факт со ссылкой на источник"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", default="page", choices=("page", "no", "yes", "maybe"))
    ap.add_argument("a", nargs="?", help="карточка, где записано подозрение")
    ap.add_argument("b", nargs="?", help="кого подозреваем")
    ap.add_argument("--why", help="no: почему нет; yes: [[источник]], место, что сказано")
    ap.add_argument("--as", dest="role", help="yes: кем B приходится A — отец, мать, сын, дочь, муж, жена")
    ap.add_argument("--same", action="store_true")
    ap.add_argument("--kin", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    tree = cards.load()
    if a.cmd == "page":
        lines, n = page(tree)
        PAGE.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Сверка: отмечено пар {n}, найдено автоматически {len(auto(tree))} → {PAGE.relative_to(paths.ROOT)}")
        return
    if not (a.a and a.b and a.why):
        sys.exit(f"{a.cmd} \"<карточка>\" \"<кто>\" --why \"…\"")
    if a.cmd == "maybe":
        changes, what = decide_maybe(tree, a.a, a.b, a.why, (a.role or "").lower(), a.apply)
    elif a.cmd == "no":
        changes, what = decide_no(tree, a.a, a.b, a.why, "same" if a.same else "kin" if a.kin else None, a.apply)
    else:
        changes, what = decide_yes(tree, a.a, a.b, (a.role or "").lower(), a.why, a.apply)
    print(what + "\nфайлы: " + ", ".join(p.name for p in changes))
    print("сделано. Дальше: possible.py (страница), коммит" + ("; assign_lineage.py" if a.cmd == "yes" else "")
          if a.apply else "(показ; записать — с --apply)")


if __name__ == "__main__":
    main()
