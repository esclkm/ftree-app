import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / ".claude" / "skills" / "archive-gaso"))
import gaso_download as dl

JPEG = b"\xff\xd8\xff" + b"0" * 20000


class StubTests(unittest.TestCase):
    """Исчерпанный абонемент: вместо JPEG приходит заглушка ≈1,3 КБ."""

    def test_stub_is_not_scan(self):
        html = b"<html>" + b"x" * 1300 + b"</html>"
        self.assertFalse(dl.is_scan(html))
        self.assertFalse(dl.is_scan(b"\xff\xd8\xff" + b"0" * 1300))  # JPEG-шапка, но крошечный
        self.assertTrue(dl.is_scan(JPEG))

    def test_old_stub_file_is_dropped_and_redownloaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / "a_001.jpg"
            stub.write_bytes(b"<html>" + b"x" * 1300)
            good = Path(tmp) / "a_002.jpg"
            good.write_bytes(JPEG)
            self.assertFalse(dl.have_scan(stub))
            self.assertFalse(stub.exists())
            self.assertTrue(dl.have_scan(good))
            self.assertFalse(dl.have_scan(Path(tmp) / "a_003.jpg"))

    def test_has_scan_does_not_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / "a_001.jpg"
            stub.write_bytes(b"x" * 1300)
            self.assertFalse(dl.has_scan(stub))
            self.assertTrue(stub.exists())


if __name__ == "__main__":
    unittest.main()
