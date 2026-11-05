#!/usr/bin/env python3
"""Проверка дерева в Obsidian (3_research/tree): ловит ошибки, которые портят поиск и выводы.

Что проверяет:
  1. ссылка по имени и номер (cr_id) ведут к одному человеку — иначе ссылка ушла на тёзку;
  2. связь взаимна: если у А супруг Б, то у Б супруг А; у ребёнка есть этот родитель и наоборот;
  3. фото и документы из поля media существуют в проекте;
  4. источники из поля sources есть в 3_research/tree/sources;
  5. ветки (lineage) — только из восьми известных;
  6. отец — мужчина, мать — женщина (MyHeritage иногда меняет роли местами);
  7. блок свойств читается (иначе Obsidian и Charted Roots не видят человека вовсе);
  8. номер cr_id не повторяется; название заметки не кончается цифрой («Мария 2» — тёзка без различия);
  9. возможные связи (maybe_same, maybe_kin) и проверенное «нет» (not_same, not_kin): ссылка ведёт на карточку, номер
     совпадает с именем, не на себя; одна пара не стоит сразу в «возможно» и «нет» (в одной карточке или в двух);
 10. рождение, смерть, похороны, брак, развод — одна карточка события на человека (пару): два импорта дерева
     заводили вторую, и в профиле было два рождения или два брака.

Запуск:  python3 tools/scripts/check_tree.py          # список ошибок, код выхода 1, если есть
         python3 tools/scripts/check_tree.py --quiet  # одна строка-итог
Вызывается автоматически после правок в 3_research/tree (хук в .claude/settings.json).
"""
import os
import re
import sys
import unicodedata

try:
    import yaml  # тот же разбор, что у Obsidian: сломанный блок свойств — карточки для дерева нет
except ImportError:
    yaml = None
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

N = lambda s: unicodedata.normalize("NFC", s)
LINES = set(paths.LINES)  # ветки — из ftree.toml
REL = ("father", "mother", "spouse", "children")
ONCE = ("birth", "death", "burial", "marriage", "divorce")  # бывает раз — у человека (или пары) одна карточка события
MAYBE = (("maybe_same", "not_same"), ("maybe_kin", "not_kin"))  # «возможно» и «проверено: нет» — одна пара не в обоих


def fm(text):
    m = re.match(r"---\n(.*?)\n---", text, re.S)
    return m.group(1) if m else None


def values(f, key):
    m = re.search(rf"^{key}:(.*(?:\n  - .*)*)", f, re.M)
    if not m:
        return []
    return [x.strip().strip('"') for x in re.findall(r"(?:^ ?|\n  - )([^\n]+)", m.group(1)) if x.strip().strip('"')]


link = lambda x: N(re.sub(r"^\[\[([^\]|]+).*", r"\1", x)) if x.startswith("[[") else None


def main():
    people = paths.TREE / "people"
    files = {N(p.stem): p for p in people.glob("*.md")}
    sources = {N(p.stem) for p in (paths.TREE / "sources").rglob("*.md")}
    names_in_project = set()
    for d, ds, fs in os.walk(paths.ROOT):
        if os.path.relpath(d, paths.ROOT).startswith((".git", "tools", ".obsidian")):
            ds[:] = []
            continue
        names_in_project.update(N(f) for f in fs)

    notes, errors = {}, []
    for n, p in files.items():
        f = fm(p.read_text(encoding="utf-8"))
        if f is None:
            errors.append(f"{n}: нет блока свойств (---)")
            continue
        if yaml:
            try:
                yaml.safe_load(f)
            except Exception as e:
                errors.append(f"{n}: блок свойств не читается ({str(e).splitlines()[0]}) — "
                              f"значение с «: » возьми в кавычки")
        notes[n] = f
    cr = {n: (re.search(r"^cr_id: (\S+)", f, re.M) or [None, None])[1] for n, f in notes.items()}
    by_id = defaultdict(list)
    for n, c in cr.items():
        by_id[c].append(n)
    for c, ns in by_id.items():
        if c is None:
            errors.extend(f"{n}: нет cr_id" for n in ns)
        elif len(ns) > 1:
            errors.append(f"cr_id {c} у нескольких: {', '.join(ns)}")
        if c and "-" in c and not re.fullmatch(r"[a-z]{3}-\d{3}-[a-z]{3}-\d{3}", c):     # формат сайта (web/ schema): abc-123-def-456
            errors.extend(f"{n}: cr_id {c} не по образцу abc-123-def-456 — сайт не соберётся" for n in ns)
    owner = {c: ns[0] for c, ns in by_id.items() if c}

    rel = {k: {} for k in REL}
    for n, f in notes.items():
        if re.search(r" \d+$", n):
            errors.append(f"{n}: название кончается цифрой — назовите по году или родителю")
        for key in REL:
            links = [link(x) for x in values(f, key) if x.startswith("[[")]
            ids = values(f, key + "_id")
            rel[key][n] = set(ids)
            for l, i in zip(links, ids):
                if cr.get(l) != i:
                    errors.append(f"{n}: {key} → [[{l}]], а номер {i} — это [[{owner.get(i, '?')}]]")
        for key in (k for pair in MAYBE for k in pair):
            links = [link(x) for x in values(f, key) if x.startswith("[[")]
            ids = values(f, key + "_id")
            if ids and len(ids) != len(links):
                errors.append(f"{n}: {key} — ссылок {len(links)}, а номеров в {key}_id {len(ids)}")
            for l in links:
                if l == n:
                    errors.append(f"{n}: {key} → [[{l}]] — ссылка на себя")
                elif l not in notes:
                    errors.append(f"{n}: {key} → [[{l}]] — нет такой карточки")
            for l, i in zip(links, ids):
                if l in notes and cr.get(l) != i:
                    errors.append(f"{n}: {key} → [[{l}]], а номер {i} — это [[{owner.get(i, '?')}]]")
        for key, want in (("father", "male"), ("mother", "female")):
            for x in values(f, key):
                par = link(x)
                if par in notes:
                    sex = (re.search(r"^sex: (\S+)", notes[par], re.M) or [None, None])[1]
                    if sex and sex != want:
                        errors.append(f"{n}: {key} [[{par}]] по полу не подходит ({sex}) — отец и мать перепутаны?")
        for m in values(f, "media"):
            name = link(m)
            if name and os.path.basename(name) not in names_in_project:
                errors.append(f"{n}: фото не найдено — {name}")
        for s in values(f, "sources"):
            name = link(s)
            if name and name not in sources:
                errors.append(f"{n}: источник не найден — [[{name}]]")
        for key in ("lineage", "lineage_by_marriage"):
            for v in values(f, key):
                if v not in LINES:
                    errors.append(f"{n}: неизвестная ветка «{v}» в {key}")

    # «**Биография:**» ведёт на раздел про другого человека — сайт покажет у него чужую жизнь. Чей раздел — видно
    # по строке «**В дереве:** [[Карточка|…]]» сразу под заголовком (в старых заголовках — по ссылке в самом заголовке).
    # Если человек там только упомянут, строка должна быть «**Упоминается в биографии:**».
    def owner_of(target, head):
        whose = re.findall(r"\[\[([^\]|]+)\|", head)
        bio = paths.ROOT / (target if target.endswith(".md") else target + ".md")
        if whose or not bio.exists():
            return whose
        plain = lambda h: re.sub(r"\s+", " ", re.sub(r"\[\[[^\]]*\]\]|[\[\]*_`]", "", h)).strip()
        text = N(bio.read_text(encoding="utf-8"))
        m = next((m for m in re.finditer(r"^#+\s+(.+)$", text, re.M) if plain(m.group(1)) == plain(head.split("#")[-1])), None)
        under = re.match(r"\s*\*\*В дереве:\*\*([^\n]*)", text[m.end():]) if m else None  # раздел на двоих — оба
        return re.findall(r"\[\[([^\]|]+)", under.group(1)) if under else []

    for n in notes:
        body = N(files[n].read_text(encoding="utf-8"))
        for target, head in re.findall(r"^\*\*Биография:\*\*\s*\[\[([^\]#]+)#(.+)\]\]\s*$", body, re.M):
            whose = owner_of(target, head)
            if whose and n not in whose:
                errors.append(f"{n}: «Биография» ведёт на раздел про [[{whose[0]}]] — если он там только упомянут, "
                              f"пишите «**Упоминается в биографии:**»")

    pairs = defaultdict(set)   # (поле, {a, b}) → в каких карточках записано
    for n, f in notes.items():
        for key in (k for pair in MAYBE for k in pair):
            for x in values(f, key):
                if link(x) in notes and link(x) != n:
                    pairs[key, frozenset((n, link(x)))].add(n)
    for maybe, no in MAYBE:
        for (key, pair), _ in sorted(pairs.items(), key=lambda kv: sorted(kv[0][1])):
            if key == maybe and (no, pair) in pairs:
                a, b = sorted(pair)
                errors.append(f"{a} ↔ {b}: пара сразу в {maybe} и {no} — решите, что верно, и уберите другое")

    for n in notes:
        me = cr[n]
        for s in rel["spouse"][n]:
            if s in owner and me not in rel["spouse"].get(owner[s], set()):
                errors.append(f"{n}: супруг [[{owner[s]}]] без пары — у него/неё нет обратной ссылки")
        for c in rel["children"][n]:
            if c in owner and me not in rel["father"].get(owner[c], set()) | rel["mother"].get(owner[c], set()):
                errors.append(f"{n}: ребёнок [[{owner[c]}]] не называет этого человека родителем")
        for par in rel["father"][n] | rel["mother"][n]:
            if par in owner and me not in rel["children"].get(owner[par], set()):
                errors.append(f"{n}: родитель [[{owner[par]}]] не называет этого человека ребёнком")

    # 10. одно событие жизни — одна карточка: два импорта дерева завели второе рождение, смерть, брак (01.11.2026)
    once = defaultdict(list)
    for e in sorted((paths.TREE / "events").glob("*.md")):
        f = fm(e.read_text(encoding="utf-8")) or ""
        kind = (values(f, "event_type") or [""])[0]
        if kind in ONCE:
            who = tuple(sorted({link(x) for x in values(f, "persons") + values(f, "person") if link(x)}))
            if who:
                once[kind, who].append(e.name)
    for (kind, who), names in once.items():
        if len(names) > 1:
            errors.append(f"{', '.join(who)}: событие {kind} — {len(names)} карточки ({'; '.join(names)}): "
                          f"слить в одну (место, описание — из второй), вторую удалить")

    if errors and "--quiet" not in sys.argv:
        print("\n".join(errors))
    print(f"Проверка дерева: людей {len(notes)}, ошибок {len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
