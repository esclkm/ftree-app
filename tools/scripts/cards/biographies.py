"""Биографии (3_research/tree/biographies/<Имя карточки> — биография.md): чья и под какими номерами.

Чья — показывает **имя файла**: биография человека называется как его карточка плюс « — биография»
(`tree/people/Прокоп Ясенев.md` ↔ `tree/biographies/Прокоп Ясенев — биография.md`). Одна биография — один человек.
Всё остальное из имени выводится и вписывается само (tools/scripts/bio_ids.py --fix, pre-commit):

  - свойства в начале файла — чтобы выгрузка для MyHeritage, сайт и перевод узнавали человека, не разбирая текст:
      ---
      person: "[[Прокоп Ясенев]]"
      person_id: ppl-001-aaa-001     ← cr_id карточки
      gedcom_id: I1                  ← номер MyHeritage (gedcom_id карточки)
      ---
  - строка в карточке `**Биография:** [[3_research/tree/biographies/<Имя> — биография.md]]` — для Obsidian и панели
    обратных ссылок; сайт её не ждёт, он находит биографию по имени;
  - переименовали карточку — биография (и её переводы) переименуются следом: человека узнаём по person_id.

Отсюда проблемы, которые называет чтение: биография без карточки, карточка переименована, а биография нет,
номера в свойствах не те, в карточке нет строки «Биография:» — всё, кроме биографии без человека, чинит --fix.
"""
from .model import Problem
from .notes import N, card_path, read_note

SUFFIX = " — биография"
FIX = "tools/scripts/bio_ids.py --fix"


def gedcom_of(person):
    return str(person.fm.get("gedcom_id") or "").strip("@") or None


def folder(research):
    return research / "tree" / "biographies"


def owner_stem(path):
    s = N(path.stem)
    return s[: -len(SUFFIX)] if s.endswith(SUFFIX) else None


def read_biographies(research, people, problems):
    """→ {путь биографии от корня проекта: cr_id хозяина или None}; что не так — в problems."""
    by_stem = {N(p.stem): p for p in people.values()}
    result = {}
    for f in sorted(folder(research).glob(f"*{SUFFIX}.md")):
        rel, note = card_path(f), read_note(f)
        stem = owner_stem(f)
        p = by_stem.get(stem)
        result[rel] = p.id if p else None
        pid, ged = note.fm.get("person_id"), str(note.fm.get("gedcom_id") or "").strip("@") or None
        bad = lambda msg: problems.append(Problem(rel, 1, msg))
        if not p:
            if pid in people:
                bad(f"карточка «{stem}» переименована в «{people[pid].stem}» — переименовать биографию следом: {FIX}")
            else:
                bad(f"нет карточки «{stem}» — биография должна называться как карточка человека + «{SUFFIX}»")
            continue
        if not pid:
            bad(f"нет свойства person_id (биография {p.name}) — {FIX}")
        elif pid != p.id:
            bad(f"person_id {pid} — а файл назван по карточке {p.name} ({p.id}); {FIX}")
        if gedcom_of(p) and ged != gedcom_of(p):
            bad(f"gedcom_id {ged or 'не записан'} — а у карточки {p.name} {gedcom_of(p)}; {FIX}")
        if f"**Биография:** [[{rel}]]" not in p.body:
            bad(f"в карточке {p.name} нет строки «**Биография:** [[{rel}]]» — {FIX}")
    return result
