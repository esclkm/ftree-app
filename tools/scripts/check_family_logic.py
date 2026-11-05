#!/usr/bin/env python3
"""Логика семьи по датам — то, что раньше держали в голове, теперь проверка (просьба Павла, 14.10.2026).

Что проверяет (правила — навык card-rules, раздел «Логика по датам»):
  1. Возраст родителей при рождении ребёнка: мать 14–50, отец 15–80. Возраст в метриках и переписях расходится до
     3–4 лет — это не довод (правило Павла), поэтому считаем с допуском ±4 года: ошибка — только если не сходится и с ним.
  2. Мать по датам: у ребёнка есть отец, матери нет, а у отца одна жена, и с ней у него есть дети, родившиеся рядом
     (±6 лет) — она вероятная мать. Это подсказка, не правка: решает человек (так находится мать: жена отца в тех же годах).
     Если в карточке сказано «от первой жены» (документ называет другую мать) — подсказки нет.
  3. Фамилия: фамилия выведена (`surname_inferred`) — в фактах нужна строка «- **Фамилия:** …» (где нашли или «в
     документах нет» и как звался по отцу). У жены, родившейся до 1900 г., фамилия по мужу (`surname_inferred` «по мужу»)
     — подсказка: по правилу её зовут по отцу, как в метриках (Агата Прокопова, не Ясенева).

  4. Смерть раньше ребёнка: ребёнок родился позже, чем через год после смерти отца (у матери — после её смерти), даже
     с допуском ±4 — ошибка в связи или дате.
  5. Отец по отчеству: у звена к нам (уровень «доказано» / «вероятно», есть дети в дереве), родившегося до 1900 г., отца
     нет, а «фамилия» — отчество (Ирина Прокопова — дочь Прокопа, Иван Прокопов — сын Прокопа). Отца заводим карточкой одинаково
     у мужчин и у женщин — иначе материнские линии обрываются на каждой жене.
  6. Года смерти нет у звена, родившегося до 1900 г., — ставим «после» последней даты, где он жив (died: AFT <год>).

Подсказки 2, 5, 6 вносятся командой — правка и строка факта с обоснованием; решает человек, какие вносить:
  tools/py tools/scripts/check_family_logic.py            # ошибки и подсказки; код 1, если есть ошибки
  tools/py tools/scripts/check_family_logic.py --quiet    # только итог
  tools/py tools/scripts/check_family_logic.py --link-mother "<карточка ребёнка>"   # мать по датам → mother + факт
  tools/py tools/scripts/check_family_logic.py --add-father "<карточка>"            # отец по отчеству → новая карточка
  tools/py tools/scripts/check_family_logic.py --died-after "<карточка>" [год]      # died: AFT <год> + факт
  tools/py tools/scripts/check_family_logic.py --surname-lines [--apply]   # строки «Фамилия:» по образцу; спорные — списком
"""
import re
import sys
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

TOL = 4                        # лет: допуск на неточный возраст в документах
MOTHER = (14, 50)
FATHER = (15, 80)
NEAR = 6
OLD = 1900                     # родившиеся раньше — точно умерли; фамилий у крестьян ещё нет                       # лет: «дети рядом» для вывода матери
WIFE_BY_FATHER_BEFORE = 1900   # жёны, родившиеся раньше, — по отцу, а не по мужу


def years(g):
    """(самый ранний, самый поздний) год даты GDate или (None, None)."""
    if g is None:
        return None, None
    lo = getattr(g, "first_year", None)
    hi = getattr(g, "last_year", None)
    lo = lo() if callable(lo) else lo
    hi = hi() if callable(hi) else hi
    hi = hi if hi is not None else lo
    kind = getattr(g, "kind", "")
    if kind == "AFT":              # «после 1861» — сверху не ограничено
        return lo, None
    if kind == "BEF":              # «до 1793» — снизу не ограничено
        return None, hi
    return lo, hi


def parent_age_problem(parent_years, child_years, limits, tol=TOL):
    """Возраст родителя при рождении ребёнка вне границ даже с допуском — текст ошибки, иначе None.
    parent_years, child_years — (ранний, поздний) год; limits — (мин, макс) возраст."""
    (plo, phi), (clo, chi) = parent_years, child_years
    if None in (plo, phi, clo, chi):
        return None
    youngest = clo - phi           # самый маленький возможный возраст родителя
    oldest = chi - plo             # самый большой
    lo, hi = limits
    if oldest < lo - tol:
        return f"родителю при рождении ребёнка не больше {oldest} лет (норма от {lo}, допуск ±{tol})"
    if youngest > hi + tol:
        return f"родителю при рождении ребёнка не меньше {youngest} лет (норма до {hi}, допуск ±{tol})"
    return None


def mother_candidate(child_years, father_spouses, siblings, wife_years=(None, None)):
    """Вероятная мать ребёнка без матери: у отца одна жена, и с ней у него есть дети в пределах NEAR лет — или, если
    год её рождения известен, ребёнок родился, когда ей было 14–50 (с допуском): другой жены у отца в документах нет.
    father_spouses — [cr_id]; siblings — [(cr_id матери, (ранний, поздний) год)] — дети отца с известной матерью."""
    if len(father_spouses) != 1 or None in child_years:
        return None
    wife = father_spouses[0]
    if None not in wife_years and parent_age_problem(wife_years, child_years, MOTHER) is None:
        return wife
    clo, chi = child_years
    for mom, (slo, shi) in siblings:
        if mom == wife and slo is not None and shi is not None and slo - NEAR <= chi and clo <= shi + NEAR:
            return wife
    return None


def death_before_birth(parent_died, child_years, kind, tol=TOL):
    """Ребёнок родился после смерти родителя (отец — позже чем через год) даже с допуском — текст ошибки, иначе None."""
    dlo, dhi = parent_died
    clo, chi = child_years
    if None in (dlo, dhi, clo, chi):
        return None
    gap = 1 if kind == "отец" else 0
    if clo - tol > dhi + gap:
        return f"ребёнок родился не раньше {clo}, а {kind} умер(ла) не позже {dhi} (допуск ±{tol})"
    return None


def _patronymic_index(extra=()):
    """«петров» → «Пётр», «сергеев» → «Сергей»: отчество-фамилия → имя отца (первая форма ряда равных имён)."""
    import name_forms as nf
    names = [row[0] for row in nf.GIVEN] + [n for n in extra if n]
    out = {}
    for n in names:
        canon = nf.forms(n)[0]
        for s in nf.patronymic_surnames(n):
            out.setdefault(s, canon.capitalize())
    return out


def father_by_patronymic(name, sex, index):
    """Имя отца по «фамилии»-отчеству: «Ирина Петрова» → «Пётр»; не похоже на отчество — None."""
    words = name.split()
    if len(words) < 2:
        return None
    w = words[-1].lower()
    if sex == "F" and w.endswith(("ова", "ева", "ина", "ёва")):
        w = w[:-1]
    return index.get(w)


DEATH_WORDS = re.compile(r"смерт|умер|умерл|погреб|похорон|(его|её|ее) вдов|вдова его|покойн|после смерти", re.I)
# Только имя в отчестве ребёнка («его сын записан „Иван Прокопов“») — не значит, что сам жив
NAME_ONLY = re.compile(r"(сын|дочь|дети) записан[аы]? «|в отчестве (сына|дочери)|только по отчеству", re.I)


OWN_BIRTH = re.compile(r"^(рождение|крещение|родил(ся|ась)|рожд\.?)$", re.I)


def last_alive_year(facts, born_last=None):
    """Последний год, когда человек по фактам ещё жив: самая поздняя дата факта, кроме фактов о смерти и о его же
    рождении (жив в год рождения — не довод) — (год, факт)."""
    best = (None, None)
    for f in facts:
        if f.date is None or DEATH_WORDS.search(f.label + " " + f.text[:200]) or OWN_BIRTH.match(f.label.strip()) \
                or NAME_ONLY.search(f.label + " " + f.text[:200]):
            continue
        if born_last is not None and f.date.last_year is not None and f.date.last_year <= born_last:
            continue
        y = f.date.last_year
        if y is not None and (best[0] is None or y > best[0]):
            best = (y, f)
    return best


FACT_SURNAME = re.compile(r"^- \*\*Фамилия:\*\*", re.M)


def is_old(born_years, died_years, kid_years):
    """Жил до того, как у крестьян появились фамилии: род. до 1900, умер до 1920 или дети до 1915."""
    return any(y is not None and y < lim for y, lim in ((born_years[1], OLD), (died_years[1], 1920),
                                                         (min([k for k in kid_years if k] or [None], key=lambda x: x or 0), 1915)))


SURNAME_RE = re.compile(r"^\s*(\S+)\s+—\s+по\s+(отцу|мужу):\s*\[\[([^\]|]+)")


def surname_kind(inferred, sex, old, married):
    """Вид строки «Фамилия:» по образцу (Павел, 15.10.2026) или None — спорная, решает человек.
    → (вид, фамилия, «отцу»/«мужу», карточка-родня): «old_wife» · «modern_father» · «married_father» · «modern_husband»."""
    m = SURNAME_RE.match(str(inferred or ""))
    if not m:
        return None
    sur, by, rel = m.group(1), m.group(2), m.group(3).strip()
    if by == "мужу":
        return ("old_wife" if old else "modern_husband", sur, by, rel)
    if old:
        return None            # предок «по отцу»: в метриках фамилия то есть, то нет — смотреть документ глазами
    return ("married_father" if sex == "F" and married else "modern_father", sur, by, rel)


def surname_line(kind, sur, rel, src_text, prov_text, children_names="", kids_surname="", in_record=False):
    """Строка «- **Фамилия:** …» по образцу; src_text — «[[Источник]], где» для хвоста строки.
    kids_surname — фамилия детей, если не её (тогда это, вероятно, фамилия мужа); in_record — фамилия есть в найденной записи."""
    seen = "так и в найденных записях" if in_record else f"документа о фамилии у нас нет — {prov_text}"
    if kids_surname:
        married = f"она замужем; по мужу, вероятно, {kids_surname} — так записаны дети ({children_names})"
    else:
        married = "она замужем, фамилию по мужу не знаем" + (
            f" — её детей ({children_names}) искать под фамилией мужа" if children_names else "")
    body = {
        "modern_father": f"{sur} — по отцу [[{rel}]]; {seen}",
        "married_father": f"{sur} — по отцу [[{rel}]]; {married}; {seen}",
        "modern_husband": f"{sur} — по мужу [[{rel}]]; девичья неизвестна; {prov_text}",
        "old_wife": f"девичья неизвестна — в наших документах её нет; «{sur}» — по мужу [[{rel}]]. По правилу жён "
                    f"XIX века зовём по отцу, но имя её отца неизвестно, поэтому карточка пока по мужу; {prov_text}",
    }[kind]
    conf = "низкая" if kind in ("old_wife", "married_father") else "обычная"
    return f"- **Фамилия:** {body} — *источник: {src_text} · уверенность: {conf} (вывод проекта)*"


PROV_TEXT = {"family": "так в семейных источниках", "found": "так в найденных записях", "other_tree": "взято из дерева MyHeritage",
             "inference": "вывод проекта"}


def surname_plan(tree):
    """→ (готовые [(человек, строка)], спорные [(человек, почему)]) для карточек с surname_inferred без строки «Фамилия:»."""
    P = tree.people
    ready, doubt = [], []
    for p in sorted(P.values(), key=lambda x: x.stem):
        inf = p.fm.get("surname_inferred")
        if not inf or FACT_SURNAME.search(p.body or ""):
            continue
        kids = [years(P[c].born)[1] for c in p.children if c in P]
        old = is_old(years(p.born), years(p.died), kids)
        k = surname_kind(inf, p.sex, old, bool(p.spouses))
        if not k:
            doubt.append((p, "предок «по отцу» — смотреть документ" if SURNAME_RE.match(str(inf)) else
                         f"surname_inferred без объяснения ({inf!r})"))
            continue
        kind, sur, by, rel = k
        stem = (sur[:-1] if sur.endswith("а") else sur).lower()
        in_record = any(f.provenance == "found" and stem in f.text.lower() for f in p.facts)
        if in_record and years(p.born)[1] is not None and years(p.born)[1] < 1918:
            doubt.append((p, "фамилия есть в найденной старой записи — вписать, где именно (документ, лист)"))
            continue
        own = [tree.sources[s] for s in p.sources if s in tree.sources]
        relp = tree.person(rel)
        if not own and relp:
            own = [tree.sources[s] for s in relp.sources if s in tree.sources]
        if not own:
            doubt.append((p, f"нет источника ни у неё/него, ни у [[{rel}]]"))
            continue
        provs = [f.provenance for f in p.facts] + [s.provenance for s in own]
        prov = next((x for x in ("family", "found", "other_tree", "inference") if x in provs), "inference")
        src_text = "; ".join(f"[[{s.stem}]]" for s in own[:2]) + ("" if p.sources else f", из карточки «{rel}»")
        names = ", ".join(P[c].name for c in p.children if c in P)
        kid_sur = [P[c].name.split()[-1] for c in p.children if c in P and len(P[c].name.split()) > 1]
        kid_sur = max(set(kid_sur), key=kid_sur.count) if kid_sur else ""
        kid_sur = kid_sur if kid_sur and kid_sur.lower()[:4] != sur.lower()[:4] else ""
        ready.append((p, surname_line(kind, sur, rel, src_text, PROV_TEXT[prov], names, kid_sur, in_record)))
    return ready, doubt


def put_fact(p, line):
    """Строка факта в карточку; нет раздела «Факты» — завести перед «## Источники» или в конце."""
    from paths import TREE
    path = TREE / "people" / f"{p.stem}.md"
    text = path.read_text()
    head = "### Факты (с источником)\n\n"
    if head in text:
        text = text.replace(head, head + line + "\n", 1)
    elif "\n## Источники" in text:
        text = text.replace("\n## Источники", f"\n## Факты и заметки\n\n{head}{line}\n\n## Источники", 1)
    else:
        text = text.rstrip("\n") + f"\n\n## Факты и заметки\n\n{head}{line}\n"
    path.write_text(text)


def surname_problems(fm, body, born_years, old=None):
    """Подсказки по фамилии карточки: [(уровень, текст)]. old — жила до 1900 по другим признакам (смерть, дети)."""
    out = []
    inf = fm.get("surname_inferred")
    if inf and not FACT_SURNAME.search(body or ""):
        out.append(("warning", "фамилия выведена (surname_inferred) — нужна строка «- **Фамилия:**»: где нашли или "
                               "«в документах нет» и как звался по отцу"))
    blo = born_years[0]
    if isinstance(inf, str) and "по мужу" in inf and ((blo is not None and blo < WIFE_BY_FATHER_BEFORE) or old) \
            and "имя её отца неизвестно" not in (body or ""):
        out.append(("warning", f"жена, род. до {WIFE_BY_FATHER_BEFORE}, записана с фамилией мужа — по правилу её зовут "
                               "по отцу, как в метриках (переименовать карточку)"))
    return out


def run(tree, plan=None):
    """→ (ошибки, подсказки). plan — словарь, куда кладём, что можно внести командой: {"mother"|"father"|"died": {cr_id: …}}."""
    from cards.kinship import levels
    plan = {} if plan is None else plan
    for k in ("mother", "father", "died"):
        plan.setdefault(k, {})
    errors, hints = [], []
    P = tree.people
    lv = levels(tree)
    index = _patronymic_index(p.name.split()[0] for p in P.values() if p.name)
    for pid, p in P.items():
        cy = years(p.born)
        for kind, ids, limits in (("мать", p.mother, MOTHER), ("отец", p.father, FATHER)):
            for par in ids:
                if par in P:
                    msg = parent_age_problem(years(P[par].born), cy, limits)
                    if msg:
                        errors.append(f"{p.stem}: {kind} [[{P[par].stem}]] — {msg}")
                    msg = death_before_birth(years(P[par].died), cy, kind)
                    if msg:
                        errors.append(f"{p.stem}: {kind} [[{P[par].stem}]] — {msg}")
        other_wife = re.search(r"(перв\w* жен|1-й жен|от 1 жен)", p.body or "", re.I)   # документ: от другой жены
        if p.father and not p.mother and p.father[0] in P and not other_wife:
            f = P[p.father[0]]
            sibs = [(P[c].mother[0], years(P[c].born)) for c in f.children
                    if c in P and c != pid and P[c].mother]
            wy = years(P[f.spouses[0]].born) if len(f.spouses) == 1 and f.spouses[0] in P else (None, None)
            cand = mother_candidate(cy, list(f.spouses), sibs, wy)
            if cand and cand in P:
                plan["mother"][pid] = cand
                hints.append(f"{p.stem}: матери нет, а у отца [[{f.stem}]] одна жена [[{P[cand].stem}]] и дети с ней "
                             f"рядом по годам — вероятная мать (решить и записать с обоснованием)")
        kids_y = [years(P[c].born)[1] for c in p.children if c in P]
        for lvl, msg in surname_problems(p.fm, p.body, years(p.born), is_old(years(p.born), years(p.died), kids_y)):
            hints.append(f"{p.stem}: {msg}")
        link = lv.get(pid, ("", ""))[0] in ("proven", "likely") and p.children
        old = cy[1] is not None and cy[1] < OLD
        if link and old and not p.father:
            dad = father_by_patronymic(p.name, p.sex, index)
            if dad:
                plan["father"][pid] = dad
                hints.append(f"{p.stem}: отца нет, а «{p.name.split()[-1]}» — отчество: отец — {dad}; завести карточку "
                             f"(--add-father), иначе линия обрывается")
        if link and old and p.died is None:
            y, f = last_alive_year(p.facts, cy[1])
            # рождение ребёнка — тоже «жив»: мать — в год рождения, отец — за год до него
            for c in p.children:
                if c in P and P[c].born is not None and not P[c].born.approx:
                    cyy = P[c].born.first_year - (1 if p.sex == "M" else 0)
                    if cyy and (y is None or cyy > y):
                        y, f = cyy, SimpleNamespace(label=f"рождение ребёнка [[{P[c].stem}]]", text="", refs=[])
            if y:
                plan["died"][pid] = (y, f)
                hints.append(f"{p.stem}: года смерти нет — жив(а) в {y} («{f.label or f.text[:40]}»): died: AFT {y} "
                             f"(--died-after)")
    return errors, hints


# --- внесение подсказок командой ---

def _split(text):
    """Карточка → (свойства без закрывающей черты, остальное с ней)."""
    end = text.index("\n---", 4)
    return text[:end], text[end:]


def _set_prop(fm, key, value, after):
    """Поставить простое свойство key: value — заменить пустое или вставить после строки свойства after."""
    if re.search(rf"^{key}:[ \t]*\S", fm, re.M):
        raise SystemExit(f"уже есть {key} — не трогаю")
    if re.search(rf"^{key}:[ \t]*$", fm, re.M):
        return re.sub(rf"^{key}:[ \t]*$", f"{key}: {value}", fm, count=1, flags=re.M)
    for a in after:
        m = re.search(rf"^{a}:.*$", fm, re.M)
        if m:
            return fm[:m.end()] + f"\n{key}: {value}" + fm[m.end():]
    return fm + f"\n{key}: {value}"


def _add_to_list(fm, key, value):
    m = re.search(rf"^{key}:[ \t]*(\S.*)$", fm, re.M)       # одно значение строкой — сначала в список
    if m:
        fm = fm[:m.start()] + f"{key}:\n  - {m.group(1)}" + fm[m.end():]
    if re.search(rf"^{key}:[ \t]*\n((?:  - .*\n?)*)", fm, re.M):
        return re.sub(rf"^({key}:[ \t]*\n(?:  - .*\n)*)", lambda g: g.group(1) + f"  - {value}\n", fm + "\n",
                      count=1, flags=re.M).rstrip("\n")
    return fm + f"\n{key}:\n  - {value}"


def _add_fact(rest, line):
    head = "### Факты (с источником)\n\n"
    if head not in rest:
        raise SystemExit("в карточке нет раздела «### Факты (с источником)»")
    return rest.replace(head, head + line + "\n", 1)


def _src(tree, p):
    names = [f"[[{tree.sources[s].stem}]]" for s in p.sources if s in tree.sources][:3]
    return "; ".join(names) or "карточка"


def link_mother(tree, child, mom):
    path = child.path if hasattr(child, "path") else None
    c, m = child, tree.people[mom]
    f = tree.people[c.father[0]]
    line = (f"- **Мать:** [[{m.stem}]] — по датам: у отца [[{f.stem}]] в документах одна жена — она, и ребёнок родился, "
            f"когда ей было по годам 14–50 (правило «мать по датам», навык card-rules); записи «от другой жены» нет — "
            f"*источник: {_src(tree, f)} · уверенность: средняя (вывод проекта по датам)*")
    _write(c, lambda fm: _set_prop(_set_prop(fm, "mother", f'"[[{m.stem}]]"', ["father_id", "father"]),
                                   "mother_id", m.id, ["mother"]), line)
    _write(m, lambda fm: _add_to_list(_add_to_list(fm, "children", f'"[[{c.stem}]]"'), "children_id", c.id))
    print(f"мать {m.stem} → {c.stem}")


def add_father(tree, child, dad):
    import cards.people as _  # noqa: F401  — только чтобы убедиться, что пакет на месте
    from paths import TREE
    stem = father_stem(dad, child)
    path = TREE / "people" / f"{stem}.md"
    if path.exists():
        raise SystemExit(f"уже есть карточка {stem}")
    cid = _new_id(tree)
    clo = years(child.born)[0]
    level = str(child.fm.get("kinship") or "вероятно")
    src = _src(tree, child)
    rel = "дочери" if child.sex == "F" else "сына"
    path.write_text(f"""---
cr_id: {cid}
cr_type: person
name: {dad}
born: "BEF {clo - FATHER[0]}"
kinship: {level}
sex: male
children:
  - "[[{child.stem}]]"
children_id:
  - {child.id}
lineage:
  - "{(child.fm.get('lineage') or [''])[0]}"
---

# Research Notes

## Факты и заметки

### Факты (с источником)

- **Фамилия:** неизвестна; известен только по отчеству {rel} — *источник: {src} · уверенность: низкая (вывод проекта)*
- **Имя:** известно только по отчеству {rel} — «{child.name}» — *источник: {src} · уверенность: средняя (имя — по отчеству)*
- **Родство:** {level} — отец [[{child.stem}|{genitive(child.name, child.sex)}]]: уровень не выше, чем у {"неё" if child.sex == "F" else "него"} — *источник: {src} · уверенность: средняя (вывод проекта)*

### Открытые вопросы

- Сам он, его годы и другие дети — в ревизских сказках и метриках прихода до рождения [[{child.stem}|{genitive(child.name, child.sex)}]].
""")
    _write(child, lambda fm: _set_prop(_set_prop(fm, "father", f'"[[{stem}]]"', ["sex", "kinship", "born"]),
                                       "father_id", cid, ["father"]))
    print(f"заведён {stem} ({cid}); дальше — assign_lineage.py")


def died_after(tree, p, y, f):
    what = f.label or f.text[:60]
    line = (f"- **Смерть:** после {y} — в {y} г. ещё жив(а) («{what}»); записи о смерти не найдено — *источник: "
            f"{_refs(tree, f) or _src(tree, p)} · уверенность: средняя "
            f"(вывод проекта: последняя запись, где жив(а))*")
    _write(p, lambda fm: _set_prop(fm, "died", f'"AFT {y}"', ["born"]), line)
    print(f"{p.stem}: died AFT {y}")


def _refs(tree, f):
    out = []
    for r in f.refs[:2]:
        if r.source in tree.sources:
            out.append(f"[[{tree.sources[r.source].stem}]]" + (f", {r.locator}" if r.locator else ""))
    return "; ".join(out)


def genitive(name, sex):
    """«Ирина Прокопова» → «Ирины Прокоповой», «Иван Прокопов» → «Ивана Прокопова» — для подписи «отец …»; грубо, по окончаниям."""
    out = []
    for i, w in enumerate(name.split()):
        lw = w.lower()
        if sex == "F":
            if i > 0 and lw.endswith(("ова", "ева", "ина", "ёва")):
                w = w[:-1] + "ой"
            elif lw.endswith(("ия", "ья")):
                w = w[:-1] + "и"
            elif lw.endswith("а"):
                w = w[:-1] + ("и" if lw[-2:-1] in "гкхжшчщ" else "ы")
            elif lw.endswith("я"):
                w = w[:-1] + "и"
        else:
            if lw.endswith(("й", "ь")):
                w = w[:-1] + "я"
            elif lw.endswith("а"):
                w = w[:-1] + "ы"
            elif lw[-1:] not in "аеиоуыэюяо":
                w = w + "а"
        out.append(w)
    return " ".join(out)


def father_stem(dad, child):
    """«Прокоп (отец Ирины Прокоповой, Вербичи)» — уточнение из скобок карточки ребёнка, если есть."""
    m = re.search(r"\(([^()]*)\)\s*$", child.stem)
    where = m.group(1).split(",")[-1].strip() if m else ""
    where = where if where and not re.search(r"жена|муж|дочь|сын|отец|мать", where) else ""
    return f"{dad} (отец {genitive(child.name, child.sex)}{', ' + where if where else ''})"


def _write(p, fm_edit, fact=None):
    from paths import TREE
    path = TREE / "people" / f"{p.stem}.md"
    fm, rest = _split(path.read_text())
    fm = fm_edit(fm)
    if fact:
        rest = _add_fact(rest, fact)
    path.write_text(fm + rest)


def _new_id(tree):
    import random
    import string
    while True:
        a = "".join(random.choices(string.ascii_lowercase, k=3))
        b = "".join(random.choices(string.ascii_lowercase, k=3))
        cid = f"{a}-{random.randint(0, 999):03d}-{b}-{random.randint(0, 999):03d}"
        if cid not in tree.people:
            return cid


def main():
    import cards
    args = sys.argv[1:]
    quiet = "--quiet" in args
    tree = cards.load()
    plan = {}
    errors, hints = run(tree, plan)
    if "--surname-lines" in args:
        ready, doubt = surname_plan(tree)
        for p, line in ready:
            if "--apply" in args:
                put_fact(p, line)
            print(f"✓ {p.stem}: {line}")
        for p, why in doubt:
            print(f"? {p.stem}: {why}")
        print(f"Строки «Фамилия:»: готово {len(ready)}{' (внесено)' if '--apply' in args else ''}, спорных {len(doubt)}")
        return 0
    for cmd, key in (("--link-mother", "mother"), ("--add-father", "father"), ("--died-after", "died")):
        if cmd in args:
            i = args.index(cmd)
            p = tree.person(args[i + 1])
            if p is None:
                raise SystemExit(f"нет карточки «{args[i + 1]}»")
            if p.id not in plan[key]:
                raise SystemExit(f"для «{p.stem}» подсказки {cmd} нет — вносить нечего")
            if key == "mother":
                link_mother(tree, p, plan[key][p.id])
            elif key == "father":
                add_father(tree, p, plan[key][p.id])
            else:
                y, f = plan[key][p.id]
                if len(args) > i + 2 and args[i + 2].isdigit():
                    y = int(args[i + 2])
                died_after(tree, p, y, f)
            return 0
    if not quiet:
        for e in errors:
            print("✗", e)
        for h in hints:
            print("·", h)
    print(f"Логика семьи по датам: ошибок {len(errors)}, подсказок {len(hints)}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
