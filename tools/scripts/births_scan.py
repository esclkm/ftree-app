#!/usr/bin/env python3
"""Метрики ГАСО: прочитать моделью левые страницы разворотов «О родившихся» и сохранить записи (JSON) — для поиска по родителям.

Зачем. Текст Manuscript-OCR в книгах одной церкви (шесть дел подряд) находил двоих из пяти известных детей одной
пары: имена и деревни искажены. Модель читает левую страницу (номер, даты, имя, графа родителей) двумя вырезками, без имён в
задании (навык metric-search); по готовым чтениям ищут пару родителей, а находки проверяют вторым чтением и по крёстным.
Уже прочитанные развороты (любой моделью) пропускаются. Правая страница (крёстные) — отдельным точным чтением находки.

    tools/py tools/scripts/births_scan.py ф48_оп6_д583 copilot:claude-sonnet-5.5 5-40,68-101
    tools/py tools/scripts/births_scan.py ф48_оп6_д100 sonnet 6-31          # модель: sonnet | opus | copilot:…

Чтения — $ARCHIVES_LOCAL/text/gaso/<дело>/births_left_<модель>.jsonl (вне git: там имена). Разделы книги по годам —
metric_filter.load_cache(дело, n)["section"]. Имена файлов — `Ф48_оп6_д<д>_файл_NNN.jpg` или `…_стр_NNN.jpg`; у консисторских копий (оп. 1–2) имена другие —
добавить шаблон в file(). Так находили всех детей одной пары, которых текст не видел.
"""
import sys, json, re, tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PIL import Image, ImageOps
sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm  # noqa: E402
import paths  # noqa: E402
R = paths.GASO_RAW; T = paths.ARCHIVES_TEXT / "gaso"
SYS = ("Ты читаешь скан метрической книги православной церкви Смоленской губернии, конец XIX – начало XX века, часть «О родившихся». "
       "Перепиши буква в букву, старую орфографию сохраняй, неуверенное — [?], нечитаемое — [нрзб]. Ничего не додумывай. "
       "Ответ — только JSON: {\"acts\":[{\"no\":..,\"sex\":..,\"born\":..,\"baptized\":..,\"child\":..,\"parents\":..}], \"month\":\"названия месяцев на странице\", \"remark\":\"\"}")
P = ("Две вырезки левой страницы одного разворота (1 — верх, 2 — низ, перекрываются). Для каждой записи о рождении перепиши: номер (и пол), "
     "день рождения и крещения, имя ребёнка, графу родителей целиком (звание, деревня, имена родителей). Запись, попавшую в обе вырезки, — один раз.")
def file(book, n):
    for pat in ("файл", "стр"):
        f = R/book/f"Ф{book[1:]}_{pat}_{n:03d}.jpg"
        if f.exists(): return f
def one(book, n, model):
    f = file(book, n)
    im = ImageOps.autocontrast(Image.open(f).convert("L"), cutoff=1); w, h = im.size
    left = im.crop((0, 0, int(w*.53), h))
    with tempfile.TemporaryDirectory() as tmp:
        ps = []
        for i, (a, b) in enumerate([(0, .56), (.44, 1)]):
            c = left.crop((0, int(h*a), left.width, int(h*b))); c.thumbnail((1500, 1500)); p = Path(tmp)/f"{i}.jpg"; c.save(p, quality=90); ps.append(p)
        ans = llm.ask("metric-births-left", P, SYS, model=model, image=ps, timeout=900)
    m = re.search(r"\{.*\}", ans, re.S)
    try: d = json.loads(m.group(0)) if m else {"raw": ans[:2000]}
    except Exception: d = {"raw": ans[:3000]}
    return {"book": book, "n": n, "model": model, **d}
def run(book, ranges, model, workers=3):
    out = T/book/f"births_left_{model.replace(':','_')}.jsonl"; out.parent.mkdir(parents=True, exist_ok=True)
    done = {json.loads(l)["n"] for f in (T/book).glob("births_left_*.jsonl") for l in f.open()}  # любой моделью
    ns = [n for a, b in ranges for n in range(a, b+1) if n not in done and file(book, n)]
    with ThreadPoolExecutor(workers) as ex, out.open("a") as fo:
        for r in ex.map(lambda n: one(book, n, model), ns):
            fo.write(json.dumps(r, ensure_ascii=False)+"\n"); fo.flush()
            print(book, r["n"], len(r.get("acts", [])), flush=True)
if __name__ == "__main__":
    book, model = sys.argv[1], sys.argv[2]
    rs = [tuple(map(int, x.split("-"))) for x in sys.argv[3].split(",")]
    run(book, rs, model)
