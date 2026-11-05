#!/usr/bin/env python3
"""Сводка «Поиск по архивам»: те же открытые задачи плана, но собранные по месту, где искать.

План поиска разложен по способу: сами в сети, платно, руками Павла, письма, вопросы родным
(ПОИСК_ОНЛАЙН.md и ПОИСК_ОФФЛАЙН.md). Из-за этого один архив оказывается в разных файлах: в Смоленский
архив мы и сами ходим на сайт, и пишем письма. Эта сводка кладёт рядом всё про одно место.

Задачи живут только в ПОИСК_ОНЛАЙН / ПОИСК_ОФФЛАЙН; сводку руками не правим — пересобирается этим скриптом
(и update_all.py). Место задачи угадывается по колонке «Где» правилами GROUPS (ftree.toml дерева или общие
из кода) сверху вниз; где правило ошибается — номер в PLACE_OF. Задача, которую не взяло ни одно правило,
попадает в «Не разложено» — тогда дописать правило.

  tools/py tools/scripts/search_by_place.py          # пересобрать <папка поиска>/ПОИСК_ПО_АРХИВАМ.md
  tools/py tools/scripts/search_by_place.py --stdout # показать, не записывая
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402
from check_search_plan import cells  # noqa: E402

OUT = paths.RESEARCH_BY_PLACE

# (ключ, заголовок, что это одной строкой, правило по колонке «Где»). Порядок важен: первое совпадение побеждает.
# Общие группы; дерево может дать свои — ftree.toml, [[search_by_place.group]] (key, title, what, rule).
_GROUPS = [
    ("gaso", "Смоленский областной архив (ГАСО)",
     "Метрики, ревизии, переписи и училищные дела Смоленщины.",
     r"ГАСО|Смоленск"),
    ("niab_grodno", "Исторический архив в Гродно (НИАБ Гродно)",
     "Метрики, ревизские сказки и дела Гродненской губернии до 1918 года.",
     r"НИАБ Гродно"),
    ("minsk", "Архивы Минска (НИАБ Минск, НАРБ, областной архив)",
     "Вторые экземпляры метрик, партийные и революционные дела, документы Минска.",
     r"НИАБ Минск|НАРБ|ГАМн|Минской обл|больница Минска"),
    ("zags", "ЗАГСы и сельсоветы",
     "Записи актов гражданского состояния и похозяйственные книги — после 1918 года.",
     r"ЗАГС|Сельисполком|похозяйств"),
    ("brest", "Архивы Брестской области (ГАБО)",
     "Документы польского времени 1921–1939: паспорта, купчие, гмины, староства.",
     r"ГАБО, Брест|ГАБО —|ГАБрО|Брестский областной"),
    ("russia", "Архивы России",
     "Петербург (РГИА), Москва и другие.",
     r"РГИА|ФСБ|Музей современной"),
    ("abroad", "Архивы Польши, Литвы и Германии",
     "Польские государственные архивы, Вильнюс (LVIA), Arolsen (лагеря и угон).",
     r"\bAP |AAN|MSWiA|LVIA|Arolsen"),
    ("usa", "США и Англия: архивы и газеты",
     "Газеты, списки пассажиров, натурализация и свидетельства о смерти эмигрантов.",
     r"newspapers\.com|Findmypast|Бюро ветеранов|USCIS"),
    ("library", "Библиотеки и газеты",
     "Национальная и Президентская библиотеки Беларуси, польские библиотеки: старые газеты, журналы, справочники.",
     r"elib\.nlb|НББ|Biblioteka|Księga Adresowa|библиотек"),
    ("bases", "Сайты-справочники: «Жниво», «Грыц», Radzima, базы репрессированных",
     "Указатели и распознанные тексты, где ищем по имени или деревне.",
     r"Жниво|Грыц|radzima|openlist|memo\.ru"),
    ("fs_dna", "FamilySearch и ДНК",
     "Общее дерево FamilySearch и совпадения по ДНК.",
     r"familysearch\.org|DNA|GEDmatch"),
    ("people", "Исследователи и Телеграм-группы",
     "Люди, которые уже держали в руках нужные книги или выписки.",
     r"Телеграм|t\.me"),
    ("social", "Родня за границей и соцсети",
     "Потомки за границей: письма, Facebook, Instagram, кладбища, суды.",
     r"Facebook|Instagram|[Сс]оцсети|кладбища"),
    ("family", "Спросить родных",
     "То, что есть только в памяти родных.",
     r"папа|мама|бабушка"),
]
GROUPS = [(g["key"], g["title"], g["what"], g["rule"]) for g in paths.tree_conf("search_by_place.group", [])] or _GROUPS

# Номер → ключ группы, где правило по «Где» промахивается (ftree.toml, [search_by_place.place_of]).
PLACE_OF = dict(paths.tree_conf("search_by_place.place_of", {}))

# Раздел исходного файла → как задача делается.
HOW = [("Сами", "🆓 сами"), ("Платно", "💰 платно"), ("руками Павла", "🖐 руками Павла"),
       ("Ждём", "⏳ ждём ответа"), ("Не в приоритете", "⬇️ не в приоритете"),
       ("Письма", "✉️ письмо"), ("Спросить", "👨 спросить")]
HOW_ORDER = [h for _, h in HOW]
TASK = re.compile(r"^\|\s*([ОПРНАС])(\d+)\s*\|")


def tasks():
    """Открытые задачи: (номер, как, файл, колонки)."""
    for path in (paths.RESEARCH_ONLINE, paths.RESEARCH_OFFLINE):
        how = "?"
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                how = next((h for k, h in HOW if k in line), "?")
            elif TASK.match(line):
                c = [x.strip().replace("¦", "|") for x in cells(line)]  # cells() прячет «|» ссылок — вернуть как в исходнике
                yield c[0], how, path.name, c


def place(num, where):
    if num in PLACE_OF:
        return PLACE_OF[num]
    return next((key for key, _, _, rule in GROUPS if re.search(rule, where)), None)


def build():
    by = {key: [] for key, *_ in GROUPS}
    by[None] = []
    for num, how, fname, c in tasks():
        by[place(num, c[3])].append((num, how, fname, c))
    order = lambda t: (HOW_ORDER.index(t[1]) if t[1] in HOW_ORDER else 99, t[0][0], int(t[0][1:]))
    total = sum(map(len, by.values()))

    out = ["# Поиск по архивам — где что искать", "",
           "**Что это.** Те же открытые задачи, что в `ПОИСК_ОНЛАЙН.md` и `ПОИСК_ОФФЛАЙН.md`, но собранные по месту:",
           "всё про один архив, библиотеку или человека — рядом, будь то поиск самим, платно, письмо или вопрос.",
           "Подробности задачи и следующий шаг — в её строке в исходном файле (ссылка на номере).", "",
           "**Руками не править** — сводка пересобирается: `rodo search-by-place` (и `rodo update-all`).",
           "Задача попала не туда — правило в этом скрипте (`GROUPS`, `PLACE_OF`).", "",
           f"Открытых задач: {total}.", "", "| Где | Задач |", "|---|---|"]
    names = [(key, title) for key, title, *_ in GROUPS] + ([(None, "Не разложено")] if by[None] else [])
    for key, title in names:
        if by[key]:
            out.append(f"| [[#{title}]] | {len(by[key])} |")
    for key, title in names:
        rows = sorted(by[key], key=order)
        if not rows:
            continue
        note = next((n for k, _, n, _ in GROUPS if k == key), "Правила скрипта не нашли место — дописать правило.")
        out += ["", f"## {title}", "", note, "", "| № | Как | Ветка | Что найти | Где |", "|---|---|---|---|---|"]
        for num, how, fname, c in rows:
            out.append(f"| [{num}]({fname}) | {how} | {c[1]} | {c[2]} | {c[3]} |")
    return "\n".join(out) + "\n", by[None]


def main():
    text, lost = build()
    if "--stdout" in sys.argv:
        print(text)
    else:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            OUT.write_text(text, encoding="utf-8")
            print(f"Сводка по архивам обновлена: {OUT.relative_to(paths.ROOT)}")
    if lost:
        print("Не разложено (дописать правило в search_by_place.py):", " ".join(n for n, *_ in lost))


if __name__ == "__main__":
    main()
