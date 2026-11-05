"""Файл заметки → свойства и текст; ссылки [[…]] → имя заметки."""
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import yaml

import paths

# разбор на C в 6 раз быстрее (на всех 1452 заметках дерева результат тот же); нет сборки с C — обычный
LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def N(s):
    """Одна запись букв: macOS хранит «й» в именах файлов двумя знаками, в тексте — одним."""
    return unicodedata.normalize("NFC", s)


@dataclass
class Note:
    path: Path
    stem: str       # имя файла без .md — так на заметку ссылаются: [[stem]]
    fm: dict        # свойства из шапки --- … ---
    body: str       # всё после шапки
    body_line: int  # номер строки файла, с которой начинается body (для сообщений об ошибках)

    def line_of(self, pos):
        """Номер строки файла для позиции в body."""
        return self.body_line + self.body.count("\n", 0, pos)


def read_note(p):
    text = N(p.read_text(encoding="utf-8"))
    m = re.match(r"---\n(.*?)\n---\n?(.*)", text, re.S)
    if not m:
        return Note(p, N(p.stem), {}, text, 1)
    try:
        fm = yaml.load(m.group(1), Loader=LOADER) or {}
    except yaml.YAMLError:
        fm = {}
    return Note(p, N(p.stem), fm, m.group(2), text.count("\n", 0, m.start(2)) + 1)


def card_path(p):
    """Как назвать карточку в сообщении: путь от корня проекта (или полный, если карточка не из проекта — в тестах)."""
    return N(p.relative_to(paths.ROOT).as_posix() if p.is_relative_to(paths.ROOT) else str(p))


def as_list(v):
    if v is None or v == "":
        return []
    return v if isinstance(v, list) else [v]


def link_target(v):
    """'[[Имя|x]]' → 'Имя'; '[[папка/Имя.md#Раздел]]' → 'Имя'; не ссылка — сам текст."""
    m = re.match(r"\[\[([^\]|#]+)", str(v))
    return N(m.group(1).split("/")[-1].removesuffix(".md")).strip() if m else N(str(v)).strip()


def year(v):
    m = re.search(r"\d{4}", str(v or ""))
    return int(m.group()) if m else None


def section(body, title, level=3):
    """Текст раздела «### title» до следующего заголовка того же или старшего уровня и его начало в body."""
    m = re.search(rf"^{'#' * level} {re.escape(title)}\n(.*?)(?=^#{{1,{level}}} |\Z)", body, re.S | re.M)
    return (m.group(1), m.start(1)) if m else ("", -1)
