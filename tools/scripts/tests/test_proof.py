import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import proof  # noqa: E402
from cards.model import Fact, SourceRef  # noqa: E402


def fact(text, prov="found", label="рождение", conf="normal", src="s1"):
    return Fact(line=1, text=text, refs=[SourceRef(src)], confidence=conf, provenance=prov, label=label)


TREE = NS(sources={"s1": NS(stem="Метрики", fm={}), "our": NS(stem="Jasieniew Web Site", fm={"our_tree": True})})
CHILD = NS(name="Евстафий Дубняк", stem="Стах Дубняк")
PARENT = NS(name="Прокоп Дубняк", stem="Прокоп Дубняк")


class KindTest(unittest.TestCase):
    def test_birth_record_in_child_card_is_document(self):
        f = fact("родители — Прокоп Николаев Дубняк и Мелания Саввишна")
        self.assertEqual(proof.kind_of(TREE, CHILD, f, CHILD), "doc")

    def test_patronymic_in_marriage_is_inference(self):
        f = fact("«Вавила Акимов Осокин», 22 года", label="брак")
        self.assertEqual(proof.kind_of(TREE, CHILD, f, CHILD), "inference")

    def test_parents_own_birth_is_not_document_for_child(self):
        f = fact("сын крестьян Савелия и Евдокии", label="рождение")
        self.assertEqual(proof.kind_of(TREE, PARENT, f, CHILD), "inference")

    def test_derived_words_make_inference(self):
        f = fact("отец — по отчеству Прокоп", label="рождение")
        self.assertEqual(proof.kind_of(TREE, CHILD, f, CHILD), "inference")

    def test_family_and_old_tree(self):
        self.assertEqual(proof.kind_of(TREE, CHILD, fact("отец Прокоп", prov="family", label="отец"), CHILD), "family")
        self.assertEqual(proof.kind_of(TREE, CHILD, fact("отец", prov="other_tree", src="our"), CHILD), "tree")
        self.assertEqual(proof.kind_of(TREE, CHILD, fact("отец", prov="other_tree"), CHILD), "other_tree")


if __name__ == "__main__":
    unittest.main()
