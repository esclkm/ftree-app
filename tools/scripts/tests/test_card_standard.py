"""Тесты стандарта карточки: образец разделов (cards.layout) и правила card_standard.py — какой год считать тем же,
что в MyHeritage, и какой абзац заметок можно переписать строкой факта.
Запуск: python3 -m unittest discover tools/scripts/tests"""
import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import card_standard as C  # noqa: E402
import dates  # noqa: E402
from cards import layout  # noqa: E402
from cards.notes import Note  # noqa: E402

GOOD = """
# Research Notes

```charted-roots-media
columns: 3
```

## Факты и заметки

**Биография:** [[3_research/tree/biographies/Савва — биография.md]]

### Факты (с источником)

- **1902:** родился — *источник: [[Аудио 04]], 10:01 · уверенность: обычная*

### Открытые вопросы

- Точная дата смерти.

## Источники

- [[Аудио 04]] — 10:01 · уверенность: обычная · происхождение: семья
"""

MESSY = """
# Research Notes

**Упоминается в биографии:** [[3_research/tree/biographies/Отец — биография.md]]

## Факты и заметки

### Открытые вопросы

- Кто был первой женой?
- **1935:** родился сын Иван — *источник: [[Аудио 04]], 16:01 · уверенность: обычная*

### Расхождения

### Из досье поиска (июнь–сентябрь 2026)

- **Похоронен:** кладбище «Липки»

## Источники

- [[Аудио 04]] — 10:01 · уверенность: обычная · происхождение: семья

## Факты и заметки

### Факты (с источником)

- **1902:** родился — *источник: [[Аудио 04]], 10:01 · уверенность: обычная*
"""


def note(body):
    return Note(Path("Савва.md"), "Савва", {}, body, 1)


def words(body):
    return Counter(l.strip() for l in body.split("\n") if l.strip() and not l.startswith("#"))


class Layout(unittest.TestCase):
    def test_good_card(self):
        self.assertEqual(layout.check(note(GOOD), "Савва.md"), [])

    def test_messy_card_is_named(self):
        msgs = " | ".join(p.message for p in layout.check(note(MESSY), "Савва.md"))
        for part in ("текст до «## Факты и заметки»", "строка факта в «Открытые вопросы»", "«### Расхождения» пустой",
                     "«### Из досье поиска (июнь–сентябрь 2026)» — не из образца", "«## Факты и заметки» — второй раз"):
            self.assertIn(part, msgs)

    def test_fix_moves_but_keeps_words(self):
        fixed = layout.fix(MESSY)
        self.assertEqual(layout.check(note(fixed), "Савва.md"), [])
        self.assertEqual(words(fixed) - words(MESSY), Counter({"**Из досье поиска (июнь–сентябрь 2026):**": 1}))
        self.assertEqual(words(MESSY) - words(fixed), Counter())
        self.assertEqual(layout.fix(fixed), fixed)   # второй раз — без изменений
        heads = [l for l in fixed.split("\n") if l.startswith("#")]
        self.assertEqual(heads, ["# Research Notes", "## Факты и заметки", "### Факты (с источником)",
                                 "### Открытые вопросы", "### Заметки (из дерева MyHeritage и записей проекта)",
                                 "## Источники"])
        facts = fixed.split("### Факты (с источником)")[1].split("###")[0]
        self.assertIn("родился сын Иван", facts)
        self.assertLess(fixed.index("**Упоминается в биографии:**"), fixed.index("### Факты"))


class SameAsMyHeritage(unittest.TestCase):
    def same(self, card, site):
        return C.same_date(dates.parse_card(card), site)

    def test_same(self):
        self.assertTrue(self.same("1902", "1902"))
        self.assertTrue(self.same("1927-04-08", "1927"))          # MyHeritage менее точен
        self.assertTrue(self.same("1996-08-03", "AUG 1996"))
        self.assertTrue(self.same("2021", "TO 2021"))
        self.assertTrue(self.same("BET 2001 AND 2008", "2007"))
        self.assertTrue(self.same("1910-02-25", "12 FEB 1910"))   # старый и новый стиль

    def test_different(self):
        self.assertFalse(self.same("1919", "ABT 1917"))           # Александр Ясенев
        self.assertFalse(self.same("1948", "27 JUN 1934"))         # Виктор Дубняк
        self.assertFalse(self.same("1901-03-20", "21 FEB 1901"))
        self.assertFalse(self.same("1902", ""))

    def test_place(self):
        self.assertTrue(C.same_place("Lesogorsk, grodzienszczyzna, Białoruś", ["Лесогорск"]))
        self.assertTrue(C.same_place("Werbycze", ["Werbicze"]))
        self.assertTrue(C.same_place("United States", ["США"]))
        self.assertTrue(C.same_place("Беларусь", ["Беларусь"]))
        self.assertFalse(C.same_place("Лужки", ["Кленовка"]))


class ProjectYears(unittest.TestCase):
    def test_own_birth_and_death_only(self):
        self.assertEqual([y for y, _ in C.years_in("Умер в 1920 году в Лужках.", C.DEATH)], [1920])
        self.assertEqual(C.years_in("двое детей умерли при рождении в 1939", C.DEATH), [])
        self.assertEqual(C.years_in("1999 Умер сын [[Сергей]]", C.DEATH), [])


class NotesToFacts(unittest.TestCase):
    STEMS = ["Doc07 — Дубняк Мария — автобиография", "Воспоминания бабушки — Ольховская (Клёнова) Анна Прокоповна",
             "Реконструкция по отчеству (вывод, не документ)", "Свидетельства семьи (устно Павел, родители)", C.MH]

    # как текст называет источник — у каждого дерева свои (ftree.toml, [card_standard] sources); у образца их нет
    RULES = [[r"автобиограф\w*(?: Марии)", "Doc07 —"],
             [r"воспоминани\w* (?:бабушки|Ольховской)", "Воспоминания бабушки"],
             [r"(?i)от отца,? \d{4}-\d\d-\d\d|со слов отца", "Свидетельства семьи"],
             [r"^ИМЯ ВОССТАНОВЛЕНО ПО ОТЧЕСТВ", "Реконструкция по отчеству"]]

    def setUp(self):
        saved = C.SOURCES
        C.SOURCES = C._sources(self.RULES)
        self.addCleanup(setattr, C, "SOURCES", saved)

    def fact(self, text, mh_note=False, section_src=None):
        return C.as_fact(text.split("\n"), [], self.STEMS, mh_note, section_src)

    def test_source_named_in_text(self):
        line, _ = self.fact("Год смерти: 1919 (автобиография Марии).")
        self.assertEqual(line, "- **Заметка:** Год смерти: 1919 (автобиография Марии). — *источник: "
                               "[[Doc07 — Дубняк Мария — автобиография]] · уверенность: обычная*")

    def test_note_from_myheritage(self):
        line, _ = self.fact("служил полицаем в 1920", mh_note=True)
        self.assertEqual(line, f"- **Заметка:** служил полицаем в 1920 — *источник: [[{C.MH}]], заметка в дереве · "
                               "уверенность: низкая (заметка в дереве MyHeritage, не проверено)*")

    def test_label_and_date(self):
        self.assertTrue(self.fact("1929 - купили участок", mh_note=True)[0].startswith("- **1929:** купили участок"))
        line, _ = self.fact("- **🪦 Похоронен:** кладбище «Липки» (от отца, 2026-08-07)")
        self.assertTrue(line.startswith("- **Похоронен:** кладбище «Липки» (от отца, 2026-08-07) — *источник: "
                                        "[[Свидетельства семьи (устно Павел, родители)]] · уверенность: обычная*"), line)

    def test_reconstructed_name(self):
        line, _ = self.fact("ИМЯ ВОССТАНОВЛЕНО ПО ОТЧЕСТВУ СЫНА: Иван ВАСИЛЬЕВИЧ.")
        self.assertIn("[[Реконструкция по отчеству (вывод, не документ)]] · уверенность: низкая (вывод проекта)", line)

    def test_section_source(self):
        src = ("Воспоминания бабушки — Ольховская (Клёнова) Анна Прокоповна", "стр. 7")
        self.assertIn("стр. 7 · уверенность: обычная", self.fact("Была жива в 1941.", section_src=src)[0])

    def test_left_as_notes(self):
        for text, why in [("ЗАПРОС: метрики Вербичей", "задание"), ("Хозяйство было крепкое", "не назван"),
                          ("Со слов отца: в тайне от отца была оформлена дарственная", "конфликт"),
                          ("Похоронен (от отца, 2026-08-07) → запись в Бресте", "после «→»"),
                          ("Для Карты поляка нужна бабушка", "заявлени")]:
            line, reason = self.fact(text, mh_note=True if why == "не назван" else False)
            if why == "не назван":
                continue   # заметка MyHeritage — источник есть
            self.assertIsNone(line, text)
            self.assertIn(why, reason)
        self.assertIsNone(self.fact("Хозяйство было крепкое")[0])


if __name__ == "__main__":
    unittest.main()
