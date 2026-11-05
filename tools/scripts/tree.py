#!/usr/bin/env python3
"""Вопросы к дереву — одной командой, ответ до 20 строк.

Зачем. Чтобы узнать о человеке, сессия раньше делала пять `grep` и читала карточку целиком (десятки тысяч знаков).
Здесь — один вызов и короткий ответ: кто он, кем приходится другому, где жил, кто назван в источнике, чего не хватает.
Читает дерево тем же разбором, что сайт и проверки (пакет cards, ~0,5 с); своего индекса нет. Кэш — только у
`mentions` (поиск по всем .md проекта): на каждый файл — размер и время правки, пересчитываются только изменённые.

  tools/py tools/scripts/tree.py who "Иван Ясенев"          # годы, места, родня, источники, биография, документы
  tools/py tools/scripts/tree.py who ppl-001-aaa-001        # то же по номеру (cr_id) или I100001 (gedcom_id)
  tools/py tools/scripts/tree.py kin "Witold Jasieniew" "Прокоп Ясенев"   # кем второй приходится первому и через кого
  tools/py tools/scripts/tree.py find Лесик                 # все написания: Lesik, Лесік, Lesikowa…
  tools/py tools/scripts/tree.py find Иван Ясенев --for "Прокоп Jasieniew"   # кандидаты для него: без проверенных «нет»
  tools/py tools/scripts/tree.py place Вербичи              # кто там родился, умер, жил и когда; эпохи
  tools/py tools/scripts/tree.py src "Аудио 04"             # кого называет источник и сколько фактов
  tools/py tools/scripts/tree.py mentions "Иван Ясенев"     # в каких файлах проекта упомянут
  tools/py tools/scripts/tree.py gaps [--line Дубняки] [--p P1]   # кому чего не хватает; gaps "<имя>" — одному
  tools/py tools/scripts/tree.py targets --place Вербичи --years 1890-1915   # кого искать в книгах места и лет
                                                    # … --for "<имя>" — без тех, с кем у него проверено «нет»

Ответ обрезается на 20 строках (последняя — «… ещё N»); всё целиком — ключ --all.
Имя — как карточка, name, aliases, home_names; не нашлось точно — по написаниям, как в find.
--for "<имя>" — кандидаты для этого человека: кого проверили и сказали «нет» (not_same / not_kin в любой из двух
карточек), не предлагаем снова; «возможно, тот же / родня» (maybe_*) — помечены.
"""
import json
import os
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cards  # noqa: E402
import paths  # noqa: E402
from cards.notes import N, as_list, link_target, section  # noqa: E402
from cards.places import states_of  # noqa: E402

LIMIT = 20


# ─── написания: одна «основа» для Lesik / Лесик / Лесік / Lesikowa ───────────────────────────────────────

_CYR = dict(zip("абвгдезийклмнопрстуфхцчшщыэіїєґўѣ", "abvgdeziiklmnoprstufhccssieiieguu")) | {
    "ж": "z", "ё": "e", "ю": "iu", "я": "ia", "ъ": "", "ь": "", "ѣ": "e"}
_LAT = [("sch", "s"), ("szcz", "s"), ("sz", "s"), ("sh", "s"), ("cz", "c"), ("ch", "h"), ("zh", "z"), ("rz", "z"),
        ("kh", "h"), ("ts", "c"), ("tz", "c"), ("ck", "k"), ("x", "ks"), ("w", "v"), ("y", "i"), ("j", "i"), ("q", "k")]
# окончания, которыми написания одной фамилии расходятся: род, пол, польское -ski/-ska, -owa
_ENDS = ("ovskaia", "evskaia", "skaia", "ovskii", "evskii", "skii", "ovska", "evska", "ska", "ski", "sky", "ovna", "evna",
         "ova", "eva", "ina", "aia", "ii", "ia", "oi", "a", "e", "i", "o")


def _ascii(s):
    return unicodedata.normalize("NFKD", s.replace("ł", "l").replace("Ł", "L")).encode("ascii", "ignore").decode()


def keys(word):
    """Основы слова: «Lesik», «Лесик», «Лесік» → {"lesik"}. Латинское ch — и «х» (польск.), и «ч» (англ.),
    поэтому основ бывает две. Г и Х — одна буква (белорусское г — h). Двойные буквы — одной."""
    w = N(word).lower()
    if re.search("[а-яёіїєґўѣ]", w):
        variants = ["".join(_CYR.get(ch, ch) for ch in w)]
    else:
        a = _ascii(w)
        variants = [a.replace("ch", "\x01").replace("cz", "c")]
        variants = [variants[0].replace("\x01", "h"), variants[0].replace("\x01", "c")] if "\x01" in variants[0] \
            else variants
    out = set()
    for v in variants:
        for a, b in _LAT:
            v = v.replace(a, b)
        v = re.sub(r"[^a-z]", "", v).replace("g", "h")
        v = re.sub(r"(.)\1+", r"\1", v)
        out.add(v)
    return out


def stem_key(k):
    """Основа без окончания рода и пола: lesikova → lesik, dubniakova → dubniak… (не короче 4 букв)."""
    for e in _ENDS:
        if k.endswith(e) and len(k) - len(e) >= 4:
            return k[: -len(e)]
    return k


def word_match(q, w):
    """Слово w — написание слова q?"""
    qs, ws = {stem_key(k) for k in keys(q)}, {stem_key(k) for k in keys(w)}
    return bool(qs & ws) or any(len(a) >= 5 and len(b) >= 5 and (a.startswith(b) or b.startswith(a)) for a in qs for b in ws)


# ─── люди: имена, годы, поиск ──────────────────────────────────────────────────────────────────────────────────────

def _y(g):
    return f"{'~' if g.approx else ''}{g.first_year}" if g and g.first_year else ""


def years(p):
    """Коротко, для списков: «1902–~1986», «?–1942», «1937»."""
    b, d = _y(p.born), _y(p.died)
    return f"{b or '?'}–{d}" if d else b


def label(p):
    y = years(p)
    if not y or re.search(r"\(\d{4}\)$", p.stem):
        return p.stem
    return f"{p.stem} [{y}]" if p.stem.endswith(")") else f"{p.stem} ({y})"


def dkey(g):
    """Ключ сортировки по дате: неизвестная — в конец."""
    return (g.sort_key() or "9999") if g else "9999"


def names(p):
    """Все имена человека: карточка, name, aliases, home_names."""
    return list(dict.fromkeys(N(str(x)) for x in [p.stem, p.name, *as_list(p.fm.get("aliases")),
                                                    *as_list(p.fm.get("home_names"))] if str(x).strip()))


def tokens(s):
    return [t for t in re.split(r"[\s,()«»\"'.\-–—/]+", s) if t and not t.isdigit()]


def find_people(tree, q):
    """→ (точные совпадения, похожие). Номер, имя карточки, name, aliases, home_names; иначе — каждое слово запроса
    должно совпасть с каким-нибудь словом имени по написанию."""
    q = N(q.strip())
    if q in tree.people:
        return [tree.people[q]], []
    gid = q.strip("@")
    exact = [p for p in tree.people.values() if str(p.fm.get("gedcom_id") or "").strip("@") == gid] if \
        re.fullmatch(r"I\d+", gid) else []
    if exact:
        return exact, []
    low = q.lower()
    for forms in (lambda p: [p.stem], names):   # имя карточки важнее name и aliases: «Иван Jasieniew» — карточка, не тёзка
        exact = [p for p in tree.people.values() if any(n.lower() == low for n in forms(p))]
        if exact:
            return exact, []
    qt = tokens(q)
    similar = [p for p in tree.people.values()
               if qt and all(any(word_match(a, b) for n in names(p) for b in tokens(n)) for a in qt)]
    return [], similar


def one(tree, q):
    """Один человек по запросу — или сообщение, почему не один."""
    exact, similar = find_people(tree, q)
    if len(exact) == 1:
        return exact[0], None
    if len(similar) == 1 and not exact:
        return similar[0], None
    many = exact or similar
    if not many:
        return None, [f"«{q}» — нет такого человека в дереве (поиск по написаниям: tree.py find {q.split()[-1]})"]
    return None, [f"«{q}» — {len(many)} подходят, уточните (имя карточки или cr_id):"] + \
        [f"  {label(p)} · {p.id}" for p in sorted(many, key=lambda p: p.stem)]


def pnames(tree, ids):
    return ", ".join(label(tree.people[i]) for i in ids) or "—"


def place_name(tree, pid):
    return tree.places[pid].stem if pid in tree.places else ""


# ─── who ───────────────────────────────────────────────────────────────────────────────────────────────────────────

PROV_RU = {"family": "семья", "found": "найдено", "other_tree": "чужое дерево", "inference": "вывод проекта"}


def biography_of(tree, p):
    return next((path for path, owner in tree.biographies.items() if owner == p.id), None)


def documents_of(p, root=paths.ROOT):
    d = root / paths.rel(paths.DOCUMENTS) / p.stem
    return sorted(f.stem for f in d.glob("*.md")) if d.is_dir() else []


KIN_RU = {"parent": "отец / мать", "child": "сын / дочь", "sibling": "брат / сестра", "pibling": "дядя / тётя",
          "nibling": "племянник / племянница", "cousin": "двоюродный брат / сестра", "grandparent": "дед / бабушка",
          "grandchild": "внук / внучка", "spouse": "супруг", "kin": "родня"}


def who(tree, q, root=paths.ROOT):
    p, err = one(tree, q)
    if err:
        return err
    f = p.fm
    life = f"{p.born.ru() if p.born else '?'}–{p.died.ru()}" if p.died else (p.born.ru() if p.born else "годы неизвестны")
    head = f"{p.stem} — {'муж.' if p.sex == 'M' else 'жен.'}, {life} · {p.id}"
    if f.get("gedcom_id"):
        head += f" · {str(f['gedcom_id']).strip('@')}"
    if f.get("research_priority"):
        head += f" · {f['research_priority']}"
    out = [head]
    br = ", ".join(as_list(f.get("lineage")))
    bm = ", ".join(as_list(f.get("lineage_by_marriage")))
    if br or bm:
        out.append(f"ветка: {br or '—'}" + (f"; по браку: {bm}" if bm else ""))
    other = [n for n in names(p) if n != p.stem]
    if other:
        out.append("другие имена: " + ", ".join(other))
    born = f"род. {p.born.ru() if p.born else '?'}" + (f", {place_name(tree, p.birth_place)}" if p.birth_place else "")
    died = (f"; ум. {p.died.ru() if p.died else '?'}" + (f", {place_name(tree, p.death_place)}" if p.death_place else "")) \
        if p.died or p.death_place else ""
    out.append(born + died)
    if f.get("occupation"):
        out.append(f"занятие: {f['occupation']}")
    out.append(f"родители: {pnames(tree, p.father + p.mother)}")
    if p.spouses:
        out.append(f"супруги: {pnames(tree, p.spouses)}")
    if p.children:
        out.append(f"дети ({len(p.children)}): {pnames(tree, p.children)}")
    prov = Counter(PROV_RU.get(x.provenance, x.provenance) for x in p.facts)
    conf = Counter(x.confidence for x in p.facts)
    out.append(f"факты: {len(p.facts)}" + (f" ({', '.join(f'{k} {v}' for k, v in prov.most_common())}; "
                                            f"высокая {conf['high']}, обычная {conf['normal']}, низкая {conf['low']})"
                                            if p.facts else ""))
    srcs = list(dict.fromkeys(p.sources + [r.source for x in p.facts for r in x.refs]))
    if srcs:
        out.append(f"источники ({len(srcs)}): " + "; ".join(tree.sources[s].stem for s in srcs[:6])
                   + (f"; … ещё {len(srcs) - 6}" if len(srcs) > 6 else ""))
    bio = biography_of(tree, p)
    out.append(f"биография: {bio}" if bio else "биографии нет")
    docs = documents_of(p, root)
    if docs:
        out.append(f"документы ({len(docs)}): " + "; ".join(docs))
    for x in p.possible:
        word = "тот же человек" if x.kind == "same" else KIN_RU.get(x.relation, "родня")
        out.append(f"возможно, {word}: {label(tree.people[x.person])}" + (" (записано у него)" if x.back else ""))
    no = [f"{'не тот же' if k == 'same' else 'не родня'}: {tree.people[i].stem}" for k, i in sorted(p.ruled_out)]
    if no:
        out.append("проверено — нет: " + "; ".join(no))
    if f.get("surname_inferred"):
        out.append("фамилия выведена (surname_inferred) — документа нет")
    oq = section(p.body, "Открытые вопросы")[0]
    n_open = len([x for x in oq.splitlines() if x.startswith("- ") and "✅" not in x])
    if n_open:
        out.append(f"открытых вопросов в карточке: {n_open}")
    log = searched_for(p.id)
    if log:
        out.append(f"уже искали ({len(log)}): " + "; ".join(f"{r['дата']} {r['источник']} — {r['итог'][:60]}"
                                                       for r in log[-3:])
                   + (f"; … ещё {len(log) - 3}" if len(log) > 3 else "") + f" (searched.py who {p.id})")
    return out


def searched_for(cr_id):
    """Заходы журнала поиска, где этот человек назван по cr_id (имена бывают у тёзок — по ним не считаем)."""
    try:
        import searched
    except ImportError:
        return []
    return [r for r in searched.read_log() if cr_id in r["кого искали"]]


# ─── kin: кем приходится ───────────────────────────────────────────────────────────────────────────────────────────

def ancestors(tree, pid):
    """{предок: (шагов вверх, через кого шли вниз)}; сам человек — 0 шагов."""
    out, queue = {pid: (0, None)}, [pid]
    while queue:
        c = queue.pop(0)
        for par in tree.people[c].father + tree.people[c].mother:
            if par not in out:
                out[par] = (out[c][0] + 1, c)
                queue.append(par)
    return out


def up_path(anc, top):
    path, c = [], top
    while c:
        path.append(c)
        c = anc[c][1]
    return path[::-1]


def blood(tree, a, x):
    """Кровное родство через ближайшего общего предка → (вверх от a, вниз к x, предок, цепочка) или None."""
    aa, ax = ancestors(tree, a), ancestors(tree, x)
    common = [(aa[c][0] + ax[c][0], c) for c in aa if c in ax]
    if not common:
        return None
    _, lca = min(common)
    path = up_path(aa, lca) + up_path(ax, lca)[::-1][1:]
    return aa[lca][0], ax[lca][0], lca, path


_ORD = {2: "двоюродн", 3: "троюродн", 4: "четвероюродн", 5: "пятиюродн", 6: "шестиюродн"}


def _adj(n, f):
    stem = _ORD.get(n, f"{n}-юродн")
    return stem + ("ая" if f else "ый")


def blood_term(a, b, f, half=None):
    """a шагов вверх до общего предка, b вниз; f — женщина ли тот, о ком говорим."""
    pra = lambda k: "пра" * max(0, k)
    if a == 0 and b == 0:
        return "сам" if not f else "сама"
    if b == 0:
        return {1: "мать" if f else "отец"}.get(a) or pra(a - 2) + ("бабушка" if f else "дед")
    if a == 0:
        return {1: "дочь" if f else "сын"}.get(b) or pra(b - 2) + ("внучка" if f else "внук")
    if a == 1 and b == 1:
        w = "сестра" if f else "брат"
        return (("единокровн" if half == "M" else "единоутробн") + ("ая " if f else "ый ") + w) if half else w
    if b == 1:
        return "тётя" if f and a == 2 else "дядя" if a == 2 else \
            pra(a - 3) + ("двоюродная бабушка" if f else "двоюродный дед")
    if a == 1:
        return ("племянница" if f else "племянник") if b == 2 else \
            pra(b - 3) + ("внучатая племянница" if f else "внучатый племянник")
    if a == b:
        return _adj(a, f) + (" сестра" if f else " брат")
    if a == b + 1:
        return _adj(b, f) + (" тётя" if f else " дядя")
    if b == a + 1:
        return _adj(a, f) + (" племянница" if f else " племянник")
    return None


RU_GEN = {"отец": "отца", "мать": "матери", "дед": "деда", "бабушка": "бабушки", "сын": "сына", "дочь": "дочери",
          "внук": "внука", "внучка": "внучки", "брат": "брата", "сестра": "сестры", "дядя": "дяди", "тётя": "тёти",
          "племянник": "племянника", "племянница": "племянницы", "муж": "мужа", "жена": "жены"}


def gen(term):
    """Родительный падеж: «двоюродный брат» → «двоюродного брата»."""
    out = []
    for w in term.split():
        pra = re.match(r"(?:пра)*", w)[0]
        core = w[len(pra):]
        if core in RU_GEN:
            out.append(pra + RU_GEN[core])
        elif re.search(r"[жшчщ]ая$", w):
            out.append(w[:-2] + "ей")
        elif w.endswith("ая"):
            out.append(w[:-2] + "ой")
        elif re.search(r"[ыо]й$", w):
            out.append(w[:-2] + "ого")
        elif w.endswith("ий"):
            out.append(w[:-2] + "его")
        else:
            out.append(w)
    return " ".join(out)


def half_of(tree, a, x):
    pa, px = tree.people[a], tree.people[x]
    common = [i for i in pa.father + pa.mother if i in px.father + px.mother]
    if len(common) == 1 and len(pa.father + pa.mother) == 2 and len(px.father + px.mother) == 2:
        return tree.people[common[0]].sex
    return None


def relation(tree, a, x):
    """Кем x приходится a → (слова, цепочка cr_id)."""
    P, fx = tree.people, tree.people[x].sex == "F"
    r = blood(tree, a, x)
    if r:
        t = blood_term(r[0], r[1], fx, half_of(tree, a, x) if r[0] == r[1] == 1 else None)
        return (t or f"кровный родственник: {r[0]} пок. вверх до общего предка, {r[1]} вниз"), r[3]
    if x in P[a].spouses:
        return ("жена" if fx else "муж"), [a, x]
    for s in P[a].spouses:   # родня супруга
        r = blood(tree, s, x)
        if r:
            wife = P[s].sex == "F"
            t = blood_term(r[0], r[1], fx)
            special = {("мать", True): "тёща", ("отец", True): "тесть", ("мать", False): "свекровь",
                       ("отец", False): "свёкор", ("брат", True): "шурин", ("сестра", True): "свояченица",
                       ("брат", False): "деверь", ("сестра", False): "золовка", ("сын", True): "пасынок",
                       ("дочь", True): "падчерица", ("сын", False): "пасынок", ("дочь", False): "падчерица"}
            t = special.get((t, wife)) or (f"{t} {'жены' if wife else 'мужа'}" if t else None)
            if t:
                return t, [a] + r[3]
    for s in P[x].spouses:   # супруг кровного родственника
        r = blood(tree, a, s)
        if r:
            t = blood_term(r[0], r[1], P[s].sex == "F")
            special = {"сын": "невестка", "брат": "невестка", "дочь": "зять", "сестра": "зять", "отец": "мачеха",
                       "мать": "отчим"}
            w = special.get(t) if (t in ("сын", "брат", "отец") and fx) or (t in ("дочь", "сестра", "мать") and not fx) \
                else None
            if t:
                return (w or f"{'жена' if fx else 'муж'} {gen(t)}"), r[3] + [x]
    prev, queue = {a: None}, [a]   # дальше — кратчайшая цепочка через браки
    while queue and x not in prev:
        c = queue.pop(0)
        for v in P[c].father + P[c].mother + P[c].children + P[c].spouses:
            if v not in prev:
                prev[v] = c
                queue.append(v)
    if x not in prev:
        return None, []
    path, c = [], x
    while c:
        path.append(c)
        c = prev[c]
    return "свойственник (через браки)", path[::-1]


def step_word(tree, a, b):
    P = tree.people
    f = P[b].sex == "F"
    if b in P[a].father + P[a].mother:
        return "мать" if f else "отец"
    if b in P[a].children:
        return "дочь" if f else "сын"
    if b in P[a].spouses:
        return "жена" if f else "муж"
    return "?"


def kin(tree, qa, qx):
    a, err = one(tree, qa)
    if err:
        return err
    x, err = one(tree, qx)
    if err:
        return err
    term, path = relation(tree, a.id, x.id)
    if not term:
        return [f"{label(x)} и {label(a)} — связи в дереве нет (ни кровной, ни через браки)"]
    out = [f"{label(x)} — {term} для {label(a)}"]
    if len(path) > 2:
        chain = [label(tree.people[path[0]])] + [f"{step_word(tree, path[i - 1], path[i])} {label(tree.people[path[i]])}"
                                                 for i in range(1, len(path))]
        out.append("цепочка: " + " → ".join(chain))
    r = blood(tree, a.id, x.id)
    if r and r[0] and r[1]:
        out.append(f"общий предок: {label(tree.people[r[2]])} ({r[0]} пок. вверх, {r[1]} вниз)")
    return out


# ─── find ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def for_whom(tree, q):
    """--for "<имя>" → (человек, None) или (None, сообщение)."""
    if not q:
        return None, None
    return one(tree, q)


def candidate_mark(tree, me, p):
    """Пометка кандидата для человека me: None — не предлагать (проверено «нет»); "" — обычный; иначе — «возможно, …»."""
    if not me:
        return ""
    if p.id == me.id or tree.ruled_out(me.id, p.id):
        return None
    may = next((x for x in me.possible if x.person == p.id), None)
    return "" if not may else " · возможно, " + ("тот же" if may.kind == "same" else KIN_RU.get(may.relation, "родня"))


def find(tree, q, me=None):
    qt = tokens(q)
    if not qt:
        return ["пустой запрос"]
    hits = []
    for p in tree.people.values():
        if candidate_mark(tree, me, p) is None:
            continue
        forms = [w for n in names(p) for w in tokens(n) if all(any(word_match(a, w2) for w2 in tokens(n)) for a in qt)
                 and any(word_match(a, w) for a in qt)]
        if forms:
            hits.append((p, forms))
    if not hits:
        return [f"«{q}» — ни одного написания в дереве"]
    by_form = Counter(w for _, fs in hits for w in dict.fromkeys(fs))
    out = [f"«{q}»: людей {len(hits)}; написания: " + ", ".join(f"{w} ({n})" for w, n in by_form.most_common())]
    if me and me.ruled_out:
        out[0] += f" · для {me.stem} не показаны проверенные «нет»: {len(me.ruled_out)}"
    prio = lambda p: (str(p.fm.get("research_priority") or "P9"), dkey(p.born), p.stem)
    for p, _ in sorted(hits, key=lambda h: prio(h[0])):
        out.append(f"  {label(p)} · {p.id}" + (f" · {p.fm['research_priority']}" if p.fm.get("research_priority") else "")
                   + candidate_mark(tree, me, p))
    return out


# ─── place ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def find_place(tree, q):
    q = N(q.strip())
    low = q.lower()
    exact = [pl for pl in tree.places.values() if q == pl.id or any(n.lower() == low for n in [pl.stem, pl.name, *pl.aliases])]
    if exact:
        return exact
    qt = tokens(q)
    return [pl for pl in tree.places.values()
            if qt and all(any(word_match(a, b) for n in [pl.stem, pl.name, *pl.aliases] for b in tokens(n)) for a in qt)]


def below(tree, pid):
    """Само место и все, что внутри него (кладбище в городе, деревня в районе)."""
    out, changed = {pid}, True
    while changed:
        changed = False
        for pl in tree.places.values():
            if pl.parent in out and pl.id not in out:
                out.add(pl.id)
                changed = True
    return out


LIFE_ROW = re.compile(r"^\|(.+)\|\s*$", re.M)


def lifeline_places(tree, root=paths.ROOT):
    """Строки линий жизни биографий: (cr_id хозяина, когда, что, [места из колонки «Где»])."""
    out = []
    for rel, owner in tree.biographies.items():
        if not owner:
            continue
        text = (root / rel).read_text(encoding="utf-8")
        for m in LIFE_ROW.finditer(text):
            cells = [c.strip() for c in m[1].replace("\\|", "\x00").split("|")]
            if len(cells) < 3 or set(cells[0]) <= set("-: "):
                continue
            where = [link_target(x) for x in re.findall(r"\[\[[^\]]+\]\]", cells[-1])]
            if where:
                out.append((owner, cells[0].replace("\x00", "|"), cells[1].replace("\x00", "|"), where))
    return out


def place(tree, q, root=paths.ROOT):
    found = find_place(tree, q)
    if not found:
        return [f"«{q}» — нет такого места в дереве"]
    if len(found) > 1:
        return [f"«{q}» — {len(found)} мест, уточните:"] + [f"  {pl.stem} ({pl.type}) · {pl.id}" for pl in found]
    pl = found[0]
    inside = below(tree, pl.id)
    names_in = {tree.places[i].stem for i in inside} | {a for i in inside for a in tree.places[i].aliases}
    chain, c = [], tree.places.get(pl.parent)
    while c and c.stem not in chain:
        chain.append(c.stem)
        c = tree.places.get(c.parent)
    out = [f"{pl.stem} ({pl.type or 'место'})" + (f" · в: {' → '.join(chain)}" if chain else "")
           + (f" · другие имена: {', '.join(pl.aliases)}" if pl.aliases else "")]
    st = states_of(pl, tree.places)
    if st:
        out.append("эпохи: " + "; ".join(f"{s.date.ru()} — {s.label}" for s in st))
    if len(inside) > 1:
        out.append(f"внутри: {', '.join(sorted(tree.places[i].stem for i in inside if i != pl.id))}")
    rows = []
    for p in tree.people.values():
        if p.birth_place in inside:
            rows.append((dkey(p.born), f"род. {p.born.ru() if p.born else '?'}: {label(p)}"))
        if p.death_place in inside:
            rows.append((dkey(p.died), f"ум. {p.died.ru() if p.died else '?'}: {label(p)}"))
    seen = set()
    for owner, when, what, where in lifeline_places(tree, root):
        if set(where) & names_in and (owner, when) not in seen:
            seen.add((owner, when))
            what = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", what).replace("**", "").lstrip("⭐ ")
            rows.append((_when_key(when), f"{when}: {tree.people[owner].stem} — {what[:90]}"))
    out += [r for _, r in sorted(rows, key=lambda r: r[0])] or ["людей с этим местом в карточках и линиях жизни нет"]
    return out


def _when_key(when):
    m = re.search(r"\d{4}", when)
    return m[0] if m else "9999"


# ─── src ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def src(tree, q):
    q = N(q.strip())
    low = q.lower()
    found = [s for s in tree.sources.values() if q == s.id or low in (s.stem.lower(), s.title.lower())]
    found = found or [s for s in tree.sources.values() if low in s.stem.lower() or low in s.title.lower()]
    if not found:
        return [f"«{q}» — нет такой карточки источника"]
    if len(found) > 1:
        return [f"«{q}» — {len(found)} источников, уточните:"] + [f"  {s.stem}" for s in found]
    s = found[0]
    out = [f"{s.stem} — {PROV_RU.get(s.provenance, s.provenance)}, {s.type}" + (f" · {s.author}" if s.author else "")
           + (f" · {s.repository}" if s.repository else "")]
    rows = []
    for p in tree.people.values():
        fs = [x for x in p.facts if any(r.source == s.id for r in x.refs)]
        if fs or s.id in p.sources:
            locs = list(dict.fromkeys(r.locator for x in fs for r in x.refs if r.source == s.id and r.locator))
            rows.append((-len(fs), p.stem, f"  {label(p)}: фактов {len(fs)}" + (f" · {'; '.join(locs[:3])}" if locs else "")
                         + (" …" if len(locs) > 3 else "")))
    out.append(f"называет людей: {len(rows)}, фактов: {sum(-r[0] for r in rows)}")
    return out + [r[2] for r in sorted(rows)]


# ─── mentions: где упомянут во всём проекте ────────────────────────────────────────────────────────────────────────

SKIP_DIRS = (".git", "node_modules", "tools", "_dossiers", "_generated", "_chunks", "tree_data", "social_export", ".venv",
             ".obsidian", ".trash", paths.rel(paths.SITE), paths.rel(paths.SITE_EXPORT))
CACHE = paths.CACHE / "mentions.json"


def md_files(root):
    for d, ds, fs in os.walk(root):
        rel = os.path.relpath(d, root)
        if rel != "." and any(rel == s or rel.startswith(s + "/") or os.path.basename(d) == s for s in SKIP_DIRS):
            ds[:] = []
            continue
        for fn in fs:
            if fn.endswith(".md"):
                yield Path(d) / fn


def name_pattern(p):
    """Как человека ищем в текстах: ссылка [[Карточка…]], номер @I…@, и имена из двух слов и больше с падежами
    («деда Прокопа»). Одно имя без фамилии — только домашнее (home_names): иначе шум."""
    forms = {n for n in names(p) if len(n.split()) >= 2} | set(N(str(x)) for x in as_list(p.fm.get("home_names")))
    forms = {re.sub(r"\s*\(.*?\)\s*", " ", f).strip() for f in forms} - {""}
    parts = [r"\[\[" + re.escape(p.stem) + r"[\]|#]"]
    if p.fm.get("gedcom_id"):
        parts.append(re.escape("@" + str(p.fm["gedcom_id"]).strip("@") + "@"))
    for n in sorted(forms, key=len, reverse=True):
        parts.append(r"\s+".join(re.escape(w[:max(3, len(w) - 2)]) + r"[а-яёa-z]*" for w in n.split()))
    return r"(?<![А-Яа-яЁёA-Za-z])(?:" + "|".join(parts) + ")"


def mentions(tree, q, root=paths.ROOT, cache=CACHE):
    p, err = one(tree, q)
    if err:
        return err
    rx = re.compile(name_pattern(p), re.I)
    try:
        old = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
    except (ValueError, OSError):
        old = {}
    sig = rx.pattern
    store = old.get(p.id) if old.get(p.id, {}).get("sig") == sig else None
    files = {}
    for f in md_files(root):
        st = f.stat()
        rel = N(f.relative_to(root).as_posix())
        prev = (store or {}).get("files", {}).get(rel)
        if prev and prev[0] == st.st_size and prev[1] == int(st.st_mtime):
            files[rel] = prev
            continue
        n = len(rx.findall(N(f.read_text(encoding="utf-8", errors="replace"))))
        files[rel] = [st.st_size, int(st.st_mtime), n]
    old[p.id] = {"sig": sig, "files": files}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    hits = sorted(((v[2], k) for k, v in files.items() if v[2]), key=lambda x: (-x[0], x[1]))
    hits = [h for h in hits if not ("/" + h[1]).endswith(f"/people/{p.stem}.md")]   # своя карточка не в счёт
    groups = Counter(h[1].split("/")[0] for h in hits)
    out = [f"{label(p)} — упомянут в {len(hits)} файлах (кроме своей карточки): "
           + ", ".join(f"{g} {n}" for g, n in groups.most_common())]
    return out + [f"  {n:>3} × {rel}" for n, rel in hits]


# ─── gaps: кому чего не хватает ────────────────────────────────────────────────────────────────────────────────────

def prio(p):
    return str(p.fm.get("research_priority") or "P9")


GAPS = ["год рождения", "место рождения", "родители", "факты с источником", "факты не из чужого дерева", "источники",
        "биография", "год рождения подтверждён фактом"]


def lacks(tree, p):
    """Чего не хватает человеку — по порядку важности."""
    out = []
    if not p.born:
        out.append("год рождения")
    if not p.birth_place:
        out.append("место рождения")
    if not (p.father or p.mother):
        out.append("родители")
    if not p.facts:
        out.append("факты с источником")
    elif all(f.provenance == "other_tree" for f in p.facts):
        out.append("факты не из чужого дерева")
    if not p.sources and not p.facts:
        out.append("источники")
    if prio(p) in ("P1", "P2") and not biography_of(tree, p):
        out.append("биография")
    born_fact = any(f.date and p.born and f.date.first_year == p.born.first_year for f in p.facts)
    if p.born and not born_fact:
        out.append("год рождения подтверждён фактом")
    return out


def gaps(tree, q=None, line=None, p_level=None):
    if q:
        p, err = one(tree, q)
        if err:
            return err
        ls = lacks(tree, p)
        return [f"{label(p)} — не хватает: {', '.join(ls)}" if ls else f"{label(p)} — всё основное есть"]
    people = [p for p in tree.people.values()
              if (not line or line in as_list(p.fm.get("lineage")) + as_list(p.fm.get("lineage_by_marriage")))
              and (not p_level or prio(p) == p_level)]
    by = {}
    for p in people:
        for g in lacks(tree, p):
            by.setdefault(g, []).append(p)
    out = [f"людей: {len(people)}" + (f" · ветка {line}" if line else "") + (f" · {p_level}" if p_level else "")]
    for g, ps in sorted(by.items(), key=lambda kv: GAPS.index(kv[0])):
        ps.sort(key=lambda p: (prio(p), p.stem))
        top = [p for p in ps if prio(p) != "P9"][:5]
        out.append(f"нет «{g}»: {len(ps)}" + (f" — сначала: {', '.join(p.stem + ' ' + prio(p) for p in top)}" if top else ""))
    return out


# ─── targets: кого искать в архиве места и лет ─────────────────────────────────────────────────────────────────────

def span(p):
    """(с какого, по какой год) жил — по born/died; одно неизвестно — ±80 лет."""
    b = p.born.first_year if p.born else None
    d = p.died.last_year if p.died else None
    if b is None and d is None:
        return None
    return (b if b is not None else d - 80), (d if d is not None else b + 80)


def targets(tree, place_q, yrs, root=paths.ROOT, me=None):
    found = find_place(tree, place_q)
    if len(found) != 1:
        return place(tree, place_q, root) if found else [f"«{place_q}» — нет такого места в дереве"]
    pl = found[0]
    m = re.fullmatch(r"(\d{4})(?:\s*[-–]\s*(\d{4}))?", yrs.strip())
    if not m:
        return [f"--years {yrs} — нужно «1890-1915» или «1900»"]
    y0, y1 = int(m[1]), int(m[2] or m[1])
    inside = below(tree, pl.id)
    names_in = {tree.places[i].stem for i in inside} | {a for i in inside for a in tree.places[i].aliases}
    linked = {}
    for p in tree.people.values():
        why = []
        if p.birth_place in inside:
            why.append("род. здесь")
        if p.death_place in inside:
            why.append("ум. здесь")
        if any(any(n in x.text for n in names_in) for x in p.facts):
            why.append("в фактах")
        if why:
            linked[p.id] = why
    for owner, when, _, where in lifeline_places(tree, root):
        if set(where) & names_in:
            k = int(_when_key(when))
            if k == 9999 or y0 - 5 <= k <= y1 + 5:
                linked.setdefault(owner, []).append("линия жизни")
    rows = []
    for pid, why in linked.items():
        p = tree.people[pid]
        mark = candidate_mark(tree, me, p)
        if mark is None:
            continue
        s = span(p)
        if s and (s[1] < y0 or s[0] > y1):
            continue
        what = []
        if p.born and y0 <= p.born.first_year <= y1:
            what.append(f"метрика рождения {p.born.ru()}")
        if p.died and y0 <= p.died.first_year <= y1:
            what.append(f"смерть {p.died.ru()}")
        if not what:
            what.append("годы неизвестны — проверить" if not s else "исповедные / перепись")
        rows.append(((prio(p), dkey(p.born)),
                     f"  {label(p)} [{prio(p) if prio(p) != 'P9' else '—'}]: {'; '.join(what)} · {', '.join(dict.fromkeys(why))}"
                     + mark))
    out = [f"{pl.stem}, {y0}–{y1}: кандидатов {len(rows)} (место и всё внутри него: {len(inside)})"]
    return out + [r for _, r in sorted(rows, key=lambda r: r[0])]


# ─── запуск ────────────────────────────────────────────────────────────────────────────────────────────────────────

def clip(lines, full=False):
    if full or len(lines) <= LIMIT:
        return lines
    return lines[: LIMIT - 1] + [f"… ещё {len(lines) - LIMIT + 1} (всё — --all)"]


def opt(args, name):
    if name in args:
        i = args.index(name)
        v = args[i + 1] if i + 1 < len(args) else None
        del args[i:i + 2]
        return v
    return None


def run(argv, tree=None, root=paths.ROOT):
    args = list(argv)
    full = "--all" in args
    args = [a for a in args if a != "--all"]
    if not args or args[0] in ("-h", "--help", "help"):
        return __doc__.strip().splitlines()
    cmd, args = args[0], args[1:]
    tree = tree or cards.load()
    if cmd == "who" and len(args) == 1:
        out = who(tree, args[0], root)
    elif cmd == "kin" and len(args) == 2:
        out = kin(tree, *args)
    elif cmd == "find" and args:
        me, err = for_whom(tree, opt(args, "--for"))
        out = err or find(tree, " ".join(args), me)
    elif cmd == "place" and args:
        out = place(tree, " ".join(args), root)
    elif cmd == "src" and args:
        out = src(tree, " ".join(args))
    elif cmd == "mentions" and len(args) == 1:
        out = mentions(tree, args[0], root)
    elif cmd == "gaps":
        line, p_level = opt(args, "--line"), opt(args, "--p")
        out = gaps(tree, args[0] if args else None, line, p_level)
    elif cmd == "targets":
        pq, yrs = opt(args, "--place"), opt(args, "--years")
        me, err = for_whom(tree, opt(args, "--for"))
        out = err or (targets(tree, pq, yrs, root, me) if pq and yrs
                      else ["targets --place <место> --years 1890-1915 [--for <имя>]"])
    else:
        out = [f"не понял: {' '.join(argv)} — tree.py --help"]
    return clip(out, full)


if __name__ == "__main__":
    print("\n".join(run(sys.argv[1:])))
