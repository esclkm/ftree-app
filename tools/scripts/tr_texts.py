#!/usr/bin/env python3
"""Перевод мест, фактов и подписей фото — та же схема и тот же переводчик, что у биографий.

Где лежит (общая схема для всех переводов — paths.tr_path, устройство файлов — tr_store.py):
  3_research/tree/translations/<язык>/places/<Имя карточки места>.md
  3_research/tree/translations/<язык>/facts/<Имя карточки человека>.md
  3_research/tree/translations/<язык>/photos/<имя файла фото>.md

Что переводить — по людям: всё, что видно на их страницах. Факты их карточек, места, на которые ссылаются их
биографии и карточки (место рождения, смерти, дома), и фото мест из их жизни. Уже свежее не трогаем: факт — по
отпечатку строки, место и фото — по отпечатку русского текста.

Переводит Claude через llm.py (как bio_autotranslate.py: словарь имён и слов из 00_АВТОПЕРЕВОД.md, ссылки [[…]]
модель не видит — только метки). Модель по умолчанию — Haiku; Sonnet — по просьбе Павла (--model sonnet).

  python3 tools/scripts/tr_texts.py status --lang es --person "Kazimierz Jasieniew"
  python3 tools/scripts/tr_texts.py translate --lang es --model sonnet --person "Kazimierz Jasieniew" --person "…"
  python3 tools/scripts/tr_texts.py translate --lang es --kind facts --person "…"     # только один вид
"""
import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bio_autotranslate as A  # noqa: E402 — переводчик, словари, маскировка ссылок
import cards  # noqa: E402
import tr_store as S  # noqa: E402
from cards.places import ABOUT  # noqa: E402

b = A.b
KINDS = ("facts", "places", "photos", "sources", "documents")
BATCH = 14000  # знаков русского текста на один вызов модели (места и фото — пачками)

RULES = """You are a literary translator for a family-history website. You translate short Russian texts — {what} —
into {lang}. The readers are relatives abroad — {readers}. They do not know Russian, Soviet or Belarusian history.
Write natural, precise {lang}, not word-for-word.

Output ONLY the translation. The input is split into items; each starts with a marker line like <<<§3>>>.
Output every item after the SAME marker line, in the same order, nothing before the first marker.

Faithfulness: translate ALL of the text; do not shorten, soften or add facts; uncertainty stays uncertainty.
Keep exactly as is: markdown (headings levels, lists, tables, bold, italics, blockquotes), every [[...]] link,
source references like *(Аудио 06, 26:13)* (but «Аудио» → «Audio», «лист» → the {lang} word for a
manuscript sheet), markers ⭐ ⚠️ 🟡 ✅ ❓ ⛔ ⬇️, codes like @I25@,
file names, URLs, the separator « ¦ ».
{format}

Names (use exactly this list; a name not in the list stays in Latin transliteration, never invent a {lang} form):
{names}

Terms (use these renderings every time):
{terms}
"""
FORMAT = {
    "facts": "Each item is a fact from a person's card: lines «label: …», «text: …», «reasoning: …», «locators: …» "
             "(places in the sources, separated by « ¦ »). Keep the line names label/text/reasoning/locators and the "
             "«## <code>» line untouched; translate only what follows «name: ». Keep each value on one line.",
    "places": "Each item is the text of a place card. Translate the headings too, except: the heading «## О месте» "
              "must become exactly «## {about}».",
    "photos": "Each item is a photo caption: sections «## desc», «## whose», «## exact», «## note», «## section». "
              "Keep these headings untouched (they are field names); translate only the text under them.",
    "sources": "Each item is the title of a source (a recording, a document, a book, a website): «## title» and the title "
               "under it. Keep «## title»; translate the title, keep dates, numbers, codes and names of archives/sites.",
    "documents": "Each item is the title of a personal document (passport, certificate…): «## title» and the title under "
                 "it. Keep «## title»; translate the title, keep series and numbers as they are.",
}
WHAT = {"facts": "facts from a person's card in the family tree", "places": "descriptions of places (villages, towns, "
        "houses) in the family history", "photos": "captions of historical photos of places",
        "sources": "titles of sources of the family history", "documents": "titles of personal documents"}


def system(kind, lang):
    return RULES.format(what=WHAT[kind], lang=A.LANG_NAME[lang], readers=A.READERS[lang],
                        format=FORMAT[kind].format(about=ABOUT[lang]), names=A.glossary(lang),
                        terms=A.glossary(lang, "Слова") or "  (none yet)")


def ask(kind, lang, items):
    """[(ключ, русский текст)] → {ключ: перевод}; пачками по BATCH знаков, метки <<<§n>>>."""
    out, batch, size = {}, [], 0
    for item in items + [None]:
        if item is None or (batch and size + len(item[1]) > BATCH):
            if batch:
                text = "\n\n".join(f"<<<§{i}>>>\n{t}" for i, (_, t) in enumerate(batch))
                got = dict((int(k), v.strip("\n")) for k, v in
                           re.findall(r"<<<§(\d+)>>>\n?(.*?)(?=\n?<<<§\d+>>>|\Z)", A.translate(system(kind, lang), text,
                                                                                         f"перевод: {kind}"), re.S))
                for i, (key, _) in enumerate(batch):
                    if got.get(i):
                        out[key] = got[i]
                    else:
                        print(f"  ⚠️ {kind}: нет в ответе — {key}")
            batch, size = [], 0
        if item is not None:
            batch.append(item)
            size += len(item[1])
    return out


# ---------- что видно на странице человека ----------

def person(name):
    d = b.people.get(b.N(name))
    if not d:
        sys.exit(f"Нет карточки «{name}»")
    return d


def person_places(d):
    """Места, на которые ссылаются биография и карточка человека (в т. ч. место рождения, смерти, дома)."""
    text = b.bio_text(d) + "\n" + d["body"] + "\n" + " ".join(str(v) for v in d["f"].values())
    out = []
    for m in re.finditer(r"\[\[[^\]]+\]\]", text):
        stem = b.place_by_name.get(b.link_target(m[0]))
        if stem and stem not in out:
            out.append(stem)
    return out


def person_photos(d, extras):
    groups, _ = extras.life_photos(d["id"])
    return list({str(r["path"]): r for g in groups for r in g["photos"]}.values())


# ---------- три вида ----------

def do_facts(d, lang, tree, run):
    p = tree.people[d["id"]]
    have = S.facts_index()
    cur = [(S.fact_key(f.label, f.text, f.reasoning), S.fact_source(f)) for f in p.facts if f.text]
    occ = str(d["f"].get("occupation") or "").strip()
    if occ:
        cur.append((S.occupation_key(occ), {"text": occ}))
    todo = [(k, src) for k, src in cur
            if lang not in have.get(k, {}) or (src.get("when") and not have[k][lang].get("when"))]
    tf = S.load("facts").get(d["stem"], {}).get(lang)
    old = {k: S.field_lines(v) for k, v in S.sections(tf[1]).items()} if tf else {}
    own = set(old)
    # та же строка уже переведена у другого человека (общий факт у родителей и детей) — берём оттуда
    old |= {k: have[k][lang] for k, _ in cur if k not in old and lang in have.get(k, {})}
    own -= {k for k, _ in todo}
    print(f"  факты {d['stem']}: всего {len(cur)}, перевести {len(todo)}")
    if not run or (not todo and all(k in own for k, _ in cur)):
        return
    got = ask("facts", lang, [(k, S.facts_body([(k, src)])) for k, src in todo]) if todo else {}
    for k, txt in got.items():
        fields = S.field_lines(S.sections(txt).get(k, txt))
        if fields.get("text"):
            old[k] = fields
        else:
            print(f"  ⚠️ факт {k}: перевод без «text:» — пропущен")
    keep = [(k, old[k]) for k, _ in cur if k in old]
    S.write("facts", lang, d["stem"], f"[[{d['stem']}]]", d["id"], S.facts_body(keep),
            S.text_hash(S.facts_body(cur)), A.engine())
    print(f"  записано: факты {d['stem']} — {len(keep)} из {len(cur)}")


def do_places(stems, lang, run):
    have = S.load("places")
    todo = []
    for stem in stems:
        src = b.place_source(b.places[stem]["body"])
        if not src:
            continue
        tf = have.get(stem, {}).get(lang)
        if tf and tf[0].get("source_hash") == S.text_hash(src):
            continue
        todo.append((stem, src))
    print(f"  места: всего {len(stems)}, перевести {len(todo)} ({sum(len(t) for _, t in todo)} знаков)")
    if not todo or not run:
        return
    got = ask("places", lang, todo)
    for stem, src in todo:
        tr = got.get(stem)
        if not tr:
            continue
        if A.check(src, tr) and "ссылки" in A.check(src, tr):
            print(f"  ⚠️ место {stem}: {A.check(src, tr)} — пропущено")
            continue
        S.write("places", lang, stem, f"[[{stem}]]", b.places[stem]["id"], tr, S.text_hash(src), A.engine())
    print(f"  записано мест: {sum(1 for s, _ in todo if s in got)}")


def do_photos(records, lang, run):
    have = S.load("photos")
    todo = []
    for r in records:
        name = Path(r["path"]).stem
        tf = have.get(name, {}).get(lang)
        if tf and tf[0].get("source_hash") == S.photo_hash(r):
            continue
        body = S.photo_body(S.photo_source(r))
        if body:
            todo.append((name, body, r))
    print(f"  фото: всего {len(records)}, перевести {len(todo)} ({sum(len(t) for _, t, _ in todo)} знаков)")
    if not todo or not run:
        return
    got = ask("photos", lang, [(n, t) for n, t, _ in todo])
    n = 0
    for name, body, r in todo:
        tr = got.get(name)
        if not tr or set(S.sections(tr)) != set(S.sections(body)):
            print(f"  ⚠️ фото {name}: разделы не совпали — пропущено")
            continue
        S.write("photos", lang, name, Path(r["path"]).name, Path(r["path"]).name, tr, S.photo_hash(r), A.engine())
        n += 1
    print(f"  записано фото: {n}")


def person_sources(d, tree):
    """Источники на странице человека: из строк фактов и ссылками из биографии и карточки → {имя карточки: название}."""
    p = tree.people[d["id"]]
    by_stem = {s.stem: s for s in tree.sources.values()}
    out = {}
    for f in p.facts:
        for r in f.refs:
            s = tree.sources.get(r.source)
            if s:
                out[s.stem] = s.title
    for m in re.finditer(r"\[\[[^\]]+\]\]", b.bio_text(d) + "\n" + d["body"]):
        s = by_stem.get(b.link_target(m[0]))
        if s:
            out[s.stem] = s.title
    return out


def do_titles(kind, items, lang, run):
    """{имя: русское название} → translations/<язык>/<sources|documents>/<имя>.md, «## title»."""
    have = S.load(kind)
    todo = [(n, t) for n, t in items.items()
            if not (lang in have.get(n, {}) and have[n][lang][0].get("source_hash") == S.text_hash(t))]
    print(f"  {kind}: всего {len(items)}, перевести {len(todo)}")
    if not todo or not run:
        return
    got = ask(kind, lang, [(n, f"## title\n{t}") for n, t in todo])
    k = 0
    for n, t in todo:
        tr = S.sections(got.get(n, "")).get("title")
        if not tr:
            print(f"  ⚠️ {kind} {n}: нет перевода")
            continue
        S.write(kind, lang, n, f"[[{n}]]" if kind == "sources" else n, n, f"## title\n{tr}", S.text_hash(t), A.engine())
        k += 1
    print(f"  записано ({kind}): {k}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("status", "translate"))
    ap.add_argument("--lang", required=True, choices=("es", "pl", "en"))
    ap.add_argument("--person", action="append", required=True, help="имя карточки; можно несколько раз")
    ap.add_argument("--kind", action="append", choices=KINDS, help="только этот вид (по умолчанию — все три)")
    ap.add_argument("--model", choices=sorted(A.ENGINES), help="модель вместо Haiku — только по просьбе Павла")
    a = ap.parse_args()
    A.MODEL_CLI = a.model or A.MODEL_CLI
    kinds = a.kind or KINDS
    run = a.cmd == "translate"
    if run and not A.can_translate():
        sys.exit("Нет программы claude (llm.py status) — переводить нечем")
    tree = cards.load()
    extras = b.SiteExtras()
    ds = [person(n) for n in a.person]
    if "facts" in kinds:
        for d in ds:
            do_facts(d, a.lang, tree, run)
    if "places" in kinds:
        do_places(list(dict.fromkeys(s for d in ds for s in person_places(d))), a.lang, run)
    if "photos" in kinds:
        do_photos(list({str(r["path"]): r for d in ds for r in person_photos(d, extras)}.values()), a.lang, run)
    if "sources" in kinds:
        do_titles("sources", {k: v for d in ds for k, v in person_sources(d, tree).items()}, a.lang, run)
    if "documents" in kinds:
        do_titles("documents", {x["file"]: x["title"] for d in ds for x in b.person_documents()[0].get(d["id"], [])},
                  a.lang, run)


if __name__ == "__main__":
    main()
