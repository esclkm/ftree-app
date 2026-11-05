#!/usr/bin/env python3
"""Журнал поиска — где и кого уже искали, чтобы не искать и не платить дважды.

Зачем. Каждый заход на платный или строгий сайт (FamilySearch, «Грыц», ГАСО) стоит денег, лимита запросов или
токенов на чтение снимков. ПОИСК_СДЕЛАНО.md помнит задачи целиком, а этот журнал — мелко: какой запрос задали,
какие кадры какой плёнки прочли, кого там искали и что вышло. Перед новым заходом — сюда.

Журнал — `<папка поиска>/ИСКАЛИ_журнал.tsv` (paths.SEARCH_LOG), одна строка — один заход:
    дата · источник · что (плёнка, дело, запрос) · кадры · кого искали · как · итог · отчёт · состояние

Состояние — чем кончился заход, одним словом (с 04.11.2026; мысль из ex-ussr-kinship-research, MIT):
    нашлось · пусто · частично · не дошло · закрыто · нет указателя   (что значит каждое — STATES ниже)
Главное: «пусто» — источник ответил, а записей нет; «не дошло» и «закрыто» — не ответ вовсе, искать там снова.
Не указано (`--state`) — берётся из итога: «⛔…» → пусто, «✅/🟢/⭐/🟡/🟠/⚪…» → нашлось, «429», «капча» → не дошло.

    tools/py tools/scripts/searched.py frames 007700001 9-46  # какие из кадров уже читали (журнал + скачанное)
    tools/py tools/scripts/searched.py query "Ясен*"          # задавали ли такой запрос
    tools/py tools/scripts/searched.py who "Агата Ясенева"    # где искали человека (имя или cr_id)
    tools/py tools/scripts/searched.py add familysearch "плёнка 007700002" "520,524" "Ясеневы" "кадры, sonnet" "⛔ …" findings/….md
    tools/py tools/scripts/searched.py add … "<итог>" "" --state "не дошло"   # состояние явно, если по итогу не понять
    tools/py tools/scripts/searched.py open                        # куда стоит вернуться: «не дошло», «частично», «закрыто»
    tools/py tools/scripts/searched.py check                       # журнал в порядке: поля, отчёты на месте

Кадры пишем списком и промежутками: «9,16,18-46». Имена — как в карточке; cr_id — через пробел после имени.
known.py читает журнал сам (он .tsv в папке поиска), так что сверка «было раньше» видит и его.
"""
import argparse
import datetime
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import paths  # noqa: E402

LOG = paths.SEARCH_LOG
COLS = ["дата", "источник", "что", "кадры", "кого искали", "как", "итог", "отчёт", "состояние"]
STATES = {
    "нашлось": "источник ответил, записи по запросу есть (наши ли — в итоге)",
    "пусто": "источник ответил или прочитано всё задуманное — записей нет",
    "частично": "прочитано или получено не всё задуманное — остаток в итоге",
    "не дошло": "отказ сайта (429, 401), капча, сбой, пауза — это не результат",
    "закрыто": "доступа нет: 403, только в центре, платно, Image Restricted",
    "нет указателя": "на эти годы или плёнку указателя нет — искать по кадрам",
}
NOT_READ = ("не дошло", "закрыто")   # кадры таких заходов не прочитаны — «уже читали» их не считает
STATE_SINCE = "2026-11-05"   # строки раньше — до поля; там, где по итогу не понять, состояние пустое
SOURCES = {"familysearch", "hryc", "gaso", "radzima", "familio", "geneteka", "gwar", "rusneb", "szukajwarchiwach",
           "yandex", "lvia", "другое"}


def read_log(path=None):
    path = Path(path or LOG)
    if not path.exists():
        return []
    rows = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if i == 0 or not line.strip():
            continue
        cells = line.split("\t") + [""] * len(COLS)
        rows.append(dict(zip(COLS, cells[:len(COLS)])))
    return rows


def parse_frames(text):
    """«9,16,18-20» → {9, 16, 18, 19, 20}. Слова и пустое — пустое множество."""
    out = set()
    for part in re.split(r"[,\s]+", text or ""):
        m = re.fullmatch(r"(\d+)(?:[-–](\d+))?", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2) or m.group(1))
            out.update(range(min(a, b), max(a, b) + 1))
    return out


def film_of(what):
    m = re.search(r"\b(\d{9})\b", what or "")
    return m.group(1) if m else ""


def frames_on_disk(film):
    """Номера кадров, которые уже лежат в сырье: имена «…_к123_…», «…_i63_…», «…_сн62__…», «<плёнка>_0669.jpg»."""
    got = set()
    base = paths.ARCHIVES_RAW / "familysearch"
    if not base.exists():
        return got
    for d in base.iterdir():
        if not d.is_dir() or not d.name.startswith(film):
            continue
        for p in d.iterdir():
            m = (re.search(r"_к(\d+)_", p.name) or re.search(r"_i(\d+)_", p.name)
                 or re.search(r"_сн(\d+)_", p.name) or re.fullmatch(rf"{film}_(\d+)\.\w+", p.name))
            if m:
                got.add(int(m.group(1)))
    return got


def norm(s):
    return (s or "").lower().replace("ё", "е")


def guess_state(result):
    """Состояние по тексту итога или None. Нашли наше (✅🟢⭐) — «нашлось»; иначе сначала беды (не дошло,
    закрыто), потом неполнота, потом значок в начале."""
    t = norm(result).strip()
    if t.startswith(("✅", "🟢", "⭐")):   # нашли наше — даже если по пути что-то не открылось
        return "нашлось"
    if re.search(r"\b429\b|капч|не дошло|не ответил|сбой|таймаут|взял паузу|сайт лежал|не открыл", t):
        return "не дошло"
    if re.search(r"\b403\b|закрыт|только в центре|restricted|вне просмотра|платн", t):
        return "закрыто"
    if re.search(r"не проиндекс|нет указател|указател[ья] нет", t):
        return "нет указателя"
    if t.startswith("⏳") or re.search(r"не читано|не дочитан|частичн|не все кадры|остаток|не прочитан", t):
        return "частично"
    if t.startswith(("⛔", "пусто", "нет ", "0 ", "наших нет")):
        return "пусто"
    if t.startswith(("✅", "🟢", "⭐", "🟡", "🟠", "⚪", "⚠", "нашл")):
        return "нашлось"
    return None


def cmd_frames(a):
    want = parse_frames(a.frames) if a.frames else None
    seen = {}
    for r in read_log():
        if film_of(r["что"]) != a.film or r["состояние"] in NOT_READ:
            continue
        for n in parse_frames(r["кадры"]):
            seen.setdefault(n, []).append(f'{r["дата"]} {r["итог"][:70]}')
    disk = frames_on_disk(a.film)
    pool = want if want is not None else (set(seen) | disk)
    if not pool:
        print(f"плёнка {a.film}: в журнале и в сырье ничего")
        return 0
    read = sorted(n for n in pool if n in seen)
    only_disk = sorted(n for n in pool if n in disk and n not in seen)
    new = sorted(n for n in pool if n not in seen and n not in disk)
    print(f"плёнка {a.film}: читали {len(read)}, только скачано {len(only_disk)}, новых {len(new)}")
    for n in read:
        print(f"  {n}: {'; '.join(seen[n])}")
    if only_disk:
        print("  скачано, в журнале нет:", fmt_frames(only_disk))
    if new and want is not None:
        print("  новые:", fmt_frames(new))
    return 0


def fmt_frames(nums):
    nums = sorted(nums)
    out, i = [], 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        out.append(str(nums[i]) if i == j else f"{nums[i]}-{nums[j]}")
        i = j + 1
    return ",".join(out)


def cmd_query(a):
    q = norm(a.text).strip("*")
    hits = [r for r in read_log() if q in norm(r["что"])]
    print(f"«{a.text}»: заходов {len(hits)}")
    for r in hits:
        print(f'  {r["дата"]} {r["источник"]}: {r["что"]} → {tag(r)}{r["итог"][:100]}  [{r["отчёт"]}]')
    return 0


def tag(r):
    """«[не дошло] » перед итогом — где заход ничего не решил."""
    return f'[{r["состояние"]}] ' if r.get("состояние") in ("не дошло", "закрыто", "частично", "нет указателя") else ""


def cmd_open(a):
    """Куда вернуться: последний заход по тому же «что» кончился не ответом и не «пусто»."""
    last = {}
    for r in read_log():
        last[(r["источник"], r["что"])] = r
    todo = [r for r in last.values() if r["состояние"] in ("не дошло", "частично", "закрыто", "нет указателя")]
    if a.source:
        todo = [r for r in todo if r["источник"] == a.source]
    print(f"незакрытых заходов: {len(todo)}")
    for st in ("не дошло", "частично", "нет указателя", "закрыто"):
        rows = [r for r in todo if r["состояние"] == st]
        if rows:
            print(f"  {st} ({len(rows)}) — {STATES[st]}:")
            for r in sorted(rows, key=lambda r: r["дата"]):
                print(f'    {r["дата"]} {r["источник"]}: {r["что"][:80]} → {r["итог"][:80]}')
    return 0


def cmd_who(a):
    keys = [norm(k) for k in a.name.split("|")]
    hits = [r for r in read_log() if any(k in norm(r["кого искали"] + " " + r["итог"]) for k in keys)]
    print(f"«{a.name}»: заходов {len(hits)}")
    for r in hits:
        print(f'  {r["дата"]} {r["источник"]}: {r["что"]} [{r["кадры"] or "—"}] → {tag(r)}{r["итог"][:100]}  [{r["отчёт"]}]')
    return 0


PAVEL_PREFIX = paths.PAVEL.relative_to(paths.ROOT).as_posix() + "/"   # «<папка поиска>/»


def norm_report(report):
    """Путь к отчёту в журнале — от папки <папка поиска>/ («findings/….md»); путь от корня проекта обрезаем."""
    report = report.strip()
    return report[len(PAVEL_PREFIX):] if report.startswith(PAVEL_PREFIX) else report


def report_error(report):
    """Почему отчёт не найден и как исправить; пусто — всё в порядке."""
    if not report or (paths.PAVEL / report).exists():
        return ""
    if report.startswith(PAVEL_PREFIX) and (paths.ROOT / report).exists():
        return (f"путь от корня проекта, а нужен от папки {PAVEL_PREFIX} — "
                f"заменить на «{norm_report(report)}»")
    return f"файла нет: искали {PAVEL_PREFIX}{report} — проверить имя или убрать отчёт из строки"


def cmd_add(a):
    if a.source not in SOURCES:
        sys.exit(f"источник «{a.source}» — один из: {', '.join(sorted(SOURCES))}")
    a.report = norm_report(a.report)
    if err := report_error(a.report):
        sys.exit(f"отчёт «{a.report}»: {err}. Сначала сохранить отчёт, потом запись в журнал.")
    state = getattr(a, "state", None) or guess_state(a.result)
    if state not in STATES:
        sys.exit(f"состояние «{state or ''}» не понять по итогу — добавить --state: " + " | ".join(STATES)
                 if not state else f"состояние «{state}» — одно из: {' | '.join(STATES)}")
    row = [a.date or datetime.date.today().isoformat(), a.source, a.what, a.frames, a.whom, a.how, a.result, a.report,
           state]
    if any("\t" in c or "\n" in c for c in row):
        sys.exit("в полях не должно быть TAB и переноса строки")
    new = not LOG.exists()
    with LOG.open("a", encoding="utf-8") as f:
        if new:
            f.write("\t".join(COLS) + "\n")
        f.write("\t".join(row) + "\n")
    print("записано:", " · ".join(c for c in row if c))
    return 0


def check(path=None):
    """Ошибки журнала: число полей, дата, источник, отчёт на месте."""
    path = Path(path or LOG)
    errs = []
    if not path.exists():
        return errs
    lines = path.read_text(encoding="utf-8").splitlines()
    if lines and lines[0].split("\t") != COLS:
        errs.append("шапка не та: " + "\t".join(COLS))
    for i, line in enumerate(lines[1:], 2):
        if not line.strip():
            continue
        cells = line.split("\t")
        if len(cells) != len(COLS):
            errs.append(f"строка {i}: полей {len(cells)}, нужно {len(COLS)}")
            continue
        r = dict(zip(COLS, cells))
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["дата"]):
            errs.append(f"строка {i}: дата «{r['дата']}» — нужно ГГГГ-ММ-ДД")
        if r["источник"] not in SOURCES:
            errs.append(f"строка {i}: источник «{r['источник']}»")
        if r["состояние"] not in STATES and not (r["состояние"] == "" and r["дата"] < STATE_SINCE):
            errs.append(f"строка {i}: состояние «{r['состояние']}» — одно из: {' | '.join(STATES)}")
        if err := report_error(r["отчёт"]):
            errs.append(f"строка {i} ({r['дата']}, {r['источник']}): отчёт «{r['отчёт']}» — {err}")
    return errs


def cmd_check(a):
    errs = check()
    for e in errs:
        print("ОШИБКА ", e)
    print(f"Журнал поиска: строк {len(read_log())}, ошибок {len(errs)}")
    return 1 if errs else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("frames"); p.add_argument("film"); p.add_argument("frames", nargs="?"); p.set_defaults(f=cmd_frames)
    p = sub.add_parser("query"); p.add_argument("text"); p.set_defaults(f=cmd_query)
    p = sub.add_parser("who"); p.add_argument("name"); p.set_defaults(f=cmd_who)
    p = sub.add_parser("add")
    for n in ("source", "what", "frames", "whom", "how", "result", "report"):
        p.add_argument(n)
    p.add_argument("--date"); p.add_argument("--state", help=" | ".join(STATES)); p.set_defaults(f=cmd_add)
    p = sub.add_parser("open"); p.add_argument("source", nargs="?"); p.set_defaults(f=cmd_open)
    p = sub.add_parser("check"); p.set_defaults(f=cmd_check)
    a = ap.parse_args(argv)
    return a.f(a)


if __name__ == "__main__":
    sys.exit(main())
