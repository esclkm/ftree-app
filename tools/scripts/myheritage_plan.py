#!/usr/bin/env python3
"""Сравнить карточки дерева со снимком сайта MyHeritage и составить список работ. Сети не касается, ИИ не нужен.

Зачем. Дерево на MyHeritage ищет совпадения (Smart Matches) только по тому, что лежит в нём. Мы ведём дерево в
карточках `3_research/tree/` и хотим, чтобы на сайте лежал скелет: люди и связи, имя и фамилия, годы рождения и
смерти, места рождения и смерти. С 04.11.2026 ещё: брак и развод пары (дата, место), работа и служба не живых
(событие OCCU), главное фото (одно — то, что аватаром на нашем сайте; остальные снимки остаются у нас).
Заметки и прочие факты на сайт не грузим.

Как. Снимок делает `node tools/scripts/myheritage_web.mjs collect` (всё дерево 1, только чтение). Этот скрипт кладёт
рядом карточки и пишет два списка в `3_research/tree_data/mh_web/`:
  • «на сайт» — работы для `myheritage_web.mjs upload`: что исправить или добавить на сайте. Каждая строка
    `- [x] \\`номер\\` …`; Павел просматривает файл и меняет [x] на [ ] там, где грузить не надо;
  • «с сайта» — что есть на сайте, а в карточках нет (другой год, другой родитель, человек без карточки…). Только
    на просмотр: в карточки это вносим обычным путём, с происхождением «найдено / чужое дерево», не «семья».

Сопоставление «карточка ↔ человек на сайте» — по номеру: `gedcom_id: I25` в карточке = `125` на сайте
(карточки новых людей — по `<папка поиска>/myheritage_ids.json`, куда upload записывает номера созданных).
Имя — не ключ: по имени и году похожих людей скрипт только предлагает в «с сайта», сам не склеивает.

Правила (карточка главнее, но ничего не стираем):
  • дата: на сайте нет — добавить; первый год другой — заменить карточкой; тот же год — не трогать
    (сайт часто подробнее: «8 апреля 1927» против «1927»). Из карточки не стираем: на сайте есть, в карточке нет —
    строка «с сайта». Даты у живых не загружаем (живым — только имя).
  • «около / до / после / между» из карточки переходят на сайт как есть. «с … по» — коды на сайте не проверены,
    такие даты пропускаем и пишем в «с сайта» («внести руками»).
  • место рождения и смерти: на сайте пусто — добавить цепочкой карточек мест «Вербичи, Лесогорская область, Беларусь»
    (участок кладбища, дом, больница → город, в котором они). На сайте другой город — заменить карточкой; тот же город
    другими словами («Минск, Белоруссия») — не трогать.
    То же место другим языком или словами («Lesogorsk, Białoruś», «USA», «д. Вербичи») — не трогаем: язык как на сайте.
    Место «под вопросом» и река не грузятся. Живым мест не грузим, как и дат.
  • имя и фамилия: пояснение в скобках («Анна Ясенева (1856)») — не часть имени; «Unknown …» не грузим.
  • связи: родитель/супруг/ребёнок есть в карточке, а между двумя людьми на сайте их нет — работа `link`
    (пока вручную); человек без номера на сайте и с связью к человеку с номером — работа `person`
    (создать; пока вручную). Карточки без единой связи (упоминания: крёстные, соседи) на сайт не идут.

Команды:
  tools/py tools/scripts/myheritage_plan.py plan     # → plan.json, plan_to_site.md, from_site.md; итог — на экран
  tools/py tools/scripts/myheritage_plan.py stats    # только цифры, файлы не пишет
"""
import hashlib
import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dates  # noqa: E402
import living  # noqa: E402
import paths  # noqa: E402
from cards.notes import link_target  # noqa: E402
from cards.kinship import levels  # noqa: E402
from cards.tree import load  # noqa: E402
from myheritage_update import split_name  # noqa: E402

DATA = paths.TREE_DATA / "mh_web"
SNAPSHOT, PLAN, PLAN_MD, FROM_MD = (DATA / n for n in ("snapshot.json", "plan.json", "plan_to_site.md", "from_site.md"))
ID_MAP = paths.RESEARCH / "pavel" / "myheritage_ids.json"   # cr_id карточки → номер на сайте (создано upload-ом)

NFC = lambda s: unicodedata.normalize("NFC", str(s))


def norm(s):
    return NFC(s or "").casefold().replace("ё", "е").strip()


# ─── Даты сайта: «12 cze 1937», «Około 1917», «Pomiędzy 2009 i 2011», «Przed 2002» ──────────────

PL_MONTHS = "sty lut mar kwi maj cze lip sie wrz paź lis gru".split()
PL_KIND = (("około", "ABT"), ("przed", "BEF"), ("po ", "AFT"), ("pomiędzy", "BET"))


def site_date(text, year):
    """Что написано на сайте → (вид, первый год, второй год). Пусто → (None, None, None). Не поняли → ('?', год, None)."""
    t = (text or "").strip()
    if not t:
        return None, None, None
    low = t.lower() + " "
    kind = ""
    for pref, k in PL_KIND:
        if low.startswith(pref):
            kind = k
            break
    years = [int(y) for y in re.findall(r"\b(\d{4})\b", t)]
    if not years:
        return "?", int(year) if year else None, None
    if "?" in t:
        return "?", years[0], None
    return kind, years[0], (years[1] if kind == "BET" and len(years) > 1 else None)


# ─── Дата карточки → поля формы сайта ─────────────────────────────────────────────────────────

def to_form(g):
    """GDate → {type, op1, op2, y1, m1, d1, y2, m2, d2}; None — такой вид даты на сайт пока не грузим.
    Коды [П 02.10.2026, проверено записью и чтением]: точно 1/1 · около 4/4 · до 2/2 · после 3/3 · между 7/1+1.
    «С … по» (FROM/TO) — коды не проверены, такие даты на сайт не грузим."""
    a, b = g.a, g.b
    if g.kind == "":
        return dict(type=1, op1=1, y1=a.y, m1=a.m, d1=a.d)
    if g.kind in ("ABT", "CAL", "EST"):
        return dict(type=4, op1=4, y1=a.y, m1=a.m, d1=a.d)
    if g.kind == "BEF":
        return dict(type=2, op1=2, y1=a.y, m1=a.m, d1=a.d)
    if g.kind == "AFT":
        return dict(type=3, op1=3, y1=a.y, m1=a.m, d1=a.d)
    if g.kind == "BET":
        return dict(type=7, op1=1, op2=1, y1=a.y, m1=a.m, d1=a.d, y2=b.y, m2=b.m, d2=b.d)
    return None


# ─── Сопоставление и сравнение ────────────────────────────────────────────────────────────────

def site_no(card):
    """Номер человека на сайте из карточки: gedcom_id I25 → 125."""
    g = str(card.fm.get("gedcom_id") or "").strip()
    m = re.fullmatch(r"I(\d+)", g)
    return "1" + m.group(1) if m else None


def guess_born(cards):
    """cr_id → год рождения: свой, а нет — оценка по родне шагами поколения (ребёнок ≈ +25, родитель ≈ −25, супруг ≈
    ровесник; умер — родился не позже года смерти). Только для решения «живой или нет», на сайт не идёт."""
    est = {cid: p.born.first_year for cid, p in cards.items() if p.born and p.born.first_year}
    for _ in range(12):
        new = {}
        for cid, p in cards.items():
            if cid in est:
                continue
            g = [est[c] - 25 for c in p.children if c in est] + [est[c] + 25 for c in p.father + p.mother if c in est] \
                + [est[c] for c in p.spouses if c in est]
            if p.died and p.died.first_year:
                g.append(p.died.first_year - 60)
            if g:
                new[cid] = round(sum(g) / len(g))
        if not new:
            break
        est.update(new)
    return est


def is_living(p, est=None):
    """Живой? Общее правило (living.py): умер или родился (по оценке поколений) больше 110 лет назад — нет. Ничего не
    известно — живой: только имя."""
    if p.died:
        return False
    y = p.born.first_year if p.born else None
    y = y or (est or {}).get(p.id)
    return living.is_living(y and str(y), None, unknown=True)


def work_id(ind, action, payload):
    h = hashlib.sha1(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:6]
    return f"{ind}:{action}:{h}"


def expect_of(patch):
    """Что должно лечь в форму после записи — по этим полям upload проверяет себя."""
    e = {k: patch[k] for k in ("firstName", "lastName", "marriedName", "isAlive", "birthPlace", "deathPlace") if k in patch}
    for prefix, d in patch.get("dates", {}).items():
        e[f"gdp_firstDateYear_{prefix}"] = d["y1"]
    return e


def site_part(v):
    """Часть имени с сайта без пояснений в скобках: «Jasieniew (Wierzbowska)» → «Jasieniew»."""
    return norm(re.sub(r"\s*\(.*?\)", " ", v or ""))


def same_name(nm, s):
    """Имя карточки уже есть на сайте? Сайт часто подробнее («Witold (Витольд) Jasieniew») — тогда не трогаем.
    Одно слово в карточке («Jasieniew») — фамилия рода: подходит, если оно есть среди имени или фамилии сайта."""
    first, last = site_part(s["firstName"]), site_part(s["lastName"])
    cf, cl = norm(nm[0]), norm(nm[1])
    if not cl:
        return cf in (first, last) or cf == f"{first} {last}".strip()
    return cf == first and cl == last or f"{cf} {cl}" == f"{first} {last}".strip()


def feminine(surname):
    """Фамилия мужа → фамилия жены: Лесовский → Лесовская, Ясенев → Ясенева, Дубнякин → Дубнякина;
    Дубняк, Мелкша, Jasieniew — как есть."""
    s = (surname or "").strip()
    for m, f in (("ий", "ая"), ("ой", "ая")):
        if s.endswith(m):
            return s[:-2] + f
    return s + "а" if re.search(r"(ов|ев|ёв|ин|ын)$", s) else s


def site_married(s):
    """Фамилия после замужества, как её показывает сайт: «Агата Дубняк (Лесовский)» → «Лесовский»;
    без фамилии при рождении — «Helena Jasieniew» → «Jasieniew»."""
    if not s.get("lastName"):
        return (s.get("name") or "")[len(s.get("firstName") or ""):].strip()
    if (s["lastName"]).rstrip().endswith(")"):
        return ""
    m = re.search(r"\(([^()]*)\)\s*$", s.get("name") or "")
    return m.group(1).strip() if m else ""


def one_word_name(p, tree, word):
    """Имя из одного слова (04.11.2026, решение Павла — создавать). Слово — фамилия, если так у его детей («Дубняк»
    → дочь «Анна Дубняк») или так в строке «Фамилия:» («Wierzbowski — по фамилии жены»): тогда имя пустое. Иначе слово —
    имя, а фамилия — из surname_inferred карточки («Jasieniew — по матери»), если она есть."""
    kids = {(split_name(tree.people[c].name) or ("", ""))[1] for c in getattr(p, "children", []) if c in tree.people}
    said = next((f.text for f in getattr(p, "facts", []) if norm(f.label) == "фамилия"), "")
    if norm(word) in {norm(k) for k in kids if k} or norm(said).startswith(norm(word) + " "):
        return {"firstName": "", "lastName": word}
    inferred = str(p.fm.get("surname_inferred") or "").split("—")[0].strip()
    if inferred and len(inferred.split()) == 1:
        return {"firstName": word, "lastName": inferred}
    return None


def site_names(p, tree):
    """Имя карточки → поля сайта {firstName, lastName[, marriedName]}. lastName на сайте — фамилия при рождении:
    жене с фамилией мужа («Helena Jasieniew», муж «Kazimierz Jasieniew») она идёт в marriedName, а в lastName — девичья
    из поля карточки maiden_name или пусто (26.10.2026: «Мастер проверки» сайта нашёл 32 таких жены).
    Жене с девичьей фамилией в карточке («Агата Дубняк», муж «Иван Лесовский») — marriedName по мужу в женском
    роде: без него сайт сам ставит в скобки фамилию мужа как есть, «Агата Дубняк (Лесовский)» (03.11.2026, 18 жён)."""
    nm = split_name(p.name)
    if not nm:
        return None
    out = {"firstName": nm[0], "lastName": nm[1]}
    if not nm[1]:
        out = one_word_name(p, tree, nm[0]) or out
    if p.sex != "F":
        return out
    husbands = list(dict.fromkeys((split_name(tree.people[s].name) or ("", ""))[1] for s in p.spouses if s in tree.people))
    husbands = [h for h in husbands if h]
    if not nm[1]:
        # жена с одним именем («Ewa», муж Witold Jasieniew, 04.11.2026): фамилия по мужу — после замужества,
        # при рождении — девичья из maiden_name или пусто; мужей с разными фамилиями — не угадываем
        if len({norm(h) for h in husbands}) == 1:
            out.update(lastName=str(p.fm.get("maiden_name") or "").strip(), marriedName=feminine(husbands[0]))
        return out
    if any(norm(nm[1]) in (norm(h), norm(feminine(h))) for h in husbands):
        out = {"firstName": nm[0], "lastName": str(p.fm.get("maiden_name") or "").strip(), "marriedName": feminine(nm[1])}
    elif len({norm(h) for h in husbands}) == 1 and feminine(husbands[0]) != husbands[0]:
        # два мужа с разными фамилиями — какая после замужества, не знаем; Дубняк, Jasieniew — сайт и так покажет верно
        out["marriedName"] = feminine(husbands[0])
    return out


def date_work(label, prefix, card_date, site_text, site_year, living):
    """→ (правка dates либо None, строка для «с сайта» либо None, пояснение)."""
    sk, sy, sy2 = site_date(site_text, site_year)
    if living:
        return None, None, None
    if not card_date:
        return None, (f"{label}: на сайте «{site_text}», в карточке даты нет" if sk is not None else None), None
    form = to_form(card_date)
    if form is None:
        return None, f"{label}: в карточке «{card_date.card()}» — такой вид даты на сайт не грузим, внести руками (на сайте: «{site_text or '—'}»)", None
    if sk is None:
        return {prefix: form}, None, f"{label}: добавить {card_date.card()}"
    if sk == "?":
        return None, f"{label}: на сайте «{site_text}» не разобрали, в карточке {card_date.card()} — сверить руками", None
    if sy != card_date.first_year:
        return {prefix: form}, None, f"{label}: {site_text} → {card_date.card()}"
    return None, None, None


INSIDE = {"cemetery", "house", "street", "hospital", "school", "church", "university", "other"}   # не место на карте сайта — берём, где оно


def place_text(tree, pid):
    """cr_id места → «Вербичи, Лесогорская область, Беларусь» или None (нет места, река, «под вопросом»)."""
    x, parts, seen = tree.places.get(pid), [], set()
    while x and x.type in INSIDE and x.id not in seen:
        seen.add(x.id)
        x = tree.places.get(x.parent)
    if not x or x.type == "river":
        return None
    while x and x.id not in seen:
        seen.add(x.id)
        if "под вопросом" in x.name:
            return None
        if not parts or norm(parts[-1]) != norm(x.name):
            parts.append(x.name)
        x = tree.places.get(x.parent)
    return ", ".join(parts) or None


LAT = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюяіў",
               "a b v g d e e zh z i i k l m n o p r s t u f h ts ch sh sch _ y _ e yu ya i u".split()))
LAT.update({"ł": "l", "ą": "a", "ę": "e", "ó": "o", "ś": "s", "ź": "z", "ż": "z", "ć": "c", "ń": "n", "ü": "u", "_": ""})
COUNTRY = {"сша": "us", "usa": "us", "unitedstates": "us", "unitedstatesofamerica": "us", "беларусь": "by", "белоруссия": "by",
           "belarus": "by", "bialorus": "by", "polska": "pl", "poland": "pl", "польша": "pl", "россия": "ru", "russia": "ru",
           "rosja": "ru", "аргентина": "ar", "argentina": "ar", "парагвай": "py", "paraguay": "py"}


def place_key(text):
    """Первая часть места без «д.», знаков и языка → набор ключей: «Oak Hill (Lesogorsk)» → {oakhill,
    oakhilllesogorsk}; «Вербичи Беларусь» (без запятой) → {..., verbichi}; «Zarechye» → {zarechye}."""
    head = NFC(text).casefold().split(",")[0]
    out = set()
    for t in (re.sub(r"\(.*?\)", " ", head), head):
        t = re.sub(r"^\s*(д|с|г|дер|село|деревня|город|wieś|wies)\.?\s+", "", t)
        words = [re.sub(r"[^\w]", "", w) for w in t.split()]
        words = [w for w in words if w]
        for ws in (words, [w for w in words if w not in COUNTRY] or words):
            k = "".join(ws)
            lat = "".join(LAT.get(ch, ch) for ch in k)
            out.add(COUNTRY.get(k, COUNTRY.get(lat, lat)))
    return out


def cyr(text):
    return bool(re.search(r"[а-яё]", NFC(text).casefold().split(",")[0]))


def same_place(site_v, tree, pid):
    """Сайт называет то же место другим языком («Lesogorsk» — «Лесогорск») или теми же словами иначе («д. Вербичи»)? Тогда не
    трогаем. Тот же алфавит, другое написание («Вербечи», «Lesogrsk») — опечатка, хоть и записана в aliases: исправляем."""
    k = place_key(site_v)
    x, seen = tree.places.get(pid), set()
    while x and x.id not in seen:
        seen.add(x.id)
        names = [x.name] + ([a for a in x.aliases if cyr(a) == cyr(site_v)] if cyr(site_v) != cyr(x.name) else [])
        if x.type not in INSIDE and any(k & place_key(n) for n in names):
            return True
        x = tree.places.get(x.parent)
    return False


def place_work(tree, p, s):
    """→ (правка мест, пояснения, заменяем ли чужое). Пусто на сайте — дописываем; другой город — заменяем карточкой."""
    patch, why, replace = {}, [], False
    for label, key, pid in (("место рождения", "birthPlace", p.birth_place), ("место смерти", "deathPlace", p.death_place)):
        t = place_text(tree, pid) if pid else None
        if not t:
            continue
        site_v = (s.get(key) or "").strip()
        if not site_v:
            patch[key] = t
            why.append(f"{label}: добавить «{t}»")
        elif not same_place(site_v, tree, pid):
            patch[key] = t
            why.append(f"{label}: «{site_v}» → «{t}»")
            replace = True
    return patch, why, replace


def name_change(nm, s):
    """Правка имени → (текст, рискованно). Рискованно — заменяем непустое другое имя (а не достраиваем пустое/неполное)."""
    old = f"{s['firstName']} {s['lastName']}".strip()
    first = site_part(s["firstName"])
    risky = bool(first) and norm(nm[0]).split()[0] != first.split()[0]
    return f"имя: «{old or '—'}» → «{' '.join(nm).strip()}»", risky


def family_of(cards, graph):
    """Карточки, связанные с деревом: от корней 8 веток (ftree.toml) по родителям, детям, супругам. Обрывок вне
    этой семьи (родня недоказанного человека, записи о боковых ветках) на сайт не идёт, даже если в нём есть связи."""
    by_stem = {p.stem: cid for cid, p in cards.items()}
    todo = [by_stem[r] for r in paths.LINES.values() if r in by_stem]
    seen = set()
    while todo:
        x = todo.pop()
        if x in seen or x not in cards:
            continue
        seen.add(x)
        todo += graph.get(x, ()) | {o for o, rel in graph.items() if x in rel}
    return seen


def build(snap, tree):
    site = snap["persons"]
    cards = tree.people
    idmap = json.loads(ID_MAP.read_text()) if ID_MAP.exists() else {}
    by_ind, ind_of = {}, {}                        # номер на сайте → карточка; cr_id → номер на сайте
    claimed = set(idmap.values())                  # номера, которые сайт выдал созданным нами людям
    for cid, p in cards.items():
        # созданное нами главнее номера из старой выгрузки; а номер старой выгрузки (≥1500571 их на сайте не было), который
        # сайт уже выдал другому созданному нами человеку, — чужой (11.10.2026: «Unknown I25» ≠ созданный 125)
        ind = idmap.get(cid) if idmap.get(cid) in site else (site_no(p) if site_no(p) not in claimed else None)
        if ind in site:                            # номер, которого на сайте нет (наш прежний GEDCOM) — человек новый
            ind_of[cid] = ind
            by_ind.setdefault(ind, cid)
    est = guess_born(cards)
    to_site, from_site, info = [], [], {"matched": 0, "same": 0, "living_dates_skipped": 0}

    for ind, cid in by_ind.items():
        p, s = cards[cid], site[ind]
        info["matched"] += 1
        living = is_living(p, est)
        patch, why, replace = {}, [], False      # replace — меняем то, что на сайте стоит другим (карточка главнее)
        nm, names = split_name(p.name), site_names(p, tree)
        if names and "marriedName" in names and norm(names["lastName"]) != norm(nm[1]):
            # жена с фамилией мужа: на сайте фамилия при рождении должна быть девичьей (или пустой), а не мужниной
            if not (norm(names["firstName"]) == site_part(s["firstName"]) and norm(names["lastName"]) == site_part(s["lastName"])
                    and norm(names["marriedName"]) == norm(site_married(s))):
                patch.update(names)
                why.append(f"фамилия: «{s['lastName'] or '—'}» при рождении → «{names['lastName'] or '—'}», "
                           f"«{names['marriedName']}» — после замужества")
        else:
            if nm and not same_name(nm, s):
                patch["firstName"], patch["lastName"] = nm
                w, replace = name_change(nm, s)
                why.append(w)
            if names and "marriedName" in names and norm(names["marriedName"]) != norm(site_married(s)):
                # в карточке девичья, муж «Лесовский»: сайт сам показал бы «(Лесовский)» — ставим «Лесовская»
                patch["marriedName"] = names["marriedName"]
                why.append(f"фамилия после замужества: «{site_married(s) or '—'}» → «{names['marriedName']}»")
        dates_patch = {}
        for label, prefix, g, st, sy in (("рождение", "birthDate", p.born, s["birthDate"], s["birthYear"]),
                                         ("смерть", "deathDate", p.died, s["deathDate"], s["deathYear"])):
            d, fs, w = date_work(label, prefix, g, st, sy, living)
            if d:
                dates_patch.update(d)
                why.append(w)
                replace = replace or "→" in w
            if fs:
                from_site.append(dict(kind="дата", ind=ind, text=f"{p.stem}: {fs}"))
        if living and (p.born or p.died):
            info["living_dates_skipped"] += 1
        if not living:
            pl, w, rep = place_work(tree, p, s)
            patch.update(pl)
            if "deathPlace" in pl or (s.get("alive") and patch):   # живому на сайте место смерти не сохранится
                patch["isAlive"] = "deceased"
            why += w
            replace = replace or rep
        if dates_patch:
            patch["dates"] = dates_patch
            if "deathDate" in dates_patch:
                patch["isAlive"] = "deceased"
        if patch:
            to_site.append(dict(work=work_id(ind, "field", patch), action="field", ind=ind, card=p.stem, patch=patch,
                                expect=expect_of(patch), replace=replace, text=f"{p.stem}: " + "; ".join(why)))
        else:
            info["same"] += 1

    # связи между людьми, которые уже на сайте: в карточке есть, на сайте нет
    seen = set()
    for ind, cid in by_ind.items():
        p, site_rel = cards[cid], {k: set(v) for k, v in site[ind]["relatives"].items()}
        for rel, ids, key in (("father", p.father, "parents"), ("mother", p.mother, "parents"),
                              ("spouse", p.spouses, "spouses"), ("child", p.children, "children")):
            for o in ids:
                oi = ind_of.get(o)
                if not oi or oi in site_rel.get(key, set()):
                    continue
                pair = frozenset((ind, oi, "spouse" if rel == "spouse" else "parent"))
                if pair in seen:
                    continue
                seen.add(pair)
                a, b = p.stem, cards[o].stem
                txt = {"father": f"{a}: отец — {b}", "mother": f"{a}: мать — {b}", "spouse": f"{a} и {b}: супруги",
                       "child": f"{b}: родитель — {a}"}[rel]
                to_site.append(dict(work=work_id(ind, "link", [rel, oi]), action="link", ind=ind, other=oi, rel=rel,
                                    text=txt + " (связь есть в карточке, на сайте её нет)"))

    # люди без номера на сайте: идём волнами от тех, кто уже есть — у каждого нового есть «якорь» (родня, к которой его
    # пристроить). Карточки без единой связи (упоминания) и «не родня» на сайт не идут.
    graph = {cid: set(p.father + p.mother + p.spouses + p.children) for cid, p in cards.items()}
    family = family_of(cards, graph)               # только те, кто связан с деревом родством (как и для Familio)
    info["outside_family"] = sum(1 for cid in cards if cid not in ind_of and graph[cid] and cid not in family)
    kin = levels(tree)                             # новых — только с доказанным родством; «вероятно» и ниже ждут документа
    info["unproven"] = sum(1 for cid in family if cid not in ind_of and graph[cid] and kin.get(cid, ("?",))[0] != "proven")
    candidates = {cid for cid, p in cards.items()
                  if cid not in ind_of and cid in family and kin.get(cid, ("?",))[0] == "proven" and not any(k == "kin" for k, _ in p.ruled_out) and split_name(p.name)}
    info["no_links"] = sum(1 for cid in cards if cid not in ind_of and not graph[cid])
    placed = set(ind_of)
    wave, left = 0, set(candidates)
    relax = False                                  # дети ждут второго родителя; если ждать нечего — создаём без него
    while left:
        wave += 1
        batch = []
        for cid in left:
            near = sorted(o for o in graph[cid] if o in placed)
            if near:
                batch.append((cid, near[0]))
        ready = []
        for cid, anchor in batch:
            p, a = cards[cid], cards[anchor]
            rel = "father" if cid in a.father else "mother" if cid in a.mother else "spouse" if cid in a.spouses else "child"
            # второй родитель — только ребёнку и только тот, кто на сайте или будет создан: «вероятного» ждать нечего
            others = [x for x in p.father + p.mother if x != anchor and (x in placed or x in candidates)] if rel == "child" else []
            if rel == "child" and not relax and any(o in left and o not in placed and not any(o == c for c, _ in batch) for o in others):
                continue                           # второй родитель ещё не пристроен и не будет в этой волне — подождём
            ready.append((cid, anchor, rel, others[0] if others else None))
        if not ready:
            if relax:
                break
            relax = True
            wave -= 1
            continue
        relax = False
        ready.sort(key=lambda r: (r[2] == "child", cards[r[0]].stem))   # сначала родители и супруги, потом дети
        for cid, anchor, rel, other in ready:
            p = cards[cid]
            nm = split_name(p.name)
            living = is_living(p, est)
            patch = site_names(p, tree)
            if not living:
                dd = {}
                for prefix, g in (("birthDate", p.born), ("deathDate", p.died)):
                    f = to_form(g) if g else None
                    if f:
                        dd[prefix] = f
                if dd:
                    patch["dates"] = dd
                for key, pid in (("birthPlace", p.birth_place), ("deathPlace", p.death_place)):
                    t = place_text(tree, pid) if pid else None
                    if t:
                        patch[key] = t
                patch["isAlive"] = "deceased"
            to_site.append(dict(work=work_id(cid, "person", [nm, anchor, rel]), action="person", cr_id=cid, sex=p.sex, patch=patch,
                                anchor_cr=anchor, anchor=ind_of.get(anchor), rel=rel, other_cr=other, other=ind_of.get(other) if other else None,
                                wave=wave, risky=False,   # имя из одного слова — тоже создаём (Павел, 04.11.2026), как решил one_word_name
                                text=f"{p.stem}: создать как {REL_RU[rel]} «{cards[anchor].stem}»" + (f", второй родитель «{cards[other].stem}»" if other else "")
                                + (" (живой — только имя)" if living else "") + (f" — на сайте: имя «{patch.get('firstName') or '—'}», фамилия «{patch.get('lastName') or patch.get('marriedName') or '—'}»" if not nm[1] else "")))
        placed |= {c for c, *_ in ready}
        left -= {c for c, *_ in ready}
    info["orphans"] = len(left)
    for cid in sorted(left, key=lambda c: cards[c].stem):
        from_site.append(dict(kind="не пристроены", ind=None, text=f"{cards[cid].stem}: связан только с людьми, которых нет ни на сайте, ни среди создаваемых"))

    # человек на сайте, которому нет карточки
    known = set(ind_of.values())
    for ind, s in site.items():
        if ind not in known:
            from_site.append(dict(kind="нет карточки", ind=ind, text=f"{s['name']} ({s['birthYear'] or '—'}–{s['deathYear'] or '—'}) — на сайте есть, карточки с этим номером нет"))
    info.update(cards=len(cards), site=len(site), links_missing=len(seen), new_people=len(candidates) - len(left))
    to_site += event_works(tree, cards, ind_of, idmap, candidates, est)
    to_site += family_works(tree, cards, ind_of, idmap, candidates, est, done_payloads())
    to_site += occupation_works(cards, ind_of, idmap, candidates, est)
    to_site += photo_works(cards, ind_of, site, site_avatars())
    return to_site, from_site, info


# ─── Брак, развод, работа, главное фото (04.11.2026) ─────────────────────────────────────────────
# Всё берётся из карточек и снимка — заново ничего не читается: сделанное (по журналу) второй раз не уходит,
# изменившееся у нас — новой работой, помеченной ⚠ (на сайте уже лежит прежнее — его надо поправить, а не добавить второе).

JOURNAL = DATA / "journal.jsonl"
MARRY = re.compile(r"брак|свадьб|венча|жени[тл]|замуж|обручен", re.I)
DIVORCE = re.compile(r"развод|развел|расторж", re.I)
DAY_RU = re.compile(r"^\s*(\d{2})\.(\d{2})\.(\d{4})\b")
LINK_RE = re.compile(r"\[\[([^\]|#\\]+)(?:\|([^\]]+))?\]\]")
NO_JOB = re.compile(r"^(не указано|неизвестно|нет|в|во|к|ко|по|с|со|на|после|до|при|у)\b", re.I)
OCCU_LABEL = re.compile(r"^(занятие|профессия|работа|служба)\b", re.I)


def done_payloads():
    """Сделанные работы по журналу: «ключ без хэша» → хэш. Нужно, чтобы изменённый брак не лёг на сайт вторым."""
    out = {}
    if JOURNAL.exists():
        for line in JOURNAL.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("status") == "ok" and str(r.get("work", "")).count(":") >= 2:
                k, _, h = r["work"].rpartition(":")
                out[k] = h
    return out


def plain(text):
    """Строка факта → текст для сайта: ссылки — их подписью, без звёздочек и хвоста «— источник»."""
    t = LINK_RE.sub(lambda m: m.group(2) or m.group(1), str(text or ""))
    t = re.sub(r"\s+—\s+\*?источник.*$", "", t).replace("*", "")
    return re.sub(r"\s+", " ", t).strip(" ;,—")


RU_MONTH = {m: i + 1 for i, m in enumerate("январ феврал март апрел ма июн июл август сентябр октябр ноябр декабр".split())}
DAY_MONTH = re.compile(r"(\d{1,2})\s+(январ|феврал|март|апрел|ма[яй]|июн|июл|август|сентябр|октябр|ноябр|декабр)\w*", re.I)


def fact_date(f):
    """Дата факта по новому стилю: «23.09.1944, …» в начале текста; подпись «1881, 26 октября (ст. ст.; н. ст.
    7 ноября)» — день по новому стилю из «н. ст.», а нет его — старый стиль переводим; иначе — дата подписи."""
    m = DAY_RU.match(f.text or "")
    if m:
        return dates.parse_card(f"{m[3]}-{m[2]}-{m[1]}")
    g = f.date if f.date and f.date.a else None
    label = f.label or ""
    if g and g.kind == "" and not g.a.m:
        ns = re.search(r"н\.\s?ст\.?\s*" + DAY_MONTH.pattern, label, re.I)
        dm = ns or DAY_MONTH.search(label)
        if dm:
            mon = next(i for k, i in RU_MONTH.items() if dm.group(2).lower().startswith(k))   # «март» раньше «ма»
            day = dates.Day(g.a.y, mon, int(dm.group(1)))
            if not ns and re.search(r"ст\.\s?ст", label) and dates.old_style_era(day):
                day = dates.julian_to_gregorian(day)
            return dates.GDate("", day)
    return g


def fact_place(tree, text):
    """Первое место-ссылка в тексте факта → «Лесогорск, Лесогорская область, Беларусь»."""
    place_of = {pl.stem: pid for pid, pl in tree.places.items()}
    for m in LINK_RE.finditer(str(text or "")):
        pid = place_of.get(m.group(1).strip())
        if pid:
            return place_text(tree, pid) or ""
    return ""


def couple_facts(tree, cards):
    """(вид, пара) → {date: GDate|None, place: str, why: str} — из фактов карточек и из событий; факт с датой главнее."""
    stem2id = {p.stem: cid for cid, p in cards.items()}
    out = {}

    def put(kind, pair, g, place, why):
        cur = out.get((kind, pair))
        score = (g is not None, bool(place))
        if not cur or score > (cur["date"] is not None, bool(cur["place"])):
            out[(kind, pair)] = dict(date=g, place=place or (cur or {}).get("place", ""), why=why)
        elif not cur["place"] and place:
            cur["place"] = place

    for cid, p in cards.items():
        for f in p.facts:
            label = re.sub(r"\([^()]*\)", "", f.label or "")
            kind = "DIV" if DIVORCE.search(label) else "MARR" if MARRY.search(label) else None
            if not kind and not re.search(r"[а-яa-z]{3}", re.sub(DAY_MONTH, "", label), re.I):
                # подпись — только дата («1881, 26 октября …»): событие — по первым словам текста («обвенчался …»)
                head = (f.text or "")[:40]
                kind = "DIV" if DIVORCE.search(head) else "MARR" if re.search(r"обвенча|венчал|женил|вышла замуж|вступил[аи]? в брак|заключили брак", head, re.I) else None
            if not kind:
                continue
            named = [stem2id.get(m.group(1).strip()) for m in LINK_RE.finditer(f.text or "")]
            other = next((o for o in named if o and o in p.spouses), None)
            if other:
                put(kind, frozenset((cid, other)), fact_date(f), fact_place(tree, f.text), f"{p.stem}, строка {f.line}")
    place_of = {pl.stem: pid for pid, pl in tree.places.items()}
    for e in tree.events:
        kind = {"marriage": "MARR", "divorce": "DIV"}.get(e.get("event_type"))
        ids = [stem2id.get(link_target(str(x))) for x in e.get("persons") or []]
        if not kind or len(ids) != 2 or not all(ids):
            continue
        try:
            g = dates.parse_card(e.get("date")) if e.get("date") else None
        except dates.DateError:
            g = None
        pid = place_of.get(link_target(str(e.get("place") or "")))
        put(kind, frozenset(ids), g, place_text(tree, pid) if pid else "", f"событие {e.get('cr_id')}")
    return out


def family_works(tree, cards, ind_of, idmap, candidates, est, done):
    """Брак и развод пары → работа `family`: оба на сайте (или создаются), оба не живые, и есть что сказать — дата
    или место. Без даты и места на сайт не идёт: что они супруги, сайт и так знает по связи."""
    new = set(candidates or ())
    out = []
    for (kind, pair), v in sorted(couple_facts(tree, cards).items(), key=lambda kv: sorted(cards[c].stem for c in kv[0][1])):
        a, b = sorted(pair, key=lambda c: cards[c].stem)
        if not all(c in ind_of or c in idmap or c in new for c in (a, b)) or any(is_living(cards[c], est) for c in (a, b)):
            continue
        form = to_form(v["date"]) if v["date"] else None
        if not form and not v["place"]:
            continue
        payload = [kind, form, v["place"]]
        key = f"{a}+{b}:{kind.lower()}"
        w = work_id(key.split(":")[0], kind.lower(), payload)
        changed = key in done and not w.endswith(done[key])
        word = "брак" if kind == "MARR" else "развод"
        when = v["date"].ru() if v["date"] else "без даты"
        out.append(dict(work=f"{key}:{w.rsplit(':', 1)[1]}", action="family", kind=kind, a_cr=a, b_cr=b,
                        a=ind_of.get(a), b=ind_of.get(b), date=form, place=v["place"], risky=changed,
                        text=f"{cards[a].stem} и {cards[b].stem}: {word} — {when}" + (f", {v['place']}" if v["place"] else "")
                        + (" — на сайте уже лежит прежний: поправь его там руками, эту строку не отмечай" if changed else "")))
    return out


def short_job(text):
    """Поле «Занятие» на сайте — короткое: до первой «;», « — » или скобки, не длиннее 80 знаков, без кавычек-цитат."""
    t = re.split(r";| — | – |\(|«", text, maxsplit=1)[0].strip(" ,.:")
    return t if len(t) <= 80 else t[:80].rsplit(" ", 1)[0] + "…"


def occupation_works(cards, ind_of, idmap, candidates, est):
    """Работа и служба → событие OCCU (по нему MyHeritage ищет справочники и газеты). Только не живым: о живых —
    только имя. Источник — поле occupation и факты с подписью «Занятие», «Профессия», «Работа», «Служба»."""
    new = set(candidates or ())
    out = []
    for cid, p in sorted(cards.items(), key=lambda kv: kv[1].stem):
        if not (cid in ind_of or cid in idmap or cid in new) or is_living(p, est):
            continue
        items = []
        if p.fm.get("occupation"):
            items.append((None, plain(p.fm["occupation"])))
        for f in p.facts:
            m = OCCU_LABEL.match(f.label or "")
            g = f.date if f.date and f.date.a else None
            # «Занятие», «Профессия» — как в документе; «Работа», «Служба» — только с датой: без даты это обычно
            # рассказ («к 40 годам», «учиться не захотел»), не название работы
            if m and (m.group(1).lower() in ("занятие", "профессия") or g):
                items.append((g, plain(f.text)))
        seen = set()
        for g, text in items:
            text = short_job(text)
            # «Не указано», «в (1944–1945)», «к Дню города» — не название работы: начало с предлога или пустое слово
            if not text or len(text) < 4 or NO_JOB.match(text) or norm(text) in seen:
                continue
            seen.add(norm(text))
            form = to_form(g) if g else None
            out.append(dict(work=work_id(cid, "occupation", [text, form]), action="occupation", cr_id=cid, ind=ind_of.get(cid),
                            fact="OCCU", date=form, header=text, text=f"{p.stem}: работа — {text}" + (f" ({g.ru()})" if g else "")))
    return out


# Главное фото — лицо человека. Скан метрики, судовой список, могила, оборот снимка — не портрет, хотя у нас стоят
# первыми в media (04.11.2026: у Прокопа Ясенева первым — лист Эллис-Айленда). Сначала «точно не портрет», потом
# «портрет» («портрет», «фото», «ателье» — в том числе фото из паспорта или некролога), потом прочие признаки документа.
NOT_FACE = re.compile(r"оборот|могил|mogila|grob|надгроб", re.I)
FACE = re.compile(r"портрет|portret|фото|foto|photo|ателье", re.I)
DOC_LIKE = re.compile(r"ellis|familysearch|\bDGS|_DGS|рожд|брак_|венч|смерт|ревизи|исповед|прошени|petition|ГАСО|_ф\d+_оп|"
                      r"подпис|перепис|указател|список|акт_|запис|_p\d+|лист|газет|справк|паспорт|свидетельств|"
                      r"аттестат|удостоверени|диплом|трудов|cédula|cedula|\bdni\b", re.I)


def is_portrait(name):
    if NOT_FACE.search(name):
        return False
    return bool(FACE.search(name)) or not DOC_LIKE.search(name)


def site_avatars():
    """cr_id → файл главного фото: первый открытый снимок человека на нашем сайте, который похож на портрет.
    Закрытые (по паролю) на сайт MyHeritage не идут: берём только то, что открыто на нашем сайте."""
    folder = paths.SITE_EXPORT / "data" / "people"
    out = {}
    for j in sorted(folder.glob("*.json")) if folder.is_dir() else ():
        try:
            d = json.loads(j.read_text(encoding="utf-8"))
        except ValueError:
            continue
        for m in d.get("media") or []:
            f = paths.SITE_EXPORT / str(m.get("url") or "").lstrip("/")
            if m.get("kind") == "photo" and not m.get("private") and f.is_file() and is_portrait(f.name):
                out[d["id"]] = f
                break
    return out


def photo_works(cards, ind_of, site, avatars):
    """Главное фото → на сайт тем, у кого на MyHeritage фото нет (snapshot: photo=false). Только одно, главное: прочие
    снимки остаются у нас. Живым тоже (решение Павла, 02.10.2026): аватар — уже открытый снимок с нашего сайта."""
    out = []
    for cid, f in sorted(avatars.items(), key=lambda kv: kv[1].name):
        ind = ind_of.get(cid)
        if not ind or cid not in cards or site[ind].get("photo"):
            continue
        rel = str(f.relative_to(paths.ROOT))
        out.append(dict(work=work_id(ind, "photo", rel), action="photo", ind=ind, cr_id=cid, file=rel,
                        text=f"{cards[cid].stem}: главное фото — {f.name}"))
    return out


MH_FACTS = {"IMMI": "прибытие", "EMIG": "отъезд", "RESI": "жительство"}


def event_works(tree, cards, ind_of, idmap, candidates, est):
    """События с пометкой mh_fact (IMMI · EMIG · RESI) → работы «событие» тем, кто есть на сайте или создаётся.
    Только помеченные: переезды и жизнь за границей — по ним MyHeritage ищет записи о прибытии и переписи.
    Повтора нет: сделанная работа (по журналу) второй раз не выполняется; номер работы — событие + человек."""
    stem2id = {p.stem: cid for cid, p in cards.items()}
    place_of = {pl.stem: pid for pid, pl in tree.places.items()}
    new = set(candidates or ())
    out = []
    for e in tree.events:
        fact = str(e.get("mh_fact") or "").strip().upper()
        if fact not in MH_FACTS:
            continue
        try:
            g = dates.parse_card(e.get("date"))
        except dates.DateError:
            g = None
        form = to_form(g) if g else None
        pid = place_of.get(link_target(str(e.get("place") or "")))
        place = place_text(tree, pid) if pid else ""
        title = str(e.get("title") or "")
        for ln in e.get("persons") or []:
            cid = stem2id.get(link_target(str(ln)))
            if not cid or not (cid in ind_of or cid in idmap or cid in new) or is_living(cards[cid], est):
                continue   # живым событий не грузим, как и дат
            out.append(dict(work=f"{e.get('cr_id')}:{cid}:event", action="event", cr_id=cid, ind=ind_of.get(cid),
                            fact=fact, date=form, place=place, header=title[:120],
                            text=f"{cards[cid].stem}: {MH_FACTS[fact]} — {title}" + (f" ({place})" if place else "")))
    return out


REL_RU = {"father": "отца", "mother": "мать", "spouse": "супруга(у)", "child": "ребёнка"}


def write_files(snap, to_site, from_site, info):
    DATA.mkdir(parents=True, exist_ok=True)
    plan = dict(generated=datetime.now().isoformat(timespec="seconds"), site=snap["site"], snapshot=snap["collected"],
                to_site=to_site, from_site=from_site, info=info)
    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    old = PLAN_MD.read_text(encoding="utf-8") if PLAN_MD.exists() else ""
    # решения Павла сохраняем при пересборке — только то, что отличалось от умолчания (рискованное — не отмечено, прочее — отмечено)
    ticked = set(re.findall(r"^- \[x\] `([^`]+)`", old, re.M))
    struck = set(re.findall(r"^- \[ \] `([^`]+)`", old, re.M))
    mark = lambda w: ("x" if w["work"] in ticked else " ") if w.get("risky") else (" " if w["work"] in struck else "x")
    sign = lambda w: "⚠ " if w.get("risky") else "↻ " if w.get("replace") else ""
    head = [f"# На сайт MyHeritage — список работ ({plan['generated'][:16]})", "",
            f"Снимок сайта: {snap['collected'][:16]}. Строка `[x]` — загрузится, `[ ]` — нет. Выполнить: "
            "`node tools/scripts/myheritage_web.mjs upload --go`.",
            "↻ — заменяем то, что на сайте стоит другим (карточка главнее); отмечено — сними, если сайт прав.",
            "⚠ — не понятно, как грузить (имя из одного слова); по умолчанию не отмечено.", ""]
    names = {"field": "Имя, годы и места", "link": "Связи между людьми, которые уже на сайте", "person": "Новые люди",
             "event": "События: переезды и жительство (mh_fact)", "family": "Брак и развод (дата, место)",
             "occupation": "Работа и служба", "photo": "Главное фото (только одно; остальные — у нас)"}
    body = []
    for act in ("field", "link", "person", "event", "family", "occupation", "photo"):
        rows = [w for w in to_site if w["action"] == act]
        body += ["", f"## {names[act]} — {len(rows)}", ""]
        body += [f"- [{mark(w)}] `{w['work']}` {sign(w)}{w['text']}" for w in rows]
    PLAN_MD.write_text("\n".join(head + body) + "\n", encoding="utf-8")
    by_kind = {}
    for r in from_site:
        by_kind.setdefault(r["kind"], []).append(r)
    out = ["# С сайта MyHeritage — чего нет в карточках", "",
           "Только на просмотр. Внести в карточки — обычным путём, происхождение «найдено / чужое дерево».", ""]
    for k, rows in by_kind.items():
        out += ["", f"## {k} — {len(rows)}", ""] + [f"- {'`' + r['ind'] + '` ' if r['ind'] else ''}{r['text']}" for r in rows]
    FROM_MD.write_text("\n".join(out) + "\n", encoding="utf-8")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("plan", "stats"):
        sys.exit(__doc__)
    if not SNAPSHOT.exists():
        sys.exit("нет снимка сайта — сначала: node tools/scripts/myheritage_web.mjs collect")
    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    tree = load()
    to_site, from_site, info = build(snap, tree)
    kinds = {}
    for w in to_site:
        kinds[w["action"]] = kinds.get(w["action"], 0) + 1
    print(f"снимок от {snap['collected'][:16]}: на сайте {info['site']}, карточек {info['cards']}, сопоставлено {info['matched']}, без правок {info['same']}")
    print(f"на сайт: {kinds or 'ничего'}; с сайта: {len(from_site)}; без связей {info['no_links']}, вне семьи {info['outside_family']}, родство не доказано {info['unproven']} (на сайт не идут); живым даты не грузим {info['living_dates_skipped']}")
    if cmd == "plan":
        write_files(snap, to_site, from_site, info)
        print(f"→ {PLAN_MD.relative_to(paths.ROOT)}, {FROM_MD.relative_to(paths.ROOT)}")


if __name__ == "__main__":
    main()
