#!/usr/bin/env python3
"""Автоперевод биографий: сам находит, у кого из «переводимых» людей поменялся русский текст, и переводит заново.

Кого переводить — таблица в 3_research/tree/translations/00_АВТОПЕРЕВОД.md: язык, человек и кого
брать вместе с ним (предки, потомки, супруги). Человек попадает в работу, если у него есть русская биография и
перевода на этот язык нет или он «отстаёт от русского» (отпечаток текста не совпал — см. bio_translation.py).

Переводит ИИ — Claude, как переводчик-литератор: с контекстом (кто читатель, что это семейная история), словарём
имён и слов. Машинного перевода (Google и т. п.) здесь нет и не будет.

⭐ Модель — **Claude Haiku 4.5**: самая быстрая и дешёвая (решение Павла, 28.09.2026). И ⭐ **переводятся только
изменённые разделы**: текст режется по заголовкам, в шапке перевода лежат отпечатки русских разделов
(`section_hashes`); раздел с тем же отпечатком берётся из прежнего перевода как есть, заново — только новые и
поправленные. Целиком — только первый перевод или если прежний не сходится с русским по числу разделов.
Зовёт модель только через `llm.py` (программа Claude Code `claude -p`, по подписке, налегке — без CLAUDE.md и
памяти; журнал вызовов, дневной потолок, кэш). Нет программы — скрипт просто печатает, что пора перевести.
Записывает перевод всегда через `bio_translation.py write` — он ставит номер человека и отпечаток.

  python3 tools/scripts/bio_autotranslate.py            # перевести всё, что отстало
  python3 tools/scripts/bio_autotranslate.py --check    # только показать, ничего не переводить
  python3 tools/scripts/bio_autotranslate.py --only "Прокоп Ясенев"
  python3 tools/scripts/bio_autotranslate.py --lang es --model sonnet --full --only "…"   # заново целиком, Sonnet
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import site_export as b  # noqa: E402
import llm  # noqa: E402
import paths  # noqa: E402

CONFIG = b.paths.TRANSLATIONS / "00_АВТОПЕРЕВОД.md"
LANG_NAME = {"es": "Spanish (neutral, easy for Argentine readers)", "pl": "Polish", "en": "English"}

RULES = """You are a literary translator working on a family-history book. You translate one Russian biography
into {lang}. The readers are relatives abroad — {readers}. They do not know Russian, Soviet or Belarusian
history, and this may be the first time they read about their own ancestors. Write the way a careful human
translator would: natural, warm, precise {lang} that reads as if it were written in it — not word-for-word.

Output ONLY the translated markdown — no preface, no notes, no code fences.

Faithfulness:
- Translate ALL of the text. Do not shorten, summarise, soften or add facts. Uncertainty stays uncertainty:
  «видимо», «по словам папы», 🟡 and ⚠️ keep their doubt. Never "fix" a date or a fact.
- Relatives' quotes are spoken language — keep them spoken, with their pauses and roughness; keep bold.
- Soviet and village realia: keep the word and make it understandable, as the Russian text itself does —
  use the terms list below; for a new term give a short natural explanation once, not a footnote.

Keep exactly as is:
- markdown structure: headings, tables, blockquotes, lists, bold, italics, strikethrough, `---`;
- every [[...]] link with everything inside the brackets (in a link to a .md file you may translate only the
  label after «|»); relative links (...md) and paths in backticks;
- source references such as *(Аудио 02, 13:48)* or *(А03, 10:38)*; markers ⭐ ⚠️ 🟡 ✅ ❓ ⛔ ⟨ ⟩; codes like
  F12 or @I25@; file names such as ВОПРОСЫ_ПАПЕ.

Names:
- Surnames are never translated (Jasieniew, Wierzbowska). Nicknames are transliterated, not corrected
  («Прокопка» → «Prokopka», «Ганулька» → «Hanulka»).
- Use exactly this list («Russian → {lang}» or a ready {lang} name); a name not in the list stays in Latin
  transliteration. Never invent a {lang} form of a name.
{names}

Terms (use these renderings every time):
{terms}
"""
# кто прочтёт перевод — своё у каждого дерева: ftree.toml, [translate.readers]
READERS = {lang: "relatives and friends of the family who read this language" for lang in ("es", "pl", "en")}
READERS.update({k: str(v) for k, v in dict(paths.tree_conf("translate.readers", {})).items()})
MODEL_CLI = "haiku"
ENGINES = {"haiku": "Claude Haiku 4.5 (Claude Code)", "sonnet": "Claude Sonnet (Claude Code)",
           # тот же перевод через GitHub Copilot CLI: свой лимит, подписку Claude не тратит (llm.py, 08.10.2026)
           "copilot:claude-haiku-4.5": "Claude Haiku 4.5 (GitHub Copilot)",
           "copilot:claude-sonnet-5.5": "Claude Sonnet 5.5 (GitHub Copilot)",
           "copilot:gemini-3.8-flash": "Gemini 3.8 Flash (GitHub Copilot)"}
DELTA = ("\n\nYou receive only SOME sections of the biography — the ones that changed. Each starts with a marker "
         "line like <<<§3>>>. Translate every section and output each one after the SAME marker line, in the same "
         "order, nothing before the first marker. Translate only the text after each marker; keep its headings.")
PREVIOUS = ("\n\nAn earlier translation of a previous version of this text is given below. Keep its wording where the "
            "Russian did not change; translate the changed parts anew.\n\n<previous_translation>\n{old}\n</previous_translation>")


def read_config():
    """Строки таблицы «| Язык | Человек | Кого ещё |» → [(lang, stem, {'предки', 'потомки', 'супруги'})]."""
    rows = []
    for line in CONFIG.read_text(encoding="utf-8").splitlines():
        c = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(c) >= 2 and c[0] in LANG_NAME:
            name = b.link_target(c[1]) or c[1]
            if b.N(name) not in b.people:
                sys.exit(f"{CONFIG.name}: нет карточки «{name}»")
            rows.append((c[0], b.N(name), set(re.findall(r"предки|потомки|супруги", c[2] if len(c) > 2 else ""))))
    return rows


def scope(stem, what):
    root = b.people[stem]["id"]
    seen = {root}
    def walk(i, keys):
        for k in keys:
            for j in b.by_id[i][k]:
                if j not in seen:
                    seen.add(j)
                    walk(j, keys)
    if "предки" in what:
        walk(root, ("father", "mother"))
    if "потомки" in what:
        walk(root, ("children",))
    if "супруги" in what:
        for i in list(seen):
            seen.update(b.by_id[i]["spouses"])
    return seen


def todo():
    """[(lang, person, russian text, old translation or None, why)] — у кого перевод отсутствует или отстал."""
    out, seen = [], set()
    for lang, stem, what in read_config():
        for pid in sorted(scope(stem, what), key=lambda i: b.by_id[i]["stem"]):
            d = b.by_id[pid]
            text = b.bio_text(d)
            if (lang, pid) in seen or not text:
                continue
            seen.add((lang, pid))
            tf, tb = b.translations.get(pid, {}).get(lang, (None, None))
            if tf is None:
                out.append((lang, d, text, None, "нет перевода"))
            elif tf.get("source_hash") != b.text_hash(text):
                out.append((lang, d, text, tb.strip(), "русский текст изменился"))
    return out


def sections(t):
    """Текст → разделы по заголовкам (строка «# …»–«###### …» начинает новый). '\\n'.join(разделы) == текст."""
    out, cur = [], []
    for line in t.split("\n"):
        if cur and re.match(r"#{1,6} ", line):
            out.append("\n".join(cur)); cur = []
        cur.append(line)
    out.append("\n".join(cur))
    return out


def shash(t):
    return b.text_hash(t)[:8]


def delta_plan(text, tf, tb):
    """[(раздел, готовый перевод или None)] — или None, если прежний перевод не годится для частичной замены."""
    old = str(tf.get("section_hashes") or "").split()
    tsec = sections(tb or "")
    if not old or len(old) != len(tsec):
        return None
    ready = dict(zip(old, tsec))
    return [(sec, ready.get(shash(sec))) for sec in sections(text)]


def translate_delta(system, plan):
    """Переводит только разделы без готового перевода — одним запросом, с метками <<<§n>>>."""
    need = [i for i, (_, tr) in enumerate(plan) if tr is None]
    if not need:
        return "\n".join(tr for _, tr in plan), 0
    out = translate(system + DELTA, "\n\n".join(f"<<<§{i}>>>\n{plan[i][0]}" for i in need), "перевод: разделы")
    got = dict((int(k), v.strip("\n")) for k, v in re.findall(r"<<<§(\d+)>>>\n?(.*?)(?=\n?<<<§\d+>>>|\Z)", out, re.S))
    missing = [i for i in need if not got.get(i)]
    if missing:
        raise RuntimeError(f"в ответе нет разделов {missing}")
    return "\n".join(got[i] if tr is None else tr for i, (_, tr) in enumerate(plan)), len(need)


def glossary(lang, kind="Имена"):
    """Раздел «## Имена: <lang>» (или «## Слова: <lang>») файла настроек; к именам — имена готовых переводов."""
    part = re.search(rf"^## {kind}: {lang}\n(.*?)(?=^## |\Z)", CONFIG.read_text(encoding="utf-8"), re.S | re.M)
    names = set(re.findall(r"^- (.+→.+)$", part.group(1), re.M)) if part else set()
    if kind != "Имена":
        return "\n".join(f"  - {n}" for n in sorted(names))
    names |= set(card_names(lang).values())
    names |= {str(tf["name_local"]) for tr in b.translations.values() for l, (tf, _) in tr.items()
              if l == lang and tf.get("name_local")}
    return "\n".join(f"  - {n}" for n in sorted(names))


def card_names(lang):
    """Раздел «## Карточки: <lang>»: «- Имя карточки → имя на этом языке» — для шапки перевода и сайта."""
    part = re.search(rf"^## Карточки: {lang}\n(.*?)(?=^## |\Z)", CONFIG.read_text(encoding="utf-8"), re.S | re.M)
    return {b.N(k.strip()): v.strip() for k, v in re.findall(r"^- (.+?) → (.+)$", part.group(1), re.M)} if part else {}


def engine():
    """Кто переводит — пишется в шапку перевода (поле model). Только Claude: машинных переводчиков здесь нет."""
    return ENGINES.get(MODEL_CLI, f"Claude {MODEL_CLI} (Claude Code)")


LINK = re.compile(r"\[\[([^\]|]+)")
TOKEN = re.compile(r"⟦L(\d+)⟧")
MASK_NOTE = ("\n\nLink targets are replaced by tokens like [[⟦L1⟧ or [[⟦L1⟧|label]]. Copy every token exactly, "
             "keep its [[ ]]; translate only a label after «|».")


def translate(system, text, task="перевод биографии"):
    """Перевод через llm.py. Адреса ссылок [[…]] модель не видит — только метки ⟦Ln⟧, их возвращает код:
    Haiku однажды «перевёл» ссылку [[Лесогорск (область)]] в [[Lesogorsk (region)]] (02.10.2026)."""
    targets = []
    masked = LINK.sub(lambda m: f"[[⟦L{targets.append(m[1]) or len(targets)}⟧", text)
    try:
        out = llm.ask(task, masked, system + (MASK_NOTE if targets else ""), model=MODEL_CLI).strip()
    except llm.Limit:
        raise
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"claude -p: не ответил за {e.timeout} с") from e
    return TOKEN.sub(lambda m: targets[int(m[1]) - 1] if 0 < int(m[1]) <= len(targets) else m[0], out)


def can_translate():
    return llm.cli() is not None


def check(ru, tr):
    """Грубая проверка, что перевод целый: те же ссылки [[…]] и почти те же заголовки и таблицы."""
    links = lambda t: sorted(re.findall(r"\[\[([^\]|]+)", t))
    if links(ru) != links(tr):
        return "ссылки [[…]] не совпадают с русским текстом"
    for pat, what in ((r"^#+ ", "заголовков"), (r"^\|", "строк таблиц"), (r"^> ", "строк цитат")):
        a, c = len(re.findall(pat, ru, re.M)), len(re.findall(pat, tr, re.M))
        if abs(a - c) > max(1, a // 10):
            return f"{what}: в русском {a}, в переводе {c}"
    if len(tr) < 0.6 * len(ru):
        return f"перевод подозрительно короткий ({len(tr)} знаков против {len(ru)})"
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="только показать, что пора перевести")
    ap.add_argument("--only", action="append", help="только этот человек (имя карточки); можно несколько раз")
    ap.add_argument("--lang", help="только этот язык (es, pl, en)")
    ap.add_argument("--model", choices=sorted(ENGINES), help="модель вместо Haiku — только по просьбе Павла")
    ap.add_argument("--full", action="store_true", help="переводить целиком, без прежнего перевода (не по разделам)")
    a = ap.parse_args()
    global MODEL_CLI
    MODEL_CLI = a.model or MODEL_CLI
    only = {b.N(x) for x in a.only or []}

    jobs = [j for j in todo() if (not only or j[1]["stem"] in only) and (not a.lang or j[0] == a.lang)]
    if not jobs:
        print("Автоперевод: всё свежее")
        return
    for lang, d, _, _, why in jobs:
        print(f"  {lang}  {d['stem']} — {why}")
    if a.check or not can_translate():
        print(f"Автоперевод: пора перевести {len(jobs)}" + ("" if a.check else
              " — нет программы claude (llm.py status); переведите в сессии Claude (скилл bio-translate)"))
        return

    done, failed, cache = 0, [], {}  # одинаковый русский текст (у супругов бывает одна глава на двоих) переводим один раз
    for lang, d, text, old, why in jobs:
        key = (lang, b.text_hash(text))
        if key not in cache:
            system = RULES.format(lang=LANG_NAME[lang], readers=READERS[lang], names=glossary(lang),
                                  terms=glossary(lang, "Слова") or "  (none yet)")
            tf = b.translations.get(d["id"], {}).get(lang, ({}, ""))[0]
            plan = delta_plan(text, tf, old) if old and not a.full else None
            try:
                if plan:
                    n = sum(1 for _, t in plan if t is None)
                    print(f"→ {lang} {d['stem']}: перевожу изменённые разделы — {n} из {len(plan)}…", flush=True)
                    tr, _ = translate_delta(system, plan)
                else:
                    if old and not a.full:
                        system += PREVIOUS.format(old=old)
                    print(f"→ {lang} {d['stem']}: перевожу целиком ({len(text)} знаков)…", flush=True)
                    tr = translate(system, text)
                problem = check(text, tr)
            except llm.Limit as e:  # потолок или лимит подписки — остальных сегодня не трогаем
                failed.append(f"{d['stem']} ({lang}): {e}")
                break
            except Exception as e:  # noqa: BLE001 — один сбой не должен останавливать остальных
                tr, problem = None, str(e)
            if problem:
                failed.append(f"{d['stem']} ({lang}): {problem}")
                continue
            cache[key] = tr
        name = card_names(lang).get(d["stem"]) or b.translations.get(d["id"], {}).get(lang, ({}, ""))[0].get("name_local")
        cmd = [sys.executable, str(HERE / "bio_translation.py"), "write", d["stem"], "--lang", lang, "--model", engine(),
               "--sections", " ".join(shash(x) for x in sections(text))]
        r = subprocess.run(cmd + (["--name", str(name)] if name else []), input=cache[key],
                           capture_output=True, text=True, cwd=b.paths.ROOT)
        if r.returncode:
            failed.append(f"{d['stem']} ({lang}): {r.stderr.strip()}")
        else:
            done += 1
            print(f"  {r.stdout.strip()}" + ("" if name else "  ⚠️ имя на этом языке не задано — латиница"))
    print(f"Автоперевод: переведено {done}" + (f", не удалось {len(failed)}:\n  " + "\n  ".join(failed) if failed else ""))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
