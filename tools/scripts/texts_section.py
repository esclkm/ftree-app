#!/usr/bin/env python3
"""Раздел «Тексты: статьи, автобиографии, воспоминания» в карточках людей.

Берёт заметки-источники с полем `principals` (о ком текст) — статьи, автобиографии, интервью, рукописи,
письма (3_research/tree/sources/press/ и другие) — и у каждого названного человека пересобирает раздел
«## Тексты: …» перед «## Источники». Здесь же — раздел «## Рассказ»: свёрнутое встраивание собственного раздела биографии человека.
Раздел создаётся заново при каждом запуске — руками его не правим;
чтобы текст появился у человека, впишите человека в `principals` заметки-источника.

Запуск: python3 tools/scripts/texts_section.py
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

HEAD = "## Тексты: статьи, автобиографии, воспоминания"
STORY = "## Рассказ"
KIND = {"newspaper": "газета", "magazine": "журнал", "autobiography": "автобиография", "interview": "интервью",
        "manuscript": "рукопись", "letter": "письмо", "book": "книга", "memoir": "воспоминания"}


def fm(text):
    m = re.match(r"---\n(.*?)\n---", text, re.S)
    return m.group(1) if m else ""


def field(f, key):
    m = re.search(rf'^{key}: *"?([^"\n]*)"?$', f, re.M)
    return m.group(1).strip() if m else ""


def main():
    by_person = defaultdict(list)
    for p in sorted((paths.TREE / "sources").rglob("*.md")):
        f = fm(p.read_text(encoding="utf-8"))
        m = re.search(r"^principals:(.*(?:\n  - .*)*)", f, re.M)
        if not m:
            continue
        date, kind = field(f, "date"), KIND.get(field(f, "source_type"), field(f, "source_type"))
        pub, author = field(f, "publication"), field(f, "author")
        line = f"- [[{p.stem}]]" + "".join(f" · {x}" for x in (kind, pub, date, author) if x)
        for who in re.findall(r"\[\[([^\]|]+)", m.group(1)):
            by_person[who].append((date or "9999", line))

    changed = 0
    for p in (paths.TREE / "people").glob("*.md"):
        t = p.read_text(encoding="utf-8")
        t2 = re.sub(rf"\n{re.escape(HEAD)}\n.*?(?=\n## |\Z)", "", t, flags=re.S)
        t2 = re.sub(rf"\n{re.escape(STORY)}\n.*?(?=\n## |\Z)", "", t2, flags=re.S)
        # «Рассказ»: свёрнутое встраивание раздела биографии — только если раздел про этого человека
        # (в заголовке есть его имя); текст остаётся в биографии, в карточку не копируется
        name = (re.search(r'^name: *"?([^"\n]*)', t2, re.M) or [None, ""])[1]
        first = name.split()[0] if name.split() else ""
        story = []
        for target, heading in re.findall(r"\*\*Биография:\*\*[^\n]*?\[\[([^\]|#]+)#([^\]|]+)\]\]", t2):
            # имя — целым словом («Иван» ↔ «Ивана» годится; «Прокоп» ↔ «Прохор» — нет)
            words = re.findall(r"\w+", heading.lower())
            if first and len(first) > 2 and any(w.startswith(first.lower()) or first.lower().startswith(w)
                                                for w in words if len(w) > 2):
                story.append(f"> [!quote]- Из биографии: {heading.strip()} (развернуть)\n> ![[{target}#{heading}]]")
        # ссылка на биографию целиком (без #раздела): одна биография — один человек, файл весь про него
        # («Иван Ясенев — биография»: имя файла — имя карточки)
        for target in re.findall(r"\*\*Биография:\*\*[^\n]*?\[\[([^\]|#]+)\]\]", t2):
            if "/biographies/" in target:
                story.append(f"> [!quote]- Биография: {Path(target).stem} (развернуть)\n> ![[{target}]]")
        if story:
            block = f"\n{STORY}\n\n" + "\n\n".join(story) + "\n"
            for anchor in (f"\n{HEAD}\n", "\n## Источники\n"):
                if anchor in t2:
                    t2 = t2.replace(anchor, block + anchor, 1)
                    break
            else:
                t2 = t2.rstrip("\n") + "\n" + block
        items = [l for _, l in sorted(by_person.get(p.stem, []))]
        if items:
            block = f"\n{HEAD}\n\n" + "\n".join(items) + "\n"
            t2 = t2.replace("\n## Источники\n", block + "\n## Источники\n", 1) if "\n## Источники\n" in t2 \
                else t2.rstrip("\n") + "\n" + block
        if t2 != t:
            p.write_text(t2, encoding="utf-8")
            changed += 1
    print(f"Тексты: людей с текстами {len(by_person)}, карточек изменено {changed}")


if __name__ == "__main__":
    main()
