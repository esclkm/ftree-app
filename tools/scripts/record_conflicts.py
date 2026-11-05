#!/usr/bin/env python3
"""Противоречия между архивными записями — метриками ГАСО (Смоленск) и плёнками FamilySearch.

Зачем. Одна семья встречается в книгах много раз: венчание, потом крещение каждого ребёнка, смерть, перепись. Священники
писали по-разному, а машина и модель ещё и читают почерк с ошибками. Поэтому мать в 1906 году — «Агата Прокопова», в 1912 —
«Агата Прокофьева»; невеста на венчании — «Ирина Савина», а в записи о сыне — «Ирина Савкина»; умершему «57 лет»,
а по записи о крещении выходит 49. Каждое такое место — либо ошибка прочтения (смотреть скан), либо две разные семьи
с одинаковыми именами (тёзки), либо вторая жена. Глазами по 700 записям этого не увидеть.

Два шага:
  1. parse — каждую запись из точных прочтений (`прочтения.json`, навык metric-search) модель ОДИН раз раскладывает по
     полям: кто родился / венчался / умер, отец и мать с отчествами, деревня, сословие, возраст. Через Copilot
     (`llm.py`, свой лимит, подписку Claude не тратит), с кэшем; разобранное не трогается.
  2. check — сверка без ИИ: группирует записи в семьи и сравнивает.
     · мать в записях о детях одного отца: другое имя — вторая жена или тёзки; другое отчество — прочтение или ошибка;
     · невеста на венчании ↔ мать в записях о детях этой пары: отчество, деревня;
     · возраст при венчании и при смерти ↔ запись о крещении того же человека (годы — по годам дела, с запасом).
Запись о самом человеке из дерева тут не нужна: сравниваются записи между собой. Решает Павел по сканам
(`metric_review.py serve`): в отчёте у каждой записи — дело, разворот и номер.

Разбор лежит рядом с прочтениями (`$ARCHIVES_LOCAL/text/gaso/записи_по_полям.json`) — там имена, в git не идёт.

  tools/py tools/scripts/record_conflicts.py parse --limit 24            # сначала проба на двух пачках
  tools/py tools/scripts/record_conflicts.py parse                       # всё, что ещё не разобрано
  tools/py tools/scripts/record_conflicts.py check      # отчёт — $ARCHIVES_LOCAL/text/gaso/противоречия_записей.md
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm  # noqa: E402
import metric_filter as mf  # noqa: E402
import name_forms as nf  # noqa: E402
import paths  # noqa: E402

READS = mf.TEXT / "прочтения.json"
PARSED = mf.TEXT / "записи_по_полям.json"
CATALOG = paths.ARCHIVES_CATALOG
MODEL = "copilot:claude-sonnet-5.5"
BATCH = 12
AGE_SLACK = 3   # священник писал возраст на глаз: ±3 года — не расхождение

# Подсказка модели; дерево может дать свою, с примерами из своих книг (ftree.toml, [record_conflicts] system)
SYSTEM = """Ты разбираешь уже прочитанные записи русских православных метрических книг XIX — начала XX века.
Текст записи дан как есть, в старой орфографии, с пометками [?] и [нрзб]. Переведи в современное написание и разложи по
полям. Ничего не додумывай: чего нет в тексте — null. Сомнительное (было [?] или буквы не видны) — в конце значения «?».
Отчество верни ИМЕНЕМ ОТЦА в именительном падеже: «Прокоповъ» → «Прокоп», «Сергеева» → «Сергей», «Петрова» → «Пётр».
Имена — как в записи, только современными буквами (Іоаннъ → Иоанн, Сергій → Сергий), не заменяй на бытовые.
Деревня — в именительном падеже, как понял («деревни Вербичей» → «Вербичи»). Ответ — только JSON-массив, без пояснений."""
SYSTEM = paths.tree_conf("record_conflicts.system", SYSTEM)

PROMPT = """Для каждой записи верни объект:
{"id": "<id как дан>", "part": "рождение|брак|смерть|не понять", "year": число или null (только если год виден в тексте),
 "village": "...", "estate": "крестьянин|мещанин|солдат|шляхтич|дворянин|...",
 "child": {"given": "...", "sex": "M|F"},                       // рождение
 "father": {"given": "...", "father": "...", "surname": "..."}, // рождение: отец ребёнка
 "mother": {"given": "...", "father": "...", "surname": "..."}, // рождение: мать ребёнка
 "groom": {"given": "...", "father": "...", "surname": "...", "age": число, "village": "...", "marriage": 1|2|3},
 "bride": {"given": "...", "father": "...", "surname": "...", "age": число, "village": "...", "marriage": 1|2|3},
 "deceased": {"given": "...", "father": "...", "surname": "...", "age": число, "sex": "M|F",
              "parent": "кто он кому, если сказано: «сын крестьянина Ивана Петрова» → {\\"given\\":\\"Иван\\",\\"father\\":\\"Петр\\"}"}}
Поля, которых нет в записи, не пиши. Записи:
"""


# ─── Шаг 1: разбор ──────────────────────────────────────────────────────────────────────────

def records():
    """Все записи из точных прочтений: id «дело:разворот:высота#i» → запись как прочитана."""
    out = {}
    for k, v in json.loads(READS.read_text(encoding="utf-8")).items():
        for i, r in enumerate(v.get("records", [])):
            if r.get("part") != "не понять" and (r.get("main") or r.get("people")):
                out[f"{k}#{i}"] = r
    return out


def load_parsed():
    return json.loads(PARSED.read_text(encoding="utf-8")) if PARSED.exists() else {}


def parse(args):
    todo = {k: r for k, r in records().items() if k not in (done := load_parsed())}
    keys = sorted(todo)[: args.limit] if args.limit else sorted(todo)
    print(f"Записей: {len(records())}, разобрано: {len(done)}, сейчас: {len(keys)} ({args.model})")
    for i in range(0, len(keys), BATCH):
        part = keys[i:i + BATCH]
        body = "\n".join(json.dumps({"id": k, **{f: todo[k].get(f) for f in ("part", "number", "date", "main", "people",
                                                                              "witnesses")}}, ensure_ascii=False)
                         for k in part)
        try:
            text = llm.ask("record_conflicts", PROMPT + body, SYSTEM, model=args.model)
        except llm.Limit as e:
            print(f"Стоп: {e}")
            break
        m = re.search(r"\[.*\]", text, re.S)
        try:
            got = {x["id"]: x for x in json.loads(m[0])} if m else {}
        except (json.JSONDecodeError, KeyError, TypeError):
            got = {}
        done = load_parsed()
        done.update({k: got[k] for k in part if k in got})
        PARSED.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  пачка {i // BATCH + 1}: разобрано {sum(k in got for k in part)} из {len(part)}")
    return 0


# ─── Шаг 2: сверка ──────────────────────────────────────────────────────────────────────────

def clean(s):
    return re.sub(r"[?\s]+$", "", str(s or "")).strip().lower().replace("ё", "е")


def canon(name):
    """Одно имя во всех формах — один ключ: Иоанн = Иван = Ян."""
    n = clean(name)
    return min(nf.forms(n)) if n else ""


def doubtful(*vals):
    return any(str(v or "").rstrip().endswith("?") for v in vals)


def dist(a, b):
    """Сколько букв поменять, чтобы из a вышло b (Левенштейн)."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def same(a, b):
    """'да' — одно имя; 'похоже' — отличается 1–3 буквами (скорее прочтение); 'нет' — разные; '' — сравнить не с чем."""
    if not clean(a) or not clean(b):
        return ""
    if canon(a) == canon(b):
        return "да"
    x, y = clean(a), clean(b)
    return "похоже" if dist(x, y) <= max(1, min(3, len(min(x, y, key=len)) // 3)) else "нет"


def village_key(v):
    return clean(v)[:4]


def book_years(book):
    """Годы дела по описи: «Покровская церковь, МК 1906–1911» → (1906, 1911); одна дата → (1858, 1858)."""
    for f in CATALOG.glob(f"*/{book}.book.json"):
        ys = [int(y) for y in re.findall(r"(?<!\d)(18\d\d|19[01]\d)(?!\d)", json.loads(f.read_text())["title"])]
        if ys:
            return min(ys), max(ys)
    return None


def where(rid, r):
    book, n, _ = rid.split("#")[0].split(":")
    yrs = book_years(book)
    num = f", № {r['number']}" if r.get("number") else ""
    return f"{book}, разворот {n}{num}" + (f" ({yrs[0]}–{yrs[1]})" if yrs and yrs[0] != yrs[1] else
                                            f" ({yrs[0]})" if yrs else "")


def person(p):
    """«Агата (отец — Прокоп) Ясенева»: отчество как имя отца — так видно, что именно сравниваем."""
    p = p or {}
    s = p.get("given") or "?"
    if p.get("father"):
        s += f" (отец — {p['father']})"
    if p.get("surname"):
        s += f" {p['surname']}"
    return s


def child(r):
    return (r.get("child") or {}).get("given") or "имя не прочитано"


def families(parsed):
    """Записи о рождении → семьи по отцу (имя + имя его отца) и деревне."""
    fam = {}
    for rid, r in parsed.items():
        if r.get("part") != "рождение" or not (r.get("father") or {}).get("given"):
            continue
        f = r["father"]
        k = (canon(f["given"]), canon(f.get("father")), village_key(r.get("village")))
        fam.setdefault(k, []).append((rid, r))
    return fam


def check_mothers(fam):
    """Одна семья — один пункт: все записи о детях и чем различаются матери."""
    out = []
    for (fg, ff, v), recs in fam.items():
        if len(recs) < 2 or not ff:
            continue
        moms = [r.get("mother") or {} for _, r in recs]
        names = {canon(m.get("given")) for m in moms if clean(m.get("given"))}
        pairs = [(same(a.get("given"), b.get("given")), same(a.get("father"), b.get("father")))
                 for i, a in enumerate(moms) for b in moms[i + 1:]]
        if not any("нет" in pr or "похоже" in pr for pr in pairs):
            continue
        if len(names) > 1 and any(g == "нет" for g, _ in pairs):
            what = "мать — другое имя: вторая жена, тёзки-соседи или ошибка прочтения"
        elif all(g != "похоже" and p != "похоже" for g, p in pairs):
            what = "отчество матери разное: ошибка священника или другая женщина"
        else:
            what = "мать пишется по-разному: похоже на ошибку прочтения — смотреть сканы"
        doubt = doubtful(*[m.get(f) for m in moms for f in ("given", "father")])
        out.append(("Мать в записях о детях одного отца", what, doubt,
                    [(rid, r, f"отец {person(r['father'])}, д. {r.get('village')}; ребёнок {child(r)}; "
                              f"мать — **{person(r.get('mother'))}**") for rid, r in recs]))
    return out


def check_weddings(parsed, fam):
    """Невеста на венчании ↔ мать в записях о детях пары (жених = отец ребёнка, имя невесты = имя матери)."""
    out = []
    for rid, r in parsed.items():
        if r.get("part") != "брак":
            continue
        g, b = r.get("groom") or {}, r.get("bride") or {}
        if not g.get("given") or not g.get("father") or not b.get("given"):
            continue
        for (fg, ff, v), recs in fam.items():
            if fg != canon(g["given"]) or ff != canon(g["father"]):
                continue
            if v and village_key(g.get("village") or r.get("village")) and v != village_key(g.get("village") or
                                                                                       r.get("village")):
                continue
            for rid2, r2 in recs:
                m = r2.get("mother") or {}
                if same(m.get("given"), b["given"]) != "да":
                    continue
                p = same(m.get("father"), b.get("father"))
                if p in ("нет", "похоже"):
                    out.append(("Невеста на венчании ↔ мать в записи о ребёнке",
                                "отчество невесты и матери разное" + (": похоже на ошибку прочтения" if p == "похоже"
                                                                       else ": другая женщина или ошибка"),
                                doubtful(m.get("father"), b.get("father")),
                                [(rid, r, f"венчание: {person(g)} и {person(b)}"),
                                 (rid2, r2, f"ребёнок {child(r2)}: отец {person(r2['father'])}"
                                            f", мать — {person(m)}")]))
    return out


def check_ages(parsed):
    """Возраст при венчании и при смерти ↔ крещение того же человека: имя + имя отца + деревня."""
    births = {}
    for rid, r in parsed.items():
        if r.get("part") == "рождение" and (r.get("child") or {}).get("given") and (r.get("father") or {}).get("given"):
            k = (canon(r["child"]["given"]), canon(r["father"]["given"]), village_key(r.get("village")))
            births.setdefault(k, []).append((rid, r))
    out = []
    for rid, r in parsed.items():
        people = [r.get("deceased")] if r.get("part") == "смерть" else \
            [r.get("groom"), r.get("bride")] if r.get("part") == "брак" else []
        for p in filter(None, people):
            if not p.get("age") or not p.get("given") or not p.get("father"):
                continue
            k = (canon(p["given"]), canon(p["father"]), village_key(p.get("village") or r.get("village")))
            for rid2, r2 in births.get(k, []):
                s1, s2 = clean(p.get("surname")), clean((r2.get("father") or {}).get("surname"))
                if s1 and s2 and same(s1, s2) == "нет":
                    continue   # Елена Яцевич ≠ Елена Одинцкая: фамилии разные — другой человек
                y_event, y_birth = book_years(rid.split(":")[0]), book_years(rid2.split(":")[0])
                if not y_event or not y_birth:
                    continue
                lo, hi = y_event[0] - y_birth[1] - 1, y_event[1] - y_birth[0]
                age = int(re.sub(r"\D", "", str(p["age"])) or 0)
                if not age or lo - AGE_SLACK <= age <= hi + AGE_SLACK:
                    continue
                if age < 1 or y_birth[0] > y_event[1]:
                    continue
                out.append(("Возраст ↔ запись о крещении",
                            f"по записи {age} лет, по годам дел выходит {max(lo, 0)}–{hi}: тёзка или ошибка возраста",
                            doubtful(p["given"], p["father"]),
                            [(rid, r, f"{r['part']}: {person(p)}, {age} лет"),
                             (rid2, r2, f"рождение: {r2['child']['given']}, отец {person(r2['father'])}, "
                                        f"д. {r2.get('village')}")]))
    return out


_CARDS = None


def in_tree(*people):
    """Карточки дерева, где человек упомянут как в книге: «Иван Прокопов» (все формы имени и «фамилии по отцу»)."""
    global _CARDS
    if _CARDS is None:
        _CARDS = {f.stem: re.sub(r"[ъ\[\]?*«»]", "", f.read_text(encoding="utf-8").lower().replace("ё", "е"))
                  for f in (paths.TREE / "people").glob("*.md")}
    hits = []
    for p in people:
        p = p or {}
        if not clean(p.get("given")) or not clean(p.get("father")):
            continue
        pats = [f"{g} {pt}" for g in nf.forms(clean(p["given"])) for pt in nf.patronymic_surnames(clean(p["father"]))]
        pats = [x[:-2] if x.endswith(("ов", "ев", "ин")) else x for x in pats]   # и «Прокопова», «Прокоповна»
        hits += [stem for stem, body in _CARDS.items() if any(x in body for x in pats)]
    return list(dict.fromkeys(hits))


def check(args):
    parsed = load_parsed()
    if not parsed:
        print("Разбора нет — сначала: record_conflicts.py parse")
        return 1
    reads = records()
    fam = families(parsed)
    found = check_mothers(fam) + check_weddings(parsed, fam) + check_ages(parsed)

    def tree_of(item):
        return in_tree(*[r.get(k) for _, r, _ in item[3] for k in ("father", "groom", "deceased")])
    lines = [f"# Противоречия между архивными записями",
             "",
             f"Записей прочитано: {len(reads)}, разобрано по полям: {len(parsed)}; семей по записям о рождении: "
             f"{len(fam)} (с двумя и больше детьми: {sum(len(v) > 1 for v in fam.values())}). "
             f"Противоречий: {len(found)}. «?» — в одном из имён сомнение уже при чтении.", ""]
    for kind in dict.fromkeys(k for k, *_ in found):
        lines.append(f"## {kind}\n")
        items = [x for x in found if x[0] == kind]
        items.sort(key=lambda x: not tree_of(x))
        for item in items:
            _, what, doubt, recs = item
            hits = tree_of(item)
            lines.append(f"- **{what}**" + (" · ?" if doubt else "") +
                         (f" · ⭐ упомянут в карточках: {', '.join(f'[[{h}]]' for h in hits[:4])}" if hits else ""))
            for rid, r, desc in recs:
                lines.append(f"  - {desc} — *{where(rid, reads.get(rid, r))}*")
        lines.append("")
    text = "\n".join(lines)
    if args.md:
        Path(args.md).write_text(text, encoding="utf-8")
        print("\n".join(lines[:3]) + f"\nОтчёт: {args.md}")
    else:
        print(text)
    return 1 if found else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("parse")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--model", default=MODEL)
    c = sub.add_parser("check")
    c.add_argument("--md", default=str(mf.TEXT / "противоречия_записей.md"), help="куда отчёт (с именами — вне git)")
    a = ap.parse_args()
    return parse(a) if a.cmd == "parse" else check(a)


if __name__ == "__main__":
    sys.exit(main())
