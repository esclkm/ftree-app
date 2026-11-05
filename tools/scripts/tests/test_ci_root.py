"""rodo check и tools/ci.sh проверяют то дерево, из папки которого их позвали, а не дерево из ~/.config/ftree/env:
ci.sh меняет папку на приложение, и найти дерево после этого уже нельзя."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tree_init  # noqa: E402

APP = Path(__file__).resolve().parents[3]


class CheckFindsTreeByFolder(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ftree-ci-root-")).resolve()
        self.tree = self.tmp / "tree"
        tree_init.create(self.tree, git=False, out=lambda *_: None)
        other = self.tmp / "other"               # «настоящее» дерево этого Mac из файла env
        tree_init.create(other, git=False, out=lambda *_: None)
        envf = self.tmp / "env"
        envf.write_text(f"FTREE_ROOT={other}\n", encoding="utf-8")
        self.env = {k: v for k, v in os.environ.items() if k != "FTREE_ROOT"} | {"FTREE_ENV_FILE": str(envf)}

    def tearDown(self):
        subprocess.run(["rm", "-rf", str(self.tmp)])

    def root(self, *cmd, cwd):
        r = subprocess.run(list(cmd), cwd=cwd, env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return Path(r.stdout.strip().splitlines()[-1]).resolve()

    def test_ci_sh_from_inside_tree(self):
        self.assertEqual(self.root("sh", str(APP / "tools/ci.sh"), "--root", cwd=self.tree), self.tree)

    def test_rodo_check_from_subfolder(self):
        self.assertEqual(self.root(str(APP / "tools/rodo"), "check", "--root", cwd=self.tree / "3_research"), self.tree)

    def test_explicit_variable_wins(self):
        self.env["FTREE_ROOT"] = str(self.tmp / "other")
        self.assertEqual(self.root("sh", str(APP / "tools/ci.sh"), "--root", cwd=self.tree), self.tmp / "other")


if __name__ == "__main__":
    unittest.main()
