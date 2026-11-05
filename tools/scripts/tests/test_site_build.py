"""Сайт собирается из одной папки выгрузки, без карточек: вымышленное дерево (rodo init → импорт tools/sample/sample.ged)
→ rodo site export (site_export.py) → сборщик web/scripts/site.mjs build с FTREE_ROOT на несуществующую папку.

Проверяет границу движок → сайт: сборщику хватает data/*.json, media/, files/ и site.json; папка дерева ему не нужна.
Запуск: python3 -m unittest tools.scripts.tests.test_site_build (или rodo test). Нужен Node (web/node_modules).
"""
import sample_tree  # noqa: F401 — первым: FTREE_ROOT = вымышленное дерево

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2]
WEB = TOOLS.parent / "web"
SITE_MJS = WEB / "scripts" / "site.mjs"


def node():
    found = shutil.which("node")
    if found:
        return found
    nvm = sorted((Path.home() / ".nvm" / "versions" / "node").glob("*/bin/node"))
    return str(nvm[-1]) if nvm else None


@unittest.skipUnless(node() and (WEB / "node_modules").exists(), "нет Node или web/node_modules (npm ci в web/)")
class SiteFromExport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="ftree-site-"))
        cls.export, cls.out = cls.tmp / "export", cls.tmp / "site"
        sample_tree._site(cls.export, data_only=False)
        env = {k: v for k, v in os.environ.items() if not k.startswith("FTREE_")}
        env.update(FTREE_ROOT=str(cls.tmp / "нет-такого-дерева"), FTREE_ENV_FILE=str(cls.tmp / "нет-env"),
                   PATH=str(Path(node()).parent) + os.pathsep + env.get("PATH", ""))
        cls.built = subprocess.run([node(), str(SITE_MJS), "build", "--data", str(cls.export), "--out", str(cls.out)],
                                 cwd=cls.tmp, env=env, capture_output=True, text=True, timeout=600)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_builds_without_tree(self):
        self.assertEqual(self.built.returncode, 0, self.built.stdout[-3000:] + self.built.stderr[-3000:])
        self.assertTrue((self.out / "index.html").exists())
        self.assertTrue(list((self.out / "assets").glob("*.js")))

    def test_site_has_export_data(self):
        index = json.loads((self.out / "data" / "index.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(index["people"]), 25)
        self.assertEqual(len(list((self.out / "data" / "people").glob("*.json"))), len(index["people"]))
        self.assertFalse((self.out / "site.json").exists(), "site.json (список закрытых файлов) на сайт не идёт")

    def test_no_pages_from_python(self):
        """Все страницы рисует приложение: HTML в папке сайта — только его index.html."""
        self.assertEqual([p.relative_to(self.out).as_posix() for p in self.out.rglob("*.html")], ["index.html"])

    def test_login_check_filled(self):
        text = (self.out / "functions" / "_middleware.js").read_text(encoding="utf-8")
        self.assertNotIn("/*PRIVATE_FILES*/", text)
        self.assertNotIn("/*OPEN_COUNTRIES*/", text)
        site = json.loads((self.export / "site.json").read_text(encoding="utf-8"))
        self.assertIn(f"const OPEN_UNTIL = '{site['open_until']}'", text)

    def test_rebuild_copies_nothing_new(self):
        """Вторая сборка тех же данных ничего не копирует заново — выкладка не грузит файлы повторно."""
        r = subprocess.run([node(), str(SITE_MJS), "build", "--no-app", "--data", str(self.export), "--out", str(self.out)],
                           capture_output=True, text=True, timeout=600)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        self.assertIn("скопировано заново 0", r.stdout)

    def run_site(self, *argv, site_json=None):
        data = self.export
        if site_json is not None:  # та же выгрузка, другой site.json — копия ссылками, без копирования данных
            data = Path(tempfile.mkdtemp(dir=self.tmp))
            for name in ("data", "media", "files"):
                (data / name).symlink_to(self.export / name)
            (data / "site.json").write_text(json.dumps(site_json, ensure_ascii=False), encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k not in ("FTREE_PROXY_KEY_FILE",)}
        env["PATH"] = str(Path(node()).parent) + os.pathsep + "/usr/bin:/bin"  # без npx в PATH выкладка упала бы
        return subprocess.run([node(), str(SITE_MJS), *argv, "--no-app", "--data", str(data), "--out", str(self.out)],
                              capture_output=True, text=True, timeout=600, env=env)

    def test_fresh_tree_publishes_nowhere(self):
        """У нового дерева целей нет: publish только собирает и объясняет, что вписать; mirror — тоже ничего."""
        site = json.loads((self.export / "site.json").read_text(encoding="utf-8"))
        self.assertEqual(site["deploy"], {"targets": []})
        for cmd in ("publish", "mirror"):
            r = self.run_site(cmd)
            self.assertEqual(r.returncode, 0, r.stderr[-2000:])
            self.assertIn("[[site.target]]", r.stdout)
            self.assertNotIn("wrangler", r.stdout + r.stderr)

    def test_folder_target_and_manual(self):
        site = json.loads((self.export / "site.json").read_text(encoding="utf-8"))
        folder = self.tmp / "hosting" / "www"
        (self.tmp / "hosting").mkdir(exist_ok=True)
        site["deploy"] = {"targets": [{"kind": "folder", "role": "main", "name": str(folder), "manual": True}]}
        r = self.run_site("publish", site_json=site)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        self.assertFalse(folder.exists(), "manual — только по имени")
        r = self.run_site("publish", str(folder), site_json=site)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        self.assertTrue((folder / "index.html").exists())
        r = self.run_site("publish", "нет-такой", site_json=site)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("нет цели", r.stderr)

    def test_builder_does_not_know_the_tree(self):
        """Сборщик не читает карточки и папки дерева — только выгрузку."""
        code = SITE_MJS.read_text(encoding="utf-8")
        for word in ("3_research", "cards", "paths.py", "ftree.toml", "FTREE_ROOT"):
            self.assertNotIn(word, re.sub(r"^\s*//.*$", "", code, flags=re.M), word)


if __name__ == "__main__":
    unittest.main()
