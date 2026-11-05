#!/usr/bin/env python3
"""Брак, развод, рождение ребёнка — у обоих сразу (правило Павла, 15.10.2026).

Событие на двоих записано у одного, а у второго нет или с другой датой — так было: акт о браке 20.01.1910 вписали
Агате Wierzbowska, а у мужа, Ивана Ясенева, осталось «Вербичи, 1910». Правка одной стороны пары — правка обеих.

Что проверяет:
  ОШИБКА  карточка: факт о браке (разводе) с точной датой (дд.мм.гггг в подписи или в начале текста) у одного супруга,
          а у другого нет факта о браке (разводе) с этой датой;
  ОШИБКА  биографии: в линиях жизни обоих супругов есть строка о свадьбе (разводе) друг с другом, а даты разные;
  ОШИБКА  линия жизни отстаёт от карточки: в карточке точная дата брака, в строке линии жизни — другая;
  ВНИМАНИЕ  у одного супруга в линии жизни свадьба есть, у другого (биография есть) — нет;
  ОШИБКА  рождение ребёнка: в линии жизни родителя строка о рождении ребёнка с датой, не той, что в карточке ребёнка
          (обе даты точные — до дня или до года);
  ВНИМАНИЕ  там же строка о рождении неточнее карточки ребёнка («1948» при 27.06.1948) — уточнить; или наоборот,
          точнее (25.12.1921 при born: 1921) — перенести в born, если дата надёжна.
  Супруг в строке — ссылкой на карточку или по имени; строки, где он не назван, не сверяются.
  (Строки о рождении ребёнка, которой вовсе нет, ищет check_lifeline.py; связи children/father/mother — check_tree.py.)

  tools/py tools/scripts/check_family_sync.py              # всё дерево; код 1, если есть ошибки
  tools/py tools/scripts/check_family_sync.py "<карточка>" # один человек и его супруги, дети
  tools/py tools/scripts/check_family_sync.py --fix        # дата рождения ребёнка — точнее туда, где грубее (строка
        линии жизни родителя или born ребёнка); недостающий факт о браке (разводе) — второму супругу:
        «- **брак:** 23.09.1944, с [[Первый]] — подробно в его (её) карточке — *источник: тот же*»;
        биографии --fix не трогает — рассказ правит человек.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import site_export as b  # noqa: E402
import cards  # noqa: E402
import check_lifeline as cl  # noqa: E402
import dates  # noqa: E402
import paths  # noqa: E402

KINDS = {"брак": re.compile(r"брак|свадьб|венча|жени[тл]|замуж|обручен", re.I),
         "развод": re.compile(r"развод|развел|расторж", re.I)}
DAY = re.compile(r"\b\d{2}\.\d{2}\.\d{4}\b")
LINK = re.compile(r"\[\[([^\]|#\\]+)")


def kind_of(text):
    """«развод» раньше «брака»: «расторжение брака» — развод. Скобки — откуда известно («свидетельство о браке»), не событие."""
    text = re.sub(r"\([^()]*\)", "", text)
    return next((k for k in ("развод", "брак") if KINDS[k].search(text)), None)


def fact_day(f):
    """Точная дата факта: в подписи (дд.мм.гггг) или первыми словами текста («20.01.1910, д. Вербичи…»)."""
    if f.date and f.date.kind == "" and f.date.a and f.date.a.d:
        return f.date.ru()
    m = DAY.match(f.text.strip())
    return m[0] if m else None


def partner(text, me, tree):
    """Супруг, о котором строка: ссылкой на его карточку или по имени. «Супруг один — значит, он» нельзя: у Ивана
    Ясенева брак 1927 — вторым браком, а в дереве у него только первая жена, Агата."""
    stems = {tree.people[s].stem: s for s in me.spouses if s in tree.people}
    named = [stems[x.strip()] for x in LINK.findall(text) if x.strip() in stems]
    if named:
        return named[0]
    return next((i for st, i in stems.items() if st in b.people and cl.mentions(text, b.people[st], {st}, ru=True)), None)


def card_events(p, tree):
    """[(вид, супруг, точная дата, факт)] — факты о браке и разводе в карточке."""
    out = []
    for f in p.facts:
        k = kind_of(f.label or "")
        if k and (s := partner(f.text, p, tree)):
            out.append((k, s, fact_day(f), f))
    return out


def card_problems(tree, people, fixes):
    errs = []
    for p in people:
        for k, s, day, f in card_events(p, tree):
            if not day:
                continue
            other = tree.people[s]
            if not any(k2 == k and s2 == p.id and (d2 == day or day in f2.text) for k2, s2, d2, f2 in card_events(other, tree)):
                errs.append((other.stem, f"карточка: нет {k}а {day} с {p.stem} — у {p.stem} есть (строка {f.line})"))
                fixes.append((other, p, k, day, f))
    return errs


def bio_rows(stem):
    d = b.people.get(stem)
    return b.split_lifeline(b.bio_text(d))[1] if d else []


def row_day(when):
    g = dates.ru_or_none(re.sub(r"[*]", "", when))
    return g if g and g.kind != "PHRASE" else None


def bio_problems(tree, people):
    errs, warns = [], []
    seen = set()
    for p in people:
        for s in p.spouses:
            if s not in tree.people or frozenset((p.id, s)) in seen:
                continue
            seen.add(frozenset((p.id, s)))
            q = tree.people[s]
            rows = {x.stem: [r for r in bio_rows(x.stem) if kind_of(r[2]) and partner(r[2], x, tree) == y.id]
                    for x, y in ((p, q), (q, p))}
            for k in KINDS:
                when = {stem: [r[1] for r in rs if kind_of(r[2]) == k] for stem, rs in rows.items()}
                a, c = when[p.stem], when[q.stem]
                if a and c:
                    da, dc = row_day(a[0]), row_day(c[0])
                    if da and dc and da.card() != dc.card():
                        errs.append((p.stem, f"линия жизни: {k} с {q.stem} — «{a[0]}», а у {q.stem} — «{c[0]}»"))
                elif k == "брак" and (a or c) and bio_rows(p.stem) and bio_rows(q.stem):
                    lack = q.stem if a else p.stem
                    warns.append((lack, f"линия жизни: нет строки о свадьбе с {p.stem if a else q.stem}, у второго есть"))
                for x, y, ws in ((p, q, a), (q, p, c)):
                    days = {d for k2, s2, d, _ in card_events(x, tree) if k2 == k and s2 == y.id and d}
                    for w in ws:
                        g = row_day(w)
                        if days and g and g.card() not in {dates.parse_ru(d).card() for d in days}:
                            errs.append((x.stem, f"линия жизни: {k} с {y.stem} — «{w}», а в карточке {', '.join(sorted(days))}"))
    return errs, warns


def birth_problems(tree, people, fixes=None):
    """fixes — сюда (родитель, «когда» строки, ребёнок, дата карточки ребёнка): что поправит --fix."""
    errs, warns = [], []
    fixes = [] if fixes is None else fixes
    for p in people:
        rows = bio_rows(p.stem)
        if not rows:
            continue
        kids = [b.people[tree.people[c].stem] for c in p.children if c in tree.people and tree.people[c].stem in b.people]
        for k in kids:
            gb = dates.card_or_none(k["f"].get("born"))
            if not gb or gb.kind:
                continue
            for r in rows:
                if not cl.about(r, k, cl.KID_BIRTH, "born", kids) or not cl.KID_BIRTH.search(r[2]) or cl.DEATH.search(r[2]):
                    continue
                g = row_day(r[1])
                if not g or g.kind:
                    continue
                if g.card() == gb.card():
                    continue
                if gb.card().startswith(g.card()):
                    warns.append((p.stem, f"линия жизни: рождение {k['stem']} — «{r[1]}», в карточке ребёнка точнее: {gb.ru()}"))
                    fixes.append(("row", p.stem, r[1], k, gb))
                elif g.card().startswith(gb.card()):
                    warns.append((k["stem"], f"карточка: born {gb.ru()}, а в линии жизни {p.stem} точнее: «{r[1]}» — "
                                             f"перенести в born"))
                    fixes.append(("born", p.stem, r[1], k, g))
                else:
                    errs.append((p.stem, f"линия жизни: рождение {k['stem']} — «{r[1]}», а в карточке ребёнка {gb.ru()}"))
    return errs, warns


def fix_birth(what, parent, when, k, g):
    """Точнее — туда, где грубее: «1950» в линии жизни родителя → дата из карточки ребёнка (row);
    born ребёнка «1921» → дата строки линии жизни родителя (born)."""
    if what == "born":
        path = paths.TREE / "people" / f"{k['stem']}.md"
        text = path.read_text(encoding="utf-8")
        new = re.sub(r"^born: .*$", f"born: {g.card()}", text, count=1, flags=re.M)
        if new != text and g.card() not in text.split("\n---", 1)[0]:
            path.write_text(new, encoding="utf-8")
            return f"{k['stem']}: born {g.card()} (как в линии жизни {parent})"
        return None
    for ref in b.bio_refs(b.people[parent]):
        path = paths.ROOT / ref.split("#")[0]
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8").split("\n")
        for i, ln in enumerate(lines):
            if ln.startswith(f"| {when} |") and cl.KID_BIRTH.search(ln) and cl.mentions(ln, k, {k["stem"]}, ru=True):
                lines[i] = f"| {g.ru()} |" + ln[len(f"| {when} |"):]
                path.write_text("\n".join(lines), encoding="utf-8")
                return f"{parent}: рождение {k['stem']} — «{when}» → {g.ru()}"
    return None


def fix(other, p, k, day, f):
    """Вписать второму супругу строку о браке (разводе) — с тем же источником, что у первого."""
    path = paths.TREE / "people" / f"{other.stem}.md"
    raw = (paths.TREE / "people" / f"{p.stem}.md").read_text(encoding="utf-8").splitlines()
    src = next((ln.split(" — *источник: ", 1)[1] for ln in raw if ln.startswith("- **") and day in ln
                and " — *источник: " in ln and kind_of(ln.split(":**")[0])), None)
    if not src:
        return None
    whose = "его" if p.sex == "M" else "её"
    line = f"- **{k}:** {day}, с [[{p.stem}]] — подробно в {whose} карточке — *источник: {src}"
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^### Факты \(с источником\)\n", text, re.M)
    if not m:
        return None
    tail = text[m.end():]
    end = re.search(r"^#{2,3} ", tail, re.M)
    block = tail[:end.start()] if end else tail
    last = list(re.finditer(r"^- .*$", block, re.M))
    if last:
        at = m.end() + last[-1].end()
        text = text[:at] + "\n" + line + text[at:]
    else:
        text = text[:m.end()] + "\n" + line + "\n" + text[m.end():]
    path.write_text(text, encoding="utf-8")
    return f"{other.stem}: {line[:110]}…"


def main():
    args = sys.argv[1:]
    do_fix = "--fix" in args
    args = [a for a in args if a != "--fix"]
    tree = cards.load()
    people = list(tree.people.values())
    if args:
        me = [p for p in people if p.stem in args]
        near = {x for p in me for x in p.spouses + p.children + p.father + p.mother}
        people = me + [tree.people[x] for x in near if x in tree.people]
    fixes = []
    errs = card_problems(tree, people, fixes)
    e2, warns = bio_problems(tree, people)
    births = []
    e3, w3 = birth_problems(tree, people, births)
    errs, warns = list(dict.fromkeys(errs + e2 + e3)), list(dict.fromkeys(warns + w3))
    done = []
    if do_fix:
        for x in fixes:
            if r := fix(*x):
                done.append(r)
        for x in births:
            if r := fix_birth(*x):
                done.append(r)
        if done:
            tree = cards.load()
            errs = card_problems(tree, [tree.people[p.id] for p in people], []) + e2 + e3
    for stem in sorted({s for s, _ in errs + warns}):
        print(f"\n{stem}")
        for s, e in errs:
            if s == stem:
                print(f"  ✗ {e}")
        for s, w in warns:
            if s == stem:
                print(f"  · {w}")
    if done:
        print("\nВписано:\n" + "\n".join(f"  + {x}" for x in done))
    print(f"\nСобытия на двоих (брак, развод, рождение): ошибок {len(errs)}, предупреждений {len(warns)}")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
