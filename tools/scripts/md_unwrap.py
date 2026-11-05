#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Распрямляет «жёсткие» переносы в markdown: один абзац -> одна строка.

Зачем: если абзац в исходнике разбит переносами на ~100 символов, часть рендереров
(и наш сборщик PDF в прежней версии) принимает каждую строку за отдельный абзац —
текст рассыпается, а **жирный**, начатый на одной строке и закрытый на другой,
превращается в литеральные звёздочки. Правка у источника лечит это для всех
рендереров сразу: GitHub, Obsidian, pandoc, наш HTML.

Что НЕ трогает: таблицы, блоки ``` ... ```, заголовки, разделители ---, пустые строки.
Что склеивает: абзацы, пункты списков (вместе со строками-продолжениями), цитаты >.

Запуск:
  python3 tools/scripts/md_unwrap.py 3_research/tree/biographies/*.md
  python3 tools/scripts/md_unwrap.py --check 3_research/tree/biographies/*.md   # только показать, что изменится
"""
import re, sys, os


def is_block_start(s):
    t = s.strip()
    if t in ("", "---"):
        return True
    return bool(
        t.startswith("```") or t.startswith("|") or t.startswith(">")
        or re.match(r"^#{1,6}\s", t) or re.match(r"^[-*]\s+", t)
        or re.match(r"^\d+\.\s+", t)
    )


def unwrap(text):
    lines = text.split("\n")
    out, i = [], 0
    while i < len(lines):
        ln = lines[i]
        # блоки кода — как есть
        if ln.strip().startswith("```"):
            out.append(ln); i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                out.append(lines[i]); i += 1
            if i < len(lines):
                out.append(lines[i]); i += 1
            continue
        # таблицы, заголовки, разделители, пустые — как есть
        if ln.strip().startswith("|") or re.match(r"^#{1,6}\s", ln.strip()) \
           or ln.strip() == "---" or ln.strip() == "":
            out.append(ln); i += 1; continue
        # цитата: склеиваем подряд идущие > в один абзац цитаты,
        # пустая строка внутри цитаты (">") сохраняет разрыв
        if ln.startswith(">"):
            buf = []

            def flush():
                if buf:
                    out.append("> " + " ".join(buf))
                    buf.clear()

            while i < len(lines) and lines[i].startswith(">"):
                body = lines[i].lstrip(">").strip()
                if body == "":
                    flush(); out.append(">")
                elif re.match(r"^([-*]|\d+\.)\s+", body) or re.match(r"^#{1,6}\s", body) \
                        or body.startswith("|"):
                    # список / заголовок / таблица внутри цитаты — своя строка,
                    # иначе структура схлопнется в один абзац
                    flush(); buf.append(body)
                    # строки-продолжения этого пункта приклеиваем к нему
                    i += 1
                    while i < len(lines) and lines[i].startswith(">"):
                        nxt = lines[i].lstrip(">").strip()
                        if nxt == "" or re.match(r"^([-*]|\d+\.)\s+", nxt) \
                           or re.match(r"^#{1,6}\s", nxt) or nxt.startswith("|"):
                            break
                        buf.append(nxt); i += 1
                    flush()
                    continue
                else:
                    buf.append(body)
                i += 1
            flush()
            continue
        # пункт списка + его строки-продолжения
        m = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)", ln)
        if m:
            indent, marker, first = m.group(1), m.group(2), m.group(3)
            buf = [first]; i += 1
            while i < len(lines) and not is_block_start(lines[i]):
                buf.append(lines[i].strip()); i += 1
            out.append(f"{indent}{marker} " + " ".join(buf)); continue
        # обычный абзац
        buf = [ln.strip()]; i += 1
        while i < len(lines) and not is_block_start(lines[i]):
            buf.append(lines[i].strip()); i += 1
        out.append(" ".join(buf))
    return "\n".join(out)


if __name__ == "__main__":
    args = sys.argv[1:]
    check = "--check" in args
    paths = [a for a in args if a != "--check"]
    if not paths:
        print(__doc__); sys.exit(1)
    changed = 0
    for p in paths:
        if not os.path.isfile(p):
            continue
        src = open(p, encoding="utf-8").read()
        dst = unwrap(src)
        if src == dst:
            print(f"  = {p}")
            continue
        changed += 1
        before = len(src.split("\n"))
        after = len(dst.split("\n"))
        print(f"  ~ {p}: строк {before} -> {after}")
        if not check:
            open(p, "w", encoding="utf-8").write(dst)
    print(("Изменилось файлов: " if not check else "Изменилось бы файлов: ") + str(changed))
