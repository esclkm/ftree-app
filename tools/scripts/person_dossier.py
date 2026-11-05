#!/usr/bin/env python3
"""Всё о человеке на одной странице — материалы к главе книги и к разговору с родней.

Ничего не копирует из карточки: разделы карточки показываются встраиванием ![[карточка#раздел]].
Собирает то, чего нет в одном месте:
  — родня, ветки, события, места, фото;
  — где человек упомянут во всём проекте (строка с контекстом, файл и номер строки);
  — что о нём УЖЕ написано в книгах (с ручными правками!) — дословные абзацы с файлом и строкой;
  — какие факты из карточки в книгах, похоже, ещё не отражены (подсказка, а не приговор).

Результат: 3_research/_dossiers/<Имя>.md (пересобирается при каждом запуске, в git не хранится).

Запуск:  python3 tools/scripts/person_dossier.py "Прокоп Ясенев"        # один человек
         python3 tools/scripts/person_dossier.py --line Ясеневы          # вся ветка (lineage)
         python3 tools/scripts/person_dossier.py "Прокоп Ясенев" --stdout  # в терминал, без файла
"""
import os
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402
from md_clean import strip_wikilinks  # noqa: E402

N = lambda s: unicodedata.normalize("NFC", s)
PEOPLE = paths.TREE / "people"
OUT = paths.RESEARCH / "_dossiers"
# книги — с 28.09.2026 удалены (сначала биографии); если вернутся, их абзацы снова попадут в досье
# какие файлы книг читать — настройка дерева ([dossier] books в ftree.toml: имена в папке книг, можно с * и ?)
BOOKS = [p for pat in paths.tree_conf("dossier.books", ["*.md"]) for p in sorted(paths.BOOKS.glob(str(pat)))] \
        + sorted(paths.BOOK_AUTO.glob("КНИГА_0*.md")) \
        + sorted(paths.BOOK_TRANSLATIONS.glob(str(paths.tree_conf("dossier.translations", "*_RU_*.md"))))
SKIP = ("tools/", ".git", "_archive", "_dossiers", "_generated", "_chunks", "tree_data", paths.rel(paths.SOCIAL_EXPORT))
STOP = set("этот этого который которая потом после когда очень только было были будет своей своего между через "
           "тогда здесь где-то также почти уже ещё источник уверенность обычная низкая высокая аудио".split())


def fm(text):
    m = re.match(r"---\n(.*?)\n---", text, re.S)
    return m.group(1) if m else ""


def values(f, key):
    m = re.search(rf"^{key}:(.*(?:\n  - .*)*)", f, re.M)
    if not m:
        return []
    return [x.strip().strip('"') for x in re.findall(r"(?:^ ?|\n  - )([^\n]+)", m.group(1)) if x.strip().strip('"')]


link = lambda x: re.sub(r"^\[\[([^\]|]+).*", r"\1", x) if x.startswith("[[") else x


def section(text, head):
    m = re.search(rf"^### {re.escape(head)}\n(.*?)(?=^### |^## |\Z)", text, re.S | re.M)
    return [l for l in (m.group(1) if m else "").splitlines() if l.startswith("- ")]


def names_of(card, f):
    """Как человека называют в текстах: имя карточки без уточнения в скобках, name, aliases."""
    base = re.sub(r"\s*\(.*?\)\s*|\s*№\d+$", "", card).strip()
    out = {card, base, *values(f, "aliases")}
    nm = (re.search(r'^name: *"?([^"\n]*)', f, re.M) or [None, ""])[1]
    if nm:
        out.add(nm)
    # Кириллическая форма фамилии (Jasieniew → Ясенев) уже в aliases; одно имя без фамилии не ищем — слишком шумно,
    # кроме домашних имён из поля home_names («Прокопка», «Ганулька», «дед Прокоп») — их вписывают руками
    return {n for n in out if len(n.split()) >= 2} | set(values(f, "home_names"))


def name_re(names):
    """«дед Прокоп» → дед\\w*\\s+Прокоп\\w* — ловит падежи: «деда Прокопа», «деду Прокопу»."""
    parts = []
    for n in sorted(names, key=len, reverse=True):
        words = [re.escape(w[:max(3, len(w) - 2)]) + r"[а-яёa-z]*" for w in n.split()]
        parts.append(r"\s+".join(words))
    return re.compile(r"(?<![А-Яа-яЁёA-Za-z])(?:" + "|".join(parts) + ")", re.I) if parts else None


def about_spans(lines, rx):
    """Строки книги «про человека»: главы, в заголовке которых он назван, и абзацы, где он упомянут."""
    keep = set()
    heads = [(i, len(m.group(1))) for i, l in enumerate(lines) if (m := re.match(r"^(#+)\s", l))]
    for k, (i, lvl) in enumerate(heads):
        if rx.search(lines[i]):
            end = next((j for j, l2 in heads[k + 1:] if l2 <= lvl), len(lines))
            keep.update(range(i, end))
    for i, l in enumerate(lines):
        if rx.search(l):
            a = i
            while a > 0 and lines[a - 1].strip():
                a -= 1
            b = i
            while b + 1 < len(lines) and lines[b + 1].strip():
                b += 1
            keep.update(range(a, b + 1))
    return keep


def iter_md():
    for d, ds, fs in os.walk(paths.ROOT):
        r = os.path.relpath(d, paths.ROOT)
        if r.startswith(SKIP) or any(s in r for s in ("_archive", "_dossiers", "_generated", "_chunks")):
            ds[:] = []
            continue
        for fn in fs:
            # склейки глав повторяют биографии и главы целиком — дают двойные упоминания
            if fn.endswith(".md") and fn != "КНИГА_полная.md":
                yield Path(d) / fn


def context(lines, i):
    """Строка-цитата простым текстом: ссылки из чужого файла здесь не работают — оставляем только их текст."""
    s = strip_wikilinks(lines[i].replace("\\|", "|"))
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)                  # картинки
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)                # [текст](путь) → текст
    s = re.sub(r"\s+", " ", s).strip()
    return s[:260] + ("…" if len(s) > 260 else "")


def dossier(card):
    p = PEOPLE / f"{card}.md"
    t = p.read_text(encoding="utf-8")
    f = fm(t)
    gid = (re.search(r"^gedcom_id: (\S+)", f, re.M) or [None, ""])[1]
    names = names_of(card, f)
    rx = name_re(names)
    L = [f"# Всё о человеке: [[{card}]]", "",
         f"> Собрано `person_dossier.py` — не править, пересобирается. Карточка — главное место: факты вносить туда.",
         ""]

    # --- кто он
    rel = []
    for key, label in (("father", "отец"), ("mother", "мать"), ("spouse", "супруг(а)"), ("children", "дети")):
        v = [f"[[{link(x)}]]" for x in values(f, key) if x.startswith("[[")]
        if v:
            rel.append(f"**{label}:** {', '.join(v)}")
    born, died = (re.search(r"^born: *(.*)$", f, re.M) or [None, ""])[1], (re.search(r"^died: *(.*)$", f, re.M) or [None, ""])[1]
    L += ["## Кто он", "",
          f"**Годы:** {born or '?'} — {died or '?'} · **номер MyHeritage:** `{gid or '—'}` · "
          f"**приоритет поиска:** {(re.search(r'^research_priority: (\\S+)', f, re.M) or [None, '—'])[1]}",
          f"**Ветки:** {', '.join(values(f, 'lineage')) or '—'}"
          + (f" · по браку: {', '.join(values(f, 'lineage_by_marriage'))}" if values(f, "lineage_by_marriage") else ""),
          " · ".join(rel), ""]
    si = (re.search(r'^surname_inferred: *"?([^"\n]*)', f, re.M) or [None, ""])[1]
    if si:
        L += [f"⚠️ Фамилия выведена, документа нет: {si}", ""]

    # --- события и места
    ev = []
    for e in (paths.TREE / "events").glob("*.md"):
        et = e.read_text(encoding="utf-8")
        if re.search(rf'\[\[{re.escape(card)}(\]\]|\|)', et):
            ef = fm(et)
            date = (re.search(r'^date: *"?([^"\n]*)', ef, re.M) or [None, ""])[1]
            place = (re.search(r'^place: *"?([^"\n]*)', ef, re.M) or [None, ""])[1]
            title = (re.search(r'^title: *"?([^"\n]*)', ef, re.M) or [None, e.stem])[1]
            if re.match(r"^\d{1,2} [A-Z]{3} \d{4} \d", title):   # служебные отметки MyHeritage «обновлено …»
                continue
            ev.append((date or "9999", f"- {date or '?'} — [[{e.stem}|{title}]]" + (f" · {place}" if place else "")))
    if ev:
        L += ["## События", ""] + [x for _, x in sorted(ev)] + [""]

    # --- разделы карточки (встраивание — без копии)
    L += ["## Из карточки", ""]
    for head in ("Факты (с источником)", "Слова дословно", "Расхождения", "Открытые вопросы",
                 "Из досье поиска (июнь–сентябрь 2026)"):
        if section(t, head):
            L += [f"### {head}", f"![[{card}#{head}]]", ""]
    if "## Тексты:" in t:
        L += ["### Статьи, автобиографии, воспоминания", f"![[{card}#Тексты: статьи, автобиографии, воспоминания]]", ""]
    media = [link(x) for x in values(f, "media")]
    if media:
        L += ["### Фото", " ".join(f"![[{m}|110]]" for m in media), ""]

    # --- упоминания во всём проекте (не книги)
    pat_link = re.compile(rf"\[\[{re.escape(card)}(\]\]|\||\\\|)")
    pat_id = re.compile(rf"@{gid}@") if gid else None
    book_set = {N(str(b)) for b in BOOKS}
    mentions, book_hits = [], {}
    for md in iter_md():
        if md == p:
            continue
        rel_p = N(md.relative_to(paths.ROOT).as_posix())
        lines = md.read_text(encoding="utf-8", errors="replace").splitlines()
        is_book = N(str(md)) in book_set
        for i, line in enumerate(lines):
            hit = pat_link.search(line) or (pat_id and pat_id.search(line)) or (is_book and rx and rx.search(line))
            if hit:
                (book_hits.setdefault(rel_p, []) if is_book else mentions).append((rel_p, i + 1, context(lines, i)))
    by_file = {}
    for rp, ln, c in mentions:
        by_file.setdefault(rp, []).append((ln, c))
    L += [f"## Где упомянут — {len(mentions)} мест в {len(by_file)} файлах", ""]
    for rp in sorted(by_file, key=lambda x: (not x.startswith(paths.rel(paths.TRANSCRIPTS) + "/"), not x.startswith(paths.rel(paths.PAVEL) + "/bio"), x)):
        L.append(f"**[[{rp}]]**")
        L += [f"- стр. {ln}: {c}" for ln, c in by_file[rp][:12]]
        if len(by_file[rp]) > 12:
            L.append(f"- … ещё {len(by_file[rp]) - 12}")
        L.append("")

    # --- что уже в книгах (с ручными правками) и чего там нет
    L += ["## Что уже написано в книгах", "",
          "> Книги правились руками — берём их текст за основу, а не перезаписываем. Ниже — дословные строки.", ""]
    book_text = ""
    for rp, hits in sorted(book_hits.items(), key=lambda x: -len(x[1])):
        L.append(f"**[[{rp}]]** — {len(hits)}")
        L += [f"- стр. {ln}: {c}" for _, ln, c in hits[:15]]
        if len(hits) > 15:
            L.append(f"- … ещё {len(hits) - 15}")
        L.append("")
        bl = (paths.ROOT / rp).read_text(encoding="utf-8").splitlines()
        book_text += "\n".join(bl[i] for i in sorted(about_spans(bl, rx))).lower() + "\n"
    if not book_hits:
        L += ["В книгах пока не упомянут.", ""]

    facts = section(t, "Факты (с источником)")
    missing = []
    for fl in facts:
        body = re.sub(r"—\s*\*источник:.*$", "", fl)
        years = re.findall(r"\b1[89]\d\d\b|\b20[0-2]\d\b", body)
        words = [w for w in re.findall(r"[А-Яа-яЁёA-Za-z]{6,}", body.lower()) if w not in STOP]
        stems = {w[:6] for w in words}
        found = sum(1 for s in stems if s in book_text)
        if book_text and stems and (found < max(2, len(stems) // 3) or (years and not any(y in book_text for y in years))):
            missing.append(fl)
    L += [f"## В книгах, похоже, ещё нет — {len(missing)} из {len(facts)} фактов", "",
          "> Проверка грубая — по ключевым словам и годам. Перед вставкой в книгу сверить глазами.", ""] + missing + [""]

    return "\n".join(L)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    cards = []
    if "--line" in sys.argv:
        line = args[0]
        for p in sorted(PEOPLE.glob("*.md")):
            if f'  - "{line}"' in fm(p.read_text(encoding="utf-8")).split("lineage_by_marriage")[0]:
                cards.append(p.stem)
    else:
        cards = args
    if not cards:
        sys.exit(__doc__)
    OUT.mkdir(parents=True, exist_ok=True)
    for c in cards:
        c = N(c)
        if not (PEOPLE / f"{c}.md").exists():
            cand = [p.stem for p in PEOPLE.glob("*.md") if c.lower() in p.stem.lower()]
            sys.exit(f"Нет карточки «{c}». Похожие: {', '.join(cand[:10]) or '—'}")
        text = dossier(c)
        if "--stdout" in sys.argv:
            print(text)
        else:
            (OUT / f"{c}.md").write_text(text, encoding="utf-8")
            print(f"{(OUT / f'{c}.md').relative_to(paths.ROOT)}")


if __name__ == "__main__":
    main()
