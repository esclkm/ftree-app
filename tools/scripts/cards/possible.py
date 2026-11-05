"""Возможные связи — подозрения, ещё не доказанные, и проверенное «нет».

Зачем. По правилу «упоминание = карточка» в дерево приходят крёстные, соседи, однофамильцы из метрик. Родство с нашими
не доказано, но подозрение есть («Сергий 1894 из Вербичей — наш Сергей Ясенев?»). Чтобы оно не жило только текстом и не
всплывало снова, когда его уже отвергли, — четыре поля в карточке (номер — рядом с именем, как у father/father_id):

  maybe_same: "[[X]]"          + maybe_same_id: <cr_id>   — возможно, это одно лицо
  maybe_kin:  "[[X]] — брат?"  + maybe_kin_id:  <cr_id>   — возможно, родня; X приходится этой карточке братом
  not_same:   "[[X]]"          + not_same_id:   <cr_id>   — проверено: не одно лицо
  not_kin:    "[[X]]"          + not_kin_id:    <cr_id>   — проверено: не родня

Пишем в одну карточку — обратную сторону достраивает чтение (у X появится «возможно, сестра: эта карточка»).
На чём держится — строка в «Фактах» или «Открытых вопросах» той же карточки со ссылкой на X; у not_* — зачёркнутая (✅).
Это не связь: ветки (lineage) и дерево на сайте по этим полям не считаются.
"""
import re
from dataclasses import dataclass

from .model import Problem
from .notes import as_list, link_target, section

FIELDS = {"maybe_same": "same", "maybe_kin": "kin", "not_same": "same", "not_kin": "kin"}

# кем X приходится карточке: слово → (связь, пол того, кто ею приходится); пол на сайте берётся из карточки
ROLES = {"отец": ("parent", "M"), "мать": ("parent", "F"), "сын": ("child", "M"), "дочь": ("child", "F"),
         "брат": ("sibling", "M"), "сестра": ("sibling", "F"), "дядя": ("pibling", "M"), "тётя": ("pibling", "F"),
         "тетя": ("pibling", "F"), "племянник": ("nibling", "M"), "племянница": ("nibling", "F"),
         "двоюродный брат": ("cousin", "M"), "двоюродная сестра": ("cousin", "F"), "дед": ("grandparent", "M"),
         "бабушка": ("grandparent", "F"), "внук": ("grandchild", "M"), "внучка": ("grandchild", "F"),
         "муж": ("spouse", "M"), "жена": ("spouse", "F"), "родня": ("kin", None)}
INVERSE = {"parent": "child", "child": "parent", "sibling": "sibling", "pibling": "nibling", "nibling": "pibling",
           "cousin": "cousin", "grandparent": "grandchild", "grandchild": "grandparent", "spouse": "spouse", "kin": "kin"}


@dataclass
class Possible:
    kind: str           # same | kin
    person: str         # cr_id другого
    relation: str = ""  # у kin: parent | child | sibling | … | kin — кем другой приходится этому человеку
    reason: str = ""    # на чём держится: строка из карточки, где записано подозрение
    back: bool = False  # записано в карточке другого; здесь — обратная сторона


def role_of(value):
    """'[[X]] — брат?' → 'брат'; '[[X]]' → ''."""
    return re.sub(r"^\[\[[^\]]*\]\]", "", str(value)).strip(" —-–?").lower()


def reason_of(body, target, done=False):
    """Строка, где записано подозрение: в «Фактах» — то, что в скобках после уверенности (иначе вся строка), в «Открытых
    вопросах» — сама строка. done — нужна закрытая (✅): почему «нет»."""
    link = re.compile(r"\[\[" + re.escape(target) + r"(?=[\]|#])")
    facts = section(body, "Факты (с источником)")[0].splitlines()
    questions = section(body, "Открытые вопросы")[0].splitlines()
    for ln in ([] if done else facts) + questions:
        if not ln.startswith("- ") or not link.search(ln) or (("✅" in ln) != done):
            continue
        m = re.search(r"уверенность:[^(*]*\(([^)]+)\)", ln)
        if ln in facts:   # в «Фактах» — то, что в скобках после уверенности; нет скобок — сам факт без источника
            text = m.group(1) if m else re.sub(r"^- \*\*[^*]+:\*\*\s*|\s+—\s+\*источник:.*$", "", ln)
        else:
            text = ln[2:]
        return re.sub(r"~~|✅|\*\*", "", text).strip(" *")
    return ""


def read(people, stems, problems, card_of):
    """Поля maybe_*/not_* всех людей → people[id].possible и people[id].ruled_out (с обеих сторон)."""
    for p in people.values():
        p.possible, p.ruled_out = [], set()
    for p in people.values():
        for key, kind in FIELDS.items():
            ids = as_list(p.fm.get(f"{key}_id"))
            for i, v in enumerate(as_list(p.fm.get(key))):
                target = link_target(v)
                other = ids[i] if i < len(ids) and ids[i] in people else stems.get(target)
                if not other or other == p.id:
                    problems.append(Problem(card_of[p.id], 1, f"{key}: {v} — " +
                                            ("ссылка на себя" if other == p.id else "нет такой карточки")))
                    continue
                if key.startswith("not_"):
                    p.ruled_out.add((kind, other))
                    people[other].ruled_out.add((kind, p.id))
                    if not reason_of(p.body, target, done=True):
                        problems.append(Problem(card_of[p.id], 1, f"{key}: {v} — почему «нет», не записано: нужна "
                                                "зачёркнутая строка (✅) в «Открытых вопросах» со ссылкой на него",
                                                level="warning"))
                    continue
                relation = ""
                if kind == "kin":
                    word = role_of(v)
                    if word not in ROLES:
                        problems.append(Problem(card_of[p.id], 1, f"{key}: {v} — кем приходится, одним словом с «?»: "
                                                + ", ".join(w for w in ROLES if w != "тетя")))
                        continue
                    relation = ROLES[word][0]
                reason = reason_of(p.body, target)
                if not reason:
                    problems.append(Problem(card_of[p.id], 1, f"{key}: {v} — на чём держится, не записано: нужна строка "
                                            "в «Фактах» или «Открытых вопросах» со ссылкой на него", level="warning"))
                p.possible.append(Possible(kind, other, relation, reason))
                people[other].possible.append(Possible(kind, p.id, INVERSE.get(relation, ""), reason, back=True))
    for p in people.values():   # записано с обеих сторон — одна строка, своя важнее обратной
        best = {}
        for x in sorted(p.possible, key=lambda x: x.back):
            if (x.kind, x.person) not in p.ruled_out:
                best.setdefault((x.kind, x.person), x)
        p.possible = list(best.values())
