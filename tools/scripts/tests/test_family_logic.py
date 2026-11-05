"""Логика семьи по датам (check_family_logic). Имена в тестах — вымышленные."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_family_logic as L  # noqa: E402


class ParentAge(unittest.TestCase):
    def test_normal(self):
        self.assertIsNone(L.parent_age_problem((1836, 1836), (1861, 1861), L.FATHER))

    def test_too_young_even_with_tolerance(self):
        self.assertIn("не больше", L.parent_age_problem((1850, 1850), (1860, 1860), L.FATHER))

    def test_tolerance_saves_rough_ages(self):
        # матери «51» по возрасту в документе — с допуском ±4 ещё допустимо
        self.assertIsNone(L.parent_age_problem((1820, 1820), (1871, 1871), L.MOTHER))

    def test_too_old_mother(self):
        self.assertIn("не меньше", L.parent_age_problem((1800, 1800), (1860, 1860), L.MOTHER))

    def test_unknown_dates_are_not_errors(self):
        self.assertIsNone(L.parent_age_problem((None, None), (1860, 1860), L.MOTHER))


class MotherByDates(unittest.TestCase):
    def test_single_wife_with_child_nearby(self):
        self.assertEqual(L.mother_candidate((1859, 1860), ["w1"], [("w1", (1861, 1861))]), "w1")

    def test_two_wives_no_guess(self):
        self.assertIsNone(L.mother_candidate((1859, 1860), ["w1", "w2"], [("w1", (1861, 1861))]))

    def test_children_too_far(self):
        self.assertIsNone(L.mother_candidate((1840, 1840), ["w1"], [("w1", (1861, 1861))]))


class Surname(unittest.TestCase):
    def test_inferred_needs_line(self):
        out = L.surname_problems({"surname_inferred": "Тестов — по отцу"}, "### Факты\n\n- **1900:** …", (1900, 1900))
        self.assertTrue(any("Фамилия" in m for _, m in out))

    def test_line_present(self):
        out = L.surname_problems({"surname_inferred": "Тестов — по отцу"}, "- **Фамилия:** в документах нет", (1900, 1900))
        self.assertEqual(out, [])

    def test_old_wife_by_husband(self):
        out = L.surname_problems({"surname_inferred": "Тестова — по мужу"}, "- **Фамилия:** …", (1870, 1870))
        self.assertTrue(any("по отцу" in m for _, m in out))

    def test_modern_wife_by_husband_ok(self):
        self.assertEqual(L.surname_problems({"surname_inferred": "Тестова — по мужу"}, "- **Фамилия:** …", (1950, 1950)), [])


if __name__ == "__main__":
    unittest.main()


class DeathBeforeBirth(unittest.TestCase):
    def test_father_may_die_before_posthumous_child(self):
        self.assertIsNone(L.death_before_birth((1860, 1860), (1861, 1861), "отец"))

    def test_child_long_after_mother_death(self):
        self.assertIn("умер", L.death_before_birth((1850, 1850), (1860, 1860), "мать"))

    def test_rough_age_tolerated(self):
        self.assertIsNone(L.death_before_birth((1860, 1860), (1863, 1863), "мать"))


class FatherByPatronymic(unittest.TestCase):
    index = L._patronymic_index(["Гордей"])

    def test_woman(self):
        self.assertEqual(L.father_by_patronymic("Мелания Акимова", "F", self.index), "Аким")

    def test_man_church_form(self):
        self.assertEqual(L.father_by_patronymic("Савва Иоаннов", "M", self.index), "Иван")

    def test_name_from_tree(self):
        self.assertEqual(L.father_by_patronymic("Анна Гордеева", "F", self.index), "Гордей")

    def test_real_surname_is_not_patronymic(self):
        self.assertIsNone(L.father_by_patronymic("Савва Ясенев", "M", self.index))


class LastAlive(unittest.TestCase):
    @staticmethod
    def fact(year, label, text=""):
        from types import SimpleNamespace
        return SimpleNamespace(date=SimpleNamespace(last_year=year), label=label, text=text)

    def test_latest_living_fact(self):
        fs = [self.fact(1850, "двор 3"), self.fact(1858, "двор 3"), self.fact(1860, "смерть")]
        self.assertEqual(L.last_alive_year(fs)[0], 1858)

    def test_own_birth_is_not_proof(self):
        self.assertEqual(L.last_alive_year([self.fact(1860, "рождение")], 1860), (None, None))


class MotherByWindow(unittest.TestCase):
    def test_single_wife_fertile_window(self):
        self.assertEqual(L.mother_candidate((1870, 1870), ["w1"], [], (1838, 1838)), "w1")

    def test_wife_too_old(self):
        self.assertIsNone(L.mother_candidate((1870, 1870), ["w1"], [], (1810, 1810)))


class Genitive(unittest.TestCase):
    def test_woman(self):
        self.assertEqual(L.genitive("Ирина Платонова", "F"), "Ирины Платоновой")

    def test_man(self):
        self.assertEqual(L.genitive("Савва Платонов", "M"), "Саввы Платонова")

    def test_soft(self):
        self.assertEqual(L.genitive("Феврония Назарова", "F"), "Февронии Назаровой")


class OpenDates(unittest.TestCase):
    def test_after_is_open_above(self):
        import dates
        self.assertEqual(L.years(dates.parse_card("AFT 1861")), (1861, None))
        self.assertIsNone(L.death_before_birth(L.years(dates.parse_card("AFT 1861")), (1870, 1870), "отец"))


class NameOnlyIsNotAlive(unittest.TestCase):
    def test_patronymic_mention_skipped(self):
        fs = [LastAlive.fact(1831, "двор 60"), LastAlive.fact(1868, "его сын записан «Пётр Мартынов»")]
        self.assertEqual(L.last_alive_year(fs)[0], 1831)


class AddToList(unittest.TestCase):
    def test_scalar_becomes_list(self):
        fm = 'name: X\nchildren: "[[A]]"\nsex: female'
        out = L._add_to_list(fm, "children", '"[[B]]"')
        self.assertEqual(out.count("children:"), 1)
        self.assertIn('  - "[[A]]"\n  - "[[B]]"', out)


class LifelineOpenDeath(unittest.TestCase):
    def test_after_is_not_a_death_year(self):
        import check_lifeline as C
        self.assertIsNone(C.death_year("AFT 1925"))
        self.assertEqual(C.death_year("1909-02-22"), 1909)


class SurnameLines(unittest.TestCase):
    def test_kind_wife_before_1900(self):
        self.assertEqual(L.surname_kind("Ковач — по мужу: [[Пётр Ковач]]", "F", True, True)[0], "old_wife")

    def test_old_by_father_is_for_human(self):
        self.assertIsNone(L.surname_kind("Ковач — по отцу: [[Пётр Ковач]]", "M", True, False))

    def test_unexplained_is_for_human(self):
        self.assertIsNone(L.surname_kind(True, "M", False, False))

    def test_married_daughter_kids_surname(self):
        line = L.surname_line("married_father", "Ковач", "Пётр Ковач", "[[S]]", "так в семейных источниках",
                              "Анна Лис", "Лис")
        self.assertIn("по мужу, вероятно, Лис", line)

    def test_old_by_children(self):
        self.assertTrue(L.is_old((None, None), (None, None), [1890]))
        self.assertFalse(L.is_old((1950, 1950), (None, None), [1980]))
