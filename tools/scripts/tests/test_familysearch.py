import argparse
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import familysearch as fs  # noqa: E402


def person(pid, name, principal=False, male=True, facts=()):
    return {"id": pid, "principal": principal, "gender": {"type": "http://gedcomx.org/" + ("Male" if male else "Female")},
            "names": [{"nameForms": [{"fullText": name}]}],
            "facts": [{"type": "http://gedcomx.org/" + k, "date": {"original": d}, "place": {"original": pl}}
                      for k, d, pl in facts]}


def entry(eid, persons, rels, rtype="Birth", film="000000123_004_ZZ7G-QQ7", img="9ZZZ-QQQQ-41CX"):
    return {"id": eid, "content": {"gedcomx": {
        "persons": persons,
        "relationships": [{"type": "http://gedcomx.org/" + t, "person1": {"resourceId": a}, "person2": {"resourceId": b}}
                          for t, a, b in rels],
        "sourceDescriptions": [{"coverage": [{"recordType": "http://gedcomx.org/" + rtype}],
                                "about": f"https://www.familysearch.org/ark:/61903/3:1:{img}"}],
        "fields": [{"type": "http://familysearch.org/types/fields/DigitalFilmNbr", "values": [{"text": film}]}]}}}


# Николай Ясенев, рожд. 16.04.1892 — запись вымышленная, сокращённая до нужных полей
ANTONY = entry("ZZ5E-QQ5", [
    person("p1", "Николай Ясенев", principal=True, facts=[("Birth", "16 Apr 1892", "Гродненская губерния")]),
    person("p2", "Аким Евстафьев Ясенев"),
    person("p3", "Ирина Сергеевна", male=False)],
    [("ParentChild", "p2", "p1"), ("ParentChild", "p3", "p1"), ("Couple", "p2", "p3")])

# Брак: у жениха первым фактом идёт «рождение», вычисленное из возраста, — событие записи всё равно брак
WEDDING = entry("ZZ6F-QQ6", [
    person("p1", "Вавила Прокопов Ясенев", principal=True,
           facts=[("Birth", "1823", ""), ("Marriage", "1845", "Гродненская губерния")]),
    person("p2", "Мелания Липская", male=False), person("p3", "Савва Кленюк")],
    [("Couple", "p1", "p2"), ("ParentChild", "p3", "p2")], rtype="Marriage", img="9ZZZ-QQQQ-41MG")


class ParseEntry(unittest.TestCase):
    def test_roles_film_image(self):
        x = fs.parse_entry(ANTONY)
        self.assertEqual(x["name"], "Николай Ясенев")
        self.assertEqual(x["others"], ["отец Аким Евстафьев Ясенев", "мать Ирина Сергеевна"])
        self.assertEqual((x["film"], x["image"], x["id"]), ("000000123", "9ZZZ-QQQQ-41CX", "1:1:ZZ5E-QQ5"))
        self.assertEqual((x["kind"], x["date"], x["born"]), ("рожд.", "16 Apr 1892", "1892"))

    def test_marriage_event_not_computed_birth(self):
        x = fs.parse_entry(WEDDING)
        self.assertEqual((x["kind"], x["date"], x["born"]), ("брак", "1845", "1823"))
        self.assertEqual(x["others"], ["супруг(а) Мелания Липская", "отец Мелания Савва Кленюк"])

    def test_empty_entry(self):
        self.assertIsNone(fs.parse_entry({"id": "X", "content": {"gedcomx": {}}}))


class OwnFilter(unittest.TestCase):
    def test_given_and_birth_years(self):
        x = fs.parse_entry(ANTONY)
        self.assertTrue(fs.keep(x, "Никола", "1885-1900"))
        self.assertFalse(fs.keep(x, "Аким", None))
        self.assertFalse(fs.keep(x, None, "1850-1870"))

    def test_yo_is_e(self):
        x = dict(fs.parse_entry(ANTONY), name="Пётр Ясенев")
        self.assertTrue(fs.keep(x, "Петр", None))

    def test_two_index_passes_become_one_row(self):
        a = fs.parse_entry(ANTONY)
        b = dict(a, id="1:1:ZZ5E-XXXX")
        rows = fs.merge_copies([a, b])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["copies"], 2)


class Rate(unittest.TestCase):
    def test_hour_limit(self):
        now = 10_000.0
        state = {"times": [now - 10] * (fs.HOURLY - 2), "stop_until": 0}
        self.assertEqual(fs.rate_plan(state, 5, now)[0], 2)
        self.assertEqual(fs.rate_plan({"times": [now - 4000] * 500, "stop_until": 0}, 5, now)[0], 5)

    def test_after_429_wait(self):
        n, why = fs.rate_plan({"times": [], "stop_until": 10_500}, 3, 10_000)
        self.assertEqual(n, 0)
        self.assertIn("429", why)


def ns(**kw):
    base = dict(surname=None, given=None, father=None, father_surname=None, mother=None, spouse=None,
                spouse_surname=None, born=None, died=None, married=None, collection=fs.GRODNO, film=None,
                exact=False, param=None)
    base.update(kw)
    return argparse.Namespace(**base)


class Params(unittest.TestCase):
    def test_film_with_surname_is_not_sent(self):
        # сайт держит q.filmNumber только один; с фамилией молча ищет по всем — плёнку отбираем сами
        p = dict(fs.records_params(ns(surname="Ясенев", film="000000123")))
        self.assertNotIn("q.filmNumber", p)
        p = dict(fs.records_params(ns(film="000000123")))
        self.assertEqual(p["q.filmNumber"], "000000123")

    def test_years_and_exact(self):
        p = fs.records_params(ns(surname="Ясенев", born="1880-1900", exact=True, collection="all"))
        self.assertIn(("q.surname.exact", "on"), p)
        self.assertIn(("q.birthLikeDate.to", "1900"), p)
        self.assertNotIn("f.collectionId", dict(p))


class StateLine(unittest.TestCase):
    def test_empty_is_not_absence(self):
        self.assertIn("не «нет в архиве»", fs.state_line("", 0))

    def test_blocked_is_not_result(self):
        self.assertIn("не «нет»", fs.state_line("не дошло: 429", 0))

    def test_found(self):
        self.assertEqual(fs.state_line("", 3, 3), "нашлось 3")

    def test_state_word_for_journal(self):
        self.assertEqual(fs.state_word("не дошло: 429", 0), "не дошло")
        self.assertEqual(fs.state_word("не дошло: 429", 4), "частично")
        self.assertEqual(fs.state_word("не дошло: 403 — закрыто", 0), "закрыто")
        self.assertEqual(fs.state_word("", 0), "пусто")
        self.assertEqual(fs.state_word("", 5, got=100, total=136), "частично")   # забрали не всё
        self.assertEqual(fs.state_word("", 1, got=136, total=136), "нашлось")


if __name__ == "__main__":
    unittest.main()
