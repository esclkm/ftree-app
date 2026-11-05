#!/usr/bin/env python3
"""Дерево Павла на Familio ← наше дерево: сравнить и составить план правок (сам скрипт на сайт не пишет).

Зачем. На Familio лежит старая выгрузка из MyHeritage (478 человек, сентябрь 2025): без дат, с опечатками в названиях деревень, латиница. Наше
дерево точнее. План говорит, что поправить у каждого человека и кого добавить; выполняет план страница Familio в
браузере проекта, под входом Павла (ключ входа из страницы не выносим — CLAUDE.md).

Вход: `<папка>/familio_tree.json` — {"me": uuid, "persons": [...], "events": {uuid: [...]}} (выгрузка из браузера:
/api/v3/persons?owner=… и /api/v2/persons/<uuid>/events). Выход: `<папка>/plan.json` и сводка в консоль.

    tools/py tools/scripts/familio_sync.py fetch <папка>   # скачать дерево Павла с Familio (открытые данные, без входа)
    tools/py tools/scripts/familio_sync.py plan <папка> [--save-snapshot]   # сравнить → plan.json; слепок пар — в tree_data
    tools/py tools/scripts/familio_sync.py pack <папка>    # сжать plan.json → plan_c.json для familio_apply.js (+ sha256)
    tools/py tools/scripts/familio_sync.py check <папка>   # после записи: связи (родители, дети, супруги) у нас и на Familio

Правила:
- Кто есть кто — от Павла по родству (родители, дети, супруги), потом — по имени и году, если ответ один.
- Семья — все, кто связан с Павлом через родителей, детей, супругов. Посторонние из документов не идут.
- Имя — русское написание (aliases), если есть; фамилия женщины в карточке — девичья (birthLastName), фамилия по мужу —
  с Familio или от мужа. Отчество на Familio не трогаем (у нас их нет по правилу, это не значит «неверно»).
- Даты, места, родители, супруги — наши. Пусто у нас, есть на Familio — оставляем Familio. Лишних не удаляем — список.
"""
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

from cards.tree import load
from paths import ARCHIVES_ONLINE, TREE_DATA, tree_conf

MAP = ARCHIVES_ONLINE / "familio" / "settlements.json"
SNAP = TREE_DATA / "familio_match.json"   # слепок: наша карточка (cr_id) → человек на Familio; следующий раз не угадываем
OWNER = "568116a2-82ec-4a52-a777-747384d8034e"   # аккаунт Павла на Familio (открытый номер, не ключ входа)
API = "https://familio.org/api"


def get(path):
    req = urllib.request.Request(f"{API}/{path}", headers={"Accept": "application/ld+json", "User-Agent": "ftree-genealogy/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def fetch(folder: Path):
    """Люди Павла, их события и поля имени — открытые данные Familio (скрытые им самим сюда не попадут)."""
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / "familio_tree.json"
    fam = json.loads(out.read_text()) if out.exists() else {"persons": [], "events": {}, "basic": {}}
    if not fam["persons"]:
        page = 1
        while True:
            j = get(f"v3/persons?page={page}&owner={OWNER}&itemsPerPage=300&orderBy=full_name&orderDirection=asc&mentions=false")
            fam["persons"] += [{k: x.get(k) for k in ("uuid", "displayName", "shortDisplayName", "gender", "isMe", "birthDate")}
                               for x in j["data"]]
            if len(j["data"]) < 300:
                break
            page += 1
    for i, p in enumerate(fam["persons"]):
        u = p["uuid"]
        if u not in fam["events"]:
            fam["events"][u] = [e for e in get(f"v2/persons/{u}/events") if e.get("type") in ("birth", "death", "wedding")]
            time.sleep(0.8)
        if u not in fam["basic"]:
            fam["basic"][u] = get(f"v2/persons/{u}/basic")
            time.sleep(0.8)
        if i % 25 == 0:
            out.write_text(json.dumps(fam, ensure_ascii=False))
            print(i, "/", len(fam["persons"]), flush=True)
    out.write_text(json.dumps(fam, ensure_ascii=False))
    print("готово:", len(fam["persons"]))
CYR = re.compile(r"[А-Яа-яЁё]")
TR = str.maketrans({"ё": "е", "й": "и"})


def norm(s: str) -> str:
    return (s or "").lower().translate(TR).strip()


LAT = {"a": "а", "b": "б", "v": "в", "g": "г", "d": "д", "e": "е", "z": "з", "i": "и", "j": "й", "k": "к", "l": "л",
       "m": "м", "n": "н", "o": "о", "p": "п", "r": "р", "s": "с", "t": "т", "u": "у", "f": "ф", "h": "х", "c": "ц",
       "y": "ы", "w": "в", "x": "кс", "q": "к"}


def key(s: str) -> str:
    """Грубый ключ имени для сравнения латиницы и кириллицы: Jasieniew ≈ Ясенев, Witold ≈ Витольд."""
    s = norm(s)
    s = s.replace("sz", "ш").replace("sh", "ш").replace("ch", "ч").replace("cz", "ч").replace("zh", "ж").replace("ia", "я")
    s = "".join(LAT.get(c, c) for c in s)
    s = s.replace("я", "а").replace("ы", "и").replace("ь", "").replace("ъ", "").replace("э", "е")
    s = re.sub(r"(.)\1", r"\1", s)
    return s[:4]


# ---------- наше дерево ----------

def names(p) -> tuple[str, str]:
    """(имя, фамилия) — русское написание, если есть."""
    cands = [re.sub(r"№\d+", "", a) for a in (p.fm.get("aliases") or []) if isinstance(a, str)] + [re.sub(r"№\d+", "", p.stem)]
    base = re.sub(r"\s*\(.*?\)\s*|№\d+", " ", p.stem).split()
    first = base[0] if base else ""
    for c in cands:
        w = re.sub(r"\s*\(.*?\)\s*", " ", c).split()
        if len(w) >= 2 and CYR.search(w[-1]) and norm(w[0]) == norm(first):
            return w[0], w[-1]
    return first, (base[-1] if len(base) >= 2 else "")


def fem(surname: str) -> str:
    if not CYR.search(surname):
        return surname
    for a, b in (("ов", "ова"), ("ев", "ева"), ("ин", "ина"), ("ский", "ская"), ("цкий", "цкая"), ("ой", "ая")):
        if surname.endswith(a):
            return surname[: -len(a)] + b
    return surname


def gdate(d) -> dict:
    """Наша дата → дата Familio."""
    empty = {"calendar": "gregorian", "type": "equal", "first": None, "second": None}
    if not d or d.kind == "PHRASE" or not d.first:
        return empty
    cal = "julian" if d.julian else "gregorian"
    part = lambda x: x and {"year": x.y, "month": x.m or None, "day": x.d or None, "type": cal}
    t = {"": "equal", "ABT": "about", "CAL": "about", "EST": "about", "BEF": "before", "AFT": "after",
         "BET": "between", "FROM": "after", "TO": "before"}.get(d.kind, "equal")
    if t == "between":
        return {"calendar": cal, "type": t, "first": part(d.a), "second": part(d.b)}
    return {"calendar": cal, "type": t, "first": part(d.first), "second": None}


def fdate_key(fd: dict | None):
    if not fd or not fd.get("first"):
        return None
    f, s = fd["first"], fd.get("second") or {}
    return (fd.get("type"), fd.get("calendar"), f.get("year"), f.get("month"), f.get("day"), s.get("year"))


def family(T):
    me_stem = tree_conf("familio.me", "")   # от кого считать семью — ftree.toml [familio] me
    me = next((p for p in T.people.values() if p.stem == me_stem), None)
    if me is None:
        sys.exit(f"нет карточки «{me_stem}» — задайте [familio] me в ftree.toml")
    seen, st = set(), [me.id]
    while st:
        i = st.pop()
        if i in seen or i not in T.people:
            continue
        seen.add(i)
        p = T.people[i]
        st += p.father + p.mother + p.spouses + p.children
    return me.id, seen


# ---------- Familio ----------

def rels(fam: dict) -> dict:
    """uuid → {parents, children, spouses, birth, death} из событий."""
    R = {u: {"parents": [], "children": [], "spouses": [], "birth": None, "death": None, "hidden": set()}
         for u in fam["events"]}
    for u, evs in fam["events"].items():
        for e in evs if isinstance(evs, list) else []:
            allp = e.get("participants", [])
            ps = [x for x in allp if x.get("personUuid")]
            hid = [x for x in allp if not x.get("personUuid")]   # скрытые Павлом люди — без номера
            if hid:
                kind = {"wedding": "spouses"}.get(e.get("type"))
                if e.get("type") == "birth":
                    me_child = any(x["personUuid"] == u and x["role"] == "child" for x in ps)
                    kind = "parents" if me_child else "children"
                if kind:
                    R[u]["hidden"].add(kind)
            if e.get("type") == "birth" and any(x["personUuid"] == u and x["role"] == "child" for x in ps):
                R[u]["birth"] = e
                R[u]["parents"] = [x["personUuid"] for x in ps if x["role"] == "parent"]
            elif e.get("type") == "death" and any(x["personUuid"] == u for x in ps):
                R[u]["death"] = e
            elif e.get("type") == "wedding":
                R[u]["spouses"] += [x["personUuid"] for x in ps if x["personUuid"] != u]
    for u, r in R.items():
        for par in r["parents"]:
            if par in R and u not in R[par]["children"]:
                R[par]["children"].append(u)
    return R


def main(folder: Path):
    T = load()
    fam = json.loads((folder / "familio_tree.json").read_text(encoding="utf-8"))
    F = {p["uuid"]: p for p in fam["persons"]}
    R = rels(fam)
    me_ours, ours = family(T)
    P = T.people
    pm = json.loads(MAP.read_text(encoding="utf-8")) if MAP.exists() else {}
    place_uuid = {name: v["uuid"] for name, v in pm.items()}

    def fname(u):  # (имя, фамилии) Familio — из displayName «Фамилия (Девичья) Имя (…)»
        dn = F[u]["displayName"]
        sur = re.findall(r"\(([^)]*)\)", dn.split(")")[0] + ")") if dn.startswith("(") else []
        rest = re.sub(r"\([^)]*\)", " ", dn).split()
        return rest, sur

    def first_key_f(u):
        b = F[u].get("shortDisplayName") or F[u]["displayName"]
        w = re.sub(r"\([^)]*\)", " ", b).split()
        return {key(x) for x in w}

    def year_f(u):
        fd = F[u].get("birthDate") or {}
        return (fd.get("first") or {}).get("year")

    me_f = fam.get("me") or next(p["uuid"] for p in fam["persons"] if p["displayName"] in tree_conf("familio.me_names", []))
    match, rmatch = {me_ours: me_f}, {me_f: me_ours}
    if SNAP.exists():   # прошлый слепок — пары, которые ещё есть с обеих сторон
        for o, u in json.loads(SNAP.read_text(encoding="utf-8")).items():
            if o in ours and u in F and u not in rmatch and o not in match:
                match[o], rmatch[u] = u, o
    ov = folder / "overrides.json"   # пары, проверенные руками: {"<наша карточка>": "<uuid на Familio>"}
    if ov.exists():
        stem_id = {P[i].stem: i for i in ours}
        for stem, u in json.loads(ov.read_text(encoding="utf-8")).items():
            match[stem_id[stem]], rmatch[u] = u, stem_id[stem]

    def sex_ok(o, u):
        g = F[u].get("gender")
        s = "male" if P[o].sex in ("M", "male") else "female"
        return not g or g == s

    def unnamed(u):
        return not (set(re.findall(r"\w+", F[u]["displayName"])) - {"Unknown"})

    def ok(o, u, by_kin=False):
        p = P[o]
        if not sex_ok(o, u):
            return False
        y1, y2 = p.born.first_year if p.born else None, year_f(u)
        if y1 and y2 and abs(y1 - y2) > 2:
            # родня та же, имя и фамилия те же — тот же человек, год у нас другой (берём наш, в отчёт)
            f, s = names(p)
            return by_kin and key(f) in first_key_f(u) and bool(s) and key(s) in first_key_f(u)
        if by_kin and unnamed(u):
            return True          # «?» на Familio — по месту в родстве
        return key(names(p)[0]) in first_key_f(u)

    changed = True
    while changed:
        changed = False
        for o, u in list(match.items()):
            p = P[o]
            for ours_rel, f_rel in ((p.father + p.mother, R.get(u, {}).get("parents", [])),
                                    (p.children, R.get(u, {}).get("children", [])),
                                    (p.spouses, R.get(u, {}).get("spouses", []))):
                for o2 in ours_rel:
                    if o2 in match or o2 not in P:
                        continue
                    cand = [u2 for u2 in f_rel if u2 not in rmatch and ok(o2, u2)] or \
                        [u2 for u2 in f_rel if u2 not in rmatch and ok(o2, u2, by_kin=True)]
                    if len(cand) == 1:
                        match[o2], rmatch[cand[0]] = cand[0], o2
                        changed = True
    # запасной путь — имя + фамилия + год, если ответ один
    by = {}
    for u in F:
        if u not in rmatch:
            by.setdefault((frozenset(first_key_f(u))), []).append(u)
    for o in ours:
        if o in match:
            continue
        p = P[o]
        f, s = names(p)
        cand = [u for u in F if u not in rmatch and ok(o, u) and s and key(s) in first_key_f(u)]
        if len(cand) == 1:
            match[o], rmatch[cand[0]] = cand[0], o

    for _ in range(3):   # ещё раз по родству — от найденных по имени
        for o, u in list(match.items()):
            p = P[o]
            for ours_rel, f_rel in ((p.father + p.mother, R.get(u, {}).get("parents", [])),
                                    (p.children, R.get(u, {}).get("children", [])),
                                    (p.spouses, R.get(u, {}).get("spouses", []))):
                free_o = [x for x in ours_rel if x not in match and x in P]
                for o2 in free_o:
                    cand = [u2 for u2 in f_rel if u2 not in rmatch and ok(o2, u2)] or \
                        [u2 for u2 in f_rel if u2 not in rmatch and ok(o2, u2, by_kin=True)]
                    if len(cand) == 1:
                        match[o2], rmatch[cand[0]] = cand[0], o2
    ops, report = [], {"matched": len(match), "ours": len(ours), "familio": len(F)}
    tmp = {}  # наш id → временный номер нового человека в плане

    def ref(o):
        return match.get(o) or tmp.get(o)

    def place(pid):
        if not pid or pid not in T.places:
            return None
        u = place_uuid.get(T.places[pid].name)
        return {"uuid": u} if u else None

    def basic(o):
        p = P[o]
        f, s = names(p)
        b = {"firstName": f, "lastName": s, "middleName": "", "birthFirstName": "", "birthLastName": "",
             "gender": "male" if p.sex in ("M", "male") else "female", "privacy": "visible_for_all"}
        stem_s = re.sub(r"\s*\(.*?\)\s*|№\d+", " ", p.stem).split()
        stem_s = stem_s[-1] if len(stem_s) >= 2 else ""
        if b["gender"] == "male" and stem_s and s and key(stem_s) != key(s):
            b["birthLastName"] = stem_s      # сменил фамилию (Иван Дубняк → Ясенев, по жене)
        if b["gender"] == "female" and p.spouses:
            # фамилия мужа — только из нормальной карточки «Имя Фамилия» (не «Муж Анны Ясеневой»)
            hs = [names(P[h])[1] for h in p.spouses if h in P and re.fullmatch(r"\S+ \S+( \(.*\))?", P[h].stem)
                  and not re.search(r"(ой|ей|I\d+)$", names(P[h])[1])]
            hs = [fem(x) for x in hs if x and norm(x) != norm(s)]
            if hs:
                b["birthLastName"], b["lastName"] = s, hs[-1]
        return b

    fam_surnames = {key(names(P[i])[1]) for i in ours if names(P[i])[1]}
    # 1. новые люди (с настоящим именем); родственник, который может быть скрытым на Familio, — не создаём
    maybe_hidden = set()
    for o, u in match.items():
        h = R.get(u, {}).get("hidden", set())
        p = P[o]
        for kind, lst in (("parents", p.father + p.mother), ("children", p.children), ("spouses", p.spouses)):
            if kind in h:
                maybe_hidden |= {x for x in lst if x not in match}
    report["maybe_hidden"] = sorted(P[o].stem for o in maybe_hidden)
    # имена, которые у нас стоят именем при фамилии: одно такое слово в карточке — человек без фамилии («Роман (отец …)»),
    # его создаём с одним именем (решение Павла 25.10.2026), а не считаем заглушкой-фамилией
    first_names = {key(names(P[x])[0]) for x in ours if names(P[x])[0] and names(P[x])[1]}
    for o in sorted(ours):
        if o in match or o in maybe_hidden:
            continue
        p = P[o]
        f, s = names(p)
        if not f or f.lower() == "unknown":
            continue
        base = re.sub(r"\s*\(.*?\)\s*", " ", p.stem).replace("№2", "").split()
        unnamed_child = False
        note = (re.search(r"\((.*)\)", p.stem) or [None, ""])[1]
        # фамилия-заглушка: «Jasieniew (отец Witold Jasieniew)» — слово повторяется в скобках фамилией; «Прокоп (отец Агаты Прокоповой)» —
        # нет, это имя (человек без фамилии, создаём с одним именем — решение Павла 25.10.2026)
        surname_like = key(base[0]) not in first_names and (not note or re.search(rf"\b{re.escape(base[0])}\b", note))
        if len(base) == 1 and not s and key(base[0]) in fam_surnames and surname_like:   # «Jasieniew», «Wierzbowska» — только фамилия
            if not re.search(r"\((сын|дочь) ", p.stem) and not (not note and (p.father or p.mother)):   # «Ясенева» — дочь без имени
                report.setdefault("placeholders", []).append(p.stem)
                continue
            unnamed_child = True                                          # «Ясенев (сын Анны…, 1880)»
        tmp[o] = f"new:{o}"
        b0 = basic(o)
        if unnamed_child:
            b0.update(firstName="?", lastName=base[0])
        if b0["birthLastName"] and key(b0["birthLastName"]) == key(b0["lastName"] or "-"):
            b0["birthLastName"] = ""
        if base[0] in ("Муж", "Сын", "Дочь", "Жена"):   # «Муж Анны Ясеневой» — человек есть, имени нет
            b0.update(firstName="?", lastName="")
        for k in ("lastName", "birthLastName"):
            if re.fullmatch(r"I\d+", b0[k] or ""):
                b0[k] = ""
        ops.append({"op": "create", "id": tmp[o], "who": p.stem, "basic": b0})
    # 2. имена, рождение (дата, место, родители), смерть, браки
    for o in sorted(ours):
        u = ref(o)
        if not u:
            continue
        p = P[o]
        if u in F:
            fb = fam.get("basic", {}).get(u)
            want = basic(o)
            rest, sur = fname(u)
            cur_first = rest[-1] if rest else ""
            if fb:
                want["middleName"] = fb.get("middleName") or ""
                if not want["birthLastName"] and fb.get("birthLastName"):
                    want["birthLastName"] = fb["birthLastName"]
                if want["gender"] == "female" and not p.spouses and fb.get("lastName") and norm(fb["lastName"]) != norm(want["lastName"]):
                    pass
                if want["firstName"] and key(want["firstName"]) in (key(want["lastName"] or "-"), key(fb.get("lastName") or "-")):
                    want["firstName"] = fb.get("firstName") or ""   # у нас только фамилия («Uss») — имя не трогаем
                if want["gender"] == "female" and (fb.get("lastName") or "") and want["birthLastName"]:
                    want["lastName"] = fb["lastName"]   # фамилия по мужу уже есть на Familio — не трогаем
                for k in ("firstName", "lastName", "birthLastName"):
                    old_v, new_v = fb.get(k) or "", want.get(k) or ""
                    if (not new_v or re.fullmatch(r"I\d+|Unknown|\?", new_v)            # у нас имени нет
                            or (old_v and (key(old_v) == key(new_v) or norm(new_v) in norm(old_v)))):  # то же, иначе записано
                        want[k] = old_v
                if want["lastName"] and key(want["lastName"]) == key(want["birthLastName"] or fb.get("birthLastName") or ""):
                    want["lastName"] = fb.get("lastName") or ""   # «Ясенев (Jasieniew)» — та же фамилия дважды не нужна
                if want["birthLastName"] and key(want["birthLastName"]) == key(want["lastName"] or "-"):
                    want["birthLastName"] = fb.get("birthLastName") or ""
                diff = {k: (fb.get(k), v) for k, v in want.items() if k != "privacy" and (fb.get(k) or "") != (v or "")}
                if diff:
                    ops.append({"op": "basic", "uuid": u, "who": p.stem, "basic": want, "diff": diff})
        parents = [ref(x) for x in p.father + p.mother if ref(x)]
        cur = R.get(u, {})
        fb_birth = (cur.get("birth") or {})
        want_date = gdate(p.born)
        if not p.born and fb_birth.get("date"):
            want_date = {k: fb_birth["date"].get(k) for k in ("calendar", "type", "first", "second")}
        want_place = place(p.birth_place) or ((fb_birth.get("settlement") or {}).get("uuid") and {"uuid": fb_birth["settlement"]["uuid"]})
        cur_par = set(cur.get("parents", []))
        # родители на Familio, которых у нас нет, — оставляем (не удаляем связь, если у нас нет своего отца/матери)
        have = {"male" if P[x].sex in ("M", "male") else "female" for x in p.father + p.mother if ref(x)}
        keep = [x for x in cur_par if x not in rmatch and F.get(x, {}).get("gender") not in have]
        par_all = sorted(set(parents) | set(keep))
        need = (u not in F or fdate_key(fb_birth.get("date")) != fdate_key(want_date) or set(par_all) != cur_par
                or ((fb_birth.get("settlement") or {}).get("uuid") != (want_place or {}).get("uuid")))
        if need:
            ops.append({"op": "birth", "uuid": u, "who": p.stem, "date": want_date, "settlement": want_place,
                        "parents": par_all})
        if p.died or p.death_place:
            fd = cur.get("death") or {}
            wd, wp = gdate(p.died), place(p.death_place) or ((fd.get("settlement") or {}).get("uuid") and {"uuid": fd["settlement"]["uuid"]})
            if not p.died and fd.get("date"):
                wd = {k: fd["date"].get(k) for k in ("calendar", "type", "first", "second")}
            if fdate_key(fd.get("date")) != fdate_key(wd) or (fd.get("settlement") or {}).get("uuid") != (wp or {}).get("uuid") or not fd:
                ops.append({"op": "death", "uuid": u, "who": p.stem, "date": wd, "settlement": wp})
        for h in p.spouses:
            v = ref(h)
            if v and o < h and v not in cur.get("spouses", []):
                ops.append({"op": "wedding", "a": u, "b": v, "who": f"{p.stem} + {P[h].stem}"})
    report["year_conflicts"] = sorted(f"{P[o].stem}: у нас {P[o].born.first_year}, на Familio {year_f(u)}"
                                      for o, u in match.items() if P[o].born and year_f(u)
                                      and abs(P[o].born.first_year - year_f(u)) > 2)
    report["extra_on_familio"] = sorted(F[u]["displayName"] for u in F if u not in rmatch)
    report["ops"] = {k: sum(1 for x in ops if x["op"] == k) for k in ("create", "basic", "birth", "death", "wedding")}
    if "--save-snapshot" in sys.argv:
        SNAP.write_text(json.dumps(dict(sorted(match.items())), ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
        print("слепок:", SNAP, len(match))
    (folder / "plan.json").write_text(json.dumps({"owner": OWNER, "ops": ops, "report": report}, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "extra_on_familio"}, ensure_ascii=False))
    print("лишние на Familio:", len(report["extra_on_familio"]))


def _pdate(d) -> str:
    """Дата Familio → «тип|календарь|г.м.д|г.м.д» (формат familio_apply.js)."""
    if not d or not d.get("first"):
        return ""
    part = lambda x: "" if not x else ".".join("" if x.get(k) is None else str(x[k]) for k in ("year", "month", "day"))
    return "|".join([d.get("type") or "equal", "j" if d.get("calendar") == "julian" else "g", part(d.get("first")),
                     part(d.get("second"))])


def pack(folder: Path):
    """plan.json → plan_c.json: люди Familio — номерами в отсортированном списке uuid, места — номерами в S."""
    import hashlib
    plan = json.loads((folder / "plan.json").read_text(encoding="utf-8"))
    tree = json.loads((folder / "familio_tree.json").read_text(encoding="utf-8"))
    U = sorted(p["uuid"] for p in tree["persons"])
    idx = {u: i for i, u in enumerate(U)}
    S = []
    ref = lambda r: r if str(r).startswith("new:") else idx[r]
    def place(st):
        if not st or not st.get("uuid"):
            return -1
        if st["uuid"] not in S:
            S.append(st["uuid"])
        return S.index(st["uuid"])
    b = lambda x: [x["firstName"], x["lastName"], x.get("middleName") or "", x.get("birthFirstName") or "",
                   x.get("birthLastName") or "", "m" if x["gender"] == "male" else "f"]
    order = {"create": 0, "basic": 1, "birth": 2, "death": 3, "wedding": 4}
    # заглушки на Familio не создаём и не переименовываем в них (навык archive-familio): «?», «Первая», «Муж …», «Жена …»
    # «?» с фамилией (Wierzbowski — муж по фамилии жены) — не заглушка: человек известен по фамилии, создаём
    def stub(x):
        first, last = (x.get("firstName") or "").strip(), (x.get("lastName") or "").strip()
        if not first.strip("?"):
            return not last
        return bool(re.fullmatch(r"Первая|Первый|Муж|Жена|Неизвестн\w*", first))
    skip = {o["id"] for o in plan["ops"] if o["op"] == "create" and stub(o["basic"])}
    dropped = [o["who"] for o in plan["ops"] if (o["op"] == "create" and o["id"] in skip) or (o["op"] == "basic" and stub(o["basic"]))]
    def keep(o):
        if o["op"] == "create":
            return o["id"] not in skip
        if o["op"] == "basic":
            return not stub(o["basic"])
        if o["op"] in ("birth", "death"):
            return o["uuid"] not in skip
        if o["op"] == "wedding":
            return o["a"] not in skip and o["b"] not in skip
        return True
    ops = []
    for o in sorted(filter(keep, plan["ops"]), key=lambda o: order[o["op"]]):
        if o["op"] == "birth":
            o = {**o, "parents": [x for x in o.get("parents") or [] if x not in skip]}
        if o["op"] == "create":
            ops.append(["c", o["id"], *b(o["basic"])])
        elif o["op"] == "basic":
            ops.append(["b", ref(o["uuid"]), *b(o["basic"])])
        elif o["op"] == "birth":
            ops.append(["r", ref(o["uuid"]), _pdate(o.get("date")), place(o.get("settlement")), [ref(x) for x in o.get("parents") or []]])
        elif o["op"] == "death":
            ops.append(["d", ref(o["uuid"]), _pdate(o.get("date")), place(o.get("settlement"))])
        elif o["op"] == "wedding":
            ops.append(["w", ref(o["a"]), ref(o["b"])])
    c = {"o": plan["owner"], "uh": hashlib.sha256(",".join(U).encode()).hexdigest()[:16], "S": S, "ops": ops}
    text = json.dumps(c, ensure_ascii=False, separators=(",", ":"))
    (folder / "plan_c.json").write_text(text, encoding="utf-8")
    print(f"plan_c.json: правок {len(ops)}, мест {len(S)}, {len(text)} знаков; sha256 {hashlib.sha256(text.encode()).hexdigest()}")
    if dropped:
        print("без заглушек:", "; ".join(dropped))


def check(folder: Path):
    """Связи по слепку пар: чего на Familio не хватает и что там лишнее; заглушки «… ?» — отдельно, их не трогаем."""
    T = load()
    P = T.people
    match = json.loads(SNAP.read_text(encoding="utf-8"))
    back = {u: c for c, u in match.items()}
    F = json.loads((folder / "familio_tree.json").read_text(encoding="utf-8"))
    name = {p["uuid"]: p.get("displayName") or "" for p in F["persons"]}
    par, kids, sp, nbirth = {}, {}, {}, {}
    for u, evs in F["events"].items():
        for e in evs if isinstance(evs, list) else []:
            ps = [x for x in e.get("participants", []) if x.get("personUuid")]
            if e.get("type") == "birth":
                ch = [x["personUuid"] for x in ps if x["role"] == "child"]
                pa = [x["personUuid"] for x in ps if x["role"] == "parent"]
                if u in ch:
                    nbirth[u] = nbirth.get(u, 0) + 1
                    par.setdefault(u, set()).update(pa)
                for a in pa:
                    kids.setdefault(a, set()).update(ch)
            elif e.get("type") == "wedding" and any(x["personUuid"] == u for x in ps):
                sp.setdefault(u, set()).update(x["personUuid"] for x in ps if x["personUuid"] != u)
    stub = lambda u: name.get(u, "").rstrip().endswith("?")
    real, stubs = [], 0
    for c, u in match.items():
        p = P.get(c)
        if not p:
            continue
        if nbirth.get(u, 0) > 1:
            real.append(f"{p.stem}: событий «рождение» — {nbirth[u]}")
        for what, ours, theirs in (("родитель", p.father + p.mother, par.get(u, set())),
                                   ("ребёнок", p.children, kids.get(u, set())), ("супруг", p.spouses, sp.get(u, set()))):
            o = {match[x] for x in ours if x in match}
            for x in o - theirs:
                real.append(f"{p.stem}: на Familio нет — {what} {P[back[x]].stem}")
            for x in theirs - o:
                if stub(x):
                    stubs += 1
                else:
                    real.append(f"{p.stem}: на Familio лишний {what} — {name.get(x) or x[:8]}"
                                + (f" (у нас {P[back[x]].stem})" if x in back and back[x] in P else " (у нас нет)"))
    for line in sorted(set(real)):
        print(line)
    print(f"Связи Familio: расхождений {len(set(real))}, связей с заглушками «?» {stubs} (не трогаем)")
    return 1 if real else 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "fetch":
        fetch(Path(sys.argv[2]))
    elif len(sys.argv) >= 3 and sys.argv[1] == "plan":
        main(Path(sys.argv[2]))
    elif len(sys.argv) == 3 and sys.argv[1] == "pack":
        pack(Path(sys.argv[2]))
    elif len(sys.argv) == 3 and sys.argv[1] == "check":
        sys.exit(check(Path(sys.argv[2])))
    else:
        print(__doc__)
