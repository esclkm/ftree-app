#!/usr/bin/env python3
"""Эталон для распознавания метрик (схема — документ дерева проект/МЕТРИКИ_СХЕМА.md): ~20 страниц, размеченных и проверенных Павлом.

Зачем: чтобы честно сравнить модели (4b, 4c), нужны страницы, где правильный ответ известен. Эталон — это он.

    tools/py tools/scripts/etalon.py pick              # выбрать страницы: печатные шапки читает macOS Vision, без ИИ
    tools/py tools/scripts/etalon.py premark --model sonnet   # черновик моделью (только по решению Павла: --model обязателен)
    tools/py tools/scripts/etalon.py scribe            # задание для Scribe AI (MyHeritage) и разбор его ответов по полям
    tools/py tools/scripts/etalon.py serve             # локальная страница: скан слева, разметка справа, «сохранить»
    tools/py tools/scripts/etalon.py status            # сколько выбрано, размечено, проверено

Как выбираем. У каждого дела берём равномерно ~16 разворотов (у дела с исповедной ведомостью — больше), Vision читает
печатную шапку бланка: «часть первая о родившихся», «о бракосочетавшихся», «об умерших», «исповедная», год. По шапке —
тип книги и часть; дальше по 3–4 страницы на тип, из разных дел и лет (разные руки). Номер файла — не номер листа.

Где что лежит. Паспорта типов книг — 3_research/archives/book_types.md (git, без имён). Всё с именами чужих людей —
только на этом Mac: $ARCHIVES_LOCAL/text/etalon/ — pages.json (выбор), draft/<id>.json (предразметка
модели), checked/<id>.json (проверено Павлом — это и есть эталон).
"""
import argparse
import datetime as dt
import http.server
import json
import random
import re
import subprocess
import sys
import urllib.parse
from collections import Counter, defaultdict
from pathlib import Path

import llm
import paths
from paths import ARCHIVES_TEXT, GASO_RAW, ROOT

CATALOG = paths.ARCHIVES_CATALOG / "gaso"
FS_CATALOG = CATALOG.parent / "familysearch"     # плёнки FamilySearch, разложенные как книги (fs_<плёнка>)
OUT = ARCHIVES_TEXT / "etalon"
PAGES = OUT / "pages.json"
DRAFT = OUT / "draft"
CHECKED = OUT / "checked"
SCRIBE = OUT / "scribe"      # <id>.txt — ответ Scribe AI слово в слово (кладёт сессия с помощником MyHeritage)
VISION_SRC = paths.SCRIPTS / "gaso_vision.swift"
VISION_BIN = paths.CACHE / "etalon" / "vision"
OCR_CACHE = paths.CACHE / "etalon" / "ocr"         # текст Vision — тоже с именами, вне git

# Исповедная ведомость — только по своей шапке («Число / Лета / Показания действия»): в бланке «умерших» тоже есть
# графа «кто исповедовал», по одному слову «исповед» их не различить.
CONFESSION = r"показан|исповедн\w*\s+ведом"
SECTION_WORDS = (("births", r"родивш|родивщ|о\s*родив"),
                 ("marriages", r"брак[оа]соч|ракосоч|кракосоч|пракосоч|бракос"), ("deaths", r"умерш|умерщ|об\s*умер"))
SECTION_RU = {"births": "рождения", "marriages": "браки", "deaths": "смерти", "confession": "исповедная ведомость",
              "other": "другое (обложка, оглавление, справка)"}
KIND_RU = {"church": "церковный экземпляр МК", "consistory": "консисторский экземпляр МК",
           "confession": "исповедная ведомость"}
# Сколько страниц эталона на (тип книги, часть): итого 20
QUOTA = {("church", "births"): 4, ("church", "marriages"): 3, ("church", "deaths"): 3,
         ("consistory", "births"): 3, ("consistory", "marriages"): 2, ("consistory", "deaths"): 2,
         ("confession", "confession"): 3}

SYSTEM = ("Ты помогаешь разметить скан страницы русской церковной книги XIX – начала XX века. Пишешь только то, что "
          "видишь. Нечитаемое — «[нрзб]», часть слова — «Ива[нрзб]». Ничего не угадываешь и не дополняешь по смыслу. "
          "Дореформенные буквы (ѣ, і, ъ) передаёшь современными. Отвечаешь только JSON, без пояснений.")

# Поля эталона — только то, что меряем в 4b/4c: номер и дата, главные люди, деревня, возраст, прочие фамилии
# (решение Павла 02.10: священник, подписи, причина смерти не нужны). Полные графы — паспорт book_types.md.
FIELDS = {
    "births": ["act", "date", "child", "parents", "village", "others"],
    "marriages": ["act", "date", "groom", "bride", "ages", "village", "others"],
    "deaths": ["act", "date", "deceased", "age", "village", "others"],
    "confession": ["household", "village", "person", "relation", "age"],
}
FIELD_RU = {"act": "№ записи", "date": "дата (рожд./крещ., венчания, смерти)", "child": "имя ребёнка",
            "parents": "родители — как написано", "groom": "жених — как написано", "bride": "невеста — как написано",
            "deceased": "умерший — как написано", "ages": "лет: жениху / невесте", "age": "лет",
            "village": "деревня (откуда)", "others": "прочие фамилии на записи (восприемники, поручители) — через запятую",
            "household": "№ двора", "person": "звание, имя, фамилия", "relation": "кем приходится главе двора"}
OLD_TO_NEW = {   # черновики и сохранённое в первой, длинной форме (до 02.10, 22:30) → новая форма
    "births": {"date": ("born", "baptized"), "others": ("godparents",)},
    "marriages": {"ages": ("groom_age", "bride_age"), "others": ("sureties",)},
    "deaths": {"date": ("died", "buried")},
    "confession": {"age": ("age_m", "age_f")},
}


def to_new_form(record: dict, section: str) -> dict:
    """Запись старой формы → новая: склеить части (рожд. / крещ.), лишние графы (священник и др.) — в примечание."""
    if all(k in FIELDS[section] or k in ("continued", "note") for k in record):
        return record
    out = {f: record.get(f, "") for f in FIELDS[section]}
    for new, old in OLD_TO_NEW.get(section, {}).items():
        parts = [str(record.get(o, "")).strip() for o in old]
        out[new] = out[new] or " / ".join(x for x in parts if x)
    used = set(FIELDS[section]) | {o for old in OLD_TO_NEW.get(section, {}).values() for o in old} | {"continued", "note"}
    extra = "; ".join(f"{FIELD_RU.get(k, k)}: {v}" for k, v in record.items() if k not in used and v)
    out["continued"] = bool(record.get("continued"))
    out["note"] = " · ".join(x for x in (record.get("note", ""), extra) if x)
    return out


PAGE_FIELDS = ["year", "month", "folio", "hands_note"]


def normalize(text: str) -> str:
    text = text.lower()
    for a, b in (("є", "е"), ("ѣ", "е"), ("і", "и"), ("ї", "и"), ("й", "и"), ("ё", "е"), ("ъ", ""), ("ь", "")):
        text = text.replace(a, b)
    return text


def books() -> list[dict]:
    out = []
    for path in sorted([*CATALOG.glob("*.book.json"), *FS_CATALOG.glob("*.book.json")]):
        book = json.loads(path.read_text(encoding="utf-8"))
        book["id"] = path.name.removesuffix(".book.json")
        book["kind"] = "consistory" if "Консистор" in book["title"] else "church"
        book["catalog"] = path.parent
        # плёнки FamilySearch лежат в archives/raw/familysearch/<плёнка>/ — путь в поле «local»
        book["dir"] = Path(book["local"]).expanduser() if path.parent == FS_CATALOG else GASO_RAW / book["id"]
        out.append(book)
    return out


def scan(book: dict, n: int) -> Path:
    return book["dir"] / book["local_template"].format(n=n)


def vision(images: list[Path]) -> dict[str, list[dict]]:
    """Текст Vision по картинкам, с кэшем на диске: дважды одно не распознаём."""
    if not VISION_BIN.exists():
        VISION_BIN.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["swiftc", "-O", "-o", str(VISION_BIN), str(VISION_SRC)], check=True)
    OCR_CACHE.mkdir(parents=True, exist_ok=True)
    cached = lambda p: OCR_CACHE / f"{p.parent.name}__{p.stem}.json"
    todo = [p for p in images if not cached(p).exists()]
    for i in range(0, len(todo), 20):
        run = subprocess.run([str(VISION_BIN), *map(str, todo[i:i + 20])], capture_output=True, text=True, check=True)
        for line in run.stdout.splitlines():
            page = json.loads(line)
            cached(Path(page["image"])).write_text(json.dumps(page["lines"], ensure_ascii=False), encoding="utf-8")
        print(f"  Vision: {min(i + 20, len(todo))}/{len(todo)}", file=sys.stderr)
    return {str(p): json.loads(cached(p).read_text(encoding="utf-8")) for p in images}


def classify(lines: list[dict]) -> dict:
    """Часть книги и год по печатной шапке (верх разворота); плотность — сколько строк текста вообще."""
    top = normalize(" ".join(x["text"] for x in lines if x["y"] > 0.6))
    every = normalize(" ".join(x["text"] for x in lines))
    printed_form = re.search(r"метрич|етрич|кнпги|книги\s+на", top)
    section = ("confession" if not printed_form and re.search(CONFESSION, top) else None) \
        or next((name for name, rx in SECTION_WORDS if re.search(rx, top)), None) \
        or next((name for name, rx in SECTION_WORDS if re.search(rx, every)), "other")
    years = re.findall(r"\b(18[3-9]\d|19[01]\d)\b", top) or re.findall(r"\b(18[3-9]\d|19[01]\d)\b", every)
    # титульный лист «Часть первая, о родившихся» без таблицы и стык частей — не страница записей (д. 583, разв. 139)
    columns = {"births": r"восприем|родител", "marriages": r"поруч|невест", "deaths": r"погреб|чего"}
    table = section == "confession" or (bool(re.search(columns.get(section, "$^"), every))
                                        and not (section == "births" and re.search(r"умерш|омерш", every)))
    return {"section": section, "year": int(Counter(years).most_common(1)[0][0]) if years else None,
            "lines": len(lines), "table": table}


def pick(args) -> int:
    rng = random.Random(args.seed)
    candidates = []
    for book in books():
        count = args.per_book * (6 if "исповед" in book["title"] else 1)
        lo, hi = book["first"] + 2, book["last"] - 2
        numbers = sorted({round(lo + (hi - lo) * (i + 0.5) / count) for i in range(count)})
        images = [scan(book, n) for n in numbers if scan(book, n).exists()]
        print(f"{book['id']}: {len(images)} разворотов", file=sys.stderr)
        for path, lines in vision(images).items():
            c = classify(lines)
            n = int(re.findall(r"(\d+)\.jpg$", path)[0])
            kind = "confession" if c["section"] == "confession" else book["kind"]
            candidates.append({"id": f"{book['id']}_{n:03d}", "book": book["id"], "n": n, "title": book["title"],
                               "kind": kind, "path": path, **c})
    by_stratum = defaultdict(list)
    for c in candidates:
        if c["section"] != "other" and c["lines"] >= args.min_lines and c["table"]:
            by_stratum[(c["kind"], c["section"])].append(c)
    chosen = []
    for stratum, quota in QUOTA.items():
        pool = by_stratum.get(stratum, [])
        rng.shuffle(pool)
        taken, books_used, years_used = [], set(), set()
        for strict in (True, False):       # сначала — разные дела и годы; не хватило — какие есть
            for c in pool:
                if len(taken) >= quota or c in taken:
                    continue
                if strict and (c["book"] in books_used or c["year"] in years_used):
                    continue
                taken.append(c)
                books_used.add(c["book"])
                years_used.add(c["year"])
        chosen += taken
        print(f"  {KIND_RU[stratum[0]]} / {SECTION_RU[stratum[1]]}: кандидатов {len(pool)}, взято {len(taken)}"
              f" (нужно {quota})", file=sys.stderr)
    OUT.mkdir(parents=True, exist_ok=True)
    PAGES.write_text(json.dumps({"made": dt.date.today().isoformat(), "seed": args.seed, "pages": chosen,
                                 "census": Counter(f"{c['kind']}/{c['section']}" for c in candidates)},
                                ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"выбрано {len(chosen)} страниц → {PAGES}")
    for c in chosen:
        print(f"  {c['id']:22} {KIND_RU[c['kind']]:28} {SECTION_RU[c['section']]:12} {c['year'] or '?'}")
    return 0


def load_pages() -> list[dict]:
    if not PAGES.exists():
        sys.exit("нет выбора страниц: сначала `etalon.py pick`")
    return json.loads(PAGES.read_text(encoding="utf-8"))["pages"]


def prompt_for(page: dict) -> str:
    fields = FIELDS[page["section"]]
    record = ", ".join(f'"{f}": "<{FIELD_RU[f]}>"' for f in fields)
    return (f"Это разворот: {KIND_RU[page['kind']]}, часть — {SECTION_RU[page['section']]}. Ожидаемый год по шапке "
            f"(проверь глазами): {page['year'] or 'не прочитан'}.\n"
            "Перепиши ВСЕ записи разворота сверху вниз, слева направо, как написано. Запись, начатая на прошлом "
            "развороте, — тоже, с \"continued\": true.\n"
            "Ответ — один JSON:\n"
            '{"page": {"year": "", "month": "", "folio": "<номер листа, если виден>", "church": "<если написано>", '
            '"hands_note": "<сколько почерков, чем пишут, состояние>"}, '
            f'"records": [{{{record}, "continued": false, "note": ""}}]}}\n'
            "Пустая графа — \"\". Ничего, кроме JSON.")


def ollama(prompt: str, image: str, model: str) -> str:
    """Локальная модель через Ollama (бесплатно, без сети): модель вида ollama:qwen3-vl:8b-instruct."""
    import base64
    import urllib.request
    body = {"model": model, "stream": False, "format": "json", "options": {"temperature": 0, "num_ctx": 16384},
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": prompt,
                          "images": [base64.b64encode(Path(image).read_bytes()).decode()]}]}
    request = urllib.request.Request("http://127.0.0.1:11434/api/chat", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=1800) as response:
        return json.load(response)["message"]["content"]


def parse_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("в ответе нет JSON")
    data = json.loads(match.group(0))
    if "records" not in data:
        raise ValueError(f"в JSON нет записей: {str(data)[:200]}")
    return data


def premark(args) -> int:
    DRAFT.mkdir(parents=True, exist_ok=True)
    pages = load_pages()
    if args.only:
        pages = [p for p in pages if p["id"] in args.only.split(",")]
    done = failed = 0
    for page in pages:
        out = DRAFT / f"{page['id']}.json"
        if out.exists() and json.loads(out.read_text(encoding="utf-8")).get("model") != args.model:
            out = DRAFT / "other" / f"{page['id']}.{args.model}.json"   # чужой черновик не затираем — кладём рядом
            out.parent.mkdir(exist_ok=True)
        if out.exists() and not args.again:
            continue
        try:
            if args.model.startswith("ollama:"):
                text = ollama(prompt_for(page), page["path"], args.model.removeprefix("ollama:"))
            else:
                text = llm.ask("etalon-premark", prompt_for(page), SYSTEM, model=args.model, image=page["path"])
            data = parse_json(text)
        except llm.Limit as stop:
            print(f"стоп: {stop}")
            break
        except (RuntimeError, OSError) as error:    # сбой связи или модели — черновик не трогаем
            failed += 1
            print(f"  {page['id']}: не вышло — {str(error)[:150]}")
            continue
        except ValueError as error:      # плохой JSON — сохраняем сырой ответ, Павел увидит пустую разметку
            failed += 1
            data = {"page": {}, "records": [], "error": str(error)[:300], "raw": locals().get("text", "")[:4000]}
        data.update({"id": page["id"], "model": args.model, "made": dt.datetime.now().isoformat(timespec="seconds")})
        out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        done += 1
        print(f"  {page['id']}: записей {len(data.get('records', []))}" + (" (ошибка разбора)" if "error" in data else ""))
    print(f"предразметка: сделано {done}, с ошибкой {failed}; всего черновиков {len(list(DRAFT.glob('*.json')))}")
    return 0


SCRIBE_SYSTEM = ("Ты раскладываешь готовую расшифровку страницы церковной книги по полям. Только переносишь слова "
                 "из текста, ничего не исправляешь, не дополняешь и не угадываешь; чего в тексте нет — \"\". "
                 "Отвечаешь только JSON.")


def scribe(args) -> int:
    """Без файлов Scribe — пишет задание; с файлами — раскладывает их текст по полям эталона (haiku, без картинки)."""
    SCRIBE.mkdir(parents=True, exist_ok=True)
    pages = load_pages()
    have = {p.stem: p for p in SCRIBE.glob("*.txt")}
    todo = [p for p in pages if p["id"] not in have]
    task = SCRIBE / "ЗАДАНИЕ.md"
    task.write_text(
        "# Scribe AI → черновики эталона метрик (фаза 4a)\n\n"
        "Каждый скан ниже загрузить в MyHeritage Scribe AI и сохранить его ответ **слово в слово** как "
        f"`{SCRIBE}/<id>.txt` (UTF-8). Ничего не править. Если Scribe отказал или выдал пусто — файл с одной строкой "
        "`SCRIBE: ОТКАЗ <что сказал>`. Потом: `tools/py tools/scripts/etalon.py scribe`.\n\n"
        "| id | скан |\n|---|---|\n" + "".join(f"| {p['id']} | {p['path']} |\n" for p in todo), encoding="utf-8")
    print(f"Scribe: ответов {len(have)}, ждут {len(todo)} — задание: {task}")
    done = 0
    for page in pages:
        txt = have.get(page["id"])
        if not txt:
            continue
        out = DRAFT / f"{page['id']}.json"
        if out.exists() and json.loads(out.read_text(encoding="utf-8")).get("model", "").startswith("scribe"):
            continue
        if out.exists():                      # черновик другой модели не затираем
            out = DRAFT / "other" / f"{page['id']}.scribe.json"
            out.parent.mkdir(exist_ok=True)
            if out.exists():
                continue
        text = txt.read_text(encoding="utf-8").strip()
        if text.startswith("SCRIBE: ОТКАЗ") or not text:
            print(f"  {page['id']}: Scribe не прочёл")
            continue
        record = ", ".join(f'"{f}": "<{FIELD_RU[f]}>"' for f in FIELDS[page["section"]])
        prompt = (f"Часть книги: {SECTION_RU[page['section']]}. Расшифровка страницы (Scribe AI):\n---\n{text}\n---\n"
                  "Разложи все записи по порядку. Ответ — один JSON: "
                  '{"page": {"year": "", "month": "", "folio": ""}, '
                  f'"records": [{{{record}, "continued": false, "note": ""}}]}}')
        try:
            data = parse_json(llm.ask("etalon-scribe-fields", prompt, SCRIBE_SYSTEM, model="haiku"))
        except llm.Limit as stop:
            print(f"стоп: {stop}")
            break
        except (RuntimeError, ValueError) as error:
            print(f"  {page['id']}: не разложил — {str(error)[:120]}")
            continue
        data.update({"id": page["id"], "model": "scribe (MyHeritage) → поля: haiku",
                     "made": dt.datetime.now().isoformat(timespec="seconds")})
        out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        done += 1
        print(f"  {page['id']}: записей {len(data.get('records', []))}")
    print(f"разложено {done}")
    return 0


def status(_args) -> int:
    pages = load_pages()
    states = {p["id"]: page_state(p)["state"] for p in pages}
    count = lambda st: sum(1 for v in states.values() if v == st)
    print(f"выбрано {len(pages)}: в эталоне {count('checked')}, с замечанием {count('note')}, "
          f"черновик {count('draft')}, без черновика {count('empty')}")
    for p in pages:
        mark = {"checked": "✅", "note": "💬", "draft": "✏️", "empty": "·"}[states[p["id"]]]
        print(f"  {mark} {p['id']:22} {KIND_RU[p['kind']]:28} {SECTION_RU[p['section']]:12} {p['year'] or '?'}")
    return 0


# ---------- локальная страница проверки ----------

def is_etalon(saved: dict) -> bool:
    """В эталон идёт только страница с записями (или честно помеченная «не годится»). Сохранение без записей,
    но с комментарием — замечание к черновику, не правильный ответ."""
    return bool(saved.get("records")) or bool(saved.get("skipped"))


def page_state(page: dict) -> dict:
    checked, draft = CHECKED / f"{page['id']}.json", DRAFT / f"{page['id']}.json"
    if checked.exists():
        saved = json.loads(checked.read_text(encoding="utf-8"))
        if is_etalon(saved):
            return {"state": "checked", **saved}
        base = json.loads(draft.read_text(encoding="utf-8")) if draft.exists() else {"page": {}, "records": []}
        base["records"] = [to_new_form(r, page["section"]) for r in base.get("records", [])]
        return {**base, "state": "note", "comment": saved.get("comment", "")}
    if draft.exists():
        data = json.loads(draft.read_text(encoding="utf-8"))
        data["records"] = [to_new_form(r, page["section"]) for r in data.get("records", [])]
        return {"state": "draft", **data}
    return {"state": "empty", "page": {}, "records": []}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, body: bytes, kind: str, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        pages = {p["id"]: p for p in load_pages()}
        url = urllib.parse.urlparse(urllib.parse.unquote(self.path))   # имена дел — кириллица
        if url.path == "/":
            return self.send((Path(__file__).parent / "etalon_page.html").read_bytes(), "text/html; charset=utf-8")
        if url.path == "/api/pages":
            rows = [{**{k: p[k] for k in ("id", "title", "kind", "section", "year", "n")},
                     "kind_ru": KIND_RU[p["kind"]], "section_ru": SECTION_RU[p["section"]],
                     "state": page_state(p)["state"]} for p in pages.values()]
            return self.send(json.dumps(rows, ensure_ascii=False).encode(), "application/json")
        if url.path.startswith("/api/page/"):
            page = pages[url.path.rsplit("/", 1)[1]]
            fields = FIELDS[page["section"]]
            body = {**page_state(page), "meta": page, "fields": fields, "labels": FIELD_RU,
                    "page_fields": PAGE_FIELDS}
            return self.send(json.dumps(body, ensure_ascii=False).encode(), "application/json")
        if url.path.startswith("/scan/"):
            page = pages[url.path.rsplit("/", 1)[1]]
            return self.send(Path(page["path"]).read_bytes(), "image/jpeg")
        self.send(b"not found", "text/plain", 404)

    def do_POST(self):
        pages = {p["id"]: p for p in load_pages()}
        url = urllib.parse.urlparse(urllib.parse.unquote(self.path))   # имена дел — кириллица
        if not url.path.startswith("/api/save/"):
            return self.send(b"not found", "text/plain", 404)
        pid = url.path.rsplit("/", 1)[1]
        if pid not in pages:
            return self.send(b"unknown page", "text/plain", 404)
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        CHECKED.mkdir(parents=True, exist_ok=True)
        draft = DRAFT / f"{pid}.json"
        saved = {"id": pid, "book": pages[pid]["book"], "n": pages[pid]["n"], "kind": pages[pid]["kind"],
                 "section": pages[pid]["section"], "page": data.get("page", {}), "records": data.get("records", []),
                 "skipped": bool(data.get("skipped")), "comment": data.get("comment", ""),
                 "checked_at": dt.datetime.now().isoformat(timespec="seconds"),
                 "seconds_spent": data.get("seconds_spent"),
                 "draft_model": json.loads(draft.read_text(encoding="utf-8")).get("model") if draft.exists() else None}
        (CHECKED / f"{pid}.json").write_text(json.dumps(saved, ensure_ascii=False, indent=1), encoding="utf-8")
        self.send(b'{"ok": true}', "application/json")


def serve(args) -> int:
    load_pages()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"страница проверки: http://127.0.0.1:{args.port}/  (остановить — Ctrl+C)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("pick", help="выбрать ~20 страниц по типам книг")
    s.add_argument("--per-book", type=int, default=16)
    s.add_argument("--min-lines", type=int, default=40, help="меньше строк Vision — пустая или обложка")
    s.add_argument("--seed", type=int, default=4)
    s.set_defaults(func=pick)
    s = sub.add_parser("premark", help="предразметка моделью (llm.py)")
    s.add_argument("--model", required=True, help="haiku | sonnet (llm.py) | ollama:<модель>; Gemini не используем (02.10: "
                   "2.5 Flash зацикливается, новые перегружены, Pro без бесплатной квоты)")
    s.add_argument("--only", help="id через запятую")
    s.add_argument("--again", action="store_true", help="переделать уже размеченные")
    s.set_defaults(func=premark)
    s = sub.add_parser("serve", help="локальная страница проверки")
    s.add_argument("--port", type=int, default=8765)
    s.set_defaults(func=serve)
    sub.add_parser("status").set_defaults(func=status)
    sub.add_parser("scribe", help="задание для Scribe AI и разбор его ответов").set_defaults(func=scribe)
    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
