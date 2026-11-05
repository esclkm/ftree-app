import contextlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import documents
import paths

R = paths.rel  # раскладка этажей от корня — та же во временном дереве


def page(name, date):
    return f'''  - file: "[[{name}]]"
    date: {date}
    what: рождение
    source: "[[ГАСО]]"
    locator: "д. 1"
'''


class DocumentsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        for name, value in (("ROOT", self.root), ("TREE", self.root / R(paths.TREE)),
                            ("DOCUMENTS", self.root / R(paths.DOCUMENTS))):
            stack.enter_context(patch.object(documents, name, value))
        (self.root / R(paths.PEOPLE)).mkdir(parents=True)
        (self.root / R(paths.PEOPLE) / "Савва.md").write_text("---\ncr_id: x\n---\n", encoding="utf-8")
        scans = self.root / R(paths.FOUND)
        scans.mkdir(parents=True)
        from PIL import Image
        for name in ("a.jpg", "b.jpg"):
            Image.new("RGB", (40, 20), "white").save(scans / name)
        self.folder = documents.DOCUMENTS / "Савва"
        self.folder.mkdir(parents=True)

    def write(self, pages, kind="metrics", variant="crops", obtained="ГАСО, ф. 48", text="## 1. 1894 — рождение\n"):
        md = self.folder / "1894 — Метрики — вырезки.md"
        md.write_text(f'''---
cr_type: document
kind: {kind}
variant: {variant}
person: "[[Савва]]"
obtained: "{obtained}"
pages:
{"".join(pages)}---

{text}''', encoding="utf-8")
        return md

    def test_good_document_builds_pdf_in_date_order(self):
        md = self.write([page("a.jpg", "1894-07-04"), page("b.jpg", "1906-09-14")])
        self.assertIn("нет PDF — documents.py build", documents.problems(md))
        pdf = documents.build(md)
        self.assertTrue(pdf.read_bytes().startswith(b"%PDF"))
        self.assertEqual(documents.problems(md), [])

    def test_wrong_kind_order_and_missing_origin_are_reported(self):
        md = self.write([page("b.jpg", "1906"), page("a.jpg", "1894")], kind="passport-ish", obtained="")
        found = " | ".join(documents.problems(md))
        for part in ("не из списка", "не по датам", "obtained"):
            self.assertIn(part, found)

    def test_spreads_need_no_text_but_crops_do(self):
        crops = self.write([page("a.jpg", "1894")], text="")
        self.assertTrue(any("нет текста" in p for p in documents.problems(crops)))
        spreads = self.write([page("a.jpg", "1894")], variant="spreads", text="")
        self.assertFalse(any("нет текста" in p for p in documents.problems(spreads)))


if __name__ == "__main__":
    unittest.main()
