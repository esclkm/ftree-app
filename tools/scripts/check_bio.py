#!/usr/bin/env python3
"""Устройство биографии: один человек в файле, разделы в одном порядке, события по времени, рассказ, а не список.

Правила — 00_ИНДЕКС.md, «Как устроена биография» (и навык biography). Раздел человека — заголовок, за которым идёт строка
«**В дереве:**»; его разделы — заголовки на уровень ниже, до следующего заголовка того же уровня или выше.

  ОШИБКА  в файле больше одного человека (жена, дети, родители — своими файлами). Старые файлы родов (LEGACY ниже)
          пока только предупреждают — их разносим по людям, когда за них берёмся; разнёс — убери файл из LEGACY;
  ОШИБКА  разделы не в порядке: Линия жизни → Память (что было после смерти; сразу за линией жизни) → жизнь по темам → Семья → Каким был →
          Воспоминания → Награды → Расхождения → Открытые вопросы → «> Источники»;
  ОШИБКА  «Воспоминания»: текст не под «### Название»; у сценки нет первой строки курсивом «*Вспоминает [[…]], кто он ему · откуда*»;
  ОШИБКА  нет раздела «Открытые вопросы» (он есть у каждого, даже из одного пункта);
  ОШИБКА  строка «Линии жизни» раньше предыдущей по дате; тематический раздел с годом в заголовке раньше предыдущего;
  ВНИМАНИЕ  нет «Линии жизни»; нет строки «> Источники»;
  ВНИМАНИЕ  раздел о жизни — больше половины строк списком или таблицей: это конспект, а не рассказ;
  ВНИМАНИЕ  заголовок по источнику или по нашим задачам («Что добавила запись», «Аудио 05», «Сюжеты для книги»):
            раздел называют по теме жизни, откуда сведение — строкой курсивом в начале раздела.

  python3 tools/scripts/check_bio.py                 # все биографии
  python3 tools/scripts/check_bio.py --file "3_research/tree/biographies/Прокоп Ясенев — биография.md"
  python3 tools/scripts/check_bio.py --quiet         # одна строка-итог
Код выхода 1, если есть ошибки (предупреждения — нет).
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402
import dates  # noqa: E402

# старые файлы родов — несколько человек в файле, пока не разнесены (правило «одна биография — один человек» с 27.09.2026)
LEGACY = set()  # все старые файлы родов разнесены по людям (29.09.2026); новый человек — новый файл

HEAD = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*$")
IN_TREE = re.compile(r"^\*\*В дереве:\*\*")
KINDS = [  # (ранг, название, образец заголовка); всё прочее — «жизнь по темам», ранг 2
    (1, "Линия жизни", re.compile(r"^Линия жизни", re.I)),
    (1.5, "Память", re.compile(r"^Память$", re.I)),  # после смерти: музей, книга, доска — сразу за линией жизни
    (3, "Семья", re.compile(r"^(Семья|Жена и |Муж и |Дети|Братья|Сёстры|Сестры|Родители)", re.I)),
    (4, "Каким был", re.compile(r"^(Каким|Какой|Какая)\b", re.I)),
    (4.5, "Воспоминания", re.compile(r"^Воспоминания$", re.I)),  # сценки, которые кто-то помнит: ### Название, *Вспоминает …*
    (5, "Награды", re.compile(r"^Награды", re.I)),
    (6, "Расхождения", re.compile(r"^Расхождения", re.I)),
    (7, "Открытые вопросы", re.compile(r"^(Открытые вопросы|Что открыто)", re.I)),
    (8, "Источники", re.compile(r"^Источники", re.I)),
]
THEME = (2, "жизнь по темам")
SOURCES = (8, "> Источники")
BY_SOURCE = re.compile(r"Аудио\s*\d|что (добавил|дал|рассказал)|из (записи|разговора)|находк|для книги|сюжет|"
                       r"Карт[аы] поляка|заявлени", re.I)
DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})|(?<!\d)(1[6-9]\d\d|20\d\d)(?!\d)")


def plain(s):
    return re.sub(r"[*_`⭐⚠️✅🟡❓]", "", s).strip()


def when(cell):
    """Первая дата в ячейке: (год, месяц, день); месяц и день — 0, если известен только год."""
    m = DATE.search(cell)
    if not m:
        return None
    return (int(m[3]), int(m[2]), int(m[1])) if m[3] else (int(m[4]), 0, 0)


APPROX = re.compile(r"(\d)-?[ех]\b|\bок\.|~|≈|начал|конец|конц|середин|вероятно|\?", re.I)


def slack(cell):
    """Запас для приблизительной даты: «1950-е», «начало 1980-х» — до конца десятилетия; «ок. 1945», «~1975» — два года."""
    return 9 if re.search(r"\d-?[ех]\b", cell) else 2 if APPROX.search(cell) else 0


def latest(g):
    """Самый поздний момент, когда могло быть событие строки (дата по правилу GEDCOM, tools/scripts/dates.py):
    «ок. 1935» — 1937, «после 1945» и «с 1945» — сколько угодно поздно, «между 1941 и 1945» и «1941–1945» — 1945."""
    if g.kind in ("AFT", "FROM") and not g.b:
        return (9999, 12, 31)
    if g.kind in ("ABT", "CAL", "EST"):
        return (g.a.y + 2, 12, 31)
    y, m, d = (g.b or g.a).key()
    return (y, m or 12, d or 31)  # «апрель 1931» — до 30 апреля: не раньше, чем «14.04.1931»


def earliest(g):
    """Самый ранний момент, когда могло быть событие строки: «между 1937 и 1938» — 1937, «ок. 1935» — 1933,
    «до 1944» — сколько угодно рано. Строка, которая наверняка раньше начала предыдущей, — не по времени
    (дети одной матери: «между 1937 и 1938 — умер сын» стояло раньше «между 1936 и 1937 — родился сын»)."""
    if g.kind in ("BEF", "TO") or not g.a:
        return (0, 0, 0)
    if g.kind in ("ABT", "CAL", "EST"):
        return (g.a.y - 2, 0, 0)
    return g.a.key()


def earlier(a, b, give=0):
    """a раньше b? Если у одной из дат только год — сравниваем годы (1934 и 06.11.1934 — не нарушение)."""
    if give:
        return a[0] + give < b[0]
    return a < b if a[1] and b[1] else a[0] < b[0]


def blocks(lines):
    """Разделы людей: (номер строки заголовка, уровень, имя)."""
    out = []
    for i, line in enumerate(lines):
        m = HEAD.match(line)
        if not m:
            continue
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j < len(lines) and IN_TREE.match(lines[j]):
            out.append((i, len(m[1]), plain(m[2])))
    return out


def check_person(lines, start, level, name, persons, legacy=False):
    err, warn = [], []
    starts = {p[0] for p in persons}
    end = next((i for i in range(start + 1, len(lines)) if (m := HEAD.match(lines[i])) and len(m[1]) <= level), len(lines))
    secs, i = [], start + 1
    while i < end:  # разделы человека; вложенный человек (ребёнок внутри) — не раздел, пропускаем целиком
        m = HEAD.match(lines[i])
        if m and len(m[1]) == level + 1:
            if i in starts:
                sub = next((k for k in range(i + 1, end) if (h := HEAD.match(lines[k])) and len(h[1]) <= level + 1), end)
                i = sub
                continue
            title = plain(m[2])
            kind = next(((r, n) for r, n, rx in KINDS if rx.search(title)), THEME)
            s_end = next((k for k in range(i + 1, end) if (h := HEAD.match(lines[k])) and len(h[1]) <= level + 1), end)
            secs.append((i, title, kind, lines[i + 1:s_end]))
        i += 1
    src = next((k for k in range(start, end) if lines[k].startswith("> Источники")), None)

    where = lambda k: f"стр. {k + 1}"
    top = (0, "")
    for k, title, (rank, kname), _ in secs:
        if rank < top[0]:
            err.append(f"порядок: «{title}» ({kname}) стоит после раздела «{top[1]}» — {where(k)}")
        else:
            top = (rank, title)
    for n, (k, title, (rank, _), _) in enumerate(secs):
        if rank == 1.5 and any(r == 1 for _, _, (r, _), _ in secs) and (n == 0 or secs[n - 1][2][0] != 1):
            err.append(f"порядок: «Память» — сразу за «Линией жизни», без разделов между ними — {where(k)}")
    if src is not None and secs and src < secs[-1][0] and secs[-1][2][0] != 8:
        err.append(f"порядок: «> Источники» ({where(src)}) — не в конце, после него ещё разделы")
    if not any(kind[0] == 7 for _, _, kind, _ in secs):
        err.append("нет раздела «Открытые вопросы»")
    if not legacy and not any(kind[0] == 1 for _, _, kind, _ in secs):  # в старых файлах родов у упомянутых — нет, и это
        warn.append("нет «Линии жизни»")                                 # не новость: заведём, когда разнесём по файлам
    if not legacy and src is None and not any(kind[0] == 8 for _, _, kind, _ in secs):
        warn.append("нет строки «> Источники»")

    prev = None
    for k, title, (rank, _), body in secs:
        if rank == 1:  # строки таблицы по времени
            last = None
            for n, row in enumerate(body):
                cells = [c.strip() for c in row.replace("\\|", "\x00").strip().strip("|").split("|")]
                if not row.startswith("|") or len(cells) < 2 or re.fullmatch(r"[\s|:-]+", row) or plain(cells[0]).lower() in ("когда", "год", "дата"):
                    continue
                g = dates.ru_or_none(cells[0])
                if g is None:  # не по правилу дат — это скажет check_dates.py; здесь — как раньше, по первой дате
                    d = when(cells[0])
                    if d is None:
                        continue
                    if last and earlier(d, last[0], slack(cells[0])):
                        err.append(f"линия жизни не по времени: «{plain(cells[0])[:30]}» после «{last[1][:30]}» — {where(k + 1 + n)}")
                    if not slack(cells[0]) and (not last or not earlier(d, last[0])):
                        last = (d, plain(cells[0]))  # приблизительная дата — не опора для следующих строк
                    continue
                if g.kind == "PHRASE":
                    continue
                # не по времени — только если строка наверняка раньше опоры: «после 1945» после «1949» — можно,
                # «до 1941» после «1949» — нельзя
                if last and earlier(latest(g), last[0]):
                    err.append(f"линия жизни не по времени: «{plain(cells[0])[:30]}» после «{last[1][:30]}» — {where(k + 1 + n)}")
                # опора — начало строки (у точной даты — сама дата): следующая не может быть наверняка раньше
                if not last or not earlier(earliest(g), last[0]):
                    last = (earliest(g), plain(cells[0]))
        if rank == 2:
            if (d := when(title)) and prev and earlier(d, prev[0]):
                err.append(f"разделы не по времени: «{title}» после «{prev[1]}» — {where(k)}")
            if d and (not prev or not earlier(d, prev[0])):
                prev = (d, title)
            text = [x for x in body if x.strip() and not x.startswith(("#", ">", "---", "*А", "*Аудио"))]
            listed = [x for x in text if re.match(r"\s*([-*+]|\d+\.)\s|\s*\|", x)]
            if len(text) >= 4 and len(listed) * 2 > len(text):
                warn.append(f"«{title}» — {len(listed)} из {len(text)} строк списком или таблицей: конспект, а не рассказ — {where(k)}")
        if rank == 4.5:
            err += recollections(body, k + 1, where)
        if BY_SOURCE.search(title):
            warn.append(f"заголовок «{title}» — по источнику или нашим задачам, а не по теме жизни — {where(k)}")
    return err, warn


RECOLL_BY = re.compile(r"^\*(Вспомина\w+|Со слов|Рассказ\w*)\b[^*]+\*\s*$")


def recollections(body, first, where):
    """«Воспоминания»: каждая сценка — «### Название», первой строкой — курсивом, кто вспоминает и откуда."""
    err, title = [], None
    for n, line in enumerate(body):
        if (m := HEAD.match(line)):
            title = plain(m[2])
            nxt = next((x for x in body[n + 1:] if x.strip()), "")
            if not RECOLL_BY.match(nxt.strip()):
                err.append(f"«Воспоминания» › «{title}»: первой строкой — курсивом, кто вспоминает и откуда "
                           f"(*Вспоминает [[…]], внучка · А08, 53:25*) — {where(first + n)}")
        elif title is None and line.strip() and not line.startswith("---"):
            err.append(f"«Воспоминания»: текст до первой сценки — каждая под своим «### Название» — {where(first + n)}")
            title = ""
    return err


def check_file(p):
    lines = p.read_text(encoding="utf-8").splitlines()
    persons = blocks(lines)
    err, warn = [], []
    if len(persons) > 1:
        names = ", ".join(n.split(" — ")[0] for _, _, n in persons)
        msg = f"в файле {len(persons)} человек ({names}) — одна биография = один человек"
        (warn if p.name in LEGACY else err).append(msg + (" [старый файл рода — разнести]" if p.name in LEGACY else ""))
    elif p.name in LEGACY:
        warn.append("файл в LEGACY, а человек в нём один — убрать из списка LEGACY в check_bio.py")
    if not persons:
        warn.append("нет строки «**В дереве:**» под заголовком — скрипты и сайт не знают, чья это биография")
    for start, level, name in persons:
        e, w = check_person(lines, start, level, name, persons, p.name in LEGACY)
        tag = f"{name.split(' — ')[0]}: " if len(persons) > 1 else ""
        err += [tag + x for x in e]
        warn += [tag + x for x in w]
    return err, warn


def main():
    args = sys.argv[1:]
    if "--file" in args:
        files = [paths.ROOT / args[args.index("--file") + 1]]
    else:
        files = sorted(paths.BIOS.glob(f"*{paths.BIO_SUFFIX}.md"))
    n_err = n_warn = 0
    for p in files:
        err, warn = check_file(p)
        n_err += len(err)
        n_warn += len(warn)
        if (err or warn) and "--quiet" not in args:
            print(p.relative_to(paths.ROOT).as_posix())
            print("\n".join(f"  ✗ {x}" for x in err) + ("\n" if err and warn else "") + "\n".join(f"  · {x}" for x in warn))
            print()
    print(f"Биографии: файлов {len(files)}, ошибок {n_err}, предупреждений {n_warn}")
    return 1 if n_err else 0


if __name__ == "__main__":
    sys.exit(main())
