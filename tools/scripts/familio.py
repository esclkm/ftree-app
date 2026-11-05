#!/usr/bin/env python3
"""Familio (familio.org) — люди наших деревень без браузера и без ИИ.

Зачем. На Familio к каждой деревне привязаны люди: из справочников (осуждённые, солдаты, ветераны, переселенцы)
и из чужих деревьев. Листать сайт по 12 записей — долго и шумно. У сайта есть открытый запрос: все люди деревни
одним ответом, без входа (`/api/v2/persons?settlement=<uuid>`; описан в github.com/dmalch/go-familio, API.md).
Скрипт один раз выкачивает список по каждой нашей деревне в `$ARCHIVES_LOCAL/text/familio/settlements/`
(вне git: там имена тысяч чужих людей), номера деревень — в `1_sources/found/archives_online/familio/settlements.json`,
а искать потом можно сколько угодно — по скачанному, без сайта.

Команды:
    tools/py tools/scripts/familio.py places            # найти наши деревни на Familio по координатам карточек мест
    tools/py tools/scripts/familio.py places --wide     # то же для мест рождения и смерти людей на Familio (и города, и вне края)
    tools/py tools/scripts/familio.py add Заречье <uuid>  # деревня без координат — номер руками (с адреса страницы)
    tools/py tools/scripts/familio.py dump [Место ...]  # скачать людей (по одной деревне, пауза 3 с); уже скачанные — пропуск
    tools/py tools/scripts/familio.py dump --force Вербичи
    tools/py tools/scripts/familio.py grep [Фамилия ...] # искать в скачанном; без фамилий — все фамилии из карточек дерева
    tools/py tools/scripts/familio.py trees             # чужие деревья в наших деревнях: кто автор, сколько людей
    tools/py tools/scripts/familio.py search "Дубняк Иван" "Ясенев Прокоп"   # поиск сайта: фамилия точно, имя — начало
    tools/py tools/scripts/familio.py geo Ясенев Дубняк      # записи справочников по фамилии → только наши уезды

Записи из чужих деревьев — подсказка, не факт: сначала проверить по документу (CLAUDE.md, «происхождение источника»).
Вход, «Совпадения» и запись в дерево Павла требуют его сессии — этим скрипт не занимается.
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request

from paths import ARCHIVES_ONLINE, ARCHIVES_TEXT, TREE, tree_conf

API = "https://familio.org/api/v2"
OUT = ARCHIVES_TEXT / "familio" / "settlements"      # имена тысяч чужих людей — вне git (документ дерева проект/ХРАНЕНИЕ.md)
MAP = ARCHIVES_ONLINE / "familio" / "settlements.json"   # наше место → uuid деревни на Familio
PAUSE = 3.0                                                # сайт под защитой от роботов — не торопимся
SKIP_TYPES = {"house", "cemetery", "grave", "country", "region", "institution", "other", "city"}


def get(path: str, **q) -> dict:
    url = f"{API}/{path}?{urllib.parse.urlencode(q)}"
    req = urllib.request.Request(url, headers={"Accept": "application/ld+json", "User-Agent": "ftree-genealogy/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def norm(s: str) -> str:
    return s.lower().replace("ё", "е").strip()


def load_map() -> dict:
    return json.loads(MAP.read_text(encoding="utf-8")) if MAP.exists() else {}


def save_map(m: dict) -> None:
    MAP.parent.mkdir(parents=True, exist_ok=True)
    MAP.write_text(json.dumps(dict(sorted(m.items())), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def our_places(wide: bool = False) -> list[tuple[str, float, float]]:
    """Наши места с координатами. wide — места рождения и смерти: и города, и вне Польши–Смоленщины."""
    skip = SKIP_TYPES - {"city"} if wide else SKIP_TYPES
    out = []
    for p in sorted((TREE / "places").glob("*.md")):
        t = p.read_text(encoding="utf-8")
        pt = re.search(r"^place_type:\s*(\S+)", t, re.M)
        if (pt and pt.group(1) in skip) or " — " in p.stem or "·" in p.stem:
            continue
        la, lo = re.search(r"lat:\s*([\d.\-]+)", t), re.search(r"long:\s*([\d.\-]+)", t)
        if la and lo and (wide or 49 < float(la.group(1)) < 57 and 14 < float(lo.group(1)) < 40):  # от Польши до Смоленска
            out.append((p.stem, float(la.group(1)), float(lo.group(1))))
    return out


def life_places() -> set[str]:
    """Места рождения и смерти людей, которые есть на Familio (слепок familio_match.json)."""
    from cards import load
    t = load()
    on_familio = json.loads((TREE.parent / "tree_data" / "familio_match.json").read_text(encoding="utf-8"))
    return {t.places[k].name for p in t.people.values() if p.id in on_familio
            for k in (p.birth_place, p.death_place) if k in t.places}


def cmd_places(wide: bool = False) -> None:
    m = load_map()
    want = life_places() if wide else None
    for name, la, lo in our_places(wide):
        if name in m or (want is not None and name not in want):
            continue
        d, base = 0.1, norm(re.sub(r"\s*\(.*\)", "", name))
        js = get("map/settlements/points", westLng=lo - d, southLat=la - d, eastLng=lo + d, northLat=la + d,
                 title=base)
        cand = []
        for f in js.get("features", []):
            s = f["properties"]["settlement"]
            if norm(s["primaryName"]).startswith(base[:5]):
                x, y = f["geometry"]["coordinates"]
                cand.append((((x - lo) ** 2 + (y - la) ** 2) ** 0.5 * 111, s["uuid"], s["primaryName"]))
        if cand:
            km, uuid, nm = min(cand)
            m[name] = {"uuid": uuid, "familio_name": nm, "km": round(km, 1)}
            print(f"{name}: {nm} · {km:.1f} км · {uuid}")
        elif wide:
            # имя на Familio другое (латиница, старое название) — только показать ближайшие, номер — руками через add
            time.sleep(PAUSE)
            d = 0.05
            js = get("map/settlements/points", westLng=lo - d, southLat=la - d, eastLng=lo + d, northLat=la + d)
            near = sorted((((f["geometry"]["coordinates"][0] - lo) ** 2 + (f["geometry"]["coordinates"][1] - la) ** 2)
                           ** 0.5 * 111, f["properties"]["settlement"]["primaryName"], f["properties"]["settlement"]["uuid"])
                          for f in js.get("features", []))
            print(f"{name}: по имени нет; рядом — " + ("; ".join(f"{n} {k:.1f} км {u}" for k, n, u in near[:4]) or "ничего"))
        else:
            print(f"{name}: на Familio не найдено")
        save_map(m)
        time.sleep(PAUSE)


def cmd_add(name: str, uuid: str) -> None:
    m = load_map()
    m[name] = {"uuid": uuid, "familio_name": name, "km": None, "manual": True}
    save_map(m)
    print(f"{name} → {uuid}")


def cmd_dump(names: list[str], force: bool) -> None:
    m = load_map()
    OUT.mkdir(parents=True, exist_ok=True)
    for name in names or list(m):
        if name not in m:
            print(f"{name}: нет в {MAP.name} — сначала places или add")
            continue
        f = OUT / f"{name}.json"
        if f.exists() and not force:
            continue
        people, page = [], 1
        while True:
            js = get("persons", settlement=m[name]["uuid"], itemsPerPage=300, page=page)
            data = js.get("data", [])
            people += [slim(x) for x in data]
            if len(data) < 300:
                break
            page += 1
            time.sleep(PAUSE)
        f.write_text(json.dumps({"settlement": m[name], "downloaded": time.strftime("%Y-%m-%d"), "persons": people},
                                ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{name}: {len(people)} чел.")
        time.sleep(PAUSE)


def slim(p: dict) -> dict:
    """Из ответа сайта — только то, что нужно для поиска: кто, когда, откуда запись."""
    f = lambda d: (d or {}).get("formatted") if isinstance(d, dict) else d
    return {k: v for k, v in {"uuid": p.get("uuid"), "name": p.get("displayName"), "catalog": p.get("catalogKey"),
            "catalogName": p.get("catalogName"), "born": f(p.get("birthDate")), "died": f(p.get("deathDate")),
            "bornPlace": p.get("birthSettlementText") or None}.items() if v}


def tree_surnames() -> list[str]:
    s = set()
    for p in (TREE / "people").glob("*.md"):
        base = re.sub(r"\s*\(.*", "", p.stem).split()
        if len(base) >= 2 and re.fullmatch(r"[А-ЯЁ][а-яё\-]{3,}", base[-1]):
            s.add(base[-1])
    return sorted(s)


def stem(surname: str) -> str:
    """Основа фамилии без родовых окончаний: Ясенко/Ясенкова, Ясенев/Ясенева, Дубняк/Дубнякова."""
    s = norm(surname)
    for end in ("ова", "ева", "ина", "ая", "ий", "ой", "а", "о"):
        if s.endswith(end) and len(s) - len(end) >= 4:
            return s[: -len(end)]
    return s


def all_people() -> list[tuple[str, dict]]:
    out = []
    for f in sorted(OUT.glob("*.json")):
        for p in json.loads(f.read_text(encoding="utf-8"))["persons"]:
            out.append((f.stem, p))
    return out


def date(d) -> str:
    return d or ""


def cmd_grep(surnames: list[str]) -> None:
    wanted = {stem(s): s for s in (surnames or tree_surnames())}
    for place, p in all_people():
        nm = p.get("name", "")
        # фамилия — первое слово; девичья — в скобках: «Ясенева (Дубняк) Анна», «(Wierzbowska) Агата»
        words = [norm(w) for w in re.findall(r"[А-Яа-яЁё\-]+", nm.split(")")[-1])[:1] + re.findall(r"\(([^)]+)\)", nm)]
        hit = next((wanted[k] for k in wanted for w in words if w.startswith(k) and len(w) - len(k) <= 3), None)
        if hit:
            src = p.get("catalogName") or "чужое дерево"
            print(f"{hit:<14} · {place:<12} · {p['name']} · {date(p.get('born'))} · {src} · "
                  f"https://familio.org/{'catalogs/' + p['catalog'] + '/persons' if p.get('catalog') else 'persons'}/{p['uuid']}")


def cmd_trees() -> None:
    by = {}
    for place, p in all_people():
        if not p.get("catalog"):
            by.setdefault(place, []).append(p["name"])
    for place, names in sorted(by.items()):
        print(f"{place}: {len(names)} чел. из чужих деревьев — {', '.join(names[:8])}{' …' if len(names) > 8 else ''}")


def search(last: str, first: str = "", pages: int = 5) -> list[dict]:
    """Поиск людей сайта (справочники + чужие деревья) — со страницы /persons, без входа; фамилия — точно."""
    out = []
    for page in range(1, pages + 1):
        q = {"f_lastName": last, "f_lastNameExactMatch": 1, "page-persons": page}
        if first:
            q["f_firstAndMiddleName"] = first
        req = urllib.request.Request("https://familio.org/persons?" + urllib.parse.urlencode(q),
                                     headers={"User-Agent": "Mozilla/5.0 ftree-genealogy"})
        with urllib.request.urlopen(req, timeout=60) as r:
            h = r.read().decode("utf-8")
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', h, re.S)
        P = json.loads(m.group(1))["props"]["pageProps"]["initialState"]["pages"]["currentPage"]["persons"]
        out += [slim(x) | {"type": x.get("type")} for x in P.get("data", [])]
        if page * 12 >= P["pager"]["totalItems"]:
            break
        time.sleep(PAUSE)
    return out


REC = ARCHIVES_TEXT / "familio" / "records"             # страница записи справочника — текстом, один раз
# начала названий наших мест — ftree.toml [familio] our_area; нет списка — ни одна запись не «в наших местах»
OUR_AREA = re.compile(r"(?<![А-Яа-яЁё])(" + "|".join(tree_conf("familio.our_area", [])) + ")" if tree_conf("familio.our_area")
                      else r"(?!)", re.I)


def record(p: dict) -> str:
    """Текст страницы записи справочника (поля «География», «Место рождения», «Оригинальная запись»…), с кэшем."""
    REC.mkdir(parents=True, exist_ok=True)
    f = REC / f"{p['uuid']}.txt"
    if f.exists():
        return f.read_text(encoding="utf-8")
    req = urllib.request.Request(f"https://familio.org/catalogs/{p['catalog']}/persons/{p['uuid']}",
                                 headers={"User-Agent": "Mozilla/5.0 ftree-genealogy"})
    with urllib.request.urlopen(req, timeout=60) as r:
        h = r.read().decode("utf-8")
    h = re.sub(r"<script.*?</script>|<style.*?</style>", " ", h, flags=re.S)
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h))
    import html as _h
    txt = _h.unescape(txt)
    i, j = txt.find("Из справочника"), txt.find("Страницы, связанные")
    txt = txt[i:j if j > i else i + 2000].strip()
    f.write_text(txt + "\n", encoding="utf-8")
    time.sleep(PAUSE)
    return txt


def cmd_geo(surnames: list[str]) -> None:
    for s in surnames:
        last, _, first = s.partition(" ")   # «Ясенев Прокоп» — фамилия и начало имени: обходит предел 360 записей
        res = search(last, first, pages=30)
        hits = []
        for p in res:
            if not p.get("catalog"):
                continue
            try:
                txt = record(p)
            except Exception as e:   # сбой сети — пропустить, при повторе возьмётся
                print(f"   (пропуск {p['uuid']}: {type(e).__name__})")
                time.sleep(PAUSE)
                continue
            if OUR_AREA.search(txt):
                hits.append((p, txt))
        print(f"== {s}: записей {len(res)}, в наших местах {len(hits)}")
        for p, txt in hits:
            print(f"   {txt[:400]} · https://familio.org/catalogs/{p['catalog']}/persons/{p['uuid']}")


def cmd_search(queries: list[str]) -> None:
    for q in queries:
        last, _, first = q.partition(" ")
        res = search(last, first)
        print(f"== {q}: {len(res)}")
        for p in res:
            src = p.get("catalogName") or "чужое дерево"
            link = f"catalogs/{p['catalog']}/persons" if p.get("catalog") else "persons"
            print(f"   {p['name']} · {p.get('born', '')}–{p.get('died', '')} · {p.get('bornPlace', '')} · {src} · "
                  f"https://familio.org/{link}/{p['uuid']}")
        time.sleep(PAUSE)


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
    elif a[0] == "places":
        cmd_places("--wide" in a)
    elif a[0] == "add" and len(a) == 3:
        cmd_add(a[1], a[2])
    elif a[0] == "dump":
        cmd_dump([x for x in a[1:] if x != "--force"], "--force" in a)
    elif a[0] == "grep":
        cmd_grep(a[1:])
    elif a[0] == "trees":
        cmd_trees()
    elif a[0] == "search":
        cmd_search(a[1:])
    elif a[0] == "geo":
        cmd_geo(a[1:])
    else:
        print(__doc__)
