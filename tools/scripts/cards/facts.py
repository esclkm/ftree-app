"""Раздел «### Факты (с источником)» карточки человека: одна строка — один факт.

  - **1944 (осень), 13 лет:** текст — *источник: [[Карточка источника]], 10:01; [[Другая]], стр. 3 · уверенность: низкая (вывод проекта: …)*

Подпись: дата, как в «Линии жизни» (dates.parse_ru), и через запятую остальное; или только слова («Занятие»).
Источник — ссылка на карточку источника, за ней через запятую — где в нём. Ссылка на файл ([[…jpg]]) — это «где»,
а не источник. Уверенность — одно из трёх слов, в скобках — на чём держится.
"""
import re

import dates
from .model import Fact, Problem, SourceRef
from .notes import link_target, section
from .sources import PROVENANCE

LINE = re.compile(r"^- \*\*(.+?):\*\* (.+) — \*источник: (.+?)\*\s*$")
FILE = r"\[\[[^\]]+\.(?:jpe?g|png|webp|pdf|m4a|mp3|opus)\]\]"
# «;» разделяет и источники («[[А]], стр. 1; [[Б]], 10:00»), и места в одном источнике («02:20; 24:56–25:30») —
# конец ссылки только там, где за «;» идёт следующая ссылка (или она сама — «(записано в [[Аудио 01]])»), или скобка закрылась
REF = re.compile(rf"\[\[([^\]]+?)\]\](?:,? ((?:[^·\[;]|;(?!\s*\[\[)|{FILE})+?))?\s*(?:·|;(?=\s*\[\[)|(?!{FILE})(?=\[\[)|(?=\))|$)")
CONFIDENCE = {"высокая": "high", "обычная": "normal", "средняя": "normal", "низкая": "low"}
TAIL = re.compile(r"уверенность: ([^()·]+?)\s*(?:\((.+?)\))?\s*(?:· происхождение: ([^·]+?))?\s*$")


def split_label(label):
    """«1944 (осень, поздняя), 13 лет» → («1944 (осень, поздняя)», «13 лет»): запятая вне скобок."""
    depth = 0
    for i, ch in enumerate(label):
        depth += (ch == "(") - (ch == ")")
        if depth == 0 and label.startswith(", ", i):
            return label[:i], label[i + 2:]
    return label, ""


def parse_label(label):
    """→ (дата или None, остаток подписи). Похоже на дату, но не по правилу — DateError."""
    head, rest = split_label(label)
    try:
        return dates.parse_ru(head), rest
    except dates.DateError:
        if re.match(r"[~≈]?\S*\d{4}", head):
            raise
        return None, label


def read_facts(note, card, source_by_name, sources, problems):
    text, start = section(note.body, "Факты (с источником)")
    facts = []
    if start < 0:
        if wrong := re.search(r"^#{1,2} Факты \(с источником\)", note.body, re.M):  # 02.10.2026: 7 карточек молча без фактов
            problems.append(Problem(card, note.line_of(wrong.start()),
                                    "заголовок «Факты (с источником)» — уровня ###, внутри «## Факты и заметки»: "
                                    "иначе факты не читаются", wrong[0]))
        return facts
    heads = list(re.finditer(r"^### Факты \(с источником\)", note.body, re.M))
    if len(heads) > 1:  # 01.11.2026: у одной карточки брак, смерть и дети стояли во втором разделе — сайт их не видел
        problems.append(Problem(card, note.line_of(heads[1].start()),
                                "второй раздел «Факты (с источником)» — читается только первый: строки перенести в него"))
    for m in re.finditer(r"^- .*$", text, re.M):
        raw, line_no = m[0], note.line_of(start + m.start())

        def bad(msg):
            problems.append(Problem(card, line_no, msg, raw))

        f = LINE.match(raw)
        if not f:
            bad("строка не по формату «- **что:** значение — *источник: [[…]] · уверенность: …*»")
            continue
        label, value, tail = f.groups()
        try:
            date, label = parse_label(label)
        except dates.DateError as e:
            bad(f"дата в подписи не по правилу: {e}")
            continue
        refs, first_prov = [], None
        for title, locator in REF.findall(tail.split("· уверенность:")[0]):
            if re.search(r"\.(jpe?g|png|webp|pdf|m4a|mp3|opus)$", title, re.I):
                continue
            sid = source_by_name.get(link_target(f"[[{title}]]"))
            if not sid:
                bad(f"[[{title}]] — нет такой карточки источника")
                continue
            refs.append(SourceRef(sid, (locator or "").strip()))
            first_prov = first_prov or sources[sid].provenance
        if not refs:
            if not any(p.line == line_no and p.card == card for p in problems):
                bad("источник — не ссылка на карточку источника")
            continue
        t = TAIL.search(tail)
        if not t or t[1].strip() not in CONFIDENCE:
            bad("уверенность — одно из слов: высокая, обычная, низкая")
            continue
        reasoning = (t[2] or "").strip()
        provenance = (PROVENANCE.get(t[3].strip()) if t[3] else None) \
            or ("inference" if "вывод проекта" in reasoning else first_prov)
        facts.append(Fact(line_no, value.strip(), refs, CONFIDENCE[t[1].strip()], provenance, date, label.strip(), reasoning))
    return facts
