#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ищет вероятные ДУБЛИ персон в дереве (частая болячка MyHeritage:
один человек заведён дважды — латиницей и кириллицей, или с разным написанием).

Метод: транслитерация кириллицы в латиницу + нечёткое сравнение токенов имени
(допускает y↔i, o↔a и опечатки), при совместимом годе рождения и поле.
НЕ сливает автоматически — только отчёт для ручной проверки/слияния.
Пары, которые уже проверили и сказали «не одно лицо» (not_same в карточке), не показывает.

Выход: <папка поиска>/search/_возможные_дубли.md
Запуск: python3 tools/scripts/find_duplicates.py
"""
import json, os, re
from itertools import combinations

import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import paths as P_
ROOT = str(P_.ROOT)

TR = {'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'e','ж':'zh','з':'z',
 'и':'i','й':'i','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r','с':'s',
 'т':'t','у':'u','ф':'f','х':'h','ц':'c','ч':'ch','ш':'sh','щ':'sch','ъ':'','ы':'y',
 'ь':'','э':'e','ю':'yu','я':'ya'}
def translit(s): return ''.join(TR.get(c, c) for c in (s or '').lower())

def tokens(name):
    s = translit(name)
    s = re.sub(r'[^a-z ]', ' ', s)
    # снять женские окончания, чтобы Jasieniew≈Jasieniewa, Ясенев≈Ясенева сравнивались
    out = []
    for t in s.split():
        if len(t) < 2: continue
        t = re.sub(r'(a|ova|eva|aya)$', '', t) if len(t) > 4 else t
        out.append(t)
    return out

def lev(a, b):
    if abs(len(a)-len(b)) > 2: return 9
    prev = list(range(len(b)+1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j]+1, cur[j-1]+1, prev[j-1]+(ca != cb)))
        prev = cur
    return prev[-1]

def tok_match(a, b):
    if a == b: return True
    if len(a) >= 4 and len(b) >= 4:
        if a.startswith(b) or b.startswith(a): return True
        return lev(a, b) <= (2 if max(len(a), len(b)) >= 6 else 1)
    return lev(a, b) <= 1

def name_sim(t1, t2):
    """сколько токенов одного нашли совпадение в другом"""
    used = set(); m = 0
    for x in t1:
        for j, y in enumerate(t2):
            if j in used: continue
            if tok_match(x, y): used.add(j); m += 1; break
    return m

def year(p):
    b = (p.get("birth") or {}).get("date") or ""
    g = re.search(r"(1[6-9]\d\d|20\d\d)", b)
    return int(g.group(1)) if g else None

def ruled_out(tree, ia, ib):
    """Пару (номера MyHeritage) уже проверили: в карточке одного из двух not_same — не одно лицо."""
    cr = {str(p.fm.get("gedcom_id") or "").strip("@"): p.id for p in tree.people.values() if p.fm.get("gedcom_id")}
    a, b = cr.get(str(ia).strip("@")), cr.get(str(ib).strip("@"))
    return bool(a and b and tree.ruled_out(a, b, "same"))


def main():
    import cards  # здесь, а не наверху: тесту нужна только ruled_out
    tree = cards.load()
    P = json.load(open(str(P_.TREE_DATA/"persons.json"), encoding="utf-8"))
    rec = []
    for p in P:
        rec.append((p["id"], p.get("name", ""), tokens(p.get("name", "")),
                    p.get("sex"), year(p), (p.get("birth") or {}).get("place", "")))

    pairs = []
    for (a, b) in combinations(rec, 2):
        ia, na, ta, sa, ya, pa = a
        ib, nb, tb, sb, yb, pb = b
        if not ta or not tb: continue
        if sa and sb and sa != sb: continue          # разный пол — не дубль
        if ya and yb and ya != yb: continue           # оба года есть и разные — не дубль
        m = name_sim(ta, tb)
        need = min(len(ta), len(tb))
        if need >= 2 and m >= 2:                       # минимум 2 совпавших токена (имя+фамилия)
            cyr_a = bool(re.search(r'[а-я]', na.lower())); cyr_b = bool(re.search(r'[а-я]', nb.lower()))
            crosswrite = cyr_a != cyr_b
            same_year = bool(ya and yb and ya == yb)
            # дубль = одна запись о ОДНОМ человеке дважды: совпавший год ИЛИ разная графика.
            # Иначе одинаковое имя при разных/пустых годах в одной графике — обычно ТЁЗКИ.
            if same_year and crosswrite: conf = "вероятный дубль"
            elif same_year:             conf = "вероятный дубль"
            elif crosswrite:            conf = "возможный дубль (разная графика)"
            else:                        conf = "скорее тёзки (разные люди)"
            pairs.append((conf, crosswrite, ia, na, ya, pa, ib, nb, yb, pb))

    order = {"вероятный дубль":0,"возможный дубль (разная графика)":1,"скорее тёзки (разные люди)":2}
    pairs = [x for x in pairs if not ruled_out(tree, x[2], x[6])]
    pairs.sort(key=lambda x: (order[x[0]], not x[1]))

    with open(str(P_.SEARCH/"_возможные_дубли.md"),"w",encoding="utf-8") as f:
        f.write("# Возможные дубли персон в дереве (для ручной сверки/слияния)\n\n")
        f.write("> Найдено сравнением имён с транслитерацией (латиница↔кириллица) и нечётким совпадением "
                "при совместимом годе рождения и поле. **Не сливать вслепую** — проверьте каждую пару в MyHeritage.\n\n")
        f.write(f"Всего пар-кандидатов: **{len(pairs)}**\n\n")
        f.write("| Увер. | ↔графика | A: id / имя / год / место | B: id / имя / год / место |\n|---|---|---|---|\n")
        for conf, cw, ia, na, ya, pa, ib, nb, yb, pb in pairs:
            f.write(f"| {conf} | {'да' if cw else ''} | `{ia}` {na} / {ya or '—'} / {pa[:20]} "
                    f"| `{ib}` {nb} / {yb or '—'} / {pb[:20]} |\n")

    print(f"Пар-кандидатов: {len(pairs)}")
    from collections import Counter
    c = Counter(p[0] for p in pairs)
    for k in ("вероятный дубль","возможный дубль (разная графика)","скорее тёзки (разные люди)"):
        print(f"  {k}: {c.get(k,0)}")
    print(f"Отчёт: {P_.rel(P_.SEARCH / '_возможные_дубли.md')}")


if __name__ == "__main__":
    main()
