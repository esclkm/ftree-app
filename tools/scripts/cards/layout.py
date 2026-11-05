"""Карточка человека по образцу: какие разделы, в каком порядке, что где лежит.

Образец — 3_research/templates/Карточка человека — устройство.md. После блока свойств и служебных блоков Charted Roots
(«# Research Notes», ```charted-roots-…```) — только эти разделы, в этом порядке; каждый — если в нём что-то есть:

  ## Факты и заметки
     **Биография:** [[…]] · **Упоминается в биографии:** [[…]]      ← только эти строки до первого ###
     ### Факты (с источником)        ← строки «- **что:** значение — *источник: [[…]] · уверенность: …*», и только здесь
     ### Контакты (не публикуются)   ← телефоны, почта, профили в соцсетях, адреса живых — теми же строками; сайт их не
                                       показывает никогда (решено 05.10.2026; выгрузка сайта его не берёт, facts.py его не читает)
     ### Слова дословно
     ### Расхождения
     ### Открытые вопросы
     ### Заметки (из дерева MyHeritage и записей проекта)   ← свободный текст, как был
  ## Рассказ                         ← собирает texts_section.py
  ## Тексты: статьи, автобиографии, воспоминания   ← собирает texts_section.py
  ## Источники                       ← «- [[Источник]] — где · уверенность: … · происхождение: …»

check(note) называет каждое отступление; fix(body) делает механическое: пустой раздел — убрать, разделы — по порядку,
два одинаковых — слить, строку факта из чужого раздела — в «Факты», свободный текст не на месте (до «Фактов и заметок»,
в разделе не из образца) — в «Заметки» с подписью, откуда он. Слова не меняются — меняется только место.
"""
import re

from .model import Problem

FACTS = "Факты (с источником)"
CONTACTS = "Контакты (не публикуются)"
# контакт — телефон с кодом страны, почта, профиль в соцсети (те же правила, что site_data/privacy.py: PHONE, EMAIL, SOCIAL)
CONTACT = re.compile(r"\+\d{2,3}[ ()\d-]{7,}\d|[\w.%+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}"
                     r"|(?<![\w.@-])(?:https?://)?(?:[\w-]+\.)?(?:facebook|instagram|linkedin|twitter|x|tiktok|vk|ok)\.(?:com|ru)/", re.I)
NOTES = "Заметки (из дерева MyHeritage и записей проекта)"
H2 = ["Факты и заметки", "Рассказ", "Тексты: статьи, автобиографии, воспоминания", "Источники"]
H3 = [FACTS, CONTACTS, "Слова дословно", "Расхождения", "Открытые вопросы", NOTES]
FACT_LINE = re.compile(r"^- \*\*(.+?):\*\* (.+) — \*источник: (.+?)\*\s*$")
BIO_LINE = re.compile(r"^\*\*(Биография|Упоминается в биографии):\*\*")
HEAD = re.compile(r"^(#{1,6}) (.+?)\s*$")
FIX = "tools/scripts/check_cards.py --fix"


class Part:
    """Раздел: заголовок (строка файла) и строки до следующего заголовка; у «##» — ещё подразделы «###»."""

    def __init__(self, title, head, start):
        self.title, self.head, self.start = title, head, start
        self.lines, self.subs = [], []

    def text(self):
        return [l for l in self.lines if l.strip() and not re.fullmatch(r"\s*<!--.*?-->\s*", l)]

    def empty(self):
        return not self.text() and all(s.empty() for s in self.subs)


def parse(body):
    """→ (строки до первого «##», [разделы «##»]). Заголовки внутри ``` … ``` не считаются."""
    pre, h2, fence = [], [], False
    for i, line in enumerate(body.split("\n")):
        if line.startswith("```"):
            fence = not fence
        m = None if fence else HEAD.match(line)
        if m and len(m[1]) == 2:
            h2.append(Part(m[2], line, i))
            continue
        if m and len(m[1]) == 3 and h2:
            h2[-1].subs.append(Part(m[2], line, i))
            continue
        target = (h2[-1].subs[-1] if h2[-1].subs else h2[-1]).lines if h2 else pre
        target.append(line)
    return pre, h2


def _is_service(lines):
    """Строки до «## Факты и заметки», которые на месте: пусто, «# Research Notes», блоки ```charted-roots-…```."""
    out, fence = [], False
    for l in lines:
        if l.startswith("```"):
            fence = not fence
            out.append(True)
            continue
        out.append(fence or not l.strip() or l.strip() == "# Research Notes" or bool(re.fullmatch(r"\s*<!--.*?-->\s*", l)))
    return out


def check(note, card):
    """Отступления от образца → [Problem]."""
    pre, h2 = parse(note.body)
    probs = []

    def bad(i, msg, text=""):
        probs.append(Problem(card, note.body_line + i if i is not None else None, msg + f" — {FIX}", text))

    def line_no(part, k):
        return part.start + 1 + k

    stray = [l for l, ok in zip(pre, _is_service(pre)) if not ok]
    if stray:
        bad(next(i for i, (l, ok) in enumerate(zip(pre, _is_service(pre))) if not ok),
            "текст до «## Факты и заметки» — ему место в «Заметках» (или строка «Упоминается в биографии» — в начале "
            "«Фактов и заметок»)", stray[0])
    seen2 = []
    for s in h2:
        if s.title not in H2:
            bad(s.start, f"раздел «## {s.title}» — не из образца")
        elif s.title in seen2:
            bad(s.start, f"раздел «## {s.title}» — второй раз")
        elif seen2 and any(H2.index(s.title) < H2.index(t) for t in seen2 if t in H2):
            bad(s.start, f"раздел «## {s.title}» не на своём месте: порядок — {' → '.join(H2)}")
        seen2.append(s.title)
        if s.empty() and s.title in H2:
            bad(s.start, f"раздел «## {s.title}» пустой")
        if s.title == "Факты и заметки":
            for k, l in enumerate(s.lines):
                if l.strip() and not BIO_LINE.match(l) and not re.fullmatch(r"\s*<!--.*?-->\s*", l):
                    bad(line_no(s, k), "в начале «Фактов и заметок» — только строки «**Биография:**» и «**Упоминается в "
                                       "биографии:**»; текст — в «Заметки», факт — в «Факты»", l)
                    break
            seen3 = []
            for sub in s.subs:
                if sub.title not in H3:
                    bad(sub.start, f"раздел «### {sub.title}» — не из образца: {', '.join(H3)}")
                elif sub.title in seen3:
                    bad(sub.start, f"раздел «### {sub.title}» — второй раз")
                elif any(H3.index(sub.title) < H3.index(t) for t in seen3 if t in H3):
                    bad(sub.start, f"раздел «### {sub.title}» не на своём месте: порядок — {' → '.join(H3)}")
                seen3.append(sub.title)
                if sub.empty() and sub.title in H3:
                    bad(sub.start, f"раздел «### {sub.title}» пустой")
                if sub.title == FACTS:
                    for k, l in enumerate(sub.lines):
                        if FACT_LINE.match(l) and CONTACT.search(l):
                            bad(line_no(sub, k), f"контакт в «Фактах» — ему место в «{CONTACTS}»", l)
                            break
                    for k, l in enumerate(sub.lines):
                        if l.strip() and not l.startswith("- ") and not re.fullmatch(r"\s*<!--.*?-->\s*", l):
                            bad(line_no(sub, k), "в «Фактах» — текст не строкой факта: факт — «- **что:** …», "
                                                 "остальное — в «Заметки»", l)
                            break
                elif sub.title in H3 and sub.title != CONTACTS:
                    for k, l in enumerate(sub.lines):
                        if FACT_LINE.match(l):
                            bad(line_no(sub, k), f"строка факта в «{sub.title}» — ей место в «Фактах»", l)
                            break
        elif s.subs and s.title in H2:
            bad(s.subs[0].start, f"подраздел «### {s.subs[0].title}» внутри «## {s.title}» — подразделы бывают только "
                                 "в «Фактах и заметках»")
        if s.title == "Источники":
            for k, l in enumerate(s.lines):
                if l.strip() and not l.startswith("- [[") and not re.fullmatch(r"\s*<!--.*?-->\s*", l):
                    bad(line_no(s, k), "в «Источниках» — только строки «- [[Источник]] — …»", l)
                    break
    return probs


def _trim(lines):
    while lines and not lines[0].strip():
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines = lines[:-1]
    return lines


def fix(body):
    """Тело карточки по образцу (что не механическое — не трогает: слова и строки те же)."""
    pre, h2 = parse(body)
    keep = [l for l, ok in zip(pre, _is_service(pre)) if ok]
    stray = [l for l, ok in zip(pre, _is_service(pre)) if not ok]
    bio = [l for l in stray if BIO_LINE.match(l)]
    told = [l for l in stray if l.startswith(">")]   # свёрнутая биография не на месте — в «Рассказ»
    stray = [l for l in stray if not BIO_LINE.match(l) and not l.startswith(">")]

    head = {t: [] for t in H2}       # строки сразу под «##»
    subs = {t: [] for t in H3}       # строки подразделов «Фактов и заметок»
    head["Факты и заметки"] += bio
    head["Рассказ"] += told
    moved = []                       # (откуда, строки) — в «Заметки» с подписью
    chunk = ("", [])                 # «### …» до первого «##» — в свой подраздел, если он из образца
    for l in stray:
        m = HEAD.match(l)
        if m and len(m[1]) == 3:
            moved.append(chunk)
            chunk = (m[2], [])
            continue
        (subs[chunk[0]] if chunk[0] in H3 else chunk[1]).append(l)
    moved.append(chunk)
    for s in h2:
        if s.title not in H2:
            moved.append((s.title, s.lines + [x for sub in s.subs for x in [sub.head] + sub.lines]))
            continue
        if s.title == "Факты и заметки":
            for l in s.lines:
                (head[s.title] if BIO_LINE.match(l) or not l.strip() or l.strip().startswith("<!--") else
                 subs[FACTS] if FACT_LINE.match(l) else subs[NOTES]).append(l)
            for sub in s.subs:
                if sub.title not in H3:
                    moved.append((sub.title, sub.lines))
                    continue
                for l in sub.lines:
                    if sub.title not in (FACTS, CONTACTS) and FACT_LINE.match(l):
                        subs[FACTS].append(l)
                    elif sub.title == FACTS and l.strip() and not l.startswith("- ") and not l.strip().startswith("<!--"):
                        subs[NOTES].append(l)
                    else:
                        subs[sub.title].append(l)
                subs[sub.title].append("")
        else:
            head[s.title] += s.lines + [x for sub in s.subs for x in [sub.head] + sub.lines] + [""]
    for title, lines in moved:
        if title in H3:
            continue
        lines = _trim(lines)
        if any(l.strip() for l in lines):
            facts = [l for l in lines if FACT_LINE.match(l)]
            subs[FACTS] += [""] + facts
            rest = [l for l in lines if not FACT_LINE.match(l)]
            if any(l.strip() and not re.fullmatch(r"\s*<!--.*?-->\s*", l) for l in rest):
                subs[NOTES] += [""] + ([f"**{title}:**", ""] if title else []) + _trim(rest)

    # телефоны, почта, профили в соцсетях — в «Контакты»: сайт их не показывает
    contact = [l for l in subs[FACTS] if FACT_LINE.match(l) and CONTACT.search(l)]
    if contact:
        subs[FACTS] = [l for l in subs[FACTS] if l not in contact]
        subs[CONTACTS] = _trim(subs[CONTACTS]) + contact + [""]

    # подпись «**Из досье поиска …:**», под которой — одна служебная пометка (текст стал фактами), — не нужна
    notes = subs[NOTES]
    for k in range(len(notes) - 1, -1, -1):
        if re.fullmatch(r"\*\*[^*]+:\*\*", notes[k].strip()):
            nxt = next((x for x in notes[k + 1:] if x.strip() and not re.fullmatch(r"\s*<!--.*?-->\s*", x)), None)
            if nxt is None or re.fullmatch(r"\*\*[^*]+:\*\*", nxt.strip()):
                del notes[k]
    out = _trim(keep)
    def block(level, title, lines):
        lines = [l for l in _trim(lines)]
        # подряд идущие пустые строки — одной
        lines = [l for k, l in enumerate(lines) if l.strip() or (k and lines[k - 1].strip())]
        return [f"{level} {title}", ""] + lines + [""] if any(l.strip() and not l.strip().startswith("<!--")
                                                             for l in lines) else []
    out = out + [""] if out else []
    fz = [l for l in _trim(head["Факты и заметки"]) if l.strip()]
    inner = [x for t in H3 for x in block("###", t, subs[t])]
    if fz or inner:
        out += ["## Факты и заметки", ""] + (fz + [""] if fz else []) + inner
    for t in H2[1:]:
        out += block("##", t, head[t])
    return "\n".join(_trim(out)) + "\n"
