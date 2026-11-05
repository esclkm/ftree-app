#!/usr/bin/env python3
"""Даты — как в GEDCOM (правило: навык dates; виды дат и их запись — шапка tools/scripts/dates.py).

Проверяет каждую дату, которую читают сайт, дерево и выгрузка в MyHeritage:

  карточки людей      born, died             — запись карточки: 1935 · 1935-05-12 · ABT 1935 · BET 2005 AND 2006
  карточки событий    date                   — то же, плюс FROM 1941 TO 1945 (длилось всё это время)
  биографии           колонка даты в таблице «Линия жизни» (та же таблица, что берёт сайт) — по-русски, одна запись
                      на вид: ок. 1935 · до 1944 · между 1941 и 1945 · 1941–1945 · 1945 (после войны) · (без даты)

  ОШИБКА  дата не разбирается («~1935», «потом», «1943 / 1944», «2005 - 2006» в карточке);
  ОШИБКА  дата разбирается, но записана не так, как принято («7.04.2010» вместо «07.04.2010», «1941 – 1945»
          вместо «1941–1945»): у каждого вида одна запись. --fix поправит сам, если может.
  ОШИБКА  точная дата до 1918 главной записью по старому стилю («13.06.1888 ст. ст.»): главная — по новому, старая —
          в скобках, «25.06.1888 (13.06.1888 ст. ст.)»; --fix переведёт сам. Стиль дат в карточках — date_styles.py.
  ОШИБКА  в колонке даты линии жизни — выделение или значки («**1951**», «⭐ 1955», «⚠️ **29.07.1951**»): там только
          дата. --fix уберёт, значок перенесёт в начало текста строки («⭐ развилка судьбы…»).

  python3 tools/scripts/check_dates.py              # всё
  python3 tools/scripts/check_dates.py --file "3_research/tree/biographies/Прокоп Ясенев — биография.md"   # так зовут хук
                                                   # и pre-commit (sync.py: только файлы коммита); --file — можно несколько
  python3 tools/scripts/check_dates.py --fix        # поправить то, что правится без человека
Код выхода 1, если остались ошибки. Переводы биографий (translations/) не проверяются: сайт их таблицы не показывает.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dates  # noqa: E402
import paths  # noqa: E402

ROOT = paths.ROOT
FIELDS = {"people": ("born", "died"), "events": ("date",)}
EDGE = re.compile(r"^([\s⭐✅🟡❓⚠️️*_]*)(.*?)([\s⭐✅🟡❓⚠️️*_]*)$", re.S)


def cells(row):
    return [c.strip() for c in row.replace("\\|", "\x00").strip().strip("|").split("|")]


def life_tables(text):
    """Таблицы «Линии жизни» в биографии — по тем же признакам, что у сайта (site_export.split_lifeline), но и внутри
    раздела ребёнка или жены: их таблицу сайт показывает на их собственной странице. → (номер строки заголовка
    таблицы, номер колонки даты)."""
    import site_export as b
    for m in b.TABLE.finditer(text):
        lines = [r for r in m.group(1).splitlines() if r.strip()]
        if len(lines) < 3:
            continue
        hm = list(re.finditer(r"^(#+)[ \t]+([^\n]*)$", text[:m.start()], re.M))
        heading = hm[-1].group(2) if hm else ""
        head = [re.sub(r"[*_`⭐]", "", h).strip() for h in cells(lines[0])]
        wi = next((i for i, h in enumerate(head) if b.WHEN_COL.match(h)), None)
        if wi is None:
            continue
        what = 1 if wi == 0 else 0
        if not b.LIFE_HEAD.search(heading) and (len(head) < 2 or not b.WHAT_COL.match(head[what]) or "[[" in heading):
            continue
        yield text[:m.start()].count("\n"), wi


MARKS = re.compile(r"⭐|✅|🟡|❓|⚠️?")


def check_bio(p, fix):
    """Колонка даты «Линии жизни»: только дата — принятой записью, без **жирного**, звёздочек и значков. Значок
    (⭐ важно, ⚠️ спорно…) при починке переезжает в начало текста строки — пометка остаётся при событии."""
    errs, text = [], p.read_text(encoding="utf-8")
    lines = text.split("\n")
    changed = False
    for start, wi in life_tables(text):
        what = 1 if wi == 0 else 0
        i = start + 2  # заголовок таблицы и строка «|---|»
        while i < len(lines) and lines[i].lstrip().startswith("|"):
            c = cells(lines[i])
            if wi < len(c) and c[wi]:
                raw = c[wi].replace("\x00", "\\|")
                try:
                    g0 = dates.parse_ru(raw)
                    g = g0.new_style()        # главная дата — по новому стилю, старый — рядом в скобках
                    if raw != g.ru():
                        marks = "".join(MARKS.findall(raw))
                        if fix:
                            c = [x.replace("\x00", "\\|") for x in c]
                            c[wi] = g.ru()
                            if marks and what < len(c) and not c[what].startswith(marks):
                                c[what] = f"{marks} {c[what]}"
                            lines[i] = "| " + " | ".join(c) + " |"
                            changed = True
                        else:
                            why = ("главная дата — по новому стилю, старый — в скобках: " if g is not g0 else "") + (
                                "только дата, без выделения и значков" if dates.clean(raw) == g.ru() else f"пиши «{g.ru()}»")
                            errs.append(f"{p.relative_to(ROOT)}:{i + 1} — «{raw}» → {why}")
                except dates.DateError as e:
                    errs.append(f"{p.relative_to(ROOT)}:{i + 1} — {e}")
            i += 1
    if changed:
        p.write_text("\n".join(lines), encoding="utf-8")
        print(f"Поправлено: {p.relative_to(ROOT)}")
    return errs


def check_card(p, keys, fix):
    errs, text = [], p.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---", text, re.S)
    if not m:
        return errs
    fm, new_fm = m.group(1), m.group(1)
    for n, line in enumerate(fm.split("\n"), 2):
        k = re.match(rf"^({'|'.join(keys)}): *(['\"]?)(.*?)\2 *$", line)
        if not k or not k[3]:
            continue
        v = k[3]
        try:
            g = dates.parse_card(v)
            if g.card() != v:
                errs.append(f"{p.relative_to(ROOT)}:{n} — {k[1]}: «{v}» → пиши «{g.card()}»")
        except dates.DateError as e:
            old = re.fullmatch(r"(\d{4})\s*-\s*(\d{4})", v)  # прежняя запись промежутка: «2005 - 2006»
            if fix and old and "people" in p.parts:
                new_fm = new_fm.replace(line, f"{k[1]}: BET {old[1]} AND {old[2]}", 1)
            else:
                errs.append(f"{p.relative_to(ROOT)}:{n} — {k[1]}: {e}")
    if new_fm != fm:
        p.write_text(text.replace(fm, new_fm, 1), encoding="utf-8")
        print(f"Поправлено: {p.relative_to(ROOT)}")
    return errs


def targets(only):
    tree = paths.TREE
    for kind, keys in FIELDS.items():
        for p in sorted((tree / kind).glob("*.md")):
            if not only or p.resolve() in only:
                yield p, keys
    for p in sorted(paths.RESEARCH.glob("*/biographies/*.md")):
        if not only or p.resolve() in only:
            yield p, None


def main():
    args = sys.argv[1:]
    fix = "--fix" in args
    only = {(ROOT / args[i + 1]).resolve() for i, a in enumerate(args) if a == "--file" and i + 1 < len(args)}
    errs = []
    for p, keys in targets(only):
        errs += check_card(p, keys, fix) if keys else check_bio(p, fix)
    for e in errs:
        print("ОШИБКА  " + e)
    print(f"Даты не по правилу: {len(errs)}")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
