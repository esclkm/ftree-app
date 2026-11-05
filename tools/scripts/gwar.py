#!/usr/bin/env python3
"""Солдаты Первой мировой на gwar.mil.ru — поиск человека и всех карточек волости одной командой.

Зачем. Раньше каждый заход на gwar собирали руками из curl (навык archive-gwar), и скрипты пропадали вместе с
временной папкой. Главное, что даёт скрипт, — сбор по волости: не «есть ли Ясенев», а «все солдаты Лесогорской
волости» (458 карточек на 03.11.2026). В этом списке видны фамилии деревни, соседи и родня, которых по имени не найти.

Как работает. Запрос к поиску сайта (POST /gt_data/?builder=Heroes) через curl — так проходит и российский прокси
(`--proxy socks5h://…`), если сайт снова закроют для Польши. Сертификат Минцифры — tools/scripts/ca/ (root + sub,
проверка не отключается). Поиск сайта нечёткий: «Лесогорская» тянет и чужие волости, поэтому после выдачи
скрипт сам отбирает записи, где волость и губерния действительно совпали, и пишет оба числа. Выдача сохраняется
в $ARCHIVES_LOCAL/raw/gwar/<дата>/ вместе с полнотой: «получено 458 из 458» или «оборвалось на 1000».
Повторный запуск с тем же файлом докачивает, а не начинает заново.

    tools/py tools/scripts/gwar.py search --surname Ясенев --gubernia Гродненская
    tools/py tools/scripts/gwar.py volost Лесогорская --gubernia Гродненская          # все солдаты волости
    tools/py tools/scripts/gwar.py show <файл.json> --surnames                         # фамилии волости по числу карточек
    tools/py tools/scripts/gwar.py show <файл.json> --grep Дубняк                      # строки одной фамилии
    tools/py tools/scripts/gwar.py places <файл.json> … --target "Вербичи"             # написания деревень, похожие первыми
    tools/py tools/scripts/gwar.py page 10150438                                       # адрес скана по pages_id

Карточка в браузере: https://gwar.mil.ru/heroes/<тип><id>/ (chelovek_donesenie13122175). Поля волости, уезда и
губернии в разных карточках то отдельные, то внутри общей строки birth_place — отбор смотрит в обе.

Приёмы сбора по волости, сравнения написаний и чтения скана взяты из навыка ex-ussr-kinship-research
(github.com/DenisSergeevitch/ex-ussr-kinship-research, MIT, Denis Shiryaev), переписаны под наш проект.
"""
import argparse
import datetime
import difflib
import json
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import paths  # noqa: E402

BASE = "https://gwar.mil.ru"
CA = Path(__file__).parent / "ca" / "russian_trusted_ca.pem"
RAW = paths.ARCHIVES_RAW / "gwar"
PAUSE = 1.5          # секунд между запросами: сайт государственный, ведём себя тихо
PAGE = 500           # записей за запрос
KINDS = {            # короткое имя → тип карточки на сайте (список 06.10.2026, навык archive-gwar)
    "losses": "chelovek_donesenie", "hospital": "chelovek_gospital", "burial": "chelovek_zahoronenie",
    "pow": "chelovek_plen", "award": "chelovek_nagrazhdenie", "nomination": "chelovek_predstavlenie",
    "awardcard": "chelovek_nagradnaya_kartochka", "service": "chelovek_posluzhnoi_spisok",
    "record": "chelovek_uchetnaya_kartochka",
}
KIND_RU = {"chelovek_donesenie": "потери", "chelovek_gospital": "госпиталь", "chelovek_zahoronenie": "захоронение",
           "chelovek_plen": "плен", "chelovek_nagrazhdenie": "награда", "chelovek_predstavlenie": "представление",
           "chelovek_nagradnaya_kartochka": "наградная карточка", "chelovek_posluzhnoi_spisok": "послужной список",
           "chelovek_uchetnaya_kartochka": "учётная карточка"}


class Stop(Exception):
    """Сайт отказал (403/429/капча) или ответил не то — дальше не идём, состояние сохранено."""


def post(builder: str, body: dict, proxy: str | None) -> dict:
    cmd = ["curl", "-s", "--max-time", "90", "--cacert", str(CA), "-w", "\n%{http_code}",
           "-A", "Mozilla/5.0 (Macintosh) Chrome/128", "-H", "Content-Type: application/json",
           "-H", "X-Requested-With: XMLHttpRequest", "-H", f"Referer: {BASE}/heroes/", "-H", f"Origin: {BASE}",
           "--data-binary", json.dumps(body, ensure_ascii=False), f"{BASE}/gt_data/?builder={builder}"]
    if proxy:
        cmd[1:1] = ["-x", proxy]
    for attempt in range(3):
        out = subprocess.run(cmd, capture_output=True, text=True, errors="replace").stdout
        text, _, code = out.rpartition("\n")
        if code in ("403", "429") or re.search(r"captcha", text[:5000], re.I):
            raise Stop(f"сайт ответил {code} или капчей — стоп, повторять не надо")
        if code == "200" and not text.lstrip().startswith("<"):
            data = json.loads(text, strict=False)
            return data.get("response", data)
        time.sleep(5 * (attempt + 1))          # 000 / 503 / страница «технические работы»
    raise Stop(f"сайт не отвечает (последний код {code or '000'}); из Польши — нужен прокси, навык archive-gwar")


def total_of(box: dict) -> int:
    t = box.get("total")
    return t.get("value") if isinstance(t, dict) else t


def collect(fields: dict, kinds: list[str], out: Path, limit: int, proxy: str | None) -> dict:
    """Все страницы выдачи в один файл; файл же — контрольная точка для докачки."""
    query = {"fields": fields, "entities": kinds}
    state = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    if state and state.get("query") != query:
        sys.exit(f"{out} — выдача другого запроса; дайте другой --out")
    state = state or {"query": query, "total": None, "hits": [], "started": now()}
    seen = {(h["_type"], h["_id"]) for h in state["hits"]}
    try:
        while len(state["hits"]) < limit and (state["total"] is None or len(state["hits"]) < state["total"]):
            body = {"indices": ["gwar"], "entities": kinds, "queryFields": fields, "filterFields": {},
                    "facetField": None, "from": len(state["hits"]), "size": min(PAGE, limit - len(state["hits"])),
                    "builderType": "Heroes"}
            box = post("Heroes", body, proxy)["hits"]
            state["total"] = total_of(box)
            fresh = [h for h in box["hits"] if (h["_type"], h["_id"]) not in seen]
            if not fresh:
                break                          # сайт больше не отдаёт (у Elasticsearch бывает предел окна)
            seen |= {(h["_type"], h["_id"]) for h in fresh}
            state["hits"] += fresh
            save(out, state)
            time.sleep(PAUSE)
        state["stopped"] = None
    except Stop as e:
        state["stopped"] = str(e)
    state["complete"] = state["total"] is not None and len(state["hits"]) >= state["total"] and not state["stopped"]
    state["updated"] = now()
    save(out, state)
    return state


# --- отбор и показ -------------------------------------------------------------------------------------------

def norm(s: str) -> str:
    s = (s or "").lower().replace("ё", "е")
    return re.sub(r"\b(губ(ерния)?|уезд|у|вол(ость)?|д|дер|с|село|м)\.?(?=\s|,|$)", " ", s).strip()


def place_of(src: dict) -> str:
    return " ".join(str(src.get(k) or "") for k in
                    ("birth_place", "birth_place_volost", "birth_place_uezd", "birth_place_gubernia", "location"))


def matches(src: dict, need: dict) -> bool:
    """Нечёткий поиск сайта → строгий отбор: каждое заданное место есть в месте карточки (как основа слова)."""
    where = norm(place_of(src))
    return all(norm(v)[:-2] in where for v in need.values() if v)


def row(h: dict) -> str:
    s = h["_source"]
    name = " ".join(x for x in (s.get("last_name"), s.get("first_name"), s.get("middle_name")) if x)
    place = s.get("birth_place") or " ".join(x for x in (s.get("birth_place_volost"), s.get("birth_place_uezd")) if x)
    when = s.get("event_date_from") or s.get("data_vibitiya") or s.get("date_death") or ""
    what = s.get("vibitie_prichina") or s.get("award_name") or s.get("event_name") or ""
    unit = s.get("military_unit_name") or s.get("document_author") or ""
    return (f"{KIND_RU.get(h['_type'], h['_type']):<10} {h['_type']}{h['_id']:<10} {name:<36} | {place[:45]:<45} | "
            f"{unit[:38]} | {when} {what}")


def show(state: dict, need: dict, surnames: bool, grep: str | None, n: int) -> None:
    hits = state["hits"]
    kept = [h for h in hits if matches(h["_source"], need)] if any(need.values()) else hits
    print(f"Сайт нашёл {state['total']}, получено {len(hits)}"
          f"{'' if state.get('complete') else ' — НЕ ВСЁ: ' + (state.get('stopped') or 'упёрлись в предел')}; "
          f"после отбора по месту — {len(kept)}")
    if surnames:
        for name, c in Counter((h["_source"].get("last_name") or "?").strip() for h in kept).most_common():
            print(f"{c:4}  {name}")
        return
    if grep:
        key = norm(grep)[:5]
        kept = [h for h in kept if key in norm(json.dumps(h["_source"], ensure_ascii=False))]
    for h in sorted(kept, key=lambda h: (h["_source"].get("last_name") or "", h["_source"].get("first_name") or ""))[:n]:
        print(row(h))
    if len(kept) > n:
        print(f"… ещё {len(kept) - n} (--n побольше или --grep)")


# --- написания деревень ---------------------------------------------------------------------------------------

def skeleton(s: str) -> str:
    return re.sub(r"[аеиоуыэюяйьъ]", "", s)


def similarity(a: str, b: str) -> float:
    a, b = (re.sub(r"[^а-яa-z]", "", norm(x)) for x in (a, b))
    if not a or not b:
        return 0.0
    scores = [difflib.SequenceMatcher(None, a, b).ratio()]
    if skeleton(a) and skeleton(b):                      # «согласный остов»: Вербичи ~ Вербэчи ~ Вирбичи
        scores.append(difflib.SequenceMatcher(None, skeleton(a), skeleton(b)).ratio())
    return round(max(scores), 2)


def places(files: list[Path], target: str | None, n: int) -> None:
    """Без сети: как деревни записаны в сохранённых карточках, по волостям; похожие на --target — первыми."""
    groups: dict[tuple, Counter] = {}
    for f in files:
        for h in json.loads(f.read_text(encoding="utf-8"))["hits"]:
            s = h["_source"]
            parts = [p.strip() for p in (s.get("birth_place") or "").split(",") if p.strip()]
            unit = {u: s.get("birth_place_" + u) or next((p for p in parts if mark in p.lower()), "")
                    for u, mark in (("gubernia", "губ"), ("uezd", "уезд"), ("volost", "вол"))}
            rest = [p for p in parts if p not in unit.values()]
            village = ", ".join(rest) or "(деревня не указана)"
            key = (unit["gubernia"], unit["uezd"], unit["volost"])
            groups.setdefault(key, Counter())[village] += 1
    lines = [(similarity(target, v) if target else 0, c, " · ".join(x for x in k if x), v)
             for k, cnt in groups.items() for v, c in cnt.items()]
    for sim, c, where, v in sorted(lines, key=lambda x: (-x[0], -x[1]))[:n]:
        print(f"{sim:4.2f} {c:4}  {v:<30} {where}")


def page(ids: list[int], proxy: str | None) -> None:
    """Скан карточки: по pages_id (поле documents_pages) — путь картинки на сайте."""
    for pid in dict.fromkeys(ids):
        body = {"indices": ["gwar"], "entities": ["stranitsa"], "queryFields": {"linkedPages": [pid]},
                "filterFields": {}, "facetField": None, "from": 0, "size": 20, "builderType": "HeroesStranitsa"}
        for h in post("HeroesStranitsa", body, proxy)["hits"]["hits"]:
            xml = h["_source"].get("obraz_s_oblastyami", "")
            m = re.search(r"[\w\-/]+\.(?:jpe?g|png|tiff?)", xml, re.I)
            print(pid, f"{BASE}/cdn/imagesfww/{m.group(0).lstrip('/')}" if m else "(путь не найден)",
                  f"строк на скане: {xml.count('<s ')}")
        time.sleep(PAUSE)
    print("Скан часто отвечает 503 «технические работы» — повторять раз в 30 минут; в браузере открывается "
          f"{BASE}/heroes/document/<documents_id>/?page_id=<pages_id>")


# --- общее ----------------------------------------------------------------------------------------------------

def now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def save(path: Path, state: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def default_out(fields: dict) -> Path:
    slug = "_".join(re.sub(r"\W+", "", str(v)) for v in fields.values() if v)[:80] or "query"
    folder = RAW / datetime.date.today().isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{slug}.json"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search", help="поиск по имени, месту, полку")
    for f in ("surname", "given", "patronymic", "place", "regiment"):
        s.add_argument("--" + f)
    v = sub.add_parser("volost", help="все карточки волости")
    v.add_argument("volost")
    for p in (s, v):
        p.add_argument("--gubernia")
        p.add_argument("--uezd")
        p.add_argument("--kind", nargs="+", choices=["all", *KINDS], default=["all"])
        p.add_argument("--max", type=int, default=5000, help="не больше стольких записей")
        p.add_argument("--out", type=Path, help="файл выдачи (по умолчанию — archives/raw/gwar/<дата>/…)")
        p.add_argument("--proxy", help="socks5h://IP:PORT — если сайт закрыт для Польши")
        p.add_argument("--n", type=int, default=40, help="сколько строк показать")
    sh = sub.add_parser("show", help="показать сохранённую выдачу")
    sh.add_argument("file", type=Path)
    sh.add_argument("--surnames", action="store_true", help="фамилии по числу карточек")
    sh.add_argument("--grep")
    sh.add_argument("--n", type=int, default=60)
    pl = sub.add_parser("places", help="написания деревень в сохранённых выдачах (без сети)")
    pl.add_argument("files", type=Path, nargs="+")
    pl.add_argument("--target")
    pl.add_argument("--n", type=int, default=40)
    pg = sub.add_parser("page", help="адрес скана по pages_id")
    pg.add_argument("ids", type=int, nargs="+")
    pg.add_argument("--proxy")
    a = ap.parse_args()

    try:
        if a.cmd == "places":
            return places(a.files, a.target, a.n)
        if a.cmd == "page":
            return page(a.ids, a.proxy)
        if a.cmd == "show":
            st = json.loads(a.file.read_text(encoding="utf-8"))
            f = st["query"]["fields"]
            need = {k: f.get(k) for k in ("birth_place_volost", "birth_place_uezd", "birth_place_gubernia")}
            return show(st, need, a.surnames, a.grep, a.n)
        if a.cmd == "volost":
            fields = {"birth_place_volost": a.volost}
        else:
            fields = {k: getattr(a, x) for x, k in (("surname", "last_name"), ("given", "first_name"),
                      ("patronymic", "middle_name"), ("place", "birth_place"), ("regiment", "military_unit_name"))
                      if getattr(a, x)}
        fields |= {k: x for k, x in (("birth_place_uezd", a.uezd), ("birth_place_gubernia", a.gubernia)) if x}
        if not fields:
            sys.exit("Нужно имя, место или полк.")
        kinds = list(KINDS.values()) if "all" in a.kind else [KINDS[k] for k in dict.fromkeys(a.kind)]
        out = a.out or default_out(fields)
        st = collect(fields, kinds, out, a.max, a.proxy)
        print(f"Выдача: {out}")
        need = {k: fields.get(k) for k in ("birth_place_volost", "birth_place_uezd", "birth_place_gubernia")}
        show(st, need, False, None, a.n)
        sys.exit(0 if st["complete"] else 1)
    except Stop as e:
        sys.exit(f"Стоп: {e}")


if __name__ == "__main__":
    main()
