#!/usr/bin/env python3
"""Переводы биографий на другие языки — по запросу, переводит ИИ. Русский текст остаётся основным.

Перевод — отдельный файл на человека и язык: 3_research/tree/translations/<lang>/biographies/<Имя карточки>.md
(общая схема для всех переводов — paths.tr_path; места, факты, фото — tr_texts.py).
В шапке файла — номер человека, имя на этом языке и «отпечаток» русского текста в момент перевода: если русскую
биографию потом поправили, `status` и сайт покажут, что перевод отстаёт.

  python3 tools/scripts/bio_translation.py source "Kazimierz Jasieniew"      # русский текст для перевода + имена
  python3 tools/scripts/bio_translation.py write "Kazimierz Jasieniew" --lang es --name "Casimiro (Kazimierz) Jasieniew" < перевод.md
  python3 tools/scripts/bio_translation.py status                               # что переведено, что отстало
  python3 tools/scripts/bio_translation.py status --line Ясеневы --lang es      # кого из ветки ещё не перевели
"""
import argparse
import datetime
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import site_export as b  # noqa: E402  — тот же разбор дерева и биографий, что у сайта

LANGS = ("es", "pl", "en")


def person(name):
    d = b.people.get(b.N(name))
    if not d:
        close = [k for k in b.people if b.N(name).split()[0] in k][:10]
        sys.exit(f"Нет карточки «{name}». Похожие: {', '.join(close) or '—'}")
    return d


def source(args):
    d = person(args.name)
    text = b.bio_text(d)
    if not text:
        sys.exit(f"У «{d['stem']}» нет биографии (ни «## Рассказ», ни строки «**Биография:**» в карточке).")
    print(f"человек: {d['stem']}\nperson_id: {d['id']}\nотпечаток: {b.text_hash(text)}\n"
          f"имена по умолчанию: pl «{d['pl']}» · en «{d['en']}»\n"
          f"откуда: {'; '.join(b.bio_refs(d))}\n" + "—" * 60 + f"\n{text}")


def rebase(body, src_dir, out_dir):
    """Ссылки на файлы в русском тексте — от папки биографии; перевод лежит в translations/<lang>/biographies/.
    Пересчитываем «](путь.md)» и «`путь.md`», если по такому пути от папки биографии есть файл."""
    def fix(m):
        path, tail = m.group(2), m.group(3) or ""
        target = src_dir / path
        if path.startswith(("http", "/")) or not target.exists():
            return m.group(0)
        return m.group(1) + os.path.relpath(target, out_dir) + tail + m.group(4)
    return re.sub(r"(\]\(|`)([^)`#\s]+\.md)(#[^)`]*)?(\)|`)", fix, body)


def write(args):
    d = person(args.name)
    text = b.bio_text(d)
    if not text:
        sys.exit("Нет русской биографии — переводить нечего.")
    body = sys.stdin.read().strip()
    if not body:
        sys.exit("Перевод подаётся на вход (stdin) — пусто.")
    out = b.paths.tr_path(args.lang, "biographies", d["stem"])
    out.parent.mkdir(parents=True, exist_ok=True)
    body = rebase(body, (b.paths.ROOT / b.bio_refs(d)[0].split("#")[0]).parent, out.parent)
    head = ["kind: biography", f'of: "[[{d["stem"]}]]"', f"of_id: {d['id']}", f"lang: {args.lang}",
            f'name_local: "{args.name_local}"' if args.name_local else None,
            f'translated_from: "{"; ".join(b.bio_refs(d))}"', f"source_hash: {b.text_hash(text)}",
            f"translated: {datetime.date.today()}", "method: ИИ",
            f'model: "{args.model}"' if args.model else None,
            f'section_hashes: "{args.sections}"' if args.sections else None, "reviewed: false"]
    out.write_text("---\n" + "\n".join(x for x in head if x) + "\n---\n\n" + body + "\n", encoding="utf-8")
    print(f"Записано: {out.relative_to(b.paths.ROOT)}")


def status(args):
    rows = []
    for pid, tr in b.translations.items():
        d = b.by_id[pid]
        cur = b.text_hash(b.bio_text(d))
        for lang, (tf, _) in sorted(tr.items()):
            if args.lang and lang != args.lang:
                continue
            state = "отстаёт от русского" if tf.get("source_hash") != cur else "свежий"
            rows.append(f"{lang}  {d['stem']:40} {state:22} {'проверен' if tf.get('reviewed') else 'ИИ, не проверен'}")
    print("\n".join(sorted(rows)) or "Переводов пока нет.")
    if args.line or args.lang:
        todo = [d["stem"] for d in b.people.values()
                if (not args.line or args.line in b.as_list(d["f"].get("lineage"))) and b.bio_text(d)
                and (args.lang or "es") not in b.translations.get(d["id"], {})]
        print(f"\nЕсть русская биография, нет перевода ({args.lang or 'es'}): {len(todo)}")
        print("\n".join("  " + x for x in sorted(todo)))


ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
sub = ap.add_subparsers(dest="cmd", required=True)
s1 = sub.add_parser("source"); s1.add_argument("name"); s1.set_defaults(fn=source)
s2 = sub.add_parser("write"); s2.add_argument("name"); s2.add_argument("--lang", choices=LANGS, required=True)
s2.add_argument("--name", dest="name_local", help="имя на этом языке, напр. «Casimiro (Kazimierz) Jasieniew»")
s2.add_argument("--model", default="Claude (сессия Claude Code)", help="кто переводил — всегда Claude, не машинный переводчик")
s2.add_argument("--sections", help="отпечатки русских разделов по порядку — для перевода только изменённых частей")
s2.set_defaults(fn=write)
s3 = sub.add_parser("status"); s3.add_argument("--lang", choices=LANGS); s3.add_argument("--line"); s3.set_defaults(fn=status)
a = ap.parse_args()
a.fn(a)
