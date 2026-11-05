#!/usr/bin/env python3
"""Бесплатный фильтр метрик ГАСО на Mac, без ИИ-токенов (схема — документ дерева проект/МЕТРИКИ_СХЕМА.md).

Зачем: в книге сотни разворотов, читать их все облачной моделью дорого. Фильтр читает только клетки с людьми
(рукопись читает Manuscript-OCR, локально), ищет в них фамилии и деревни из `tree.py targets` — с поправкой на ошибки
распознавания — и отдаёт список «записей, на которые стоит посмотреть». Только они идут дальше (модель, человек).
Непрочитанное — «не проверено», а не «не наш».

    tools/py tools/scripts/metric_filter.py run   ф48_оп6_д525 [--workers 4] [--spreads 100-140] [--limit N]
    tools/py tools/scripts/metric_filter.py match ф48_оп6_д525 [--places Вербичи,Лесогорск]
    tools/py tools/scripts/metric_filter.py draft [--dir draft|checked]       # полнота: известные слова против распознанного
    tools/py tools/scripts/metric_filter.py report ф48_оп6_д525

Как идёт работа (одна книга):
  1) `etalon.vision` + `etalon.classify` — какая часть книги на развороте (рождения / браки / смерти; остальное пропускаем);
  2) `form_template.place` — шаблон бланка книги → колонки с людьми; `form_layout.record_starts` — где начинаются записи;
  3) колонка нарезается целиком (сверху вниз) и читается Manuscript-OCR — отдельным процессом в своём окружении
     (`metric_ocr_worker.py`, tools/.cache/venv-manuscript); строки текста раскладываются по записям по высоте;
  4) нечёткое сравнение (`find_hits`): фамилия и деревня из targets, написанные как угодно — ѣ/ъ/ь, -овъ/-ова/-овым,
     перенос слова, похожие буквы (н/п/и, ш/щ/ц, о/а). У крестьян фамилии часто нет («Иван Прокопов» — сын Прокопа), поэтому
     деревня считается отдельным, более слабым признаком;
  5) кандидаты: дело, разворот, номер записи (читается отдельно, «?» если не вышло), что совпало, оценка.

Где что лежит. Сырой результат OCR по клеткам — tools/.cache/metric_filter/<дело>/<разворот>.json (кэш, вне git).
Текст с именами и кандидаты — только на этом Mac: $ARCHIVES_LOCAL/text/gaso/<дело>/metric_text.jsonl и
metric_candidates.json. В каталог (git, без имён) — только статус разворота: поле `filter` строки дела (archives.py).
"""
import argparse
import json
import queue
import re
import subprocess
import sys
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

import name_forms
import paths  # noqa: E402
from paths import ARCHIVES_TEXT, ROOT

CACHE = paths.CACHE / "metric_filter"
VENV_PY = paths.CACHE / "venv-manuscript" / "bin" / "python"
WORKER = Path(__file__).resolve().with_name("metric_ocr_worker.py")
TEXT = ARCHIVES_TEXT / "gaso"
CACHE_VERSION = 2
PEOPLE = {"births": ["parents", "godparents"], "marriages": ["groom", "bride", "sureties"], "deaths": ["deceased"]}
DEFAULT_PLACES = ",".join(paths.tree_conf("metric_filter.places", []))   # деревни дерева — ftree.toml
CLERGY_MIN = 5            # раз на строках причта — и фамилия считается причтом книги
MIN_CELL_CHARS = 3        # клетка короче — «не прочитана»
HEAD_GAP = 0.08           # доля высоты: слово «шапки» дальше этого от остальных — уже из первой записи (д. 581, разв. 17)
WEAK_FIT = 0.4            # одна половина разворота легла на шаблон хуже GOOD_FIT — читать, если шапка за эту часть


# ═══ нечёткое сравнение (без сканов; тесты — tests/test_metric_filter.py) ══════════════════════════════════════════

_MAP = str.maketrans({"ѣ": "е", "і": "и", "ї": "и", "ѳ": "ф", "ѵ": "и", "й": "и", "ё": "е", "ъ": None, "ь": None,
                      "a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у", "k": "к", "t": "т",
                      "m": "м", "h": "н", "b": "в", "i": "и"})
# буквы, которые рукописное распознавание путает: замена внутри группы стоит 0,4, а не 1
_CONFUSED = ["ипнш", "шщц", "оае", "се", "вб", "лдя", "ая", "гтп", "ыи", "кх", "уч", "рф", "зэ", "нл", "тп", "еи"]
_PAIRS = {(a, b) for g in _CONFUSED for a in g for b in g if a != b}
_CASE = re.compile(r"(ыми|ами|ого|ому|ых|ым|им|ом|ои|ою|ую|ам|ах|ем|еи)$")
_WORD = re.compile(r"[А-Яа-яЁёѢѣІіѲѳЇї]+")


def norm(word: str) -> str:
    """Слово без ударений, в современных буквах, без ъ/ь: «Ясеневъ» → «ясенев»."""
    word = "".join(c for c in unicodedata.normalize("NFKD", word) if not unicodedata.combining(c) or c == "̆")
    return unicodedata.normalize("NFC", word).lower().translate(_MAP)


def stem(word: str) -> str:
    """Основа фамилии или деревни: без падежа и рода («Ясенева», «Ясеневым», «Ясеневъ» → «ясенев»).
    Если после обрезки осталось меньше 4 букв — слово не режем."""
    s = norm(word)
    s = _CASE.sub("", s) if len(s) > 5 else s
    t = re.sub(r"[аоуеыияю]+$", "", s)
    return t if len(t) >= 4 else s


def distance(a: str, b: str) -> float:
    """Расстояние правок; замена похожих при распознавании букв — дешёвая."""
    prev = [float(j) for j in range(len(b) + 1)]
    for i, ca in enumerate(a, 1):
        cur = [float(i)]
        for j, cb in enumerate(b, 1):
            sub = 0.0 if ca == cb else (0.4 if (ca, cb) in _PAIRS else 1.0)
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + sub))
        prev = cur
    return prev[-1]


@lru_cache(maxsize=200_000)
def similarity(a: str, b: str) -> float:
    """0…1 между двумя основами (уже нормализованными)."""
    if not a or not b:
        return 0.0
    return 1 - distance(a, b) / max(len(a), len(b))


THRESH = {"short": 0.72, "long": 0.65}      # короткая основа (4–5 букв) / длинная; --thresh меняет
PATRONYM_FREQUENT = 0.015    # доля разворотов: чаще — «частое слово» (в д. 525 частое «по отцу» — на 6 из 318, редкое — на 3)
PATRONYM_SIM = 0.78
B_SURNAME_SIM = 0.85
NAME_COMMON = 0.2       # имя в большей доле мест D — частое (Иван, Мария), не признак    # B «фамилия + деревня» без имени — только при почти точной фамилии; иначе C     # «по отцу» строже: при 0,65 одно такое слово находило две чужие фамилии на -ов (д. 525, 04.10.2026)


def threshold(length: int) -> float:
    """Чем короче основа, тем строже: на 4–5 буквах одна настоящая ошибка уже много."""
    return THRESH["short"] if length <= 5 else THRESH["long"]


def words_of(text: str) -> list[str]:
    """Слова текста по порядку; перенос «Катве-\\nровки» склеивается."""
    return _WORD.findall(re.sub(r"[-‐–]\s*\n\s*", "", text))


def join_lines(lines: list[str]) -> str:
    """Строки колонки одним текстом; строка, оканчивающаяся на «-», склеивается со следующей без пробела."""
    out = ""
    for line in lines:
        line = line.strip()
        out = (out[:-1] + line) if out.endswith("-") else (out + " " + line if out else line)
    return out


def candidates_in(text: str) -> list[tuple[str, str]]:
    """Слова текста и склейки соседних («Добро сердова»): (как написано, основа)."""
    ws = words_of(text)
    out = [(w, stem(w)) for w in ws if len(w) >= 3]
    out += [(a + b, stem(a + b)) for a, b in zip(ws, ws[1:]) if len(a) + len(b) >= 6 and len(a) <= 6]
    return out


_SURNAME_END = re.compile(r"(ов|ев|ин|ын|ск|цк)$")


def same_ending(target_stem: str, word_stem: str) -> bool:
    """У фамилии на -ов/-ев/-ин/-ын/-ск конец слова должен быть тем же (с поправкой на похожие буквы). Иначе «Прокопова»
    находила бы имя «Прокопъ» — сходство высокое, а это совсем другое слово."""
    m = _SURNAME_END.search(target_stem)
    return not m or distance(m.group(0), word_stem[-2:]) <= 1.0


def best_match(target_stem: str, found: list[tuple[str, str]], adjectival_ok: bool = False) -> tuple[float, str]:
    """Лучшее слово текста для основы: (сходство, слово как написано). Прилагательные на -ск/-цк («Вербичской
    волости») — это волость, а не деревня: их пропускаем, если искали не такое слово."""
    need = threshold(len(target_stem))
    best = (0.0, "")
    for word, st in found:
        if abs(len(st) - len(target_stem)) > 2:
            continue
        if not adjectival_ok and re.search(r"(ск|цк)$", st) and not re.search(r"(ск|цк)$", target_stem):
            continue
        if not same_ending(target_stem, st):
            continue
        s = similarity(target_stem, st)
        if s >= need and s > best[0]:
            best = (s, word)
    return best


_ABBR = re.compile(r"([А-Яа-яЁёѢѣІіѲѳЇї]{4,})\.")


def given_match(given: str, text: str) -> bool:
    """Имя есть в тексте — в любой своей форме («Иван» = «Іоаннъ», `name_forms`) или сокращением писаря с точкой
    («Евфр.» — начало формы, не короче 4 букв). Слабый признак, только усиливает."""
    words = [norm(w) for w in words_of(text)]
    abbr = [norm(a) for a in _ABBR.findall(text)]
    for g in map(norm, name_forms.forms(given)):
        if len(g) < 3:
            continue
        if any(similarity(g, w) >= 0.8 for w in words if abs(len(w) - len(g)) <= 2):
            return True
        if any(len(a) < len(g) and g.startswith(a) for a in abbr):
            return True
    return False


def find_hits(text: str, targets: dict) -> list[dict]:
    """Что из targets есть в тексте. targets = {"people": [{label, given, surname}], "villages": [name]}.
    Однофамильцы из дерева — один поиск: в ответе `people` (кто с такой фамилией) и `givens` (их имена)."""
    found = candidates_in(text)
    by_stem: dict[str, list[dict]] = {}
    for t in targets["people"]:
        st = stem(t["surname"])
        if len(st) >= 4:
            by_stem.setdefault(st, []).append(t)
    hits = []
    for st, people in by_stem.items():
        score, word = best_match(st, found)
        if score and all(p.get("patronym") for p in people) and score < PATRONYM_SIM:
            score = 0.0
        if score:
            givens = list(dict.fromkeys(p["given"] for p in people if p.get("given")))
            hits.append({"kind": "surname", "target": people[0]["surname"], "word": word, "sim": round(score, 2),
                         "people": [p["label"] for p in people], "givens": givens,
                         "ids": list(dict.fromkeys(p["id"] for p in people if p.get("id"))),
                         "patronym": all(p.get("patronym") for p in people),
                         "given": any(given_match(g, text) for g in givens)})
    for name in targets["villages"]:
        st = stem(name)
        score, word = best_match(st, found)
        if score >= 0.85 or (score and len(st) >= 6):
            hits.append({"kind": "village", "target": name, "word": word, "sim": round(score, 2)})
    return hits


def grade(hits: list[dict]) -> tuple[str, float]:
    """Оценка места: A — фамилия, рядом с ней имя из карточки и деревня; B — фамилия и имя рядом, либо фамилия и
    деревня; C — только фамилия (имя где-то в окне — чуть выше); D — только деревня (у крестьян фамилии нет — признак
    слабый, но не «нет»). «Имя рядом» — слово перед фамилией: «Иван Прокопов» = Иван, сын Прокопа."""
    sur = [h for h in hits if h["kind"] == "surname"]
    vil = [h for h in hits if h["kind"] == "village"]
    if not hits:
        return "", 0.0
    s = max((h["sim"] for h in sur), default=0.0)
    v = max((h["sim"] for h in vil), default=0.0)
    g = any(h.get("given") for h in sur)
    near = any(h.get("given_near") for h in sur)
    named = sum(1 for h in hits if h["kind"] == "given")
    score = s + (0.5 if g else 0.15 if near else 0) + (0.3 * v if sur else 0.5 * v) + min(0.8, 0.4 * named)
    if sur and vil == [] and all(h.get("patronym") and h.get("frequent") for h in sur):
        return "C", score - 0.5         # «Анна Прокопова» без деревни — частое сочетание, не сильнее одной фамилии
    if sur and g and vil:
        return "A", score
    if sur and vil and not g and not near and s < B_SURNAME_SIM:
        return "C", score       # «Никифазовъ» рядом с деревней — догадка машины, а не фамилия (д. 522–526, 05.10.2026)
    if sur and (g or vil):
        return "B", score
    if sur:
        return "C", score
    return "D", score


# ═══ цели: кого и где ищем ════════════════════════════════════════════════════════════════════════════════════════

def parse_target_lines(lines: list[str]) -> list[dict]:
    """Строки `tree.py targets` → люди с фамилией: «  Иван Ясенев (1878–1940) [P1]: …» → given/surname.
    Без фамилии («Агата (невеста, 1906)») — с `surname=None` и полным именем карточки в `name`: сами по себе они не цель
    (их ищет признак «деревня»), но ручные написания из `варианты_имён.toml` у них работают («Агата Прокопова»)."""
    out = []
    for line in lines:
        m = re.match(r"^\s{2}(.+?)\s*(?:\(|\[|:)", line)
        if not m:
            continue
        words = _WORD.findall(m.group(1))
        if len(words) >= 2:
            out.append({"label": f"{words[0]} {words[-1]}", "given": words[0], "surname": words[-1],
                        "name": m.group(1).strip()})
        elif words:
            full = re.match(r"^\s{2}(.+?)\s*\[", line)
            out.append({"label": words[0], "given": words[0], "surname": None,
                        "name": (full.group(1) if full else m.group(1)).strip()})
    return out


def as_written(person: dict, card, tree_people: dict) -> list[dict]:
    """Как ещё человек мог быть записан без фамилии: «имя + по отцу» (Иван, сын Прокопа → «Иван Прокопов») и ручные
    написания из `варианты_имён.toml`. Такая цель — кандидат, только если имя стоит прямо перед словом «по отцу»:
    «Прокопов» один — слишком частое слово."""
    out = []
    extra = name_forms.manual().get(card.id, {}) if card else {}
    givens = [person["given"], *extra.get("given", [])]
    fathers = [tree_people[f] for f in (card.father if card else []) if f in tree_people]
    for father in fathers:
        fg = _WORD.findall(father.stem)
        if fg:
            for sur in name_forms.patronymic_surnames(fg[0]):
                sur = sur.capitalize() + ("а" if card.sex == "F" else "")     # «Анна Прокопова»
                out += [{"label": person["label"], "given": g, "surname": sur, "patronym": True}
                        for g in givens]
    for written in extra.get("written", []):
        words = _WORD.findall(written)
        if len(words) >= 2:
            out.append({"label": person["label"], "given": words[0], "surname": words[-1], "patronym": True})
    return out


def load_targets(places: list[str], years: str) -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import cards
    import tree
    t = cards.load()
    by_stem = {p.stem: p for p in t.people.values()}
    people, villages = {}, []
    for place in places:
        for p in parse_target_lines(tree.targets(t, place, years, ROOT, None)):
            card = by_stem.get(p["name"])
            p["id"] = card.id if card else None
            if p["surname"]:
                people[p["label"]] = p
            for w in as_written(p, card, t.people):
                people[(w["label"], w["given"], w["surname"])] = {**w, "id": p["id"]}
        found = tree.find_place(t, place)
        names = [place] + [a for pl in found[:1] for a in [pl.name, *pl.aliases]]
        villages += [n for n in dict.fromkeys(names) if n and len(_WORD.findall(n)) == 1]
    return {"people": list(people.values()), "villages": list(dict.fromkeys(villages))}


def book_years(book: dict) -> str:
    m = re.search(r"(18\d\d|19\d\d)\s*[–-]\s*(18\d\d|19\d\d)", book["title"])
    return f"{m[1]}-{m[2]}" if m else "1880-1917"


# ═══ разворот → клетки → текст ════════════════════════════════════════════════════════════════════════════════════

def header_bottom_of(head_y1: list[float], horizontals: list[int], h: int) -> int:
    """Низ шапки: ближайшая линия под словами шапки. Слова шапки стоят кучкой; слово, оторванное от кучки вниз, —
    из первой записи, его и всё ниже не считаем,
    иначе низ шапки уходит к низу страницы и клетки получаются пустыми (10.10.2026: ≈170 разворотов д. 580–585)."""
    ys = sorted(head_y1)
    head_low = h * 0.2
    for i, y in enumerate(ys):
        if i and y - ys[i - 1] > h * HEAD_GAP:
            break
        head_low = y
    below = [y for y in horizontals if head_low - 5 <= y <= head_low + h * HEAD_GAP * 1.5]
    return int(min(below, default=head_low + 5))


def place_ok(r: dict, weak: bool) -> bool:
    """Шаблон лёг: обе половины ≥ GOOD_FIT. Со слабым порогом (часть известна по шапке или соседям) — обе ≥ WEAK_FIT
    или одна твёрдо (≥ 0,75): у другой линии не видны, её колонки — по месту из шаблона (form_template.place_tpl)."""
    sides = list(r["sides"].values())
    return r["ok"] or (weak and bool(sides) and (min(sides) >= WEAK_FIT or max(sides) >= 0.75))


def _layout(path: Path, book_id: str, section: str, vis: list[dict], weak: bool = False) -> dict:
    """Колонки с людьми, строки записей и низ шапки — по шаблону книги (без ИИ)."""
    import numpy as np
    from PIL import Image

    import form_layout as fl
    import form_template as ft
    r = ft.place(path, book_id, section)
    if not place_ok(r, weak):
        return {"state": "template_miss", "share": r["share"]}
    gray = np.asarray(Image.open(path).convert("L"))
    h, w = gray.shape
    verticals, horizontals = fl.lines(gray)
    if not all("h" in x for x in vis):            # старый кэш Vision — без рамок слов: прочитать заново
        vis = fl.vision(path)
    words = fl.header_words(vis, h, w)
    keyed = [wd for wd in words if re.search(fl.normalize(fl.HEAD_KEYS), fl.normalize(wd["text"]))
             and not re.search(fl.normalize(fl.TITLE), fl.normalize(wd["text"]))]
    header_bottom = header_bottom_of([wd["y1"] for wd in keyed], horizontals, h)
    mask = fl.dark_mask(gray)
    for x in r["verticals"]:
        mask[:, max(0, x - 4):x + 5] = False
    for y in horizontals:
        mask[max(0, y - 4):y + 5, :] = False
    cols = r["columns"]
    acts = [c for c in cols if c["field"] == "act"]
    dates = [c for c in cols if c["field"] in ("born", "date", "died")][:1]
    lead = acts + dates
    starts = (fl.record_starts(mask, min(c["x0"] for c in lead) + 6, max(c["x1"] for c in lead) - 6,
                               header_bottom + 8, h // 40) if lead else [])
    boxes = {}
    for field in PEOPLE[section]:
        fc = [c for c in cols if c["field"] == field]
        if fc:
            boxes[field] = [min(c["x0"] for c in fc), header_bottom + 4, max(c["x1"] for c in fc), int(h * 0.985)]
    act_box = [min(c["x0"] for c in acts), 0, max(c["x1"] for c in acts), int(h * 0.985)] if acts else None
    return {"state": "ok", "share": r["share"], "size": [w, h], "header_bottom": header_bottom, "starts": starts,
            "boxes": boxes, "act_box": act_box}


class Pool:
    """Несколько процессов Manuscript-OCR; задача — клетка, ответ — строки текста с положением."""

    def __init__(self, n: int):
        self.idle: queue.Queue = queue.Queue()
        self.procs = []
        for _ in range(n):
            proc = subprocess.Popen([str(VENV_PY), str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, text=True, bufsize=1,
                                    env={**__import__("os").environ, "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2"})
            self.procs.append(proc)
        for proc in self.procs:
            ready = proc.stdout.readline()
            if '"ready"' not in ready:
                raise RuntimeError("Manuscript-OCR не запустился: " + ready)
            self.idle.put(proc)

    def read(self, image: Path, box: list[int]) -> dict:
        proc = self.idle.get()
        try:
            proc.stdin.write(json.dumps({"id": 0, "image": str(image), "box": box}) + "\n")
            proc.stdin.flush()
            return json.loads(proc.stdout.readline())
        finally:
            self.idle.put(proc)

    def close(self):
        for proc in self.procs:
            proc.stdin.close()
            proc.wait(timeout=20)


def cache_path(book_id: str, n: int) -> Path:
    return CACHE / book_id / f"{n:03d}.json"


def load_cache(book_id: str, n: int) -> dict | None:
    p = cache_path(book_id, n)
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("version") == CACHE_VERSION:
            return d
    return None


def save_cache(book_id: str, n: int, data: dict) -> None:
    p = cache_path(book_id, n)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({**data, "version": CACHE_VERSION}, ensure_ascii=False), encoding="utf-8")


def read_spread(pool: Pool, path: Path, book_id: str, n: int, section: str, vis: list[dict], weak: bool = False) -> dict:
    """Один разворот целиком: разметка → OCR колонок. Результат — в кэш. Ни строки текста — «empty», а не «ok»:
    такой разворот не прочитан, и следующий прогон возьмёт его снова."""
    t0 = time.time()
    lay = _layout(path, book_id, section, vis, weak)
    data = {"n": n, "section": section, **lay, "cells": {}}
    if lay["state"] == "ok":
        for field, box in lay["boxes"].items():
            r = pool.read(path, box)
            data["cells"][field] = {"lines": r["lines"], "error": r["error"]}
        if not any(c["lines"] for c in data["cells"].values()):
            data["state"] = "empty"
    data["seconds"] = round(time.time() - t0, 1)
    save_cache(book_id, n, data)
    return data


def choose_section(path: Path, book_id: str, vis: list[dict], forms: dict, hint: tuple = ()) -> tuple[str | None, str]:
    """Какая часть книги на развороте. Печатную шапку Vision читает с ошибками (на д. 525 — у половины разворотов),
    поэтому: сначала шапка, но решает шаблон бланка — та часть, чей шаблон ложится на линии скана. Ничего не
    легло — None и причина («не проверено», а не «не наш»). hint — часть по соседним разворотам: шапка не прочиталась,
    а до и после — эти части (д. 581, разв. 263–265 — хвост рождений перед браками): берём ту, чей шаблон лёг лучше."""
    import etalon
    import form_template as ft
    c = etalon.classify(vis)
    if c["lines"] < 40:
        return None, "blank"                        # титул, пустая страница, вклейка
    order = ([c["section"]] if c["section"] in PEOPLE else []) + [s for s in PEOPLE if s != c["section"]]
    best = (0.0, None)
    for section in order:
        if section not in forms:
            continue
        r = ft.place(path, book_id, section)
        if r["ok"] and r["share"] > best[0]:
            best = (r["share"], section)
        if r["ok"] and section == c["section"] and r["share"] >= 0.75:
            return section, "header"                # шапка и шаблон согласны
    if best[1] and best[0] >= 0.7:
        return best[1], "template"
    known = [c["section"]] if c["section"] in PEOPLE else list(hint)
    tries = [(r, s_) for s_ in dict.fromkeys(known) if s_ in forms
             for r in [ft.place(path, book_id, s_)] if place_ok(r, weak=True)]
    if tries:
        r, s_ = max(tries, key=lambda t: (min(t[0]["sides"].values()), t[0]["share"]))
        return s_, "weak"                           # одна половина легла хуже, но часть известна
    return None, "unknown" if c["section"] not in PEOPLE else "template_miss"


def neighbour_sections(heads: list[dict]) -> list[tuple]:
    """Часть по соседям: части ближайших страниц с таблицей до и после (одна, если совпали)."""
    sec = [h["section"] if h["section"] in PEOPLE and h["lines"] >= 40 else None for h in heads]
    out = []
    for i in range(len(sec)):
        before = next((s for s in reversed(sec[:i]) if s), None)
        after = next((s for s in sec[i + 1:] if s), None)
        out.append(tuple(dict.fromkeys(x for x in (before, after) if x)))
    return out


def run(args) -> int:
    import etalon
    import form_template as ft
    book = ft.book_by_id(args.book)
    lo, hi = book["first"], book["last"]
    if args.spreads:
        a, b = args.spreads.split("-")
        lo, hi = max(lo, int(a)), min(hi, int(b))
    numbers = [n for n in range(lo, hi + 1) if etalon.scan(book, n).exists()]
    if args.limit:
        numbers = numbers[:args.limit]
    forms = json.loads(ft.forms_path(args.book).read_text(encoding="utf-8"))["sections"]
    t0 = time.time()
    vis = etalon.vision([etalon.scan(book, n) for n in numbers])
    todo, skipped = [], {}
    hints = neighbour_sections([etalon.classify(vis[str(etalon.scan(book, n))]) for n in numbers])
    for n, hint in zip(numbers, hints):
        path = etalon.scan(book, n)
        cached = load_cache(args.book, n)
        retry = cached and (cached.get("state") == "empty"                # пустое чтение — читать снова
                            or cached.get("section") in ("template_miss", "unknown"))   # решить заново — дёшево
        if cached and not retry:
            continue
        section, why = choose_section(path, args.book, vis[str(path)], forms, hint)
        if section:
            todo.append((n, section, why == "weak"))
        else:
            skipped[n] = why
            save_cache(args.book, n, {"n": n, "section": why, "state": "skipped", "cells": {}, "seconds": 0})
    print(f"{args.book}: разворотов {len(numbers)}, к чтению {len(todo)}, пропущено (не метрика с людьми) {len(skipped)}; "
          f"Vision {time.time() - t0:.0f} с", file=sys.stderr)
    pool = Pool(args.workers)
    done = [0]
    lock = threading.Lock()

    def job(item):
        n, section, weak = item
        path = etalon.scan(book, n)
        try:
            read_spread(pool, path, args.book, n, section, vis[str(path)], weak)
        except Exception as e:  # noqa: BLE001
            save_cache(args.book, n, {"n": n, "section": section, "state": f"error: {type(e).__name__}: {e}", "cells": {},
                                      "seconds": 0})
        with lock:
            done[0] += 1
            if done[0] % 10 == 0 or done[0] == len(todo):
                print(f"  {done[0]}/{len(todo)}  {time.time() - t0:.0f} с", file=sys.stderr, flush=True)

    try:
        with ThreadPoolExecutor(args.workers) as ex:
            list(ex.map(job, todo))
    finally:
        pool.close()
    print(f"готово: {len(todo)} разворотов за {time.time() - t0:.0f} с")
    return 0


# ═══ записи и кандидаты ═══════════════════════════════════════════════════════════════════════════════════════════

def split_records(data: dict) -> list[dict]:
    """Строки текста всех клеток разворота — по записям (по высоте). Запись -1 — то, что выше первой строки
    (продолжение с прошлого разворота). Нет найденных начал — вся страница одна запись."""
    starts = data.get("starts") or []
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    pad = min(25, 0.3 * (sorted(gaps)[len(gaps) // 2] if gaps else 0))
    bounds = [s - pad for s in starts]
    recs = {}
    for field, cell in data["cells"].items():
        for ln in sorted(cell["lines"], key=lambda x: x["y"]):
            idx = sum(1 for b in bounds if ln["y"] >= b) - 1 if bounds else 0     # -1 — выше первой записи
            recs.setdefault(idx, {}).setdefault(field, []).append(ln["text"])
    out = []
    for idx in sorted(recs):
        fields = {f: join_lines(v) for f, v in recs[idx].items()}
        y = starts[idx] if bounds and idx >= 0 else None
        out.append({"index": idx + 1 if idx >= 0 else 0, "y": y, "fields": fields})
    # записи без текста — начало есть, а клетки пустые: «не прочитано»
    have = {r["index"] for r in out}
    bottom = data.get("size", [0, 2 * (starts[-1] if starts else 0)])[1]
    for i, s in enumerate(starts, 1):
        nxt = starts[i] if i < len(starts) else bottom
        if i not in have and nxt - s >= 100:          # короче — вероятно, чернильное пятно, а не запись
            out.append({"index": i, "y": s, "fields": {}})
    return sorted(out, key=lambda r: r["index"])


def cells_unread(section: str, rec: dict) -> int:
    """Сколько клеток записи (из тех, где живут люди) пусты или короче порога."""
    return sum(1 for f in PEOPLE[section] if len(re.sub(r"\W", "", rec["fields"].get(f, ""))) < MIN_CELL_CHARS)


def spread_status(data: dict) -> dict:
    """Статус разворота для каталога (без имён)."""
    if data.get("state") == "skipped":
        return {"state": "skipped", "section": data["section"]}
    if data.get("state") != "ok":
        return {"state": "unchecked", "why": data.get("state"), "section": data.get("section")}
    recs = [r for r in split_records(data) if r["index"] > 0]
    unread = sum(1 for r in recs if cells_unread(data["section"], r) == len(PEOPLE[data["section"]]))
    return {"state": "read", "section": data["section"], "records": len(recs), "unread": unread}


WINDOW = 150              # пикселей по высоте разворота: «одна запись» вокруг найденной фамилии (запись ≈ 200–230)


def spread_segments(data: dict) -> list[tuple[float, str, str]]:
    """Строки всех клеток разворота: (высота, поле, текст); перенос на «-» склеен со следующей строкой."""
    segs: list[tuple[float, str, str]] = []
    for field, cell in data["cells"].items():
        glue = False
        for ln in sorted(cell["lines"], key=lambda x: x["y"]):
            text = ln["text"].strip()
            if glue and segs:
                y, f, prev = segs[-1]
                segs[-1] = (y, f, prev[:-1] + text)
            else:
                segs.append((ln["y"], field, text))
            glue = segs[-1][2].endswith("-")
    return segs


CLERGY = re.compile(r"свящ|священ|дьяк|дѣяк|диак|дiак|дiяк|псалом|псал|иерей|причетн|и\.?\s*об\.", re.I)


def clergy_lines(segs: list[tuple[float, str, str]]) -> set[int]:
    """Номера строк, где подписывается причт: «Священникъ Стефанъ Кленовъ», «Дьяконъ …», «Псаломщикъ …» и короткая
    строка-перенос сразу после. Эти фамилии стоят под каждой записью и ничего не говорят о семье."""
    out = set()
    for i, (y, field, text) in enumerate(segs):
        if CLERGY.search(norm(text)) or CLERGY.search(text):
            out.add(i)
        elif i - 1 in out and segs[i - 1][1] == field and len(words_of(text)) <= 3 and y - segs[i - 1][0] < 60:
            out.add(i)
    return out


def given_before(segs: list[tuple[float, str, str]], i: int, word: str, givens: list[str]) -> bool:
    """Имя из карточки — одно из двух слов прямо перед найденной фамилией (в начале строки — в конце прошлой строки той же
    колонки)."""
    words = words_of(segs[i][2])
    pos = next((k for k, w in enumerate(words) if w == word or (word.startswith(w) and k + 1 < len(words)
                                                              and word == w + words[k + 1])), None)
    if pos is None:
        return False
    before = words[max(0, pos - 2):pos]
    if len(before) < 2 and i > 0 and segs[i - 1][1] == segs[i][1]:
        before = words_of(segs[i - 1][2])[-(2 - len(before)):] + before
    return any(given_match(g, " ".join(before)) for g in givens)


STRONG = 0.85              # совпадение фамилии, которое считается при поиске причта
EXACT = 0.95               # почти точная фамилия не выбрасывается никогда


def common_surnames(cands: list[dict], read: int, share: float) -> dict[str, int]:
    """Фамилии, которые уверенно стоят больше чем на доле `share` прочитанных разворотов, — это причт.
    Слабые совпадения не считаем: короткая фамилия нечётко похожа на «Исповѣ…» из каждой записи (FamilySearch, 1871),
    и без этого настоящая такая фамилия выбрасывалась вместе с мусором. Ответ — фамилия → на скольких разворотах стоит."""
    spreads_with: dict[str, set] = {}
    for c in cands:
        for h in c["hits"]:
            if h["kind"] == "surname" and not h.get("patronym") and h.get("sim", 1.0) >= STRONG:
                spreads_with.setdefault(h["target"], set()).add(c["n"])
    return {t: len(ns) for t, ns in spreads_with.items() if len(ns) > share * max(1, read)}


def clergy_counts(segs: list[tuple[float, str, str]], targets: dict) -> dict[str, int]:
    """Сколько раз каждая целевая фамилия стоит на строке причта на этом развороте (священник, дьякон, псаломщик)."""
    out: dict[str, int] = {}
    clergy = clergy_lines(segs)
    for i, (_, _, text) in enumerate(segs):
        if i in clergy:
            for h in find_hits(text, targets):
                if h["kind"] == "surname" and not h.get("patronym"):    # «по отцу» отсеивает имя рядом, не причт
                    out[h["target"]] = out.get(h["target"], 0) + 1
    return out


def spread_candidates(segs: list[tuple[float, str, str]], targets: dict, keep_clergy: bool = False,
                      clergy: frozenset | set = frozenset()) -> list[dict]:
    """Кандидаты разворота. Записи не режем (начала записей по чернилам ненадёжны): вокруг каждой найденной фамилии
    берём окно ±WINDOW по высоте, в нём ищем имя из карточки и деревни; деревня без фамилии — слабый кандидат D."""
    events = []
    lines = clergy_lines(segs)
    for i, (y, field, text) in enumerate(segs):
        for h in find_hits(text, targets):
            if h["kind"] == "surname" and ((i in lines and not keep_clergy) or h["target"] in clergy):
                continue
            if h.get("patronym") and not given_before(segs, i, h["word"], h["givens"]):
                continue                    # «Прокопов» без «Иван» прямо перед ним — частое слово, не признак
            events.append({**h, "y": y, "field": field, "i": i, "given": False if h["kind"] == "surname" else None})
    sur = sorted((e for e in events if e["kind"] == "surname"), key=lambda e: e["y"])
    vil = [e for e in events if e["kind"] == "village"]

    def text_between(lo, hi):
        return "\n".join(f"[{f}] {t}" for y, f, t in segs if lo <= y <= hi)

    groups: list[list[dict]] = []
    for e in sur:
        if groups and e["y"] - groups[-1][-1]["y"] <= WINDOW:
            groups[-1].append(e)
        else:
            groups.append([e])
    cands = []
    for g in groups:
        lo, hi = g[0]["y"] - WINDOW, g[-1]["y"] + WINDOW
        window = text_between(lo, hi)
        hits = {}
        for e in g:
            if e["target"] not in hits or e["sim"] > hits[e["target"]]["sim"]:
                adjacent = given_before(segs, e["i"], e["word"], e["givens"])
                hits[e["target"]] = {**e, "given": adjacent,
                                     "given_near": not adjacent and any(given_match(x, window) for x in e["givens"])}
        for e in vil:
            if lo <= e["y"] <= hi and (e["target"] not in hits or e["sim"] > hits[e["target"]]["sim"]):
                hits[e["target"]] = e
        cands.append({"y0": g[0]["y"], "y1": g[-1]["y"], "hits": list(hits.values()), "context": window})
    covered = [(c["y0"] - WINDOW, c["y1"] + WINDOW) for c in cands]
    alone = sorted((e for e in vil if not any(lo <= e["y"] <= hi for lo, hi in covered)), key=lambda e: e["y"])
    groups = []
    for e in alone:
        if groups and e["y"] - groups[-1][-1]["y"] <= WINDOW:
            groups[-1].append(e)
        else:
            groups.append([e])
    for g in groups:
        best = {}
        for e in g:
            if e["target"] not in best or e["sim"] > best[e["target"]]["sim"]:
                best[e["target"]] = e
        context = text_between(g[0]["y"] - WINDOW, g[-1]["y"] + WINDOW)
        cands.append({"y0": g[0]["y"], "y1": g[-1]["y"], "hits": list(best.values()) + names_near(context, targets),
                      "context": context})
    for c in cands:
        c["grade"], c["score"] = grade(c["hits"])
        c["score"] = round(c["score"], 2)
    return cands


def names_near(text: str, targets: dict) -> list[dict]:
    """Для места «только деревня» (D): имена людей дерева из этих мест, которые есть в окне в любой форме («Нинъ» =
    Нил). Фамилию машина могла не разобрать, а имя — разобрать; такое D смотрим первым. Частые имена (Иван, Мария)
    отсеивает `match` по доле мест D, где они встретились."""
    by_given: dict[str, list[str]] = {}
    for p in targets["people"]:
        if not p.get("patronym") and p.get("given") and p.get("id"):
            by_given.setdefault(p["given"], []).append(p["id"])
    return [{"kind": "given", "target": g, "word": g, "sim": 1.0, "ids": list(dict.fromkeys(ids))}
            for g, ids in by_given.items() if given_match(g, text)]


def act_number(act_lines: list[dict], y: float) -> str | None:
    """Номер записи: число из колонки «Счёт» над найденным местом (ближайшее выше, не дальше 350 пикселей)."""
    best = None
    for ln in act_lines:
        m = re.search(r"\d{1,4}", ln["text"])
        if m and ln["y"] <= y + 40 and y - ln["y"] <= 350 and (best is None or ln["y"] > best[0]):
            best = (ln["y"], m.group(0))
    return best[1] if best else None


def match(args) -> int:
    import archives
    import etalon
    import form_template as ft
    book = ft.book_by_id(args.book)
    targets = load_targets([p for p in (args.places or DEFAULT_PLACES).split(",") if p], args.years or book_years(book))
    out_dir = TEXT / args.book
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = archives.pages(args.book)
    cands, texts, stats = [], [], {"spreads": 0, "read": 0, "skipped": 0, "unchecked": 0, "records": 0,
                                  "records_unread": 0, "cells": 0, "cells_unread": 0, "seconds": 0.0}
    t0 = time.time()
    # проход 1: чей это причт — фамилия, которая ≥ CLERGY_MIN раз стоит на строках «Священникъ/Дьяконъ/Псаломщикъ»
    on_clergy: dict[str, int] = {}
    for n in range(book["first"], book["last"] + 1):
        data = load_cache(args.book, n)
        if data and data.get("state") == "ok":
            for t, k in clergy_counts(spread_segments(data), targets).items():
                on_clergy[t] = on_clergy.get(t, 0) + k
    clergy = {t for t, k in on_clergy.items() if k >= CLERGY_MIN}
    for n in range(book["first"], book["last"] + 1):
        data = load_cache(args.book, n)
        if not data:
            continue
        stats["spreads"] += 1
        status = spread_status(data)
        if n in pages:
            pages[n]["filter"] = status
        if status["state"] == "skipped":
            stats["skipped"] += 1
            continue
        if status["state"] != "read":
            stats["unchecked"] += 1
            continue
        stats["read"] += 1
        stats["seconds"] += data["seconds"]
        for rec in split_records(data):
            texts.append({"n": n, "section": data["section"], "record": rec["index"], "fields": rec["fields"]})
            if rec["index"] > 0:
                unread = cells_unread(data["section"], rec)
                stats["records"] += 1
                stats["cells"] += len(PEOPLE[data["section"]])
                stats["cells_unread"] += unread
                stats["records_unread"] += unread == len(PEOPLE[data["section"]])
        for c in spread_candidates(spread_segments(data), targets, clergy=clergy):
            cands.append({"book": args.book, "n": n, "section": data["section"], "act": None, **c})
    # фамилия, что стоит почти на каждом развороте, — причт (священник подписывает каждую запись): не признак семьи
    common = common_surnames(cands, stats["read"], args.common_share)
    if common:
        kept = []
        for c in cands:
            c["hits"] = [h for h in c["hits"]
                         if not (h["kind"] == "surname" and h["target"] in common and h["sim"] < EXACT)]
            if c["hits"]:
                c["grade"], c["score"] = grade(c["hits"])
                c["score"] = round(c["score"], 2)
                kept.append(c)
        cands = kept
    # имя рядом с деревней (D), встречающееся в каждом пятом D, — частое имя, не признак
    d_cands = [c for c in cands if c["grade"] == "D"]
    by_name: dict[str, int] = {}
    for c in d_cands:
        for h in c["hits"]:
            if h["kind"] == "given":
                by_name[h["target"]] = by_name.get(h["target"], 0) + 1
    common_names = {t for t, k in by_name.items() if k > NAME_COMMON * max(1, len(d_cands))}
    for c in d_cands:
        c["hits"] = [h for h in c["hits"] if not (h["kind"] == "given" and h["target"] in common_names)]
        c["grade"], c["score"] = grade(c["hits"])
        c["score"] = round(c["score"], 2)
    # «по отцу» частое в книге («Прокопова» — на каждом десятом развороте) без деревни — не сильнее одной фамилии
    pat = {}
    for c in cands:
        for h in c["hits"]:
            if h.get("patronym"):
                pat.setdefault(h["target"], set()).add(c["n"])
    frequent = {t for t, ns in pat.items() if len(ns) > PATRONYM_FREQUENT * max(1, stats["read"])}
    for c in cands:
        if any(h.get("patronym") for h in c["hits"]):
            for h in c["hits"]:
                h["frequent"] = h.get("target") in frequent
            c["grade"], c["score"] = grade(c["hits"])
            c["score"] = round(c["score"], 2)
    match_seconds = time.time() - t0
    if args.acts and cands:                       # номера записей — только для кандидатов
        pool = Pool(args.workers)
        try:
            for c in cands:
                data = load_cache(args.book, c["n"])
                if "act_lines" not in data and data.get("act_box"):
                    r = pool.read(etalon.scan(book, c["n"]), data["act_box"])
                    data["act_lines"] = r["lines"]
                    save_cache(args.book, c["n"], data)
                c["act"] = act_number(data.get("act_lines", []), c["y0"])
        finally:
            pool.close()
    cands.sort(key=lambda c: ("ABCD".index(c["grade"]), -c["score"], c["n"]))
    archives.write_pages(args.book, pages)
    (out_dir / "metric_candidates.json").write_text(json.dumps(
        {"book": args.book, "targets": {"people": len(targets["people"]), "villages": targets["villages"],
                     "excluded_as_clergy": {t: on_clergy[t] for t in sorted(clergy)},
                     "excluded_as_common": {t: common[t] for t in sorted(common)}},
         "stats": stats, "candidates": cands}, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "metric_text.jsonl").write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in texts),
                                               encoding="utf-8")
    by_grade = {g: sum(1 for c in cands if c["grade"] == g) for g in "ABCD"}
    print(f"{args.book}: разворотов в кэше {stats['spreads']} (прочитано {stats['read']}, пропущено как не метрика "
          f"{stats['skipped']}, не проверено {stats['unchecked']}); OCR {stats['seconds']:.0f} с, сравнение {match_seconds:.0f} с")
    print(f"записей ≈{stats['records']} (по чернилам, приблизительно); клеток {stats['cells']}, не прочитано "
          f"{stats['cells_unread']} ({stats['cells_unread'] / max(1, stats['cells']):.0%}); записей совсем без текста "
          f"{stats['records_unread']}")
    print(f"целей: людей с фамилией {len(targets['people'])}, деревень {targets['villages']}")
    if clergy:
        print("исключены как причт книги (стоят на строках священник/дьякон/псаломщик): "
              + ", ".join(f"{t} ({on_clergy[t]} раз)" for t in sorted(clergy)))
    if common:
        print("исключены как «в каждом втором развороте» (скорее причт): "
              + ", ".join(f"{t} ({common[t]} разв.)" for t in sorted(common)))
    print(f"кандидатов {len(cands)}: {by_grade} (A фамилия+имя+деревня, B, C только фамилия, D только деревня)")
    print(f"→ {out_dir}/metric_candidates.json (с именами, не в git)")
    return 0


# ═══ полнота на черновиках / эталоне ══════════════════════════════════════════════════════════════════════════════

STOP = set(map(norm, """волости волость деревни деревня деревне губернии губерния уезда уезд православные православный
православная православного православной оба жена его крестьянин крестьянина крестьянка крестьянки вероисповедания
священник дьякон диакон псаломщик той же дочь сын вдова вдовец первым вторым браку жениха невесты невесты которым
состоящий рядовой запасной запаса рядового солдат солдатка мещанин мещанка жителя села село слободы слобода приходе
прихода покровской успенской церкви церковь званiе имя отчество фамилiя родителей восприемников поручители поручитель
жениху невесте жениху нрзб надворная советница дворянин дворянка князь""".split()))
SURNAMELIKE = re.compile(r"(ов|ев|ин|ын|ск|цк|ич|ук|юк|ко|ова|ева|ина|ына)$")


def known_words(record: dict, section: str) -> list[str]:
    """Слова-имена из размеченной записи (черновик или эталон): с заглавной буквы, не служебные, не [нрзб]."""
    out = []
    for f in PEOPLE.get(section, []):
        text = re.sub(r"\[[^\]]*\]", " ", str(record.get(f, "")))
        for w in _WORD.findall(text):
            if w[0].isupper() and len(w) >= 4 and norm(w) not in STOP:
                out.append(w)
    return out


def draft(args) -> int:
    import etalon
    import form_template as ft
    base = ARCHIVES_TEXT / "etalon" / args.dir
    label = "по черновику, не по эталону" if args.dir == "draft" else "по эталону"
    pool = Pool(args.workers)
    total = {"all": [0, 0], "surname": [0, 0], "village": [0, 0]}
    per_page = []
    try:
        for f in sorted(base.glob("ф48_*.json")):
            d = json.loads(f.read_text(encoding="utf-8"))
            recs = d.get("records") or []
            if not recs:
                continue
            m = re.match(r"(ф48_оп\d+_д\d+)_(\d+)$", f.stem)
            book_id, n = m[1], int(m[2])
            book = ft.book_by_id(book_id)
            sec = "births" if "parents" in recs[0] else "marriages" if "groom" in recs[0] else "deaths" if "deceased" in recs[0] else None
            if not sec or not ft.forms_path(book_id).exists() or sec not in json.loads(
                    ft.forms_path(book_id).read_text(encoding="utf-8"))["sections"]:
                per_page.append((f.stem, sec, "нет шаблона", 0, 0))
                continue
            data = load_cache(book_id, n)
            if not data or data.get("state") != "ok":
                path = etalon.scan(book, n)
                vis = etalon.vision([path])[str(path)]
                data = read_spread(pool, path, book_id, n, sec, vis)
            if data.get("state") != "ok":
                per_page.append((f.stem, sec, data.get("state"), 0, 0))
                continue
            ocr = " ".join(ln["text"] for c in data["cells"].values() for ln in c["lines"])
            found = candidates_in(ocr)
            hit = tot = 0
            for rec in recs:
                for w in dict.fromkeys(known_words(rec, sec)):
                    kind = "village" if re.search(r"(дер\.?|деревни|села|слободы)\s+" + re.escape(w), json.dumps(rec, ensure_ascii=False)) \
                        else "surname" if SURNAMELIKE.search(norm(w)) else "all"
                    ok = bool(best_match(stem(w), found, adjectival_ok=True)[0]) if len(stem(w)) >= 4 else None
                    if ok is None:
                        continue
                    for k in {"all", kind}:
                        total[k][0] += ok
                        total[k][1] += 1
                    hit += ok
                    tot += 1
            per_page.append((f.stem, sec, f"записей {len(recs)}, OCR {data['seconds']} с", hit, tot))
    finally:
        pool.close()
    print(f"Полнота {label}: известные слова-имена из разметки, найденные в распознанном тексте той же страницы")
    for stem_, sec, note, hit, tot in per_page:
        print(f"  {stem_} {sec}: {hit}/{tot} {note}")
    for k, name in (("all", "все имена и отчества"), ("surname", "похожие на фамилии (-ов/-ин/-ский…)"),
                    ("village", "деревни")):
        h, t = total[k]
        print(f"  {name}: {h}/{t} = {h / max(1, t):.0%}")
    return 0


def report(args) -> int:
    path = TEXT / args.book / "metric_candidates.json"
    if not path.exists():
        print("нет отчёта — сначала match")
        return 1
    d = json.loads(path.read_text(encoding="utf-8"))
    print(json.dumps(d["stats"], ensure_ascii=False))
    for c in d["candidates"][:args.top]:
        print(c["grade"], c["score"], f"разв. {c['n']} {c['section']} y≈{round(c['y0'])} №{c['act'] or '?'}",
              "; ".join(f"{h['kind']}:{h['target']}~{h['word']}({h['sim']})" for h in c["hits"]))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("run")
    s.add_argument("book")
    s.add_argument("--workers", type=int, default=4)
    s.add_argument("--spreads", help="диапазон файлов, например 100-140")
    s.add_argument("--limit", type=int)
    s.set_defaults(func=run)
    s = sub.add_parser("match")
    s.add_argument("book")
    s.add_argument("--places")
    s.add_argument("--years")
    s.add_argument("--workers", type=int, default=3)
    s.add_argument("--no-acts", dest="acts", action="store_false")
    s.add_argument("--common-share", type=float, default=0.2, help="фамилия в большей доле разворотов — причт, исключаем")
    s.set_defaults(func=match)
    s = sub.add_parser("draft")
    s.add_argument("--dir", default="draft", choices=("draft", "checked"))
    s.add_argument("--workers", type=int, default=2)
    s.set_defaults(func=draft)
    s = sub.add_parser("report")
    s.add_argument("book")
    s.add_argument("--top", type=int, default=30)
    s.set_defaults(func=report)
    for sp in (s for s in sub.choices.values() if s.prog.endswith(("match", "draft"))):
        sp.add_argument("--thresh", help="порог сходства «короткая,длинная», например 0.72,0.65 (по умолчанию 0.72,0.65 — мягкий)")
    args = p.parse_args()
    if getattr(args, "thresh", None):
        THRESH["short"], THRESH["long"] = map(float, args.thresh.split(","))
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
