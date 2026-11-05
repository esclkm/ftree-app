#!/usr/bin/env python3
"""Переезды без объяснения — где у человека два места подряд, а записи о переезде нет.

Зачем. Церковная книга и перепись видят только свой приход. Ушёл человек в другую деревню — и в «нашей» книге он
пропал. Каждый такой переезд — дыра для поиска: почему ушёл (свадьба, помещик, служба, работа, беженство) и где тогда
остался след (`<папка поиска>/plans/13_Алгоритмы_генеалогов_сверка.md`, раздел «Переезды»).

Что считает. У каждого родственника (есть ветка lineage) — точки «год → место» из рождения, смерти, линии жизни
биографии (колонка «Где») и строк фактов со ссылкой на место. Точки по годам; соседние точки в разных местах дальше
MIN_KM друг от друга (или в разных странах, если координат нет) — переезд. Переезд «объяснён», если в строке, где
человек появился на новом месте, или между двумя точками есть слово о причине (переехал, женился, служба, беженство…).

  tools/py tools/scripts/migrations.py                  # необъяснённые переезды до 1945 года, по веткам
  tools/py tools/scripts/migrations.py --before 2000    # граница по году
  tools/py tools/scripts/migrations.py --all            # и объяснённые тоже (с причиной)
  tools/py tools/scripts/migrations.py --who "Прокоп Ясенев"

Это не проверка «по нулям»: дыры будут всегда. Это список задач для поиска.
"""
import argparse
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cards  # noqa: E402
import paths  # noqa: E402
import tree as T  # noqa: E402
from cards.notes import link_target  # noqa: E402

MIN_KM = 8          # ближе — та же округа (соседняя деревня того же прихода), не переезд
COARSE = {"country", "region", "district", "river"}   # страна, область, река — слишком крупно для точки
REASON = re.compile(
    r"пере(ех|езд|сел|вед|числ)|уехал|уеха|вернул|бежен|эвакуац|депорт|выслан|ссылк|призван|служб|арми|рекрут|"
    r"плен|лагер|угнан|замуж|женил|венча|брак|свадьб|учёб|учил|поступил|работ|назначен|мещан|причисл|купил|"
    r"хутор|остался|ушёл|ушла|в гости", re.I)
LINK = re.compile(r"\[\[[^\]]+\]\]")


def year(text):
    m = re.search(r"(1[5-9]\d\d|20\d\d)", text or "")
    return int(m[1]) if m else None


def place_index(tr):
    idx = {}
    for pl in tr.places.values():
        for n in [pl.stem, pl.name, *pl.aliases]:
            if n:
                idx.setdefault(str(n).strip().lower(), pl.id)
    return idx


def chain(tr, pid):
    out = []
    while pid and pid in tr.places and pid not in out:
        out.append(pid)
        pid = tr.places[pid].parent
    return out


def coords(tr, pid):
    for p in chain(tr, pid):
        if tr.places[p].coords:
            return tr.places[p].coords
    return None


def km(a, b):
    (la1, lo1), (la2, lo2) = a, b
    x = math.radians(lo2 - lo1) * math.cos(math.radians((la1 + la2) / 2))
    return 6371 * math.hypot(x, math.radians(la2 - la1))


def country(tr, pid):
    c = chain(tr, pid)
    return c[-1] if c else None


def moved(tr, a, b):
    """Разные места и правда далеко: ни одно не внутри другого, дальше MIN_KM (без координат — разные страны)."""
    if a == b:
        return False
    ca, cb = chain(tr, a), chain(tr, b)
    if a in cb or b in ca:
        return False
    pa, pb = coords(tr, a), coords(tr, b)
    if pa and pb:
        return km(pa, pb) > MIN_KM
    return country(tr, a) != country(tr, b)


def settle(tr, pid):
    """Точка на карте — населённое место: кладбище, дом, больница → их город; страна, область, река — None."""
    while pid in tr.places and tr.places[pid].type not in ("city", "village", "town", "locality") + tuple(COARSE):
        pid = tr.places[pid].parent
    return pid if pid in tr.places and tr.places[pid].type not in COARSE else None


def points(tr, idx, lifelines):
    """cr_id → [(год, место, откуда строка, текст)]."""
    out = {}
    for p in tr.people.values():
        if not p.fm.get("lineage"):
            continue
        pts = []
        if p.birth_place and p.born and p.born.sort_key():
            pts.append((int(p.born.sort_key()[:4]), p.birth_place, "рождение", ""))
        if p.death_place and p.died and p.died.sort_key():
            pts.append((int(p.died.sort_key()[:4]), p.death_place, "смерть", ""))
        for f in p.facts:
            y = int(f.date.sort_key()[:4]) if f.date and f.date.sort_key() else None
            for raw in LINK.findall(f.text):
                pid = idx.get(link_target(raw).strip().lower())
                if pid and y:
                    pts.append((y, pid, "факт", f.text))
        for when, what, where in lifelines.get(p.id, []):
            y = year(when)
            for w in where:
                pid = idx.get(str(w).strip().lower())
                if pid and y:
                    pts.append((y, pid, "линия жизни", f"{when}: {what}"))
        pts = [(y, settle(tr, pl), k, t) for y, pl, k, t in pts]
        out[p.id] = sorted((x for x in pts if x[1]), key=lambda t: t[0])
    return out


def gaps(tr, pts):
    """cr_id → [(год до, место до, год после, место после, причина или '')]."""
    out = {}
    for pid, ps in pts.items():
        rows, last = [], None
        for i, pt in enumerate(ps):
            # одна строка с несколькими местами («Минск, Лесогорск», маршрут войны) — описанный путь, не дыра
            if last and moved(tr, last[1], pt[1]) and not (pt[3] and pt[3] == last[3]):
                between = [x[3] for x in ps if last[0] <= x[0] <= pt[0]]
                why = next((m[0] for t in between for m in [REASON.search(t or "")] if m), "")
                rows.append((last[0], last[1], pt[0], pt[1], why))
            last = pt
        if rows:
            out[pid] = rows
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--before", type=int, default=1945, help="только переезды, начавшиеся до этого года")
    ap.add_argument("--all", action="store_true", help="и объяснённые переезды")
    ap.add_argument("--who", help="один человек (имя карточки или cr_id)")
    a = ap.parse_args(argv)

    tr = cards.load()
    idx = place_index(tr)
    lifelines = {}
    for owner, when, what, where in T.lifeline_places(tr, paths.ROOT):
        lifelines.setdefault(owner, []).append((when, what, where))
    found = gaps(tr, points(tr, idx, lifelines))

    if a.who:
        hit = [p for p in tr.people.values() if a.who in (p.id, p.stem, p.name)]
        found = {k: v for k, v in found.items() if hit and k == hit[0].id}

    by_line, n_open, n_why = {}, 0, 0
    for pid, rows in found.items():
        p = tr.people[pid]
        for y1, p1, y2, p2, why in rows:
            if y1 >= a.before:
                continue
            n_why += bool(why)
            n_open += not why
            if why and not a.all:
                continue
            line = (p.fm.get("lineage") or ["?"])
            line = line[0] if isinstance(line, list) else str(line)
            what = f"{tr.places[p1].stem} ({y1}) → {tr.places[p2].stem} ({y2})"
            by_line.setdefault(line, []).append((y1, f"  {T.label(p)}: {what}" + (f" — причина: «{why}»" if why else "")))

    print(f"Переезды до {a.before} года: без объяснения {n_open}, с причиной {n_why}.")
    for line in sorted(by_line):
        print(f"\n{line}:")
        for _, row in sorted(by_line[line]):
            print(row)
    if not by_line:
        print("Нет.")


if __name__ == "__main__":
    main()
