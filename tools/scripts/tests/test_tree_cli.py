"""Тесты tree.py (вопросы к дереву) на выдуманном дереве. Запуск: python3 -m unittest discover tools/scripts/tests"""
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cards  # noqa: E402
import tree as T  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cards import write  # noqa: E402

SRC = "Аудио 04 — дед Вавила"


def person(root, name, cid, sex, **kw):
    fm = [f"cr_id: {cid}", f"name: {name}", f"sex: {sex}"]
    body = kw.pop("body", "")
    for k, v in kw.items():
        if isinstance(v, list):
            fm.append(f"{k}:\n" + "\n".join(f'  - "{x}"' for x in v))
        else:
            fm.append(f'{k}: "{v}"' if "[[" in str(v) else f"{k}: {v}")
    write(root / "people", name, "\n".join(fm), body)


def family():
    """Дед Прокоп + Феврония → Сергей (+ Мария) → Николай → Михаил; брат Михаила Пётр; сестра Сергея Ольга → её сын
    Иван; жена Михаила Люцина, её мать Ядвига. Фамилия Сабулик — то латиницей, то по-русски, то по-белорусски."""
    root = Path(tempfile.mkdtemp())
    write(root / "sources", SRC, f'cr_type: source\ncr_id: src-001-aaa-001\ntitle: "{SRC}"\norigin: "семья"')
    write(root / "places", "Беларусь", "cr_type: place\ncr_id: plc-000-aaa-000\nname: Беларусь\nplace_type: country",
          "## Государства по годам\n\n- до 1915 — Российская империя\n- с 1991 — Беларусь\n")
    write(root / "places", "Кленовка", 'cr_type: place\ncr_id: plc-001-aaa-001\nname: Кленовка\nplace_type: village\n'
                                      'parent_place: "[[Беларусь]]"')
    fact = (f"## Факты и заметки\n\n### Факты (с источником)\n\n- **1890:** родился в [[Кленовка]] — *источник: [[{SRC}]], "
            f"10:01 · уверенность: обычная*\n")
    person(root, "Прокоп Sabulik", "g", "male", born=1890, birth_place="[[Кленовка]]", research_priority="P1",
           sources=[f"[[{SRC}]]"], body=fact)
    person(root, "Феврония Хвостак", "s", "female", born=1893)
    person(root, "Сергей Sabulik", "se", "male", born=1929, died=2000, father_id="g", mother_id="s",
           father="[[Прокоп Sabulik]]", mother="[[Феврония Хвостак]]", spouse="[[Мария Плашко]]", spouse_id="m")
    person(root, "Мария Плашко", "m", "female", born="1937-08-01")
    person(root, "Ольга Sabulik", "o", "female", born=1919, father_id="g", mother_id="s")
    person(root, "Иван Kowalski", "iv", "male", born=1945, mother_id="o", aliases=["Иван Ковальский"])
    person(root, "Mikalaj Sabulik", "a", "male", born=1964, father_id="se", mother_id="m",
           aliases=["Николай Сабулик"])
    person(root, "Mikhail Sabulik", "p", "male", born=1986, father_id="a", spouse_id="v")
    person(root, "Пётр Сабулік", "pe", "male", born=1990, father_id="a")
    person(root, "Lucyna Piszkel", "v", "female", born=1990, mother_id="st")
    person(root, "Ядвига Пишкель", "st", "female", born=1960)
    (root / "events").mkdir()
    return root, cards.load(root)


class Spelling(unittest.TestCase):
    def test_same_surname_in_all_alphabets(self):
        for a, b in [("Sabulik", "Сабулик"), ("Сабулік", "Sabulik"), ("Plaszko", "Плашко"), ("Piszkel", "Пишкель"),
                     ("Chwostak", "Хвостак"), ("Kowalska", "Ковальский"), ("Sabulikowa", "Сабулик"),
                     ("Hlafira", "Глафира"), ("Ракитинъ", "Ракитин"), ("Свѣтъ", "Свет")]:
            self.assertTrue(T.word_match(a, b), (a, b))

    def test_different_surnames(self):
        for a, b in [("Sabulik", "Сабалик"), ("Плашко", "Плажник"), ("Uss", "Ус-Пишкель")]:
            self.assertFalse(T.word_match(a, b), (a, b))


class Commands(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root, cls.tree = family()

    def run_(self, *argv):
        return T.run(argv, self.tree, self.root)

    def test_who(self):
        out = self.run_("who", "Сергей Sabulik")
        self.assertTrue(out[0].startswith("Сергей Sabulik — муж., 1929–2000 · se"))
        self.assertIn("родители: Прокоп Sabulik (1890), Феврония Хвостак (1893)", out)
        self.assertIn("дети (1): Mikalaj Sabulik (1964)", out)
        self.assertIn("биографии нет", out)

    def test_who_by_alias_number_and_spelling(self):
        self.assertEqual(self.run_("who", "Николай Сабулик")[0][:15], "Mikalaj Sabulik")
        self.assertEqual(self.run_("who", "a")[0][:15], "Mikalaj Sabulik")
        self.assertEqual(self.run_("who", "Михаил Сабулик")[0][:15], "Mikhail Sabulik")   # только по написанию
        self.assertIn("подходят", self.run_("who", "Sabulik")[0])

    def test_kin_blood(self):
        cases = {("p", "g"): "прадед", ("p", "a"): "отец", ("g", "p"): "правнук", ("p", "pe"): "брат",
                 ("p", "o"): "двоюродная бабушка", ("p", "iv"): "двоюродный дядя", ("a", "iv"): "двоюродный брат",
                 ("iv", "a"): "двоюродный брат", ("o", "a"): "племянник", ("p", "m"): "бабушка"}
        for (a, x), term in cases.items():
            self.assertEqual(T.relation(self.tree, a, x)[0], term, (a, x))

    def test_kin_marriage(self):
        self.assertEqual(T.relation(self.tree, "p", "v")[0], "жена")
        self.assertEqual(T.relation(self.tree, "p", "st")[0], "тёща")
        self.assertEqual(T.relation(self.tree, "st", "p")[0], "зять")
        self.assertEqual(T.relation(self.tree, "a", "v")[0], "невестка")
        self.assertEqual(T.relation(self.tree, "pe", "v")[0], "невестка")
        self.assertEqual(T.relation(self.tree, "a", "st")[0], "свойственник (через браки)")
        out = self.run_("kin", "Mikhail Sabulik", "Ольга Sabulik")
        self.assertIn("цепочка: Mikhail Sabulik (1986) → отец Mikalaj Sabulik (1964) → отец Сергей Sabulik", out[1])

    def test_genitive(self):
        self.assertEqual(T.gen("двоюродный брат"), "двоюродного брата")
        self.assertEqual(T.gen("внучатая племянница"), "внучатой племянницы")
        self.assertEqual(T.gen("прадед"), "прадеда")

    def test_find(self):
        out = self.run_("find", "Сабулик")
        self.assertTrue(out[0].startswith("«Сабулик»: людей 6"), out[0])
        self.assertIn("Sabulik", out[0])
        self.assertIn("Сабулік", out[0])
        self.assertTrue(self.run_("find", "Kowalski")[0].startswith("«Kowalski»: людей 1"))

    def test_place(self):
        out = self.run_("place", "Кленовка")
        self.assertEqual(out[0], "Кленовка (village) · в: Беларусь")
        self.assertIn("эпохи: до 1915 — Российская империя; с 1991 — Беларусь", out)
        self.assertIn("род. 1890: Прокоп Sabulik (1890)", out)
        self.assertIn("род. 1890: Прокоп Sabulik (1890)", self.run_("place", "Беларусь"))   # и всё, что внутри

    def test_src(self):
        out = self.run_("src", "Аудио 04")
        self.assertEqual(out[1], "называет людей: 1, фактов: 1")
        self.assertEqual(out[2], "  Прокоп Sabulik (1890): фактов 1 · 10:01")

    def test_mentions_uses_cache(self):
        (self.root / "notes").mkdir(exist_ok=True)
        f = self.root / "notes" / "рассказ.md"
        f.write_text("Про деда Прокопа Сабулика: [[Прокоп Sabulik]] и Прокоп Sabulik.\n", encoding="utf-8")
        cache = self.root / "cache.json"
        out = T.mentions(self.tree, "Прокоп Sabulik", self.root, cache)
        self.assertIn("  2 × notes/рассказ.md", "\n".join(out))
        self.assertNotIn("Прокоп Sabulik.md", "\n".join(out))   # своя карточка не в счёт
        f.write_text("[[Прокоп Sabulik]]\n", encoding="utf-8")
        import os
        os.utime(f, (time.time() + 5, time.time() + 5))
        self.assertIn("  1 × notes/рассказ.md", "\n".join(T.mentions(self.tree, "Прокоп Sabulik", self.root, cache)))

    def test_gaps(self):
        self.assertEqual(self.run_("gaps", "Феврония Хвостак"),
                         ["Феврония Хвостак (1893) — не хватает: место рождения, родители, факты с источником, источники, "
                          "год рождения подтверждён фактом"])
        out = self.run_("gaps", "--p", "P1")
        self.assertEqual(out[0], "людей: 1 · P1")
        self.assertIn("нет «биография»: 1 — сначала: Прокоп Sabulik P1", out)

    def test_targets(self):
        out = self.run_("targets", "--place", "Кленовка", "--years", "1880-1900")
        self.assertEqual(out[0], "Кленовка, 1880–1900: кандидатов 1 (место и всё внутри него: 1)")
        self.assertIn("метрика рождения 1890", out[1])
        self.assertIn("кандидатов 0", self.run_("targets", "--place", "Кленовка", "--years", "1990-2000")[0])

    def test_answer_is_short(self):
        lines = [str(i) for i in range(50)]
        self.assertEqual(len(T.clip(lines)), 20)
        self.assertEqual(T.clip(lines)[-1], "… ещё 31 (всё — --all)")
        self.assertEqual(len(T.clip(lines, full=True)), 50)


class OnSampleTree(unittest.TestCase):
    """На дереве-образце (tests/sample_tree.py, 30 вымышленных людей): cards.load() без папки читает его. Чтение дерева —
    до 3 с, каждая команда — до 0,5 с и не длиннее 20 строк; и ответы — по образцу, а не «не понял». Скорость на живом
    дереве (≈970 карточек) этот тест больше не меряет."""

    def test_fast(self):
        t0 = time.perf_counter()
        tree = cards.load()
        self.assertLess(time.perf_counter() - t0, 3.0, "чтение дерева")
        place = "Вербичи (Гродненская губерния, Российская империя)"
        for argv in (["who", "Аким Ясенев"], ["kin", "Прокоп Ясенев", "Аким Ясенев"], ["find", "Ясенев"],
                     ["place", place], ["src", "Метрическая книга"], ["gaps"],
                     ["targets", "--place", place, "--years", "1852-1885"]):
            t0 = time.perf_counter()
            out = T.run(argv, tree)
            self.assertLess(time.perf_counter() - t0, 0.5, argv)
            self.assertLessEqual(len(out), 20, argv)
            self.assertNotIn("не понял", out[0])
        self.assertTrue(T.run(["who", "Аким Ясенев"], tree)[0].startswith("Аким Ясенев — муж., 1985"))
        self.assertTrue(T.run(["kin", "Прокоп Ясенев", "Аким Ясенев"], tree)[0].startswith("Аким Ясенев (1985) — праправнук"))
        self.assertTrue(T.run(["find", "Ясенев"], tree)[0].startswith("«Ясенев»: людей 20"))


if __name__ == "__main__":
    unittest.main()
