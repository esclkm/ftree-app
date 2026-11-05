"""Что с сайта не уходит в интернет: номера домов и квартир, телефоны и почта живых людей (решено 27.09.2026).

По адресу можно найти живых людей, поэтому улица остаётся, а номер — нет: «Минск — Садовая, 12-34» → «Минск — Садовая».
Исключение — дом, где из тех, с кем держим связь, уже никто не живёт: в карточке места `address_public: true`
(«Гродно — Луговая, 5»; решено 02.10.2026). Его адрес с номером сайт показывает; другие номера той же улицы — нет.
Улицы с номером берутся из названий мест («Гродно — Луговая, 5»), плюс любые «ул./пер./ul./Av./Calle … N» и «д. N»,
«кв. N». Годы (4 цифры) не трогаем. Аудиозаписи телефон называет по адресу дома («<улица> 5.m4a»; улица —
`[privacy] audio_name` в ftree.toml) — на сайте они «Запись 5».

Правило одно для HTML-страниц и для JSON: всё, что видит посетитель, проходит через Privacy и no_contacts. Записи
разговоров в семье (звук и расшифровка) на сайт не идут вовсе — в конце файла, audio_source и unpublished. В карточках
и архиве адреса и контакты целы — это зацепка для контакта с роднёй; вырезаются они только на выходе.
"""
import functools
import hashlib
import re

import paths
from cards.notes import N, as_list, link_target
from .names import latin

# Контакты: телефоны с кодом страны и почта. Старые номера без кода страны («Тел. 123-45-67» в шапке письма 1980-х) —
# часть документа, их не трогаем.
PHONE = re.compile(r"\+\d{2,3}[ ()\d-]{7,}\d")
EMAIL = re.compile(r"[\w.%+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}")
# Профили в соцсетях (решено 05.10.2026): в карточках они — зацепка для контакта с роднёй, но по ним живого человека
# находят за минуту. На сайт не идут ни ссылкой, ни текстом адреса; строка факта, где кроме профиля ничего нет, — целиком.
SOCIAL = re.compile(r"(?<![\w.@-])(?:https?://)?(?:[\w-]+\.)?(?:facebook|instagram|linkedin|twitter|x|tiktok|vk|ok)\.(?:com|ru)/[^\s)\]|,;]*", re.I)


# Аргентинский адрес «Arenales 1234 piso 5 depto 9, C.A.B.A.» — улица без «ул./Calle», номер дома сразу за ней, за ним —
# город Буэнос-Айрес. Улица остаётся, номер, этаж и квартира — нет (05.10.2026). Месяц перед годом («Mayo 1944, Buenos
# Aires») — не улица.
_MONTHS_ES = "Enero|Febrero|Marzo|Abril|Mayo|Junio|Julio|Agosto|Septiembre|Setiembre|Octubre|Noviembre|Diciembre"
AR_ADDRESS = re.compile(r"\b(?!(?:" + _MONTHS_ES + r")\b)([A-ZÁÉÍÓÚÑ][\wáéíóúñ.]+(?: [A-ZÁÉÍÓÚÑ][\wáéíóúñ.]+){0,3}) \d{2,5}"
                        r"(?: piso \w+)?(?: (?:depto|dpto)\.? ?\w+)?(?=(?:,\s*|\s*\(\s*)(?:CABA|C\.A\.B\.A\.|Ciudad Aut[oó]noma|Buenos Aires|Bs\.? ?As))")


def no_contacts(s):
    """Телефоны с кодом страны, почта, профили в соцсетях и номера домов в аргентинских адресах → «[телефон скрыт]»,
    «[почта скрыта]», «[профиль скрыт]», улица без номера."""
    s = AR_ADDRESS.sub(r"\1", s)
    return SOCIAL.sub("[профиль скрыт]", EMAIL.sub("[почта скрыта]", PHONE.sub("[телефон скрыт]", s)))


def social_only(s):
    """В строке нет ничего, кроме профилей в соцсетях (и знаков между ними) — такую строку сайт не показывает."""
    return bool(SOCIAL.search(s)) and not re.sub(r"[\s—–\-:·,;()]+", "", SOCIAL.sub("", s))


_SHOWN_ATTR = re.compile(r'(\s(?:alt|title|aria-label|data-(?!src|href|url)[\w-]+)=")([^"]*)(")')

_HOUSE = r"\d{1,3}(?:к\d{1,2}|[a-zA-Zа-я])?(?:\s?[-–/]\s?\d{1,3}[a-zA-Zа-я]?)?(?![^\W_])(?![.:]\d)"
# как эти улицы звучат в переводах биографий (кроме побуквенной латиницы — её правило строит само)
# улицы дерева — в ftree.toml, [privacy.streets_translated]: {"Луговая": ["Ługow", "Meadow"]}
STREETS_TRANSLATED = dict(paths.CONFIG.get("privacy", {}).get("streets_translated", {}))
# так телефон называет записи разговоров — по улице дома («<улица> 5.m4a»); на сайте — «Запись 5»
AUDIO_NAME = paths.setting("FTREE_AUDIO_NAME", "", toml="privacy.audio_name")


_OPIS = re.compile(r"(?<!\w)оп\.\s*\d")  # «оп. 6» — опись в архивном шифре
_STREET_WORD = re.compile(r"(?<!\w)(?:ул\.|улиц|пер\.|переул|просп|бульвар|шоссе|тракт|дом\b|кв\.)", re.I)


def _flat(m):
    """«д. 16», «кв. 1» — убрать; но «д.» в архивном шифре — это «дело» («ф. 347, оп. 1, д. 4»), а «кв.» сразу после
    ряда — квадрат кладбища («38 кв. 6 ряд»): их оставляем. «Дело» и дальше по тексту после шифра, в том же абзаце и
    без улицы между ними: «оп. 6, **д. 526**», «…, 521; запасные — д. 518», «ведомость 1914 года в д. 526»."""
    before = m.string[max(0, m.start() - 12):m.start()]
    if m[2] == "д." and re.search(r"оп\.\s*\d+[а-я]?,?$", before + m[1].rstrip()):
        return m[0]
    if m[2] == "д." and (op := list(_OPIS.finditer(m.string[max(0, m.start() - 160):m.start()]))):
        gap = m.string[max(0, m.start() - 160):m.start()][op[-1].end():]
        if "\n\n" not in gap and not _STREET_WORD.search(gap):
            return m[0]
    if m[2] == "кв." and re.match(r"\s*ряд", m.string[m.end():]):
        return m[0]
    return ""


class Privacy:
    """Очистка от адресов. Улицы с номером берутся из названий мест («Гродно — Луговая, 5»)."""

    def __init__(self, place_names, public=()):
        """public — названия мест с address_public: true; их «улица, номер» не вырезаем."""
        self.streets = sorted({m[1].split()[0] for name in place_names
                               if (m := re.search(r"—\s*([^,—·№]+?),?\s+\d", name)) and m[1][0].isupper()},
                              key=len, reverse=True)
        self.public = [(m[1].split()[0], m[2]) for name in public
                       if (m := re.search(r"—\s*([^,—·№]+?),?\s+(\d{1,3}[a-zA-Zа-я]?)\b", name))]
        self._addr = None
        self._keep = None

    @staticmethod
    def _forms(w):
        """Как улица звучит в тексте и переводах: падежи, латиница, перевод — основы для правил."""
        out = set()
        for form in [w, latin(w, "en"), latin(w, "pl"), *STREETS_TRANSLATED.get(w, [])]:
            out.add(re.escape(form[:-2] if re.search(r"(ая|ий|ой|ый|aya|iy|aja|ij)$", form) else form))
        return out

    def _keep_rule(self):
        """«Луговая, 5», «на Луговой, 5», «Ługowej 5», «Луговая-5» — адреса, открытые для сайта."""
        if not self.public:
            return None
        alts = [rf"(?:{'|'.join(sorted(self._forms(w), key=len, reverse=True))})[^\W\d_]{{0,4}}"
                rf"(?:\s(?:улица|ул\.|Street|St\.))?(?:,\s*|\s|_|-)(?:д\.\s*|дом\s*|nr\s*|No\.?\s*)?{re.escape(n)}"
                for w, n in self.public]
        return re.compile(rf"(?<![^\W_])(?:{'|'.join(alts)})(?![^\W_])(?![-–/.:]\d)")

    def _rules(self):
        """Правила строятся при первом вызове: второй шаг читает все заметки 3_research."""
        stems = set()
        for w in self.streets:  # падежи: «на Луговой, 5», «na Ługowej 5» — у прилагательных отрезаем окончание
            stems |= self._forms(w)
        alt = "|".join(sorted(stems, key=len, reverse=True))
        street = re.compile(rf"(?<![^\W_])(?:{alt})[^\W\d_]{{0,4}},?\s(?:д\.\s*)?(\d{{1,3}}\s?[-–/]\s?\d{{1,3}})(?!\d)")
        # «дом-квартира», которые где-то стоят после улицы («Садовая, 12-34»), прячем и там, где улицы рядом нет
        # («переехала в дом напротив, 12-34 осталась…»)
        flats = {re.sub(r"\s", "", m[1]) for f in paths.RESEARCH.rglob("*.md")
                 for m in street.finditer(N(f.read_text(encoding="utf-8", errors="ignore")))}
        return [
            *([(re.compile(rf"(?<![^\W_]){re.escape(AUDIO_NAME)}[ _](\d)(?![^\W_])(?![/.:,-]\d)"), r"Запись \1")]
              if AUDIO_NAME else []),
            (re.compile(rf"((?<![^\W_])(?:{alt})[^\W\d_]{{0,4}}(?:\s(?:переулок|пер\.|улица|ул\.|pereulok|Street|St\.|Lane))?)"
                        rf"(?:,\s*|\s|_|-)(?:д\.\s*|дом\s*|nr\s*|No\.?\s*)?{_HOUSE}"), r"\1"),
            # по-английски номер впереди: «5 Lugovaya Street»
            (re.compile(rf"(?<!\w)\d{{1,3}}[a-zA-Z]?,?\s(?=(?:{alt})\w*\s(?:Street|St\.|Lane))"), ""),
            (re.compile(r"((?<!\w)(?:ул\.|улица|улице|улицу|пер\.|переулок|просп\.|проспект|бульвар|шоссе|тракт|ul\.|ulica|ulicy|ulicę)"
                        r"\s?[\w.\-]+(?: [\w.\-]+)??)(?:,\s*|\s)(?:д\.\s*|№\s*|nr\s*)?" + _HOUSE), r"\1"),
            # тип улицы после названия: «Койдановский тракт, 16», «Брилевский переулок 3»
            (re.compile(r"((?<!\w)[А-ЯЁ][\w-]+\s(?:тракт|переулок|проспект|бульвар|шоссе|улица))(?:,\s*|\s)(?:д\.\s*)?" + _HOUSE), r"\1"),
            # в Аргентине номер дома — до 4 цифр: «Av. Siempreviva 742», «Calle 12 №1234»
            (re.compile(r"((?<!\w)(?:Av\.|Avda\.|Avenida|Calle|calle)\s?[\w.\-]+)(?:,\s*|\s)(?:№\s*)?\d{1,4}[a-zA-Z]?(?!\w)(?![.:]\d)"), r"\1"),
            (re.compile(r"(,?\s*)(?<!\w)(д\.|дом|кв\.|квартира|корп\.)\s*№?\s*\d{1,3}(?:\s?[-–/]\s?\d{1,3})?[а-я]?(?!\w)(?![.:]\d)"), _flat),
            *([(re.compile(rf"(?:,\s*)?(?<![\w.:/-])(?:{'|'.join('[-–]'.join(map(re.escape, re.split('[-–]', x))) for x in sorted(flats))})(?![\w:/-]|[.,]\d)"), "")]
              if flats else []),
        ]

    def text(self, s):
        """Строка без номеров домов и квартир."""
        if self._addr is None:
            self._addr, self._keep = self._rules(), self._keep_rule()
        kept = []
        if self._keep:  # открытые адреса прячем от правил под метку и возвращаем после
            s = self._keep.sub(lambda m: kept.append(m[0]) or f"\x00{len(kept) - 1}\x00", s)
        for rx, rep in self._addr:
            s = rx.sub(rep, s)
        return re.sub(r"\x00(\d+)\x00", lambda m: kept[int(m[1])], s) if kept else s

    def file_name(self, stem):
        """Имя файла на сайте без номера дома («Минск_Садовая-12_1985» → «Минск_Садовая_1985-3f2a») — метка, чтобы не совпали."""
        clean = self.text(stem)
        return stem if clean == stem else re.sub(r"\s+", "_", clean) + "-" + hashlib.md5(stem.encode()).hexdigest()[:4]

    def html(self, s):
        """Номера домов — только из того, что человек видит: текст и подписи (alt, title, data-en…). Ссылки и имена файлов
        не трогаем — файлы на сайте и так названы без номера (file_name); скрипты и стили пропускаем."""
        out, skip = [], False
        for part in re.split(r"(<[^>]+>)", s):
            if part.startswith("<"):
                low = part[:8].lower()
                skip = low.startswith(("<script", "<style")) or (skip and not low.startswith(("</script", "</style")))
                out.append(_SHOWN_ATTR.sub(lambda m: m[1] + self.text(m[2]) + m[3], part))
            else:
                out.append(part if skip else self.text(part))
        return "".join(out)


# ---------- разговоры в семье ----------
# Аудиозаписи разговоров (Аудио 01, 02, …: с родителями, с дальней роднёй) и их расшифровки — рабочий материал: в расшифровке
# оговорки, повторы, личное; её ещё чистить. На сайт идёт только карточка источника — название, кто рассказывает, о ком
# (решено 29.09.2026). Ни текста, ни самого звука, ни страниц из 2_transcripts/audio/.
AUDIO = re.compile(r"\.(m4a|mp3|wav|ogg|aac|flac|opus)$", re.I)
NOT_PUBLISHED = (paths.rel(paths.TRANSCRIPTS_AUDIO) + "/",)


def is_audio(name):
    return bool(AUDIO.search(str(name)))


def unpublished(rel):
    """Путь от корня проекта, который на сайт не идёт вовсе (страницы и файлы)."""
    return N(str(rel)).startswith(NOT_PUBLISHED) or is_audio(rel) or closed_document(rel)


DOCUMENTS = paths.rel(paths.DOCUMENTS) + "/"
CLOSED = re.compile(r"^access:\s*closed\s*$", re.M)


@functools.cache
def closed_document(rel):
    """Документ с `access: closed` (живые, здоровье — documents.py): ни страницы с текстом, ни PDF рядом. До входа по уровням
    (отложенный план документ дерева проект/ПЛАН_ДОСТУП_И_ПРАВА.md) закрытое не публикуется вовсе."""
    rel = N(str(rel))
    if not rel.startswith(DOCUMENTS):
        return False
    note = (paths.ROOT / rel).with_suffix(".md")
    try:
        head = note.read_text(encoding="utf-8").split("\n---", 1)[0]
    except OSError:
        return False
    return bool(CLOSED.search(head))


def audio_source(fm):
    """Карточка источника — запись разговора: в media есть звук. У таких на сайте — только описание, без текста."""
    return any(is_audio(link_target(m)) for m in as_list(fm.get("media")))
