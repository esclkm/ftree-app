#!/usr/bin/env python3
"""Перенаправить ссылки на старый общий источник («Doc17 — …») на карточки новых документов (навык card-rules, «Документы человека»).

Правила — YAML (2_transcripts/family_archive/remap/*.yaml): old — старые источники, rules — «регулярка → новая карточка».
Для каждой строки со ссылкой на старый источник (и по имени файла — для карточек-источников «press») берутся все
сработавшие правила; ссылка заменяется на «[[А]]; [[Б]]». В свойствах (`  - "[[Doc17…]]"`) — на все карточки, которые
ушли в тексте этого файла. Что не сработало — список; по нему правим руками или дописываем правило.

    tools/py tools/scripts/remap_doc_sources.py <rules.yaml>           # показать, что изменится
    tools/py tools/scripts/remap_doc_sources.py <rules.yaml> --apply   # записать
"""
import argparse
import re
import sys
from pathlib import Path

import yaml

import paths
from paths import ROOT

SKIP = (paths.SOURCES.name, paths.OUTPUTS.name, "node_modules", ".git", ".venv", "web", "tools")
NOT_NOTES = (Path(paths.rel(paths.TRANSCRIPTS_ARCHIVE)).parts, Path(paths.rel(paths.DOCUMENTS)).parts)


def md_files():
    for p in ROOT.rglob("*.md"):
        rel = p.relative_to(ROOT).parts
        if rel[0] in SKIP or rel[:2] in NOT_NOTES:
            continue
        yield p


def pages_after(line: str, pos: int) -> set:
    """Номера страниц из «стр. 7–8, 12» сразу за ссылкой (до следующей ссылки или «· уверенность»)."""
    tail = re.split(r"\[\[| · уверенность", line[pos:], maxsplit=1)[0]
    pages = set()
    pages.update(int(x) for x in re.findall(r"§\s*(\d+)", tail))  # «Архив Ясеневых, §2» — раздел как страница
    for group in re.findall(r"стр\.?\s*((?:\d+(?:\s*[–-]\s*\d+)?(?:\s*(?:,|;|и)\s*)?)+)", tail):
        for a, b in re.findall(r"(\d+)(?:\s*[–-]\s*(\d+))?", group):
            pages.update(range(int(a), int(b or a) + 1))
    return pages


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rules")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--show", action="store_true", help="для каждой строки — какие карточки выбраны")
    args = ap.parse_args()
    spec = yaml.safe_load(Path(args.rules).read_text(encoding="utf-8"))
    olds = spec["old"]
    rules = [(re.compile(r["match"]), r["to"], bool(r.get("stop"))) for r in spec["rules"] if "pages" not in r]
    # pages: [7, 8] — по номерам страниц PDF в «стр. …» сразу после ссылки (диапазоны «7–13» раскрываются); сильнее слов
    page_rules = [(set(r["pages"]), r["to"], re.compile(r.get("file", ""))) for r in spec["rules"] if "pages" in r]
    by_file = [(re.compile(r["match"]), r["to"], bool(r.get("exclusive"))) for r in spec.get("files", [])]
    # files: по имени карточки; exclusive — вместо правил по строке (подписанты: что подписал, то и источник)
    entry = re.compile(r"^- \[\[(?:%s)(?:\|[^\]]*)?\]\]" % "|".join(re.escape(o) for o in olds))
    tail_re = re.compile(r"(\s*· уверенность:.*)$")
    link = re.compile(r"\[\[(?:%s)(?:\|[^\]]*)?\]\]" % "|".join(re.escape(o) for o in olds))
    prop = re.compile(r'^(\s*-\s*)"\[\[(?:%s)(?:\|[^\]]*)?\]\]"\s*$' % "|".join(re.escape(o) for o in olds))
    keyed = re.compile(r'^(\w+): "\[\[(?:%s)(?:\|[^\]]*)?\]\]"\s*$' % "|".join(re.escape(o) for o in olds))
    changed, bad = 0, []
    for path in md_files():
        if path.stem in olds:
            continue
        text = path.read_text(encoding="utf-8")
        if not link.search(text):
            continue
        lines = text.split("\n")
        end = lines.index("---", 1) if lines[0] == "---" and "---" in lines[1:] else 0
        used, out, entries, used_of_line = [], list(lines), [], {}
        for i, line in enumerate(lines):
            if not link.search(line) or (i <= end and (prop.match(line) or keyed.match(line))):
                continue
            bare = link.sub("", line)  # название самого старого источника («…трудовая книжка, дипломы…») правила путает
            kw = [to for rx, to, ex in by_file if ex and rx.search(path.stem)]
            for rx, to, stop in ([] if kw else rules):
                if rx.search(bare):
                    kw.append(to)
                    if stop:
                        break
            if not kw:
                kw = [to for rx, to, ex in by_file if rx.search(path.stem)]
            line_hits, missing = [], []

            def repl(m, line=line, kw=kw):
                pg = pages_after(line, m.end())
                by_page = [to for pgs, to, frx in page_rules if pgs & pg and frx.search(path.stem)]
                h = (kw or by_page) if spec.get("prefer_keywords") else (by_page or kw)
                if not h:
                    missing.append(1)
                    return m[0]
                line_hits.extend(x for x in h if x not in line_hits)
                return "; ".join(f"[[{x}]]" for x in h)

            newline = link.sub(repl, line)
            if missing:
                bad.append(f"{path.relative_to(ROOT)}:{i + 1}: {line.strip()[:170]}")
                continue
            hit = line_hits
            if args.show:
                print(f"   {path.stem[:28]}:{i + 1} → {' + '.join(h.split(' — ')[0][:30] for h in hit)} | {line.strip()[:110]}")
            used += [h for h in hit if h not in used]
            used_of_line[i] = hit
            out[i] = newline
            if entry.match(line):  # строка «Источники»: описание «стр. …» устарело — по строке на новую карточку
                entries.append((i, line))
        for i, line in entries:
            tail = (tail_re.search(line) or [None, ""])[1]
            out[i] = "\n".join(f"- [[{h}]]{tail}" for h in used_of_line[i])
        emitted = set()
        for i in range(end + 1):
            m = prop.match(lines[i]) if i <= end else None
            k = keyed.match(lines[i]) if i <= end else None
            if not (m or k):
                continue
            hit = used or [to for rx, to, _ in rules if rx.search(path.stem)]
            if not hit:
                bad.append(f"{path.relative_to(ROOT)}:{i + 1}: свойство без текста для вывода — {lines[i].strip()}")
                continue
            if m:
                new = [h for h in hit if f'{m[1]}"[[{h}]]"' not in emitted]  # свойства Doc17 и Doc25 дают одни и те же карточки
                emitted.update(f'{m[1]}"[[{h}]]"' for h in new)
                out[i] = "\n".join(f'{m[1]}"[[{h}]]"' for h in new) if new else None
            else:
                out[i] = f'{k[1]}: "[[{hit[0]}]]"'
        new = "\n".join(x for x in out if x is not None)
        if new != text:
            changed += 1
            print(f"{path.relative_to(ROOT)}: {len(used)} карточек новых документов")
            if args.apply:
                path.write_text(new, encoding="utf-8")
    print(f"Файлов изменено: {changed}; не сработало правило: {len(bad)}")
    for b in bad:
        print("  ?", b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
