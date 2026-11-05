"""Что получается из карточек. Имена полей — как в web/schema/ (там же — откуда каждое берётся)."""
from dataclasses import dataclass, field

from dates import GDate


@dataclass
class Problem:
    """Запись в карточке не по правилам. error — сборка сайта останавливается; warning — показываем, но собираем."""
    card: str          # путь карточки от корня проекта
    line: int | None   # строка файла
    message: str       # что не так — по-человечески
    text: str = ""     # сама строка (или её начало)
    level: str = "error"

    def __str__(self):
        where = f"{self.card}:{self.line}" if self.line else self.card
        mark = "" if self.level == "error" else "(предупреждение) "
        return f"{where} — {mark}{self.message}" + (f"\n    {self.text[:200]}" if self.text else "")


@dataclass
class SourceRef:
    source: str        # cr_id карточки источника
    locator: str = ""  # где в источнике: «стр. 12», «10:01», «MAZ.by, просмотрено 27.06.2026»


@dataclass
class Fact:
    line: int
    text: str
    refs: list[SourceRef]
    confidence: str            # high | normal | low
    provenance: str            # family | found | other_tree | inference
    date: GDate | None = None  # дата в начале подписи («1944 (осень), 13 лет» → 1944 (осень))
    label: str = ""            # подпись без даты («Занятие», «13 лет»)
    reasoning: str = ""        # на чём держится: текст в скобках после уверенности


@dataclass
class Source:
    id: str
    stem: str
    title: str
    provenance: str
    type: str
    author: str = ""
    repository: str = ""
    fm: dict = field(default_factory=dict, repr=False)
    body: str = field(default="", repr=False)


@dataclass
class State:
    """Строка «Государства по годам»: «1921–1939 — **Польша** (II Речь Посполитая)»."""
    date: GDate
    label: str
    main: bool = False  # выделено жирным — главная эпоха для нашей истории


@dataclass
class Place:
    id: str
    stem: str
    name: str
    type: str
    real: bool
    aliases: list[str]
    parent: str | None                 # cr_id места выше (деревня → страна)
    coords: tuple[float, float] | None
    states: list[State]
    fm: dict = field(default_factory=dict, repr=False)
    body: str = field(default="", repr=False)
    card: str = ""                     # путь карточки от корня проекта — для сообщений проверок
    house: dict | None = None          # дом: {"kind", "built", "gone"} (cards/houses.py); не дом — None


@dataclass
class Person:
    id: str
    stem: str
    name: str
    sex: str                     # M | F
    born: GDate | None
    died: GDate | None
    birth_place: str | None      # cr_id места
    death_place: str | None
    father: list[str]            # cr_id; не больше одного
    mother: list[str]
    spouses: list[str]
    children: list[str]
    sources: list[str]           # cr_id источников из свойства sources
    facts: list[Fact]
    fm: dict = field(default_factory=dict, repr=False)
    body: str = field(default="", repr=False)
    possible: list = field(default_factory=list)   # possible.Possible: «возможно, тот же / родня» — с обеих сторон
    ruled_out: set = field(default_factory=set)    # {("same"|"kin", cr_id)}: проверено — нет (not_same / not_kin)


@dataclass
class Tree:
    people: dict[str, Person]    # cr_id → человек
    places: dict[str, Place]
    sources: dict[str, Source]
    events: list[dict]           # свойства карточек событий как есть
    divorces: dict[frozenset, int | None]  # пара → год развода
    problems: list[Problem]
    biographies: dict[str, str | None] = field(default_factory=dict)  # путь биографии → cr_id хозяина (None — файл рода)
    residents: dict = field(default_factory=dict)  # cr_id дома → [houses.Resident]: кто в нём жил, по году

    @property
    def errors(self):
        return [p for p in self.problems if p.level == "error"]

    def ruled_out(self, a, b, kind=None):
        """Пару a–b уже проверили и сказали «нет» (not_same / not_kin, в любой из двух карточек) — не предлагать снова.
        kind — "same" или "kin"; без него — любое «нет»."""
        out = self.people[a].ruled_out if a in self.people else set()
        return any(i == b and (kind is None or k == kind) for k, i in out)

    def person(self, stem):
        return next((p for p in self.people.values() if p.stem == stem), None)
