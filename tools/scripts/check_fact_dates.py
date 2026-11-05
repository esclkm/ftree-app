#!/usr/bin/env python3
"""Дата есть, а факта нет: рассказ и события не должны знать больше карточки (01.11.2026).

Порядок работы — источник → факт в карточке → биография. Но дата часто попадает сразу в рассказ или в карточку
события, мимо фактов. Например: брак Ивана Ясенева — акт 20.01.1910 в Вербичах в фактах, а карточка события
«Marriage of Ivan Jasieniew» пустая; у Прокопа Ясенева в событиях рождение 1855 и смерть 1920, а по метрикам —
около 1852 и 14.03.1921, и сайт показывал старые годы. Решать, вносить ли дату в факты, — сессии, глядя на источник;
скрипт находит, где решить.

Что проверяет:
  ВНИМАНИЕ  строка «Линии жизни» с годом, а в карточке нет факта с этим годом (и born/died не тот год). Решить:
            внести факт с источником; дописать год в факт, где событие уже есть без года; или, если факт не нужен,
            строку — в ftree.toml, [fact_dates] ok. Не спрашивает строк о рождении и смерти детей, супругов и родителей —
            их дата в карточке того человека, — и строк, вписанных из дерева (в «Откуда» — «дерево»).
  ВНИМАНИЕ  событие рождения или смерти (3_research/tree/events) — другой год, чем born/died карточки. Карточка —
            то, во что дерево верит: если событие устарело — поправить его; если право событие — внести факт и поле.
  ВНИМАНИЕ  событие с датой (жительство, работа, брак…), а года нет ни в одном факте человека.
  --fix     событие рождения или смерти не спорит с карточкой по годам, но записано иначе («1908» при 29.02.1908,
            «2008» при «между 2001 и 2008») — дата из карточки: сайт берёт годы жизни из неё, событие — её копия.
            Точный день в событии при неточной карточке не трогает — предупреждает: день мог прийти из документа; брак без даты, а в факте о браке точная дата и ссылка на второго из пары — дата (и место, если
            в факте ссылка на место, а у события места нет).

  tools/py tools/scripts/check_fact_dates.py                 # всё дерево; код выхода 0 — это список для решения
  tools/py tools/scripts/check_fact_dates.py "<карточка>"    # один человек
  tools/py tools/scripts/check_fact_dates.py --file "<биография>"  # люди этой биографии (так зовёт хук)
  tools/py tools/scripts/check_fact_dates.py --fix
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import site_export as b  # noqa: E402
import cards  # noqa: E402
import check_family_sync as fs  # noqa: E402
import paths  # noqa: E402
from cards.notes import as_list, link_target  # noqa: E402

# (карточка, начало текста «Что») — дата в линии жизни без своего факта, и так задумано.
# Список — у дерева: ftree.toml, [fact_dates] ok = [["Карточка", "начало строки"], …]; нет — пусто
OK = {tuple(x) for x in paths.tree_conf("fact_dates.ok", [])}
YEAR = re.compile(r"(1[5-9]\d\d|20\d\d)")
SPAN = re.compile(r"(1[5-9]\d\d|20\d\d)\s*[–—-]\s*(1[5-9]\d\d|20\d\d)|между (1[5-9]\d\d|20\d\d) и (1[5-9]\d\d|20\d\d)")
DECADE = re.compile(r"\b(1[5-9]\d|20\d)0-е")
AFTER, BEFORE = re.compile(r"(?:после|с) (1[5-9]\d\d|20\d\d)"), re.compile(r"до (1[5-9]\d\d|20\d\d)")
BIRTH = re.compile(r"(?<!о )рожд|родил|родит|появил(ся|ась) на свет", re.I)
DEATH = re.compile(r"умер|умир|погиб|скончал|смерть|похорон", re.I)
MARRIAGE = re.compile(r"жени[тл]|замуж|брак|свадьб|венча", re.I)
ROUGH = re.compile(r"\bок\.|около|≈|~|примерно")
DAY = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")


def spans(text, slack=0):
    """Годы в тексте → [(с, по)]: «1935–1944» — промежуток, «1952» — один год; slack — допуск для «ок.»."""
    text = str(text or "")
    out = [(int(a or c), int(bb or d)) for a, bb, c, d in SPAN.findall(text)] + [(int(y), int(y)) for y in YEAR.findall(text)]
    out += [(int(x) * 10, int(x) * 10 + 9) for x in DECADE.findall(text)]  # «1930-е»
    out += [(int(y), int(y) + 5) for y in AFTER.findall(text)] + [(int(y) - 5, int(y)) for y in BEFORE.findall(text)]
    return [(a - slack, c + slack) for a, c in out]


def meet(xs, ys):
    return any(a <= d and c <= bb for a, bb in xs for c, d in ys)


def known_years(p):
    """Годы, которые карточка уже знает: факты (подпись, текст, дата) и born/died."""
    out = []
    for f in p.facts:
        out += spans(f"{f.label} {f.text} {f.date.ru() if f.date else ''}")
    return out + spans(p.fm.get("born")) + spans(p.fm.get("died"))


def lifeline_gaps(d, p, tree):
    """Строки «Линии жизни» с годом, которого карточка не знает: [(когда, что)]."""
    rows = b.split_lifeline(b.bio_text(d))[1]
    if not rows:
        return []
    mine = known_years(p)
    near = lambda ids: [tree.people[x] for x in ids if x in tree.people]
    parents = near(p.father + p.mother)
    # чья дата рождения или смерти — в его карточке: родители, бабушки и дедушки, братья и сёстры, супруги, дети
    kin = parents + near(p.spouses + p.children) + near([x for q in parents for x in q.father + q.mother + q.children])
    spouses = near(p.spouses)
    out = []
    for _, when, what, extra in rows:
        row = spans(when, 2 if ROUGH.search(when) else 0)
        if not row or "дерево" in (what + " ".join(v for _, v in extra)).lower():
            continue
        if meet(row, mine) or any(s == p.stem and what.strip().startswith(w) for s, w in OK):
            continue
        if (BIRTH.search(what) and any(meet(row, spans(k.fm.get("born"))) for k in kin)) or \
                (DEATH.search(what) and any(meet(row, spans(k.fm.get("died"))) for k in kin)) or \
                (MARRIAGE.search(what) and any(meet(row, known_years(k)) for k in spouses)):  # факт о браке — у второго
            continue
        out.append((when, re.sub(r"\s+", " ", what)[:110]))
    return out


def raw_field(p, key):
    """Поле карточки как записано (born: 1908-02-29), а не как его понял YAML."""
    m = re.search(rf"^{key}:[ \t]*\"?([^\"\n]*)\"?\s*$", (paths.TREE / "people" / f"{p.stem}.md").read_text(encoding="utf-8"), re.M)
    return m[1].strip() if m else ""


def precision(v):
    return ("range" if v.startswith(("BET", "FROM")) else "estimated" if v.startswith(("ABT", "EST", "CAL", "BEF", "AFT"))
            else "exact" if re.fullmatch(r"\d{4}(-\d\d-\d\d)?", v) else "month" if re.fullmatch(r"\d{4}-\d\d", v) else "unknown")


def event_path(e):
    return next((f for f in (paths.TREE / "events").glob("*.md") if f"cr_id: {e.get('cr_id')}\n" in f.read_text(encoding="utf-8")), None)


def set_fields(path, fields):
    """Свойства карточки события: заменить строку или дописать перед концом шапки."""
    text = path.read_text(encoding="utf-8")
    head, body = text[4:].split("\n---", 1)
    for k, v in fields.items():
        line = f"{k}: {v}"
        head = re.sub(rf"^{k}:.*$", line, head, flags=re.M) if re.search(rf"^{k}:", head, re.M) else head + "\n" + line
    path.write_text("---\n" + head + "\n---" + body, encoding="utf-8")


def event_checks(tree, who):
    """→ (предупреждения {cr_id человека: [строки]}, правки [(путь события, {поле: значение}, что сделано)])."""
    by_stem = {p.stem: p for p in tree.people.values()}
    warns, fixes = {}, []
    for e in tree.events:
        kind, date = e.get("event_type"), str(e.get("date") or "").strip()
        ps = [by_stem[t] for t in (link_target(x) for x in as_list(e.get("persons"))) if t in by_stem]
        if not ps or not any(p.id in who for p in ps):
            continue
        title = e.get("title") or kind
        if kind in ("birth", "death") and date:
            p, key = ps[0], "born" if kind == "birth" else "died"
            card = raw_field(p, key)
            if card and card != date:
                day = re.compile(r"\d{4}-\d\d-\d\d")
                if meet(spans(date), spans(card)) and (not day.fullmatch(date) or day.fullmatch(card)):
                    fixes.append((e, {"date": card, "date_precision": precision(card)}, f"{title}: {date} → {card} (как в карточке)"))
                elif meet(spans(date), spans(card)):
                    warns.setdefault(p.id, []).append(f"событие «{title}» — точный день {date}, а в карточке {key}: {card} — "
                                                      f"если день из документа, внести его в карточку с источником")
                else:
                    warns.setdefault(p.id, []).append(f"событие «{title}» — {date}, а в карточке {key}: {card}")
            continue
        if kind == "marriage" and not date:
            for p in ps:
                for k, partner, day, f in fs.card_events(p, tree):
                    if k == "брак" and day and partner in {x.id for x in ps}:
                        dd, mm, yy = DAY.match(day).groups() if DAY.match(day) else (None, None, None)
                        if not yy:
                            continue
                        fields = {"date": f"{yy}-{mm}-{dd}", "date_precision": "exact"}
                        pl = next((t for t in (link_target(x) for x in re.findall(r"\[\[[^\]]+\]\]", f.text))
                                   if t in {x.stem for x in tree.places.values()}), None)
                        if pl and not e.get("place"):
                            fields["place"] = f'"[[{pl}]]"'
                        fixes.append((e, fields, f"{title}: дата {day}" + (f", место {pl}" if "place" in fields else "")
                                      + f" — из факта карточки {p.stem}"))
                        break
                else:
                    continue
                break
            continue
        if date and kind not in ("birth", "death"):
            if kind in ("marriage", "divorce") and any(meet(spans(date), known_years(p)) for p in ps):
                continue  # событие на двоих: год в фактах хотя бы одного из пары
            for p in ps:
                if p.id in who and not meet(spans(date), known_years(p)):
                    warns.setdefault(p.id, []).append(f"событие «{title}» ({kind}, {date}) — года нет в фактах")
    return warns, fixes


def main():
    args = sys.argv[1:]
    do_fix = "--fix" in args
    args = [a for a in args if a != "--fix"]
    tree = cards.load()
    if args[:1] == ["--file"]:
        f = b.N(args[1]).removesuffix(".md")
        people = [d for d in b.people.values() if any(b.N(r.split("#")[0]).removesuffix(".md") == f for r in b.bio_refs(d))]
    else:
        people = [d for d in b.people.values() if not args or d["stem"] in args]
    who = {d["id"] for d in people}
    warns, fixes = event_checks(tree, who)
    if do_fix:
        for e, fields, what in fixes:
            if path := event_path(e):
                set_fields(path, fields)
                print(f"  + {what}")
    n = 0
    for d in sorted(people, key=lambda d: d["stem"]):
        p = tree.people.get(d["id"])
        if not p:
            continue
        gaps = lifeline_gaps(d, p, tree)
        ev = warns.get(p.id, [])
        if gaps or ev:
            print(f"\n{d['stem']}")
            for when, what in gaps:
                print(f"  · линия жизни {when} | {what} — в фактах года нет")
            for w in ev:
                print(f"  · {w}")
            n += len(gaps) + len(ev)
    left = 0 if do_fix else len(fixes)
    print(f"\nДата есть, факта нет: решить {n}" + (f"; поправится само (--fix): {left}" if left else "")
          + (" — внести факт с источником, дописать год в факт или строку в ftree.toml, [fact_dates] ok" if n else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
