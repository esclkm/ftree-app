#!/usr/bin/env python3
"""Замеры для фото-линз самопроверки (скилл self-review, линзы Ф1–Ф5). Ничего не чинит — только считает и показывает.

Проверки дерева (check_tree, card_doctor) смотрят на строки `media` в карточках. Сами файлы на этажах 1–2 они не
видят: копию, у которой нет хозяина, снимок без подписи, документ живого человека, который сайт покажет всем. Здесь —
именно это:

  Ф1  точные копии (байт в байт) и копии macOS «… 2.jpg»; «≈» — оригинал из _originals/ и его копия (сверить с описью);
  Ф3  семейные снимки, на которые не ссылается ни один .md — ни карточка, ни опись («кого ещё опознать»);
  Ф5  документы живых (паспорт, свидетельство, аттестат, удостоверение…) в `media` карточки — сайт отдаёт их только по
      паролю (site_export.doc_scans_of_living); здесь — какие это снимки и закрыты ли они в собранном сайте;
      и оригиналы с координатами съёмки (GPS) в служебных данных.

Живой — как на сайте (site_export.lifespan): нет года и даты смерти, и родился меньше 100 лет назад.

  python3 tools/scripts/review_photos.py            # всё
  python3 tools/scripts/review_photos.py --changed  # только снимки, ещё не закоммиченные (новые и изменённые)
"""
import datetime
import hashlib
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

IMG = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".tif", ".tiff"}
# тот же список слов — site_export.DOC_SCAN: поменял здесь — поменяй там
DOC_WORDS = re.compile(r"паспорт|свидетельство|аттестат|удостоверение|диплом|трудов|военн[ыо]|cédula|cedula|\bdni\b", re.I)


def images():
    for base in (paths.SOURCES, paths.PHOTOS_PROCESSED):
        for p in base.rglob("*"):
            if p.suffix.lower() in IMG and "social_export" not in p.as_posix():
                yield p


def changed():
    out = subprocess.run(["git", "-c", "core.quotePath=false", "status", "--porcelain", "-uall"], cwd=paths.ROOT,
                         capture_output=True, text=True).stdout
    return {(paths.ROOT / line[3:].strip('"')).resolve() for line in out.splitlines()}


def rel(p):
    return p.relative_to(paths.ROOT).as_posix()


def alive(fm):
    if re.search(r"^died:[ \t]*\S", fm, re.M):
        return False
    m = re.search(r"^born:[ \t]*\D*?(\d{4})", fm, re.M)
    return bool(m) and int(m.group(1)) >= datetime.date.today().year - 100


def main():
    only = changed() if "--changed" in sys.argv else None
    imgs = [p for p in images() if only is None or p.resolve() in only]
    print(f"Снимков в проверке: {len(imgs)}" + (" (не закоммиченные)" if only is not None else ""))

    by_hash = defaultdict(list)
    for p in images():  # копию ищем среди всех, даже если проверяем только новые
        by_hash[hashlib.md5(p.read_bytes()).hexdigest()].append(p)
    mine = {p.resolve() for p in imgs}
    dups = [g for g in by_hash.values() if len(g) > 1 and any(p.resolve() in mine for p in g)]
    mac = [p for p in imgs if re.search(r" \d+$", p.stem)]
    print(f"\nФ1 точные копии — групп {len(dups)}; копий macOS «… 2» — {len(mac)}")
    for g in dups:  # присланный оригинал в _originals/ и его переименованная копия — так задумано, если есть в описи
        mark = "   ≈ " if any("/_originals/" in p.as_posix() for p in g) else "   = "
        print(mark + "  |  ".join(rel(p) for p in g))
    for p in mac:
        print("   2 " + rel(p))

    text = []
    for p in paths.ROOT.rglob("*.md"):
        s = p.as_posix()
        if "node_modules" not in s and "/4_outputs/site/" not in s:
            text.append(p.read_text(encoding="utf-8", errors="ignore"))
    text = "\n".join(text)
    def mentioned(p):  # по имени, без расширения или по хвосту имени («WA0016» в описи папки _originals)
        tail = re.split(r"[-_ ]", p.stem)[-1]
        return p.name in text or p.stem in text or (len(tail) >= 5 and not tail.isdigit() and tail in text)
    orphans = [p for p in imgs if p.is_relative_to(paths.FAMILY) and not mentioned(p)]
    print(f"\nФ3 семейные снимки без единой ссылки из .md — {len(orphans)}")
    for p in orphans:
        print("   · " + rel(p))

    risky = []
    for card in sorted((paths.TREE / "people").glob("*.md")):
        s = card.read_text(encoding="utf-8")
        fm = s.split("\n---", 1)[0]
        if not alive(fm):
            continue
        media = re.findall(r"^\s*-\s*\"?\[\[([^\]|]+)", fm.split("\nmedia:", 1)[1], re.M) if "\nmedia:" in fm else []
        for m in media:
            if Path(m).suffix.lower() in IMG and DOC_WORDS.search(m):
                risky.append((card.stem, m))
    mw = paths.SITE / "functions" / "_middleware.js"
    locked = mw.read_text(encoding="utf-8") if mw.exists() else None
    print(f"\nФ5 документы живых в галерее карточки — {len(risky)}"
          + ("" if locked is not None else " (сайт не собран — закрыты ли паролем, не проверить)"))
    for who, m in risky:
        site_name = re.sub(r"[^\w.-]", "_", Path(m).stem)  # как называет site_export.photo (без номера дома)
        mark = "?" if locked is None else ("🔒" if f"/media/{site_name}" in locked else "! ОТКРЫТ")
        print(f"   {mark} {who}: {m}")

    try:
        from PIL import Image
    except ImportError:
        print("\nФ5 GPS — не проверено: нет Pillow (pip install pillow)")
        return
    gps = []
    for p in imgs:
        try:
            with Image.open(p) as im:
                if im.getexif().get_ifd(0x8825):
                    gps.append(p)
        except Exception:
            pass
    print(f"\nФ5 снимки с координатами съёмки (GPS) в служебных данных — {len(gps)}"
          " (сайт пересохраняет фото без них; важно, если файл отдают как есть)")
    for p in gps:
        print("   ⌖ " + rel(p))


if __name__ == "__main__":
    main()
