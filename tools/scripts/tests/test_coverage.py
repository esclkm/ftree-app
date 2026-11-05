import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец, не живое (tests/sample_tree.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import coverage  # noqa: E402
from cards.model import Fact, SourceRef  # noqa: E402
from dates import parse_card as parse  # noqa: E402

SOURCES = {
    "metric": NS(stem="ГАСО — метрики Рождественского, 1894", type="church_record", provenance="found", fm={}),
    "anketa": NS(stem="Анкета (личный листок) — Галина Ясенева (1981)", type="custom", provenance="family", fm={}),
    "audio": NS(stem="Аудио 04 — дед Прокоп Дубняк", type="custom", provenance="family", fm={}),
    "our": NS(stem="Jasieniew Web Site", type="custom", provenance="other_tree", fm={"our_tree": True}),
    "other": NS(stem="Geni World Family Tree", type="custom", provenance="other_tree", fm={}),
    "web": NS(stem="Интернет-находки (открытые источники, реестры, пресса)", type="custom", provenance="found", fm={}),
}
TREE = NS(sources=SOURCES, people={})


def fact(text, src="metric", label="", prov="found", date=None, reasoning=""):
    return Fact(line=1, text=text, refs=[SourceRef(src)], confidence="normal", provenance=prov, label=label,
                date=parse(date) if date else None, reasoning=reasoning)


class KindTest(unittest.TestCase):
    def test_source_kinds(self):
        self.assertEqual(coverage.source_kind(SOURCES["metric"]), "record")
        self.assertEqual(coverage.source_kind(SOURCES["anketa"]), "doc")
        self.assertEqual(coverage.source_kind(SOURCES["audio"]), "family")
        self.assertEqual(coverage.source_kind(SOURCES["our"]), "tree")
        self.assertEqual(coverage.source_kind(SOURCES["other"]), "other_tree")
        self.assertEqual(coverage.source_kind(SOURCES["web"]), "web")

    def test_family_words_with_web_pointer_are_not_document(self):
        f = Fact(line=1, text="похоронен на кладбище «Липки» (от отца)", refs=[SourceRef("audio"), SourceRef("web")],
                 confidence="normal", provenance="family", label="Похоронен")
        self.assertEqual(coverage.fact_kind(TREE, f), "family")
        self.assertEqual(coverage.doc_refs(TREE, f), set())

    def test_derived_is_inference_even_from_metric(self):
        f = fact("около 1861 — вычислен из возраста 48 лет при смерти", label="Год рождения")
        self.assertEqual(coverage.fact_kind(TREE, f), "inference")


class EventTest(unittest.TestCase):
    def test_own_events(self):
        self.assertEqual(coverage.events_of(fact("родился в д. Вербичи")), {"birth"})
        self.assertEqual(coverage.events_of(fact("умер (рак); похоронен на кладбище «Кленовка»")), {"death"})
        self.assertEqual(coverage.events_of(fact("женился на Феодоре")), {"marriage"})
        self.assertEqual(coverage.events_of(fact("Кленовское кладбище", label="Могила")), {"death"})

    def test_not_own_events(self):
        self.assertEqual(coverage.events_of(fact("мать Антонины: «урождённой Шашиловой»")), set())
        self.assertEqual(coverage.events_of(fact("трое детей, двое умерли до войны")), set())
        self.assertEqual(coverage.events_of(fact("поручитель по невесте на свадьбе Корнилия")), set())
        self.assertEqual(coverage.events_of(fact("отец Антония (родился 10.07.1857)")), set())
        self.assertEqual(coverage.events_of(fact("доказано — метрика 1894 года", label="Родство")), set())
        self.assertEqual(coverage.events_of(fact("родился сын Георгий")), set())


def person(pid, name, born=None, died=None, facts=(), spouses=(), children=(), father=(), mother=()):
    return NS(id=pid, stem=name, name=name, born=parse(born) if born else None, died=parse(died) if died else None,
              facts=list(facts), spouses=list(spouses), children=list(children), father=list(father),
              mother=list(mother), birth_place=None, fm={})


class CoverageTest(unittest.TestCase):
    def setUp(self):
        self.kid = person("k", "Леонид Ясенев", "1919", "1920", father=["s"])
        self.wife = person("w", "Пелагея Ольховская", "1901", spouses=["s"],
                           facts=[fact("вышла замуж за [[Иван Ясенев|Ивана]] — ЗАГС", date="1918")])
        self.man = person("s", "Иван Ясенев", "1894", "1973", spouses=["w"], children=["k"], facts=[
            fact("родился Иван, крещён 5 июля", label="4 июля 1894 (ст. ст.)"),
            fact("год рождения в анкете дочери — «1894»", src="anketa", date="1894"),
            fact("родился сын [[Леонид Ясенев|Леонид]]", date="1919"),
            fact("умер; похоронен в Минске", src="audio", prov="family", date="1973"),
            fact("призван в гвардию", src="audio", prov="family", date="1914"),
        ])
        self.tree = NS(sources=SOURCES, people={p.id: p for p in (self.man, self.wife, self.kid)})
        self.cov = coverage.Coverage(self.tree)

    def test_birth_two_documents(self):
        self.assertEqual(coverage.summary(self.tree, self.cov.birth(self.man)), ("record", 2))

    def test_death_family_only(self):
        self.assertEqual(coverage.summary(self.tree, self.cov.death(self.man)), ("family", 0))

    def test_marriage_from_spouse_card(self):
        (sp, ev), = self.cov.marriages(self.man)
        self.assertIs(sp, self.wife)
        self.assertEqual(coverage.summary(self.tree, ev)[0], "record")

    def test_child_birth_from_parent_card(self):
        self.assertEqual(coverage.summary(self.tree, self.cov.birth(self.kid))[0], "record")
        self.assertNotIn(self.man.facts[2], [f for _, f in self.cov.birth(self.man)])

    def test_alive_no_death_gap(self):
        self.assertEqual(coverage.cell(None, 0, coverage.alive(person("g", "Галина", "1937"))), "·")
        self.assertEqual(coverage.cell(None, 0, coverage.alive(person("x", "Прокоп", "1902"))), "✖")


if __name__ == "__main__":
    unittest.main()
