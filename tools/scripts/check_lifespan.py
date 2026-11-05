#!/usr/bin/env python3
"""Годы жизни в карточке — не пустые, если мы их знаем.

Шапку профиля на сайте («1921–2006») и дерево строят только поля `born` / `died` карточки. Если год выяснили, но
вписали лишь в текст — в факт «**смерть:** …» или в заголовок биографии «Ева … (1921 – ~2005)», — на сайте будет
«1921–?». Этот скрипт ищет такие места.

  ОШИБКА    `born` / `died` пусты, а год есть в заголовке своей биографии или в строке факта «рождение» / «смерть»;
  ВНИМАНИЕ  то же, но год — только в факте с «уверенность: низкая» (например, «может относиться к другой паре»):
            решить глазами — вписать (ABT, BET … AND …) или оставить пустым;
  ВНИМАНИЕ  год в карточке и год в заголовке биографии расходятся больше чем на год.

Год, посчитанный из возраста («умерла в 84 года» при рождении в 1921), — в карточку промежутком: `died: BET 2005 AND 2006`
(как пишутся даты — навык dates; проверяет check_dates.py).
Строки факта со словами «между», «после», «до» (пределы, а не год) — не требуют заполнения.

  python3 tools/scripts/check_lifespan.py                 # все
  python3 tools/scripts/check_lifespan.py "Ewa Jasieniew"
Код выхода 1, если есть ошибки.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import site_export as b  # noqa: E402

YEAR = re.compile(r"(?<!\d)(1[5-9]\d\d|20\d\d)(?!\d)")
FACT = {"born": re.compile(r"^- \*\*(рождение|родил[а-я]*)[^*]*:\*\*(.*)$", re.M | re.I),
        "died": re.compile(r"^- \*\*(смерть|умер[а-я]*|гибель|погиб[а-я]*)[^*]*:\*\*(.*)$", re.M | re.I)}
BOUND = re.compile(r"между|после|не позже|не раньше|\bдо\b", re.I)


def years(v):
    return [int(y) for y in YEAR.findall(str(v or ""))]


def from_facts(body, key):
    """Годы из строк факта (только само значение — до «— *источник»): (уверенные, с уверенностью «низкая»)."""
    sure, weak = [], []
    for m in FACT[key].finditer(body):
        val = re.split(r"—\s*\*источник", m.group(2))[0]
        if BOUND.search(val):
            continue
        (weak if "уверенность: низкая" in m.group(2) else sure).extend(years(val))
    return sure, weak


def from_bio_head(d):
    """«# Ева … (1921 – ~2005)» / «(род. 1934)» в начале своей биографии — только для биографии целиком."""
    for ref in b.bio_refs(d):
        if "#" in ref:
            continue
        p = b.md_file(ref)
        if not p:
            continue
        m = re.match(r"\s*#[ \t]([^\n]*)", p.read_text(encoding="utf-8"))
        if not m:
            continue
        g = re.search(r"\((?:род\.\s*)?~?(\d{4})\s*(?:[–-]\s*~?(\d{4})?)?\)\s*$", m.group(1))
        if g:
            return (int(g.group(1)), int(g.group(2)) if g.group(2) else None)
    return (None, None)


def check(d):
    f, body = d["f"], d["body"]
    errs, warns = [], []
    head = dict(zip(("born", "died"), from_bio_head(d)))
    for key, lab in (("born", "рождения"), ("died", "смерти")):
        have = years(f.get(key))
        sure, weak = from_facts(body, key)
        known = sorted(set(sure + ([head[key]] if head[key] else [])))
        if not have and known:
            errs.append(f"`{key}` пусто, а год {lab} известен: {', '.join(map(str, known))}")
        elif not have and weak:
            warns.append(f"`{key}` пусто; год {lab} {', '.join(map(str, sorted(set(weak))))} — только с уверенностью «низкая»")
        elif have and head[key] and min(abs(head[key] - y) for y in have) > 1:
            warns.append(f"`{key}: {f.get(key)}` — а в заголовке биографии {head[key]}")
    return errs, warns


def main():
    only = sys.argv[1:]
    n_err = n_warn = 0
    for d in sorted(b.people.values(), key=lambda d: d["stem"]):
        if only and d["stem"] not in only:
            continue
        errs, warns = check(d)
        if errs or warns:
            print(f"\n{d['stem']}")
            for e in errs:
                print(f"  ✗ {e}")
            for w in warns:
                print(f"  · {w}")
        n_err += len(errs)
        n_warn += len(warns)
    print(f"\nГоды жизни: ошибок {n_err}, предупреждений {n_warn}")
    return 1 if n_err else 0


if __name__ == "__main__":
    sys.exit(main())
