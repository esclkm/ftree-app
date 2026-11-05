"""Насколько доказано, что человек — наш: поле kinship карточки, а где его нет — оценка по фактам и связям.

Шкала (навык card-rules): proven доказано · likely вероятно · possible возможно · unlikely маловероятно · no не родня.
Оценку перекрывает поле kinship, которое ставит человек. Две группы людей:

1. Семья знает — доказано. Сомнение должно на чём-то держаться, родню оценка не занижает:
   - не дальше трёх шагов (родитель, ребёнок, супруг) от Павла — дочь, брат, жена брата и его дочь, дяди, тёти;
   - любой семейный факт (низкая уверенность там — про дату, не про родство);
   - источник — наше дерево (у карточки источника our_tree: true — сайт своего дерева на MyHeritage);
   - внесён в первой выгрузке семейного дерева (gedcom_id I500…, I900…) и держится не только на чужих деревьях.

2. Нашли сами — по метрикам, документам, чужим деревьям. Уверенно прочитанная метрика доказывает запись, а не то, что
   человек наш (трое братьев из одной метрики — так уже было). Поэтому:
   - строка факта «Родство» / «Родство с нашими» начинается словом шкалы — берём его («не установлено» — маловероятно,
     «не родственник» — не родня);
   - иначе — по связям: рядом (родитель, ребёнок, супруг) с тем, кого знает семья, — вероятно; ещё через одного —
     возможно; дальше — маловероятно. Прокоп — отец Ивана (Ивана знает семья) — вероятно; другие сыновья
     Прокопа — возможно; их жёны и дети — маловероятно;
   - и не выше, чем позволяют свои факты: всё найденное с низкой уверенностью, вывод проекта, чужое дерево — не выше
     «возможно»; только чужое дерево с низкой уверенностью — не выше «маловероятно»;
   - ни с кем не связан — по своим фактам, не выше «возможно».

«Unknown» (второй родитель без имени) — как у лучшего из его детей: он точно был, вопрос лишь в ребёнке.
"""
import re

import paths

from .people import KINSHIP

ORDER = ["proven", "likely", "possible", "unlikely", "no"]   # лучше → хуже
UNKNOWN = re.compile(r"Unknown\b")
ROOT = paths.tree_conf("kinship.root_gedcom_id", "")   # от кого считать шаги — gedcom_id в карточке (ftree.toml)
NEAR = 3           # шагов от Павла: дальше — уже не «знаем сами»

WORDS = {"доказано": "proven", "вероятно": "likely", "возможно": "possible", "маловероятно": "unlikely",
         "не родственник": "no", "не родственница": "no", "не родня": "no", "нет": "no", "не установлено": "unlikely"}
LABEL = re.compile(r"родство(?: с нашими)?$", re.I)


def _rank(level):
    return ORDER.index(level)


def _links(p):
    return p.father + p.mother + p.spouses + p.children


def _stated(p):
    """Уровень из строки факта «Родство …», если она начинается словом шкалы."""
    for f in p.facts:
        if LABEL.match(f.label.strip()):
            low = f.text.strip().lower()
            word = next((w for w in sorted(WORDS, key=len, reverse=True) if re.match(re.escape(w) + r"\b", low)), None)
            if word:
                return WORDS[word]
    return None


def _near(tree):
    """Кто не дальше NEAR шагов от Павла по связям родитель — ребёнок — супруг."""
    root = next((p.id for p in tree.people.values() if p.fm.get("gedcom_id") == ROOT), None)
    seen, edge = ({root}, [root]) if root else (set(), [])
    for _ in range(NEAR):
        edge = [n for i in edge for n in _links(tree.people[i]) if n in tree.people and n not in seen]
        seen.update(edge)
    return seen


def _family_knows(tree, p, near, our):
    if p.id in near or any(f.provenance == "family" for f in p.facts):
        return True
    if any(r.source in our for f in p.facts for r in f.refs) or any(s in our for s in p.sources):
        return True
    provs = {f.provenance for f in p.facts} | {tree.sources[s].provenance for s in p.sources if s in tree.sources}
    return bool(re.match(r"I[59]\d{5}$", str(p.fm.get("gedcom_id") or ""))) and provs != {"other_tree"}


def _cap(tree, p):
    """Выше чего не поднимут свои факты: найденное со средней/высокой уверенностью — вероятно, иначе — ниже."""
    pairs = [(f.provenance, f.confidence) for f in p.facts] \
        or [(tree.sources[s].provenance, "normal") for s in p.sources if s in tree.sources]
    if any(pr == "found" and c != "low" for pr, c in pairs) or not pairs:
        return "likely"
    if all(pr == "other_tree" and c == "low" for pr, c in pairs):
        return "unlikely"
    return "possible"


def levels(tree):
    """cr_id → (уровень, откуда: "card" — поле kinship, "facts" — оценка по фактам и связям)."""
    out, near = {}, _near(tree)
    our = {s.id for s in tree.sources.values() if s.fm.get("our_tree") is True}
    found = []   # нашли сами: уровень — по связям
    for p in tree.people.values():
        own = KINSHIP.get(str(p.fm.get("kinship") or "").strip())
        if own:
            out[p.id] = (own, "card")
        elif UNKNOWN.match(p.name):
            continue
        elif _family_knows(tree, p, near, our):
            out[p.id] = ("proven", "facts")
        elif _stated(p):
            out[p.id] = (_stated(p), "facts")
        else:
            found.append(p)
    # по связям: шаг от известного — ступень ниже; считаем, пока что-то меняется (цепочки предков по метрикам)
    dist, changed = {}, True
    while changed:
        changed = False
        for p in found:
            ranks = [_rank(out[n][0]) for n in _links(p) if n in out and out[n][0] != "no"] \
                + [dist[n] for n in _links(p) if n in dist]
            if ranks and min(3, min(ranks) + 1) < dist.get(p.id, 9):
                dist[p.id], changed = min(3, min(ranks) + 1), True
    for p in found:
        out[p.id] = (ORDER[max(dist.get(p.id, _rank("possible")), _rank(_cap(tree, p)))], "facts")
    for p in tree.people.values():   # безымянные — по детям
        if p.id not in out:
            kids = [out[c][0] for c in p.children if c in out]
            out[p.id] = (min(kids, key=_rank) if kids else "possible", "facts")
    return out
