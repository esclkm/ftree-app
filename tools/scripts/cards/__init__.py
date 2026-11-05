"""Карточки дерева как данные — первый слой всех скриптов.

Проект идёт по одной цепочке: источник → расшифровка → карточка → сайт. Этот пакет — звено «карточка»: он читает
3_research/tree (людей, места, источники, события) и отдаёт объекты с понятными полями. Про сайт, HTML и JSON он не
знает ничего — это следующий слой, site_data.

Всё, что в карточке записано не по правилам, попадает в tree.problems — с карточкой, строкой и тем, что не так.
Правила записи — навык card-rules (.claude/skills/card-rules) и <папка поиска>/biographies/00_ИНДЕКС.md; схема того, что из них
получается, — web/schema/.

  import cards
  tree = cards.load()
  tree.people["ppl-001-aaa-001"].facts[0].date.ru()   # «1852»
  for p in tree.problems: print(p)

Модули — в том порядке, в каком идёт чтение:
  notes    — файл .md → свойства (frontmatter) и текст; ссылки [[…]]
  model    — что получается: Person, Place, Source, Fact, Problem, Tree
  sources  — карточки источников (их читаем первыми: на них ссылаются факты)
  places   — карточки мест и «Государства по годам»
  facts    — строки «Факты (с источником)»
  people   — карточки людей и связи между ними
  possible — «возможно, тот же человек / родня» и проверенное «нет» (maybe_*, not_*), с обеих сторон
  layout   — разделы карточки по образцу: порядок, что где лежит; fix() — механическая правка
  biographies — чья биография и под какими номерами (person_id, gedcom_id в свойствах)
  tree     — load(): всё вместе
"""
from .model import Fact, Person, Place, Problem, Source, SourceRef, State, Tree  # noqa: F401
from .tree import load  # noqa: F401
