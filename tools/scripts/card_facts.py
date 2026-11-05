#!/usr/bin/env python3
"""Дописать факты из нового источника в карточки дерева — по одной строке, в нужный раздел.

Зачем. После разговора фактов десятки, а карточек — пятнадцать-двадцать. Руками легко вставить факт
не в тот раздел или забыть ссылку на источник. Эта библиотека делает одинаково во всех карточках:
раздел «Факты (с источником)» / «Слова дословно» / «Расхождения» / «Открытые вопросы», источник —
в `sources:` карточки и в раздел «Источники», ссылка на биографию — наверху «Фактов и заметок».

Использование (из скрипта или python - <<EOF):
    import sys; sys.path.insert(0, "tools/scripts"); import card_facts as cf
    cf.SRC = "Аудио 07 — …"; cf.BIO = "[[3_research/tree/biographies/<Имя карточки> — биография.md]]"
    cf.upd("Прокоп Ясенев", tc="мм:сс–мм:сс", fm={"died": "1921"},
           facts=[cf.F("смерть", "1921, Вербичи", "54:55", "высокая")], openq=["- …"])
Потом — check_tree.py. SRC задавать всегда: значения по умолчанию нет.
"""
import re, pathlib, random, string
from paths import TREE as T  # noqa: E402
SRC = ""  # источник — карточка в 3_research/tree/sources без .md: «Аудио 07 — разговор с отцом»
BIO = ""  # «Упоминается в биографии: [[…]]» — только если задан явно; своя биография — `**Биография:**` руками

def cr():
    r = lambda: "".join(random.choice(string.ascii_lowercase) for _ in range(3))
    d = lambda: "%03d" % random.randint(0, 999)
    return f"{r()}-{d()}-{r()}-{d()}"

def F(what, val, tc, conf="обычная"):
    if not SRC:
        raise SystemExit("card_facts: задайте cf.SRC — карточку источника")
    return f"- **{what}:** {val} — *источник: [[{SRC}]], {tc} · уверенность: {conf}*"

def set_fm(txt, key, val):
    fm_end = txt.index("\n---", 3)
    fm = txt[:fm_end]
    if re.search(rf"^{key}:.*$", fm, flags=re.M):
        fm = re.sub(rf"^{key}:.*$", f"{key}: {val}", fm, count=1, flags=re.M)
    else:
        fm += f"\n{key}: {val}"
    return fm + txt[fm_end:]

def add_source_fm(txt):
    fm_end = txt.index("\n---", 3); fm = txt[:fm_end]
    link = f'  - "[[{SRC}]]"'
    if SRC in fm: return txt
    if re.search(r"^sources:\s*$", fm, flags=re.M):
        fm = re.sub(r"^sources:\s*$", "sources:\n" + link, fm, count=1, flags=re.M)
    elif re.search(r"^sources:.+$", fm, flags=re.M):  # inline value
        m = re.search(r"^sources:(.+)$", fm, flags=re.M)
        fm = fm.replace(m.group(0), "sources:\n  - " + m.group(1).strip() + "\n" + link)
    else:
        fm += "\nsources:\n" + link
    return fm + txt[fm_end:]

def section(txt, name, lines, level="###"):
    """Дописать строки в конец раздела ### name (создать раздел внутри «Факты и заметки»)."""
    if not lines: return txt
    block = "\n".join(lines)
    h = f"{level} {name}"
    if "## Факты и заметки" not in txt:
        # перед «## Рассказ» / «## Источники», иначе в конец
        m = re.search(r"^## (Рассказ|Источники)", txt, flags=re.M)
        ins = "## Факты и заметки\n\n"
        txt = txt[:m.start()] + ins + txt[m.start():] if m else txt.rstrip() + "\n\n" + ins
    if h in txt:
        i = txt.index(h) + len(h)
        m = re.compile(r"^#{2,3} ", re.M).search(txt, i)
        j = m.start() if m else len(txt)
        body = txt[i:j].rstrip()
        return txt[:i] + body + "\n" + block + "\n\n" + txt[j:]
    # новый раздел: после последнего ### внутри «Факты и заметки» — перед следующим «## »
    i = txt.index("## Факты и заметки") + len("## Факты и заметки")
    m = re.compile(r"^## ", re.M).search(txt, i)
    j = m.start() if m else len(txt)
    order = ["Факты (с источником)", "Слова дословно", "Расхождения", "Открытые вопросы"]
    # вставить с учётом порядка: перед первым существующим разделом, который идёт позже
    later = [o for o in order[order.index(name)+1:] if f"### {o}" in txt[i:j]] if name in order else []
    if later:
        k = txt.index(f"### {later[0]}", i)
        return txt[:k] + f"{h}\n\n{block}\n\n" + txt[k:]
    return txt[:j].rstrip() + f"\n\n{h}\n\n{block}\n\n" + txt[j:]

def add_bio(txt):
    if not BIO or BIO.strip("[]").removesuffix(".md") in txt: return txt  # не задана или уже есть
    i = txt.index("## Факты и заметки") + len("## Факты и заметки")
    return txt[:i] + f"\n\n**Упоминается в биографии:** {BIO}" + txt[i:]

def add_src_list(txt, tc):
    line = f"- [[{SRC}]] — {tc} · уверенность: обычная · происхождение: семья"
    if line in txt: return txt
    if "## Источники" in txt:
        return txt.rstrip() + "\n" + line + "\n"
    return txt.rstrip() + "\n\n## Источники\n\n" + line + "\n"

def upd(name, facts=(), words=(), contra=(), openq=(), fm=None, tc=""):
    p = T / "people" / f"{name}.md"
    txt = p.read_text(encoding="utf-8")
    for k, v in (fm or {}).items():
        txt = set_fm(txt, k, v)
    txt = add_source_fm(txt)
    txt = section(txt, "Факты (с источником)", list(facts))
    txt = section(txt, "Слова дословно", list(words))
    txt = section(txt, "Расхождения", list(contra))
    txt = section(txt, "Открытые вопросы", list(openq))
    txt = add_bio(txt)
    txt = add_src_list(txt, tc)
    from cards import layout   # разделы — по образцу карточки (порядок, пустых нет; check_cards.py проверяет то же)
    head = txt[: len(txt) - len(txt.split("\n---\n", 1)[1])]
    p.write_text(head + "\n" + layout.fix(txt[len(head):]), encoding="utf-8")
    print("ok", name)
