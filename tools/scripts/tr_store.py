"""Переводы мест, фактов и подписей фото — та же схема, что у биографий: один переводимый объект — один файл,
названный как оригинал (paths.tr_path):

  3_research/tree/translations/<язык>/places/<Имя карточки места>.md   — текст карточки места (и дома)
  3_research/tree/translations/<язык>/facts/<Имя карточки человека>.md — блок «Факты» человека
  3_research/tree/translations/<язык>/photos/<имя файла фото>.md       — подпись снимка из описи

Шапка у всех одна (как у биографий): kind, of, of_id, lang, source_hash, translated, method, model, reviewed.
Тело:
  place — переведённый текст карточки с теми же разделами; «О месте» — под заголовком того языка («Sobre el lugar»);
  facts — по разделу на строку факта: «## <отпечаток строки>», под ним «label: …», «text: …», «reasoning: …»,
          «locators: …» (места в источниках через « ¦ »), «when: …» (слова при дате: «с конца 1960-х»); поле
          «Занятие» карточки — таким же разделом с одним «text: …». Строку поправили — у неё новый отпечаток, и сайт показывает
          её по-русски, пока не переведут заново;
  photo — разделы-поля подписи: «## desc», «## whose», «## exact», «## note», «## section»;
  source, document — «## title»: название карточки источника / документа человека (2_transcripts/documents/…).

Лёгкий модуль без сборки сайта: его читает site_export.py (SiteExtras), пишет tr_texts.py.
"""
import datetime
import hashlib
import re

import paths
from cards.notes import read_note

FACT_FIELDS = ("label", "text", "reasoning", "locators", "when")
PHOTO_FIELDS = ("desc", "whose", "exact", "note", "section")
LOC_SEP = " ¦ "
KIND = {"places": "place", "facts": "facts", "photos": "photo", "sources": "source", "documents": "document"}


def text_hash(t):
    """Тот же отпечаток, что у биографий (site_export.text_hash): пробелы не в счёт."""
    return hashlib.sha1(re.sub(r"\s+", " ", t or "").strip().encode()).hexdigest()[:12]


def fact_key(label, text, reasoning):
    return text_hash(f"{label or ''}|{text or ''}|{reasoning or ''}")[:10]


def fact_source(f):
    """Строка факта → поля для перевода (что видно на сайте)."""
    return {"label": f.label or "", "text": f.text or "", "reasoning": f.reasoning or "",
            "locators": LOC_SEP.join(r.locator or "" for r in f.refs) if any(r.locator for r in f.refs) else "",
            "when": (f.date.phrase or "") if f.date is not None and f.date.kind != "PHRASE" else ""}


def occupation_key(text):
    """Поле «Занятие» карточки — тем же файлом фактов, раздел с этим отпечатком и одним полем text."""
    return fact_key("occupation", text, "")


def photo_source(r):
    return {k: r.get(k) or "" for k in PHOTO_FIELDS}


def photo_hash(r):
    return text_hash("\n".join(f"{k}:{v}" for k, v in photo_source(r).items()))


def sections(body):
    """«## ключ» + текст под ним → {ключ: текст}."""
    out, key, cur = {}, None, []
    for line in body.split("\n"):
        m = re.match(r"^## (.+?)\s*$", line)
        if m:
            if key is not None:
                out[key] = "\n".join(cur).strip()
            key, cur = m[1], []
        elif key is not None:
            cur.append(line)
    if key is not None:
        out[key] = "\n".join(cur).strip()
    return out


def field_lines(text):
    """«label: …» строками → {поле: значение}; продолжение без «поле:» — к предыдущему полю."""
    out, key = {}, None
    for line in text.split("\n"):
        m = re.match(rf"^({'|'.join(FACT_FIELDS)}):\s?(.*)$", line)
        if m:
            key = m[1]
            out[key] = m[2]
        elif key and line.strip():
            out[key] += " " + line.strip()
    return {k: v.strip() for k, v in out.items() if v.strip()}


def facts_body(items):
    """[(ключ, {поле: значение})] → тело файла фактов."""
    return "\n\n".join(f"## {k}\n" + "\n".join(f"{f}: {v}" for f, v in d.items() if v) for k, d in items)


def photo_body(d):
    return "\n\n".join(f"## {k}\n{v}" for k, v in d.items() if v)


def load(kind):
    """{имя оригинала: {язык: (шапка, тело)}} для вида places | facts | photos."""
    out = {}
    root = paths.TRANSLATIONS
    for p in sorted(root.glob(f"*/{kind}/*.md")) if root.exists() else []:
        n = read_note(p)
        out.setdefault(p.stem, {})[p.parent.parent.name] = (n.fm or {}, n.body or "")
    return out


def titles(kind, current):
    """{имя: {язык: перевод названия}} — только свежие (русское название с тех пор не менялось); current — {имя: название}."""
    out = {}
    for name, langs in load(kind).items():
        for lang, (fm, body) in langs.items():
            t = sections(body).get("title")
            if t and name in current and fm.get("source_hash") == text_hash(current[name]):
                out.setdefault(name, {})[lang] = t
    return out


def facts_index():
    """{ключ строки факта: {язык: {поле: перевод}}} — по всем файлам фактов."""
    out = {}
    for _, langs in load("facts").items():
        for lang, (_, body) in langs.items():
            for key, text in sections(body).items():
                out.setdefault(key, {})[lang] = field_lines(text)
    return out


def write(kind, lang, name, of, of_id, body, source_hash, model, section_hashes=None):
    out = paths.tr_path(lang, kind, name)
    out.parent.mkdir(parents=True, exist_ok=True)
    head = [f"kind: {KIND[kind]}", f'of: "{of}"', f"of_id: {of_id}", f"lang: {lang}", f"source_hash: {source_hash}",
            f"translated: {datetime.date.today()}", "method: ИИ", f'model: "{model}"',
            f'section_hashes: "{section_hashes}"' if section_hashes else None, "reviewed: false"]
    out.write_text("---\n" + "\n".join(x for x in head if x) + "\n---\n\n" + body.strip() + "\n", encoding="utf-8")
    return out
