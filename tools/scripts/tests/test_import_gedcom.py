"""Новое дерево «из коробки»: rodo init → rodo import gedcom tools/sample/sample.ged → все проверки (tools/ci.sh) по
нулям → данные сайта собираются (site_export.py --data), адрес на сайте без номера дома. И мелкие части: чтение
выгрузки MyHeritage (CONC посреди буквы, NEL, «х» перед разрывом), даты GEDCOM, загрузка в живое дерево.

Образец — вымышленное дерево tools/sample/sample.ged (30 человек, 5 поколений; что в нём проверяется — tools/sample/README.md).
Запуск: python3 -m unittest tools.scripts.tests.test_import_gedcom (или rodo test)
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dates  # noqa: E402
import gedcom_parse  # noqa: E402

TOOLS = Path(__file__).resolve().parents[2]
PY, RODO, SAMPLE = TOOLS / "py", TOOLS / "rodo", TOOLS / "sample" / "sample.ged"
GIT = ["git", "-c", "user.name=test", "-c", "user.email=test@example.com"]


def run(cmd, root, **kw):
    env = {**os.environ, "FTREE_ROOT": str(root), "FTREE_CI_SKIP_TESTS": "1"}
    return subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, **kw)


class ReadGedcomTest(unittest.TestCase):
    def lines(self, raw):
        with tempfile.NamedTemporaryFile(suffix=".ged", delete=False) as f:
            f.write(raw)
        try:
            return gedcom_parse.fold_cont(gedcom_parse.load_lines(f.name))
        finally:
            os.unlink(f.name)

    def test_conc_inside_letter(self):
        # «ж» = D0 B6: MyHeritage рвёт строку CONC между этими байтами
        raw = "0 @I1@ INDI\r\n1 NOTE ставил ".encode() + b"\xd0\r\n2 CONC \xb6" + "ернова".encode()
        self.assertEqual(self.lines(raw), ["0 @I1@ INDI", "1 NOTE ставил жернова"])

    def test_kha_before_break_is_not_nel(self):
        # «х» = D1 85: байт 0x85 — часть буквы, не разделитель строк; прежнее правило съедало его
        raw = "1 NOTE старых".encode() + b"\r\n2 CONC " + " верб".encode()
        self.assertEqual(self.lines(raw), ["1 NOTE старых верб"])

    def test_nel_and_cont(self):
        raw = "0 @I1@ INDI".encode() + b"\xc2\x85" + "1 NOTE раз".encode() + b"\r\n" + "2 CONT два".encode()
        self.assertEqual(self.lines(raw), ["0 @I1@ INDI", "1 NOTE раз\nдва"])

    def test_sample_reads(self):
        recs = gedcom_parse.build_tree(gedcom_parse.fold_cont(gedcom_parse.load_lines(SAMPLE)))
        people = gedcom_parse.parse_individuals(recs)
        self.assertEqual(len(people), 30)
        self.assertIn("ставил жернова", people["@I1@"]["notes"][0])
        self.assertIn("старых верб", people["@I1@"]["notes"][0])


class GedcomDateTest(unittest.TestCase):
    def test_forms(self):
        for ged, card in [("12 FEB 1852", "1852-02-12"), ("MAY 1905", "1905-05"), ("ABT 1855", "ABT 1855"),
                          ("BET 1930 AND 1931", "BET 1930 AND 1931"), ("FROM 1980", "FROM 1980"), ("TO 1950", "TO 1950"),
                          ("FROM 1941 TO 1945", "FROM 1941 TO 1945"), ("EST 1876", "EST 1876"), ("BEF 1941", "BEF 1941"),
                          ("INT 1883 (умер младенцем)", "1883")]:
            self.assertEqual(dates.parse_gedcom(ged).card(), card, ged)

    def test_julian_day_to_new_style(self):
        g = dates.parse_gedcom("@#DJULIAN@ 12 FEB 1852")
        self.assertEqual(g.card(), "1852-02-24")
        self.assertEqual(g.ru(), "24.02.1852 (12.02.1852 ст. ст.)")
        self.assertEqual(dates.parse_gedcom("@#DJULIAN@ 1852").card(), "1852")   # год не переводим

    def test_phrase_and_bad(self):
        self.assertEqual(dates.parse_gedcom("(в молодости)").kind, "PHRASE")
        self.assertIsNone(dates.parse_gedcom(""))
        with self.assertRaises(dates.DateError):
            dates.parse_gedcom("весной")


class OutOfTheBoxTest(unittest.TestCase):
    """Пустое дерево → образец → проверки и сборка данных сайта. Медленный (~40 с): идут все проверки дерева."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="ftree-ootb-"))
        cls.root = cls.tmp / "tree"
        r = subprocess.run([str(RODO), "init", str(cls.root), "--title", "Родословная Ясеневых"],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        r = run([str(RODO), "import", "gedcom", str(SAMPLE)], cls.root)
        assert r.returncode == 0, r.stdout + r.stderr
        cls.import_out = r.stdout
        subprocess.run(GIT + ["add", "-A"], cwd=cls.root, check=True)
        subprocess.run(GIT + ["commit", "-qm", "образец", "--no-verify"], cwd=cls.root, check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_layout(self):
        for d in ("1_sources/inbox", "2_transcripts", "3_research/tree/people", "3_research/tree/biographies",
                  "4_outputs", "setup/setup.toml", "setup/scan_deny.txt", "CLAUDE.md", ".gitignore", ".githooks/pre-commit"):
            self.assertTrue((self.root / d).exists(), d)
        hooks = subprocess.run(["git", "config", "core.hooksPath"], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(hooks.stdout.strip(), ".githooks")

    def test_init_refuses_existing_tree(self):
        before = (self.root / "ftree.toml").read_text(encoding="utf-8")
        r = subprocess.run([str(RODO), "init", str(self.root)], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("уже дерево", r.stdout + r.stderr)
        self.assertEqual((self.root / "ftree.toml").read_text(encoding="utf-8"), before)

    def test_cards(self):
        people = self.root / "3_research/tree/people"
        self.assertEqual(len(list(people.glob("*.md"))), 30)
        # братья-тёзки — две карточки, по году
        self.assertTrue((people / "Иван Ясенев (1878).md").exists())
        self.assertTrue((people / "Иван Ясенев (1885).md").exists())
        # ребёнок без имени — одной фамилией
        self.assertIn('name: "Ясенев"', (people / "Ясенев (1883).md").read_text(encoding="utf-8"))
        elisey = (people / "Прокоп Ясенев.md").read_text(encoding="utf-8")
        self.assertIn("born: 1852-02-24", elisey)                       # старый стиль → новый
        self.assertIn("24.02.1852 (12.02.1852 ст. ст.), рождение", elisey)
        self.assertIn("ставил жернова", elisey)                          # CONC посреди буквы
        anna = (people / "Анна Ясенева.md").read_text(encoding="utf-8")
        self.assertIn("born: 1881-03-15", anna)                          # два рождения 12 дней — одна дата
        self.assertIn("15.03.1881 (03.03.1881 ст. ст.)", anna)
        ivan = (people / "Иван Ясенев (1885).md").read_text(encoding="utf-8")
        self.assertIn("1925, развод", ivan)
        self.assertIn("father_id:", ivan)
        self.assertTrue((self.root / "3_research/tree/events/Развод — Иван Ясенев (1885) и Agata Wierzbowska (1925).md").exists())
        src = next((self.root / "3_research/tree/sources").glob("Чужое дерево — sample.ged*.md")).read_text(encoding="utf-8")
        self.assertIn('origin: "чужое дерево"', src)

    def test_all_checks_zero(self):
        r = run(["sh", str(TOOLS / "ci.sh")], self.root, timeout=600)
        self.assertEqual(r.returncode, 0, r.stdout[-4000:] + r.stderr[-2000:])
        self.assertIn("Все проверки прошли", r.stdout)
        self.assertIn("людей 30, ошибок 0", r.stdout)

    def test_site_data_hides_house_number(self):
        out = self.tmp / "site"
        r = subprocess.run(
            [str(PY), str(TOOLS / "scripts" / "site_export.py"), "--data"], cwd=self.root, capture_output=True, text=True,
            env={**os.environ, "FTREE_ROOT": str(self.root), "FTREE_SITE_EXPORT": str(out)}, timeout=600)
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-3000:])
        text = "".join(p.read_text(encoding="utf-8") for p in (out / "data").rglob("*.json"))
        self.assertIn("Лесогорск — Садовая", text)
        self.assertNotIn("12-34", text)
        self.assertIn("Ясенев", text)

    def test_live_tree_dry_run_writes_nothing(self):
        before = subprocess.run(["git", "status", "--porcelain"], cwd=self.root, capture_output=True, text=True).stdout
        r = run([str(RODO), "import", "gedcom", str(SAMPLE), "--dry-run"], self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("живое", r.stdout)
        self.assertIn("[[Иван Ясенев (1878)]]", r.stdout)               # похожие — в отчёте
        self.assertNotIn("[[Иван Ясенев (1885)]] | имя (Иван Ясенев), пол, год 1885 ~ 1878", r.stdout)
        after = subprocess.run(["git", "status", "--porcelain"], cwd=self.root, capture_output=True, text=True).stdout
        self.assertEqual(before, after)


class LiveCreateTest(unittest.TestCase):
    """Живое дерево + --create: карточки заводятся с maybe_same, старые не меняются, номер — external_id."""

    def test_create_with_maybe_same(self):
        tmp = Path(tempfile.mkdtemp(prefix="ftree-live-"))
        try:
            root = tmp / "tree"
            subprocess.run([str(RODO), "init", str(root), "--no-git"], capture_output=True, check=True)
            run([str(RODO), "import", "gedcom", str(SAMPLE)], root, check=True)
            people = root / "3_research/tree/people"
            old = {p.name: p.read_text(encoding="utf-8") for p in people.glob("*.md")}
            r = run([str(RODO), "import", "gedcom", str(SAMPLE)], root)
            self.assertIn("карточки не созданы", r.stdout)
            self.assertEqual(len(list(people.glob("*.md"))), 30)
            self.assertTrue(list((root / "3_research/tree_data/import").glob("sample — *.md")))
            r = run([str(RODO), "import", "gedcom", str(SAMPLE), "--create"], root)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(len(list(people.glob("*.md"))), 60)
            for name, text in old.items():
                self.assertEqual((people / name).read_text(encoding="utf-8"), text, name)
            new = (people / "Прокоп Ясенев (1852).md").read_text(encoding="utf-8")
            self.assertIn('external_id: "I1"', new)
            self.assertNotIn("gedcom_id", new)
            self.assertIn('maybe_same:\n  - "[[Прокоп Ясенев]]"', new)
            r = run([str(PY), str(TOOLS / "scripts" / "check_tree.py")], root)
            self.assertEqual(r.returncode, 0, r.stdout[-2000:])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
