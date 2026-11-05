"""Тесты сравнения карточек со снимком сайта MyHeritage (myheritage_plan.py): разбор дат сайта, коды формы,
«то же имя». Сети нет, карточки не читаются. Запуск: python3 -m unittest discover tools/scripts/tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dates  # noqa: E402
import myheritage_plan as P  # noqa: E402


class SiteDate(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(P.site_date("12 cze 1937", "1937"), ("", 1937, None))
        self.assertEqual(P.site_date("Około 1917", "1917"), ("ABT", 1917, None))
        self.assertEqual(P.site_date("Przed 2002", "2002"), ("BEF", 2002, None))
        self.assertEqual(P.site_date("Po 1986", "1986"), ("AFT", 1986, None))
        self.assertEqual(P.site_date("Pomiędzy 2009 i 2011", "2009"), ("BET", 2009, 2011))

    def test_empty_and_unclear(self):
        self.assertEqual(P.site_date("", ""), (None, None, None))
        self.assertEqual(P.site_date("1935?", "1935")[0], "?")   # неуверенное написание — не разбираем, отдаём человеку


class ToForm(unittest.TestCase):
    """Коды проверены записью на сайт и чтением 02.10.2026."""
    def test_codes(self):
        f = lambda s: P.to_form(dates.parse_card(s))
        self.assertEqual((f("1971-03-05")["type"], f("1971-03-05")["op1"], f("1971-03-05")["d1"]), (1, 1, 5))
        self.assertEqual((f("ABT 1917")["type"], f("ABT 1917")["op1"]), (4, 4))
        self.assertEqual((f("BEF 2002")["type"], f("BEF 2002")["op1"]), (2, 2))
        self.assertEqual((f("AFT 1986")["type"], f("AFT 1986")["op1"]), (3, 3))
        b = f("BET 2009 AND 2011")
        self.assertEqual((b["type"], b["op1"], b["op2"], b["y1"], b["y2"]), (7, 1, 1, 2009, 2011))

    def test_from_to_not_uploaded(self):
        self.assertIsNone(P.to_form(dates.parse_card("FROM 1941 TO 1945")))


class DateWork(unittest.TestCase):
    def go(self, card, site_text, site_year, living=False):
        return P.date_work("рождение", "birthDate", dates.parse_card(card) if card else None, site_text, site_year, living)

    def test_add_when_site_empty(self):
        d, _, why = self.go("1877", "", "")
        self.assertIn("birthDate", d)
        self.assertIn("добавить", why)

    def test_same_year_not_touched(self):
        self.assertEqual(self.go("1927-04-08", "1927", "1927")[0], None)     # сайт точнее или равен — не трогаем
        self.assertEqual(self.go("1917", "Około 1917", "1917")[0], None)

    def test_other_year_replaces_and_is_marked(self):
        d, _, why = self.go("1948", "27 cze 1934", "1934")
        self.assertIn("birthDate", d)
        self.assertIn("→", why)                                              # «→» — признак замены: в списке не отмечена

    def test_never_erases(self):
        d, from_site, _ = self.go(None, "1935", "1935")
        self.assertIsNone(d)
        self.assertIn("в карточке даты нет", from_site)

    def test_living_dates_skipped(self):
        self.assertEqual(self.go("1971-03-05", "", "", living=True), (None, None, None))


class SameName(unittest.TestCase):
    site = lambda self, f, l: {"firstName": f, "lastName": l}

    def test_exact_and_yo(self):
        self.assertTrue(P.same_name(("Пётр", "Ясенев"), self.site("Петр", "Ясенев")))

    def test_site_more_detailed(self):
        self.assertTrue(P.same_name(("Helena", "Brzozowski"), self.site("Helena (Елена)", "Brzozowski (Бжозовский)")))
        self.assertTrue(P.same_name(("Anna", "Uss"), self.site("Anna", "Uss (Lipska)")))

    def test_site_missing_surname(self):
        self.assertFalse(P.same_name(("Anna", "Jasieniew"), self.site("Anna", "")))

    def test_family_name_only_card(self):
        self.assertTrue(P.same_name(("Brzozowski", ""), self.site("", "Brzozowski")))

    def test_name_change_risk(self):
        s = self.site("Иван", "Кленюк")
        self.assertTrue(P.name_change(("Антон", "Кленюк"), s)[1])          # другое имя — рискованно
        self.assertFalse(P.name_change(("Иван", "Кленюк-Ясенев"), s)[1])   # достраиваем — нет



class MarriedName(unittest.TestCase):
    """Фамилия жены после замужества: без неё сайт сам ставит фамилию мужа как есть — «Елена Осокина (Липский)»."""
    def person(self, name, spouses=(), sex="F", maiden=""):
        from types import SimpleNamespace as N
        return N(name=name, sex=sex, spouses=list(spouses), fm={"maiden_name": maiden})

    def tree(self, **people):
        from types import SimpleNamespace as N
        return N(people=people)

    def test_feminine(self):
        self.assertEqual([P.feminine(x) for x in ("Липский", "Ясенев", "Ракитин", "Толстой", "Клёнич", "Мелкша", "Jasieniew")],
                         ["Липская", "Ясенева", "Ракитина", "Толстая", "Клёнич", "Мелкша", "Jasieniew"])

    def test_site_married(self):
        self.assertEqual(P.site_married({"name": "Елена Осокина (Липский)", "firstName": "Елена", "lastName": "Осокина"}), "Липский")
        self.assertEqual(P.site_married({"name": "Феврония Jasieniew", "firstName": "Феврония", "lastName": ""}), "Jasieniew")
        self.assertEqual(P.site_married({"name": "Anna Uss (Lipska)", "firstName": "Anna", "lastName": "Uss (Lipska)"}), "")

    def test_maiden_in_card_gets_husband_feminine(self):
        t = self.tree(h=self.person("Виктор Липский", sex="M"))
        self.assertEqual(P.site_names(self.person("Елена Осокина", ["h"]), t),
                         {"firstName": "Елена", "lastName": "Осокина", "marriedName": "Липская"})

    def test_neutral_surname_left_to_site(self):
        t = self.tree(h=self.person("Прокоп Клёнич", sex="M"))
        self.assertNotIn("marriedName", P.site_names(self.person("Мелания Вишнякова", ["h"]), t))

    def test_husband_surname_in_card(self):
        t = self.tree(h=self.person("Аким Ясенев", sex="M"))
        self.assertEqual(P.site_names(self.person("Пелагея Ясенева", ["h"]), t),
                         {"firstName": "Пелагея", "lastName": "", "marriedName": "Ясенева"})

    def test_two_husbands_unknown(self):
        t = self.tree(a=self.person("Савва Ольховский", sex="M"), b=self.person("Вавила Липский", sex="M"))
        self.assertNotIn("marriedName", P.site_names(self.person("Анастасия Ракитина", ["a", "b"]), t))

class SiteNumber(unittest.TestCase):
    def test_gedcom_to_site(self):
        card = type("C", (), {"fm": {"gedcom_id": "I12"}})
        self.assertEqual(P.site_no(card), "112")
        self.assertIsNone(P.site_no(type("C", (), {"fm": {}})))


if __name__ == "__main__":
    unittest.main()


class EventWorks(unittest.TestCase):
    """События на сайт: только с mh_fact, только тем, кто есть на сайте, и не живым (25.10.2026)."""
    def setUp(self):
        from types import SimpleNamespace as N
        self.N = N
        dead = N(stem="Иван", born=dates.parse_card("1885"), died=dates.parse_card("1936"), children=[], father=[], mother=[], spouses=[])
        alive = N(stem="Мария", born=dates.parse_card("1940"), died=None, children=[], father=[], mother=[], spouses=[])
        self.cards = {"d": dead, "a": alive}
        self.tree = N(places={}, events=[
            {"cr_id": "e1", "title": "В Америку", "mh_fact": "IMMI", "date": "1911-11-12", "persons": ["[[Иван]]", "[[Мария]]"]},
            {"cr_id": "e2", "title": "Без пометки", "date": "1911", "persons": ["[[Иван]]"]},
        ])

    def test_only_marked_dead_on_site(self):
        out = P.event_works(self.tree, self.cards, {"d": "1500091", "a": "1500092"}, {}, set(), {})
        self.assertEqual([w["work"] for w in out], ["e1:d:event"])
        self.assertEqual((out[0]["fact"], out[0]["ind"], out[0]["date"]["y1"]), ("IMMI", "1500091", 1911))

    def test_not_on_site_skipped(self):
        self.assertEqual(P.event_works(self.tree, self.cards, {}, {}, set(), {}), [])


class FamilyAndJobs(unittest.TestCase):
    """Брак, развод, работа, главное фото на MyHeritage (04.11.2026)."""
    def setUp(self):
        from types import SimpleNamespace as N
        F = lambda label, text, date=None: N(label=label, text=text, date=dates.parse_card(date) if date else None, line=1)
        self.N, self.F = N, F
        self.v = N(stem="Василий", born=dates.parse_card("1923"), died=dates.parse_card("1993"), spouses=["o"], fm={},
                   facts=[F("брак", "23.09.1944, г. [[Вербичи]], с [[Ольга]]")], father=[], mother=[], children=[])
        self.o = N(stem="Ольга", born=dates.parse_card("1927"), died=dates.parse_card("2010"), spouses=["v"], fm={},
                   facts=[], father=[], mother=[], children=[])
        self.tree = N(places={}, events=[])

    def test_marriage_from_fact_with_day(self):
        out = P.family_works(self.tree, {"v": self.v, "o": self.o}, {"v": "1", "o": "2"}, {}, set(), {}, {})
        self.assertEqual(len(out), 1)
        w = out[0]
        self.assertEqual((w["kind"], w["date"]["y1"], w["date"]["m1"], w["date"]["d1"]), ("MARR", 1944, 9, 23))
        self.assertFalse(w["risky"])

    def test_changed_marriage_is_risky(self):
        first = P.family_works(self.tree, {"v": self.v, "o": self.o}, {"v": "1", "o": "2"}, {}, set(), {}, {})[0]
        key = first["work"].rsplit(":", 1)[0]
        again = P.family_works(self.tree, {"v": self.v, "o": self.o}, {"v": "1", "o": "2"}, {}, set(), {}, {key: "000000"})[0]
        self.assertTrue(again["risky"])          # на сайте уже лежит прежний — второй не добавляем молча

    def test_living_or_undated_skipped(self):
        self.o.died, self.o.born = None, dates.parse_card("1990")
        self.assertEqual(P.family_works(self.tree, {"v": self.v, "o": self.o}, {"v": "1", "o": "2"}, {}, set(), {}, {}), [])

    def test_jobs(self):
        self.assertEqual(P.short_job("паркет; рано заболел диабетом"), "паркет")
        self.assertTrue(P.NO_JOB.match("в (1944–1945)"))
        self.assertTrue(P.NO_JOB.match("Не указано"))
        self.v.fm = {"occupation": "машинист паровоза"}
        self.v.facts = [self.F("Работа", "к 40 годам — бригадир"), self.F("Занятие", "Крестьянин")]
        out = P.occupation_works({"v": self.v}, {"v": "1"}, {}, set(), {})
        self.assertEqual([w["header"] for w in out], ["машинист паровоза", "Крестьянин"])   # «Работа» без даты — рассказ

    def test_portrait(self):
        self.assertFalse(P.is_portrait("Ellis_1911-11-12_Lituania_p132_Ivan_Pupkin.jpg"))
        self.assertFalse(P.is_portrait("Мария-Дубняк_с-Лялей_ОБОРОТ-надпись_фото.jpg"))
        self.assertFalse(P.is_portrait("Вера-Ясенева_могила_уч31.jpg"))
        self.assertTrue(P.is_portrait("Василий-Ясенев_фото-из-паспорта-СССР_1974.jpg"))
        self.assertTrue(P.is_portrait("I198_01_Adam_Jasieniew_.jpg"))


class FactDate(unittest.TestCase):
    def go(self, label, text="", date="1881"):
        from types import SimpleNamespace as N
        return P.fact_date(N(label=label, text=text, date=dates.parse_card(date), line=1))

    def test_new_style_given(self):
        d = self.go("26 октября (ст. ст.; н. ст. 7 ноября)").a
        self.assertEqual((d.y, d.m, d.d), (1881, 11, 7))

    def test_old_style_converted(self):
        d = self.go("26 октября (ст. ст.)").a
        self.assertEqual((d.y, d.m, d.d), (1881, 11, 7))

    def test_may_and_march(self):
        self.assertEqual(self.go("3 мая", date="1914").a.m, 5)
        self.assertEqual(self.go("3 марта", date="1914").a.m, 3)

    def test_day_in_text(self):
        d = self.go("брак", "23.09.1944, г. Вербичи", "1944").a
        self.assertEqual((d.m, d.d), (9, 23))


class OneWordWife(unittest.TestCase):
    def test_wife_gets_husband_surname_after_marriage(self):
        from types import SimpleNamespace as N
        husband = N(name="Witold Brzozowski")
        wife = N(name="Агата", sex="F", spouses=["h"], fm={})
        out = P.site_names(wife, N(people={"h": husband}))
        self.assertEqual((out["firstName"], out["lastName"], out["marriedName"]), ("Агата", "", "Brzozowski"))


class OneWordName(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace as N
        self.N = N

    def tree(self, **people):
        return self.N(people=people)

    def test_surname_from_children(self):
        N = self.N
        dad = N(name="Пупкин", sex="M", spouses=[], children=["k"], facts=[], fm={})
        self.assertEqual(P.site_names(dad, self.tree(k=N(name="Марина Пупкин"))), {"firstName": "", "lastName": "Пупкин"})

    def test_surname_from_surname_line(self):
        N = self.N
        f = N(label="Фамилия", text="Lipski — по фамилии жены: на её камне «Ewa Lipski»")
        p = N(name="Lipski", sex="M", spouses=[], children=[], facts=[f], fm={})
        self.assertEqual(P.site_names(p, self.tree()), {"firstName": "", "lastName": "Lipski"})

    def test_inferred_surname(self):
        N = self.N
        p = N(name="Вавила", sex="M", spouses=[], children=[], facts=[], fm={"surname_inferred": "Brzozowski — по матери"})
        self.assertEqual(P.site_names(p, self.tree()), {"firstName": "Вавила", "lastName": "Brzozowski"})

    def test_plain_first_name(self):
        N = self.N
        p = N(name="Прокоп", sex="M", spouses=[], children=[], facts=[], fm={})
        self.assertEqual(P.site_names(p, self.tree()), {"firstName": "Прокоп", "lastName": ""})
