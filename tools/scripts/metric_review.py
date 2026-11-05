#!/usr/bin/env python3
"""Павел смотрит вырезки кандидатов из метрик и решает: наш / не наш / непонятно (схема — документ дерева проект/МЕТРИКИ_СХЕМА.md, шаг 5).

Зачем. Фильтр (`metric_filter.py match`) только говорит «здесь, кажется, Иван Прокопов из Вербичей». Машина часто
ошибается в почерке, поэтому каждую находку человек видит глазами — вырезку скана, а не пересказ. Модель картинку не
видит; вырезка режется на этом Mac из файла скана.

    tools/py tools/scripts/metric_review.py book  ф48_оп6_д526 [--village Вербичи]  # вся книга: чтение → поиск → итог
    tools/py tools/scripts/metric_review.py serve [--port 8766] [--grades AB] [--village Вербичи] [--named]
    tools/py tools/scripts/metric_review.py list  [--grades AB]          # то же текстом: что ещё не решено
    tools/py tools/scripts/metric_review.py read  --grades A [--limit 5] # точное чтение вырезок sonnet (только по «да»
                                                                         # Павла; одна вырезка — один вызов, с кэшем)

Под каждой вырезкой — «кто из дерева» (кем приходится Феодоре или Сергею) и, после точного чтения, «что это значит
для семьи»: кто в записи, кем он нам, есть ли уже в дереве. Это подсказка для решения, а не факт.

Решения — `$ARCHIVES_LOCAL/text/gaso/решения.jsonl` (вне git: там имена): дело, разворот, высота, решение,
комментарий, дата. Решённое больше не показывается. В карточку факт попадает только после «наш» — обычной строкой
по навыку `card-rules`.
"""
import argparse
import datetime as dt
import html
import http.server
import io
import json
import re
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import metric_filter as mf  # noqa: E402
import paths  # noqa: E402

DECISIONS = mf.TEXT / "решения.jsonl"
READS = mf.TEXT / "прочтения.json"          # точное чтение вырезок: ключ кандидата → разбор модели (с именами, вне git)
READ_MODEL = "sonnet"                       # haiku для метрик не берём (МЕТРИКИ_СХЕМА, правило 6)
READ_SYSTEM = (
    "Ты палеограф. Читаешь вырезку из русской православной метрической книги Смоленской губернии 1885–1917 годов "
    "(дореформенная орфография, рукопись по печатному бланку). Переписывай только то, что видно, буква в букву, "
    "в старой орфографии. Неразборчивое — [нрзб], сомнительное слово — со знаком [?]. Ничего не достраивай по смыслу: "
    "названия деревень и волостей не угадывай. Ответ — только JSON, без пояснений.")
READ_PROMPT = """На вырезке — часть разворота: одна запись целиком или куски двух-трёх соседних. Перепиши каждую
запись, которую видно хотя бы наполовину. Формат:
{"records": [{"part": "рождение | брак | смерть | не понять",
  "number": "номер записи или null", "date": "даты, как написаны (рождение / крещение и т. п.)",
  "main": "кто родился / кто умер / жених и невеста — как написано",
  "people": "родители (для рождения), возраст и причина (для смерти), звание, деревня, волость — как написано",
  "witnesses": "восприемники или поручители — как написано", "complete": true|false}]}"""

# от кого считаем родство: первый, с кем связь есть (имена карточек — ftree.toml, [metric_review] anchors)
ANCHORS = ",".join(paths.tree_conf("metric_review.anchors", []))
# если человек из дерева в записи о рождении — родитель, то кем новорождённый приходится тому же «я»
CHILD_OF = {"отец": "брат или сестра", "мать": "брат или сестра", "дядя": "двоюродный брат или сестра",
            "тётя": "двоюродный брат или сестра", "брат": "племянник или племянница",
            "сестра": "племянник или племянница", "дед": "дядя или тётя", "бабушка": "дядя или тётя",
            "двоюродный брат": "двоюродный племянник или племянница",
            "двоюродная сестра": "двоюродный племянник или племянница"}
VERDICTS = {"our": "наш", "not": "не наш", "unclear": "непонятно"}


def key(c: dict) -> str:
    return f"{c['book']}:{c['n']}:{int(c['y0'])}"


def decisions() -> dict[str, dict]:
    if not DECISIONS.exists():
        return {}
    out = {}
    for line in DECISIONS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            out[d["key"]] = d
    return out


def village_names(village: str | None) -> set[str]:
    """Деревня и все её написания из карточки места: «Вербичи» → Вербичи, Вербичы, Werbicze."""
    if not village:
        return set()
    import cards
    import tree
    found = tree.find_place(cards.load(), village)
    return {village, *(n for pl in found[:1] for n in [pl.name, *pl.aliases])}


def candidates(grades: str, village: str | None = None, named: bool = False, book: str | None = None) -> list[dict]:
    """Кандидаты всех прочитанных книг, ещё не решённые: сначала A, потом B…; с --village — только с этой деревней
    (в любом её написании); с --named — только те, где рядом есть имя человека из дерева (для D)."""
    done = decisions()
    names = village_names(village)
    out = []
    for f in sorted(mf.TEXT.glob("*/metric_candidates.json")):
        for c in json.loads(f.read_text(encoding="utf-8"))["candidates"]:
            if c["grade"] not in grades or key(c) in done or (book and c["book"] != book):
                continue
            if names and not any(h["kind"] == "village" and h["target"] in names for h in c["hits"]):
                continue
            if named and not any(h["kind"] in ("surname", "given") for h in c["hits"]):
                continue
            out.append(c)
    out.sort(key=lambda c: ("ABCD".index(c["grade"]), -c["score"], c["book"], c["n"]))
    return out


def columns_x(book_id: str, n: int, w: int) -> tuple[int, int]:
    """Ширина вырезки: от колонки «Счёт» (номер и дата записи) до правого края последней колонки с людьми — по шаблону
    бланка из кэша фильтра. Подписи причта и поля справа не нужны: без них буквы крупнее, а в картинку модели влезает
    больше вырезок. Нет шаблона — весь разворот."""
    data = mf.load_cache(book_id, n) or {}
    boxes = list((data.get("boxes") or {}).values())
    if not boxes:
        return 0, w
    left = data["act_box"][0] if data.get("act_box") else min(b[0] for b in boxes) - 350
    return max(0, left - 15), min(w, max(b[2] for b in boxes) + 20)


def crop(book_id: str, n: int, y0: float, y1: float) -> bytes:
    """Вырезка: колонки от номера записи до последней колонки с людьми; по высоте — окно кандидата; JPEG."""
    import etalon
    import form_template as ft
    from PIL import Image
    img = Image.open(etalon.scan(ft.book_by_id(book_id), n))
    w, h = img.size
    x0, x1 = columns_x(book_id, n, w)
    box = (x0, max(0, int(y0 - mf.WINDOW)), x1, min(h, int(y1 + mf.WINDOW)))
    part = img.crop(box).convert("RGB")
    if part.width > 2600:
        part = part.resize((2600, int(part.height * 2600 / part.width)))
    buf = io.BytesIO()
    part.save(buf, "JPEG", quality=82)
    return buf.getvalue()


def genitive(name: str) -> str:
    """Агата → Агаты, Сергей → Сергея, Нил → Нила (для «брат для Агаты»)."""
    if name.endswith("а"):
        return name[:-1] + ("и" if name[-2] in "гкхжшчщ" else "ы")
    if name.endswith(("я", "й", "ь")):
        return name[:-1] + ("и" if name.endswith("я") else "я")
    return name + "а"


def instrumental(name: str) -> str:
    """Агата → Агатой, Сергей → Сергеем, Нил → Нилом."""
    if name.endswith(("а", "я")):
        return name[:-1] + ("ей" if name.endswith("я") else "ой")
    if name.endswith(("й", "ь")):
        return name[:-1] + "ем"
    return name + "ом"


class Kin:
    """Кем люди из дерева, совпавшие в записи, приходятся Феодоре (или Сергею) — `tree.relation`."""

    def __init__(self, anchors: str):
        import cards
        self.t = cards.load()
        by_stem = {p.stem: p for p in self.t.people.values()}
        self.anchors = [by_stem[a.strip()] for a in anchors.split(",") if a.strip() in by_stem]

    def fits_years(self, pid: str, book: str, adult: bool = True) -> bool:
        """Мог ли человек быть в записи этой книги: родился не позже конца книги (взрослый — не позже конца минус 12 лет:
        крёстный, поручитель, родитель) и не умер до её начала. Годы неизвестны — не отсеиваем. Без этого внук 1964 года
        «находился» крёстным в книге 1890-х (Павел, 10.10.2026)."""
        import form_template as ft
        try:
            y0, y1 = map(int, mf.book_years(ft.book_by_id(book)).split("-"))
        except Exception:
            return True
        p = self.t.people[pid]
        born = p.born.first_year if getattr(p, "born", None) else None
        died = p.died.last_year if getattr(p, "died", None) else None
        if born and born > y1 - (12 if adult else 0):
            return False
        if died and died < y0:
            return False
        return True

    def term(self, pid: str) -> str:
        import tree
        for a in self.anchors:
            if pid == a.id:
                return f"это {a.stem}"
            t, _ = tree.relation(self.t, a.id, pid)
            if t:
                return f"{t} для {genitive(a.stem.split()[0])}"
        return "связи с " + " и ".join(instrumental(a.stem.split()[0]) for a in self.anchors) + " в дереве нет"

    def child_known(self, parents: list[str], main: str) -> str:
        """Есть ли новорождённый уже в дереве: среди детей возможных родителей — ребёнок с тем же именем в любой форме.
        Год смотреть глазами: тёзка мог умереть младенцем, и следующего ребёнка назвали так же."""
        import tree
        names = mf._WORD.findall(main)
        if not names:
            return ""
        for i in parents:
            for ch in self.t.people[i].children:
                child = self.t.people.get(ch)
                if child and mf.given_match(mf._WORD.findall(child.stem)[0], names[0]):
                    return f"в дереве есть ребёнок с этим именем: {tree.label(child)} — сверить год"
        return f"ребёнка «{names[0]}» среди детей этих людей в дереве нет — возможно, новый человек"

    def lines(self, c: dict, by_name: bool = False) -> list[str]:
        """Кто из дерева мог быть в этой записи: из совпавших по фамилии (или «по отцу») — только те, чьё имя в любой
        форме есть в окне; иначе — «однофамилец, в дереве N»."""
        import tree
        out = []
        self.matched = []
        for h in c["hits"]:
            ids = [i for i in h.get("ids", []) if i in self.t.people]
            if not ids:
                continue
            named = [i for i in ids if mf.given_match(mf._WORD.findall(self.t.people[i].stem)[0], c["context"])
                     and self.fits_years(i, c["book"], adult=c["section"] != "births" or h.get("field") != "child")]
            if not named:
                if not by_name:     # в разборе точного чтения такие строки — шум
                    out.append(f"«{h['word']}» — {len(ids)} чел. в дереве с таким словом, имя рядом не найдено")
                continue
            self.matched += named[:4]
            for i in named[:4]:
                t = self.term(i)
                line = f"{tree.label(self.t.people[i])} — {t}"
                base = t.split(" для ")[0]
                if c["section"] == "births" and (by_name or h.get("field") == "parents") and base in CHILD_OF:
                    who = "она тут мать" if self.t.people[i].sex == "F" else "он тут отец"
                    line += f"; если {who} — младенец: {CHILD_OF[base]} для {t.split(' для ')[1]}"
                out.append(line)
        return list(dict.fromkeys(out))


def reads() -> dict:
    return json.loads(READS.read_text(encoding="utf-8")) if READS.exists() else {}


def crop_file(c: dict) -> Path:
    """Вырезка кандидата файлом (для модели): тот же кадр, что видит Павел."""
    out = mf.TEXT / "_crops" / f"v2_{key(c).replace(':', '_')}.jpg"      # v2 — узкая вырезка (05.10.2026)
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(crop(c["book"], c["n"], c["y0"], c["y1"]))
    return out


def parse_read(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else {"error": text[:300]}
    except json.JSONDecodeError:
        return {"error": text[:300]}


def stack(cs: list[dict], first: int = 1) -> Path:
    """Несколько вырезок одной картинкой, сверху вниз, над каждой — полоса «ВЫРЕЗКА k». Зачем: у вызова модели
    ≈16 тыс. токенов служебного начала (замер 04.10.2026), а сама вырезка — ≈1 тыс.; пачка делит начало на всех.
    Ширина та же, что у одной вырезки: модель всё равно ужимает длинную сторону, высота пачки её не ухудшает."""
    from PIL import Image, ImageDraw, ImageFont
    parts = [Image.open(crop_file(c)).convert("RGB") for c in cs]
    w, band = max(p.width for p in parts), 46
    out = Image.new("RGB", (w, sum(p.height + band for p in parts)), "white")
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 34)
    except OSError:
        font = ImageFont.load_default()
    y, draw = 0, ImageDraw.Draw(out)
    for k, p in enumerate(parts, first):
        draw.rectangle([0, y, w, y + band - 4], fill="black")
        draw.text((12, y + 4), f"ВЫРЕЗКА {k}", fill="white", font=font)
        out.paste(p, (0, y + band))
        y += band + p.height
    path = mf.TEXT / "_crops" / ("batch_" + "_".join(key(c).replace(":", "_") for c in cs)[:180] + ".jpg")
    out.save(path, "JPEG", quality=85)
    return path


def read(args) -> int:
    """Точное чтение вырезок: по --batch вырезок в картинке, по --images картинок в вызове (`llm.ask`: кэш, журнал,
    потолок). Служебное начало вызова ≈16 тыс. токенов делится на все вырезки вызова."""
    import llm
    model = args.model or READ_MODEL
    done = reads()
    todo = [c for c in candidates(args.grades, args.village, args.named, args.book_id) if key(c) not in done][:args.limit]
    per_call = args.batch * args.images
    print(f"к чтению: {len(todo)} вырезок, модель {model}, по {args.batch} в картинке, по {per_call} за вызов")
    for start in range(0, len(todo), per_call):
        part = todo[start:start + per_call]
        if len(part) == 1:
            prompt, images = READ_PROMPT, [crop_file(part[0])]
        else:
            groups = [part[i:i + args.batch] for i in range(0, len(part), args.batch)]
            images = [stack(g, first=1 + i * args.batch) for i, g in enumerate(groups)]
            prompt = (f"Всего {len(part)} вырезок на {len(images)} картинках, каждая под чёрной полосой «ВЫРЕЗКА k» "
                      f"(номера сквозные). Каждую читай отдельно, записи из разных вырезок не смешивай. Ответ — "
                      f"JSON-объект {{\"1\": {{…}}, \"2\": {{…}}, …}} по номерам вырезок, каждое значение — в формате:\n"
                      + READ_PROMPT)
        try:
            text = llm.ask("metric-crop", prompt, READ_SYSTEM, model=model, image=images)
        except llm.Limit as e:
            print(f"стоп: {e}")
            break
        got = parse_read(text)
        for k, c in enumerate(part, 1):
            done[key(c)] = got if len(part) == 1 else (got.get(str(k)) or {"error": "нет в ответе пачки"})
            done[key(c)]["model"] = model
            bad = " — ошибка разбора" if "error" in done[key(c)] else ""
            print(f"{c['book']} разв. {c['n']}: записей {len(done[key(c)].get('records', []))}{bad}")
        READS.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    llm.status()
    return 0


def meaning(c: dict, r: dict, kin: "Kin") -> list[str]:
    """Что точное чтение значит для семьи: по каждой записи — кто в ней, кто из дерева похож, кем он нам, есть ли уже
    этот ребёнок в дереве. Родители и крёстные — раздельно: крёстная — не мать."""
    out = []
    for rec in r.get("records", []):
        part = rec.get("part", "?")
        section = {"рождение": "births", "брак": "marriages", "смерть": "deaths"}.get(part, c["section"])
        main = str(rec.get("main") or "")
        line = f"{part} № {rec.get('number') or '?'}, {rec.get('date') or 'дата не прочитана'}: {main or '?'}"
        core = kin.lines({**c, "section": section, "context": f"{main} {rec.get('people') or ''}"}, by_name=True)
        parents = list(kin.matched)
        godp = kin.lines({**c, "section": "", "context": str(rec.get("witnesses") or "")}, by_name=True)
        parts = core + [f"восприемник/поручитель: {x}" for x in godp]
        if section == "births" and core:
            parts.append(kin.child_known(parents, main))
        out.append(line + (" — " + "; ".join(p for p in parts if p) if parts else " — людей из дерева по именам не видно"))
    return out


def what(c: dict) -> str:
    return "; ".join(f"{h['target']} ~ «{h['word']}» ({h['sim']})" for h in c["hits"])


PAGE = """<!doctype html><meta charset="utf-8"><title>Метрики — проверка</title>
<style>body{{font:15px system-ui;margin:16px;background:#fafafa;color:#222}}.c{{background:#fff;border:1px solid #ddd;
border-radius:8px;padding:12px;margin:0 0 18px}}img{{max-width:100%;display:block;margin:8px 0}}pre{{white-space:pre-wrap;
font-size:13px;color:#555;background:#f3f3f3;padding:8px}}button{{font-size:15px;margin-right:8px;padding:6px 14px}}
input{{width:60%;font-size:14px;padding:5px}}.g{{font-weight:700}}.k{{margin-top:6px;color:#0a5a2a}}.r{{margin-top:8px;padding:8px;background:#eef5ff;border-radius:6px}}</style>
<h2>Кандидаты из метрик: {count} не решено</h2><p>Смотрите на скан, а не на текст машины: текст — только подсказка,
где искать. Клик по скану — во весь размер. «Наш» — только если видно имя, деревню и родню, как в карточке.</p>{items}
<script>async function v(k,d){{const c=document.getElementById('n'+k).value;
await fetch('/decide',{{method:'POST',body:JSON.stringify({{key:k,verdict:d,comment:c}})}});
document.getElementById('c'+k).style.opacity=.35}}</script>"""

ITEM = """<div class="c" id="c{i}"><div><span class="g">{grade}</span> · {book}, разворот {n}, {section}, высота ≈{y}
· {what}</div><div class="k">{kin}</div>{read}<a href="/crop?k={k}" target="_blank"><img loading="lazy" src="/crop?k={k}"></a><pre>{context}</pre>
<input id="n{i}" placeholder="что видно на скане (необязательно)">
<button onclick="v({i},'our')">наш</button><button onclick="v({i},'not')">не наш</button>
<button onclick="v({i},'unclear')">непонятно</button></div>"""


def serve(args) -> int:
    items = candidates(args.grades, args.village, args.named, args.book_id)
    by_i = dict(enumerate(items))
    kin = Kin(args.anchors)
    done_reads = reads()

    def read_block(c: dict) -> str:
        r = done_reads.get(key(c))
        if not r:
            return ""
        recs = "".join("<div>📜 " + " · ".join(f"<i>{lab}</i>: {html.escape(str(x.get(f)))}" for f, lab in (
            ("part", "что"), ("number", "№"), ("date", "дата"), ("main", "кто"), ("people", "родители / о ком"),
            ("witnesses", "крёстные / поручители")) if x.get(f)) + ("" if x.get("complete", True) else " · <i>запись видна не целиком</i>")
            + "</div>" for x in r.get("records", []))
        fam = "".join(f"<div>👪 {html.escape(x)}</div>" for x in meaning(c, r, kin))
        return (f'<div class="r"><b>Точное чтение ({r.get("model", READ_MODEL)}, проверить по скану):</b>{recs}'
                f'<b>Что это значит для семьи (подсказка):</b>{fam}</div>')

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, body: bytes, ctype: str):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            if u.path == "/crop":
                k = urllib.parse.parse_qs(u.query)["k"][0]
                book, n, y = k.split(":")
                c = next(x for x in items if key(x) == k)
                return self.send(crop(book, int(n), c["y0"], c["y1"]), "image/jpeg")
            body = "".join(ITEM.format(i=i, k=urllib.parse.quote(key(c)), grade=c["grade"], book=c["book"], n=c["n"],
                                       section=c["section"], y=int(c["y0"]), what=html.escape(what(c)),
                                       kin="<br>".join(html.escape(x) for x in kin.lines(c)) or "кто из дерева — не ясно",
                                       read=read_block(c),
                                       context=html.escape(c["context"]))
                           for i, c in by_i.items())
            self.send(PAGE.format(count=len(items), items=body).encode(), "text/html; charset=utf-8")

        def do_POST(self):
            d = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            c = by_i[int(d["key"])]
            row = {"key": key(c), "book": c["book"], "n": c["n"], "y0": c["y0"], "section": c["section"],
                   "verdict": VERDICTS[d["verdict"]], "comment": d.get("comment", ""), "hits": what(c),
                   "date": dt.datetime.now().isoformat(timespec="seconds")}
            DECISIONS.parent.mkdir(parents=True, exist_ok=True)
            with DECISIONS.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            self.send(b"ok", "text/plain")

    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"кандидатов {len(items)}; страница: http://127.0.0.1:{args.port}/  (остановить — Ctrl+C)")
    server.serve_forever()
    return 0


def list_(args) -> int:
    items = candidates(args.grades, args.village, args.named, args.book_id)
    kin = Kin(args.anchors) if args.kin else None
    print(f"не решено: {len(items)}")
    for c in items[:args.top]:
        print(f"{c['grade']} {c['book']} разв. {c['n']} {c['section']} y≈{int(c['y0'])} · {what(c)}")
        for x in (kin.lines(c) if kin else []):
            print(f"    {x}")
    done = decisions().values()
    if done:
        print("решено: " + ", ".join(f"{v} {sum(1 for d in done if d['verdict'] == v)}" for v in VERDICTS.values()))
    return 0


def book(args) -> int:
    """Вся книга одной командой: Manuscript-OCR (прочитанное кэшем пропускается) → поиск → итог в десяток строк.
    Для главной сессии: запускать фоном, читать только итог — не лог чтения и не кандидатов целиком."""
    import subprocess
    tool = [sys.executable, str(Path(__file__).with_name("metric_filter.py"))]
    run = subprocess.run(tool + ["run", args.book, "--workers", str(args.workers)], capture_output=True, text=True)
    last = (run.stdout.strip().splitlines() or [run.stderr.strip()[-300:]])[-1]
    print(f"чтение: {last}")
    if run.returncode != 0 and "forms.json" in run.stderr:
        # Шаблон бланка не построен (консисторские копии, окна плёнок вперемешку) — читать целыми разворотами,
        # а не моделью: 30.10.2026 сессия после этой ошибки ушла в Sonnet на сотни снимков.
        print(f"нет шаблона бланка — читать без него: form_template.py build {args.book}; если «страниц 0» — "
              f"ocr_folder.py --src <папка снимков> --out <папка> --only <снимки>, потом grep (навык metric-search)")
        return 1
    m = subprocess.run(tool + ["match", args.book, "--no-acts"] + (["--places", args.places] if args.places else []),
                       capture_output=True, text=True)
    print(next((x for x in m.stdout.splitlines() if x.startswith("кандидатов")), m.stdout[-300:] or m.stderr[-300:]))
    mine = [c for c in candidates("ABD", args.village, False) if c["book"] == args.book]
    strong = [c for c in mine if c["grade"] in "AB"]
    named_d = [c for c in mine if c["grade"] == "D" and any(h["kind"] == "given" for h in c["hits"])]
    for c in strong[:10]:
        print(f"  {c['grade']} разв. {c['n']} {c['section']} · {what(c)[:150]}")
    print(f"не решено: A+B {len(strong)}, D с именем рядом {len(named_d)}"
          + (f" (деревня {args.village})" if args.village else ""))
    print("дальше: metric_review.py read --grades AB (по «да» Павла) → serve → решения → карточки")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("book", help="вся книга: чтение → поиск → итог")
    b.add_argument("book")
    b.add_argument("--workers", type=int, default=5)
    b.add_argument("--places", help="деревни через запятую (по умолчанию — смоленские)")
    b.add_argument("--village", help="для итога: только места с этой деревней")
    for name in ("serve", "list", "read"):
        s = sub.add_parser(name)
        s.add_argument("--grades", default="AB", help="какие оценки показывать, например AB или ABCD")
        s.add_argument("--village", help="только кандидаты с этой деревней (например Вербичи)")
        s.add_argument("--named", action="store_true", help="только с именем из дерева рядом (для D)")
        s.add_argument("--book", dest="book_id", help="только эта книга, например fs_7767677")
        s.add_argument("--anchors", default=ANCHORS, help="от кого считать родство, через запятую (имя карточки)")
        if name == "serve":
            s.add_argument("--port", type=int, default=8766)
        elif name == "read":
            s.add_argument("--limit", type=int, default=5, help="сколько вырезок прочитать за запуск")
            s.add_argument("--batch", type=int, default=4, help="вырезок в одной картинке")
            s.add_argument("--images", type=int, default=3, help="картинок в одном вызове")
            s.add_argument("--model", help="вместо sonnet — только по слову Павла; copilot:<модель> — лимит GitHub, "
                                            "не подписки Claude (навык orchestration)")
        else:
            s.add_argument("--top", type=int, default=40)
            s.add_argument("--kin", action="store_true", help="показать, кем приходятся люди из дерева")
    args = ap.parse_args()
    return {"serve": serve, "list": list_, "read": read, "book": book}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
