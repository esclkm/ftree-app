#!/usr/bin/env python3
"""Могилы в Беларуси — поиск человека по базе захоронений spachyn.by.

Зачем. В Беларуси нет одной базы кладбищ. Самая полная открытая — spachyn.by (~957 тыс. имён, 5,6 тыс. кладбищ;
те же записи, что у pomnim.by, но кладбище и район видны без входа). Запись даёт годы жизни (часто точные даты),
район и иногда кладбище — то есть дату смерти и где человек жил в конце жизни. Навык — archive-belarus-graves.

    tools/py tools/scripts/graves_by.py name "Ясенев Прокоп"                 # один запрос, все строки
    tools/py tools/scripts/graves_by.py name "Ясенев Иван" --died 1950       # пометить совпавших по году
    tools/py tools/scripts/graves_by.py person "Прокоп Ясенев"                # по карточке: имя, годы, фамилия мужа
    tools/py tools/scripts/graves_by.py tree --max 20                        # умершие в Беларуси с 1941 г. — пачкой

Запросы — по одному, пауза 4 с (сайт маленький, не злить). Итог — в журнал поиска:
    tools/py tools/scripts/searched.py add spachyn.by "<запрос>" "" "<кого>" "graves_by.py" "<итог>"

Совпадение: фамилия + имя + год смерти (±1) — «сильное»; без года смерти, но год рождения (±1) — «по рождению»;
только имя — «имя» (тёзок много: свой ли — по отчеству = имя отца в карточке).
"""
import argparse
import html
import re
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, __import__("os").path.dirname(__file__))

BASE = "https://spachyn.by"
UA = "Mozilla/5.0 (Macintosh) family-tree-research"
PAUSE = 4.0
LI = re.compile(r'<li class="card[^"]*">(.*?)</li>', re.S)


def _text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def search(q, region="", death_from="", death_to=""):
    """Строки выдачи: name, dates, place, notes, url. Первая страница (до ~20 строк) — этого хватает:
    точные совпадения сайт ставит первыми."""
    params = {"q": q}
    if region:
        params["region"] = region
    if death_from:
        params["death_from"] = death_from
    if death_to:
        params["death_to"] = death_to
    url = f"{BASE}/search?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        s = r.read().decode("utf-8", "replace")
    rows = []
    for li in LI.findall(s):
        a = re.search(r'href="(/person/[^"]+)"[^>]*>(.*?)</a>', li, re.S)
        if not a:
            continue
        ps = re.findall(r"<p[^>]*>(.*?)</p>", li, re.S)
        dates = _text(ps[0]) if ps else ""
        place = _text(re.search(r'<span class="line-clamp-2">(.*?)</span>', li, re.S).group(1)) \
            if 'line-clamp-2' in li else ""
        notes = [_text(x) for x in re.findall(r'<span class="status-pill[^"]*">(.*?)</span>', li, re.S)]
        rows.append({"name": _text(a.group(2)), "dates": dates, "place": place, "notes": notes,
                     "url": BASE + a.group(1)})
    return url, rows


def _years(dates):
    parts = [p.strip() for p in dates.split("—")]
    out = []
    for p in parts + [""] * (2 - len(parts)):
        m = re.search(r"(\d{4})", p)
        out.append(int(m.group(1)) if m else None)
    return out[0], out[1]


def grade(row, given, born=None, died=None, surname=""):
    """Насколько строка похожа на нашего человека."""
    words = row["name"].lower().replace("ё", "е").split()
    if given and given.lower().replace("ё", "е") not in words:
        return ""
    if surname and (not words or words[0].rstrip("а") != surname.lower().replace("ё", "е").rstrip("а")):
        return ""          # похожая, но другая фамилия (Ясенко вместо Ясенев)
    b, d = _years(row["dates"])
    if died and d and abs(d - died) <= 1:
        return "сильное"
    if born and b and abs(b - born) <= 1 and not (died and d):
        return "по рождению"
    if (died and d) or (born and b):
        return ""          # годы есть и не сходятся — тёзка
    return "имя"


def show(q, rows, given="", born=None, died=None, only_match=False):
    print(f"— {q}: {len(rows)} строк")
    for r in rows:
        g = grade(r, given, born, died, q.split()[0]) if given else ""
        if only_match and not g:
            continue
        mark = f"  [{g}]" if g else ""
        print(f"    {r['name']} · {r['dates']} · {r['place']}{mark}")
        if g:
            print(f"      {r['url']}  ({'; '.join(r['notes'])})")


def _split(name):
    """«Прокоп Ясенев» → («Прокоп», «Ясенев»); скобки и уточнения отбрасываем."""
    w = re.sub(r"\(.*?\)", "", name).split()
    return (" ".join(w[:-1]), w[-1]) if len(w) >= 2 else ("", w[0] if w else "")


def queries_for(p, tree):
    """Запросы по карточке: своё имя и, у женщины, — с фамилией каждого мужа (хоронят под фамилией мужа)."""
    given, surname = _split(p.name)
    qs = [(f"{surname} {given}", given)]
    if p.sex == "F":
        for sid in p.spouses:
            s = tree.people.get(sid)
            if s:
                ms = _split(s.name)[1]
                if ms and ms != surname:
                    qs.append((f"{ms} {given}", given))
    return qs


def in_belarus(tree, place_id):
    seen = set()
    while place_id and place_id not in seen:
        seen.add(place_id)
        pl = tree.places.get(place_id)
        if not pl:
            return False
        if pl.name in ("Беларусь", "Belarus"):
            return True
        place_id = pl.parent
    return False


def _y(g):
    return g.first_year if g else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("name")
    a.add_argument("q")
    a.add_argument("--born", type=int)
    a.add_argument("--died", type=int)
    b = sub.add_parser("person")
    b.add_argument("stem")
    c = sub.add_parser("tree")
    c.add_argument("--max", type=int, default=20)
    c.add_argument("--since", type=int, default=1941, help="умершие с этого года (раньше в базе почти пусто)")
    args = ap.parse_args()

    if args.cmd == "name":
        _, rows = search(args.q)
        given = args.q.split()[1] if len(args.q.split()) > 1 else ""
        show(args.q, rows, given, args.born, args.died)
        return

    import cards
    tree = cards.load()
    if args.cmd == "person":
        p = tree.person(args.stem) or next((x for x in tree.people.values() if x.name == args.stem), None)
        if not p:
            sys.exit(f"нет карточки «{args.stem}»")
        people = [p]
    else:
        people = [p for p in tree.people.values()
                  if p.died and (_y(p.died) or 0) >= args.since and in_belarus(tree, p.death_place)]
        people.sort(key=lambda p: p.name)
        print(f"Умерли в Беларуси с {args.since} г.: {len(people)}; ищем первых {min(len(people), args.max)}")
        people = people[:args.max]

    first = True
    for p in people:
        print(f"\n{p.name} ({p.id}) · род. {_y(p.born) or '?'} · ум. {_y(p.died) or '?'}")
        for q, given in queries_for(p, tree):
            if not first:
                time.sleep(PAUSE)
            first = False
            _, rows = search(q)
            show(q, rows, given, _y(p.born), _y(p.died), only_match=True)


if __name__ == "__main__":
    main()
