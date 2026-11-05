#!/usr/bin/env python3
"""Биография ↔ карточка — по имени: `3_research/tree/biographies/<Имя карточки> — биография.md`.

Чья биография — говорит имя файла (правила — шапка tools/scripts/cards/biographies.py). Всё, что из имени следует,
этот скрипт приводит в порядок сам:

  1. карточку переименовали (в Obsidian или руками) — биография и её переводы (`translations/<язык>/<Имя>.md`)
     переименовываются следом; человека узнаём по person_id в свойствах; ссылки на старое имя по проекту — на новое;
  2. свойства в начале файла: person (ссылка на карточку), person_id (cr_id), gedcom_id (MyHeritage) — текст
     биографии не меняется, отпечаток для переводов остаётся прежним;
  3. строка в карточке `**Биография:** [[3_research/tree/biographies/<Имя> — биография.md]]` (панель обратных ссылок
     Obsidian и «Рассказ»); другие ссылки в той же строке (вторая биография-заметка) — сохраняются.

  python3 tools/scripts/bio_ids.py          # что не так (то же видит check_cards.py)
  python3 tools/scripts/bio_ids.py --fix    # починить (так зовут pre-commit, sync.py, и хук после правки)
"""
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cards  # noqa: E402
import paths  # noqa: E402
from cards.biographies import SUFFIX, gedcom_of, owner_stem  # noqa: E402
from cards.notes import N  # noqa: E402

KEYS = ("person", "person_id", "gedcom_id")
FIX = "--fix" in sys.argv
LINE = re.compile(r"^\*\*Биография:\*\*[^\n]*$", re.M)
LINK = re.compile(r"\[\[([^\]|#]+)[^\]]*\]\]")
TEXT_DIRS = (*map(paths.rel, (paths.RESEARCH, paths.TRANSCRIPTS, paths.OUTPUTS_PAVEL, paths.OUTPUTS_ARGENTINA)), ".claude/skills")


def with_ids(text, values):
    """Текст файла с этими свойствами: есть блок свойств — обновить в нём, нет — поставить в начало."""
    lines = [f"{k}: {v}" for k, v in values.items()]
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m:
        return "---\n" + "\n".join(lines) + "\n---\n" + text
    kept = [l for l in m[1].splitlines() if not re.match(rf"({'|'.join(KEYS)}):", l)]
    return "---\n" + "\n".join(lines + kept) + "\n---\n" + text[m.end():]


def move(src, dst):
    """git mv, если файл под git, иначе просто переименовать."""
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", str(src)], cwd=paths.ROOT,
                             capture_output=True).returncode == 0
    if tracked:
        subprocess.run(["git", "mv", str(src), str(dst)], cwd=paths.ROOT, check=True)
    else:
        src.rename(dst)


def relink(old, new):
    """Ссылки и упоминания «<old> — биография» по текстам проекта → «<new> — биография»."""
    a, b = f"{old}{SUFFIX}", f"{new}{SUFFIX}"
    n = 0
    for d in TEXT_DIRS:
        for p in (paths.ROOT / d).rglob("*.md"):
            t = p.read_text(encoding="utf-8")
            if a in t:
                p.write_text(t.replace(a, b), encoding="utf-8")
                n += 1
    return n


def card_line(body, rel):
    """Тело карточки со строкой «**Биография:** [[rel]]»: чужую биографию-ссылку в строке — заменить, остальные сохранить."""
    want = f"[[{rel}]]"
    m = LINE.search(body)
    if m:
        links = [x.group(0) for x in LINK.finditer(m.group(0))]
        keep = [l for l in links if "/biographies/" not in l and SUFFIX not in l]
        new = "**Биография:** " + ", ".join([want] + keep)
        return body[:m.start()] + new + body[m.end():]
    line = f"**Биография:** {want}\n"
    if "## Факты и заметки\n" in body:
        i = body.index("## Факты и заметки\n") + len("## Факты и заметки\n")
        return body[:i] + "\n" + line + body[i:]
    line = "## Факты и заметки\n\n" + line   # раздела нет — заводим: строка «Биография» живёт в нём (образец карточки)
    for anchor in ("## Рассказ\n", "## Тексты: статьи, автобиографии, воспоминания\n", "## Источники\n"):
        if anchor in body:
            i = body.index(anchor)
            return body[:i] + line + "\n" + body[i:]
    return body.rstrip("\n") + "\n\n" + line


def main():
    out = []
    tree = cards.load()
    # 1. переименования вслед за карточкой
    for f in sorted(paths.BIOS.glob(f"*{SUFFIX}.md")):
        stem = owner_stem(f)
        if any(N(p.stem) == stem for p in tree.people.values()):
            continue
        pid = (cards.notes.read_note(f).fm or {}).get("person_id")
        p = tree.people.get(pid)
        if not p:
            continue  # биография без человека — только сказать (check_cards.py)
        dst = paths.bio_path(p.stem)
        out.append(f"переименовать: {f.name} → {dst.name}")
        if FIX:
            move(f, dst)
            for lang in paths.TRANSLATIONS.glob("*/"):
                for kind in ("biographies", "facts"):
                    tf = paths.tr_path(lang.name, kind, stem)
                    if tf.exists():
                        move(tf, paths.tr_path(lang.name, kind, p.stem))
            out.append(f"  ссылки поправлены в {relink(stem, p.stem)} файлах")
    if FIX and any(x.startswith("переименовать") for x in out):
        tree = cards.load()
    # 2. свойства, 3. строка в карточке
    for rel, pid in tree.biographies.items():
        if not pid:
            continue
        p = tree.people[pid]
        values = {"person": f'"[[{p.stem}]]"', "person_id": pid}
        if gedcom_of(p):
            values["gedcom_id"] = gedcom_of(p)
        f = paths.ROOT / rel
        text = N(f.read_text(encoding="utf-8"))
        new = with_ids(text, values)
        if new != text:
            out.append(f"свойства: {rel}")
            if FIX:
                f.write_text(new, encoding="utf-8")
        cp = paths.TREE / "people" / f"{p.stem}.md"
        ct = N(cp.read_text(encoding="utf-8"))
        cn = card_line(ct, rel)
        if cn != ct:
            out.append(f"строка «Биография:» в карточке {p.stem}")
            if FIX:
                cp.write_text(cn, encoding="utf-8")
    verb = "Поправлено" if FIX else "Нужно поправить"
    n = sum(1 for x in tree.biographies.values() if x)
    print(f"Биографий: {n}; {verb.lower()}: {sum(1 for x in out if not x.startswith('  '))}")
    for x in out:
        print("  ", x)
    return 1 if out and not FIX else 0


if __name__ == "__main__":
    sys.exit(main())
