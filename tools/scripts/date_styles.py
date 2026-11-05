#!/usr/bin/env python3
"""Стиль точных дат до 14.02.1918: где в дереве дата по старому стилю, где по новому, где неясно.

Зачем. Правило (Павел, 20.10.2026; шапка dates.py): главная дата везде — по новому стилю, дата документа по старому —
рядом. Раньше писали «как в документе», и в дереве смешались оба стиля: у одних людей в карточке дата из православной
метрики (старый стиль), у других — уже пересчитанная (новый). Скрипт смотрит каждую точную дату до 1918 года:

  карточки людей      born, died
  карточки событий    date
  биографии           колонка даты «Линии жизни»

и сверяет её с датами в тексте той же карточки (строки фактов), рядом с которыми написано «ст. ст.» или «н. ст.»:

  НОВЫЙ      дата совпала с датой «н. ст.» или с переводом даты «ст. ст.» — всё верно;
  СТАРЫЙ     дата совпала с датой «ст. ст.» — надо перевести (--fix переводит карточку; в линии жизни — check_dates --fix);
  НЕЯСНО     пометок нет — стиль решает источник: православная метрика — старый, костёл и ЗАГС после 1918 — новый;
             записано с подсказкой, откуда дата (источник строки факта с этой датой).

  tools/py tools/scripts/date_styles.py           # отчёт в консоль и 3_research/tree/_СТИЛИ_ДАТ.md
  tools/py tools/scripts/date_styles.py --fix     # СТАРЫЙ в карточках → новый стиль (старый — в строку факта не пишем:
                                                  # он уже там, рядом с «ст. ст.»)
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dates  # noqa: E402
import paths  # noqa: E402

ROOT = paths.ROOT
TREE = paths.TREE
OUT = TREE / "_СТИЛИ_ДАТ.md"
GEN = "|".join(dates.MONTHS_GEN)
MON = {w: i + 1 for i, w in enumerate(dates.MONTHS_GEN)}
# даты в тексте: «13.06.1888», «13 июня 1888», «1888, 13 июня»
RX = [
    (re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.(1[0-9]\d\d)(?!\d)"), lambda m: (int(m[3]), int(m[2]), int(m[1]))),
    (re.compile(rf"(?<!\d)(\d{{1,2}}) ({GEN}) (1[0-9]\d\d)(?!\d)"), lambda m: (int(m[3]), MON[m[2]], int(m[1]))),
    (re.compile(rf"(?<!\d)(1[0-9]\d\d),? (\d{{1,2}}) ({GEN})(?![а-я])"), lambda m: (int(m[1]), MON[m[3]], int(m[2]))),
]
OS = re.compile(r"ст\.\s?ст\.|старому стилю|по ст\. ст")
NS = re.compile(r"н\.\s?ст\.|новому стилю")
FULL = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def day(t):
    try:
        return dates.Day(*t)
    except dates.DateError:
        return None


ANYDATE = re.compile(rf"(?<!\d)\d{{1,2}}(?:\.\d{{1,2}}|\s(?:{GEN}))")   # начало следующей даты (и без года: «24 октября»)
SHORT_OS = re.compile(rf"(?<!\d)(\d{{1,2}}) ({GEN}) (?:по старому стилю|ст\.\s?ст\.)")


def mentions(text):
    """Все полные даты в тексте: (Day, стиль рядом: 'os' | 'ns' | '', строка текста). Пометка стиля относится к
    ближайшей к ней дате: в «05.11.1889 (24 октября по старому стилю)» старая — 24 октября, а 05.11 — новая."""
    out = []
    for line in text.split("\n"):
        for rx, conv in RX:
            for m in rx.finditer(line):
                d = day(conv(m))
                if not d:
                    continue
                after = line[m.end():m.end() + 45]
                nxt = ANYDATE.search(after)
                own = after[:nxt.start()] if nxt else after
                inner = SHORT_OS.search(after[:45])
                if inner and nxt and nxt.start() == inner.start():
                    jd = day((d.y, MON[inner[2]], int(inner[1])))
                    if jd and dates.julian_to_gregorian(jd) == d:
                        out.append((d, "ns", line.strip()))
                        out.append((jd, "os", line.strip()))
                        continue
                before = line[max(0, m.start() - 12):m.start()]
                st = "os" if OS.search(own) or OS.search(before) and not ANYDATE.search(before) else \
                     "ns" if NS.search(own) else ""
                out.append((d, st, line.strip()))
    return out


def judge(value, text):
    """Стиль даты value (Day) по упоминаниям в тексте карточки: ('НОВЫЙ'|'СТАРЫЙ'|'НЕЯСНО', пояснение, дата по старому
    стилю или None)."""
    ms = mentions(text)
    for d, st, line in ms:
        if st == "os" and d == value:
            return "СТАРЫЙ", f"в тексте «{d.ru()} ст. ст.» → по новому {dates.julian_to_gregorian(d).ru()}", d
    for d, st, line in ms:
        if st == "os" and dates.julian_to_gregorian(d) == value:
            return "НОВЫЙ", f"перевод «{d.ru()} ст. ст.»", d
    for d, st, line in ms:
        if st == "ns" and d == value:
            return "НОВЫЙ", "в тексте помечено «н. ст.»", None
    src = ""
    for d, st, line in ms:
        if d == value or dates.julian_to_gregorian(d) == value:
            s = re.search(r"источник: \[\[([^\]|]+)", line)
            src = s[1] if s else line[:90]
            break
    return "НЕЯСНО", ("источник: " + src) if src else "в тексте дата не встречается", None


def card_dates(p, keys):
    text = p.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---", text, re.S)
    if not m:
        return []
    out = []
    for k in keys:
        f = re.search(rf"^{k}: *['\"]?([^'\"\n]+)", m[1], re.M)
        if f and (g := FULL.match(f[1].strip())):
            d = day((int(g[1]), int(g[2]), int(g[3])))
            if d and dates.old_style_era(d):
                out.append((k, d))
    return out


def life_dates(p):
    """Точные даты до 1918 в «Линии жизни» биографии: (номер строки, Day, ячейка)."""
    out = []
    for n, line in enumerate(p.read_text(encoding="utf-8").split("\n"), 1):
        c = re.match(r"\|\s*([^|]+?)\s*\|", line)
        if not c:
            continue
        g = dates.ru_or_none(c[1])
        if g and g.kind == "" and g.a and g.a.d and dates.old_style_era(g.a):
            out.append((n, g, c[1]))
    return out


def linked(text):
    """Тексты карточек людей, названных в событии (persons: [[…]]), и их биографий."""
    out = []
    for name in re.findall(r"\[\[([^\]|#]+)", text):
        for q in (TREE / "people" / f"{name}.md", TREE / "biographies" / f"{name} — биография.md"):
            if q.exists():
                out.append(q.read_text(encoding="utf-8"))
    return out


def person_card(bio):
    m = re.search(r'^person: "\[\[([^\]|]+)', bio.read_text(encoding="utf-8"), re.M)
    p = TREE / "people" / f"{m[1]}.md" if m else None
    return p if p and p.exists() else None


def main():
    fix = "--fix" in sys.argv
    rows = []
    for kind, keys in (("people", ("born", "died")), ("events", ("date",))):
        for p in sorted((TREE / kind).glob("*.md")):
            text = p.read_text(encoding="utf-8")
            # биография бывает только у человека; у события её не ищем: имя «<длинное событие> — биография.md»
            # длиннее 255 байт, и на Linux (GitHub) bio.exists() падает с «File name too long» (22–25.10.2026)
            bio = TREE / "biographies" / f"{p.stem} — биография.md" if kind == "people" else None
            ctx = (text + "\n" + "\n".join(linked(text)) if kind == "events" else text) + (
                "\n" + bio.read_text(encoding="utf-8") if bio and bio.exists() else "")
            for k, d in card_dates(p, keys):
                verdict, why, _ = judge(d, ctx)
                rows.append((verdict, f"{kind}/{p.stem}", f"{k}: {d.iso()}", why))
                if fix and verdict == "СТАРЫЙ":
                    new = dates.julian_to_gregorian(d).iso()
                    text = re.sub(rf"^({k}: *['\"]?){d.iso()}", rf"\g<1>{new}", text, count=1, flags=re.M)
                    p.write_text(text, encoding="utf-8")
                    print(f"Поправлено: {p.relative_to(ROOT)} — {k}: {d.iso()} → {new} (ст. ст. → н. ст.)")
    for p in sorted(TREE.glob("biographies/*.md")):
        card = person_card(p)
        btext = p.read_text(encoding="utf-8")
        ctext = (card.read_text(encoding="utf-8") if card else "") + "\n" + btext
        lines, changed = btext.split("\n"), False
        for n, g, cell in life_dates(p):
            if g.os:
                rows.append(("НОВЫЙ", f"biographies/{p.stem}:{n}", cell, "старый стиль рядом"))
                continue
            if g.julian:
                rows.append(("СТАРЫЙ", f"biographies/{p.stem}:{n}", cell, "check_dates --fix переведёт"))
                continue
            verdict, why, os_day = judge(g.a, ctext)
            rows.append((verdict, f"biographies/{p.stem}:{n}", cell, why))
            if fix and os_day:   # СТАРЫЙ — перевести; НОВЫЙ по переводу — дописать старый стиль рядом
                ns = dates.julian_to_gregorian(os_day)
                rest = "; ".join(x for x in g.phrase.split("; ") if x and not SHORT_OS.fullmatch(x.strip()))
                new = dates.GDate("", ns, phrase=rest, os=os_day).ru()   # «7 марта по старому стилю» — уже в os
                lines[n - 1] = lines[n - 1].replace(cell, new, 1)
                changed = True
                print(f"Поправлено: {p.relative_to(ROOT)}:{n} — «{cell}» → «{new}»")
        if changed:
            p.write_text("\n".join(lines), encoding="utf-8")
    order = {"СТАРЫЙ": 0, "НЕЯСНО": 1, "НОВЫЙ": 2}
    rows.sort(key=lambda r: (order[r[0]], r[1]))
    count = {v: sum(r[0] == v for r in rows) for v in order}
    lines = ["# Стиль точных дат до 1918 года", "",
             "Собирает `rodo date-styles` — руками не править. Правило: главная дата — по новому стилю, "
             "дата документа по старому — рядом (шапка скрипта `dates.py`).", "",
             f"Старый стиль главной датой (перевести): **{count['СТАРЫЙ']}** · неясно (решить по источнику): "
             f"**{count['НЕЯСНО']}** · новый: {count['НОВЫЙ']}.", "",
             "| Стиль | Где | Дата | Почему так решено |", "|---|---|---|---|"]
    plain = lambda t: re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]?\]?", r"\1", re.sub(r"\\\|", "|", t)).replace("[[", "").replace("|", "/")
    lines += [f"| {v} | {w} | {d} | {plain(why)} |" for v, w, d, why in rows]   # без ссылок: обрезанная ссылка — битая
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for v, w, d, why in rows:
        if v != "НОВЫЙ":
            print(f"{v:7} {w} — {d} — {why}")
    print(f"Стиль дат до 1918: старый {count['СТАРЫЙ']}, неясно {count['НЕЯСНО']}, новый {count['НОВЫЙ']} → {OUT.relative_to(ROOT)}")
    return 1 if count["СТАРЫЙ"] and not fix else 0   # старый стиль главной датой — ошибка; неясное — задача, не ошибка


if __name__ == "__main__":
    sys.exit(main())
