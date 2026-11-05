"""Список приложения (app_files.py, tools/APP_MANIFEST): что входит в ftree-app, что пропускается, что остаётся в данных."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app_files  # noqa: E402

MANIFEST = """# пример
app  tools/
app  Brewfile
skip tools/.cache/
tree tools/scripts/book.py   # книга этого дерева
tree .claude/skills/our/
"""


class AppFiles(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="app-files-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        for rel in ("tools/scripts/a.py", "tools/scripts/book.py", "tools/.cache/x.json", "Brewfile", "ftree.toml",
                    "3_research/tree/people/x.md", ".claude/skills/our/SKILL.md"):
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text("x", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "-A"], check=True)
        (self.root / "M").write_text(MANIFEST, encoding="utf-8")
        self.m = app_files.read(self.root / "M")

    def test_only_app_lines_without_skip_and_tree(self):
        self.assertEqual(app_files.files(self.root, self.m), ["Brewfile", "tools/scripts/a.py"])

    def test_tree_lines_keep_reason(self):
        self.assertEqual(self.m.tree["tools/scripts/book.py"], "книга этого дерева")
        self.assertEqual(app_files.tree_files(self.root, self.m), [".claude/skills/our/SKILL.md", "tools/scripts/book.py"])

    def test_unknown_line_is_an_error(self):
        (self.root / "M").write_text("take tools/\n", encoding="utf-8")
        with self.assertRaises(SystemExit):
            app_files.read(self.root / "M")

    def test_real_manifest_reads(self):   # список самого приложения разбирается, и данные дерева в него не входят
        m = app_files.read()
        self.assertIn("tools/", m.app)
        self.assertFalse([p for p in m.app if p.startswith(("1_sources", "2_transcripts", "3_research", "4_outputs"))])


if __name__ == "__main__":
    unittest.main()
