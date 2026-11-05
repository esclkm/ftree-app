"""Нечёткое сравнение фильтра метрик (без сканов): написания, ошибки распознавания, ложные срабатывания.
Имена — вымышленные («Ивановский», «Курьянов»), чужих людей в тестах нет."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import metric_filter as mf  # noqa: E402

TARGETS = {
    "people": [{"label": "Пётр Курьянов", "given": "Пётр", "surname": "Курьянов"},
               {"label": "Анна Осокина", "given": "Анна", "surname": "Осокина"},
               {"label": "Иван Бор", "given": "Иван", "surname": "Бор"}],      # короткая основа — не ищем
    "villages": ["Вербичи", "Липовья"],
}


def hit(text, kind="surname"):
    return [h for h in mf.find_hits(text, TARGETS) if h["kind"] == kind]


class Spelling(unittest.TestCase):
    def test_old_orthography_and_endings(self):
        for written in ("Курьяновъ", "Курьянова", "Курьяновымъ", "КУРЬЯНОВ", "Куріяновъ"):
            self.assertTrue(hit(f"крестьянинъ Иванъ {written}"), written)

    def test_feminine_and_case_of_surname_target(self):
        # цель записана женской формой, в книге — мужская и падежи
        for written in ("Осокинъ", "Осокина", "Осокину", "Осокинымъ"):
            self.assertTrue(hit(f"{written} Андрей"), written)

    def test_recognition_errors(self):
        # типичные ошибки рукописного OCR: н→п, о→а, ь/ъ, лишняя буква
        for written in ("Курьяпов", "Курьянав", "Курьяновъ,", "Куриянов", "Курьянв"):
            self.assertTrue(hit(written), written)

    def test_word_split_across_lines(self):
        text = mf.join_lines(["крестьянинъ Курья-", "новъ Петръ"])
        self.assertIn("Курьяновъ", text.replace("Курьянов ъ", "Курьяновъ"))
        self.assertTrue(hit(text))
        self.assertTrue(hit("Курья новъ"))          # разрыв пробелом внутри слова

    def test_no_false_hits(self):
        for other in ("Лаврентьевъ", "Кирпичниковъ", "Никитинъ", "крестьянинъ Михаилъ Сухов", "Святославовъ"):
            self.assertFalse(hit(other), other)

    def test_short_surname_not_searched(self):
        self.assertFalse(hit("Иван Бородин Бор"))

    def test_similarity_confusable_letters_cost_less(self):
        self.assertGreater(mf.similarity("курьянов", "курьяпов"), mf.similarity("курьянов", "курьяхов"))
        self.assertEqual(mf.similarity("абв", "абв"), 1.0)
        self.assertEqual(mf.similarity("", "абв"), 0.0)


class Villages(unittest.TestCase):
    def test_village_forms(self):
        for written in ("Вербичи", "Вербичей", "Вербичахъ", "деревни Вербича", "Вирбичи"):
            self.assertTrue(hit(written, "village"), written)

    def test_volost_is_not_village(self):
        # «Козловской волости» — волость, а не деревня Козлово
        t = {"people": [], "villages": ["Козлово"]}
        self.assertEqual(mf.find_hits("Козловской волости деревни Гороховка", t), [])
        self.assertTrue(mf.find_hits("деревни Козлово крестьянинъ", t))


class Grading(unittest.TestCase):
    def test_grades(self):
        a = mf.grade(mf.find_hits("деревни Вербичи крестьянинъ Пётръ Курьяновъ", TARGETS))
        b = mf.grade(mf.find_hits("крестьянинъ Курьяновъ Андрей", TARGETS))
        c = mf.grade(mf.find_hits("деревни Вербичи крестьянинъ Иванъ Петровъ", TARGETS))
        none = mf.grade(mf.find_hits("деревни Гороховка крестьянинъ Иванъ Петровъ", TARGETS))
        self.assertEqual(a[0], "A")                 # фамилия + имя + деревня
        self.assertEqual(b[0], "C")                 # только фамилия (имя другое)
        self.assertEqual(c[0], "D")                 # только деревня
        self.assertEqual(none, ("", 0.0))
        self.assertGreater(a[1], c[1])

    def test_surname_with_given_name_beats_surname_alone(self):
        with_name = mf.grade(mf.find_hits("Пётръ Курьяновъ", TARGETS))
        alone = mf.grade(mf.find_hits("Андрей Курьяновъ", TARGETS))
        self.assertGreater(with_name[1], alone[1])


class TargetsParsing(unittest.TestCase):
    def test_parse_lines(self):
        lines = ["Лесогорск, 1906–1911: кандидатов 4 (место и всё внутри него: 1)",
                 "  Сергей Осокин (1894–1973) [P1]: метрика рождения 28.07.1894 · род. здесь",
                 "  Евстафий (жених, 1906) [—]: годы неизвестны — проверить · в фактах",
                 "  Ирина Осокина (жена Саввы) [~1893] [—]: метрика рождения расч. 1893",
                 "  Прокоп (Вербичи, 1907) [~1845–1907] [—]: смерть 22.04.1907"]
        got = mf.parse_target_lines(lines)
        self.assertEqual([p["surname"] for p in got], ["Осокин", None, "Осокина", None])
        self.assertEqual(got[0]["given"], "Сергей")
        # без фамилии — полное имя карточки, чтобы найти её ручные написания («Александр Липский»)
        self.assertEqual(got[1]["name"], "Евстафий (жених, 1906)")
        self.assertEqual(got[3]["name"], "Прокоп (Вербичи, 1907)")

    def test_book_years(self):
        self.assertEqual(mf.book_years({"title": "Лесогорск-Покровская церковь, МК 1906–1911"}), "1906-1911")
        self.assertEqual(mf.book_years({"title": "без годов"}), "1880-1917")


class Records(unittest.TestCase):
    def test_split_by_height_and_unread(self):
        data = {"section": "births", "starts": [100, 300, 500], "cells": {
            "parents": {"lines": [{"y": 110, "text": "Курьяновъ Петръ"}, {"y": 140, "text": "жена его"},
                                  {"y": 520, "text": "Иванъ"}], "error": None},
            "godparents": {"lines": [{"y": 305, "text": "Анна"}], "error": None}}}
        recs = {r["index"]: r for r in mf.split_records(data)}
        self.assertEqual(sorted(recs), [1, 2, 3])
        self.assertEqual(recs[1]["fields"]["parents"], "Курьяновъ Петръ жена его")
        self.assertEqual(recs[2]["fields"], {"godparents": "Анна"})
        self.assertEqual(mf.cells_unread("births", recs[1]), 1)       # крестные не прочитаны
        self.assertEqual(mf.cells_unread("births", recs[2]), 1)       # родители не прочитаны
        st = mf.spread_status(data | {"state": "ok"})
        self.assertEqual((st["records"], st["unread"]), (3, 0))

    def test_text_above_first_record_is_continuation(self):
        data = {"section": "deaths", "starts": [400], "cells": {
            "deceased": {"lines": [{"y": 50, "text": "хвост прошлой записи"}, {"y": 410, "text": "Прокоп"}], "error": None}}}
        recs = mf.split_records(data)
        self.assertEqual([r["index"] for r in recs], [0, 1])


class Layout(unittest.TestCase):
    def test_header_word_in_first_record_is_not_header(self):
        # шапка кончается на 220, линия под ней — 254; слово первой записи на 405 совпало со словами шапки
        self.assertEqual(mf.header_bottom_of([183, 221, 405], [2, 68, 129, 254, 1616], 1627), 254)

    def test_header_without_line_below(self):
        self.assertEqual(mf.header_bottom_of([200], [1600], 1600), 205)

    def test_weak_fit_only_when_asked(self):
        r = {"ok": False, "sides": {"left": 0.88, "right": 0.5}}
        self.assertFalse(mf.place_ok(r, weak=False))
        self.assertTrue(mf.place_ok(r, weak=True))
        self.assertFalse(mf.place_ok({"ok": False, "sides": {"left": 0.6, "right": 0.3}}, weak=True))
        self.assertTrue(mf.place_ok({"ok": False, "sides": {"left": 0.25, "right": 1.0}}, weak=True))   # бледная левая

    def test_section_from_neighbours(self):
        h = lambda s, n=80: {"section": s, "lines": n}
        heads = [h("births"), h("other"), h("births"), h("other"), h("deaths"), h("births", 10)]   # последняя — пустая
        self.assertEqual(mf.neighbour_sections(heads),
                         [("births",), ("births",), ("births", "deaths"), ("births", "deaths"), ("births",), ("deaths",)])


class SpreadCandidates(unittest.TestCase):
    DATA = {"cells": {
        "parents": {"lines": [{"y": 450, "text": "Козловской волости деревни Вербичи"},
                              {"y": 480, "text": "крестьянинъ Пётръ Курья-"},
                              {"y": 510, "text": "новъ и жена его"},
                              {"y": 900, "text": "деревни Вербичи крестьянинъ Ивана Сухова"},
                              {"y": 1300, "text": "деревни Гороховка"}]},
        "godparents": {"lines": [{"y": 1301, "text": "Анна Осокина"}]}}}

    def test_hyphen_glue_and_grouping(self):
        segs = mf.spread_segments(self.DATA)
        self.assertTrue(any("Курьяновъ" in t for _, _, t in segs))      # «Курья-» + «новъ» склеено
        cands = mf.spread_candidates(segs, TARGETS)
        grades = sorted((round(c["y0"]), c["grade"]) for c in cands)
        # у первой записи: фамилия + имя + деревня в одном окне; вторая — только деревня; третья — фамилия (+ имя Анна)
        self.assertEqual(grades[0][1], "A")
        self.assertEqual([g for y, g in grades if 800 < y < 1000], ["D"])
        self.assertEqual([g for y, g in grades if y > 1200], ["B"])
        self.assertEqual(len(cands), 3)

    def test_nothing_found_nothing_returned(self):
        data = {"cells": {"parents": {"lines": [{"y": 450, "text": "деревни Гороховка крестьянинъ Иванъ Петровъ"}]}}}
        self.assertEqual(mf.spread_candidates(mf.spread_segments(data), TARGETS), [])

    def test_act_number_is_nearest_above(self):
        lines = [{"y": 100, "text": "53"}, {"y": 420, "text": "54"}, {"y": 800, "text": "55"}]
        self.assertEqual(mf.act_number(lines, 520), "54")
        self.assertIsNone(mf.act_number(lines, 2000))

    def test_namesakes_are_one_search(self):
        t = {"people": [{"label": "Сергей Осокин", "given": "Сергей", "surname": "Осокин"},
                        {"label": "Анна Осокина", "given": "Анна", "surname": "Осокина"}], "villages": []}
        hits = mf.find_hits("Осокинъ Сергей", t)
        self.assertEqual(len(hits), 1)
        self.assertEqual(len(hits[0]["people"]), 2)
        self.assertTrue(hits[0]["given"])


class KnownWords(unittest.TestCase):
    def test_known_words_skip_service_words(self):
        rec = {"parents": "Козловской волости деревни Гороховка крестьянин Тарас Рогов и жена его [нрзб], оба православные"}
        words = mf.known_words(rec, "births")
        self.assertIn("Гороховка", words)
        self.assertIn("Рогов", words)
        self.assertNotIn("волости", words)
        self.assertNotIn("нрзб", [norm.lower() for norm in words])


class Clergy(unittest.TestCase):
    """Причт — только по уверенным совпадениям: слабое «Исповѣ…» на каждом развороте не делает фамилию причтом."""

    def test_weak_hits_do_not_make_clergy(self):
        weak = lambda n: {"n": n, "hits": [{"kind": "surname", "target": "Вахрушев", "sim": 0.66}]}
        cands = [weak(n) for n in range(10)] + [{"n": 10, "hits": [{"kind": "surname", "target": "Вахрушев", "sim": 1.0}]}]
        self.assertEqual(mf.common_surnames(cands, 11, 0.2), {})

    def test_strong_hits_everywhere_are_clergy(self):
        cands = [{"n": n, "hits": [{"kind": "surname", "target": "Кутузов", "sim": 0.9}]} for n in range(10)]
        self.assertEqual(mf.common_surnames(cands, 10, 0.2), {"Кутузов": 10})


if __name__ == "__main__":
    unittest.main()


class NameForms(unittest.TestCase):
    """Имя по святцам, «фамилия по отцу», сокращения писаря (name_forms + given_match)."""

    def test_church_forms(self):
        import name_forms as nf
        self.assertIn("иоанн", nf.forms("Иван"))
        self.assertIn("анастасия", nf.forms("Настасья"))
        self.assertIn("пелагия", nf.forms("Палагея"))          # два ряда с общим именем слиты
        self.assertEqual(nf.forms("Нестор"), ["нестор"])

    def test_patronymic(self):
        import name_forms as nf
        for father, want in (("Адриан", "адрианов"), ("Дорофей", "дорофеев"), ("Ипатий", "ипатиев"),
                             ("Гурай", "гураев"), ("Зосима", "зосимин"), ("Ермия", "ермьин")):
            self.assertEqual(nf.patronymic(father), want, father)
        self.assertIn("ипатьев", nf.patronymic_surnames("Ипатий"))
        self.assertIn("иоаннов", nf.patronymic_surnames("Иван"))

    def test_given_in_church_form_and_abbreviation(self):
        self.assertTrue(mf.given_match("Иван", "крестьянинъ Іоаннъ Петровъ"))
        self.assertTrue(mf.given_match("Настасья", "жена его Анаст. Ракитина"))
        self.assertFalse(mf.given_match("Настасья", "жена его Анисія"))
        self.assertFalse(mf.given_match("Иван", "дер. Ивановка"))


class Patronym(unittest.TestCase):
    """Крестьянин без фамилии: «Пётр Курьянов» = Пётр, сын Курьяна. Кандидат — только с именем прямо перед словом."""
    T = {"people": [{"label": "Пётр Ивановский", "given": "Пётр", "surname": "Курьянов", "patronym": True}],
         "villages": ["Липовья"]}

    def test_needs_given_before(self):
        segs = [(100.0, "parents", "дер. Липовьи крестьянинъ Петръ Курьяновъ и жена его")]
        self.assertTrue(any(c["grade"] == "A" for c in mf.spread_candidates(segs, self.T)))
        lone = [(100.0, "parents", "дер. Липовьи крестьянинъ Андрей Курьяновъ и жена его")]
        self.assertFalse(any(h["kind"] == "surname" for c in mf.spread_candidates(lone, self.T) for h in c["hits"]))


class Grades(unittest.TestCase):
    """B без имени — только при почти точной фамилии; D с именем человека из дерева — выше простого D."""

    def test_fuzzy_surname_with_village_is_c(self):
        loose = [{"kind": "surname", "target": "Курьянов", "sim": 0.7, "given": False},
                 {"kind": "village", "target": "Липовья", "sim": 1.0}]
        self.assertEqual(mf.grade(loose)[0], "C")
        exact = [{**loose[0], "sim": 1.0}, loose[1]]
        self.assertEqual(mf.grade(exact)[0], "B")

    def test_village_with_known_name(self):
        t = {"people": [{"label": "Пётр Курьянов", "given": "Пётр", "surname": "Курьянов", "id": "x-1"}],
             "villages": ["Липовья"]}
        segs = [(100.0, "deceased", "Козловской волости деревни Липовьи крестьянинъ Петръ Ксаровъ")]
        named = mf.spread_candidates(segs, t)       # фамилию машина не разобрала, имя — разобрала
        self.assertEqual([c["grade"] for c in named], ["D"])
        self.assertTrue(any(h["kind"] == "given" and h["ids"] == ["x-1"] for h in named[0]["hits"]))
        plain = mf.spread_candidates([(100.0, "deceased", "деревни Липовьи крестьянинъ Андрей")], t)
        self.assertEqual([c["grade"] for c in plain], ["D"])
        self.assertFalse(any(h["kind"] == "given" for c in plain for h in c["hits"]))
