#!/usr/bin/env python3
"""Стандарт карточки человека (фаза 1b, журнал документ дерева проект/ОРКЕСТРАЦИЯ_ЖУРНАЛ.md): годы из свойств — с источником, факты — строками.

Зачем. Сайт и проверки верят строкам «Фактов (с источником)»: у каждой — откуда она и насколько ей верить. А годы и
места в свойствах карточки (born, died, birth_place, death_place) у сотен людей стоят без такой строки — непонятно,
откуда они. И у части карточек факты записаны свободным текстом в «Заметках» — сайт их не видит вовсе.

  years — год или место из свойств без строки факта:
          • в дереве MyHeritage то же самое → строка факта «источник: [[<наше дерево на MyHeritage>]] · уверенность: низкая (чужое
            дерево, не проверено)»: это подсказка, не доказательство;
          • в MyHeritage иначе или нет вовсе → строки нет, человек — в список;
          • всё, что о тех же годах говорит проект (факты, заметки, биография, расшифровки, GEDCOM проекта), — сверка:
            не сходится → в список. Даты в карточках не правятся — список читает Павел.
          Список — 3_research/tree/_СВЕРКА_ГОДОВ.md.
  notes — свободный текст «Заметок» и «Из досье поиска» → строки фактов: слова те же, источник — тот, что назван в
          самом тексте (Doc07, «воспоминания Ясеневой А. П., стр. 3», Аудио 03, «от отца»), или заметка MyHeritage,
          если это она. Источник не назван — абзац остаётся заметкой. Список — 3_research/tree/_СТАНДАРТ_ПРАВКИ.md.

  tools/py tools/scripts/card_standard.py years            # что будет сделано (ничего не пишет)
  tools/py tools/scripts/card_standard.py years --apply    # вписать факты и список
  tools/py tools/scripts/card_standard.py notes [--apply]

Повторный запуск ничего не дублирует: строка, которая уже есть, не пишется второй раз. Пустые свойства Charted Roots
(group_name, external_id) не трогаются — меняются только тело карточки и список sources.
"""
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cards  # noqa: E402
import dates  # noqa: E402
import myheritage_update as mh  # noqa: E402
import paths  # noqa: E402
import tree as T  # noqa: E402
from cards import layout  # noqa: E402
from cards.notes import N, as_list, link_target, section  # noqa: E402

# карточка источника — сайт нашего дерева на MyHeritage (ftree.toml, [myheritage.ours] source_card)
MH = paths.tree_conf("myheritage.ours.source_card", "") or "MyHeritage"
MH_CONF = "низкая (чужое дерево, не проверено)"
YEARS_OUT = paths.TREE / "_СВЕРКА_ГОДОВ.md"
NOTES_OUT = paths.TREE / "_СТАНДАРТ_ПРАВКИ.md"
BIRTH = re.compile(r"рожд|родил|\bрод\.|крещ|\bborn\b|появил\w* на свет", re.I)
DEATH = re.compile(r"умер|умерл|смерт|погиб|похорон|скончал|расстрел|\bdied\b|захорон|утонул|убит", re.I)
YEAR = re.compile(r"(?<!\d)(1[6-9]\d\d|20[0-2]\d)(?!\d)")


# ─── карточка как текст ────────────────────────────────────────────────────────────────────────────────────────────

def read(path):
    text = N(path.read_text(encoding="utf-8"))
    m = re.match(r"---\n.*?\n---\n", text, re.S)
    return text[: m.end()], text[m.end():]


def write(path, head, body):
    path.write_text(head + "\n" + layout.fix(body), encoding="utf-8")


def add_source(head, body, stem, where, conf, prov):
    """Источник — в свойство sources и строкой в «## Источники» (если его там ещё нет)."""
    link = f'"[[{stem}]]"'
    if f"[[{stem}]]" not in head:
        m = re.search(r"^sources:[ \t]*(\[\])?[ \t]*\n((?:[ \t]+- .*\n)*)", head, re.M)
        if m:
            head = head[: m.start()] + "sources:\n" + m[2] + f"  - {link}\n" + head[m.end():]
        else:
            head = head[: head.rindex("---")] + f"sources:\n  - {link}\n---\n"
    text, start = section(body, "Источники", 2)
    if not re.search(rf"^- \[\[{re.escape(stem)}\]\]", text, re.M):
        line = f"- [[{stem}]]" + (f" — {where}" if where else "") + f" · уверенность: {conf} · происхождение: {prov}"
        if start < 0:
            body = body.rstrip("\n") + "\n\n## Источники\n\n" + line + "\n"
        else:   # в конец раздела «Источники», где бы он ни стоял
            end = start + len(text.rstrip("\n"))
            body = body[:end] + "\n" + line + body[end:]
    return head, body


def add_facts(body, first=(), last=()):
    """Строки фактов — в начало и в конец «### Факты (с источником)» (раздела нет — заводится)."""
    if f"### {layout.FACTS}\n" not in body:
        body = body.rstrip("\n") + f"\n\n## Факты и заметки\n\n### {layout.FACTS}\n\n"
    i = body.index(f"### {layout.FACTS}\n") + len(f"### {layout.FACTS}\n")
    nxt = re.search(r"^#{1,3} ", body[i:], re.M)
    j = i + nxt.start() if nxt else len(body)
    inner = body[i:j].strip("\n")
    inner = "\n".join([*first, *([inner] if inner else []), *last])
    return body[:i] + "\n" + inner + "\n\n" + body[j:]


def fact_line(label, value, source, where, conf):
    return f"- **{label}:** {value} — *источник: [[{source}]]" + (f", {where}" if where else "") + \
        f" · уверенность: {conf}*"


# ─── что говорит MyHeritage ────────────────────────────────────────────────────────────────────────────────────────

def mh_people(path=None):
    """{номер I…: {"BIRT": (дата, место), "DEAT": (…), "notes": текст заметок}} из выгрузки MyHeritage."""
    out = {}
    for xref, kind, lines in mh.records(mh.read_ged(path or mh.latest_export())):
        if kind != "INDI":
            continue
        rec, ev = {"notes": ""}, None
        for l in lines[1:]:
            m = re.match(r"(\d) (\w+) ?(.*)", l)
            if not m:
                continue
            lvl, tag, val = int(m[1]), m[2], m[3].strip()
            if lvl == 1:
                ev = tag if tag in ("BIRT", "DEAT") else None
                if ev:
                    rec[ev] = ["", ""]
            elif lvl == 2 and ev and tag in ("DATE", "PLAC"):
                rec[ev][0 if tag == "DATE" else 1] = val
            if tag in ("NOTE", "CONT", "CONC"):
                rec["notes"] += " " + val
        out[xref] = rec
    return out


def ged_years(v):
    ys = [int(y) for y in YEAR.findall(v or "")]
    return (min(ys), max(ys)) if ys else None


def same_date(card, site):
    """Дата карточки и дата MyHeritage — одна и та же (или та же с точностью до «около», стиля, дня); годы
    промежутка («BET 2001 AND 2008») и «TO 2021» — если год MyHeritage внутри."""
    if not site or not card:
        return False
    if mh.keep_site_date(site, card.gedcom()) or mh.date_core(site) == mh.date_core(card.gedcom()):
        return True
    core = re.sub(r"^(TO|FROM|INT)\s+", "", site.strip().upper())   # «TO 2021» на MyHeritage и 2021 в карточке
    if core != site.strip().upper() and (core == card.gedcom() or mh.keep_site_date(core, card.gedcom())):
        return True
    m = re.fullmatch(r"(?:(?:ABT|EST|CAL) )?(?:(?:(\d{1,2}) )?(%s) )?(\d{4})" % "|".join(mh.MONTHS), site.strip().upper())
    f = card.first
    if m and f and card.kind in ("", "ABT", "EST", "CAL") and int(m[3]) == f.y and \
            (not m[2] or (f.m and mh.MONTHS.index(m[2]) + 1 == f.m)) and (not m[1] or (f.d and int(m[1]) == f.d)):
        return True                                   # MyHeritage просто менее точен: «1927» при 08.04.1927
    ys = ged_years(site)
    return bool(ys) and card.kind == "BET" and card.first_year <= ys[0] and ys[1] <= card.last_year


COUNTRY = [{"сша", "usa", "united states", "united states of america", "соединённые штаты"}, {"аргентина", "argentina"},
           {"бразилия", "brasil", "brazil"}, {"беларусь", "белоруссия", "belarus", "białoruś", "bialorus"},
           {"польша", "polska", "poland"}, {"россия", "russia", "rosja"}, {"ссср", "ussr"}]


def same_place(site, pnames):
    """Место MyHeritage — то же, что в карточке: то же слово в любом написании (Вербичи = Werbicze, Лесогорск = Lesogorsk),
    или страна под другим названием (США = United States)."""
    s = mh.norm(site)
    if mh.same_place(site, [mh.norm(n) for n in pnames]):
        return True
    for group in COUNTRY:
        if any(mh.norm(n) in group for n in pnames) and any(re.search(rf"(^|[\s,]){re.escape(c)}($|[\s,])", s) for c in group):
            return True
    first = re.split(r"[,(]", s)[0]
    import difflib
    for n in pnames:
        for a in T.tokens(n):
            for b in T.tokens(first):
                if len(a) >= 3 and (T.word_match(a, b) or any(difflib.SequenceMatcher(None, x, y).ratio() >= 0.85
                                                             for x in T.keys(a) for y in T.keys(b))):
                    return True
    return False


# ─── что говорит проект ────────────────────────────────────────────────────────────────────────────────────────────

KIN_AFTER = re.compile(r"^\W{0,3}(?:\w+\s){0,2}(?:сын|сына|дочь|дочери|муж|мужа|жена|жены|брат|брата|сестр|отец|отца|мать|"
                       r"матери|внук|внучк|дет|ребён|ребен|\[\[)", re.I)


def years_in(text, kw):
    """Годы рядом со словом о рождении или смерти самого человека: «умер в 1919», «род. ок. 1936»; по предложениям.
    «Умер сын…», «двое детей умерли при рождении» — о других, не в счёт."""
    out = []
    for sent in re.split(r"(?<=[.;!?])\s+|\n", text):
        for m in kw.finditer(sent):
            if KIN_AFTER.search(sent[m.end(): m.end() + 30]) or re.search(r"(дет\w*|ребён\w*|двое|трое)\s+\S*\s*$",
                                                                           sent[max(0, m.start() - 25): m.start()]):
                continue
            y = YEAR.search(sent[m.start(): m.start() + 60])
            if y:
                out.append((int(y[1]), sent.strip()))
                break
    return out


def own_fact(f, kw):
    """Строка факта — о рождении/смерти самого человека: слово в подписи («смерть», «рождение») или первым в тексте."""
    return bool(kw.search(f.label)) or bool(re.match(r"\W*(" + kw.pattern + r")", f.text, re.I))


def evidence(tree, p, kind, bio_text, transcripts, enriched, mh_id=None):
    """Всё, что проект говорит о годе рождения (BIRT) или смерти (DEAT): [(год, где, цитата)]. Факты из самого
    MyHeritage — не в счёт: с ним и сверяем."""
    kw = BIRTH if kind == "BIRT" else DEATH
    out = []
    for f in p.facts:
        if own_fact(f, kw) and not all(r.source == mh_id for r in f.refs):
            ys = (f.date.first_year, f.date.last_year) if f.date else ged_years(f.label + " " + f.text)
            if ys:
                out.append((ys, f"факт карточки, стр. {f.line}", (f.label + ": " + f.text)[:140]))
    free = "\n".join(l for l in p.body.split("\n") if not layout.FACT_LINE.match(l) and not l.startswith(("- [[", "#")))
    for where, text in [("текст карточки", free), ("биография", bio_text), *transcripts]:
        for y, s in years_in(text, kw):
            out.append(((y, y), where, s[:140]))
    if enriched and enriched.get(kind) and ged_years(enriched[kind][0]):
        out.append((ged_years(enriched[kind][0]), "GEDCOM проекта (enriched.ged)", enriched[kind][0]))
    return out


def lifeline_text(tree, p):
    bio = T.biography_of(tree, p)
    if not bio:
        return ""
    text = (paths.ROOT / bio).read_text(encoding="utf-8")
    rows = [l for l in text.split("\n") if l.startswith("|") and l.count("|") >= 3]   # строки линии жизни
    return "\n".join(r.replace("|", " ") + "." for r in rows)


def transcripts_about(p, files):
    """Строки расшифровок и документов, где человек назван (ссылкой, номером или именем из двух слов)."""
    rx = re.compile(T.name_pattern(p), re.I)
    out = []
    for rel, text in files:
        lines = [l for l in text.split("\n") if rx.search(l)]
        if lines:
            out.append((rel, "\n".join(lines)))
    return out


def covered(p, kind, g, place_names, mh_id=None):
    """Строка факта о том же: год (± неточность) или место — со словом о рождении/смерти. → номер строки или None.
    Факт, у которого источник — только MyHeritage, опорой не считается: он сам — то, что проверяем."""
    kw = BIRTH if kind == "BIRT" else DEATH
    facts = [f for f in p.facts if not mh_id or any(r.source != mh_id for r in f.refs)]
    for f in facts:
        words = f.label + " " + f.text
        if not kw.search(words) and not (kind == "BIRT" and re.match(r"(место )?рожд", f.label, re.I)):
            continue
        if g is not None:
            ys = (f.date.first_year, f.date.last_year) if f.date else ged_years(words)
            if ys and ys[0] - 1 <= g.first_year and g.last_year <= ys[1] + 1:
                return f.line
        if place_names and (any(f"[[{n}]]" in words or f"[[{n}|" in words for n in place_names) or any(
                T.word_match(a, b) for n in place_names for a in T.tokens(n) if len(a) >= 4 for b in T.tokens(words))):
            return f.line
    if g is not None and g.kind == "CAL":   # год вычислен из возраста: «Андрей, 10» в переписи 1914 года → 1904
        for f in facts:
            words = f.label + " " + f.text
            ys = (f.date.first_year,) if f.date else [int(y) for y in YEAR.findall(words)]
            for age in re.findall(r"(?<![\d.])(\d{1,3})(?![\d.])", words):
                if int(age) <= 120 and any(abs(y - int(age) - g.first_year) <= 1 for y in ys):
                    return f.line
    return None


def outside(ys, g):
    tol = 1 if g.approx else 0
    return ys[1] < g.first_year - tol or ys[0] > g.last_year + tol


def years(apply=False):
    tree = cards.load()
    site = mh_people()
    enriched = mh_people(paths.ENRICHED_GED)
    files = [(N(f.relative_to(paths.ROOT).as_posix()), N(f.read_text(encoding="utf-8")))
             for f in sorted(paths.TRANSCRIPTS.rglob("*.md"))]
    write_facts, mh_differs, only_card, conflicts = [], [], [], []
    mh_id = next((s.id for s in tree.sources.values() if s.stem == MH), None)
    for p in sorted(tree.people.values(), key=lambda p: p.stem):
        gid = str(p.fm.get("gedcom_id") or "").strip("@")
        rec = site.get(gid)
        first, last, trs = [], [], None
        for kind, g, pl, word in (("BIRT", p.born, p.birth_place, "рождение"), ("DEAT", p.died, p.death_place, "смерть")):
            place = tree.places.get(pl)
            pnames = [place.stem, place.name, *place.aliases] if place else []
            site_date, site_place = (rec or {}).get(kind, ["", ""])
            what = "рождения" if kind == "BIRT" else "смерти"
            fact_date = covered(p, kind, g, [], mh_id) if g is not None else None
            fact_place = covered(p, kind, None, pnames, mh_id) if place else None
            date_ok = g is not None and same_date(g, site_date)
            place_ok = place is not None and bool(site_place) and same_place(site_place, pnames)
            up, seen = tree.places.get(place.parent) if place else None, set()
            while place and not place_ok and up and up.id not in seen:   # MyHeritage назвал страну: «Аргентина»
                seen.add(up.id)
                place_ok = same_place(site_place, [up.stem, up.name, *up.aliases]) and "," not in site_place
                up = tree.places.get(up.parent)
            if g is not None and site_date and not date_ok:
                mh_differs.append((p, kind, f"год {what}", g.ru(), site_date, fact_date))
            if place and site_place and not place_ok:
                mh_differs.append((p, kind, f"место {what}", place.stem, site_place, fact_place))
            need_date, need_place = g is not None and not fact_date, place is not None and not fact_place
            if (need_date and date_ok) or (need_place and place_ok):
                value = ("родилась" if p.sex == "F" else "родился") if kind == "BIRT" else ("умерла" if p.sex == "F" else "умер")
                if need_place and place_ok:
                    value += f", [[{place.stem}]]"
                label = f"{g.ru()}, {word}" if need_date and date_ok else f"место {what}"
                line = fact_line(label, value, MH, gid, MH_CONF)
                (first if kind == "BIRT" else last).append(line)
                if line not in p.body:
                    write_facts.append((p, line))
            if need_date and not site_date:
                only_card.append((p, f"год {what}", g.ru()))
            if need_place and not site_place:
                only_card.append((p, f"место {what}", place.stem))
            if g is not None and (need_date or (site_date and not date_ok)):
                if trs is None:
                    trs = (lifeline_text(tree, p), transcripts_about(p, files))
                ev = evidence(tree, p, kind, trs[0], trs[1], (enriched.get(gid) if gid else None), mh_id)
                bad = [e for e in ev if outside(e[0], g)]
                if bad and need_date:
                    conflicts.append((p, word, g.ru(), site_date or "—", ev, bad))
                for d in mh_differs:
                    if d[0] is p and d[1] == kind and d[2].startswith("год") and len(d) == 6:
                        mh_differs[mh_differs.index(d)] = d + (ev,)
        if apply and (first or last):
            path = paths.TREE / "people" / f"{p.stem}.md"
            head, body = read(path)
            new = [l for l in first + last if l not in body]
            if new:
                body = add_facts(body, [l for l in first if l in new], [l for l in last if l in new])
                head, body = add_source(head, body, MH, gid, "низкая", "чужое дерево")
                write(path, head, body)
    already = [p for p in tree.people.values()
               if any(r.source == mh_id and re.search(r"рождени|смерт", f.label) for f in p.facts for r in f.refs)
               and p.id not in {q.id for q, _ in write_facts}]   # вписано прошлым запуском — тоже в разделе 4
    report = years_report(write_facts, mh_differs, only_card, conflicts, already)
    if apply:
        YEARS_OUT.write_text(report, encoding="utf-8")
    print(f"строк факта из MyHeritage: {len(write_facts)} у {len({p.id for p, _ in write_facts})} человек; "
          f"MyHeritage не как карточка: {len(mh_differs)}; только в карточке: {len(only_card)}; год без строки факта "
          f"расходится с проектом: {len(conflicts)}" + ("" if apply else " (ничего не записано: --apply)"))
    return report


def _ev_lines(ev, g_bad):
    out = []
    for ys, where, s in ev:
        y = f"{ys[0]}" if ys[0] == ys[1] else f"{ys[0]}–{ys[1]}"
        out.append(f"- {'≠' if (ys, where, s) in g_bad else '='} {y} — {where}: «{s}»")
    return out


def years_report(write_facts, mh_differs, only_card, conflicts, already=()):
    L = [f"# Сверка годов и мест из свойств карточек — {date.today():%d.%m.%Y}", "",
         "> Собрано `tools/scripts/card_standard.py years`. **Даты в карточках не правились** — решает Павел.", "",
         "**Что это.** Год рождения или смерти и место человека стоят в свойствах карточки (born, died, birth_place, "
         "death_place). У многих к ним нет строки факта с источником — непонятно, откуда они. Скрипт сравнил каждое "
         "значение с деревом на MyHeritage (выгрузка 28.09.2026) и со всем, что о тех же годах говорит проект: факты "
         "и текст карточки, линия жизни биографии, расшифровки и документы, GEDCOM проекта (`enriched.ged`).", "",
         f"Где карточка и MyHeritage совпали, а строки факта не было, — она вписана: «источник: [[{MH}]] · "
         "уверенность: низкая (чужое дерево, не проверено)». Это подсказка, а не доказательство. Ниже — всё, что не "
         "сошлось. «=» — источник согласен с карточкой, «≠» — называет другой год.", ""]
    L += [f"## 1. MyHeritage говорит не то, что карточка — {len(mh_differs)}", "",
          "Карточка не правилась. Если права карточка — поправить MyHeritage следующей выгрузкой "
          "(`myheritage_update.py`); если прав MyHeritage — найти, откуда значение в карточке. Решено, что ошибка в "
          "MyHeritage, — строка «**В MyHeritage неверно:** …» в «Расхождениях» карточки; тогда здесь ✅.", ""]
    for d in mh_differs:
        p, kind, what, card, site_v, line = d[:6]
        wrong = re.search(r"^- .*\*\*В MyHeritage неверно", p.body, re.M)
        L.append(f"### {T.label(p)} — {what}" + (" — ✅ решено: в MyHeritage неверно" if wrong else ""))
        if wrong:
            L.append("- помечено в карточке («Расхождения»): исправить на MyHeritage при следующей выгрузке")
        L.append(f"- в карточке: **{card}**" + (f" (строка факта {line})" if line else " (своей строки факта нет)")
                 + f"; в MyHeritage: **{site_v}**")
        if len(d) > 6:
            g = p.born if kind == "BIRT" else p.died
            L += _ev_lines(d[6], [e for e in d[6] if outside(e[0], g)])
        L.append("")
    L += [f"## 2. Год без своей строки факта (разве что из MyHeritage) спорит с тем, что знает проект — {len(conflicts)}", ""]
    for p, kind, card, site_v, ev, bad in conflicts:
        L.append(f"### {T.label(p)} — {kind}")
        L.append(f"- в карточке: **{card}**; в MyHeritage: {site_v}")
        L += _ev_lines(ev, bad) + [""]
    L += [f"## 3. Только в карточке: в MyHeritage нет, строки факта нет — {len(only_card)}", "",
          "Чаще всего — люди, которых нет на MyHeritage, или место, которого там не записали. Опоры у значения нет: "
          "найти, откуда оно, или оставить как есть. В «Что ещё искать» не переносится.", "",
          "| Человек | Что | В карточке |", "|---|---|---|"]
    L += [f"| {T.label(p)} | {what} | {v} |" for p, what, v in only_card]
    who = list(dict.fromkeys([T.label(p) for p, _ in write_facts] + sorted(T.label(p) for p in already)))
    L += ["", f"## 4. Совпало с MyHeritage — строка факта с источником [[{MH}]] есть у {len(who)} человек", "",
          ", ".join(who), ""]
    return "\n".join(L)


# ─── notes: свободный текст → строки фактов ────────────────────────────────────────────────────────────────────────

def _sources(rows):
    """[[regex, начало имени карточки источника], …] → [(regex, pick)]: «{1}» в начале имени — первая скобка regex."""
    return [(rx, (lambda pre: lambda m, S: _src(S, pre.format(m[0], *m.groups())))(pre)) for rx, pre in rows]


# что в тексте называет источник → карточка источника; где в нём — то, что совпало в скобках. Свои у дерева:
# ftree.toml, [card_standard] sources; нет — источник в тексте не узнаётся, абзац остаётся заметкой
SOURCES = _sources(paths.tree_conf("card_standard.sources", []))
LOCATOR = re.compile(r"(стр\. ?[\d–-]+(?: PDF)?|\d\d:\d\d(?:–\d\d:\d\d)?|\d{4}-\d\d-\d\d)")
LEAVE = [   # абзацы, которые не факты: задания, ссылки, служебное, рассуждения для заявлений
    (r"^ЗАПРОС", "задание для поиска, не факт"),
    (r"^Источник:", "строка-источник для абзацев выше"),
    (r"Web content link|link=https?://|^https?://", "ссылка без сведений"),
    (r"^<!--|Этот блок генерируется скриптом", "служебная пометка"),
    (r"!\[\[", "фото"),
    (r"Карт\w* поляка|маршрут\w* A|для заявлени", "про заявление — место в 32_ПОЛЬСКИЙ_ПУТЬ_и_СТРАНЫ.md"),
    (r"^Кандидат \(", "кандидат в одного человека — это вопрос, а не факт"),
    (r"(?i)дарственн|снесла дом|уничтожила весь|в тайне от отца|контакт категорически|владеет участком",
     "семейный конфликт вокруг дома — на сайт не выносим, остаётся заметкой"),
    (r" → ", "после «→» — вывод или задание; разделить руками, где факт"),
]
DOUBT = re.compile(r"\[вывод\]|вероятно|предположительно|возможно|видимо|\?\]|не установлено|по легенде|не доказано",
                   re.I)


def _src(stems, prefix):
    return next((s for s in stems if s.startswith(prefix)), None)


def paragraphs(text):
    """Абзацы: пустая строка или новый пункт «- » начинают следующий."""
    out, cur = [], []
    for l in text.split("\n"):
        if not l.strip() or (l.startswith("- ") and cur):
            if cur:
                out.append(cur)
            cur = [l] if l.strip() else []
        else:
            cur.append(l)
    if cur:
        out.append(cur)
    return out


def as_fact(para, card_sources, src_stems, mh_note, section_src):
    """Абзац → (строка факта, None) или (None, почему остаётся заметкой)."""
    text = " ".join(l.strip() for l in para)
    text = re.sub(r"^- ", "", text).strip()
    for rx, why in LEAVE:
        if re.search(rx, text):
            return None, why
    plain = re.sub(r"^[⭐🪦🔴🚫🏠⚠️️\s]+", "", text)
    label = "Заметка"
    m = re.match(r"\*\*(?:[⭐🪦🔴🚫🏠⚠️️\s]*)(.+?):?\*\*:?\s+(.+)", plain)
    if m:
        label, value = m[1].strip(" :"), m[2]
    elif (m := re.match(r"(\d{4}(?:[-–]\d{4})?)\s+[-–—]\s+(.+)", plain)):
        label, value = m[1].replace("-", "–"), m[2]
    elif (m := re.match(r"([А-ЯЁ][А-ЯЁ ]{3,}[А-ЯЁ])(?: \[[^\]]+\])?\s*[:\-–]\s*(.+)", plain)):
        label, value = m[1].capitalize(), m[2]
    else:
        value = plain
    if "ЗАКРЫТО" in label:   # «ЗАКРЫТО … :» — пометка о закрытом вопросе, а не подпись факта
        label, value = "Заметка", plain
    label = label.rstrip(". ")
    refs = []
    for rx, pick in SOURCES:
        for mm in re.finditer(rx, plain):
            s = pick(mm, src_stems)
            if s and s not in [r[0] for r in refs]:
                near = LOCATOR.search(plain[mm.end(): mm.end() + 25])
                refs.append((s, near[1] if near else ""))
    if not refs and section_src:
        refs = [section_src]
    if not refs and mh_note:
        refs = [(MH, "заметка в дереве")]
    if not refs:
        return None, "источник в тексте не назван"
    conf = "низкая (заметка в дереве MyHeritage, не проверено)" if refs[0][0] == MH else \
        "низкая (вывод проекта)" if refs[0][0].startswith("Реконструкция") or DOUBT.search(value) else "обычная"
    value = value.replace(" — *", " – *").rstrip()
    src = "; ".join(f"[[{s}]]" + (f", {w}" if w else "") for s, w in refs)
    return f"- **{label}:** {value} — *источник: {src} · уверенность: {conf}*", None


NOTE_SECTIONS = [layout.NOTES, "Из досье поиска (июнь–сентябрь 2026)"]


def notes(apply=False):
    tree = cards.load()
    site = mh_people()
    src_stems = [s.stem for s in tree.sources.values()] + [MH]
    changed, kept = [], []
    for p in sorted(tree.people.values(), key=lambda p: p.stem):
        path = paths.TREE / "people" / f"{p.stem}.md"
        head, body = read(path)
        gid = str(p.fm.get("gedcom_id") or "").strip("@")
        mh_text = " ".join(mh.norm(site.get(gid, {}).get("notes", "")).split())
        existing = " ".join(mh.norm(f.text) for f in p.facts)
        existing_lines = {mh.norm(f.text).strip(" .") for f in p.facts}
        new_facts, new_body, card_changes = [], body, []
        for title in NOTE_SECTIONS:
            text, start = section(new_body, title)
            if start < 0 or not text.strip():
                continue
            paras = paragraphs(text)
            sec_src = None
            for para in paras:
                m = re.match(r"Источник: (.+)", " ".join(para).strip())
                if m:
                    for rx, pick in SOURCES:
                        mm = re.search(rx, m[1])
                        if mm and pick(mm, src_stems):
                            near = LOCATOR.search(m[1])
                            sec_src = (pick(mm, src_stems), near[1] if near else "")
                            break
            left, done = [], 0
            for para in paras:
                raw = "\n".join(para)
                core = " ".join(mh.norm(re.sub(r"^- ", "", " ".join(l.strip() for l in para))).split())
                if core and (core[:60] in existing if len(core) >= 25 else core in existing_lines):
                    card_changes.append(("уже есть фактом — абзац убран", raw, ""))
                    done += 1
                    continue
                line, why = as_fact(para, p.sources, src_stems, bool(core) and core[:50] in mh_text, sec_src)
                if line:
                    new_facts.append(line)
                    card_changes.append(("стало фактом", raw, line))
                    done += 1
                else:
                    left.append(raw)
                    if why != "строка-источник для абзацев выше":
                        kept.append((p.stem, why, raw))
            if not done:
                continue
            if all(re.match(r"Источник:", l.strip()) for l in left):   # абзацев, которым служил «Источник:», не осталось
                left = []
            i = new_body.index(f"### {title}\n")
            j = i + len(f"### {title}\n") + len(text)
            new_body = new_body[:i] + (f"### {title}\n\n" + "\n\n".join(left) + "\n\n" if left else "") + new_body[j:]
        if card_changes:
            changed.append((p.stem, card_changes))
            if apply:
                body = add_facts(new_body, last=new_facts)
                for line in new_facts:
                    for s in re.findall(r"\[\[([^\]]+)\]\]", line.split("— *источник:")[1]):
                        prov = {"family": "семья", "found": "найдено", "other_tree": "чужое дерево",
                                "inference": "вывод проекта"}.get(next((x.provenance for x in tree.sources.values()
                                                                        if x.stem == s), "other_tree"))
                        head, body = add_source(head, body, s, "", "низкая" if s == MH else "обычная", prov)
                write(path, head, body)
    report = notes_report(changed, kept)
    if apply and not changed:
        print("переписывать нечего — список _СТАНДАРТ_ПРАВКИ.md не тронут")
        return report
    if apply:
        NOTES_OUT.write_text(report, encoding="utf-8")
    n = sum(1 for _, ch in changed for c in ch if c[0] == "стало фактом")
    print(f"карточек изменено: {len(changed)}; абзацев стало фактами: {n}; осталось заметками: {len(kept)}"
          + ("" if apply else " (ничего не записано: --apply)"))
    return report


def notes_report(changed, kept):
    L = [f"# Факты из свободного текста — что переписано, {date.today():%d.%m.%Y}", "",
         "> Собрано `tools/scripts/card_standard.py notes`. Павлу — проверить: слова те же, источник тот, что назван в "
         "тексте.", "",
         "**Что это.** В части карточек сведения о человеке записаны не строками фактов, а свободным текстом — в "
         "разделах «Заметки (из дерева MyHeritage и записей проекта)» и «Из досье поиска». Сайт такой текст не видит: "
         "он показывает только строки «Фактов (с источником)». Скрипт переписал абзацы в строки фактов — **слово в "
         "слово**, с тем источником, который назван в самом тексте (Doc07, «воспоминания Ясеневой А. П., стр. 3», "
         f"Аудио 03, «от отца»), а если абзац — заметка из дерева MyHeritage, то с источником [[{MH}]] и "
         "уверенностью «низкая». Абзац без названного источника остался заметкой — он в конце списка.", "",
         f"## Переписано — {len(changed)} карточек", ""]
    for stem, ch in changed:
        L.append(f"### [[{stem}]]")
        for what, raw, line in ch:
            L.append(f"- {what}:")
            L += ["  > " + x for x in raw.split("\n")]
            if line:
                L.append(f"  → `{line[:400]}`" if len(line) > 400 else f"  → `{line}`")
        L.append("")
    L += [f"## Осталось заметками — {len(kept)}", "", "| Карточка | Почему | Начало абзаца |", "|---|---|---|"]
    L += [f"| [[{s}]] | {why} | {raw.replace(chr(10), " ").replace("|", chr(92) + "|")[:120]} |" for s, why, raw in kept]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "years":
        years("--apply" in sys.argv)
    elif cmd == "notes":
        notes("--apply" in sys.argv)
    else:
        print(__doc__)
