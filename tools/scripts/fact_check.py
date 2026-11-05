#!/usr/bin/env python3
"""Сверка фактов: каждый факт карточки — с источником (говорит ли он именно это) и с биографией (рассказан ли там).

Зачем. `card_doctor` и `check_cards` проверяют, что у факта **есть** ссылка на источник. Что источник говорит **именно это**
и что биография человека этот факт **рассказывает** и ему **не противоречит** — не проверяет никто: это читают глазами.
Фактов больше 1400 — за раз не прочесть. Скрипт подбирает к каждому факту то, что нужно прочитать (отрывок расшифровки
на указанном месте и строку биографии), и ведёт журнал: что сверено, с каким итогом. Порядок работы — скилл
self-review, линза О13.

Журнал — 3_research/tree_data/fact_checks.tsv, одна строка — один факт:
  ключ (cr_id человека + отпечаток строки факта) · человек · источник · биография · дата · примечание
  источник:  ✅ говорит это · ❌ говорит другое (карточку исправить) · ❓ места не нашёл / нечем проверить
  биография: ✅ рассказано · ➕ дописал в биографию · ❌ биография противоречит (исправить) · — не для биографии (почему)
Факт поправили — отпечаток другой, и он снова «не сверен»: старую отметку на новый текст не переносим.

  python3 tools/scripts/fact_check.py status                     # сколько сверено, что осталось, что с ошибкой
  python3 tools/scripts/fact_check.py next -n 10                 # следующие несверенные: факт, отрывок источника, биография
  python3 tools/scripts/fact_check.py next --person "Прокоп Ясенев"   # или часть имени / cr_id
  python3 tools/scripts/fact_check.py next --source "Аудио 06"   # по одному источнику — расшифровка уже в голове
  python3 tools/scripts/fact_check.py mark <ключ> source=✅ bio=➕ note="дописал в «Вербичи, 1875–1921»"
"""
import csv
import datetime
import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402
import cards  # noqa: E402

LEDGER = paths.TREE_DATA / "fact_checks.tsv"
COLS = ["key", "person", "source", "bio", "date", "note"]
SRC_OK, BIO_OK = {"✅", "❌", "❓"}, {"✅", "➕", "❌", "—"}
TIME = re.compile(r"(?<![\d:])(?:(\d):)?(\d{1,2}):(\d{2})(?![\d:])")
MARK = re.compile(r"^[\s>*-]*(?:[^\W\d_]{1,10}\s*)?\[(?:(\d):)?(\d{1,2}):(\d{2})")
PAGE = re.compile(r"(?:стр|с|л|раздел)\.?\s*(\d+(?:\s*[–-]\s*\d+)?(?:\s*,\s*\d+(?:\s*[–-]\s*\d+)?)*)", re.I)
STOP = set("было была были будет этого этой того тоже когда потом после перед через около между всех всего всегда "
           "очень только чтобы который которая которые своей своего свою годы года году лет".split())


def key_of(person, fact):
    raw = "|".join([fact.label, fact.text, *(f"{r.source}@{r.locator}" for r in fact.refs)])
    return f"{person.id}:{hashlib.sha1(raw.encode()).hexdigest()[:10]}"


def load_ledger():
    if not LEDGER.exists():
        return {}
    with LEDGER.open(encoding="utf-8") as f:
        return {r["key"]: r for r in csv.DictReader(f, delimiter="\t")}


def save_ledger(rows):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, COLS, delimiter="\t")
        w.writeheader()
        for k in sorted(rows):
            w.writerow({c: rows[k].get(c, "") for c in COLS})


def words(s):
    """Опорные слова факта: числа целиком, слова — по первым 5 буквам (падежи не мешают)."""
    s = re.sub(r"\[\[([^\]|]+\|)?([^\]]+)\]\]", r"\2", s.lower())
    nums = set(re.findall(r"\d{2,4}", s))
    ws = {w[:5] for w in re.findall(r"[^\W\d_]{4,}", s) if w not in STOP}
    return nums | ws


def score(line, keys):
    return len(keys & words(line))


def transcripts(src):
    found = re.findall(re.escape(paths.rel(paths.TRANSCRIPTS)) + r"/[^\]|)`\n]+?\.md", src.body + str(src.fm))
    return [p for p in dict.fromkeys(paths.ROOT / x for x in found) if p.exists()]


def pages_in(s):
    """Номера страниц из «стр. 3–4, 16» → {3, 4, 16}."""
    out = set()
    for m in PAGE.finditer(s):
        for part in m[1].split(","):
            a, _, b = part.replace("–", "-").partition("-")
            out |= set(range(int(a), int(b or a) + 1))
    return out


def secs(m):
    return int(m[1] or 0) * 3600 + int(m[2]) * 60 + int(m[3])


def region(lines, locator):
    """Строки файла на месте, указанном в факте: по времени записи («54:39–54:48») или по странице («стр. 5»)."""
    ts = [secs(m) for m in TIME.finditer(locator)]
    if ts:
        a, b = min(ts) - 30, max(ts) + 30
        keep, on = [], False
        for i, line in enumerate(lines):
            m = MARK.match(line)  # метка в начале реплики: «**[53:21] Павел.**», «- [03:35] **О:**», «> **О [10:20]:**»
            if m:
                on = a <= secs(m) <= b
            elif line.startswith("#"):
                h = [secs(x) for x in TIME.finditer(line)]
                on = bool(h) and h[0] <= b and h[-1] >= a
            if on:
                keep.append(i)
        return keep
    pages = pages_in(locator)
    if pages:
        keep, on = [], False
        for i, line in enumerate(lines):
            if line.startswith("#"):
                on = bool(pages_in(line) & pages)
            elif re.search(r"(стр\.|страница)\s*(\d+)", line) and not line.startswith(("-", "|")):
                n = int(re.search(r"(стр\.|страница)\s*(\d+)", line)[2])
                on = n in pages or on
            if on:
                keep.append(i)
        return keep
    return []


def excerpt(src, locator, keys, width=6):
    """Лучшие строки расшифровки: на указанном месте, а если места нет или оно не найдено — во всём файле."""
    out = []
    for p in transcripts(src):
        lines = p.read_text(encoding="utf-8").splitlines()
        area = region(lines, locator)
        pool = area or range(len(lines))
        need = 1 if area else 2  # вне указанного места — только строки, где совпало хотя бы два опорных слова
        best = sorted((i for i in pool if lines[i].strip() and not lines[i].startswith("#")),
                      key=lambda i: -score(lines[i], keys))[:width if area else 3]
        best = [i for i in best if score(lines[i], keys) >= need] or list(area[:width])
        for i in sorted(best):
            out.append((p, i + 1, lines[i].strip(), bool(area)))
    return out


def bio_of(b, person):
    d = next((d for d in b.people.values() if d["id"] == person.id), None)
    return b.bio_text(d) if d else ""


def bio_match(text, keys):
    """Строка биографии, где факт рассказан лучше всего, и какие опорные слова факта в биографии не встретились."""
    if not text:
        return None, keys
    lines = [x.strip() for x in text.splitlines() if x.strip() and not x.startswith(("#", "> ", "---"))]
    best = max(lines, key=lambda x: score(x, keys), default="")
    all_words = words(text)
    return (best if score(best, keys) else None), {k for k in keys if k not in all_words}


def facts(tree):
    for p in sorted(tree.people.values(), key=lambda p: p.stem):
        for f in p.facts:
            yield p, f


def status(tree, rows):
    total = src_done = bio_done = 0
    bad = []
    keys = set()
    for p, f in facts(tree):
        k = key_of(p, f)
        keys.add(k)
        total += 1
        r = rows.get(k)
        if r and r["source"] in SRC_OK:
            src_done += 1
        if r and r["bio"] in BIO_OK:
            bio_done += 1
        if r and ("❌" in (r["source"], r["bio"])):
            bad.append((p, f, r))
    stale = len(set(rows) - keys)
    print(f"Фактов {total}: сверено с источником {src_done}, с биографией {bio_done}; "
          f"не сверено {total - min(src_done, bio_done)}; отметок на изменённые или удалённые факты {stale}")
    for p, f, r in bad:
        print(f"  ❌ {p.stem}, стр. {f.line}: {f.label}: {f.text[:80]} — источник {r['source']} биография {r['bio']} · {r['note']}")
    return 1 if bad else 0


def show(tree, rows, n, who, src_filter):
    import site_export as b  # биография человека — так же, как её собирает сайт
    shown = 0
    for p, f in facts(tree):
        k = key_of(p, f)
        r = rows.get(k, {})
        if r.get("source") in SRC_OK and r.get("bio") in BIO_OK:
            continue
        if who and who.lower() not in (p.stem + " " + p.id).lower():
            continue
        titles = [tree.sources[x.source].stem if x.source in tree.sources else x.source for x in f.refs]
        if src_filter and not any(src_filter.lower() in t.lower() for t in titles):
            continue
        label = f.label or (f.date.ru() if f.date else "")
        keys = words(label + " " + f.text)
        card = (paths.TREE / "people" / f"{p.stem}.md").relative_to(paths.ROOT).as_posix()
        print(f"━━ {k}  {card}:{f.line}")
        print(f"   ФАКТ: **{label}:** {f.text}   · уверенность: {f.confidence} · {f.provenance}")
        for ref, title in zip(f.refs, titles):
            print(f"   ИСТОЧНИК: {title} — {ref.locator or 'место не указано'}")
            src = tree.sources.get(ref.source)
            ex = excerpt(src, ref.locator, keys) if src else []
            if not ex:
                print("     (расшифровки нет — сверять с оригиналом или заметкой-источником" +
                      (f": {src.stem}.md" if src else "") + ")")
            for path, line, text, on_place in ex:
                mark = "  " if on_place else "? "  # «?» — строка не с указанного места, а найдена поиском по файлу
                print(f"     {mark}{path.relative_to(paths.ROOT).as_posix()}:{line}  {text[:260]}")
        best, missing = bio_match(bio_of(b, p), keys)
        if best is None and not bio_of(b, p):
            print("   БИОГРАФИЯ: нет биографии у человека")
        else:
            print(f"   БИОГРАФИЯ: {(best or '— не нашёл похожей строки')[:300]}")
            nums = {m for m in missing if m.isdigit()}
            if nums:
                print(f"     в биографии нет чисел факта: {', '.join(sorted(nums))}")
        print()
        shown += 1
        if shown >= n:
            break
    if not shown:
        print("Несверенных фактов по этому отбору нет.")


def mark(rows, args):
    k = args[0]
    vals = dict(a.split("=", 1) for a in args[1:] if "=" in a)
    r = rows.get(k, {"key": k})
    if "source" in vals and vals["source"] not in SRC_OK:
        sys.exit(f"source= — одно из {' '.join(sorted(SRC_OK))}")
    if "bio" in vals and vals["bio"] not in BIO_OK:
        sys.exit(f"bio= — одно из {' '.join(sorted(BIO_OK))}")
    if vals.get("bio") == "—" and not vals.get("note"):
        sys.exit("bio=— только с примечанием note=\"почему этот факт не для биографии\"")
    r.update(vals, date=datetime.date.today().isoformat())
    tree = cards.load()
    r["person"] = tree.people[k.split(":")[0]].stem if k.split(":")[0] in tree.people else r.get("person", "")
    rows[k] = r
    save_ledger(rows)
    print(f"{k}: источник {r.get('source', '')} · биография {r.get('bio', '')}")


def main():
    a = sys.argv[1:] or ["status"]
    rows = load_ledger()
    if a[0] == "mark":
        return mark(rows, a[1:])
    tree = cards.load()
    if a[0] == "next":
        opt = lambda name, default=None: a[a.index(name) + 1] if name in a else default
        return show(tree, rows, int(opt("-n", 10)), opt("--person"), opt("--source"))
    return status(tree, rows)


if __name__ == "__main__":
    sys.exit(main() or 0)
