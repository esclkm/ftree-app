#!/usr/bin/env python3
"""Безопасная работа с GEDCOM-файлом дерева.

Любая запись делает бэкап в 3_research/tree_data/.ged_backups перед изменением.
Ручное редактирование .ged запрещено — формат строчно-иерархический,
одна сбитая строка ломает всё дерево.

Использование:
    python3 tools/scripts/gedcom_tool.py check [файл]
    python3 tools/scripts/gedcom_tool.py stats [файл]
    python3 tools/scripts/gedcom_tool.py find <строка>
    python3 tools/scripts/gedcom_tool.py show <@ID@>
    python3 tools/scripts/gedcom_tool.py dupes
    python3 tools/scripts/gedcom_tool.py merge <фрагмент.ged>
    python3 tools/scripts/gedcom_tool.py backup
    python3 tools/scripts/gedcom_tool.py restore
"""

import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from paths import ENRICHED_GED, GED_BACKUPS, ROOT  # корень дерева — папка с ftree.toml (paths.find_root)
MAIN = ENRICHED_GED
BACKUP_DIR = GED_BACKUPS

LINE_RE = re.compile(r"^(\d+)\s+(?:(@[^@]+@)\s+)?(\S+)(?:\s(.*))?$")
POINTER_RE = re.compile(r"^@[^@]+@$")


def read(path):
    return path.read_text(encoding="utf-8-sig").splitlines()


def parse(lines):
    """Возвращает список записей верхнего уровня: (id, tag, [строки])."""
    records, cur = [], None
    for raw in lines:
        line = raw.rstrip("\r")
        if not line.strip():
            continue
        m = LINE_RE.match(line)
        if not m:
            continue
        level = int(m.group(1))
        if level == 0:
            if cur:
                records.append(cur)
            cur = {"id": m.group(2), "tag": m.group(3), "lines": [line]}
        elif cur:
            cur["lines"].append(line)
    if cur:
        records.append(cur)
    return records


def cmd_check(path):
    lines = read(path)
    errors, warnings = [], []

    if not lines or not lines[0].startswith("0 HEAD"):
        errors.append("файл не начинается с '0 HEAD'")
    if not any(l.startswith("0 TRLR") for l in lines):
        errors.append("нет завершающей строки '0 TRLR'")

    prev_level = None
    continuations = 0
    for n, raw in enumerate(lines, 1):
        line = raw.rstrip("\r")
        if not line.strip():
            continue
        m = LINE_RE.match(line)
        if not m:
            # Строка без уровня = продолжение предыдущего значения.
            # MyHeritage так экспортирует многострочные заметки с HTML.
            # Формально это нарушение GEDCOM (нужны CONT/CONC), но файл рабочий.
            continuations += 1
            continue
        level = int(m.group(1))
        if prev_level is not None and level > prev_level + 1:
            errors.append(f"строка {n}: скачок уровня {prev_level} → {level}")
        prev_level = level

    if continuations:
        warnings.append(
            f"строк-продолжений без уровня: {continuations} "
            "(многострочные заметки MyHeritage; формально нужны теги CONT/CONC — "
            "на работу дерева не влияет, но при ручной правке легко порвать)"
        )

    records = parse(lines)
    ids = [r["id"] for r in records if r["id"]]
    seen = set()
    for i in ids:
        if i in seen:
            errors.append(f"дубль ID: {i}")
        seen.add(i)

    # битые ссылки
    defined = set(ids)
    for r in records:
        for line in r["lines"][1:]:
            m = LINE_RE.match(line)
            if not m:
                continue
            val = (m.group(4) or "").strip()
            if POINTER_RE.match(val) and val not in defined:
                warnings.append(f"{r['id'] or r['tag']}: ссылка на несуществующий {val}")

    print(f"Файл: {path}")
    print(f"Строк: {len(lines)}, записей верхнего уровня: {len(records)}")
    if errors:
        print(f"\n❌ ОШИБОК: {len(errors)}")
        for e in errors[:20]:
            print(f"   {e}")
    else:
        print("\n✅ Структура корректна")
    if warnings:
        print(f"\n⚠️  Предупреждений: {len(warnings)}")
        for w in warnings[:20]:
            print(f"   {w}")
    return 1 if errors else 0


def cmd_stats(path):
    records = parse(read(path))
    indi = [r for r in records if r["tag"] == "INDI"]
    fam = [r for r in records if r["tag"] == "FAM"]
    with_birth = sum(1 for r in indi if any(" BIRT" in l for l in r["lines"]))
    with_death = sum(1 for r in indi if any(" DEAT" in l for l in r["lines"]))
    with_sour = sum(1 for r in indi if any(" SOUR" in l for l in r["lines"]))
    print(f"Персон:  {len(indi)}")
    print(f"Семей:   {len(fam)}")
    print(f"С датой рождения: {with_birth} ({with_birth * 100 // max(len(indi), 1)}%)")
    print(f"С датой смерти:   {with_death} ({with_death * 100 // max(len(indi), 1)}%)")
    print(f"С источником:     {with_sour} ({with_sour * 100 // max(len(indi), 1)}%)")


def _name_of(rec):
    for line in rec["lines"]:
        m = LINE_RE.match(line)
        if m and m.group(3) == "NAME":
            return (m.group(4) or "").replace("/", "").strip()
    return "(без имени)"


def _date_of(rec, tag):
    inside = False
    for line in rec["lines"]:
        m = LINE_RE.match(line)
        if not m:
            continue
        if m.group(1) == "1":
            inside = m.group(3) == tag
        elif inside and m.group(3) == "DATE":
            return (m.group(4) or "").strip()
    return ""


def cmd_find(path, needle):
    records = parse(read(path))
    needle_low = needle.lower()
    found = 0
    for r in records:
        if r["tag"] != "INDI":
            continue
        name = _name_of(r)
        if needle_low in name.lower():
            b, d = _date_of(r, "BIRT"), _date_of(r, "DEAT")
            span = f"  {b} – {d}" if (b or d) else ""
            print(f"{r['id']:<12} {name}{span}")
            found += 1
    print(f"\nНайдено: {found}")


def cmd_show(path, ident):
    for r in parse(read(path)):
        if r["id"] == ident:
            print("\n".join(r["lines"]))
            return 0
    print(f"Не найдено: {ident}")
    return 1


def cmd_dupes(path):
    records = parse(read(path))
    buckets = defaultdict(list)
    for r in records:
        if r["tag"] != "INDI":
            continue
        name = _name_of(r)
        year = ""
        b = _date_of(r, "BIRT")
        ym = re.search(r"\b(1[6-9]\d\d|20\d\d)\b", b)
        if ym:
            year = ym.group(1)
        key = (re.sub(r"\s+", " ", name.lower()), year)
        buckets[key].append((r["id"], name, b))
    dupes = {k: v for k, v in buckets.items() if len(v) > 1 and k[0] != "(без имени)"}
    if not dupes:
        print("✅ Вероятных дублей не найдено")
        return 0
    print(f"⚠️  Вероятных дублей: {len(dupes)}\n")
    for (name, year), items in dupes.items():
        print(f"— {name} ({year or 'без года'}):")
        for i, n, b in items:
            print(f"     {i:<12} {n}  {b}")
    return 0


def cmd_backup(path=MAIN):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = BACKUP_DIR / f"{path.stem}_{stamp}.ged"
    shutil.copy2(path, dst)
    print(f"✅ Бэкап: {dst.relative_to(ROOT)}")
    return dst


def cmd_restore(path=MAIN):
    backups = sorted(BACKUP_DIR.glob(f"{path.stem}_*.ged"))
    if not backups:
        print("Бэкапов не найдено")
        return 1
    latest = backups[-1]
    shutil.copy2(latest, path)
    print(f"✅ Восстановлено из {latest.name}")
    return 0


def cmd_merge(path, fragment_path):
    fragment = Path(fragment_path)
    if not fragment.exists():
        print(f"Нет файла: {fragment}")
        return 1

    main_records = parse(read(path))
    frag_records = parse(read(fragment))

    main_ids = {r["id"] for r in main_records if r["id"]}
    new_records = [r for r in frag_records if r["tag"] in ("INDI", "FAM")]

    conflicts = [r["id"] for r in new_records if r["id"] in main_ids]
    if conflicts:
        print(f"❌ Конфликт ID — эти уже есть в дереве: {', '.join(conflicts[:10])}")
        print("   Переименуйте ID во фрагменте и повторите.")
        return 1

    cmd_backup(path)

    lines = read(path)
    trlr_idx = next(i for i, l in enumerate(lines) if l.startswith("0 TRLR"))
    insert = []
    for r in new_records:
        insert.extend(r["lines"])
    merged = lines[:trlr_idx] + insert + lines[trlr_idx:]
    path.write_text("\n".join(merged) + "\n", encoding="utf-8")

    n_indi = sum(1 for r in new_records if r["tag"] == "INDI")
    n_fam = sum(1 for r in new_records if r["tag"] == "FAM")
    print(f"✅ Влито: персон {n_indi}, семей {n_fam}")
    print("   Теперь проверьте: python3 tools/scripts/gedcom_tool.py check")
    print("   ⚠️  Связи с существующими персонами нужно проставить вручную в MyHeritage.")
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd == "check":
        return cmd_check(Path(args[0]) if args else MAIN)
    if cmd == "stats":
        return cmd_stats(Path(args[0]) if args else MAIN)
    if cmd == "find":
        if not args:
            print("Укажите строку поиска")
            return 1
        return cmd_find(MAIN, " ".join(args))
    if cmd == "show":
        if not args:
            print("Укажите @ID@")
            return 1
        return cmd_show(MAIN, args[0])
    if cmd == "dupes":
        return cmd_dupes(MAIN)
    if cmd == "merge":
        if not args:
            print("Укажите файл фрагмента")
            return 1
        return cmd_merge(MAIN, args[0])
    if cmd == "backup":
        cmd_backup()
        return 0
    if cmd == "restore":
        return cmd_restore()

    print(f"Неизвестная команда: {cmd}")
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
