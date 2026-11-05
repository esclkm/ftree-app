#!/usr/bin/env python3
"""Противоречия в фактах: у одного человека разные источники говорят разное — или дата не сходится со здравым смыслом.

Зачем. Факты в карточки приходят из разных мест: метрики, рассказы семьи, чужие деревья (MyHeritage, сайт своего дерева на MyHeritage,
Familio). Чужое дерево часто ошибается — год из возраста, место жизни вместо места рождения, ребёнок «родился» у
шестидесятилетней матери. Глазами по 3200 фактам такое не найти. Скрипт сравнивает сам и выводит список: кто, что
расходится, какие строки карточки, откуда каждая (семья / найдено / чужое дерево / вывод проекта).

Что сравнивает:
  1. Источник против источника — у одного человека: дата и место рождения, смерти, брака (с тем же супругом).
     Свойства карточки (born, died, birth_place, death_place) — тоже сторона: это то, во что карточка сейчас верит.
     «ок.» — ±2 года, «расч.» — ±1, «оцен.» — ±3; крещение — до 2 месяцев после рождения, похороны — до 2 недель
     после смерти; деревня и её страна — не расхождение. Два дня до 1919 года с разницей 11–13 дней — не ошибка,
     а, скорее всего, старый и новый стиль (навык dates): такое идёт отдельной пометкой.
  2. Здравый смысл (по свойствам карточек и связям): умер раньше, чем родился; прожил больше 105 лет; мать моложе 14
     или старше 52 при рождении ребёнка, отец моложе 15 или старше 75; ребёнок родился после смерти матери (или
     больше чем через год после смерти отца). Рядом — на чём держится каждая дата: если только на чужом дереве,
     это видно сразу.
Документ против чужого дерева, рассказа или вывода — не спор: в отчёте пометка «документ сильнее — исправить
сразу», и такую строку правим, а не записываем в «Расхождения».
Противоречие, уже описанное в «### Расхождения» карточки (оба значения там названы), помечено «записано» и по
умолчанию не показывается (--all — показать).

  tools/py tools/scripts/fact_conflicts.py                        # всё новое, сначала самое грубое
  tools/py tools/scripts/fact_conflicts.py --other-tree           # только где одна из сторон — чужое дерево
  tools/py tools/scripts/fact_conflicts.py --person "Ясенев"      # часть имени или cr_id
  tools/py tools/scripts/fact_conflicts.py --min-years 2          # без расхождений «на год»
  tools/py tools/scripts/fact_conflicts.py --all --md /tmp/x.md   # и записанные; отчёт в файл
Выход: 0 — противоречий нет, 1 — есть (для ci не подключён: это список для разбора, а не ошибка).
"""
import argparse
import datetime
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cards  # noqa: E402
import dates  # noqa: E402
from cards.notes import link_target, section  # noqa: E402

PROV_RU = {"family": "семья", "found": "найдено", "other_tree": "чужое дерево", "inference": "вывод проекта",
           "card": "свойство карточки"}
KIND_RU = {"birth": "рождение", "death": "смерть", "marriage": "брак"}
WIDEN = {"ABT": 2, "CAL": 1, "EST": 3}  # лет в обе стороны
FAR = 10 ** 6

# Подпись факта (без даты) → вид события; «(кандидат)» и «место …» — отдельно
END = r"\s*(?:$|[(;,:])"   # «рождение», «рождение (расчёт)», но не «рождение сына»
LABEL = [(re.compile(rf"^(рождение|год рождения|полное имя и рождение|дата рождения){END}"), "birth", ""),
         (re.compile(rf"^(крещение|крещён|крещена){END}"), "birth", "bapt"),
         (re.compile(rf"^место рождения{END}"), "birth", "place"),
         (re.compile(rf"^(смерть|дата смерти|год смерти|гибель){END}"), "death", ""),
         (re.compile(rf"^(похоронен|похоронена|похороны|погребение){END}"), "death", "burial"),
         (re.compile(rf"^место смерти{END}"), "death", "place"),
         (re.compile(rf"^(брак|свадьба|венчание){END}"), "marriage", "")]
# Подписи нет (только дата) — смотрим первое слово текста: глагол о самом человеке («родился …»), а не «смерть жены»
KIN = r"(?!\s+(сын|дочь|дочка|ребёнок|дети|внук|внучка|отец|мать|муж|жена|брат|сестра|дед|бабушка|тесть|свёкор))"
TEXT = [(re.compile(rf"^(родился|родилась)\b{KIN}"), "birth", ""),
        (re.compile(r"^(крещён|крещена)\b"), "birth", "bapt"),
        (re.compile(rf"^(умер|умерла|скончался|скончалась|погиб|погибла)\b{KIN}"), "death", ""),
        (re.compile(r"^(похоронен|похоронена)\b"), "death", "burial"),
        (re.compile(r"^(венчались|женился|вышла замуж)\b"), "marriage", "")]
D = r"(?:\d{1,2}\.\d{1,2}\.)?(?:1[6-9]\d\d|20[0-2]\d)(?!\d)"
BET_TEXT = re.compile(rf"между ({D}) и ({D})")
ABT_TEXT = re.compile(rf"(?:около|ок\.|→)\s*({D})")
DAY_IN_TEXT = re.compile(rf"(?<![\d.])({D})")


@dataclass
class Claim:
    """Одно утверждение: «рождение — 1905, Вербичи» с тем, откуда оно."""
    kind: str                 # birth | death | marriage
    sub: str                  # "" | bapt | burial | place
    date: dates.GDate | None
    place: str | None         # cr_id места
    spouse: str | None        # для брака
    prov: str                 # family | found | other_tree | inference | card
    conf: str                 # high | normal | low | card
    where: str                # «строка 42: …» — чтобы найти в карточке
    sources: list = field(default_factory=list)


@dataclass
class Conflict:
    person: cards.Person
    what: str                 # «рождение: дата», «рождение: место», «мать при рождении ребёнка»
    years: int                # насколько грубо: разница в годах (для мест и логики — своя оценка)
    lines: list               # [(значение, Claim или текст)]
    note: str = ""
    recorded: bool = False
    tokens: tuple = ()        # что искать в «Расхождениях», чтобы понять, записано ли

    @property
    def other_tree(self):
        return any(isinstance(c, Claim) and c.prov == "other_tree" for _, c in self.lines)


# ─── Даты как промежутки дней ───────────────────────────────────────────────────────────────

def _ord(y, m=1, d=1):
    return datetime.date(y, m, d).toordinal()


def _day_span(day):
    if day.d:
        o = _ord(day.y, day.m, day.d)
        return o, o
    if day.m:
        nxt = _ord(day.y + (day.m == 12), day.m % 12 + 1)
        return _ord(day.y, day.m), nxt - 1
    return _ord(day.y), _ord(day.y + 1) - 1


def span(g):
    """GDate → (от, до) в днях: «1905» — весь год, «ок. 1905» — 1903–1907, «до 1944» — что угодно до конца 1944."""
    if not g or not g.first:
        return None
    if g.kind == "BEF":
        return -FAR, _day_span(g.a)[1]
    if g.kind == "AFT":
        return _day_span(g.a)[0], FAR
    if g.kind in ("BET", "FROM", "TO"):
        lo = _day_span(g.a)[0] if g.a else -FAR
        hi = _day_span(g.b)[1] if g.b else FAR
        return lo, hi
    lo, hi = _day_span(g.a)
    w = WIDEN.get(g.kind, 0) * 366
    return lo - w, hi + w


def gap(a, b):
    """Сколько дней между двумя промежутками (0 — пересекаются)."""
    return max(0, a[0] - b[1], b[0] - a[1])


def years_apart(g1, g2):
    s1, s2 = span(g1), span(g2)
    return round(gap(s1, s2) / 365.25 + 0.49) if s1 and s2 else 0


# ─── Что утверждает каждая строка карточки ──────────────────────────────────────────────────

def classify(fact):
    label = (fact.label or "").lower().strip()
    if "кандидат" in label or "кандидат" in fact.reasoning.lower():
        return None
    for rx, kind, sub in LABEL:
        if rx.match(label):
            return kind, sub
    if label and not re.match(r"^\d+ (лет|год|года)$", label):
        return None
    text = re.sub(r"^[«\"(\s]+", "", fact.text.lower())
    for rx, kind, sub in TEXT:
        if rx.match(text):
            return kind, sub
    return None


def _day(t):
    parts = [int(x) for x in t.split(".")]
    return dates.Day(parts[2], parts[1], parts[0]) if len(parts) == 3 else dates.Day(parts[0])


def date_from_text(text, kind=""):
    """Дата из значения, когда в подписи её нет. Вывод важнее записи: «20 лет в 1891 — родился около 1871» → ок. 1871,
    «→ между 2012 и 2013» → между; иначе первая дата до «;». Скобки не читаем — там пояснения."""
    head = re.sub(r"\([^)]*\)", "", text.split(";")[0])
    if kind == "death" and "→" in head and "родил" in head.split("→", 1)[1]:
        head = head.split("→", 1)[0]   # «1957, в 74 годика → родилась между 1882 и 1883»: вывод — про рождение
    try:
        if m := BET_TEXT.search(head):
            return dates.GDate("BET", _day(m[1]), _day(m[2]))
        if m := ABT_TEXT.search(head):
            return dates.GDate("ABT" if "→" not in m[0] else "", _day(m[1]))
        if re.search(r"\d+ (лет|год|года)\b", head):
            return None   # возраст на дату записи — год записи не год рождения
        if m := DAY_IN_TEXT.search(head):
            return dates.GDate("", _day(m[1]))
    except dates.DateError:
        return None
    return None


class Index:
    def __init__(self, tree):
        self.tree = tree
        self.place = {}
        for pid, pl in tree.places.items():
            for n in [pl.stem, pl.name, *pl.aliases]:
                self.place.setdefault(n, pid)
        self.person = {p.stem: pid for pid, p in tree.people.items()}

    def links(self, text):
        return [link_target(f"[[{t}]]") for t in re.findall(r"\[\[([^\]]+)\]\]", text)]

    def ancestors(self, pid):
        out, seen = [], set()
        while pid and pid not in seen:
            seen.add(pid)
            out.append(pid)
            pid = self.tree.places[pid].parent if pid in self.tree.places else None
        return out

    def same_place(self, a, b):
        return a == b or a in self.ancestors(b) or b in self.ancestors(a)

    def place_name(self, pid):
        return self.tree.places[pid].name if pid in self.tree.places else pid


def claims_of(p, ix):
    out = []
    if p.born:
        out.append(Claim("birth", "", p.born, None, None, "card", "card", f"born: {p.fm.get('born')}"))
    if p.died:
        out.append(Claim("death", "", p.died, None, None, "card", "card", f"died: {p.fm.get('died')}"))
    if p.birth_place:
        out.append(Claim("birth", "place", None, p.birth_place, None, "card", "card", f"birth_place: {p.fm.get('birth_place')}"))
    if p.death_place:
        out.append(Claim("death", "place", None, p.death_place, None, "card", "card", f"death_place: {p.fm.get('death_place')}"))
    for f in p.facts:
        c = classify(f)
        if not c:
            continue
        kind, sub = c
        names = ix.links(f.text)
        places = [ix.place[n] for n in names if n in ix.place]
        spouses = [ix.person[n] for n in names if n in ix.person and ix.person[n] in p.spouses]
        # у похорон в тексте обычно даты другого: «кладбище открыто в 1969»
        date = f.date if f.date and f.date.first else None if sub == "burial" else date_from_text(f.text, kind)
        if kind == "marriage" and not spouses and len(p.spouses) == 1:
            spouses = p.spouses
        label = f"{f.date.ru() + ', ' if f.date else ''}{f.label}".strip(", ")
        out.append(Claim(kind, sub, date, places[0] if len(places) == 1 else None, spouses[0] if spouses else None,
                         f.provenance, f.confidence, f"строка {f.line}: **{label}:** {f.text[:140]}",
                         [ix.tree.sources[r.source].title for r in f.refs if r.source in ix.tree.sources]))
    return out


# ─── Сравнение ──────────────────────────────────────────────────────────────────────────────

def style_pair(a, b):
    """Два точных дня до 1919 с разницей 11–13 — старый и новый стиль, а не ошибка."""
    return (a.kind == b.kind == "" and a.a.d and b.a.d and min(a.a.y, b.a.y) < 1919
            and 11 <= abs(_ord(a.a.y, a.a.m, a.a.d) - _ord(b.a.y, b.a.m, b.a.d)) <= 13)


def shifted(c):
    """Крещение — до 60 дней после рождения, похороны — до 14 после смерти: двигаем промежуток назад."""
    s = span(c.date)
    back = {"bapt": 60, "burial": 14}.get(c.sub, 0)
    return (s[0] - back, s[1]) if s else None


def verdict(a, b):
    """Документ против чужого дерева, памяти или вывода — спора нет: документ верен, другую строку исправить."""
    doc = [c for c in (a, b) if c.prov == "found" and c.conf != "low"]
    weak = [c for c in (a, b) if c.prov in ("other_tree", "family", "inference")]
    if len(doc) == 1 and len(weak) == 1:
        w = weak[0]
        what = {"other_tree": "строку чужого дерева убрать",
                "family": "это оговорка — дату из рассказа убрать, слова о жизни оставить",
                "inference": "вывод проекта заменить датой документа"}[w.prov]
        return f"документ сильнее — исправить сразу: {what} ({w.where.split(':')[0]})"
    return ""


def compare_person(p, ix):
    found = []
    cl = claims_of(p, ix)
    for kind in ("birth", "death", "marriage"):
        dated = [c for c in cl if c.kind == kind and c.date and c.date.first]
        groups = {}
        for c in dated:
            groups.setdefault(c.spouse if kind == "marriage" else None, []).append(c)
        if kind == "marriage" and len(p.spouses) > 1:
            groups.pop(None, None)   # брак без супруга при двух браках — не с чем сравнивать
        for key, cs in groups.items():
            seen = set()
            for i, a in enumerate(cs):
                for b in cs[i + 1:]:
                    if a.prov == b.prov == "card":
                        continue
                    if gap(shifted(a), shifted(b)) == 0:
                        continue
                    pair = tuple(sorted((a.where, b.where)))
                    if pair in seen:
                        continue
                    seen.add(pair)
                    if style_pair(a.date, b.date):
                        found.append(Conflict(p, f"{KIND_RU[kind]}: дата — похоже, старый и новый стиль", 0,
                                              [(a.date.ru(), a), (b.date.ru(), b)],
                                              "разница 11–13 дней до 1919 года: проверить, в каком стиле каждая "
                                              "(навык dates)", tokens=(a.date.ru(), b.date.ru())))
                        continue
                    yrs = years_apart(a.date, b.date)
                    found.append(Conflict(p, f"{KIND_RU[kind]}: дата", yrs, [(a.date.ru(), a), (b.date.ru(), b)],
                                          verdict(a, b), tokens=_tokens(a.date, b.date)))
        placed = [c for c in cl if c.kind in ("birth", "death") and c.place and c.sub != "burial"]
        for i, a in enumerate(placed):
            for b in placed[i + 1:]:
                if a.kind != kind or b.kind != kind or (a.prov == b.prov == "card"):
                    continue
                if ix.same_place(a.place, b.place):
                    continue
                found.append(Conflict(p, f"{KIND_RU[kind]}: место", 1,
                                      [(ix.place_name(a.place), a), (ix.place_name(b.place), b)], verdict(a, b),
                                      tokens=(ix.place_name(a.place), ix.place_name(b.place))))
    return _dedupe(found)


def _tokens(*gs):
    return tuple(str(g.first.y) for g in gs)


def _dedupe(found):
    """Свойство карточки обычно повторяет одну из строк фактов — пара «свойство ↔ X» лишняя, если есть «факт ↔ X»
    с тем же значением."""
    out, keys = [], set()
    for c in sorted(found, key=lambda c: sum(isinstance(x, Claim) and x.prov == "card" for _, x in c.lines)):
        k = (c.what, frozenset(v for v, _ in c.lines))
        if k in keys:
            continue
        keys.add(k)
        out.append(c)
    return out


# ─── Здравый смысл ──────────────────────────────────────────────────────────────────────────

def backing(p, kind, ix):
    """На чём держится дата из свойства карточки: строки фактов с тем же годом → их происхождение."""
    g = p.born if kind == "birth" else p.died
    if not g:
        return ""
    provs = {c.prov for c in claims_of(p, ix) if c.kind == kind and c.prov != "card" and c.date
             and gap(span(c.date), span(g)) == 0}
    if not provs:
        return "ни одной строки факта с этой датой"
    return ", ".join(PROV_RU[x] for x in sorted(provs))


def logic(p, ix):
    T = ix.tree.people
    out = []

    def add(what, years, rows, note=""):
        out.append(Conflict(p, what, years, rows, note,
                            tokens=tuple(re.findall(r"\d{4}", " ".join(v for v, _ in rows)))))

    def row(q, kind):
        g = q.born if kind == "birth" else q.died
        word = "род." if kind == "birth" else "ум."
        return f"{q.name}: {word} {g.ru()}", f"держится на: {backing(q, kind, ix)}"

    if p.born and p.died:
        lo_b, hi_b = span(p.born)
        lo_d, hi_d = span(p.died)
        if hi_d < lo_b:
            add("умер раньше, чем родился", round((lo_b - hi_d) / 365.25), [row(p, "birth"), row(p, "death")])
        elif lo_d - hi_b > 105 * 365.25:
            add("прожил больше 105 лет", round((lo_d - hi_b) / 365.25) - 105, [row(p, "birth"), row(p, "death")])
    if not p.born:
        return out
    cb = span(p.born)
    for rel, lo_age, hi_age in (("mother", 14, 52), ("father", 15, 75)):
        for pid in getattr(p, rel):
            q = T.get(pid)
            if not q or not q.born:
                continue
            pb = span(q.born)
            youngest = (cb[0] - pb[1]) / 365.25   # самый молодой возможный возраст родителя
            oldest = (cb[1] - pb[0]) / 365.25
            word = "мать" if rel == "mother" else "отец"
            if oldest < lo_age:
                add(f"{word} моложе {lo_age} при рождении ребёнка", round(lo_age - oldest),
                    [row(q, "birth"), row(p, "birth")], f"возраст {word}и — не больше {oldest:.0f}".replace("отеци", "отца").replace("матьи", "матери"))
            elif youngest > hi_age:
                add(f"{word} старше {hi_age} при рождении ребёнка", round(youngest - hi_age),
                    [row(q, "birth"), row(p, "birth")], f"возраст — не меньше {youngest:.0f}")
            if q.died:
                limit = 0 if rel == "mother" else 300   # после смерти отца — до ~10 месяцев
                qd = span(q.died)
                if cb[0] - qd[1] > limit:
                    add(f"родился после смерти {'матери' if rel == 'mother' else 'отца'}",
                        max(1, round((cb[0] - qd[1]) / 365.25)), [row(q, "death"), row(p, "birth")])
    return out


# ─── Записано ли уже ────────────────────────────────────────────────────────────────────────

def mark_recorded(c):
    text, _ = section(c.person.body, "Расхождения")
    if text and c.tokens and all(t.lower() in text.lower() for t in set(c.tokens)):
        c.recorded = True


# ─── Вывод ──────────────────────────────────────────────────────────────────────────────────

def render_row(value, src):
    if not isinstance(src, Claim):
        return f"  - {value} — *{src}*"
    who = PROV_RU[src.prov]
    conf = "" if src.conf == "card" else f", уверенность {dict(high='высокая', normal='обычная', low='низкая')[src.conf]}"
    srcs = f" — [[{'; '.join(src.sources)}]]" if src.sources else ""
    return f"  - **{value}** — {who}{conf}{srcs}\n    {src.where}"


def render(conflicts, show_recorded):
    lines = []
    by_person = {}
    for c in conflicts:
        by_person.setdefault(c.person.id, []).append(c)
    order = sorted(by_person.values(), key=lambda cs: (-max(c.years for c in cs), cs[0].person.name))
    for cs in order:
        p = cs[0].person
        lines.append(f"\n## {p.name} · {p.id}  ({p.born.ru() if p.born else '?'} – {p.died.ru() if p.died else ''})")
        for c in sorted(cs, key=lambda c: -c.years):
            tag = " · ⚠️ чужое дерево" if c.other_tree else ""
            tag += " · записано в «Расхождениях»" if c.recorded else ""
            size = f" — на {c.years} г." if c.years and "место" not in c.what else ""
            lines.append(f"- **{c.what}**{size}{tag}")
            lines += [render_row(v, s) for v, s in c.lines]
            if c.note:
                lines.append(f"  - {'➡️ **' + c.note + '**' if c.note.startswith('документ') else '*' + c.note + '*'}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--person", help="часть имени или cr_id")
    ap.add_argument("--other-tree", action="store_true", help="только где одна сторона — чужое дерево")
    ap.add_argument("--min-years", type=int, default=0, help="даты: показывать расхождения не меньше N лет")
    ap.add_argument("--all", action="store_true", help="и то, что уже записано в «Расхождениях»")
    ap.add_argument("--no-logic", action="store_true", help="без проверок здравого смысла")
    ap.add_argument("--md", help="записать отчёт в файл")
    a = ap.parse_args(argv)

    tree = cards.load()
    ix = Index(tree)
    people = [p for p in tree.people.values()
              if not a.person or a.person.lower() in p.name.lower() or a.person == p.id]
    conflicts = []
    for p in people:
        conflicts += compare_person(p, ix)
        if not a.no_logic:
            conflicts += logic(p, ix)
    for c in conflicts:
        mark_recorded(c)
    shown = [c for c in conflicts
             if (a.all or not c.recorded)
             and (not a.other_tree or c.other_tree or any("чужое дерево" in str(s) for _, s in c.lines))
             and (c.years >= a.min_years or "место" in c.what or "стиль" in c.what)]

    kinds = {}
    for c in shown:
        kinds[c.what.split(":")[0]] = kinds.get(c.what.split(":")[0], 0) + 1
    head = [f"# Противоречия в фактах — {datetime.date.today():%d.%m.%Y}",
            "",
            f"Людей проверено: {len(people)}. Противоречий: {len(shown)} у {len({c.person.id for c in shown})} человек"
            f" (из них с чужим деревом: {sum(c.other_tree for c in shown)}; уже записано в «Расхождениях» и скрыто: "
            f"{0 if a.all else sum(c.recorded for c in conflicts)}).",
            "По видам: " + ", ".join(f"{k} — {v}" for k, v in sorted(kinds.items(), key=lambda kv: -kv[1])) + "."]
    report = "\n".join(head) + "\n" + render(shown, a.all)
    if a.md:
        Path(a.md).write_text(report + "\n", encoding="utf-8")
        print("\n".join(head) + f"\nОтчёт: {a.md}")
    else:
        print(report)
    return 1 if shown else 0


if __name__ == "__main__":
    sys.exit(main())
