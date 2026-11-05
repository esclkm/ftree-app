#!/usr/bin/env python3
"""Место в факте — ссылкой, иначе его нет на карте (01.11.2026).

Карта и страница места знают, кто где был, только по ссылкам: место рождения и смерти, карточка события с местом и
ссылка [[Место]] в строке факта. Пример: о супругах вписали брак в Лесогорске, отъезд из Вербичей, могилу в
Заречье — словами, без ссылок, и на карте у Вербичей не появилось ни одного человека.

Что проверяет: в тексте факта (до «— *источник») названо место, у которого есть карточка, — словом, а не ссылкой.
Узнаёт название и его падежи («Вербичей», «Лесогорске», «Заречье»), имя карточки и её aliases; прилагательные
(«Брестский уезд», «Минской области») — нет. Страны, области и районы не проверяет: это фон, а не точка жизни, и
«паспорт СССР» не значит, что человек был в точке «СССР»; реки — тоже. Строки «Заметка» и «Ссылка» (старый
импорт) — тоже нет. Слово в квадратных скобках — догадка чтения («деревни [Вербичей]»), его не трогаем. Слово сразу
за именем — фамилия или отчество, а не место: «Анна Лесогорская» — фамилия, не Лесогорск.
--fix переносит и переводы строки (translations/<язык>/facts): перевод ищется по отпечатку текста, а ссылка его меняет.

  tools/py tools/scripts/check_fact_places.py              # всё дерево; код 1, если есть такие факты
  tools/py tools/scripts/check_fact_places.py "<карточка>" # один человек
  tools/py tools/scripts/check_fact_places.py --fix        # первое упоминание места в факте → [[Место|как в тексте]]
  tools/py tools/scripts/check_fact_places.py --fix --staged  # то же для карточек из коммита — так зовёт хук (sync.py)
"""
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import cards  # noqa: E402
import paths  # noqa: E402
import tr_store  # noqa: E402

SKIP_TYPES = {"country", "region", "district", "house", "street", "river"}
SKIP_LABELS = {"Заметка", "Ссылка"}
SKIP_NAMES = {"Лида"}  # ещё и женское имя: «тётя Лида»
# окончания падежей по тому, чем кончается название (у несклоняемых — «Монтевидео» — подойдёт и пустое)
ENDINGS = [("ия", "ия|ии|ию|ией"), ("ья", "ья|ьи|ью|ьей"), ("ье", "ье|ья|ью|ьем"), ("ое", "ое|ого|ому|ом"),
           ("ай", "ай|ая|аю|аем|ае"), ("ей", "ей|ея|ею|еем|ее"), ("ь", "ь|и|ью|я|ю|ем|е"),
           ("и", "и|ей|ам|ами|ах"), ("ы", "ы|ов|ам|ами|ах"), ("а", "а|ы|и|е|у|ой|ою"), ("я", "я|и|е|ю|ей|ёй")]
# ссылка целиком, и с «[?]» внутри: [[Иван Ясенев (1878)|Иван[?]]]
LINK = re.compile(r"\[\[(?:[^\[\]]|\[[^\[\]]*\])*\]\]|https?://\S+|`[^`]*`")
TAIL = " — *источник:"
AFTER_NAME = re.compile(r"(?<![\w-])[А-ЯЁ][а-яё]+ $")  # «Ксения Ясенева»: перед словом — имя


def forms(name):
    """«Вербичи» → regex всех падежей; несколько слов — только как написано."""
    if " " in name:
        return re.escape(name)
    for end, alts in ENDINGS:
        if name.endswith(end):
            return re.escape(name[:-len(end)]) + f"(?:{alts})"
    return re.escape(name) + "(?:а|у|ом|е)?" if re.search(r"[а-яё]$", name) else re.escape(name)


def names_of(pl):
    """Имя карточки без уточнения в скобках и aliases до запятой; номера домов и адреса — нет."""
    out = []
    for n in [pl.stem, *pl.aliases]:
        n = re.sub(r"\s*\([^)]*\)", "", n.split(",")[0]).strip()
        if len(n) >= 4 and " — " not in n and not re.search(r"\d", n) and n not in SKIP_NAMES:
            out.append(n)
    return list(dict.fromkeys(out))


def patterns(tree):
    """[(regex, place)]: длинные названия раньше коротких («Новые Вербичи» раньше «Вербичи»); одно название у двух мест — пропуск."""
    owner = {}
    for pl in tree.places.values():
        if pl.type in SKIP_TYPES or not pl.real:
            continue
        for n in names_of(pl):
            owner.setdefault(n, set()).add(pl.id)
    pats = []
    for n, ids in sorted(owner.items(), key=lambda x: -len(x[0])):
        if len(ids) == 1:
            pats.append((re.compile(rf"(?<![\w\-«\[]){forms(n)}(?![\w\-\]])"), tree.places[next(iter(ids))]))
    return pats


def mask(text):
    return LINK.sub(lambda m: " " * len(m[0]), text)


def unlinked(fact, pats, tree):
    """[(начало, конец, место)] — по одному на место, первое упоминание; место уже ссылкой в этом факте — пропуск."""
    linked = {tree.places[i].id for i in (cards_place_by_name(tree).get(t) for t in
              re.findall(r"\[\[([^\]|#]+)", fact.text)) if i}
    text, found, taken = mask(fact.text), [], []
    for rx, pl in pats:
        if pl.id in linked or any(pl.id == f[2].id for f in found):
            continue
        for m in rx.finditer(text):
            if AFTER_NAME.search(text[:m.start()]):
                continue
            if not any(a < m.end() and m.start() < b for a, b in taken):
                found.append((m.start(), m.end(), pl))
                taken.append((m.start(), m.end()))
                break
    return sorted(found, key=lambda f: f[0])


_by_name = {}


def cards_place_by_name(tree):
    if not _by_name:
        _by_name.update({pl.stem: pl.id for pl in tree.places.values()})
    return _by_name


def move_translations(renamed):
    """Перевод строки факта лежит под «## <отпечаток>»: строка поменялась — тот же перевод под новым отпечатком."""
    moved = 0
    for p in sorted(paths.TRANSLATIONS.glob("*/facts/*.md")) if renamed else []:
        lines = p.read_text(encoding="utf-8").split("\n")
        new = [f"## {renamed[ln[3:].strip()]}" if ln.startswith("## ") and ln[3:].strip() in renamed else ln for ln in lines]
        if new != lines:
            moved += sum(a != b for a, b in zip(lines, new))
            p.write_text("\n".join(new), encoding="utf-8")
    return moved


def main():
    args = sys.argv[1:]
    do_fix = "--fix" in args
    if "--staged" in args:  # хук pre-commit (sync.py): только карточки людей из коммита; их нет — и дерево не читаем
        out = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=AM", "--", paths.rel(paths.PEOPLE)],
                             cwd=paths.ROOT, capture_output=True, text=True,
                             env={**os.environ, "GIT_CONFIG_PARAMETERS": "'core.quotepath=false'"}).stdout.splitlines()
        args = [Path(x).stem for x in out if x.endswith(".md")]
        if not args:
            return 0
    args = [a for a in args if a not in ("--fix", "--staged")]
    tree = cards.load()
    pats = patterns(tree)
    people = [p for p in tree.people.values() if not args or p.stem in args or p.name in args]
    total, fixed, renamed = 0, 0, {}
    for p in sorted(people, key=lambda p: p.stem):
        path = paths.TREE / "people" / f"{p.stem}.md"
        lines = None
        for f in p.facts:
            if f.label in SKIP_LABELS:
                continue
            hits = unlinked(f, pats, tree)
            if not hits:
                continue
            total += len(hits)
            print(f"{path.relative_to(paths.ROOT)}:{f.line} — место словом, не ссылкой: "
                  + ", ".join(f"«{f.text[a:b]}» → [[{pl.stem}]]" for a, b, pl in hits))
            if do_fix:
                lines = lines or path.read_text(encoding="utf-8").split("\n")
                raw = lines[f.line - 1]
                head, sep, tail = raw.partition(TAIL)
                start = head.index(f.text)
                text = f.text
                for a, b, pl in reversed(hits):
                    word = text[a:b]
                    text = text[:a] + (f"[[{pl.stem}]]" if word == pl.stem else f"[[{pl.stem}|{word}]]") + text[b:]
                lines[f.line - 1] = head[:start] + text + head[start + len(f.text):] + sep + tail
                renamed[tr_store.fact_key(f.label, f.text, f.reasoning)] = tr_store.fact_key(f.label, text, f.reasoning)
                fixed += len(hits)
        if lines:
            path.write_text("\n".join(lines), encoding="utf-8")
    moved = move_translations(renamed)
    if fixed:
        print(f"✅ привязано мест: {fixed}; переводов строк перенесено: {moved}")
    elif total:
        print(f"\nМест словом, не ссылкой: {total} — на карте их нет. Привязать: tools/py tools/scripts/check_fact_places.py --fix")
    else:
        print("✅ места в фактах — ссылками")
    return 1 if total and not fixed else 0


if __name__ == "__main__":
    sys.exit(main())
