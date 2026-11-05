#!/usr/bin/env python3
"""Имя человека в карточке (поле `name`) — одно и то же устройство у всех.

Зачем. Поле `name` видит посетитель сайта: подпись в схеме дерева, заголовок профиля, поиск; из него же — имя и
фамилия на MyHeritage. Пояснение для различения тёзок («Иван Ясенев (1878)», «Агата Wierzbowska (жена
Витольда Ясенева)», «… (Вербичи, ≈1810)») живёт только в имени ФАЙЛА карточки, а в `name` — только само имя.

Стандарт (26.10.2026):
  • «Имя Фамилия», можно два имени («Анна Мария Ясенева», «Witold K. Jasieniew»); фамилия неизвестна — одно имя («Анна»),
    имя неизвестно — одна фамилия («Ясенев»); не знаем ничего — ровно «Unknown» (на сайте — «неизвестно»);
  • без скобок, цифр, «?», описаний («жена …», «из Лесогорска») — каждое слово с большой буквы;
  • без отчеств: отчество в карточку не вносим, форму из документа («Иван Прокопов Ясенев») — в `aliases`;
  • жена — под фамилией по мужу, девичья — полем `maiden_name` (навык card-rules); второе написание
    («Jan» и «Иван», «Ян») — в `aliases`;
  • одна азбука в имени и в фамилии; исключение — кириллическое имя с латинской фамилией рода («Агата Jasieniew»):
    так сайт пишет фамилию латиницей по-английски и по-польски. Наоборот («Anna Ясенева») — нельзя.

  ОШИБКА — нарушен стандарт. Код выхода 1, если есть ошибки.
  tools/py tools/scripts/check_names.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cards.tree import load  # noqa: E402

CYR, LAT = re.compile("[А-Яа-яЁёІіЎў]"), re.compile("[A-Za-zÀ-žŁłŚśŻżŹźĆćŃńĘęĄąÓó]")
PARTICLES = {"de", "del", "della", "da", "dos", "van", "von", "der", "la", "le", "y", "di"}
PATRONYMIC_MID = re.compile(r"(ович|евич|овна|евна|ична|инична|ovich|evich|ovna|evna|ichna|ovych)$", re.I)
PATRONYMIC_END = re.compile(r"(овна|евна|ична|ovna|evna)$", re.I)


def problems(name):
    n = str(name or "")
    if n == "Unknown":
        return []
    out = []
    if n != n.strip() or "  " in n or not n:
        out.append("лишние пробелы или пусто")
    if re.search(r"[()\[\]]", n):
        out.append("скобки — пояснение для тёзок только в имени файла, второе написание — в aliases")
    if re.search(r"\d", n):
        out.append("цифры в имени")
    if re.search(r"[?«»\"/,;]", n):
        out.append("знаки «?», кавычки, запятые — сомнение пишется в факте, не в имени")
    if n.startswith("Unknown"):
        out.append("неизвестный — ровно «Unknown», без номера")
    words = n.split()
    low = [w for w in words if w[:1].islower() and w not in PARTICLES]
    if low:
        out.append(f"слова с маленькой буквы ({' '.join(low)}) — описание, а не имя")
    if any(PATRONYMIC_MID.search(w.rstrip(".")) for w in words[1:-1]) or (
            len(words) == 2 and PATRONYMIC_END.search(words[1])):
        out.append("отчество — в карточку не вносим (форму документа — в aliases)")
    if len(words) >= 2 and CYR.search(n) and LAT.search(n):
        first, last = " ".join(words[:-1]), words[-1]
        if not (CYR.search(first) and not LAT.search(first) and LAT.search(last) and not CYR.search(last)):
            out.append("азбуки перемешаны — можно только «кириллическое имя + латинская фамилия»")
    return out


def main():
    tree = load()
    errors = 0
    for p in sorted(tree.people.values(), key=lambda p: p.stem):
        for msg in problems(p.name):
            errors += 1
            print(f"ОШИБКА  {p.stem}: name «{p.name}» — {msg}")
    print(f"Имена в карточках: людей {len(tree.people)}, ошибок {errors}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
