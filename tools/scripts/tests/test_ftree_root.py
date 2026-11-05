"""Корень дерева по ftree.toml (paths.find_root) и пустышки медиа для проверок на GitHub (media.py stub).

Запуск: python3 -m unittest discover tools/scripts/tests
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import media  # noqa: E402
import paths  # noqa: E402
PHOTOS_FAMILY = paths.rel(paths.PHOTOS_FAMILY)

ENGINE = Path(__file__).resolve().parents[3]  # папка, где лежат сами скрипты


class FindRootTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ftree_root_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = {k: v for k, v in os.environ.items() if k != paths.ROOT_ENV}
        # файл ~/.config/ftree/env этого Mac не в счёт: его место в порядке проверяет test_setup.RootOrderTest
        for patcher in (mock.patch.dict(os.environ, env, clear=True),
                        mock.patch.dict(paths._ENV_FILE_VALUES, {}, clear=True)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_finds_toml_upwards_from_start(self):
        (self.tmp / "ftree.toml").write_text("[tree]\n", encoding="utf-8")
        deep = self.tmp / paths.rel(paths.PEOPLE)
        deep.mkdir(parents=True)
        self.assertEqual(paths.find_root(deep), self.tmp.resolve())

    def test_outside_any_tree(self):
        # приложение внутри данных — запасной корень: дерево самого скрипта; приложение отдельно (ftree-app) — дерева нет,
        # понятная ошибка вместо чужого дерева
        if (ENGINE / paths.CONFIG_NAME).is_file():
            self.assertEqual(paths.find_root(self.tmp), ENGINE)
        else:
            with self.assertRaises(SystemExit):
                paths.find_root(self.tmp)

    def test_env_wins(self):
        os.environ[paths.ROOT_ENV] = str(self.tmp)
        self.assertEqual(paths.find_root(ENGINE), self.tmp.resolve())

    def test_branches_come_from_toml_in_order(self):
        self.assertEqual(list(paths.LINES), ["Ясеневы", "Дубняки"])          # образец: tests/sample_tree.py
        self.assertEqual(paths.LINES["Дубняки"], "Евстафий Дубняк")


class StubTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="media_stub_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        (self.root / "media").mkdir()
        rows = [{"path": f"{PHOTOS_FAMILY}/Сергей_1950.jpg"}, {"path": "есть.pdf"}]
        (self.root / "media" / "manifest.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        (self.root / "есть.pdf").write_bytes(b"real")

    def run_stub(self, ci):
        env = {k: v for k, v in os.environ.items() if k != "CI"} | ({"CI": "true"} if ci else {})
        with mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(io.StringIO()):
            return media.main(["--root", str(self.root), "--remote", "x:", "--open-remote", "y:", "stub"])

    def test_refuses_outside_ci(self):
        self.assertEqual(self.run_stub(ci=False), 1)
        self.assertFalse((self.root / paths.SOURCES.name).exists())

    def test_creates_missing_and_keeps_real(self):
        self.assertEqual(self.run_stub(ci=True), 0)
        self.assertEqual((self.root / f"{PHOTOS_FAMILY}/Сергей_1950.jpg").stat().st_size, 0)
        self.assertEqual((self.root / "есть.pdf").read_bytes(), b"real")


if __name__ == "__main__":
    unittest.main()
