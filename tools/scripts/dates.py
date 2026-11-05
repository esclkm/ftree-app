#!/usr/bin/env python3
"""Даты проекта — по образцу GEDCOM (формат родословных, в нём MyHeritage и Charted Roots). Правило — CLAUDE.md,
«Даты — как в GEDCOM»; подробно с примерами — <папка поиска>/biographies/00_ИНДЕКС.md, «Как писать даты».

Видов даты немного, и у каждого — одна запись в карточке и одна по-русски в таблице «Линия жизни»:

  вид                     карточка (born, died, date)   таблица «Линия жизни»        GEDCOM (выгрузка)
  точно                   1935 · 1935-05 · 1935-05-12    1935 · май 1935 · 12.05.1935  1935 · MAY 1935 · 12 MAY 1935
  около                   ABT 1935                       ок. 1935                      ABT 1935
  вычислено (из возраста) CAL 1935                       расч. 1935                    CAL 1935
  оценка (по другим датам) EST 1935                      оцен. 1935                    EST 1935
  до / после              BEF 1944 · AFT 1944            до 1944 · после 1944          BEF 1944 · AFT 1944
  один раз, где-то между  BET 1941 AND 1945              между 1941 и 1945             BET 1941 AND 1945
    — десятилетие         BET 1950 AND 1959              1950-е                        BET 1950 AND 1959
  всё это время           FROM 1941 TO 1945              1941–1945                     FROM 1941 TO 1945
    — десятилетия         FROM 1960 TO 1979              1960-е–1970-е                 FROM 1960 TO 1979
  с / по                  FROM 1944 · TO 1950            с 1944 · по 1950              FROM 1944 · TO 1950

Месяц после «ок.», «до», «после», «с» — в родительном («до мая 1944»), после «между» — в творительном («между маем
1944 и июнем 1945»); разбор понимает любой падеж, --fix в check_dates.py пишет как принято.
В таблице к любой дате можно дописать слова из источника в скобках: «1945 (после войны)», «между 1944 и 1950
(детство)» — сама дата остаётся, слова — пояснение (в GEDCOM — INT 1945 (после войны)). Даты нет и оценить нечем —
одни слова: «(без даты)» (в GEDCOM так тоже можно). Звёздочки, ⭐ ⚠️ ❓ и **жирный** вокруг даты — оформление,
разбору не мешают. В карточке — только сама дата: без слов и без стиля.

Два календаря (Павел, 20.10.2026): главная дата везде — по НОВОМУ стилю (григорианскому): в карточке, в линии жизни,
на сайте, в сортировке и возрасте. Дату из документа по старому стилю (юлианскому; Россия — до 31.01.1918 включительно,
православные метрики) пишем рядом в скобках: «25.06.1888 (13.06.1888 ст. ст.)» — сайт показывает её мелко. Перевод —
только julian_to_gregorian(): +12 дней в XIX веке, +13 с 1 марта 1900. Старая запись «13.06.1888 ст. ст.» (главная дата —
по старому стилю) читается, но check_dates.py --fix переводит её в новую форму. Год или месяц без дня не переводим.

Возраст и праздники (навык dates): birth_from_age(45, 1897) → BET 1851 AND 1852 и широкое BET 1849 AND 1854;
ages_agree((45, 1897), (50, 1905)) → (3, «норма»); estimate_birth(father=1850, eldest_child=1895) — оценка по родне;
feast_date("на Покров", 1888) → 13.10.1888 (01.10.1888 ст. ст.); orthodox_easter(1888), catholic_easter(1888).

  import dates
  g = dates.parse_card("BET 1941 AND 1945")   # или dates.parse_ru("между 1941 и 1945")
  g.ru(), g.card(), g.gedcom(), g.first_year, g.sort_key()
"""
import datetime
import re
from dataclasses import dataclass

MONTHS_RU = ("январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь",
             "ноябрь", "декабрь")
MONTHS_GEN = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
              "ноября", "декабря")      # «до мая 1944», «после мая», «с мая», «ок. мая»
MONTHS_INS = ("январём", "февралём", "мартом", "апрелем", "маем", "июнем", "июлем", "августом", "сентябрём",
              "октябрём", "ноябрём", "декабрём")  # «между маем 1944 и июнем 1945»
MONTH_NO = {w: i + 1 for forms in (MONTHS_RU, MONTHS_GEN, MONTHS_INS) for i, w in enumerate(forms)}
MONTH_NO.update({w.replace("ё", "е"): n for w, n in list(MONTH_NO.items())})
MONTHS_GED = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
ONE = ("ABT", "CAL", "EST", "BEF", "AFT")          # приставка + одна дата
RU_PREFIX = {"ABT": "ок.", "CAL": "расч.", "EST": "оцен.", "BEF": "до", "AFT": "после", "FROM": "с", "TO": "по"}
DECOR = re.compile(r"[*_`⭐✅🟡❓⚠️️]")


class DateError(ValueError):
    pass


@dataclass(frozen=True)
class Day:
    """Одна дата: год, месяц и день (0 — неизвестно)."""
    y: int
    m: int = 0
    d: int = 0

    def __post_init__(self):
        if not 1000 <= self.y <= 2100:
            raise DateError(f"год {self.y}")
        if not 0 <= self.m <= 12 or (self.d and not self.m):
            raise DateError(f"месяц {self.m}")
        if self.d:
            try:
                datetime.date(self.y, self.m, self.d)
            except ValueError:
                raise DateError(f"нет такого дня: {self.d}.{self.m}.{self.y}")

    def iso(self):
        return f"{self.y}" + (f"-{self.m:02d}" if self.m else "") + (f"-{self.d:02d}" if self.d else "")

    def ru(self, case=MONTHS_RU):
        if self.d:
            return f"{self.d:02d}.{self.m:02d}.{self.y}"
        return f"{case[self.m - 1]} {self.y}" if self.m else str(self.y)

    def ged(self):
        return " ".join(x for x in (str(self.d) if self.d else "", MONTHS_GED[self.m - 1] if self.m else "",
                                    str(self.y)) if x)

    def key(self):
        return (self.y, self.m, self.d)



def _jdn_julian(y, m, d):
    a = (14 - m) // 12
    y2, m2 = y + 4800 - a, m + 12 * a - 3
    return d + (153 * m2 + 2) // 5 + 365 * y2 + y2 // 4 - 32083


def _from_jdn_gregorian(j):
    a = j + 32044
    b = (4 * a + 3) // 146097
    c = a - 146097 * b // 4
    d = (4 * c + 3) // 1461
    e = c - 1461 * d // 4
    m = (5 * e + 2) // 153
    return Day(100 * b + d - 4800 + m // 10, m + 3 - 12 * (m // 10), e - (153 * m + 2) // 5 + 1)


def _jdn_gregorian(y, m, d):
    return datetime.date(y, m, d).toordinal() + 1721425


def _from_jdn_julian(j):
    c = j + 32082
    d = (4 * c + 3) // 1461
    e = c - 1461 * d // 4
    m = (5 * e + 2) // 153
    return Day(d - 4800 + m // 10, m + 3 - 12 * (m // 10), e - (153 * m + 2) // 5 + 1)


JULIAN_LAST = (1918, 1, 31)   # последний день старого стиля в России; следующий — 14.02.1918 по новому


def julian_to_gregorian(day):
    """Дата по старому стилю → по новому: 13.06.1888 → 25.06.1888, 24.04.1903 → 07.05.1903. Только полная дата."""
    if not (day.m and day.d):
        raise DateError(f"{day.iso()}: перевод стиля — только для полной даты (день, месяц, год)")
    return _from_jdn_gregorian(_jdn_julian(day.y, day.m, day.d))


def gregorian_to_julian(day):
    """Обратно: 25.06.1888 → 13.06.1888."""
    if not (day.m and day.d):
        raise DateError(f"{day.iso()}: перевод стиля — только для полной даты (день, месяц, год)")
    return _from_jdn_julian(_jdn_gregorian(day.y, day.m, day.d))


def old_style_era(day):
    """Дата (по новому стилю) — из того времени, когда в России жили по старому (до 14.02.1918)."""
    return (day.y, day.m or 12, day.d or 31) < (1918, 2, 14)


@dataclass(frozen=True)
class GDate:
    """kind: "" (точно), ABT, CAL, EST, BEF, AFT, BET (a и b), FROM (a, иногда b), TO (b);
    PHRASE — даты нет, только слова: «(без даты)» (в GEDCOM — тоже только слова в скобках)."""
    kind: str
    a: Day | None = None
    b: Day | None = None
    phrase: str = ""
    julian: bool = False          # главная дата — по старому стилю (прежняя запись «12.02.1910 ст. ст.»; --fix переводит)
    os: "Day | None" = None       # та же дата по старому стилю, как в документе: «25.06.1888 (13.06.1888 ст. ст.)»

    def __post_init__(self):
        if self.a and self.b and self.b.key() < self.a.key():
            raise DateError(f"конец раньше начала: {self.a.iso()} … {self.b.iso()}")
        if self.os and not (self.kind == "" and self.a and self.a.d):
            raise DateError("старый стиль рядом — только у точной даты с днём («25.06.1888 (13.06.1888 ст. ст.)»)")
        if self.os and julian_to_gregorian(self.os) != self.a:
            raise DateError(f"{self.os.ru()} ст. ст. — это {julian_to_gregorian(self.os).ru()} по новому, а не {self.a.ru()}")

    def new_style(self):
        """Главная дата по старому стилю → по новому, старая — рядом: «13.06.1888 ст. ст.» → «25.06.1888 (13.06.1888 ст. ст.)».
        Год или месяц без дня — как есть (на 12–13 дней не сдвинуть)."""
        if not self.julian or not (self.kind == "" and self.a and self.a.d):
            return self
        return GDate("", julian_to_gregorian(self.a), phrase=self.phrase, os=self.a)

    @property
    def os_ru(self):
        """Старый стиль словами для показа рядом: «13.06.1888 ст. ст.» — или пусто."""
        return f"{self.os.ru()} ст. ст." if self.os else ""

    @property
    def first(self):
        return self.a or self.b

    @property
    def first_year(self):
        return self.first.y if self.first else None

    @property
    def last_year(self):
        return (self.b or self.a).y if self.first else None

    @property
    def approx(self):
        """Не точная дата — ни день, ни год не известны наверняка."""
        return self.kind not in ("", "FROM", "TO")

    def sort_key(self):
        """Для сортировки строк: «ГГГГ-ММ-ДД» (как сайт); «после 1949» — после всех дат 1949 года («1949-99»);
        у даты из одних слов — None."""
        f = self.first
        if not f:
            return None
        return f.iso() + ("-99" if self.kind == "AFT" else "")

    def card(self):
        if self.kind == "PHRASE":
            raise DateError("в карточке дата без слов")
        if self.kind == "":
            return self.a.iso()
        if self.kind in ONE:
            return f"{self.kind} {self.a.iso()}"
        if self.kind == "BET":
            return f"BET {self.a.iso()} AND {self.b.iso()}"
        if self.kind == "TO":
            return f"TO {self.b.iso()}"
        return f"FROM {self.a.iso()}" + (f" TO {self.b.iso()}" if self.b else "")

    def ru(self):
        a, b = self.a, self.b
        if self.kind == "PHRASE":
            return f"({self.phrase})"
        if self.kind == "":
            s = a.ru()
        elif self.kind in ONE:
            s = f"{RU_PREFIX[self.kind]} {a.ru(MONTHS_RU if self.kind in ('CAL', 'EST') else MONTHS_GEN)}"
        elif self.kind == "BET":
            s = (f"{a.y}-е" if not a.m and not b.m and a.y % 10 == 0 and b.y == a.y + 9
                 else f"между {a.ru(MONTHS_INS)} и {b.ru(MONTHS_INS)}")
        elif self.kind == "TO":
            s = f"по {b.ru()}"
        elif not b:
            s = f"с {a.ru(MONTHS_GEN)}"
        elif not a.m and not b.m and a.y % 10 == 0 and b.y % 10 == 9 and b.y - a.y >= 19:
            s = f"{a.y}-е–{b.y - 9}-е"
        else:
            s = f"{a.ru()}–{b.ru()}" if not a.d and not a.m and not b.m else f"{a.ru()} – {b.ru()}"
        words = "; ".join(x for x in (self.os_ru, self.phrase) if x)
        return s + (" ст. ст." if self.julian else "") + (f" ({words})" if words else "")

    def gedcom(self):
        """GEDCOM 5.5.1: «ABT 1935», «BET 1941 AND 1945», «INT 1945 (после войны)», «@#DJULIAN@ 12 FEB 1910»."""
        if self.kind == "PHRASE":
            return f"({self.phrase})"
        cal = "@#DJULIAN@ " if self.julian else ""
        a, b = (cal + self.a.ged()) if self.a else "", (cal + self.b.ged()) if self.b else ""
        if self.kind == "":
            return f"INT {a} ({self.phrase})" if self.phrase else a
        if self.kind in ONE:
            return f"{self.kind} {a}"
        if self.kind == "BET":
            return f"BET {a} AND {b}"
        if self.kind == "TO":
            return f"TO {b}"
        return f"FROM {a}" + (f" TO {b}" if b else "")


# ─── Разбор ─────────────────────────────────────────────────────────────────────────────────

ISO = r"(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?"
CARD = re.compile(rf"(?:(ABT|CAL|EST|BEF|AFT|FROM|TO) )?{ISO}|BET {ISO} AND {ISO}|FROM {ISO} TO {ISO}")


def _iso(y, m, d):
    return Day(int(y), int(m or 0), int(d or 0))


def parse_card(v):
    """Дата из карточки (born, died, date события). Пусто — None; не по правилу — DateError."""
    if v is None or str(v).strip() == "":
        return None
    s = str(v).strip()
    m = CARD.fullmatch(s)
    if not m:
        raise DateError(f"«{s}» — не дата карточки (1935, 1935-05-12, ABT 1935, BEF 1944, BET 1941 AND 1945, "
                        f"FROM 1941 TO 1945)")
    g = m.groups()
    if g[1]:
        kind = g[0] or ""
        day = _iso(*g[1:4])
        return GDate("TO", b=day) if kind == "TO" else GDate(kind, a=day)
    if g[4]:
        return GDate("BET", _iso(*g[4:7]), _iso(*g[7:10]))
    return GDate("FROM", _iso(*g[10:13]), _iso(*g[13:16]))


DAY_RU = rf"(\d{{1,2}})\.(\d{{1,2}})\.(\d{{4}})|({'|'.join(sorted(MONTH_NO, key=len, reverse=True))}) (\d{{4}})|(\d{{4}})"
_DAY_RU = re.compile(DAY_RU, re.I)
OS_WORDS = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4}) ст\. ст\.")   # «13.06.1888 ст. ст.» в скобках после даты
RU = {
    "": re.compile(rf"(?P<a>{DAY_RU})"),
    "ABT": re.compile(rf"ок\. (?P<a>{DAY_RU})"),
    "CAL": re.compile(rf"расч\. (?P<a>{DAY_RU})"),
    "EST": re.compile(rf"оцен\. (?P<a>{DAY_RU})"),
    "BEF": re.compile(rf"до (?P<a>{DAY_RU})"),
    "AFT": re.compile(rf"после (?P<a>{DAY_RU})"),
    "BET": re.compile(rf"между (?P<a>{DAY_RU}) и (?P<b>{DAY_RU})"),
    "DEC": re.compile(r"(?P<a>\d{3}0)-е"),
    "DECS": re.compile(r"(?P<a>\d{3}0)-е ?– ?(?P<b>\d{3}0)-е"),
    "FROM": re.compile(rf"с (?P<a>{DAY_RU})"),
    "TO": re.compile(rf"по (?P<b>{DAY_RU})"),
    "SPAN": re.compile(rf"(?P<a>{DAY_RU}) ?– ?(?P<b>{DAY_RU})"),
}


def _day_ru(s):
    m = _DAY_RU.fullmatch(s)
    if m[3]:
        return Day(int(m[3]), int(m[2]), int(m[1]))
    if m[5]:
        return Day(int(m[5]), MONTH_NO[m[4].lower()])
    return Day(int(m[6]))


def clean(cell):
    """Ячейка без оформления: «⭐ **12.05.1935**» → «12.05.1935»."""
    return re.sub(r"\s+", " ", DECOR.sub("", str(cell))).strip()


def parse_ru(cell):
    """Дата из таблицы «Линия жизни». Не по правилу — DateError (что именно не так — в тексте ошибки)."""
    s = clean(cell)
    m = re.fullmatch(r"\(([^()]+)\)", s)
    if m:
        return GDate("PHRASE", phrase=m[1].strip())
    phrase = ""
    m = re.fullmatch(r"(.*?) \(([^()]+)\)", s)
    if m:
        s, phrase = m[1], m[2].strip()
    julian = False
    if s.endswith(" ст. ст."):
        s, julian = s[:-8].strip(), True
    os = None
    parts = [x.strip() for x in phrase.split(";")] if phrase else []
    for x in parts:
        m = OS_WORDS.fullmatch(x)
        if m:
            os = Day(int(m[3]), int(m[2]), int(m[1]))
            parts.remove(x)
            break
    phrase = "; ".join(parts)
    if os:
        a = _DAY_RU.fullmatch(s)
        if not (a and a[3]):
            raise DateError(f"«{clean(cell)}»: старый стиль в скобках — только при точной дате с днём")
        return GDate("", _day_ru(s), phrase=phrase, os=os)
    for kind, rx in RU.items():
        m = rx.fullmatch(s)
        if not m:
            continue
        if kind == "DEC":
            y = int(m["a"])
            return GDate("BET", Day(y), Day(y + 9), phrase, julian)
        if kind == "DECS":
            return GDate("FROM", Day(int(m["a"])), Day(int(m["b"]) + 9), phrase, julian)
        a = _day_ru(m["a"]) if "a" in m.groupdict() and m["a"] else None
        b = _day_ru(m["b"]) if "b" in m.groupdict() and m["b"] else None
        kind = {"SPAN": "FROM"}.get(kind, kind)
        return GDate(kind, a, b, phrase, julian)
    raise DateError(f"«{clean(cell)}» — не дата линии жизни (1935, май 1935, 12.05.1935, ок. 1935, до 1944, "
                    f"после 1944, между 1941 и 1945, 1950-е, 1941–1945, с 1944, по 1950; слова — в скобках после даты; "
                    f"даты нет вовсе — только слова в скобках: (без даты))")


def year(v):
    """Первый год в любой записи даты (карточка, таблица, число из YAML) — или None. Для сортировки и грубых сравнений."""
    m = re.search(r"(?<!\d)(1[0-9]\d\d|20\d\d)(?!\d)", str(v if v is not None else ""))
    return int(m.group(1)) if m else None


_GED_DAY = re.compile(r"(?:(@#D[A-Z ]+@)\s*)?(?:(\d{1,2})\s+)?(?:([A-Z]{3})\s+)?(\d{3,4})(?:/\d{2})?")
_GED_FORMS = [  # (вид, правило) — по порядку; «A» и «B» — одна дата GEDCOM
    ("BET", re.compile(r"BET\s+(?P<a>.+?)\s+AND\s+(?P<b>.+)")),
    ("FROM", re.compile(r"FROM\s+(?P<a>.+?)\s+TO\s+(?P<b>.+)")),
    ("FROM", re.compile(r"FROM\s+(?P<a>.+)")),
    ("TO", re.compile(r"TO\s+(?P<b>.+)")),
    ("INT", re.compile(r"INT\s+(?P<a>.+?)\s*\((?P<p>.*)\)")),
    *[(k, re.compile(rf"{k}\s+(?P<a>.+)")) for k in ONE],
    ("", re.compile(r"(?P<a>.+)")),
]


def _ged_day(s):
    """«@#DJULIAN@ 12 FEB 1852» → (Day, по старому стилю?). Не дата — DateError."""
    m = _GED_DAY.fullmatch(s.strip())
    if not m or (m[3] and m[3] not in MONTHS_GED) or (m[2] and not m[3]):
        raise DateError(f"«{s}» — не дата GEDCOM")
    cal = (m[1] or "").replace(" ", "")
    if cal and cal not in ("@#DJULIAN@", "@#DGREGORIAN@"):
        raise DateError(f"«{s}» — календарь {cal} не поддерживается")
    return Day(int(m[4]), MONTHS_GED.index(m[3]) + 1 if m[3] else 0, int(m[2] or 0)), cal == "@#DJULIAN@"


def parse_gedcom(v):
    """Дата из файла GEDCOM (DATE) → GDate по правилам карточки. Пусто — None; не разобрать — DateError.

    «12 FEB 1852» → 1852-02-12; «ABT 1855», «BET 1930 AND 1931», «FROM 1980», «INT 1883 (умер младенцем)» — как есть;
    «(без даты)» — только слова. Старый стиль (@#DJULIAN@) у даты с днём переводится в новый (главная дата — по новому
    стилю), старая — рядом: «@#DJULIAN@ 12 FEB 1852» → 24.02.1852 (12.02.1852 ст. ст.); год или месяц — как есть."""
    if v is None or not str(v).strip():
        return None
    s = re.sub(r"\s+", " ", str(v).strip().upper())
    if s.startswith("(") and s.endswith(")"):
        return GDate("PHRASE", phrase=str(v).strip()[1:-1].strip())

    def day(x):
        d, julian = _ged_day(x)
        return (julian_to_gregorian(d), d) if julian and d.d else (d, None)

    for kind, rx in _GED_FORMS:
        m = rx.fullmatch(s)
        if not m:
            continue
        g = m.groupdict()
        if kind == "INT":
            a, os_ = day(g["a"])
            phrase = re.search(r"\((.*)\)", str(v)).group(1).strip()   # слова — как в файле, не заглавными
            return GDate("", a, phrase=phrase, os=os_)
        a, os_ = day(g["a"]) if g.get("a") else (None, None)
        b = day(g["b"])[0] if g.get("b") else None
        if kind == "TO":
            return GDate("TO", b=b)
        return GDate(kind, a, b, os=os_ if kind == "" else None)
    raise DateError(f"«{v}» — не дата GEDCOM")


def card_or_none(v):
    try:
        return parse_card(v)
    except DateError:
        return None


def ru_or_none(v):
    try:
        return parse_ru(v)
    except DateError:
        return None


def to_ru(v):
    """Дата карточки → по-русски («ABT 1935» → «ок. 1935»); не разобралась — как есть."""
    g = card_or_none(v)
    return g.ru() if g else ("" if v is None else str(v))



# ─── Год из возраста, оценка по родне ───────────────────────────────────────────────────────
# Правила и числа — из genealogy-mcp (igormel81, MIT): estimate.py, dates.py. Навык dates, «Год из возраста».

def birth_from_age(age, when):
    """«45 лет в 1897» → (точно BET 1851 AND 1852, широко BET 1849 AND 1854). when — год, Day или GDate записи.
    Точно — день рождения мог быть до записи или после. Широко — для сравнения записей: в ревизиях, исповедных
    и записях о смерти возраст округлён (до 0 или 5) и «плывёт» на 2–5 лет."""
    y = when if isinstance(when, int) else (when.y if isinstance(when, Day) else when.first_year)
    a = int(float(age))
    return GDate("BET", Day(y - a - 1), Day(y - a)), GDate("BET", Day(y - a - 3), Day(y - a + 2))


def ages_agree(first, second):
    """Два возраста одного имени — (age, год записи) каждый → (разница в годах рождения, вывод):
    до 5 лет — «норма» (возраст плывёт); 6–10 — «перечитать» (возраст и другие приметы); больше 10 — «тёзки»
    (скорее два человека: отец и сын, двоюродные — не сливать, сравнить родителей, супруга, двор)."""
    d = abs((first[1] - int(float(first[0]))) - (second[1] - int(float(second[0]))))
    return d, "норма" if d <= 5 else "перечитать" if d <= 10 else "тёзки"


KIN_SPAN = {   # родня → (раньше, позже) — на сколько лет от её года рождения (или года брака) рождается наш человек
    "father": (18, 45), "mother": (18, 45),            # родители: обычно ребёнок в 18–45 (чаще около 30 и 27)
    "eldest_child": (-45, -18),                       # старший известный ребёнок — в 18–45 лет родителя
    "spouse": (-8, 8), "sibling": (-8, 8),            # супруг, брат, сестра — в пределах 8 лет
    "first_marriage": (-35, -16),                     # первый брак — в 16–35, чаще около 22
}
KIN_WORDS = {"father": "отец", "mother": "мать", "eldest_child": "старший ребёнок", "spouse": "супруг(а)",
             "sibling": "брат/сестра", "first_marriage": "первый брак"}


def estimate_birth(ages=(), **kin):
    """Оценка года рождения по родне — пересечение окон KIN_SPAN и широких окон возраста. kin — father=1850,
    eldest_child=1895, siblings=[1870, 1874], first_marriage=1890 …; ages — [(возраст, год записи)].
    → (GDate, почему): окно до 15 лет — BET a AND b, шире — EST середины. Окна не сходятся — DateError с окнами:
    решает человек (чаще всего связь неверна или это тёзки). Это оценка, не факт: в карточку — с пояснением."""
    win = []
    for k, v in kin.items():
        if k == "siblings":
            win += [(f"брат/сестра {y}", y - 8, y + 8) for y in v]
        elif v is not None:
            lo, hi = KIN_SPAN[k]
            win.append((f"{KIN_WORDS[k]} {v}", v + lo, v + hi))
    for a, y in ages:
        g = birth_from_age(a, y)[1]
        win.append((f"{a} лет в {y}", g.a.y, g.b.y))
    if not win:
        raise DateError("оценивать не по чему: нужен год кого-то из родни или возраст в записи")
    lo, hi = max(w[1] for w in win), min(w[2] for w in win)
    why = "; ".join(f"{w[0]} → {w[1]}–{w[2]}" for w in win)
    if lo > hi:
        raise DateError(f"окна не сходятся: {why}")
    g = GDate("BET", Day(lo), Day(hi)) if hi - lo <= 15 else GDate("EST", Day((lo + hi) // 2))
    return g, f"оценка по родне: {why}; общее — {lo}–{hi}"


# ─── Пасха и церковные праздники ────────────────────────────────────────────────────────────
# «Крещён на Покров», «умер на Троицу» — день по календарю той церкви. Православная церковь (и метрика) считает по
# старому стилю, костёл — по новому. Даты праздников и Пасха (алгоритм Меуса) — из genealogy-mcp (calendars.py, MIT).

def orthodox_easter(year):
    """Православная Пасха — по старому стилю, как в метрике: 1888 → 24.04.1888 (новый стиль — julian_to_gregorian)."""
    a, b, c = year % 4, year % 7, year % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    return Day(year, (d + e + 114) // 31, (d + e + 114) % 31 + 1)


def catholic_easter(year):
    """Католическая Пасха — по новому стилю: 1888 → 01.04.1888."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    g = (b - (b + 8) // 25 + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    return Day(year, (h + l_ - 7 * m + 114) // 31, (h + l_ - 7 * m + 114) % 31 + 1)


FEASTS_ORTHODOX = {   # название (как пишут; рус. и бел.) → (месяц, день) по старому стилю или сдвиг от Пасхи в днях
    "рождество христово": (12, 25), "рождество": (12, 25), "крещение": (1, 6), "богоявление": (1, 6),
    "сретение": (2, 2), "благовещение": (3, 25), "егорий вешний": (4, 23), "юрьев день вешний": (4, 23),
    "никола вешний": (5, 9), "иван купала": (6, 24), "купалле": (6, 24), "рождество иоанна предтечи": (6, 24),
    "петров день": (6, 29), "петра и павла": (6, 29), "ильин день": (7, 20), "преображение": (8, 6),
    "яблочный спас": (8, 6), "успение": (8, 15), "усекновение": (8, 29), "рождество богородицы": (9, 8),
    "воздвижение": (9, 14), "покров": (10, 1), "пакровы": (10, 1), "казанская": (10, 22), "дмитриев день": (10, 26),
    "кузьма и демьян": (11, 1), "михайлов день": (11, 8), "введение": (11, 21), "юрьев день": (11, 26),
    "никола зимний": (12, 6), "николин день": (12, 6),
    "прощёное воскресенье": -49, "чистый понедельник": -48, "лазарева суббота": -8, "вербное воскресенье": -7,
    "страстная пятница": -2, "пасха": 0, "вялікдзень": 0, "радоница": 9, "вознесение": 39, "троица": 49,
    "тройца": 49, "духов день": 50,
}
FEASTS_CATHOLIC = {   # то же у костёла (пол. и рус.) — по новому стилю
    "boże narodzenie": (12, 25), "рождество": (12, 25), "trzech króli": (1, 6), "matki boskiej gromnicznej": (2, 2),
    "zwiastowanie": (3, 25), "świętego jana": (6, 24), "piotra i pawła": (6, 29), "wniebowzięcie": (8, 15),
    "matki boskiej zielnej": (8, 15), "narodzenie najświętszej marii panny": (9, 8), "matki boskiej siewnej": (9, 8),
    "świętego michała": (9, 29), "wszystkich świętych": (11, 1), "zaduszki": (11, 2), "świętego marcina": (11, 11),
    "świętego andrzeja": (11, 30), "świętego mikołaja": (12, 6),
    "popielec": -46, "niedziela palmowa": -7, "wielki piątek": -2, "wielkanoc": 0, "пасха": 0,
    "wniebowstąpienie": 39, "zielone świątki": 49, "boże ciało": 60,
}
_PREP = re.compile(r"^(на|в|во|под|после|до|перед|к|na|w|we|po|przed|od)\s+")


def _feast(name, table):
    """«на Николу зимнего» → «никола зимний»: слова сверяем по первым 4 буквам — так сходятся падежи."""
    n = _PREP.sub("", " ".join(name.lower().replace("ё", "е").replace("św.", "świętego").split()))
    n = re.sub(r"\bдня\b", "день", n)                  # «Петрова дня» = «петров день»
    q = [w[:4] for w in n.split()]
    for key, v in table.items():
        k = key.replace("ё", "е")
        if n == k or q == [w[:4] for w in k.split()]:
            return key, v
    raise DateError(f"праздник «{name}» не знаю; есть: {', '.join(table)}")


def feast_date(name, year, church="orthodox"):
    """День праздника в году → GDate главной датой по новому стилю; у православного — старый стиль рядом:
    feast_date("на Покров", 1888).ru() → «13.10.1888 (01.10.1888 ст. ст.)»; church="catholic" — костёл."""
    orthodox = church.startswith(("o", "п"))
    key, v = _feast(name, FEASTS_ORTHODOX if orthodox else FEASTS_CATHOLIC)
    if orthodox:
        e = orthodox_easter(year)
        jul = Day(year, *v) if isinstance(v, tuple) else _from_jdn_julian(_jdn_julian(e.y, e.m, e.d) + v)
        return GDate("", julian_to_gregorian(jul), os=jul)
    if isinstance(v, tuple):
        return GDate("", Day(year, *v))
    e = catholic_easter(year)
    d = datetime.date(e.y, e.m, e.d) + datetime.timedelta(days=v)
    return GDate("", Day(d.year, d.month, d.day))
