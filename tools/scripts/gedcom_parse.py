#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Парсер GEDCOM-файла, экспортированного из MyHeritage (Family Tree Builder 5.5.1).

Решает две известные особенности экспорта MyHeritage:
  1. Длинные текстовые значения (HTML-заметки) разрываются тегом CONC
     ПОСЕРЕДИНЕ многобайтового UTF-8 символа -> сначала склеиваем на уровне байтов.
  2. В файле смешаны разделители строк CRLF и NEL (U+0085, в UTF-8 — C2 85); одиночный байт 0x85 — часть буквы «х».

Извлекает: персоны (INDI), семьи (FAM), источники (SOUR), медиа (OBJE).
Строит прямую родословную линию от заданной персоны.

Вывод (в папку 3_research/tree_data/):
  persons.json        — все персоны со связями
  persons.csv         — табличный список персон
  families.json       — семьи
  sources.json        — источники
  media.csv           — список медиафайлов (фото/документы) с URL
  completeness.json   — статистика полноты данных (для поиска пробелов)

Использование:
  python3 tools/scripts/gedcom_parse.py [путь_к_ged] [--root @I1@]   (без --root — первый человек в файле)
"""
import sys, re, json, csv, os, argparse
from collections import defaultdict, Counter

import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import paths as P_
OUT_DIR = str(P_.TREE_DATA)


# Перевод строки в GEDCOM: CRLF, LF, CR и NEL (U+0085, в UTF-8 — два байта C2 85). Одиночный байт 0x85 — НЕ разделитель:
# это второй байт буквы «х» (D1 85), «Х» — D0 A5 … В выгрузке MyHeritage 0x85 встречается только внутри «х» (05.11.2026:
# 120 из 120); прежнее правило [\r\n\x85]+ склеивало CONC и съедало «х», если она стояла прямо перед разрывом.
EOL_BYTES = rb"(?:\r\n|\r|\n|\xc2\x85)"
EOL = re.compile(r"\r\n|\r|\n|\x85")


def load_lines(path):
    """Читает GEDCOM, чинит CONC-разрывы на уровне байтов, возвращает логические строки.
    CONC режет длинное значение где попало — и посреди многобайтовой буквы, поэтому склеиваем байты до декодирования."""
    with open(path, "rb") as f:
        raw = f.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    # Склеиваем CONC: убираем (перевод строки + 'N CONC ') -> прямое соединение
    raw = re.sub(EOL_BYTES + rb"\d+ CONC ?", b"", raw)
    text = raw.decode("utf-8")
    return [l for l in EOL.split(text) if l.strip()]


def fold_cont(lines):
    """CONT — продолжение значения с новой строки: «2 CONT вторая строка» → к значению строки выше через перевод строки."""
    out = []
    for line in lines:
        m = re.match(r"^\d+ CONT ?(.*)$", line)
        if m and out:
            out[-1] += "\n" + m.group(1)
        else:
            out.append(line)
    return out


def parse_line(line):
    """Разбирает строку GEDCOM -> (level, xref, tag, value)."""
    m = re.match(r"^(\d+)\s+(@[^@]+@)?\s*(\S+)(?:\s(.*))?$", line, re.S)
    if not m:
        return None
    level = int(m.group(1))
    xref = m.group(2)
    tag = m.group(3)
    value = m.group(4) or ""
    return level, xref, tag, value


def build_tree(lines):
    """Группирует плоские строки в записи верхнего уровня (level 0) с вложенностью."""
    records = []
    stack = []  # стек узлов по уровням
    for line in lines:
        p = parse_line(line)
        if not p:
            continue
        level, xref, tag, value = p
        node = {"tag": tag, "xref": xref, "value": value, "children": []}
        if level == 0:
            records.append(node)
            stack = [node]
        else:
            # обрезаем стек до нужной глубины
            while len(stack) > level:
                stack.pop()
            if stack:
                stack[-1]["children"].append(node)
            stack.append(node)
    return records


def get_child(node, tag):
    for c in node["children"]:
        if c["tag"] == tag:
            return c
    return None


def get_children(node, tag):
    return [c for c in node["children"] if c["tag"] == tag]


def event_info(node, tag):
    """Возвращает {date, place} для события (BIRT/DEAT/MARR/BURI)."""
    ev = get_child(node, tag)
    if not ev:
        return None
    d = get_child(ev, "DATE")
    p = get_child(ev, "PLAC")
    info = {}
    if d:
        info["date"] = d["value"]
    if p:
        info["place"] = p["value"]
    caus = get_child(ev, "CAUS")
    if caus:
        info["cause"] = caus["value"]
    return info or {"_present": True}


def parse_individuals(records):
    persons = {}
    for r in records:
        if r["tag"] != "INDI":
            continue
        pid = r["xref"]
        name_node = get_child(r, "NAME")
        full = name_node["value"].replace("/", "").strip() if name_node else ""
        given = surname = ""
        marnm = []
        if name_node:
            g = get_child(name_node, "GIVN")
            s = get_child(name_node, "SURN")
            given = g["value"] if g else ""
            surname = s["value"] if s else ""
            marnm = [m["value"] for m in get_children(name_node, "_MARNM")]
        sex = get_child(r, "SEX")
        media = []
        for obje in get_children(r, "OBJE"):
            f = get_child(obje, "FILE")
            t = get_child(obje, "TITL")
            if f:
                media.append({"file": f["value"], "title": t["value"] if t else ""})
        sources = []
        for s in get_children(r, "SOUR"):
            page = get_child(s, "PAGE")
            sources.append({"ref": s["value"], "page": page["value"] if page else ""})
        notes = [n["value"] for n in get_children(r, "NOTE")]
        resi = get_child(r, "RESI")
        email = None
        if resi:
            e = get_child(resi, "EMAIL")
            email = e["value"] if e else None
        persons[pid] = {
            "id": pid,
            "name": full,
            "given": given,
            "surname": surname,
            "married_names": marnm,
            "sex": sex["value"] if sex else "",
            "birth": event_info(r, "BIRT"),
            "death": event_info(r, "DEAT"),
            "burial": event_info(r, "BURI"),
            "occupation": (get_child(r, "OCCU") or {}).get("value"),
            "education": (get_child(r, "EDUC") or {}).get("value"),
            "religion": (get_child(r, "RELI") or {}).get("value"),
            "description": (get_child(r, "DSCR") or {}).get("value"),
            "email": email,
            "media": media,
            "media_count": len(media),
            "sources": sources,
            "notes": notes,
            "famc": [c["value"] for c in get_children(r, "FAMC")],  # семья-родители
            "fams": [c["value"] for c in get_children(r, "FAMS")],  # семья-супруги
        }
    return persons


def parse_families(records):
    fams = {}
    for r in records:
        if r["tag"] != "FAM":
            continue
        fid = r["xref"]
        husb = get_child(r, "HUSB")
        wife = get_child(r, "WIFE")
        fams[fid] = {
            "id": fid,
            "husband": husb["value"] if husb else None,
            "wife": wife["value"] if wife else None,
            "children": [c["value"] for c in get_children(r, "CHIL")],
            "marriage": event_info(r, "MARR"),
            "divorce": event_info(r, "DIV"),
        }
    return fams


def parse_sources(records):
    srcs = {}
    for r in records:
        if r["tag"] != "SOUR":
            continue
        sid = r["xref"]
        srcs[sid] = {
            "id": sid,
            "title": (get_child(r, "TITL") or {}).get("value"),
            "author": (get_child(r, "AUTH") or {}).get("value"),
            "publication": (get_child(r, "PUBL") or {}).get("value"),
            "type": (get_child(r, "_TYPE") or {}).get("value"),
        }
    return srcs


def parents_of(pid, persons, fams):
    """Возвращает (father_id, mother_id) для персоны."""
    p = persons.get(pid)
    if not p or not p["famc"]:
        return None, None
    fam = fams.get(p["famc"][0])
    if not fam:
        return None, None
    return fam["husband"], fam["wife"]


def direct_line(root, persons, fams):
    """Строит прямую восходящую линию предков (BFS по поколениям)."""
    generations = []
    current = [(root, "пробанд")]
    seen = set()
    gen = 0
    labels_m = {0: "пробанд", 1: "отец", 2: "дед", 3: "прадед", 4: "прапрадед", 5: "прапрапрадед"}
    labels_f = {1: "мать", 2: "бабушка", 3: "прабабушка", 4: "прапрабабушка", 5: "прапрапрабабушка"}
    while current and gen < 8:
        gen_list = []
        nxt = []
        for pid, rel in current:
            if pid in seen or pid not in persons:
                continue
            seen.add(pid)
            gen_list.append({"id": pid, "relation": rel, "person": persons[pid]})
            f, m = parents_of(pid, persons, fams)
            if f:
                nxt.append((f, labels_m.get(gen + 1, f"предок-{gen+1}")))
            if m:
                nxt.append((m, labels_f.get(gen + 1, f"предок-{gen+1}")))
        if gen_list:
            generations.append({"generation": gen, "members": gen_list})
        current = nxt
        gen += 1
    return generations


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ged", nargs="?", default=None)
    ap.add_argument("--root", default=None, help="от кого прямая линия; по умолчанию — первый человек в файле")
    args = ap.parse_args()

    ged = args.ged
    if not ged:
        ged = str(P_.MYHERITAGE_GED)

    os.makedirs(OUT_DIR, exist_ok=True)
    lines = fold_cont(load_lines(ged))
    records = build_tree(lines)
    persons = parse_individuals(records)
    fams = parse_families(records)
    srcs = parse_sources(records)

    # --- запись JSON ---
    json.dump(list(persons.values()), open(os.path.join(OUT_DIR, "persons.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    json.dump(list(fams.values()), open(os.path.join(OUT_DIR, "families.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    json.dump(list(srcs.values()), open(os.path.join(OUT_DIR, "sources.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    # --- persons.csv ---
    with open(os.path.join(OUT_DIR, "persons.csv"), "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "name", "sex", "birth_date", "birth_place",
                    "death_date", "death_place", "media", "sources", "famc", "fams"])
        for p in persons.values():
            b = p["birth"] or {}
            d = p["death"] or {}
            w.writerow([p["id"], p["name"], p["sex"], b.get("date", ""), b.get("place", ""),
                        d.get("date", ""), d.get("place", ""), p["media_count"], len(p["sources"]),
                        ";".join(p["famc"]), ";".join(p["fams"])])

    # --- media.csv ---
    with open(os.path.join(OUT_DIR, "media.csv"), "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["person_id", "person_name", "title", "url"])
        for p in persons.values():
            for m in p["media"]:
                w.writerow([p["id"], p["name"], m["title"], m["file"]])

    # --- статистика полноты ---
    total = len(persons)
    stats = {
        "total_persons": total,
        "total_families": len(fams),
        "total_sources": len(srcs),
        "with_birth_date": sum(1 for p in persons.values() if (p["birth"] or {}).get("date")),
        "with_birth_place": sum(1 for p in persons.values() if (p["birth"] or {}).get("place")),
        "with_death_date": sum(1 for p in persons.values() if (p["death"] or {}).get("date")),
        "with_media": sum(1 for p in persons.values() if p["media_count"] > 0),
        "with_sources": sum(1 for p in persons.values() if p["sources"]),
        "with_occupation": sum(1 for p in persons.values() if p["occupation"]),
        "no_parents_linked": sum(1 for p in persons.values() if not p["famc"]),
    }
    json.dump(stats, open(os.path.join(OUT_DIR, "completeness.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    # --- прямая линия ---
    args.root = args.root or next(iter(persons), None)
    line = direct_line(args.root, persons, fams)
    json.dump(line, open(os.path.join(OUT_DIR, "direct_line.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    # --- консольный отчёт ---
    print("=" * 60)
    print("РАСПАРСЕНО:", total, "персон,", len(fams), "семей,", len(srcs), "источников")
    print("=" * 60)
    for k, v in stats.items():
        print(f"  {k:22} {v}")
    print("\nПРЯМАЯ ЛИНИЯ ПРЕДКОВ (от", persons.get(args.root, {}).get("name", args.root), "):")
    for g in line:
        for m in g["members"]:
            p = m["person"]
            b = (p["birth"] or {}).get("date", "?")
            d = (p["death"] or {}).get("date", "")
            bp = (p["birth"] or {}).get("place", "")
            yrs = f"{b}–{d}" if d else b
            print(f"  [{g['generation']}] {m['relation']:12} {p['name']:28} {yrs:20} {bp}")


if __name__ == "__main__":
    main()
