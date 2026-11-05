#!/usr/bin/env python3
"""Книги ЗАГС 1918–1923 (ГАСО, ф. Р-3315): прочитать развороты моделью дважды и найти в двух чтениях наших.

Зачем. Акты ЗАГС — печатная таблица на весь разворот, заполненная от руки. Программа Manuscript-OCR, которая хорошо
берёт церковные метрики, здесь склеивает колонки, и поиск по её тексту «Ясенев» промахивается. Поэтому схема другая:
1) по тексту программы находим, где в книге нужные месяцы (`months`) — читаем только эти развороты;
2) каждый разворот режем на четыре части с нахлёстом (верх/низ × левая/правая страница), поднимаем контраст и отдаём
   модели одним вызовом — без имён в задании: «перепиши все акты как написано»;
3) второе чтение — независимо: другая нарезка (`--cut strips`, шесть полос) или другая модель (`--model copilot:…`);
4) `find` ищет по обоим чтениям фамилии, деревни и имена и показывает, где чтения сходятся, а где нет.

    tools/py tools/scripts/zags_read.py months фР1234_оп1_д100
    tools/py tools/scripts/zags_read.py read   фР1234_оп1_д100 --kind birth --from 113 --to 165
    tools/py tools/scripts/zags_read.py read   фР1234_оп1_д100 --kind birth --from 113 --to 165 --cut strips
    tools/py tools/scripts/zags_read.py find   фР1234_оп1_д100 --terms Ясен Вербич Прокоп

Чтения — `$ARCHIVES_LOCAL/text/gaso/<дело>/zags_<модель>.jsonl` (вне git: там имена), строка на разворот.
Найденное — кандидат, а не факт: решение «наш / не наш» — по таблице доводов (навык `metric-search`, «Наш или не наш»).
"""
import argparse
import collections
import json
import re
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm  # noqa: E402
from paths import ARCHIVES_TEXT, GASO_RAW  # noqa: E402

MONTHS = (("янв", "I"), ("фев", "II"), ("мар", "III"), ("апр", "IV"), ("ма[яй]", "V"), ("июн", "VI"), ("июл", "VII"),
          ("авг", "VIII"), ("сен", "IX"), ("окт", "X"), ("ноя", "XI"), ("дек", "XII"))

FIELDS = {
    "birth": "no (номер акта), reg_date (когда записан), birth_date (когда родился), child (имя ребёнка), sex, "
             "father, mother (имена и фамилия родителей как написаны), village (местожительство), ages (возраст "
             "родителей), child_order (который ребёнок), notes (особые примечания, поздние пометки)",
    "marriage": "no (номер акта), date (дата записи), groom, bride (имена, фамилии, отчества как написаны), village "
                "(местожительство жениха и невесты), groom_birth, bride_birth (годы или даты рождения), status "
                "(холост/вдов, который брак), new_surname (фамилия после брака), notes (особые примечания)",
    "death": "no (номер акта), reg_date, death_date, name (имя, фамилия умершего), age, village, cause, notes",
}

SYSTEM = (
    "Ты читаешь скан страницы советской книги актов гражданского состояния 1918–1923 года (Смоленская губерния). "
    "Это печатная таблица, заполненная от руки; один акт — строка через весь разворот. Вырезки "
    "перекрываются, поэтому один и тот же акт может попасть в две — перечисли его один раз. Перепиши каждый акт "
    "буква в букву, как написано, старую орфографию сохраняй; ничего не исправляй и не додумывай. Неуверенные буквы "
    "или слова помечай [?], нечитаемое — [нрзб]. Если акт обрезан краем разворота — всё равно перечисли, что видно. "
    "Ответ — только JSON без пояснений: {\"acts\": [{...}, ...], \"remark\": \"что мешало читать\"}."
)


def book_dir(book: str) -> Path:
    d = GASO_RAW / book
    if not d.is_dir():
        sys.exit(f"нет папки {d}")
    return d


def scan(book: str, n: int) -> Path:
    return book_dir(book) / f"{book.removeprefix('ф')}_файл_{n:03d}.jpg"


def text_file(book: str, n: int) -> Path:
    return ARCHIVES_TEXT / "gaso" / book / f"{book.removeprefix('ф')}_файл_{n:03d}.txt"


def out_file(book: str, model: str, cut: str = "quarters") -> Path:
    """Одно чтение = модель + нарезка; файл на каждое."""
    return ARCHIVES_TEXT / "gaso" / book / f"zags_{model.replace(':', '_')}_{cut}.jsonl"


def months(args) -> int:
    """Карта книги: на каждом развороте — два самых частых месяца и год по тексту программы (грубо, но хватает,
    чтобы найти нужное окно: в акте о рождении месяц пишется дважды — рождения и записи)."""
    files = sorted((ARCHIVES_TEXT / "gaso" / args.book).glob("*_файл_*.txt"))
    for f in files:
        t = f.read_text(errors="ignore").lower()
        c = collections.Counter({roman: len(re.findall(stem + r"[а-яё]*", t)) for stem, roman in MONTHS})
        years = collections.Counter(re.findall(r"19(?:1[89]|2[0-3])", t))
        top = "/".join(f"{m}×{k}" for m, k in c.most_common(2) if k) or "-"
        year = years.most_common(1)[0][0] if years else ""
        print(f"{f.stem.rsplit('_', 1)[-1]}  {top:12} {year}")
    return 0


CUTS = {
    # четверти: верх/низ × левая/правая страница, нахлёст 10–16 %
    "quarters": [(0, 0, .55, .58), (.45, 0, 1, .58), (0, .42, .55, 1), (.45, .42, 1, 1)],
    # полосы для второго, независимого чтения: три полосы по высоте × левая/правая — другие края, другой масштаб
    "strips": [(0, 0, .55, .40), (.45, 0, 1, .40), (0, .30, .55, .70), (.45, .30, 1, .70), (0, .60, .55, 1),
               (.45, .60, 1, 1)],
}
CUT_NOTE = {
    "quarters": "Тебе дают четыре вырезки одного разворота: 1 — верх левой страницы, 2 — верх правой, 3 — низ левой, "
                "4 — низ правой.",
    "strips": "Тебе дают шесть вырезок одного разворота — три полосы сверху вниз, в каждой сначала левая страница, "
              "потом правая: 1–2 — верх, 3–4 — середина, 5–6 — низ.",
}


def crops(src: Path, folder: Path, cut: str = "quarters") -> list[Path]:
    """Вырезки разворота с нахлёстом (CUTS); серое, автоконтраст, длинная сторона ≤ 1500."""
    from PIL import Image, ImageOps
    img = ImageOps.autocontrast(Image.open(src).convert("L"), cutoff=1)
    w, h = img.size
    boxes = [(int(w * a), int(h * b), int(w * c), int(h * d)) for a, b, c, d in CUTS[cut]]
    out = []
    for i, box in enumerate(boxes, 1):
        part = img.crop(box)
        part.thumbnail((1500, 1500))
        p = folder / f"{src.stem}_{i}.jpg"
        part.save(p, quality=90)
        out.append(p)
    return out


def parse(answer: str) -> dict:
    m = re.search(r"\{.*\}", answer, re.S)
    try:
        return json.loads(m.group(0)) if m else {"acts": [], "remark": "нет JSON", "raw": answer[:2000]}
    except json.JSONDecodeError:
        return {"acts": [], "remark": "битый JSON", "raw": answer[:4000]}


def read_one(book: str, n: int, kind: str, model: str, cut: str = "quarters") -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        images = crops(scan(book, n), Path(tmp), cut)
        prompt = f"{CUT_NOTE[cut]}\nВид актов: {kind}. Поля каждого акта: {FIELDS[kind]}."
        answer = llm.ask(f"zags-{kind}", prompt, SYSTEM, model=model, image=images, timeout=600)
    return {"book": book, "n": n, "kind": kind, "model": model, "cut": cut, **parse(answer)}


def read(args) -> int:
    path = out_file(args.book, args.model, args.cut)
    path.parent.mkdir(parents=True, exist_ok=True)
    done = {json.loads(line)["n"] for line in path.open()} if path.exists() else set()
    todo = [n for n in range(args.start, args.end + 1) if n not in done and scan(args.book, n).exists()]
    print(f"{args.book}: {len(todo)} разворотов, модель {args.model}, нарезка {args.cut}", flush=True)

    def job(n):
        try:
            return read_one(args.book, n, args.kind, args.model, args.cut)
        except llm.Limit as e:
            return {"n": n, "limit": str(e)}

    with ThreadPoolExecutor(args.workers) as pool, path.open("a") as out:
        for row in pool.map(job, todo):
            if "limit" in row:
                print(f"стоп на {row['n']}: {row['limit']}", flush=True)
                break
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            print(f"{row['n']:03d}: актов {len(row.get('acts', []))} {row.get('remark', '')[:80]}", flush=True)
    return 0


def readings(book: str) -> dict[str, dict[int, dict]]:
    """{модель: {разворот: строка}} по всем чтениям этой книги."""
    out = {}
    for f in sorted((ARCHIVES_TEXT / "gaso" / book).glob("zags_*.jsonl")):
        rows = [json.loads(line) for line in f.open()]
        out[f.stem.removeprefix("zags_")] = {r["n"]: r for r in rows}
    return out


def hits(row: dict, terms: list[str]) -> list[dict]:
    pat = re.compile("|".join(re.escape(t) for t in terms), re.I)
    return [a for a in row.get("acts", []) if pat.search(json.dumps(a, ensure_ascii=False))]


def find(args) -> int:
    rs = readings(args.book)
    if not rs:
        sys.exit("чтений нет — сначала read")
    spreads = sorted(set().union(*rs.values()))
    print(f"{args.book}: чтения {', '.join(f'{m} ({len(r)})' for m, r in rs.items())}; ищу {args.terms}")
    for n in spreads:
        found = {m: hits(r[n], args.terms) for m, r in rs.items() if n in r}
        if not any(found.values()):
            continue
        agree = sum(bool(v) for v in found.values())
        print(f"\n== разворот {n:03d} — нашли {agree} из {len(found)} чтений")
        for m, acts in found.items():
            for a in acts:
                print(f"  [{m}] {json.dumps(a, ensure_ascii=False)}")
    # где чтения расходятся по числу актов — там одно из них могло пропустить акт
    if len(rs) > 1:
        odd = [n for n in spreads if len({len(r.get(n, {}).get("acts", [])) for r in rs.values() if n in r}) > 1]
        once = [n for n in spreads if sum(n in r for r in rs.values()) < len(rs)]
        print(f"\nчисло актов расходится: {odd or '—'}\nпрочитано одним чтением: {once or '—'}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("months")
    s.add_argument("book")
    s.set_defaults(fn=months)
    s = sub.add_parser("read")
    s.add_argument("book")
    s.add_argument("--kind", choices=FIELDS, required=True)
    s.add_argument("--from", dest="start", type=int, required=True)
    s.add_argument("--to", dest="end", type=int, required=True)
    s.add_argument("--model", default="sonnet")
    s.add_argument("--cut", choices=CUTS, default="quarters", help="второе чтение — strips")
    s.add_argument("--workers", type=int, default=3)
    s.set_defaults(fn=read)
    s = sub.add_parser("find")
    s.add_argument("book")
    s.add_argument("--terms", nargs="+", required=True)
    s.set_defaults(fn=find)
    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
