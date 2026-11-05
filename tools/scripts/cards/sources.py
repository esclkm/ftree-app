"""Карточки источников. Их читаем первыми: на них ссылаются факты людей."""
from .model import Problem, Source
from .notes import N, card_path, read_note

# origin карточки → происхождение (CLAUDE.md: семья > найдено > чужое дерево > вывод проекта)
PROVENANCE = {"семья": "family", "найдено": "found", "чужое дерево": "other_tree", "вывод проекта": "inference"}
# source_type (Charted Roots) — тот же список, что в web/schema/source.schema.json
TYPES = ("custom", "vital_record", "church_record", "census", "immigration", "military", "newspaper", "letter", "photo", "audio")
# карточки в sources/press (тексты, вырезки) — свои виды; сайт их знает (texts_section.py, KIND)
PRESS_TYPES = ("book", "magazine", "memoir", "manuscript", "autobiography")


def read_sources(folder, problems):
    """→ (cr_id → Source, имя или заголовок → cr_id)."""
    sources, by_name = {}, {}
    for p in sorted(folder.rglob("*.md")):
        note, card = read_note(p), card_path(p)
        f = note.fm
        if f.get("cr_type") != "source":
            continue
        if not f.get("cr_id"):
            problems.append(Problem(card, 1, "у источника нет номера cr_id"))
            continue
        prov = PROVENANCE.get(str(f.get("origin") or ""))
        if not prov:
            problems.append(Problem(card, 1, f"origin «{f.get('origin')}» — не из списка: {', '.join(PROVENANCE)}"))
            prov = "found"
        if str(f.get("source_type") or "custom") not in TYPES + PRESS_TYPES:
            problems.append(Problem(card, 1, f"source_type «{f.get('source_type')}» — не из списка: {', '.join(TYPES)}"))
        s = Source(f["cr_id"], note.stem, N(str(f.get("title") or note.stem)), prov, str(f.get("source_type") or "custom"),
                   N(str(f.get("author") or "")), N(str(f.get("repository") or "")), f, note.body)
        sources[s.id] = s
        by_name[s.stem] = by_name[s.title] = s.id
    return sources, by_name
