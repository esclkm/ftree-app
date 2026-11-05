#!/usr/bin/env python3
"""Слить две карточки одного человека в одну — когда доказано, что это один человек.

Зачем. Правило «упоминание = карточка» (CLAUDE.md): каждый, кто назван в документе, сразу получает карточку — даже
крёстная «Анна Прокопова» из метрики 1911 года, хотя в дереве уже есть «Анна Ясенева». Когда документ доказывает,
что это один человек, две карточки сливают этим скриптом: одна остаётся, вторая исчезает, а всё, что знала вторая,
переезжает в первую. Ничего не теряется: номер слитой карточки остаётся в `merged_from`, имя — в `aliases`,
сама запись — в журнале `3_research/tree/_СЛИЯНИЯ.md`, файл — в истории git.

Какую оставить (KEEP). Ту, у которой есть `gedcom_id` (она уже на MyHeritage); если номера нет ни у одной — ту, что
уже связана с семьёй; иначе — старшую. У обеих разные `gedcom_id` — скрипт остановится: сначала слить людей на
MyHeritage, потом здесь.

Что делает:
  1. свойства: списки (sources, media, aliases, tags, children…) — объединяет; одиночные поля — оставляет у KEEP,
     а если у DROP было другое непустое (born, died, места) — пишет строкой в «Расхождения»;
     разные father/mother/spouse — остановка: решить руками;
  2. текст: строки разделов «Факты», «Слова дословно», «Расхождения», «Открытые вопросы» — дописывает недостающие;
  3. во всём проекте (3_research, 4_outputs, 1_sources/**/00_ОПИСЬ*) — ссылки [[DROP]] → [[KEEP]], номер DROP → KEEP,
     и убирает повторы, если человек оказался в списке дважды;
  4. удаляет файл DROP и пишет строку в журнал слияний.
Биографию DROP скрипт не трогает, если у KEEP своя уже есть, — говорит, что слить руками; если у KEEP нет —
переименовывает биографию DROP под KEEP.

Запуск:
  python3 tools/scripts/merge_cards.py "Анна Прокопова (1911)" "Анна Ясенева" --why "[[ГАСО — метрики …]], д. 525, файл 307: …"
  … --apply      # без него — только показать, что будет сделано
  python3 tools/scripts/merge_cards.py --candidates   # все пары maybe_same: кто, с кем, на чём держится
                                                      # (пары из not_same — проверено «нет» — не показывает)
После --apply: check_tree.py, check_cards.py, bio_ids.py --fix, assign_lineage.py.
"""
import argparse
import datetime
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402
import cards  # noqa: E402
from cards.notes import N, as_list, link_target, read_note  # noqa: E402

PEOPLE = paths.TREE / "people"
BIOS = paths.TREE / "biographies"
JOURNAL = paths.TREE / "_СЛИЯНИЯ.md"
LISTS = ("sources", "media", "aliases", "tags", "children", "children_id", "merged_from", "lineage",
         "lineage_by_marriage")
LINKS = (("father", "father_id"), ("mother", "mother_id"), ("spouse", "spouse_id"))
# возможные связи и проверенное «нет»: имя и номер — парами, как father/father_id
POSSIBLE = (("maybe_same", "maybe_same_id"), ("maybe_kin", "maybe_kin_id"), ("not_same", "not_same_id"),
            ("not_kin", "not_kin_id"))
SINGLE_NOTE = ("born", "died", "birth_place", "death_place", "occupation", "sex", "surname_inferred")
SECTIONS = ("Факты (с источником)", "Слова дословно", "Расхождения", "Открытые вопросы")
SCAN = [paths.RESEARCH, paths.OUTPUTS]


def card(stem):
    p = PEOPLE / f"{stem}.md"
    if not p.exists():
        sys.exit(f"нет карточки: {p}")
    return read_note(p)


def q(v):
    """Значение свойства так, как пишет проект: ссылки и даты — в кавычках."""
    s = str(v)
    return f'"{s}"' if s.startswith("[[") or ": " in s or s.startswith(("*", "&", "!", "%", "@")) else s


def dump(fm):
    out = []
    for k, v in fm.items():
        if isinstance(v, list):
            out.append(f"{k}:")
            out += [f"  - {q(x)}" for x in v]
        else:
            out.append(f"{k}: {'' if v is None else q(v)}".rstrip())
    return "\n".join(out)


def uniq(xs):
    return list(dict.fromkeys(x for x in xs if x not in (None, "")))


def lines_of(body, title):
    m = re.search(rf"^### {re.escape(title)}\n(.*?)(?=^#{{1,3}} |\Z)", body, re.S | re.M)
    return [ln for ln in (m.group(1).splitlines() if m else []) if ln.startswith("- ")]


def add_lines(body, title, new):
    if not new:
        return body
    m = re.search(rf"^### {re.escape(title)}\n(.*?)(?=^#{{1,3}} |\Z)", body, re.S | re.M)
    block = "\n".join(new) + "\n"
    if m:
        end = m.start(1) + len(m.group(1).rstrip("\n")) + 1
        return body[:end] + block + body[end:]
    anchor = re.search(r"^## (Рассказ|Источники)", body, re.M)
    sec = f"### {title}\n\n{block}\n"
    return body[:anchor.start()] + sec + body[anchor.start():] if anchor else body.rstrip() + "\n\n" + sec


def merge(keep, drop, why, today):
    k, d = dict(keep.fm), drop.fm
    stop, notes = [], []
    gk, gd = str(k.get("gedcom_id") or ""), str(d.get("gedcom_id") or "")
    if gk and gd and gk != gd:
        stop.append(f"у обеих свой gedcom_id ({gk}, {gd}) — сначала слить на MyHeritage")
    if gd and not gk:
        k["gedcom_id"] = gd
    for name_key, id_key in LINKS:
        a, b = as_list(k.get(id_key)), as_list(d.get(id_key))
        if name_key == "spouse":
            k[name_key] = uniq(as_list(k.get(name_key)) + as_list(d.get(name_key))) or None
            k[id_key] = uniq(a + b) or None
            for kk in (name_key, id_key):
                if isinstance(k[kk], list) and len(k[kk]) == 1:
                    k[kk] = k[kk][0]
        elif a and b and a != b:
            stop.append(f"разные {name_key}: {k.get(name_key)} / {d.get(name_key)} — решить, кто прав")
        elif b and not a:
            k[name_key], k[id_key] = d.get(name_key), d.get(id_key)
    for key in LISTS:
        if key in k or key in d:
            k[key] = uniq(as_list(k.get(key)) + as_list(d.get(key)))
    me = {x for x in (keep.stem, drop.stem, k.get("cr_id"), d.get("cr_id")) if x}

    def named(fm, nk, ik):   # [(ссылка, номер или None)] — номер рядом с именем, если записаны парами
        names, ids = as_list(fm.get(nk)), as_list(fm.get(ik))
        return list(zip(names, ids if len(ids) == len(names) else [None] * len(names)))

    for nk, ik in POSSIBLE:
        both = named(k, nk, ik) + named(d, nk, ik)
        if nk == "not_same" and any(link_target(x) in me or i in me for x, i in both):
            stop.append("пара отмечена not_same — «проверено: не одно лицо»; сначала решить, что верно")
        both = list(dict.fromkeys((x, i) for x, i in both if link_target(x) not in me and i not in me))
        k.pop(nk, None)
        k.pop(ik, None)
        if both:
            k[nk] = [x for x, _ in both]
            if all(i for _, i in both):
                k[ik] = [i for _, i in both]
    k["aliases"] = uniq(as_list(k.get("aliases")) + [d.get("name") or drop.stem])
    k["merged_from"] = uniq(as_list(k.get("merged_from")) + [d.get("cr_id")])
    for key in SINGLE_NOTE:
        a, b = str(k.get(key) or ""), str(d.get(key) or "")
        if b and not a:
            k[key] = d.get(key)
        elif a and b and a != b:
            notes.append(f"- При слиянии ({today}) у карточки «{drop.stem}» было {key}: {b} — здесь оставлено {a}.")
    body = keep.body
    for title in SECTIONS:
        have = set(lines_of(body, title))
        new = [ln for ln in lines_of(drop.body, title) if ln not in have]
        if title == "Расхождения":
            new += notes
        if title == "Факты (с источником)":
            new.append(f"- **Слияние ({today}):** карточка «{drop.stem}» ({d.get('cr_id')}) — тот же человек — "
                       f"*источник: {why} · уверенность: высокая*")
        body = add_lines(body, title, new)
    return k, body, stop


def dedupe_lists(text):
    """В шапке карточки: убрать повтор пункта в одном списке (после замены DROP → KEEP)."""
    m = re.match(r"---\n(.*?)\n---", text, re.S)
    if not m:
        return text
    out, seen = [], set()
    for ln in m.group(1).split("\n"):
        if ln.startswith("  - "):
            if ln in seen:
                continue
            seen.add(ln)
        else:
            seen = set()
        out.append(ln)
    return "---\n" + "\n".join(out) + text[m.end(1):]


def relink(keep, drop, apply):
    ks, ds = keep.stem, drop.stem
    kid, did = keep.fm.get("cr_id"), drop.fm.get("cr_id")
    pat = re.compile(r"\[\[" + re.escape(ds) + r"(?=[\]|#])")
    changed = []
    files = [p for root in SCAN for p in root.rglob("*.md")]
    files += list(paths.SOURCES.rglob("00_ОПИСЬ*.md"))
    for p in files:
        if p == drop.path:
            continue
        t = N(p.read_text(encoding="utf-8"))
        t2 = pat.sub("[[" + ks, t)
        if did:
            t2 = re.sub(r"\b" + re.escape(did) + r"\b", kid, t2)
        if t2 != t:
            t2 = dedupe_lists(t2)
            changed.append(p)
            if apply:
                p.write_text(t2, encoding="utf-8")
    return changed


def candidates(tree=None):
    """Пары «возможно, тот же человек» (maybe_same, с любой стороны) — подозреваемые двойники, ещё не доказанные.
    Пару, которую уже проверили и сказали «нет» (not_same в любой из двух карточек), не показываем."""
    tree = tree or cards.load()
    rows, seen = [], set()
    for p in sorted(tree.people.values(), key=lambda p: p.stem):
        for x in p.possible:
            pair = frozenset((p.id, x.person))
            if x.kind != "same" or x.back or pair in seen or tree.ruled_out(p.id, x.person, "same"):
                continue
            seen.add(pair)
            rows.append(f"{p.stem}  →  {tree.people[x.person].stem}" + (f"\n    на чём держится: {x.reason[:200]}"
                                                                        if x.reason else ""))
    return rows


def main():
    if "--candidates" in sys.argv:
        rows = candidates()
        print("\n".join(rows) or "пар maybe_same нет")
        print(f"\nвсего: {len(rows)} · все возможные связи рядом, с решениями — rodo possible")
        return
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("drop", help="карточка, которая исчезнет (имя файла без .md)")
    ap.add_argument("keep", help="карточка, которая останется")
    ap.add_argument("--why", required=True, help="на каком документе доказано, что это один человек")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if "[[" not in a.why:
        sys.exit("--why: нужна ссылка на карточку источника и место в нём: "
                 "\"[[ГАСО — метрики …]], д. 525, файл 307: крёстная Анна Прокопова из Вербичей = дочь Прокопа\"")
    keep, drop = card(N(a.keep)), card(N(a.drop))
    today = datetime.date.today().isoformat()
    fm, body, stop = merge(keep, drop, a.why, today)
    if stop:
        sys.exit("СТОП, не сливаю:\n  " + "\n  ".join(stop))
    changed = relink(keep, drop, a.apply)
    bio_d, bio_k = BIOS / f"{drop.stem} — биография.md", BIOS / f"{keep.stem} — биография.md"
    print(f"оставляю: {keep.stem} ({keep.fm.get('cr_id')})\nсливаю:   {drop.stem} ({drop.fm.get('cr_id')})")
    print(f"ссылки поправлю в файлах: {len(changed)}")
    for p in changed[:30]:
        print("  ", p.relative_to(paths.ROOT))
    if bio_d.exists():
        print("⚠️ у обеих есть биография — слить тексты руками" if bio_k.exists()
              else f"биографию «{bio_d.name}» переименую под «{keep.stem}»")
    if not a.apply:
        print("\n(показ; слить — с --apply)")
        return
    keep.path.write_text(f"---\n{dump(fm)}\n---\n{body}", encoding="utf-8")
    if bio_d.exists() and not bio_k.exists():
        bio_d.rename(bio_k)
    drop.path.unlink()
    new = not JOURNAL.exists()
    with JOURNAL.open("a", encoding="utf-8") as f:
        if new:
            f.write("# Журнал слияний карточек\n\nКто в кого слит и на чём доказано. Пишет `rodo merge-cards`; "
                    "слитый файл — в истории git.\n\n| Дата | Осталась | Слита (номер) | Доказательство |\n|---|---|---|---|\n")
        f.write(f"| {today} | [[{keep.stem}]] | {drop.stem} ({drop.fm.get('cr_id')}) | {a.why} |\n")
    print("слито. Дальше: check_tree.py, check_cards.py, bio_ids.py --fix, assign_lineage.py")


if __name__ == "__main__":
    main()
