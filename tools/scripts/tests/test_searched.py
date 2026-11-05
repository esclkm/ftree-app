import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import searched  # noqa: E402
import paths  # noqa: E402
PAVEL = paths.rel(paths.PAVEL)


class FramesTest(unittest.TestCase):
    def test_parse_frames(self):
        self.assertEqual(searched.parse_frames("9,16,18-20"), {9, 16, 18, 19, 20})
        self.assertEqual(searched.parse_frames("5–3"), {3, 4, 5})
        self.assertEqual(searched.parse_frames(""), set())
        self.assertEqual(searched.parse_frames("кадры не указаны"), set())

    def test_fmt_frames(self):
        self.assertEqual(searched.fmt_frames([1, 2, 3, 7, 9, 10]), "1-3,7,9-10")

    def test_film_of(self):
        self.assertEqual(searched.film_of("плёнка 007700003 (Заречье)"), "007700003")
        self.assertEqual(searched.film_of("запрос «Дубняк*»"), "")


class CheckTest(unittest.TestCase):
    def write(self, text):
        f = tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False, encoding="utf-8")
        f.write(text)
        f.close()
        return f.name

    def test_good_and_bad_rows(self):
        head = "\t".join(searched.COLS) + "\n"
        ok = "2026-10-14\thryc\tзапрос\t\tкто\tкак\tитог\t\tпусто\n"
        self.assertEqual(searched.check(self.write(head + ok)), [])
        bad = "14.10.2026\tsomewhere\tзапрос\t\tкто\tкак\tитог\t\tпусто\n"
        errs = searched.check(self.write(head + bad))
        self.assertTrue(any("дата" in e for e in errs))
        self.assertTrue(any("источник" in e for e in errs))
        short = "2026-10-14\thryc\tзапрос\n"
        self.assertTrue(any("полей" in e for e in searched.check(self.write(head + short))))

    def test_report_path_from_root_is_explained(self):
        head = "\t".join(searched.COLS) + "\n"
        rep = "findings/_подсказки_Ясеневых_2026-10-30.md"           # отчёт в образце (tests/sample_tree.py)
        report = searched.paths.PAVEL / rep
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("# отчёт\n", encoding="utf-8")
        self.addCleanup(report.unlink)
        self.assertEqual(searched.norm_report(f"{PAVEL}/" + rep), rep)
        row = f"2026-10-31\tfamilysearch\tплёнка\t\tкто\tкак\tитог\t{PAVEL}/{rep}\tнашлось\n"
        errs = searched.check(self.write(head + row))
        self.assertEqual(len(errs), 1)
        self.assertIn(f"заменить на «{rep}»", errs[0])
        self.assertEqual(searched.check(self.write(head + row.replace(f"{PAVEL}/", ""))), [])

    def test_read_log_skips_header(self):
        head = "\t".join(searched.COLS) + "\n"
        rows = searched.read_log(self.write(head + "2026-10-14\thryc\tзапрос «Вербич*»\t\tВербичи\tтекст\t109 стр.\t\tнашлось\n"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["источник"], "hryc")


class StateTest(unittest.TestCase):
    def test_guess_from_result(self):
        g = searched.guess_state
        self.assertEqual(g("⛔ Гликерии нет"), "пусто")
        self.assertEqual(g("✅ брак 1902; зеркало 403"), "нашлось")      # нашли наше — важнее сбоя по пути
        self.assertEqual(g("⛔ ответ FS 429, указатели собраны частично"), "не дошло")
        self.assertEqual(g("⛔ нет (одно чтение); 95-129 не читано"), "частично")
        self.assertEqual(g("⛔ Image Restricted"), "закрыто")
        self.assertEqual(g("⏳ читается"), "частично")
        self.assertEqual(g("⚪ тёзки, наших нет"), "нашлось")
        self.assertIsNone(g("Вербичи 18 стр., Липки 7"))

    def write(self, text):
        f = tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False, encoding="utf-8")
        f.write("\t".join(searched.COLS) + "\n" + text)
        f.close()
        return f.name

    def test_check_state(self):
        old_blank = "2026-10-14\thryc\tзапрос\t\tкто\tкак\tВербичи 18 стр.\t\t\n"
        self.assertEqual(searched.check(self.write(old_blank)), [])      # до поля — можно пусто
        new_blank = old_blank.replace("2026-10-14", "2026-11-05")
        self.assertTrue(any("состояние" in e for e in searched.check(self.write(new_blank))))
        wrong = old_blank.replace("\t\t\n", "\t\tнайдено\n")
        self.assertTrue(any("состояние" in e for e in searched.check(self.write(wrong))))

    def test_blocked_frames_are_not_read(self):
        rows = [{"что": "плёнка 007700000", "кадры": "1-3", "итог": "⛔ 429", "состояние": "не дошло", "дата": "2026-11-04"},
                {"что": "плёнка 007700000", "кадры": "5", "итог": "⛔ нет", "состояние": "пусто", "дата": "2026-11-04"}]
        seen = {n for r in rows if r["состояние"] not in searched.NOT_READ for n in searched.parse_frames(r["кадры"])}
        self.assertEqual(seen, {5})


if __name__ == "__main__":
    unittest.main()
