#!/usr/bin/env python3
"""Сторож публичного репозитория: личное семьи не должно попасть в ftree-app — ни в файл, ни в имя файла, ни в текст
коммита, ни в историю. Всё, что ушло в публичный git, разошлось навсегда: «убрать следующим коммитом» не помогает.

Что считается личным (словарь собирается из данных дерева, FTREE_ROOT, при каждом запуске — сам он личный, поэтому
нигде не хранится):
  имена     — слова из имён людей, имён их файлов (и в скобках: «Анна (Вербичи, жена Прокопа)») и вариантов (aliases):
              фамилии, имена, прозвища. Фамилии и места ловятся по основе — в любом падеже и регистре («Ясеневых»,
              «ВЕРБИЧЕЙ», «yasenevy»), кириллицей и латиницей (фамилия из латинской карточки — и по-русски);
  места     — слова из названий мест (деревни, улицы, дома) и их вариантов; улица с домом («Садовая, 12») — в любом
              написании, и в имени файла («Лесогорск_Садовая-12.jpg»);
  даты      — точные даты рождения живых (living.py: нет смерти, родился не раньше 110 лет назад) во всех записях:
              «1971-03-05», «05.03.1971», «5 марта 1971», «5 MAR 1971»;
  номера    — номера карточек (cr_id), номера GEDCOM (gedcom_id), номер нашего дерева на MyHeritage;
  контакты  — любой телефон, почта, адрес с номером дома, номер документа: и по виду (шаблоны ниже), и точные значения,
              найденные где угодно в данных (письма в архивы, анкеты, расшифровки) — их сторож тоже знает;
  запрет    — строки из setup/scan_deny.txt данных (то, чего в карточках нет: номера документов, старые адреса).
Не считается — общие слова из setup/scan_allow.txt данных (Минск, Беларусь, частые имена): сами по себе они никого не
выдают, а без списка сторож кричит на каждом шагу, и его начинают обходить.

  tools/py tools/scripts/scan_personal.py files <файл|папка>…   отчёт по файлам (код выхода 1 — что-то нашлось)
  tools/py tools/scripts/scan_personal.py app [N]                отчёт по будущему ftree-app — ровно по списку tools/APP_MANIFEST
                                                                 (rodo app-files); N — сколько мест напечатать (60)
  tools/py tools/scripts/scan_personal.py staged                 хук pre-commit в ftree-app: подготовленные файлы и имена
  tools/py tools/scripts/scan_personal.py message <файл>         хук commit-msg: текст коммита
  tools/py tools/scripts/scan_personal.py push <старый> <новый>  хук pre-push: каждый коммит, который уходит, — все
                                                                 файлы его дерева, имена и текст (старый = 000… — вся история)
  tools/py tools/scripts/scan_personal.py install <папка клона>  поставить хуки в клон ftree-app (в .git/hooks, не в git):
                                                                 этот сторож и gitleaks (leaks.py) — в pre-commit и pre-push

Найденное печатается с самим словом — на этом Mac; дальше этого экрана оно не уходит.
"""
from __future__ import annotations

import re
import subprocess
import sys
import unicodedata
import functools
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dates  # noqa: E402
import living  # noqa: E402
import paths  # noqa: E402

N = lambda s: unicodedata.normalize("NFC", s)  # noqa: E731
DENY_FILE = paths.setting_path("FTREE_SCAN_DENY", paths.ROOT / "setup" / "scan_deny.txt")
ALLOW_FILE = paths.setting_path("FTREE_SCAN_ALLOW", paths.ROOT / "setup" / "scan_allow.txt")
LOW_MIN = 6                      # слово дерева строчными ловим от 6 букв: «yasenev» в адресе — да, «нина» — нет
HANDLE_MIN = 5                   # внутри ссылки или ника — от 5 букв («prokop», «jasie»)
MIN_WORD = 4                     # короче — слишком часто совпадает с обычными словами («Ян», «Ира»)

# По виду — личное всегда, где бы ни встретилось
PATTERNS = {
    "телефон": re.compile(r"(?<![\w+])\+\d{1,3}[\s().-]*\d{2,4}[\s().-]*\d{2,4}[\s.-]*\d{2,4}(?:[\s.-]*\d{2,4})?(?!\w)"
                          r"|(?<![\w.:/-])\d{3}[- ]\d{2}[- ]\d{2}(?![\w.:/-])"),
    "почта": re.compile(r"[\w.%+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}"),
    "номер карточки": re.compile(r"\b[a-z]{3}-\d{3}-[a-z]{3}-\d{3}\b"),
    "номер GEDCOM": re.compile(r"(?<![\w@])@?I5\d{5,}@?(?!\w)"),
    "дерево MyHeritage": re.compile(r"\bOYYV[A-Z0-9]{27}\b"),
    "адрес с номером": re.compile(r"(?i)(?<!\w)(?:ул\.|улица|пер\.|пр-т|просп\.|ul\.|ulica|calle|av\.|avenida)\s*"
                                  r"[\w.-]+(?:\s[\w.-]+)?,?\s*(?:д\.\s*)?\d{1,4}(?:\s?[/-]\s?\d{1,4})?(?!\w)"),
    "индекс и город": re.compile(r"\b\d{2}-\d{3}\s+[A-ZŁŚŻŹ][a-ząćęłńóśźż]+"),
    "номер документа": re.compile(r"\b(?:[A-Z]{2}\d{7}|[A-Z]{3}\d{6}|\d{7}[A-Z]\d{3}[A-Z]{2}\d)\b"),
}
# что по виду похоже на личное, но не личное: адреса для примеров и служебные почты
NOT_PERSONAL = re.compile(r"noreply@|@example\.|@users\.noreply\.github\.com|git@github\.com|@anthropic\.com", re.I)
# номер карточки для тестов и примеров: в середине одна буква три раза («ppl-001-aaa-001»). Настоящие номера случайны,
# и каждый настоящий сторож всё равно знает точно (из карточек) — так что вымышленный вид ничего не прячет
FAKE_ID = re.compile(r"[a-z]{3}-\d{3}-([a-z])\1\1-\d{3}")
TEXT_EXT = {".py", ".mjs", ".js", ".ts", ".tsx", ".jsx", ".json", ".md", ".txt", ".toml", ".yml", ".yaml", ".sh", ".css",
            ".scss", ".html", ".svg", ".csv", ".tsv", ".swift", ".cfg", ".ini", ".lock", ".ged", ""}   # .ged — вымышленное дерево образца
# что входит в ftree-app — список tools/APP_MANIFEST (app_files.py): то же самое смотрят gitleaks и раздел на этапе 8


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[^\W\d_][\w'’-]*[^\W\d_]|[^\W\d_]", N(text)) if len(w) >= MIN_WORD}


def ordered_words(text: str) -> list[str]:
    """Слова по порядку (первое — имя, последнее — фамилия); words() — множество, порядка в нём нет."""
    return [w for w in re.findall(r"[^\W\d_][\w'’-]*[^\W\d_]|[^\W\d_]", N(text)) if len(w) >= MIN_WORD]


def lower_only(entry: str) -> bool:
    """Строка scan_allow вида «~петров»: общее слово, только когда и в тексте строчными («петров день»); с большой буквы
    (с большой буквы — фамилия) сторож его ловит."""
    return entry.startswith("~")


def read_list(path: Path) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [N(x.strip()) for x in lines if x.strip() and not x.lstrip().startswith("#")]


CYR = re.compile("[а-яёіў]", re.I)
# окончания, которые срезаем, чтобы найти основу слова: «Вербичи» → «вербич», «Лесное» → «лесн». Только гласные, «й» и
# «ь» — «-ов», «-ин» у фамилий не срезаем: «Ясенев» склоняется как «Ясенева», «Ясеневых», основа и так цела
ENDINGS = sorted(["ая", "яя", "ое", "ее", "ые", "ие", "ой", "ей", "ий", "ый", "ья", "ье", "ьи",
                  "а", "я", "ы", "и", "о", "е", "у", "ю", "ь", "й"], key=len, reverse=True)
STEM_MIN = 5                     # основа короче 5 букв — уже не слово рода, а начало десятка обычных слов
ID_SHAPE = re.compile(r"[a-z]{3}-\d{3}-[a-z]{3}-\d{3}|I?\d{5,}", re.I)   # номера карточек и GEDCOM — по виду, потом по словарю
TOKEN = re.compile(r"[^\W\d_]+(?:[-'’][^\W\d_]+)*")   # слово; «_», цифры и пробел — границы («Лесогорск_Садовая-12»)


def stem(word: str, least: int = STEM_MIN) -> str | None:
    """Основа кириллического слова дерева для поиска в любом падеже и регистре: «Ясенев» → «ясенев» (найдёт «Ясеневы»,
    «ЯСЕНЕВЫХ»), «Вербичи» → «вербич» («Вербичей»). Короче `least` букв или латиница — None."""
    w = word.lower()
    if not CYR.search(w) or len(w) < least:
        return None
    for e in ENDINGS:
        if w.endswith(e) and len(w) - len(e) >= least:
            return w[: -len(e)]
    return w


def name_stems(given, least: int = 4) -> set[str]:
    """Основы имён — по ним узнаём падежи и отчества: «Прокоп» → «прокоп», «Савелий» → «савел»; беглая
    гласная — двумя основами: «Лев» → «лев» и «льв» («Льва», «Львович»)."""
    out = set()
    for g in given:
        if s := stem(g, least):
            out.add(s)
            if re.search("[аеёо][лрнкц]$", s) and len(s) > least:
                out.add(s[:-2] + s[-1])
    return out


def prefix_in(token: str, table, least: int):
    """Самое длинное начало слова `token` (от `least` букв), которое есть в `table`, — или None."""
    for k in range(len(token), least - 1, -1):
        if token[:k] in table:
            return token[:k]
    return None


@dataclass
class Dictionary:
    words: dict[str, str]        # слово → «имя» | «место»
    exact: dict[str, str]        # строка → вид (номера, контакты из данных, запрет, даты живых)
    allow: set[str]
    low: set[str] = frozenset()  # что ловить и строчными: фамилии (последнее слово имени) и слова мест; не имена —
                                 # «григорий» строчными — общая таблица форм имён, а «yasenev» — адрес страницы
    addresses: dict[str, str] = field(default_factory=dict)   # «улица дом» из карточек мест → название места
    given: set[str] = frozenset()  # имена (первые слова имён людей): от их основы — отчества и фамилии-отчества

    @functools.cached_property
    def given_stems(self) -> set[str]:
        return name_stems(self.given)

    @functools.cached_property
    def stems(self) -> dict[str, str]:
        """Основа → слово дерева: фамилии и места кириллицей в любом падеже и регистре («Ясеневых», «ВЕРБИЧЕЙ»). Не
        берём слова от имён: «Прокопов», «Савельева», «Святого Савелия» — их основа («прокоп», «савел») встречается в
        таблицах имён и отчеств, в названиях праздников; с большой буквы и целиком такое слово сторож и так ловит."""
        out = {}
        common = {stem(a) for a in self.allow if not lower_only(a)}   # «Аргентина» в scan_allow — и «Аргентине» общее
        cyr = {v: w for w in self.low if not CYR.search(w) for v in to_cyrillic(w)}   # «Jasieniew» → «ясеневь»…
        for w in sorted(self.low) + sorted(cyr):
            s = stem(w)
            w = cyr.get(w, w)
            if not s or s in common or any(s.startswith(g) or g.startswith(s) for g in self.given_stems):
                continue
            out.setdefault(s, w)
            if re.search("(?:ец|ок|ек|ёк)$", s) and len(s) > STEM_MIN:   # беглая гласная: «Заречец» → «Заречца»
                out.setdefault(s[:-2] + s[-1], w)
        return out

    @functools.cached_property
    def lower_stems(self) -> set[str]:
        """Основы, общие только строчными («~высокий» в scan_allow: «высокое качество» — да, «Высокое» — нет)."""
        common = {a[1:].lower() for a in self.allow if lower_only(a)}
        return {s for s in self.stems if any(c.startswith(s) or stem(c) == s for c in common)}

    @functools.cached_property
    def latin(self) -> set[str]:
        """Фамилии и места латиницей — начало слова в любом регистре («Yasenev», «yasenevy», «JASIENIEW»): латинские как
        есть, кириллические — в ходовых транслитах. От LOW_MIN букв: короткие строчными — обычные слова."""
        out = set()
        given = {g.lower() for g in self.given}
        for w in self.low:
            if CYR.search(w):
                s = stem(w)
                forms = translit(s) if s in self.stems and s not in self.lower_stems else set()  # те же отборы
            else:
                forms = set() if w.lower() in given else {w.lower()}
            out |= {v for v in forms if len(v) >= LOW_MIN}
        return out

    @functools.cached_property
    def exact_rx(self):
        """Точные строки (номера, контакты, запрет, даты) — одним правилом, без учёта регистра; телефоны — отдельно."""
        alts = sorted((k for k, v in self.exact.items() if v != "телефон" and not ID_SHAPE.fullmatch(k)), key=len,
                      reverse=True)
        return re.compile(r"(?<!\d)(?:" + "|".join(map(re.escape, alts)) + r")(?!\d)", re.I) if alts else None

    @functools.cached_property
    def address_rx(self):
        """Улица и дом из карточки места в любом написании: «Садовая, 12», «Садовая-12», «садовая_12», «ул. Садовая
        д. 12». Номер дома без улицы — не личное («дом 12» есть у всех)."""
        alts = []
        for addr in self.addresses:
            street, num = addr.rsplit(" ", 1)
            alts.append(re.escape(street) + r"[\s,._-]*(?:д\.?\s*)?" + re.escape(num) + r"(?![\dа-яa-z])")
        return re.compile(r"(?<![^\W_])(?:" + "|".join(alts) + ")", re.I) if alts else None

    @functools.cached_property
    def rx(self):
        alts = sorted(self.words, key=len, reverse=True)
        # «_» и «-» — разделители: имена в именах файлов пишутся через подчёркивание («Иван_Ясенев_1878.jpg»), адрес —
        # через дефис («Лесогорск_Садовая-12»)
        return re.compile(r"(?<![^\W_])(" + "|".join(map(re.escape, alts)) + r")(?![^\W_])") if alts else None

    @functools.cached_property
    def handles(self) -> set[str]:
        """Фамилии и места строчными латиницей — для поиска ВНУТРИ ссылок и ников («instagram.com/annayasenev»,
        «linkedin.com/in/ivan-yasenev-123»): там слово склеено с именем, и границ слова нет. От HANDLE_MIN букв."""
        return {v for x in self.latin | {w.lower() for w in self.low if not CYR.search(w)}
                if len(v := re.sub(r"[^a-z]", "", x)) >= HANDLE_MIN}


_TR = dict(zip("абвгдеёзийклмнопрстуфхцчшщъыьэюяіў",
               ["a", "b", "v", "g", "d", "e", "e", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t", "u", "f",
                "kh", "ts", "ch", "sh", "shch", "", "y", "", "e", "yu", "ya", "i", "u"]))
# другие ходовые написания: польское и белорусская латинка («Ясенев» → jasieniew… , «Щука» → szczuka), упрощённое
# (h, c, ia) и английское без «k» перед «h» («Zharikov» и «Zarikov» — разные люди только для программы)
_TR_PL = {**_TR, "в": "w", "й": "j", "х": "ch", "ц": "c", "ч": "cz", "ш": "sz", "щ": "szcz", "ю": "ju", "я": "ja",
          "ж": "ż"}
_TR_SIMPLE = {**_TR, "х": "h", "ц": "c", "ю": "iu", "я": "ia", "й": "i", "ы": "i"}
SCHEMES = (_TR, _TR_PL, _TR_SIMPLE)


def translit(word: str) -> set[str]:
    """Кириллица → латиница в ходовых написаниях: «Ясенев» → {yasenev, jasenew, iasenev, …}; латиница — пусто."""
    w = word.lower()
    if not CYR.search(w):
        return set()
    out = set()
    for tr in SCHEMES:
        for zh in ("zh", "z", "ż"):
            v = "".join(tr.get(c, zh if c == "ж" else c) if c != "ж" else zh for c in w)
            out.add(v)
            out.add(unicodedata.normalize("NFKD", v).encode("ascii", "ignore").decode())   # «ż» → «z»
    return out


# латиница → кириллица: «Kleniuk» в карточке, «Кленюки» в тексте. Неоднозначные буквы — всеми вариантами
_RU = [("szcz", ["щ"]), ("sch", ["ш", "сх"]), ("shch", ["щ"]), ("sh", ["ш"]), ("ch", ["х", "ч"]), ("cz", ["ч"]),
       ("sz", ["ш"]), ("zh", ["ж"]), ("kh", ["х"]), ("ts", ["ц"]), ("rz", ["ж", "рз"]), ("ya", ["я"]), ("ja", ["я"]),
       ("ia", ["я", "иа"]), ("yu", ["ю"]), ("ju", ["ю"]), ("iu", ["ю"]), ("a", ["а"]), ("b", ["б"]), ("c", ["ц", "к"]),
       ("d", ["д"]), ("e", ["е", "э"]), ("f", ["ф"]), ("g", ["г"]), ("h", ["х", "г"]), ("i", ["и"]), ("j", ["й"]),
       ("k", ["к"]), ("l", ["л"]), ("ł", ["л"]), ("m", ["м"]), ("n", ["н"]), ("ń", ["нь"]), ("o", ["о"]), ("ó", ["у"]),
       ("p", ["п"]), ("r", ["р"]), ("s", ["с"]), ("ś", ["сь"]), ("t", ["т"]), ("u", ["у"]), ("v", ["в"]), ("w", ["в"]),
       ("x", ["кс"]), ("y", ["ы", "и", "й"]), ("z", ["з", "ж"]), ("ż", ["ж"]), ("ź", ["зь"]), ("ą", ["он"]),
       ("ę", ["ен"]), ("ć", ["ць"])]


def to_cyrillic(word: str, limit: int = 64) -> set[str]:
    """«Kleniuk» → {клениук, кленюк, …}: как фамилию из латинской карточки могут написать по-русски. Не больше
    `limit` вариантов; буква, которой нет в таблице, — слово не переводим."""
    w, out = word.lower(), [""]
    while w:
        for lat, cyr in _RU:
            if w.startswith(lat):
                out = [o + c for o in out for c in cyr][:limit]
                w = w[len(lat):]
                break
        else:
            return set()
    return set(out)


ESCAPE = re.compile(r"\\[ntr](?=[^\W\d_])")
URL_TOKEN = re.compile(r"[^\s\"'<>()\[\]`|]+")
URL_LIKE = re.compile(r"[/@]|\.(?:com|net|org|ar|pl|by|ru|ua|me|io|de)\b", re.I)


@cache
def dictionary() -> Dictionary:
    import cards
    tree = cards.load()
    allow = set(read_list(ALLOW_FILE))
    # «~слово» в scan_allow — общее только строчными (lower_only): из словаря дерева оно не выпадает
    allow_low = {a.lower() for a in allow if not lower_only(a)}
    w: dict[str, str] = {}
    low: set[str] = set()
    given: set[str] = set()
    places: set[str] = set()   # первые слова имён — имена: строчными это общая таблица форм имён, а не человек
    cands: set[str] = set()
    surnames: set[str] = set()
    for p in tree.people.values():   # заголовок карточки — «Имя Фамилия»: первое слово — имя (в aliases бывает и
        for title in {p.name, p.stem}:   # «Фамилия Имя», поэтому имена берём только из заголовков)
            main = re.findall(r"[^\W\d_][\w'’-]*", re.sub(r"\(.*?\)", " ", N(title)))   # и короткие: «Нил», «Ян»
            if main and main[0][0].isupper():
                given.add(main[0])
            if len(main) > 1:
                surnames.add(main[-1])
    given -= surnames   # «Ясенев (сын Анны)» — первое слово, но фамилия: в другом заголовке оно последнее
    given_stems = name_stems(given)

    short = name_stems(given, 3)

    def name_form(x: str) -> bool:
        """«Прокопа», «Анны» («сын Прокопа», «Муж Анны Ясеневой») — падеж имени, а не фамилия."""
        s = stem(x, 3)
        return x not in given and bool(s) and any(s.startswith(g) and len(s) - len(g) <= 2 for g in short)

    for p in tree.people.values():
        for name in [p.name, p.stem, *map(str, p.fm.get("aliases") or [])]:
            # «Ясе[н?]ев» — догадка чтения в скобках: слово целиком, без неё («Ясеев»), а не «Ясе»
            name = re.sub(r"\[[^\]]*\]", "", N(name))
            main = [x for x in ordered_words(re.sub(r"\(.*?\)", " ", name)) if x[0].isupper()]
            # в скобках имени файла — деревня, муж, мать: «Анна (Вербичи, жена Прокопа Ясенева)» — тоже слова дерева
            extra = [x for x in words(" ".join(re.findall(r"\((.*?)\)", name))) if x[0].isupper()]
            for x in main + extra:
                if x.lower() not in allow_low and not name_form(x):
                    w.setdefault(x, "имя")
                    cands.add(x)
    given_low = {g.lower() for g in given}
    low |= {x for x in cands if x.lower() not in given_low}
    for pl in tree.places.values():
        for name in [pl.name, pl.stem, *map(str, pl.aliases or [])]:
            for x in words(re.sub(r"\(.*?\)", " ", name) + " " + " ".join(re.findall(r"\((.*?)\)", name))):
                if x[0].isupper() and x.lower() not in allow_low:
                    w.setdefault(x, "место")
                    places.add(x)
    exact: dict[str, str] = {}
    for p in tree.people.values():
        exact[p.id] = "номер карточки"
        if p.fm.get("gedcom_id"):
            exact[str(p.fm["gedcom_id"]).strip("@")] = "номер GEDCOM"
    for pl in tree.places.values():
        exact[pl.id] = "номер карточки"
    if paths.MYHERITAGE_SITE:
        exact[paths.MYHERITAGE_SITE] = "дерево MyHeritage"
    for kind, value in contacts_in_data():
        exact.setdefault(value, kind)
    for p in tree.people.values():
        for when in (p.born, p.died):
            if when and living.is_living(p.born, p.died):
                for form in date_forms(when):
                    exact.setdefault(form, "дата живого")
    addresses = {}
    for pl in tree.places.values():
        for name in [pl.name, pl.stem, *map(str, pl.aliases or []), *map(str, as_list(pl.fm.get("photos")))]:
            for street, num in ADDRESS_IN_NAME.findall(N(name)):   # и общая улица: «Садовая, 12» — уже адрес
                addresses.setdefault(f"{street} {num}", pl.name)
    for x in read_list(DENY_FILE):
        exact[x] = "запрет (scan_deny)"
        if re.fullmatch(r"[^\W\d_][\w'’-]*", x) and len(x) >= STEM_MIN:   # одно слово — и в любом падеже («Лесное» → «Лесного»)
            places.add(x)
    return Dictionary(w, {k: v for k, v in exact.items() if len(k) >= MIN_WORD}, allow, (low | places) - given,
                      addresses, given)


# «Лесогорск — Садовая, 12», «Вербичи — Луговая, 3А», «Лесогорск_Садовая-12» (начало имён снимков в «photos:» места)
ADDRESS_IN_NAME = re.compile(r"(?:—|_|^)\s*([^\W\d_][\w.’'-]*?[^\W\d_](?:\s[^\W\d_][\w’'-]*)?)[\s,_-]+(\d{1,4}[а-яa-z]?"
                             r"(?:к\d)?)(?![\d])", re.I)


def as_list(v):
    return [] if v is None else v if isinstance(v, list) else [v]


def date_forms(g) -> set[str]:
    """Точная дата (с днём) во всех ходовых записях: «1971-03-05», «05.03.1971», «5.3.1971», «05.03.71», «5 марта 1971»,
    «5 MAR 1971», «05/03/1971», «03/05/1971». Без дня — ничего: год и месяц сами по себе никого не выдают."""
    day = getattr(g, "a", None)
    if not (day and day.d) or g.kind not in ("", "FROM", "TO"):
        return set()
    y, m, d = day.y, day.m, day.d
    return {f"{y}-{m:02d}-{d:02d}", f"{d:02d}.{m:02d}.{y}", f"{d}.{m}.{y}", f"{d:02d}.{m:02d}.{y % 100:02d}",
            f"{d} {dates.MONTHS_GEN[m - 1]} {y}", f"{d:02d} {dates.MONTHS_GEN[m - 1]} {y}",
            f"{d} {dates.MONTHS_GED[m - 1]} {y}", f"{d:02d} {dates.MONTHS_GED[m - 1]} {y}",
            f"{d:02d}/{m:02d}/{y}", f"{m:02d}/{d:02d}/{y}", f"{y}{m:02d}{d:02d}"}


def contacts_in_data():
    """Телефоны, почты, адреса и номера документов, которые где-то в данных уже записаны (письма, анкеты), — точными
    значениями: так сторож узнает их и в другом написании (без «+», с другими пробелами)."""
    out = subprocess.run(["git", "-C", str(paths.ROOT), "grep", "-hoIE",
                          r"\+[0-9]{2,3}[ ()0-9-]{7,}[0-9]|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
                          "--", ":!tools", ":!web", ":!.claude"], capture_output=True, text=True).stdout
    # адреса в записи «улица дом piso/depto» и «ул. Улица, дом» из карточек и писем: «Arenales 1234 piso 5» → «Arenales 1234»
    addr = subprocess.run(["git", "-C", str(paths.ROOT), "grep", "-hoIE",
                           r"[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ]+ [0-9]{2,5},? (piso|depto|dpto)",
                           "--", ":!tools", ":!web", ":!.claude"], capture_output=True, text=True).stdout
    for v in set(addr.splitlines()):
        yield "адрес из данных", re.sub(r",? (piso|depto|dpto)$", "", v)
    for v in set(out.splitlines()):
        if "@" in v:
            if not NOT_PERSONAL.search(v):
                yield "почта", N(v)
        else:
            digits = re.sub(r"\D", "", v)
            if len(digits) >= 9:
                yield "телефон", digits


@dataclass
class Hit:
    where: str
    line: int
    kind: str
    what: str


def scan_text(where: str, text: str) -> list[Hit]:
    d = dictionary()
    text = N(text)
    hits = []
    rx, handles, xrx, arx = d.rx, d.handles, d.exact_rx, d.address_rx
    stems, latin, lower_stems = d.stems, d.latin, d.lower_stems
    exact_low = {k.lower(): v for k, v in d.exact.items()}
    allow_low = {a.lower() for a in d.allow if not lower_only(a)}
    allow_lower_words = {a[1:].lower() for a in d.allow if lower_only(a)}
    phones = {k for k, v in d.exact.items() if v == "телефон"}
    # строка из нескольких слов в scan_allow — общее только целиком: «Ivan Yasenev» (например, автор приложения) не считается,
    # а та же фамилия при другом имени — считается
    phrases = [re.compile(re.escape(a), re.I) for a in d.allow if " " in a.strip() and not lower_only(a)]

    def common(word: str) -> bool:
        w = word.lower()
        return w in allow_low or (w in allow_lower_words and word.islower())

    for i, line in enumerate(text.splitlines() or [text], 1):
        line = ESCAPE.sub("  ", line)   # «\\tЯсенев» в строке кода — «\\t» не часть слова
        for prx in phrases:
            line = prx.sub(" ", line)
        for kind, prx in PATTERNS.items():
            for m in prx.finditer(line):
                if kind == "номер карточки" and FAKE_ID.fullmatch(m.group(0)):
                    continue
                if not NOT_PERSONAL.search(m.group(0)) and m.group(0).lower() not in allow_low:
                    hits.append(Hit(where, i, kind, m.group(0)))
        if rx:
            for m in rx.finditer(line):
                hits.append(Hit(where, i, d.words[m.group(1)], m.group(1)))
        # фамилия или место — начало слова в любом падеже и регистре: «Ясеневых», «ВЕРБИЧЕЙ», «yasenevy», «Jasieniew»;
        # слово через дефис — и целиком, и по частям
        for m in TOKEN.finditer(line):
            whole = m.group(0)
            for tok in dict.fromkeys([whole, *re.split(r"[-'’]", whole)]):
                t = tok.lower()
                if CYR.search(t):
                    s = prefix_in(t, stems, STEM_MIN)
                    if s and not common(tok) and not (s in lower_stems and tok.islower()):
                        hits.append(Hit(where, i, "основа: " + stems[s], tok))
                elif (s := prefix_in(t, latin, LOW_MIN)) and not common(tok) and s not in allow_low:
                    hits.append(Hit(where, i, "латиницей", tok))
        for tok in URL_TOKEN.findall(line):
            if URL_LIKE.search(tok):
                t = tok.lower()
                for f in handles:
                    if f in t and f not in allow_low and f not in allow_lower_words:
                        hits.append(Hit(where, i, "в ссылке", f))
        if arx:
            for m in arx.finditer(line):
                hits.append(Hit(where, i, "адрес из карточки", m.group(0)))
        if xrx:
            for m in xrx.finditer(line):
                value = m.group(0).lower()
                if value not in allow_low:   # общее (почта организации) — в scan_allow
                    hits.append(Hit(where, i, exact_low.get(value, "точное значение"), m.group(0)))
        for m in ID_SHAPE.finditer(line):
            if (kind := exact_low.get(m.group(0).lower())) and kind != "телефон":
                hits.append(Hit(where, i, kind, m.group(0)))
        digits = re.sub(r"\D", "", line)
        for ph in phones:
            if ph[-9:] in digits:
                hits.append(Hit(where, i, "телефон", ph[:3] + "…"))
    seen, out = set(), []
    for h in hits:
        if (h.line, h.what.lower()) not in seen:
            seen.add((h.line, h.what.lower()))
            out.append(h)
    return out


def scan_name(path: str) -> list[Hit]:
    return [Hit(path, 0, "имя файла: " + h.kind, h.what) for h in scan_text(path, path.replace("/", " / ").replace("_", " "))]


def is_text(path: str, data: bytes) -> bool:
    return Path(path).suffix.lower() in TEXT_EXT and b"\0" not in data[:8000]


def scan_blob(path: str, data: bytes) -> list[Hit]:
    hits = scan_name(path)
    if is_text(path, data):
        hits += scan_text(path, data.decode("utf-8", errors="replace"))
    return hits


def report(hits: list[Hit], limit: int = 400) -> int:
    if not hits:
        print("🛡 Личного не найдено.")
        return 0
    by_kind: dict[str, int] = {}
    for h in hits:
        by_kind[h.kind] = by_kind.get(h.kind, 0) + 1
    for h in hits[:limit]:
        print(f"  {h.where}{':' + str(h.line) if h.line else ''} — {h.kind}: {h.what}")
    if len(hits) > limit:
        print(f"  … и ещё {len(hits) - limit}")
    files = len({h.where for h in hits})
    print(f"⛔ Личное: {len(hits)} мест в {files} файлах — " + ", ".join(f"{k} {v}" for k, v in sorted(by_kind.items(), key=lambda x: -x[1])))
    print("   Убрать или заменить вымышленным; общее слово, которое никого не выдаёт, — в setup/scan_allow.txt данных.")
    return 1


def git(*args, cwd=None, text=True):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=text, check=True).stdout


def files_under(targets) -> list[Path]:
    out = []
    for t in map(Path, targets):
        out += [p for p in t.rglob("*") if p.is_file()] if t.is_dir() else [t]
    return out


def cmd_files(targets, base: Path | None = None) -> int:
    hits = []
    for p in files_under(targets):
        rel = N(p.relative_to(base).as_posix()) if base else N(str(p))
        hits += scan_blob(rel, p.read_bytes())
    return report(hits)


def cmd_app() -> int:
    import app_files
    hits = []
    for rel in app_files.files():
        hits += scan_blob(rel, (paths.APP / rel).read_bytes())
    return report(hits, limit=int(dict(enumerate(sys.argv)).get(2, 60)))


def cmd_staged() -> int:
    names = git("-c", "core.quotepath=false", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").split("\0")
    hits = []
    for rel in filter(None, names):
        hits += scan_blob(N(rel), subprocess.run(["git", "show", f":{rel}"], capture_output=True, check=True).stdout)
    return report(hits)


def cmd_message(path: str) -> int:
    text = "\n".join(x for x in Path(path).read_text(encoding="utf-8").splitlines() if not x.startswith("#"))
    return report(scan_text("текст коммита", text))


def cmd_push(old: str, new: str) -> int:
    """Всё, что уходит: каждый новый коммит — текст и всё его дерево (файлы, которые потом удалили, тоже уходят)."""
    rng = new if set(old) <= {"0"} else f"{old}..{new}"
    hits, seen = [], set()
    for sha in filter(None, git("rev-list", rng).split()):
        hits += scan_text(f"текст коммита {sha[:7]}", git("log", "-1", "--format=%B", sha))
        for row in git("-c", "core.quotepath=false", "ls-tree", "-r", "-z", sha).split("\0"):
            if not row:
                continue
            meta, path = row.split("\t", 1)
            blob = meta.split()[2]
            if (blob, path) in seen:
                continue
            seen.add((blob, path))
            hits += [Hit(f"{sha[:7]}:{h.where}", h.line, h.kind, h.what)
                     for h in scan_blob(N(path), subprocess.run(["git", "cat-file", "blob", blob], capture_output=True,
                                                                check=True).stdout)]
    return report(hits)


HOOK = """#!/bin/sh
# Сторож личного (ftree, tools/scripts/scan_personal.py) и gitleaks (пароли, ключи — tools/scripts/leaks.py) — поставлены
# `scan_personal.py install`, в git не хранятся. Обойти (--no-verify) нельзя молча: pre-push проверяет всё, что уходит, ещё раз.
{body}
"""
BODIES = {
    "pre-commit": '"{py}" "{script}" staged || exit 1\nexec "{py}" "{leaks}" staged',
    "commit-msg": 'exec "{py}" "{script}" message "$1"',
    "pre-push": 'exec "{py}" "{script}" push-stdin',   # и gitleaks по тем же коммитам — внутри push-stdin
}


def cmd_install(clone: str) -> int:
    hooks = Path(clone).expanduser().resolve() / ".git" / "hooks"
    if not hooks.is_dir():
        raise SystemExit(f"нет {hooks}: это не клон git")
    here = Path(__file__).resolve()
    for name, body in BODIES.items():
        f = hooks / name
        f.write_text(HOOK.format(body=body.format(py=paths.PY, script=here, leaks=here.with_name("leaks.py"))),
                     encoding="utf-8")
        f.chmod(0o755)
        print(f"✅ {f}")
    return 0


def cmd_push_stdin() -> int:
    """pre-push получает на вход строки «<местная ссылка> <новый> <удалённая ссылка> <старый>». Те же коммиты — ещё и
    gitleaks (пароли и ключи): после --no-verify у pre-commit это последняя проверка."""
    import leaks
    code = 0
    for line in sys.stdin:
        parts = line.split()
        if len(parts) == 4 and not set(parts[1]) <= {"0"}:
            code |= cmd_push(parts[3], parts[1])
            code |= leaks.run(["git", "--log-opts=" + (parts[1] if set(parts[3]) <= {"0"} else f"{parts[3]}..{parts[1]}"), "."])
    return code


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    mode, rest = argv[0], argv[1:]
    if mode == "files":
        return cmd_files(rest or ["."])
    if mode == "app":
        return cmd_app()
    if mode == "staged":
        return cmd_staged()
    if mode == "message":
        return cmd_message(rest[0])
    if mode == "push":
        return cmd_push(*rest[:2])
    if mode == "push-stdin":
        return cmd_push_stdin()
    if mode == "install":
        return cmd_install(rest[0])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
