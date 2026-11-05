#!/usr/bin/env python3
r"""Проверка «Линии жизни» — в ней только жизнь самого человека (правило: навык biography и 00_ИНДЕКС.md, «Как устроена
биография», п. 2).

Берёт ту же таблицу, что показывает сайт (site_export: биография человека → строки линии жизни), и ищет:

  ОШИБКА  строка позже его смерти («после смерти — ничего»): музей, книга, доска, перезахоронение — в «## Память»;
  ОШИБКА  «## Память» (таблица «Когда | Что | Где» сразу за линией жизни — что было после смерти): строка раньше
          смерти; «Память» у человека без даты смерти в карточке (died — хотя бы AFT 1945); пусто в «Где»;
  ОШИБКА  строка раньше его рождения;
  ОШИБКА  внуки и правнуки — ссылкой на карточку внука;
  ВНИМАНИЕ  слово «внук/внучка/правнук» в строке — бывает и честно («опознал внук Павел»), посмотреть глазами;
  ВНИМАНИЕ  событие ребёнка, кроме рождения и смерти при его жизни (свадьба, переезд, работа): оно — в линию самого
            ребёнка; у родителя остаётся, только если меняет жизнь родителя. Если так и есть — строку в список
            «так и задумано» (OK: ftree.toml, [lifeline] ok), и предупреждение замолчит.
  ОШИБКА  смерть ребёнка стоит в таблице раньше его рождения или в его карточке died раньше born;
  ОШИБКА  нет строки о рождении ребёнка, который есть в карточке (`children`) и родился при жизни родителя;
  ОШИБКА  нет строки о смерти ребёнка, умершего при жизни родителя (обе даты смерти известны);
  ВНИМАНИЕ  дети одной строкой («Прокоп (1961), Анна (1964), Мария (1973)», «умерли дочь и сын») — у каждого
            ребёнка своя строка: рождение ребёнка — всегда главное событие жизни. Строка с двумя детьми и больше
            за их рождение (смерть) не считается — --fix ставит отдельные, общую убрать руками;
  ВНИМАНИЕ  у ребёнка нет даты рождения в карточке — строку не поставить: оценить `born` (EST 1905) по братьям и сёстрам;
  ОШИБКА  ссылка `[[Карточка|Имя]]` в строке таблицы без `\|` — «|» делит ячейку, и на сайте строка разваливается.
  ОШИБКА  нет колонки «Где» или она пустая в строке: в каждой строке — город или деревня, где он был тогда, ссылкой
          на карточку места (`[[Лодзь]]`); так видно переезды и понятно, в каком архиве искать. На сайте колонки нет;
  ВНИМАНИЕ  «Где» — «?» (не знаем: искать) или без ссылки на карточку места (завести карточку).

  --fix  вписывает недостающее само: строку «Родился сын [[Карточка|Имя]]» / «Умерла дочь …» с датой из карточки
         ребёнка — на своё место по времени, в колонку «Откуда» (или в скобках) — «дерево», в «Где» — место рождения
         (смерти) из карточки ребёнка или «?»; «|» в ссылках — `\|`.
         Так ребёнок, добавленный в дерево, сам появляется в линиях жизни обоих родителей (зовут хук после правки
         карточки и pre-commit, sync.py). Ребёнок узнаётся по ссылке, по имени (в том числе русскому) или по дате
         рождения в строке «родился/родилась».

Общая биография на двоих (старые файлы родов, где супруги в одном разделе) проверяется как одна: смерть — поздняя
из двух, дети — общие. Новое так не пишем: одна биография — один человек.
Строка «потом» / «позже» без года получает год предыдущей строки (как на сайте).

  python3 tools/scripts/check_lifeline.py              # все люди с биографией
  python3 tools/scripts/check_lifeline.py "Прокоп Ясенев"
  python3 tools/scripts/check_lifeline.py --file "3_research/tree/biographies/Прокоп Ясенев — биография.md"
                                                       # только люди, чья биография в этом файле (так зовёт хук)
  python3 tools/scripts/check_lifeline.py --fix --kin "Анна Ясенева"
                                                       # человек и его родители (так зовёт хук после правки карточки)
Код выхода 1, если есть ошибки (предупреждения — нет).
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import site_export as b  # noqa: E402
import dates  # noqa: E402
import paths  # noqa: E402

# (карточка, начало текста строки «Что») — событие ребёнка, которое меняет жизнь родителя; предупреждать не надо.
# Список — у дерева: ftree.toml, [lifeline] ok = [["Карточка", "начало строки"], …]; нет — пусто
OK = {tuple(x) for x in paths.tree_conf("lifeline.ok", [])}
# домашние «имена», которые не имена: «бабушка Нюра» не должна ловить каждую «бабушку» в тексте
KIN = {"бабушка", "баба", "бабуля", "дедушка", "дед", "мама", "папа", "тётя", "тетя", "дядя", "сын", "дочь", "брат", "сестра"}

BIRTH = re.compile(r"родил|рожд|появил(ся|ась) на свет", re.I)
DEATH = re.compile(r"умер|умерл|погиб|скончал|смерть|похорон", re.I)
# рождение ребёнка в строке родителя: «свидетельство о рождении Прокопа» — документ, а не событие
KID_BIRTH = re.compile(r"(?<!о )рожд|родил|появил(ся|ась) на свет", re.I)
GRAND = re.compile(r"\b(пра)?внук|\b(пра)?внучк", re.I)
LINK = re.compile(r"\[\[([^\]|#]+)")


def year(v):
    m = re.search(r"(1[6-9]\d\d|20\d\d)", str(v or ""))
    return int(m.group(1)) if m else None


def death_year(v):
    """Год смерти для проверки «после смерти»: «AFT 1925» — умер когда-то после, год неизвестен → None."""
    return None if str(v or "").strip().upper().startswith("AFT") else year(v)


def words(d, ru=False):
    """Как ребёнка называют в тексте: первое слово имени, домашние имена, имена в скобках («Ева (Ewa)»)."""
    f = d["f"]
    names = [str(f.get("name") or d["stem"])] + [str(x) for x in b.as_list(f.get("home_names"))]
    names += [str(d.get("ru") or "")] if ru else []  # русское имя — только для строки «родился»: «Павел» бывает и автором
    out = set()
    if d.get("unk") or "имя неизвестно" in names[0]:   # безымянного узнаём только по ссылке: «Ясенев» — и брат Иван
        return out
    for n in names:
        parts = re.findall(r"[^\W\d_]+", n)
        if parts:
            out.add(parts[0].lower())
        out |= {p.lower() for p in re.findall(r"\(([^\W\d_]+)", n)}
    return {w for w in out if len(w) > 2 and w not in KIN}


def mentions(text, d, stems, ru=False):
    t = text.lower()
    if any(b.N(x).strip().rstrip("\\").strip() in stems for x in LINK.findall(text)):
        return True
    # «Николай II» — не сын Николай
    return any(re.search(rf"(?<![^\W\d_]){re.escape(w)}(?![^\W\d_])(?!\s+[ivx]+\b)", t) for w in words(d, ru))


PIPE = re.compile(r"\[\[([^\]]*?)(?<!\\)\|([^\]]*)\]\]")


def same_day(when, v):
    """Дата строки («05.03.1971», «между 1936 и 1937») — та же, что дата карточки ребёнка."""
    g, c = dates.ru_or_none(re.sub(r"[*]", "", when)), dates.card_or_none(v)
    if not (g and c) or "PHRASE" in (g.kind, c.kind):   # «(без даты)» — словами, не сравнить
        return False
    # «ок. 1948» в строке и «1948» в карточке (или наоборот) — тот же год: одна из дат неточная
    return g.card() == c.card() or ((g.approx or c.approx) and g.first_year == c.first_year)


def kids_in(row, kids):
    """Кто из детей назван в строке (ссылкой или именем, в том числе русским). Есть ссылка на ребёнка — верим ей:
    два сына-тёзки («Иван» 1878 и 1885) по имени неразличимы, по ссылке — да."""
    linked = {b.N(x).strip().rstrip("\\").strip() for x in LINK.findall(row[2])}   # «[[X\\|Имя]]» в таблице
    by_link = [k for k in kids if k["stem"] in linked]
    return by_link or [k for k in kids if mentions(row[2], k, {k["stem"]}, ru=True)]


def about(row, k, what_re, field, kids=()):
    """Строка линии жизни — о рождении (смерти) ребёнка k: он назван ссылкой или именем и есть слово «родился»
    («умер»), или слово есть и дата строки — та же, что в его карточке. Строка, где названы двое детей и больше
    («Прокоп (1961), Анна (1964), Мария (1973)»), не считается: у каждого ребёнка — своя строка."""
    if len(kids_in(row, kids)) > 1:
        return False
    _, when, what, _ = row
    v = k["f"].get(field)
    y = str(year(v) or "")
    # «1961–1973 | Прокоп (05.03.1961), Анна (12.09.1964)…» — список детей с датами тоже считается
    if not (what_re.search(what) or (y and y in what)):
        return False
    return mentions(what, k, {k["stem"]}, ru=True) or bool(v and same_day(when, v))


def kid_rows(d, group, rows):
    """Чего не хватает про детей: [(ключ сортировки, «когда», «что», ошибка, «где»)] и предупреждения."""
    born = min((y for y in (year(g["f"].get("born")) for g in group) if y), default=None)
    ends = [death_year(g["f"].get("died")) for g in group]
    died = max(ends) if ends and all(ends) else None
    need, warns = [], []
    allkids = [b.people[s] for s in dict.fromkeys(b.by_id[c]["stem"] for g in group for c in g["children"] if c in b.by_id)]
    for r in rows:
        named = kids_in(r, allkids)
        if len(named) > 1 and (KID_BIRTH.search(r[2]) or re.search(r"умерли\W+(\w+\W+)?(дочь|сын|дет)", r[2], re.I) or
                               any(str(year(k["f"].get("born")) or "—") in r[2] for k in named)):
            warns.append(f"дети одной строкой ({', '.join(k['stem'] for k in named)}) — у каждого своя строка; "
                         f"общую убрать: {r[1]} | {re.sub(r'\s+', ' ', r[2])[:80]}")
    for k in dict.fromkeys(b.by_id[c]["stem"] for g in group for c in g["children"] if c in b.by_id):
        k = b.people[k]
        kb, kd = k["f"].get("born"), k["f"].get("died")
        gb, gd = dates.card_or_none(kb), dates.card_or_none(kd)
        first = "имя неизвестно" if k.get("unk") or str(k.get("ru")) == "неизвестно" else str(k.get("ru") or k["stem"]).split()[0]
        link = f"[[{k['stem']}\\|{first}]]"
        sex = str(k["f"].get("sex") or "")
        if not gb:
            if not (died and year(kb) and year(kb) > died + 1):
                warns.append(f"ребёнок {k['stem']} без даты рождения в карточке — строку не поставить: оценить born")
            continue
        if died and gb.first_year > died + 1:   # родился после смерти родителя (+1 — посмертный ребёнок)
            continue
        if born and gb.last_year < born:
            continue
        if not any(about(r, k, KID_BIRTH, "born", allkids) for r in rows):
            what = {"male": "Родился сын", "female": "Родилась дочь"}.get(sex, "Родился ребёнок") + " " + link
            need.append((gb.sort_key(), gb.ru(), what, f"нет рождения ребёнка {k['stem']} ({gb.ru()})",
                         str(k["f"].get("birth_place") or "")))
        if gd and gd.kind != "AFT" and died and gd.last_year <= died \
                and not any(about(r, k, DEATH, "died", allkids) for r in rows):
            what = {"male": "Умер сын", "female": "Умерла дочь"}.get(sex, "Умер ребёнок") + " " + link
            need.append((gd.sort_key(), gd.ru(), what, f"нет смерти ребёнка {k['stem']} ({gd.ru()}) при его жизни",
                         str(k["f"].get("death_place") or "")))
    return need, warns


def check(d):
    rows = b.split_lifeline(b.bio_text(d))[1]
    if not rows:
        return [], [], []
    refs = set(b.bio_refs(d))
    # общая биография: те, у кого та же ссылка на биографию, — «один человек» для проверки
    group = [d] + [b.by_id[s] for s in d["spouses"] if s in b.by_id and refs & set(b.bio_refs(b.by_id[s]))]
    born = min((y for y in (year(g["f"].get("born")) for g in group) if y), default=None)
    died = max((y for y in (death_year(g["f"].get("died")) for g in group) if y), default=None)
    if any(not death_year(g["f"].get("died")) for g in group) and died:
        died = None  # кто-то из двоих жив или год неизвестен — «после смерти» не проверяем
    kids = [b.by_id[c] for g in group for c in g["children"] if c in b.by_id]
    grand = [b.by_id[c] for k in kids for c in k["children"] if c in b.by_id]
    grand += [b.by_id[c] for k in grand[:] for c in k["children"] if c in b.by_id]
    grand_stems = {g["stem"] for g in grand}
    need, warns = kid_rows(d, group, rows)
    errs = [n[3] for n in need]
    if not any(b.WHERE_COL.match(h) for _, _, _, extra in rows for h, _ in extra):
        errs.append("нет колонки «Где» — таблица «| Когда | Что | Где |»: в каждой строке город или деревня")
        rows_where = False
    else:
        rows_where = True
    for key, when, what, extra in rows:
        y = int(key[:4]) if key[:4].isdigit() and key[:4] != "0000" else None
        line = f"{when} | {re.sub(r'\s+', ' ', what)[:90]}"
        where = next((v for h, v in extra if b.WHERE_COL.match(h)), "").strip()
        if rows_where and not where:
            errs.append(f"пусто в «Где» — город или деревня, не знаем — «?»: {line}")
        elif rows_where and where.strip("? ") == "":
            warns.append(f"«Где» не известно — искать: {line}")
        elif rows_where and "?" not in where and "[[" not in where:
            warns.append(f"«Где» без ссылки на карточку места ({where}) — завести карточку или поставить ссылку: {line}")
        if y and died and y > died:
            errs.append(f"после смерти ({died}) — перенести в «## Память»: {line}")
        after = str(d["f"].get("died") or "").strip().strip('"').upper()
        if (y and after.startswith("AFT") and year(after) and y > year(after) and not when.strip().startswith("до")
                and not re.match(r"\W*(умер|умерла|смерть|погиб|погибла)\b", what, re.I)):
            warns.append(f"жив и позже, чем «умер после {year(after)}» в карточке — поднять died до AFT {y}: {line}")
        if y and born and y < born:
            errs.append(f"раньше рождения ({born}): {line}")
        if any(b.N(x).strip() in grand_stems for x in LINK.findall(what)):
            errs.append(f"внуки: {line}")
            continue
        ok = any(g["stem"] == s and re.sub(r"^[\s*⭐]+", "", what).startswith(p) for g in group for s, p in OK)
        if GRAND.search(what) and not ok:
            warns.append(f"слово «внук» — внуков в линии быть не должно: {line}")
        for k in kids:
            if not mentions(what, k, {k["stem"]}):
                continue
            kb = str(year(k["f"].get("born")) or "")
            birth = BIRTH.search(what) or (kb and kb in what)  # «дети | Прокоп (05.03.1961), …»
            # смерть ребёнка после смерти родителя ловит проверка «после смерти»: строка стоит его годом
            if not birth and not DEATH.search(what) and not ok:
                warns.append(f"событие ребёнка {k['ru']} — ему в линию? {line}")
            break
    # у каждого ребёнка: смерть не раньше рождения — ни строкой в таблице, ни датой в карточке
    # (у одной матери «умер младший сын» стояло раньше «родился сын»)
    for k in dict.fromkeys(k["stem"] for k in kids):
        k = b.people[k]
        at = lambda what_re: next((i for i, r in enumerate(rows) if about(r, k, what_re, "born" if what_re is KID_BIRTH
                                                                         else "died", kids)), None)
        i_birth, i_death = at(KID_BIRTH), at(DEATH)
        if i_birth is not None and i_death is not None and i_death < i_birth:
            errs.append(f"смерть ребёнка {k['stem']} стоит раньше его рождения: {rows[i_death][1]} | "
                        f"{re.sub(r'\s+', ' ', rows[i_death][2])[:70]}")
        gb, gd = dates.card_or_none(k["f"].get("born")), dates.card_or_none(k["f"].get("died"))
        if gb and gd and gd.last_year < gb.first_year:
            errs.append(f"в карточке ребёнка {k['stem']} смерть ({gd.ru()}) раньше рождения ({gb.ru()})")
    return errs, warns, need


def memory(d):
    """Ошибки таблицы «Память»: она — только после смерти, и смерть должна быть в карточке (died)."""
    rows = b.split_lifeline(b.bio_text(d), memory=True)[1] if b.bio_text(d) else []
    if not rows:
        return []
    died = year(d["f"].get("died"))
    if not died:
        return [f"«Память» есть, а даты смерти в карточке нет — вписать died (хотя бы AFT 1945): {rows[0][1]}"]
    errs = []
    for key, when, what, extra in rows:
        y = int(key[:4]) if key[:4].isdigit() and key[:4] != "0000" else None
        line = f"{when} | {re.sub(r'\s+', ' ', what)[:90]}"
        if y and y < died:
            errs.append(f"в «Памяти» строка раньше смерти ({died}) — это линия жизни: {line}")
        if not next((v for h, v in extra if b.WHERE_COL.match(h)), "").strip():
            errs.append(f"«Память»: пусто в «Где» — город или деревня, не знаем — «?»: {line}")
    return errs


def life_table(section):
    """Таблица линии жизни в тексте раздела — та, которую берёт сайт (b.split_lifeline); «Линия жизни» — первой."""
    found = []
    for m in b.TABLE.finditer(section):
        if b.in_other_person(section, m.start()):
            continue
        if len(b.split_lifeline(section[:m.end()])[1]) > len(b.split_lifeline(section[:m.start()])[1]):
            hm = list(re.finditer(r"^#+[ \t]+([^\n]*)$", section[:m.start()], re.M))
            found.append((not (hm and b.LIFE_HEAD.search(hm[-1].group(1))), m.group(1)))
    return min(found, key=lambda x: x[0])[1] if found else None


def insert_rows(block, need):
    """Строки need — в таблицу block, каждая на своё место по времени."""
    lines = block.rstrip("\n").split("\n")
    cells = lambda r: [c.strip() for c in r.replace("\\|", "\x00").strip().strip("|").split("|")]
    head = [re.sub(r"[*_`⭐]", "", h).strip() for h in cells(lines[0])]
    wi = next((i for i, h in enumerate(head) if b.WHEN_COL.match(h)), 0)
    wh = 1 if wi == 0 else 0
    src = next((i for i, h in enumerate(head) if re.match(r"(откуда|источник)", h, re.I)), None)
    gi = next((i for i, h in enumerate(head) if b.WHERE_COL.match(h)), None)
    for key, when, what, _, where in sorted(need):
        row = [""] * len(head)
        row[wi], row[wh] = when, what + ("" if src is not None else " (дерево)")
        if gi is not None:  # ребёнок родился (умер) там, где записано в его карточке; не записано — «?», искать
            row[gi] = where.replace("|", "\\|") or "?"
        if src is not None:
            row[src] = "дерево"
        at, last = len(lines), "0000"
        for i in range(2, len(lines)):
            c = cells(lines[i])
            g = dates.ru_or_none(re.sub(r"[*]", "", c[wi])) if wi < len(c) else None
            last = g.sort_key() if g and g.sort_key() else last
            if last > key:
                at = i
                break
        lines.insert(at, "| " + " | ".join(row) + " |")
    return "\n".join(lines) + "\n"


def fix(d, need):
    """Вписать недостающие строки в файл биографии и экранировать «|» в ссылках её таблиц. → что сделано."""
    done = []
    for ref in b.bio_refs(d):
        p = b.md_file(ref.partition("#")[0])
        if not p:
            continue
        text = p.read_text(encoding="utf-8")
        new = re.sub(r"^\|.*$", lambda m: PIPE.sub(r"[[\1\\|\2]]", m.group(0)), text, flags=re.M)
        if new != text:
            done.append(f"{p.name}: «|» в ссылках таблиц → «\\|»")
        if need:
            block = life_table(b.embed(ref))
            if block and new.count(block) == 1:
                new = new.replace(block, insert_rows(block, need))
                done += [f"{p.name}: {n[1]} | {n[2]} | {n[4] or '?'}" for n in sorted(need)]
                need = []
        if new != text:
            p.write_text(new, encoding="utf-8")
    if need:
        done += [f"не вписано (нет таблицы «Линия жизни» или она не нашлась в файле): {n[3]}" for n in need]
    return done


def pipes(d):
    """Строки таблиц в файлах биографии, где «|» в ссылке не экранирован."""
    out = []
    for ref in b.bio_refs(d):
        p = b.md_file(ref.partition("#")[0])
        for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if p else []:
            if ln.lstrip().startswith("|") and PIPE.search(ln):
                out.append(f"«|» в ссылке без «\\» — ячейка развалится: {p.name}, стр. {i}: {PIPE.search(ln).group(0)}")
    return list(dict.fromkeys(out))


def main():
    args = sys.argv[1:]
    do_fix = "--fix" in args
    args = [a for a in args if a != "--fix"]
    if args[:1] == ["--kin"]:
        me = [b.people[s] for s in args[1:] if s in b.people]
        people = me + [b.by_id[x] for d in me for x in d["father"] + d["mother"] if x in b.by_id]
    elif args[:1] == ["--file"]:
        f = b.N(args[1]).removesuffix(".md")
        people = [d for d in b.people.values() if any(b.N(r).removesuffix(".md") == f for r in
                                                    (x.split("#")[0] for x in b.bio_refs(d)))]
    else:
        people = [d for d in b.people.values() if not args or d["stem"] in args]
    n_err = n_warn = 0
    fixed = []
    for d in sorted({d["stem"]: d for d in people}.values(), key=lambda d: d["stem"]):
        errs, warns, need = check(d)
        errs += pipes(d) + memory(d)
        if do_fix and (need or any(e.startswith("«|»") for e in errs)):
            done = fix(d, need)
            fixed += done
            errs, warns, _ = check(d)   # файл уже другой: b.embed читает его заново
            errs += pipes(d) + memory(d)
        if errs or warns:
            print(f"\n{d['stem']}")
            for e in errs:
                print(f"  ✗ {e}")
            for w in warns:
                print(f"  · {w}")
        n_err += len(errs)
        n_warn += len(warns)
    if fixed:
        print("\nПоправлено:\n" + "\n".join(f"  + {x}" for x in fixed))
    print(f"\nЛинии жизни: ошибок {n_err}, предупреждений {n_warn}")
    return 1 if n_err else 0


if __name__ == "__main__":
    sys.exit(main())
