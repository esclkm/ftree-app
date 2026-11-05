#!/usr/bin/env python3
"""FamilySearch одной командой — поиск в указателе, дереве, каталоге и тексте страниц без ручного кода в браузере.

Зачем. Раньше каждая сессия писала кусок JavaScript для страницы FamilySearch заново: искала, разбирала ответ,
забывала паузы и ловила отказ сайта (429). Теперь запросы идут из своей вкладки Chrome проекта (`browser_cdp.mjs`,
вход Павла остаётся в браузере: скрипт не видит ни пароля, ни cookie), ответ разбирает Python, в разговор идёт
короткая таблица. Ходим только на адреса `/service/…` и `/search/…`, которые принимают вход браузера;
«официальный» `/platform/…` без токена отвечает 401 — его не трогаем (решение Павла 04.11.2026).

    tools/py tools/scripts/familysearch.py records --surname Ясенев --given Прокоп --born 1840-1860
    tools/py tools/scripts/familysearch.py records --surname Ясенев --father Прокоп --collection all
    tools/py tools/scripts/familysearch.py records --film 007700000 --surname Ясенев   # плёнку отбирает сам скрипт
    tools/py tools/scripts/familysearch.py tree --given Иван --surname Ясенев --born 1875-1890
    tools/py tools/scripts/familysearch.py fulltext "Вербичи" --years 1880-1900
    tools/py tools/scripts/familysearch.py catalog 123456          # что в деле каталога, где, какие плёнки
    tools/py tools/scripts/familysearch.py film 007700000 --frames 1-20 --tsv /tmp/k.tsv   # кадры плёнки → id
    tools/py tools/scripts/familysearch.py frames 007700000 596-600 <папка> --name Вербичи_1893
    tools/py tools/scripts/familysearch.py record 1:1:XXXX-XXXX    # одна запись: страница записи текстом
    tools/py tools/scripts/familysearch.py limit                   # сколько запросов осталось в этот час

Лимиты сайта — встроены: один поток, пауза ≥5 с между запросами, не больше 150 запросов поиска в час на всех
сессиях (счёт в `$ARCHIVES_LOCAL/familysearch_rate.json`). После 429 — стоп 15 минут для всех.

Журнал «что искали». Перед поиском скрипт смотрит `ИСКАЛИ_журнал.tsv`: тот же запрос уже был — показывает итог
и не ищет (`--force` — всё равно). После поиска сам пишет строку (`--no-log` — не писать). Итог — с состоянием:
«нашлось N» / «пусто: указатель ответил, записей нет» / «не дошло: 429…». «Пусто» — не «нет в архиве»:
указатель покрывает не все плёнки (1882–1884 Гродно не проиндексированы) — охват проверить командой `film`.
«Не дошло» — вообще не результат, повторить позже.

Выход: 0 — готово; 1 — ошибка; 2 — неверные параметры; 3 — нет входа или стоп от сайта (401, 403, 429).
"""
import argparse
import datetime
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import paths  # noqa: E402
import searched  # noqa: E402

CDP = paths.SCRIPTS / "browser_cdp.mjs"
RATE = paths.ARCHIVES_LOCAL / "familysearch_rate.json"
GRODNO = "4166194"          # «Беларусь, Гродно. Метрические книги, 1649–1915» — коллекция по умолчанию
PAGE = 50                   # записей на страницу ответа
PAUSE = 5                   # секунд между запросами
HOURLY = 150                # запросов поиска в час (второй 429 был на ≈200-м, 08.10.2026)
STOP_AFTER_429 = 15 * 60
ORIGIN = "https://www.familysearch.org"


# ---------- лимит запросов: общий для всех сессий ----------

def rate_load(path=RATE):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"times": [], "stop_until": 0}


def rate_plan(state, want, now):
    """Сколько запросов из `want` можно сделать сейчас: (можно, почему меньше). 0 — ждать."""
    if state.get("stop_until", 0) > now:
        mins = int((state["stop_until"] - now) // 60) + 1
        return 0, f"сайт ответил 429 — пауза ещё {mins} мин."
    used = sum(1 for t in state.get("times", []) if t > now - 3600)
    left = HOURLY - used
    if left <= 0:
        return 0, f"за час уже {used} запросов из {HOURLY} — подождать"
    return min(want, left), (f"в этот час осталось {left} запросов" if left < want else "")


def rate_save(state, done_times, got_429, now, path=RATE):
    times = [t for t in state.get("times", []) if t > now - 3600] + list(done_times)
    out = {"times": times, "stop_until": now + STOP_AFTER_429 if got_429 else state.get("stop_until", 0)}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(out), encoding="utf-8")


def wait_gap(state):
    """Пауза между запросами и между запусками (вторая сессия могла спросить секунду назад)."""
    last = max(state.get("times", [0]) or [0])
    gap = last + PAUSE - time.time()
    if gap > 0:
        time.sleep(gap)


# ---------- браузер ----------

GET_SEQ = """(async()=>{const urls=%s, pause=%d, opt=%s; const sl=ms=>new Promise(r=>setTimeout(r,ms)); const out=[];
for(let i=0;i<urls.length;i++){ if(i) await sl(pause*1000); const t=Date.now()/1000; let st=0, body=null;
 try{const r=await fetch(urls[i],Object.assign({headers:{accept:'application/json'}},opt)); st=r.status;
  if(r.ok){const s=await r.text(); try{body=JSON.parse(s)}catch(e){body=null; st=-1}}}catch(e){st=-2}
 out.push({u:urls[i],t:t,status:st,body:body});
 if([401,403,429].includes(st)) break;
 if(body && %s) break; }
return JSON.stringify(out);})()"""


def on_site():
    """Своя вкладка должна стоять на www.familysearch.org: адреса в запросах — относительные."""
    r = subprocess.run(["node", str(CDP), "eval", "location.hostname"], capture_output=True, text=True, timeout=60)
    if "www.familysearch.org" not in r.stdout:
        subprocess.run(["node", str(CDP), "nav", ORIGIN + "/en/search/"], capture_output=True, text=True, timeout=90)


def browser(js, timeout):
    on_site()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "fs.json"
        r = subprocess.run(["node", str(CDP), "eval", js, "--out", str(out)], capture_output=True, text=True,
                           timeout=timeout)
        if r.returncode or not out.exists():
            sys.exit(f"браузер не ответил: {(r.stderr or r.stdout).strip()[-300:]}\n"
                     "проверить вход: node tools/scripts/browser_cdp.mjs login-check familysearch")
        data = json.loads(out.read_text(encoding="utf-8"))
        return json.loads(data) if isinstance(data, str) else data


def get_seq(urls, stop_when_short=True, post=None):
    """Запросы по одному с паузой, с учётом общего лимита. → (ответы, состояние «не дошло» или '')."""
    state = rate_load()
    now = time.time()
    n, why = rate_plan(state, len(urls), now)
    if n == 0:
        return [], "не дошло: " + why
    if why:
        print(f"  ⚠ {why}: делаю {n} из {len(urls)}")
    wait_gap(state)
    opt = json.dumps(post or {})
    stop = f"(body.entries||[]).length<{PAGE}" if stop_when_short else "false"
    res = browser(GET_SEQ % (json.dumps(urls[:n], ensure_ascii=False), PAUSE, opt, stop), 60 + (PAUSE + 10) * n)
    got_429 = any(r["status"] == 429 for r in res)
    rate_save(state, [r["t"] for r in res], got_429, time.time())
    bad = [r["status"] for r in res if r["status"] != 200]
    if bad:
        code = bad[0]
        why = {429: "429 — сайт просит паузу (стоп 15 мин для всех сессий)", 401: "401 — нет входа",
               403: "403 — закрыто для просмотра", -1: "ответ не JSON", -2: "сеть"}.get(code, f"HTTP {code}")
        return [r for r in res if r["status"] == 200], "не дошло: " + why
    return res, ""


def qs(params):
    from urllib.parse import urlencode
    return urlencode([(k, v) for k, v in params if v not in (None, "")])


def years(text):
    """«1880-1900» → ('1880', '1900'); «1892» → ('1892', '1892')."""
    if not text:
        return None, None
    m = re.fullmatch(r"\s*(\d{3,4})\s*(?:[-–]\s*(\d{3,4}))?\s*", text)
    if not m:
        sys.exit(f"годы «{text}» — нужно 1880 или 1880-1900")
    return m.group(1), m.group(2) or m.group(1)


# ---------- разбор записи указателя ----------

def _name(p):
    for n in p.get("names") or []:
        for f in n.get("nameForms") or []:
            if f.get("fullText"):
                return f["fullText"].strip()
    return "?"


def _facts(p):
    out = []
    for f in p.get("facts") or []:
        kind = f.get("type", "").split("/")[-1]
        date = (f.get("date") or {}).get("original", "")
        place = (f.get("place") or {}).get("original", "")
        out.append((kind, date, place))
    return out


KIND_RU = {"Birth": "рожд.", "Christening": "крещ.", "Baptism": "крещ.", "Death": "смерть", "Burial": "погреб.",
           "Marriage": "брак", "Residence": "жит.", "Census": "перепись"}


def parse_entry(e):
    """Одна запись указателя → словарь: кто главный, событие, родня по ролям, плёнка, кадр, ссылка."""
    g = (e.get("content") or {}).get("gedcomx") or {}
    persons = g.get("persons") or []
    if not persons:
        return None
    by_id = {p.get("id"): p for p in persons}
    main = next((p for p in persons if p.get("principal")), persons[0])
    mid = main.get("id")
    roles = {}
    for r in g.get("relationships") or []:
        a = (r.get("person1") or {}).get("resourceId")
        b = (r.get("person2") or {}).get("resourceId")
        kind = (r.get("type") or "").split("/")[-1]
        if kind == "ParentChild" and b == mid and a in by_id:
            male = "Male" in ((by_id[a].get("gender") or {}).get("type") or "")
            roles[a] = "отец" if male else "мать"
        elif kind == "ParentChild" and a == mid and b in by_id:
            roles[b] = "ребёнок"
        elif kind == "Couple" and mid in (a, b):
            roles[b if a == mid else a] = "супруг(а)"
    others = []
    for p in persons:
        if p is main:
            continue
        role = roles.get(p.get("id"), "")
        if not role:
            # родители супруга и прочие: «отец <имени>» по связи с не-главным
            for r in g.get("relationships") or []:
                if (r.get("type") or "").endswith("ParentChild") and (r.get("person1") or {}).get("resourceId") == p.get("id"):
                    child = by_id.get((r.get("person2") or {}).get("resourceId"))
                    if child is not None and child is not main:
                        male = "Male" in ((p.get("gender") or {}).get("type") or "")
                        role = ("отец " if male else "мать ") + _name(child).split()[0]
                        break
        others.append(f"{role} {_name(p)}".strip() if role else _name(p))
    facts = _facts(main)
    s = json.dumps(g, ensure_ascii=False)
    film = re.search(r'DigitalFilmNbr".{0,80}?"text": ?"(\d{9})', s) or re.search(r'FS_DIGITAL_FILM_NBR.{0,200}?"text": ?"(\d{9})', s)
    img = re.search(r"3:1:([A-Z0-9-]+)", s)
    rtype = re.search(r'"recordType": ?"http://gedcomx.org/(\w+)"', s)
    rtype = rtype.group(1) if rtype else ""
    # событие записи: факт того же вида (у брака первым идёт «рождение», вычисленное из возраста)
    kind, date, place = next((f for f in facts if f[0] == rtype), facts[0] if facts else (rtype, "", ""))
    birth = next((f[1] for f in facts if f[0] in ("Birth", "Christening", "Baptism")), "")
    return {"id": "1:1:" + e.get("id", ""), "name": _name(main), "kind": KIND_RU.get(rtype or kind, rtype or kind),
            "date": date, "place": place, "others": others, "film": film.group(1) if film else "",
            "image": img.group(1) if img else "", "sort": _sort_date(date), "born": _sort_date(birth or date),
            "copies": 1}


def norm(s):
    return (s or "").lower().replace("ё", "е")


def keep(x, given=None, born=None):
    """Свой отбор: сайт фильтры по имени и годам держит нестрого. Имя — начало имени главного; годы — рождения."""
    if given and not norm(x["name"]).startswith(norm(given).rstrip("*")):
        return False
    y1, y2 = years(born)
    if y1 and not (y1 <= x["born"] <= y2):
        return False
    return True


def merge_copies(rows):
    """Одна запись указателя бывает дважды (два прохода индексации): тот же кадр, имя и дата → одна строка."""
    out = {}
    for x in rows:
        k = (x["image"], norm(x["name"]), x["date"], x["kind"])
        if k in out:
            out[k]["copies"] += 1
        else:
            out[k] = x
    return list(out.values())


def _sort_date(text):
    m = re.search(r"(\d{4})", text or "")
    return m.group(1) if m else "9999"


def fmt_entry(r):
    who = "; ".join(r["others"])
    return (f"{r['date'] or '—'} {r['kind']} | {r['name']} | {who or '—'} | {r['place'] or '—'} | "
            f"{r['film'] or '—'} {r['image'] or ''} | {r['id']}" + (f" (×{r['copies']} в указателе)" if r.get("copies", 1) > 1 else ""))


# ---------- журнал ----------

def already(what, force):
    hits = [r for r in searched.read_log() if r["источник"] == "familysearch" and r["что"] == what
            and r["состояние"] not in searched.NOT_READ]   # «не дошло» — не ответ: искать снова можно
    if hits and not force:
        print(f"уже искали: «{what}»")
        for r in hits[-3:]:
            print(f"  {r['дата']}: {r['итог'][:150]}")
        print("повторить — с --force (указатель мог дополниться)")
        return True
    return False


def log(a, what, whom, result, state):
    if getattr(a, "no_log", False):
        return
    row = argparse.Namespace(date=None, source="familysearch", what=what, frames="-", whom=whom or "-",
                             how="familysearch.py (вкладка Chrome проекта)", result=result.replace("\t", " ")[:300],
                             report=getattr(a, "report", "") or "", state=state)
    searched.cmd_add(row)


# ---------- команды ----------

def records_params(a):
    p = []
    ex = "on" if a.exact else None
    for key, val in (("q.surname", a.surname), ("q.givenName", a.given), ("q.fatherGivenName", a.father),
                     ("q.fatherSurname", a.father_surname), ("q.motherGivenName", a.mother),
                     ("q.spouseGivenName", a.spouse), ("q.spouseSurname", a.spouse_surname)):
        if val:
            p.append((key, val))
            if ex and key in ("q.surname", "q.givenName"):
                p.append((key + ".exact", ex))
    for key, val in (("birthLikeDate", a.born), ("deathLikeDate", a.died), ("marriageLikeDate", a.married)):
        y1, y2 = years(val)
        if y1:
            p += [(f"q.{key}.from", y1), (f"q.{key}.to", y2)]
    if a.collection != "all":
        p.append(("f.collectionId", a.collection))
    only_film = a.film and not any(v for k, v in p if k.startswith("q."))
    if only_film:   # фильтр плёнки сайт держит только один; с фамилией — молча выкидывает (31.10.2026)
        p.append(("q.filmNumber", a.film))
    for kv in a.param or []:
        k, _, v = kv.partition("=")
        p.append((k, v))
    return p


def describe(params, film=None):
    s = " ".join(f"{k.replace('q.', '')}={v}" for k, v in params if not k.endswith(".exact") and k != "count")
    return f"указатель: {s}" + (f" film={film}" if film and f"filmNumber={film}" not in s else "")


def cmd_records(a):
    if not any([a.surname, a.given, a.father, a.film, a.param]):
        sys.exit("нужно хотя бы --surname, --given, --father или --film")
    params = records_params(a)
    what = describe(params, a.film)
    if already(what, a.force):
        return 0
    base = "/service/search/hr/v2/personas?" + qs(params)
    urls = [f"{base}&count={PAGE}&offset={o}" for o in range(0, a.max, PAGE)]
    res, problem = get_seq(urls)
    total = next((r["body"].get("results") for r in res if r.get("body")), 0) or 0
    rows, seen = [], set()
    for r in res:
        for e in (r["body"] or {}).get("entries") or []:
            try:
                x = parse_entry(e)
            except Exception:   # одна испорченная запись в ответе сайта уже роняла разбор (04.11.2026)
                x = None
            if x and x["id"] not in seen and (not a.film or x["film"] == a.film.zfill(9)):
                seen.add(x["id"])
                rows.append(x)
    got = len(rows)
    if not a.loose:
        rows = [x for x in rows if keep(x, a.given, a.born)]
    rows = merge_copies(rows)
    rows.sort(key=lambda x: (x["sort"], x["name"]))
    if got != len(rows):
        print(f"  свой отбор: из {got} осталось {len(rows)} (имя, годы рождения, повторы; --loose — без отбора)")
    shown = rows if a.all_rows else rows[:a.show]
    print(f"{what}: у сайта {total}, забрано {got}, в таблице {len(rows)}" + (f", показываю {len(shown)}" if len(shown) < len(rows) else ""))
    print("дата событие | кто | родня в записи | место | плёнка кадр | запись")
    for x in shown:
        print("  " + fmt_entry(x))
    if a.tsv:
        Path(a.tsv).write_text("\n".join("\t".join([x["date"], x["kind"], x["name"], "; ".join(x["others"]), x["place"],
                                                     x["film"], x["image"], x["id"]]) for x in rows) + "\n", encoding="utf-8")
        print(f"→ {a.tsv}")
    if total > got and not problem and not a.film:
        print(f"  ещё {total - got} у сайта не забрано — сузить запрос или --max {min(total, 500)}")
    result = state_line(problem, len(rows), None if got != len(rows) else total)
    print(result)
    log(a, what, a.whom or " ".join(filter(None, [a.given, a.surname])), result,
        state_word(problem, len(rows), got, total if not a.film else None))
    return 3 if problem.startswith("не дошло") and not rows else 0


def state_word(problem, n, got=None, total=None):
    """Слово для поля «состояние» журнала (searched.STATES)."""
    if problem:
        return "закрыто" if "403" in problem else ("частично" if n else "не дошло")
    if total and got is not None and got < total:
        return "частично" if n else "пусто"   # забрали не всё, что у сайта
    return "нашлось" if n else "пусто"


def state_line(problem, n, total=None):
    if problem:
        return f"{problem}" + (f" (успели разобрать {n})" if n else "") + " — это не «нет», повторить позже"
    if n == 0:
        return "пусто: указатель ответил, записей нет — это не «нет в архиве»: охват плёнок проверить командой film"
    return f"нашлось {n}" + (f" из {total}" if total and total != n else "")


def cmd_tree(a):
    p = [("q.givenName", a.given), ("q.surname", a.surname)]
    y1, y2 = years(a.born)
    if y1:
        p += [("q.birthLikeDate.from", y1), ("q.birthLikeDate.to", y2)]
    y3, y4 = years(a.died)
    if y3:
        p += [("q.deathLikeDate.from", y3), ("q.deathLikeDate.to", y4)]
    what = "общее дерево: " + " ".join(f"{k[2:]}={v}" for k, v in p if v)
    if already(what, a.force):
        return 0
    res, problem = get_seq([f"/service/search/tree/v2/personas?{qs(p)}&count={a.max}&offset=0"])
    rows = []
    for r in res:
        for e in (r["body"] or {}).get("entries") or []:
            g = (e.get("content") or {}).get("gedcomx") or {}
            ps = g.get("persons") or []
            if not ps:
                continue
            m = next((x for x in ps if x.get("id") == e.get("id")), ps[0])
            disp = m.get("display") or {}
            b, d = disp.get("birthDate") or "", disp.get("deathDate") or ""
            if y1 and not (y1 <= _sort_date(b) <= y2):   # годы рождения сайт в дереве не держит
                continue
            full = norm(disp.get("name") or _name(m))
            if not a.loose and (norm(a.surname)[:-1] not in full or (a.given and norm(a.given)[:3] not in full)):
                continue   # сайт подмешивает созвучных (Jasinski к Ясеневу); латиницу и иные формы — с --loose
            life = f"({b or '?'} – {d or '?'})" if b or d else ""
            place = disp.get("birthPlace") or disp.get("deathPlace") or ""
            rel = []
            for x in ps:
                if x is m:
                    continue
                rel.append((x.get("display") or {}).get("name") or _name(x))
            rows.append(f"{e.get('id')} | {disp.get('name') or _name(m)} {life} | {place or '—'} | {'; '.join(rel[:6]) or '—'}")
    print(f"{what}: {len(rows)}" + ("" if a.loose else " (фамилия, имя и годы отобраны скриптом; --loose — как у сайта)"))
    for x in rows:
        print("  " + x)
    result = state_line(problem, len(rows))
    print(result)
    log(a, what, " ".join(filter(None, [a.given, a.surname])), result, state_word(problem, len(rows)))
    return 0


def cmd_fulltext(a):
    p = [("count", str(min(a.max, 100))), ("offset", "0"), ("m.defaultFacets", "on"), ("m.queryRequireDefault", "on"),
         ("q.text", a.text)]
    if a.place:
        p.append(("q.recordPlace", a.place))
    y1, y2 = years(a.years)
    if y1:
        p += [("q.recordYear.from", y1), ("q.recordYear.to", y2)]
    if a.collection:
        p.append(("q.collectionId", a.collection))
    what = "текст страниц: " + " ".join(f"{k[2:]}={v}" for k, v in p if k.startswith("q."))
    if already(what, a.force):
        return 0
    res, problem = get_seq([f"/service/search/fulltext/search?{qs(p)}"])
    body = res[0]["body"] if res else {}
    total = (body or {}).get("results") or 0
    rows = []
    for e in (body or {}).get("entries") or []:
        c = e.get("content") or {}
        text = re.sub(r"\s+", " ", c.get("textDocument") or "")
        i = text.lower().find(a.text.lower().strip('"').split()[0]) if a.text.strip() else -1
        snip = text[max(0, i - 80): i + 120] if i >= 0 else text[:200]
        img = re.search(r"3:1:([A-Z0-9-]+)", json.dumps(e))
        rows.append(f"{c.get('recordDate', '—')} | {c.get('recordType', '')} | {c.get('recordPlace', '—')} | "
                    f"{img.group(1) if img else '—'} | …{snip}…")
    print(f"{what}: у сайта {total}, показываю {len(rows)}")
    for x in rows:
        print("  " + x)
    result = state_line(problem, len(rows), total)
    print(result + ("; автоматическая расшифровка рукописей кириллицей почти не покрывает — пусто не значит «нет»"
                    if not rows and not problem else ""))
    log(a, what, a.text, result, state_word(problem, len(rows)))
    return 0


def cmd_catalog(a):
    res, problem = get_seq([f"/service/search/catalog/item/{a.id}"], stop_when_short=False)
    if not res:
        print(problem)
        return 3
    s = (res[0]["body"] or {}).get("source") or res[0]["body"] or {}
    t = s.get("display_title") or s.get("title") or ""
    title = "; ".join(x if isinstance(x, str) else x.get("value", "") for x in (t if isinstance(t, list) else [t]))
    if s.get("inclusive_dates"):
        title += f" ({s['inclusive_dates']})"
    subj = [x.get("text", "") for x in s.get("subject") or [] if isinstance(x, dict)]
    notes = [n.get("text", "") for n in s.get("note") or [] if isinstance(n, dict) and n.get("type") in ("SUMM", "LANG", "GENERAL")]
    print(f"каталог {a.id}: {title or '—'}")
    for x in subj:
        print(f"  место/тема: {x}")
    for x in notes[:4]:
        print(f"  {x[:300]}")
    films = film_notes(res[0]["body"])
    if films:
        print(f"  плёнок {len(films)} (DGS | номер микрофильма | что внутри | онлайн):")
        for f in films[: a.show]:
            print(f"    {f['dgs'] or '—'} | {f['film'] or '—'} | {f['text'][:120]} | {f['online']}")
        if len(films) > a.show:
            print(f"    … ещё {len(films) - a.show} (--show {len(films)})")
    return 0


def film_notes(body):
    """Список плёнок из ответа каталога или film-data: [{dgs, film, text, online}]."""
    out = []
    s = json.dumps(body or {}, ensure_ascii=False)
    try:
        j = body or {}
        groups = [c.get("data") or {} for c in j.get("catalogs") or []] or [j.get("source") or j]
        for g in groups:
            for f in g.get("film_note") or []:
                out.append({"dgs": str(f.get("digital_film_no") or f.get("dgs") or ""),
                            "film": str(f.get("film_no") or f.get("film_number") or ""),
                            "text": re.sub(r"\s+", " ", str(f.get("text") or f.get("items") or "")),
                            "online": "да" if f.get("digital_film_no") else "?"})
    except AttributeError:
        pass
    if not out:
        for dgs in dict.fromkeys(re.findall(r'"dgs"\s*:\s*"?(\d{7,9})', s)):
            out.append({"dgs": dgs, "film": "", "text": "", "online": "?"})
    return out


def film_data(dgs):
    """Кадры плёнки и её описание одним запросом (POST, как делает просмотрщик сайта)."""
    body = json.dumps({"type": "film-data", "args": {"dgsNum": dgs.zfill(9), "state": {"i": "0"}, "locale": "en"}})
    post = {"method": "POST", "headers": {"content-type": "application/json", "accept": "application/json"}, "body": body}
    res, problem = get_seq(["/search/filmdatainfo/film-data"], stop_when_short=False, post=post)
    if not res:
        sys.exit(problem)
    j = res[0]["body"] or {}
    ids = [m.group(0)[4:] for u in j.get("images") or [] if (m := re.search(r"3:1:[A-Z0-9-]+", str(u)))]
    mine = [f for f in film_notes(j) if f["dgs"].lstrip("0") == dgs.lstrip("0")]
    return ids, mine


def cmd_film(a):
    ids, mine = film_data(a.dgs)
    print(f"плёнка {a.dgs.zfill(9)}: кадров {len(ids)}")
    for f in mine:
        print(f"  что внутри: {f['text'][:300]}")
    if not mine:
        print("  описания этой плёнки в ответе нет (каталог шлёт весь фонд — сверить через catalog <id>)")
    if len(mine) > 1:
        print("  ⚠ на плёнке несколько дел — кадр-табличку в середине смотреть отдельно")
    want = searched.parse_frames(a.frames) if a.frames else set()
    if want:
        rows = [(n, ids[n - 1]) for n in sorted(want) if 0 < n <= len(ids)]
        for n, i in rows[:a.show]:
            print(f"  кадр {n}: {i}")
        if a.tsv:
            name = a.name or a.dgs.zfill(9)
            Path(a.tsv).write_text("".join(f"{i}\t{name}_к{n}__{i}\n" for n, i in rows), encoding="utf-8")
            print(f"→ {a.tsv} ({len(rows)} строк для browser_cdp.mjs fs-frames)")
    return 0


def cmd_frames(a):
    want = searched.parse_frames(a.frames)
    if not want:
        sys.exit("кадры — списком и промежутками: 9,16,18-46")
    film = a.dgs.zfill(9)
    seen = {n for r in searched.read_log() if searched.film_of(r["что"]) == film and r["состояние"] not in searched.NOT_READ
            for n in searched.parse_frames(r["кадры"])}
    have = searched.frames_on_disk(film)
    skip = (want & (seen | have)) if not a.force else set()
    if skip:
        print(f"уже читали или скачаны, пропускаю: {searched.fmt_frames(skip)} (--force — всё равно)")
    want -= skip
    if not want:
        return 0
    if len(want) > 40:
        sys.exit(f"кадров {len(want)} — за заход не больше 40 (условия сайта; не листать плёнку целиком)")
    ids, _ = film_data(film)
    rows = [(n, ids[n - 1]) for n in sorted(want) if 0 < n <= len(ids)]
    name = a.name or film
    Path(a.folder).mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False, encoding="utf-8") as f:
        f.write("".join(f"{i}\t{name}_к{n}__{i}\n" for n, i in rows))
    r = subprocess.run(["node", str(CDP), "fs-frames", a.folder, f.name], text=True)
    print(f"кадры {searched.fmt_frames([n for n, _ in rows])} → {a.folder}; после чтения — "
          f"searched.py add familysearch \"плёнка {film}\" \"{searched.fmt_frames([n for n, _ in rows])}\" …")
    return r.returncode


def cmd_record(a):
    rid = a.id if a.id.startswith("1:1:") else "1:1:" + a.id.split("1:1:")[-1]
    url = f"{ORIGIN}/ark:/61903/{rid}?lang=ru"
    state = rate_load()
    n, why = rate_plan(state, 1, time.time())
    if n == 0:
        sys.exit("не дошло: " + why)
    wait_gap(state)
    subprocess.run(["node", str(CDP), "nav", url], capture_output=True, text=True, timeout=90)
    r = subprocess.run(["node", str(CDP), "text", str(a.chars)], capture_output=True, text=True, timeout=60)
    rate_save(state, [time.time()], False, time.time())
    text = r.stdout
    for menu in ("Кладбища\n", "Cemeteries\n"):   # шапка сайта — до последнего пункта меню
        if menu in text[:1500]:
            text = text.split(menu, 1)[1]
            break
    print(text.strip())
    return r.returncode


def cmd_limit(a):
    state = rate_load()
    now = time.time()
    used = sum(1 for t in state.get("times", []) if t > now - 3600)
    print(f"за последний час запросов {used} из {HOURLY}")
    if state.get("stop_until", 0) > now:
        print(f"пауза после 429 ещё {int((state['stop_until'] - now) // 60) + 1} мин.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, log_it=True):
        p.add_argument("--force", action="store_true", help="искать, даже если журнал знает такой запрос")
        if log_it:
            p.add_argument("--no-log", action="store_true", help="не писать строку в журнал поиска")
            p.add_argument("--report", default="", help="отчёт для журнала (от <папка поиска>/)")
        p.add_argument("--show", type=int, default=60, help="сколько строк показать (60)")

    p = sub.add_parser("records", help="указатель записей (метрики и др.)")
    p.add_argument("--surname"), p.add_argument("--given"), p.add_argument("--father"), p.add_argument("--father-surname")
    p.add_argument("--mother"), p.add_argument("--spouse"), p.add_argument("--spouse-surname")
    p.add_argument("--born"), p.add_argument("--died"), p.add_argument("--married")
    p.add_argument("--collection", default=GRODNO, help=f"номер коллекции ({GRODNO} — Гродно) или all")
    p.add_argument("--film", help="только эта плёнка (DGS); с фамилией отбирает сам скрипт")
    p.add_argument("--exact", action="store_true", help="фамилия и имя без вариантов (иначе Ясенев → и Ясеневич)")
    p.add_argument("--param", action="append", help="любой другой параметр сайта: q.ключ=значение")
    p.add_argument("--max", type=int, default=100, help="сколько записей забрать (по 50 за запрос; 100)")
    p.add_argument("--all-rows", action="store_true", help="показать все строки")
    p.add_argument("--loose", action="store_true", help="без своего отбора по имени и годам (как отдаёт сайт)")
    p.add_argument("--tsv", help="сохранить все строки в файл")
    p.add_argument("--whom", help="кого искали — для журнала (по умолчанию имя и фамилия)")
    common(p)
    p.set_defaults(f=cmd_records)

    p = sub.add_parser("tree", help="общее дерево FamilySearch")
    p.add_argument("--given"), p.add_argument("--surname", required=True), p.add_argument("--born"), p.add_argument("--died")
    p.add_argument("--max", type=int, default=50)
    p.add_argument("--loose", action="store_true", help="без своего отбора по фамилии, имени и годам")
    common(p)
    p.set_defaults(f=cmd_tree)

    p = sub.add_parser("fulltext", help="поиск по автоматической расшифровке страниц")
    p.add_argument("text"), p.add_argument("--place"), p.add_argument("--years"), p.add_argument("--collection")
    p.add_argument("--max", type=int, default=20)
    common(p)
    p.set_defaults(f=cmd_fulltext)

    p = sub.add_parser("catalog", help="дело каталога: что, где, какие плёнки")
    p.add_argument("id")
    common(p, log_it=False)
    p.set_defaults(f=cmd_catalog)

    p = sub.add_parser("film", help="кадры плёнки и её описание")
    p.add_argument("dgs"), p.add_argument("--frames", help="какие кадры показать: 1-20,35")
    p.add_argument("--tsv", help="файл для browser_cdp.mjs fs-frames"), p.add_argument("--name", help="начало имени файла")
    common(p, log_it=False)
    p.set_defaults(f=cmd_film)

    p = sub.add_parser("frames", help="скачать кадры плёнки по номерам (≤40 за заход)")
    p.add_argument("dgs"), p.add_argument("frames"), p.add_argument("folder"), p.add_argument("--name")
    common(p, log_it=False)
    p.set_defaults(f=cmd_frames)

    p = sub.add_parser("record", help="одна запись: страница записи текстом")
    p.add_argument("id"), p.add_argument("--chars", type=int, default=3000)
    p.set_defaults(f=cmd_record)

    p = sub.add_parser("limit", help="сколько запросов осталось в этот час")
    p.set_defaults(f=cmd_limit)

    a = ap.parse_args(argv)
    return a.f(a)


if __name__ == "__main__":
    sys.exit(main())
