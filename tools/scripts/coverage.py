#!/usr/bin/env python3
"""Чем подтверждено каждое событие жизни наших предков — и где документа ещё нет.

Зачем. У человека три главных события — рождение, брак, смерть — и рождение каждого ребёнка. Про каждое мы знаем
откуда-то: из метрики, из анкеты, со слов бабушки, из чужого дерева. По карточке этого не видно сразу, а пропуски
(свадьба Прокопа — только со слов, смерть Анны — нигде) и есть то, что искать в архивах. Скрипт проходит по фактам
карточек, относит каждый к событию по словам («родился», «крещён», «венчан», «умер», «похоронен») и по году и
показывает у события лучшее подтверждение и число документов.

Подтверждение — лучшее из фактов о событии:
    📄 запись — метрика, акт ЗАГС, свидетельство о рождении / браке / смерти (запись, сделанная о самом событии)
    📃 документ — другая бумага, где событие названо: анкета, паспорт, справка, газета, перепись, военная база
    👪 семья — слова родных (разговоры, воспоминания, рукописи)
    🗂 старое дерево — первое семейное дерево на MyHeritage, без источника
    🧮 вывод — наш вывод: по отчеству, возрасту, годам
    🌐 интернет без документа — только общая папка «Интернет-находки»: подсказка, где искать, не бумага
    🌳 чужое дерево — подсказка, не доказательство
    ✖ — нигде; · — не нужно (человек, скорее всего, жив)
Число после знака — сколько разных документов (📄 + 📃) подтверждают событие.

Кто входит: прямые предки Павла и Вики, у каждого — его браки и рождения детей; дети и супруги вне прямой линии —
отдельной таблицей (рождение, брак, смерть).

    tools/py tools/scripts/coverage.py                     # сводка по поколениям + пропуски
    tools/py tools/scripts/coverage.py "Прокоп Ясенев"     # один человек: события и какие факты их подтверждают
    tools/py tools/scripts/coverage.py --line Ясеневы      # только ветка
    tools/py tools/scripts/coverage.py --write             # всё в 3_research/tree/_ДОКУМЕНТЫ_ПО_ЛЮДЯМ.md

Отнесение по словам — не идеально. Факт не попал в событие — проверить человека командой с именем: там видно, какие
строки карточки куда отнесены. Править — факты в карточках (подпись «Рождение», «Брак», «Смерть» решает спор).
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cards  # noqa: E402
import paths  # noqa: E402
from cards.kinship import ROOT  # noqa: E402
from cards.notes import as_list  # noqa: E402

OUT = paths.TREE / "_ДОКУМЕНТЫ_ПО_ЛЮДЯМ.md"
ORDER = ["record", "doc", "family", "tree", "inference", "web", "other_tree"]
MARK = {"record": "📄", "doc": "📃", "family": "👪", "tree": "🗂", "inference": "🧮", "web": "🌐", "other_tree": "🌳",
        None: "✖"}
NAME = {"record": "запись о событии", "doc": "другой документ", "family": "семья", "tree": "старое дерево",
        "inference": "вывод", "web": "интернет без документа", "other_tree": "чужое дерево", None: "нигде"}
ALIVE_FROM = 1930   # родился после и смерти нет — считаем живым, смерть не пропуск

# Какой источник — запись о событии, какой — слова родных
RECORD_TYPES = {"church_record", "vital_record"}
RECORD = re.compile(r"метрик|ЗАГС|Свидетельство о|выпись|Marriages|Death|Burials|регистрац", re.I)
NOT_RECORD = re.compile(r"Росписание|приходов", re.I)
TESTIMONY_TYPES = {"memoir", "manuscript", "photo"}
TESTIMONY = re.compile(r"Аудио|устно|Свидетельства семьи|Воспоминания|[Рр]укопис|Комментарии|Тетрадь|Записи о роде|"
                       r"Отчёт генеалога|Соцсети|фотоархив|опись, полистная|Домашний архив|Книга о роде|Реконструкция")
# Общая папка находок в сети: подсказка, где искать, — не бумага о событии
WEB = re.compile(r"^Интернет-находки")
DERIVED = re.compile(r"по отчеству|вывод|по годам|по возрасту|из возраста|вычисл|не позже|не раньше|вероятн|предполож|"
                     r"скорее всего|видимо|по деревне|расч\.",
                     re.I)

# Какое событие — по словам
BIRTH = re.compile(r"родил(?:ся|ась)|(?<!у)рожд|крещ|появил(?:ся|ась) на свет", re.I)
DEATH = re.compile(r"\bумер(?:ла)?\b|скончал|смерт|погреб|похорон|могил|погиб|убит|расстрел", re.I)
MARRIAGE = re.compile(r"\bбрак|венча|женил|замуж|свадьб|бракосочет|муж и жена", re.I)
KIN = r"(?:сын\w*|доч\w*|ребён\w*|дет\w*|внук\w*|внучк\w*|брат\w*|сестр\w*|племян\w*|отц\w*|отец|мат\w*|муж\w*|жен\w*)"
OTHER_BIRTH = re.compile(rf"рожд\w*\s+{KIN}|родил(?:ся|ась|и|а)\s+{KIN}|родила\b|у (?:них|него|неё) родил", re.I)
OTHER_DEATH = re.compile(rf"(?:смерт\w*|гибел\w*)\s+{KIN}|{KIN}\s+(?:умер|умерла|погиб)", re.I)
OTHER_MARRIAGE = re.compile(rf"{KIN}\s+(?:женил|вышла|выдал|венча)", re.I)
NO_EVENT = re.compile(r"^(?:родство|слияние|фамилия|имя|имена|отец|мать|родители|заметка|профиль|после|до\b|дет|брат|"
                      r"сестр|сын|доч|внук|крёстн|крестн|род\b)", re.I)
ABOUT_KIN = re.compile(r"^(?:отец|отца|мать|матери|сын|дочь|брат|сестра|жена|муж|дети)\b", re.I)   # «отец Антонины…», «сын Иван…» — о другом человеке
OTHER_ROLE = re.compile(r"поручител|восприемни|крёстн|крестн(?:ый|ая|ой|ым)|свидетел[ья]\b", re.I)   # на чужом событии
HEAD = 100   # слово события ищем в начале факта: дальше обычно уже о других
LABEL_EVENT = [("birth", re.compile(r"рожд|крещ", re.I)), ("death", re.compile(r"смерт|могил|похорон|погреб", re.I)),
               ("marriage", re.compile(r"брак|свадьб|венча", re.I))]
YEAR = re.compile(r"\b(1[5-9]\d\d|20[0-2]\d)\b")


# ─── что за источник ────────────────────────────────────────────────────────────────────────────────────────────────

def source_kind(src):
    if src.fm.get("our_tree") is True:
        return "tree"
    if src.provenance == "other_tree":
        return "other_tree"
    if src.provenance == "inference":
        return "inference"
    if WEB.search(src.stem):
        return "web"
    if (src.type in RECORD_TYPES or RECORD.search(src.stem)) and not NOT_RECORD.search(src.stem):
        return "record"
    if src.type in TESTIMONY_TYPES or TESTIMONY.search(src.stem):
        return "family"
    return "doc"


def fact_kind(tree, f):
    """Лучшее, чем держится факт. Вывод («по отчеству», «вероятно») — вывод, даже если источник — метрика."""
    if f.provenance == "inference" or DERIVED.search(f.label + " " + f.reasoning + " " + f.text[:HEAD]):
        return "inference"
    kinds = [source_kind(tree.sources[r.source]) for r in f.refs if r.source in tree.sources]
    if not kinds:
        return {"family": "family", "found": "doc", "other_tree": "other_tree"}.get(f.provenance, "inference")
    return min(kinds, key=ORDER.index)


def doc_refs(tree, f):
    """Документы факта: (источник, место в нём) — по ним считаем, сколько разных бумаг."""
    return {(r.source, r.locator.split(",")[0].strip()) for r in f.refs
            if r.source in tree.sources and source_kind(tree.sources[r.source]) in ("record", "doc")}


# ─── к какому событию факт ──────────────────────────────────────────────────────────────────────────────────────────

def fact_year(f):
    if f.date:
        return f.date.first_year
    m = YEAR.search(f.label) or YEAR.match(f.text[:6])
    return int(m[1]) if m else None


def near(year, gd, slack=1):
    """Год факта сходится с датой события (или чего-то не знаем — тогда не спорим)."""
    if year is None or gd is None:
        return True
    return gd.first_year - slack <= year <= gd.last_year + slack


def given(p):
    return (p.name or p.stem).split()[0].lower().replace("ё", "е")


def names(f, p):
    """Факт называет человека: ссылкой [[Имя карточки]] или именем."""
    low = f.text.lower().replace("ё", "е")
    return f"[[{p.stem}" in f.text or re.search(rf"\b{re.escape(given(p))}", low) is not None


def events_of(f):
    """События, о которых может говорить факт: по подписи — одно, иначе — по словам текста."""
    if NO_EVENT.search(f.label):
        return set()
    for ev, rx in LABEL_EVENT:
        if rx.search(f.label):
            return {ev}
    head = f.text[:HEAD]
    if ABOUT_KIN.search(f.text.lstrip(" *:—-")) or OTHER_ROLE.search(head):
        return set()
    out = set()
    if BIRTH.search(head) and not OTHER_BIRTH.search(head):
        out.add("birth")
    if DEATH.search(head) and not OTHER_DEATH.search(head):
        out.add("death")
    if MARRIAGE.search(head) and not OTHER_MARRIAGE.search(head) and not re.search("развод|расторг", head, re.I):
        out.add("marriage")
    return out


def child_birth_facts(tree, parent, child):
    """Факты в карточке родителя о рождении этого ребёнка: «родился сын [[Иван Ясенев (1878)|Иван]]»."""
    out = []
    for f in parent.facts:
        if NO_EVENT.search(f.label):
            continue
        if BIRTH.search(f.text[:HEAD]) and names(f, child) and near(fact_year(f), child.born):
            out.append((parent, f))
    return out


def classify(tree, p):
    """{событие: [(чья карточка, факт)]}; событие — 'birth', 'death', ('marriage', cr_id супруга)."""
    spouses = [tree.people[s] for s in p.spouses if s in tree.people]
    kids = [tree.people[c] for c in p.children if c in tree.people]
    out = {}
    for f in p.facts:
        y = fact_year(f)
        if any(names(f, k) for k in kids) and not events_of(f) & {"death"}:
            continue   # о ребёнке — идёт ему (child_birth_facts)
        for ev in events_of(f):
            if ev == "birth" and near(y, p.born):
                out.setdefault("birth", []).append((p, f))
            elif ev == "death" and near(y, p.died) and not (p.born and y and y < p.born.first_year + 1):
                out.setdefault("death", []).append((p, f))
            elif ev == "marriage" and spouses:
                if p.born and y and y < p.born.first_year + 14:
                    continue
                hit = [s for s in spouses if names(f, s)]
                if not hit and len(spouses) == 1 and (LABEL_EVENT[2][1].search(f.label) or MARRIAGE.search(f.text[:40])):
                    hit = spouses   # единственный супруг: факт без имени — только если брак назван сразу
                for s in hit:
                    out.setdefault(("marriage", s.id), []).append((p, f))
    return out


def marriage(tree, a, b, cls):
    """Брак — событие на двоих: факты из обеих карточек."""
    ev = list(cls(a).get(("marriage", b.id), []))
    if b.id in tree.people:
        ev += cls(b).get(("marriage", a.id), [])
    return ev


def summary(tree, ev):
    """(лучшее, число документов) по фактам события."""
    if not ev:
        return None, 0
    best = min((fact_kind(tree, f) for _, f in ev), key=ORDER.index)
    docs = set().union(*(doc_refs(tree, f) for _, f in ev if fact_kind(tree, f) in ("record", "doc")))
    return best, len(docs)


def cell(best, n, alive=False):
    if best is None and alive:
        return "·"
    return MARK[best] + (str(n) if n else "")


def alive(p):
    return p.died is None and p.born is not None and p.born.first_year >= ALIVE_FROM


# ─── кто входит ────────────────────────────────────────────────────────────────────────────────────────────────────

def ancestors(tree, roots):
    """{cr_id: поколение}: 0 — Павел и Вика, 1 — родители, 2 — деды…"""
    gen, todo = {}, [(0, r) for r in roots]
    while todo:
        g, p = todo.pop(0)
        if p.id in gen:
            continue
        gen[p.id] = g
        todo += [(g + 1, tree.people[i]) for i in p.father + p.mother if i in tree.people]
    return gen


GEN_RU = {0: "Павел и Вика", 1: "родители", 2: "деды и бабушки", 3: "прадеды", 4: "прапрадеды"}


def gen_ru(g):
    return GEN_RU.get(g, f"{g - 2}× прадеды")


def years(p):
    b = p.born.first_year if p.born else "?"
    d = p.died.first_year if p.died else ("" if alive(p) else "?")
    return f"{b}–{d}"


class Coverage:
    def __init__(self, tree):
        self.tree = tree
        self._cls = {}

    def cls(self, p):
        if p.id not in self._cls:
            self._cls[p.id] = classify(self.tree, p)
        return self._cls[p.id]

    def birth(self, p):
        ev = list(self.cls(p).get("birth", []))
        for pid in p.father + p.mother:
            if pid in self.tree.people:
                ev += child_birth_facts(self.tree, self.tree.people[pid], p)
        return ev

    def death(self, p):
        return self.cls(p).get("death", [])

    def marriages(self, p):
        return [(self.tree.people[s], marriage(self.tree, p, self.tree.people[s], self.cls))
                for s in p.spouses if s in self.tree.people]

    def row(self, p):
        t = self.tree
        b = summary(t, self.birth(p))
        d = summary(t, self.death(p))
        ms = [(s, summary(t, ev)) for s, ev in self.marriages(p)]
        kids = [t.people[c] for c in p.children if c in t.people]
        kb = [summary(t, self.birth(k)) for k in kids]
        return b, ms, d, kids, kb


# ─── вывод ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def kids_cell(kb):
    if not kb:
        return "—"
    n = {k: sum(1 for b, _ in kb if b == k) for k in ORDER + [None]}
    parts = [f"{MARK[k]}{n[k]}" for k in ORDER + [None] if n[k]]
    return " ".join(parts) + f" из {len(kb)}"


def marr_cell(ms):
    if not ms:
        return "—"
    return "; ".join(cell(*s) + (f" ({sp.stem.split(' (')[0]})" if len(ms) > 1 else "") for sp, s in ms)


def report(tree, cov, gen, line=None):
    def in_line(p):
        return not line or line in as_list(p.fm.get("lineage")) + as_list(p.fm.get("lineage_by_marriage"))

    anc = sorted((tree.people[i] for i in gen if in_line(tree.people[i])),
                 key=lambda p: (gen[p.id], p.born.first_year if p.born else 9999, p.stem))
    out, stats = [], {}
    gaps = {}   # ключ события → (поколение, строка, лучшее); брак — одно событие у обоих супругов
    kid_gaps = {}   # ребёнок вне прямой линии → [поколение родителей, ребёнок, [родители], лучшее]
    out += ["## Прямые предки", "",
            "| Пок. | Человек | Годы | Рождение | Брак | Смерть | Рождения детей |",
            "|---|---|---|---|---|---|---|"]

    def who(p):
        where = tree.places[p.birth_place].stem if p.birth_place in tree.places else ""
        return f"[[{p.stem}]] ({years(p)}{', ' + where if where else ''})"

    for p in anc:
        g = gen[p.id]
        b, ms, d, kids, kb = cov.row(p)
        out.append(f"| {g} | [[{p.stem}]] | {years(p)} | {cell(*b)} | {marr_cell(ms)} | {cell(*d, alive(p))} | "
                   f"{kids_cell(kb)} |")
        st = stats.setdefault(g, {"n": 0, "birth": {}, "marriage": {}, "death": {}, "kids": {}})
        st["n"] += 1
        events = [(("birth", p.id), f"{who(p)} — рождение", b[0])]
        st["birth"][p.id] = b[0]
        if not alive(p):
            st["death"][p.id] = d[0]
            events.append((("death", p.id), f"{who(p)} — смерть", d[0]))
        for sp, sm in ms:
            pair = frozenset((p.id, sp.id))
            st["marriage"][pair] = sm[0]
            events.append((("marriage", pair), f"[[{p.stem}]] и [[{sp.stem}]] — брак", sm[0]))
        for key, text, best in events:
            if best not in ("record", "doc"):
                gaps.setdefault(key, (g, text, best))
        for k, kx in zip(kids, kb):
            st["kids"][k.id] = kx[0]
            if k.id not in gen and kx[0] not in ("record", "doc"):
                kid_gaps.setdefault(k.id, [g, k, [], kx[0]])[2].append(p)

    head = ["## Сводка по поколениям", "",
            "Сколько событий подтверждено записью (📄) или другим документом (📃) — из всех известных. "
            "Брак пары и ребёнок считаются один раз.", "",
            "| Поколение | Людей | Рождение | Брак | Смерть | Рождения детей |", "|---|---|---|---|---|---|"]

    def frac(d):
        xs = list(d.values())
        if not xs:
            return "—"
        r = sum(1 for x in xs if x == "record")
        o = sum(1 for x in xs if x == "doc")
        return f"{r + o} из {len(xs)}" + (f" (📄{r} 📃{o})" if r + o else "")

    for g in sorted(stats):
        st = stats[g]
        head.append(f"| {g} — {gen_ru(g)} | {st['n']} | {frac(st['birth'])} | {frac(st['marriage'])} | "
                    f"{frac(st['death'])} | {frac(st['kids'])} |")

    side = sorted({c for i in gen for c in tree.people[i].children + tree.people[i].spouses
                   if c in tree.people and c not in gen and in_line(tree.people[c])},
                  key=lambda c: tree.people[c].stem)
    out += ["", "## Супруги и дети вне прямой линии", "",
            "| Человек | Годы | Рождение | Брак | Смерть |", "|---|---|---|---|---|"]
    for c in side:
        p = tree.people[c]
        b, ms, d, _, _ = cov.row(p)
        out.append(f"| [[{p.stem}]] | {years(p)} | {cell(*b)} | {marr_cell(ms)} | {cell(*d, alive(p))} |")

    gl = ["## Пропуски — события прямых предков без документа", "",
          "Событие было, а бумаги о нём нет. Сначала ближние поколения; брак пары — одной строкой. В скобках — чем "
          "держится сейчас. Под каждым поколением, свёрнуто, — рождения их детей вне прямой линии (братья и сёстры "
          "предков): метрика такого ребёнка тоже называет родителей.", ""]
    for g in sorted({x[0] for x in gaps.values()} | {x[0] for x in kid_gaps.values()}):
        own = sorted(f"{t} ({NAME[b]})" for gg, t, b in gaps.values() if gg == g)
        kid = sorted(f"[[{k.stem}]] ({years(k)}) — рождение; родители: "
                     + " и ".join(f"[[{x.stem}]]" for x in ps) + f" ({NAME[b]})"
                     for gg, k, ps, b in kid_gaps.values() if gg == g)
        gl += [f"**{g} — {gen_ru(g)}**", ""] + [f"- {t}" for t in own]
        if kid:
            gl += ["", f"<details><summary>рождения детей вне прямой линии — {len(kid)}</summary>", ""]
            gl += [f"- {t}" for t in kid] + ["", "</details>"]
        gl.append("")
    return head, out, gl


def detail(tree, cov, p):
    def show(title, ev, is_alive=False):
        best, n = summary(tree, ev)
        lines = [f"{title}: {cell(best, n, is_alive)} {NAME[best] if not (best is None and is_alive) else 'жив'}"]
        for owner, f in ev:
            lines.append(f"    {MARK[fact_kind(tree, f)]} {owner.stem}:{f.line} — {(f.label + ': ' if f.label else '')}"
                         f"{f.text[:110]}")
        return lines
    out = [f"{p.stem} ({years(p)})"]
    out += show("рождение", cov.birth(p))
    for s, ev in cov.marriages(p):
        out += show(f"брак с {s.stem}", ev)
    out += show("смерть", cov.death(p), alive(p))
    for c in p.children:
        if c in tree.people:
            k = tree.people[c]
            best, n = summary(tree, cov.birth(k))
            out.append(f"ребёнок {k.stem} ({years(k)}): {cell(best, n)} {NAME[best]}")
    return out


def find(tree, name):
    hits = [p for p in tree.people.values() if p.stem == name or p.id == name]
    hits = hits or [p for p in tree.people.values() if name.lower() in p.stem.lower()]
    if len(hits) != 1:
        sys.exit(f"«{name}»: найдено {len(hits)} — уточните (имя карточки или cr_id): "
                 + "; ".join(p.stem for p in hits[:8]))
    return hits[0]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("person", nargs="?")
    ap.add_argument("--line", help="только ветка (как в lineage: Ясеневы, Дубняки…)")
    ap.add_argument("--write", action="store_true", help=f"записать в {OUT.relative_to(paths.ROOT)}")
    a = ap.parse_args(argv)
    tree = cards.load()
    cov = Coverage(tree)
    if a.person:
        print("\n".join(detail(tree, cov, find(tree, a.person))))
        return 0
    pavel = next(p for p in tree.people.values() if p.fm.get("gedcom_id") == ROOT)
    roots = [pavel] + [tree.people[s] for s in pavel.spouses if s in tree.people]
    gen = ancestors(tree, roots)
    head, rows, gl = report(tree, cov, gen, a.line)
    intro = ["# Документы по людям — " + ("ветка " + a.line if a.line else "прямые предки Павла и Вики"), "",
             "Чем подтверждено каждое событие: 📄 запись о событии (метрика, акт ЗАГС, свидетельство) · 📃 другой "
             "документ (анкета, паспорт, справка, газета) · 👪 семья · 🗂 старое дерево · 🧮 вывод · 🌐 интернет без документа · "
             "🌳 чужое дерево · "
             "✖ нигде · · жив. Число — сколько разных документов. «📄2 из 5» у детей — у скольких детей рождение "
             "подтверждено так.", "",
             "Собрано скриптом `rodo coverage --write` из фактов карточек — руками не править: "
             "править факты. Один человек подробно — `coverage.py \"<имя>\"`.", ""]
    text = "\n".join(intro + head + [""] + gl + rows) + "\n"
    if a.write:
        OUT.write_text(text, encoding="utf-8")
        print("\n".join(head))
        print(f"записано: {OUT.relative_to(paths.ROOT)}; событий без документа: {sum(1 for x in gl if x.startswith('- '))}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
