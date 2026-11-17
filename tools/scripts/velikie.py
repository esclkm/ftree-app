"""velikie — «Великія описи» (inv.velikie.org) и их снимки (f.velikie.org) без человека в каждом шаге.

Что это. inv.velikie.org — база описей архивов России, Беларуси, Украины, Литвы с поиском по тексту и именные указатели,
которые набирают добровольцы (например, заёмщики Крестьянского поземельного банка, РГИА ф. 592). Поиск работает только
после входа: владелец дерева один раз входит в своём Chrome проекта (browser_cdp.mjs), дальше скрипт сам. f.velikie.org —
архивы снимков складчин (zip по 1–5 ГБ); из них можно взять только нужные дела, не скачивая весь архив.

Команды (rodo velikie …):
  login-check                    вошёл ли владелец; нет — открывает вход в окне Chrome, код 3
  search <слово> … [--force]     поиск (морфология + «*»): вкладки «Дела», «Записи», «Документы» → таблица
                                 в <found>/velikie/search/<слово>.tsv; уже есть — пропускает (--force — заново)
  filter <regex> [слово …]       строки сохранённых поисков, где есть regex (без слов — по всем)
  zip-list <url> [--grep re]     оглавление zip по сети (только конец файла): папки дел и число кадров
  zip-get <url> <часть пути> <папка>   скачать из zip только кадры, в пути которых есть эта часть
  ocr <папка> [--out файл.jsonl] распознать кадры на Mac (Apple Vision, без токенов; рукопись — грубо)
  grep <файл.jsonl> <regex>      найти слова в распознанном; номер дела — по карточкам «ФОНД / ОПИСЬ / ДЕЛО»

Правила сайта и вежливость: пауза ≥4 с между поисками; капча, 403/429 или «слишком много запросов» — стоп, код 3.
Пароль и cookie скрипт не видит: вход держит сам Chrome.
Выход: 0 — готово; 1 — ошибка; 2 — неверные параметры; 3 — не вошёл или стоп от сайта.
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402
from paths import FOUND  # noqa: E402

SEARCH_URL = ("https://inv.velikie.org/search/?searchText={q}&useMorphology=1&addAsterisks=1&highlightMatches=1"
              "&sortMode=0&archives=all&projects=all")
LOGIN_URL = "https://id.velikie.org/login/?returnToUrl=https%3A%2F%2Finv.velikie.org%2Fsearch%2F"
OUT = FOUND / "velikie" / "search"
PAUSE = 4
VISION_SWIFT = paths.SCRIPTS / "gaso_vision.swift"
VISION_BIN = paths.CACHE / "velikie_vision"


# ── Chrome проекта ──────────────────────────────────────────────────────────────────────────────────────────────────

def cdp(*args: str, timeout: int = 120) -> str:
    r = subprocess.run(["node", str(paths.SCRIPTS / "browser_cdp.mjs"), *args], capture_output=True, text=True,
                       timeout=timeout)
    if r.returncode == 3:
        raise SystemExit(f"✋ стоп от сайта или вход: {r.stdout.strip()} {r.stderr.strip()}"[:400]) from None
    if r.returncode:
        raise RuntimeError((r.stderr or r.stdout).strip()[:400])
    return r.stdout.strip()


def js(code: str) -> str:
    """Выполнить JS; длинный ответ browser_cdp кладёт в файл и печатает «→ путь» — читаем его."""
    out = cdp("eval", code)
    m = re.match(r"→ (\S+)", out)
    return Path(m.group(1)).read_text(encoding="utf-8") if m else out


def logged_in() -> bool:
    return js('!!document.querySelector("a[href^=\\"/logout/\\"]")') == "true"


def check_stop() -> None:
    t = js('document.body ? document.body.innerText.slice(0, 3000) : ""')
    if re.search(r"captcha|капч|не робот|слишком много запросов|Too Many Requests|403 Forbidden", t, re.I):
        raise SystemExit("✋ сайт просит капчу или ограничил запросы — стоп, позвать владельца дерева (код 3)")


def cmd_login_check(_a) -> int:
    cdp("start")
    cdp("nav", "https://inv.velikie.org/search/")
    if logged_in():
        print("вошёл")
        return 0
    cdp("nav", LOGIN_URL)
    print("не вошёл: страница входа открыта в окне Chrome проекта — войти и повторить")
    return 3


# ── Поиск ───────────────────────────────────────────────────────────────────────────────────────────────────────────

# Вкладки результатов: подписи «Дела (12)», «Записи (4)»… Для каждой — щёлкнуть и снять видимую таблицу с шапкой «Шифр».
READ_TABS_JS = r"""(async () => {
  const wait = ms => new Promise(r => setTimeout(r, ms));
  for (let i = 0; i < 40; i++) {           // дождаться, пока появятся счётчики вкладок
    if ([...document.querySelectorAll('*')].some(e => /^Дела \(\d+\)$/.test((e.innerText||'').trim()))) break;
    await wait(500);
  }
  // Все таблицы вкладок лежат на странице сразу; своя узнаётся по шапке. Остальное догружается при прокрутке.
  const HEAD = {'Дела': /Заголовок.*Листов/, 'Записи': /Объединенное/, 'Документы': /^ШифрНазваниеДатыЗаписей/};
  const out = {}; const seen = new Set();
  const tabs = [...document.querySelectorAll('li')].filter(e =>
      /^(Фонды|Дела|Документы|Записи) \(\d+\)$/.test((e.innerText||'').trim()));
  for (const tb of tabs) {
    const label = tb.innerText.trim(); const [, name, n] = label.match(/^(\S+) \((\d+)\)$/);
    if (seen.has(name)) continue; seen.add(name);
    out[name] = {count: +n, rows: []};
    if (+n === 0 || !HEAD[name]) continue;
    (tb.querySelector('a') || tb).click(); await wait(2500);
    const tbl = [...document.querySelectorAll('table')].find(t =>
        HEAD[name].test(((t.rows[0] && t.rows[0].innerText) || '').replace(/\s+/g, '')) ||
        HEAD[name].test(((t.rows[0] && t.rows[0].innerText) || '')));
    if (!tbl) continue;
    for (let last = -1, idle = 0; tbl.rows.length - 1 < +n && idle < 6; ) {
      window.scrollTo(0, document.body.scrollHeight); await wait(1500);
      if (tbl.rows.length === last) idle++; else { idle = 0; last = tbl.rows.length; }
    }
    for (const tr of [...tbl.rows].slice(1)) {
      const cells = [...tr.cells].map(c => c.innerText.replace(/\s+/g, ' ').trim());
      if (cells.some(Boolean)) out[name].rows.push(cells);
    }
  }
  return JSON.stringify(out);
})()"""


def search_one(word: str) -> dict:
    cdp("nav", SEARCH_URL.format(q=urllib.parse.quote(word)))
    check_stop()
    return json.loads(js(READ_TABS_JS) or "{}")


def cmd_search(a) -> int:
    cdp("start")
    cdp("nav", "https://inv.velikie.org/search/")
    if not logged_in():
        print("не вошёл — rodo velikie login-check")
        return 3
    OUT.mkdir(parents=True, exist_ok=True)
    for i, w in enumerate(a.words):
        f = OUT / f"{w}.tsv"
        if f.exists() and not a.force:
            print(f"{w}: уже есть ({paths.rel(f)})")
            continue
        if i:
            time.sleep(PAUSE)
        res = search_one(w)
        lines = [f"# {w}\t{time.strftime('%Y-%m-%d')}\t" +
                 " ".join(f"{k}={v['count']}" for k, v in res.items())]
        for tab, v in res.items():
            for cells in v["rows"]:
                lines.append("\t".join([tab, *cells]))
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
        got = {k: len(v["rows"]) for k, v in res.items() if v["count"]}
        # Счётчик «Записи» на сайте вдвое больше строк (проверено 16.11.2026 на 11 поисках) — это не потеря.
        short = {k: f"{len(v['rows'])}/{v['count']}" for k, v in res.items() if k != "Фонды"
                 and v["count"] > len(v["rows"]) and not (k == "Записи" and 2 * len(v["rows"]) == v["count"])}
        print(f"{w}: {got or 'пусто'}" + (f" — снято не всё (страницы): {short}" if short else ""))
    return 0


def cmd_filter(a) -> int:
    rx = re.compile(a.regex, re.I)
    files = [OUT / f"{w}.tsv" for w in a.words] if a.words else sorted(OUT.glob("*.tsv"))
    n = 0
    for f in files:
        if not f.exists():
            print(f"нет {f.name} — сначала search")
            continue
        for line in f.read_text(encoding="utf-8").splitlines()[1:]:
            if rx.search(line):
                print(f"[{f.stem}] {line}")
                n += 1
    print(f"— строк: {n}", file=sys.stderr)
    return 0


# ── zip по сети ─────────────────────────────────────────────────────────────────────────────────────────────────────

def _range(url: str, a: int, b: int) -> bytes:
    for t in range(4):
        try:
            req = urllib.request.Request(url, headers={"Range": f"bytes={a}-{b}", "User-Agent": "ftree-velikie"})
            return urllib.request.urlopen(req, timeout=120).read()
        except OSError:
            time.sleep(5 * (t + 1))
    raise RuntimeError(f"не скачалось: {url} {a}-{b}")


def zip_entries(url: str) -> list[tuple[str, int, int, int]]:
    """(имя, сжатый размер, смещение, метод) по центральному каталогу; имена cp866, если не помечены utf-8."""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "ftree-velikie"})
    size = int(urllib.request.urlopen(req, timeout=60).headers["Content-Length"])
    tail = _range(url, max(0, size - 65536), size - 1)
    i = tail.rfind(b"PK\x05\x06")
    n = struct.unpack("<H", tail[i + 10:i + 12])[0]
    cd_size, cd_off = struct.unpack("<II", tail[i + 12:i + 20])
    if cd_off == 0xFFFFFFFF or n == 0xFFFF:
        j = tail.rfind(b"PK\x06\x07")
        z64 = struct.unpack("<Q", tail[j + 8:j + 16])[0]
        z = _range(url, z64, z64 + 55)
        cd_size, cd_off = struct.unpack("<QQ", z[40:56])
    cd = _range(url, cd_off, cd_off + cd_size - 1)
    out, p = [], 0
    while cd[p:p + 4] == b"PK\x01\x02":
        flag, meth = struct.unpack("<HH", cd[p + 8:p + 12])
        csz, usz = struct.unpack("<II", cd[p + 20:p + 28])
        fl, el, cl = struct.unpack("<HHH", cd[p + 28:p + 34])
        off = struct.unpack("<I", cd[p + 42:p + 46])[0]
        raw = cd[p + 46:p + 46 + fl]
        name = raw.decode("utf-8" if flag & 0x800 else "cp866", "replace")
        ex, q = cd[p + 46 + fl:p + 46 + fl + el], 0
        while q + 4 <= len(ex):
            hid, hl = struct.unpack("<HH", ex[q:q + 4])
            if hid == 1:
                d, k, vals = ex[q + 4:q + 4 + hl], 0, []
                for v in (usz, csz, off):
                    if v == 0xFFFFFFFF:
                        vals.append(struct.unpack("<Q", d[k:k + 8])[0])
                        k += 8
                    else:
                        vals.append(v)
                usz, csz, off = vals
            q += 4 + hl
        if not name.endswith("/"):
            out.append((name, csz, off, meth))
        p += 46 + fl + el + cl
    return out


def cmd_zip_list(a) -> int:
    folders: dict[str, int] = {}
    for name, *_ in zip_entries(a.url):
        d = name.rsplit("/", 1)[0]
        folders[d] = folders.get(d, 0) + 1
    rx = re.compile(a.grep, re.I) if a.grep else None
    for d, k in folders.items():
        if not rx or rx.search(d):
            print(f"{k:5}  {d}")
    print(f"— папок {len(folders)}, кадров {sum(folders.values())}", file=sys.stderr)
    return 0


def cmd_zip_get(a) -> int:
    dest = Path(a.dir)
    dest.mkdir(parents=True, exist_ok=True)
    k = 0
    for name, csz, off, meth in zip_entries(a.url):
        if a.part not in name:
            continue
        rel = Path(*[re.sub(r"\s.*$", "", x) or x for x in name.split("/")[1:]])  # без корня и хвостов «(… 157)»
        f = dest / rel
        if f.exists():
            continue
        h = _range(a.url, off, off + 29)
        fl, el = struct.unpack("<HH", h[26:30])
        s = off + 30 + fl + el
        data = _range(a.url, s, s + csz - 1)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(zlib.decompress(data, -15) if meth == 8 else data)
        k += 1
    print(f"скачано кадров: {k} → {dest}")
    return 0


# ── Распознавание и поиск по кадрам ─────────────────────────────────────────────────────────────────────────────────

def vision_bin() -> Path:
    if not VISION_BIN.exists() or VISION_BIN.stat().st_mtime < VISION_SWIFT.stat().st_mtime:
        VISION_BIN.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["swiftc", "-O", str(VISION_SWIFT), "-o", str(VISION_BIN)], check=True)
    return VISION_BIN


def cmd_ocr(a) -> int:
    src = Path(a.dir)
    imgs = sorted(p for p in src.rglob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".jxl"))
    out = Path(a.out) if a.out else src / "vision.jsonl"
    done = set()
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(line)["image"])
            except (ValueError, KeyError):
                pass
    todo = [str(p) for p in imgs if str(p) not in done]
    print(f"кадров {len(imgs)}, распознать {len(todo)} → {out}")
    vb = str(vision_bin())
    with out.open("a", encoding="utf-8") as fo:
        for k in range(0, len(todo), 50):
            r = subprocess.run([vb, *todo[k:k + 50]], capture_output=True, text=True)
            fo.write(r.stdout)
            fo.flush()
            if k and k % 1000 == 0:
                print(f"  {k}/{len(todo)}", flush=True)
    return 0


def frames(jsonl: Path):
    """(кадр, номер дела по последней карточке «ДЕЛО №», текст) в порядке имён файлов."""
    rows = []
    for line in jsonl.read_text(encoding="utf-8").splitlines():
        try:
            p = json.loads(line)
        except ValueError:
            continue
        rows.append((p["image"], " ".join(x["text"] for x in p["lines"])))
    case = "?"
    for img, t in sorted(rows):
        if re.search(r"ЛАБОРАТОР|МИКРОФОТО", t) or ("ФОНД" in t and "ДЕЛО" in t):
            m = re.search(r"ДЕЛО\s*N?[º°o]?\s*([\d| ]{2,7})", t)
            case = re.sub(r"\D", "", m.group(1)) if m else "?"
            continue
        yield img, case, t


def cmd_grep(a) -> int:
    rx = re.compile(a.regex, re.I)
    n = 0
    for img, case, t in frames(Path(a.jsonl)):
        m = rx.search(t)
        if m:
            print(f"д. {case}\t{Path(img).parent.name}/{Path(img).name}\t…{t[max(0, m.start() - 100):m.end() + 100]}…")
            n += 1
    print(f"— кадров: {n}", file=sys.stderr)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login-check").set_defaults(fn=cmd_login_check)
    s = sub.add_parser("search")
    s.add_argument("words", nargs="+")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_search)
    s = sub.add_parser("filter")
    s.add_argument("regex")
    s.add_argument("words", nargs="*")
    s.set_defaults(fn=cmd_filter)
    s = sub.add_parser("zip-list")
    s.add_argument("url")
    s.add_argument("--grep")
    s.set_defaults(fn=cmd_zip_list)
    s = sub.add_parser("zip-get")
    s.add_argument("url")
    s.add_argument("part")
    s.add_argument("dir")
    s.set_defaults(fn=cmd_zip_get)
    s = sub.add_parser("ocr")
    s.add_argument("dir")
    s.add_argument("--out")
    s.set_defaults(fn=cmd_ocr)
    s = sub.add_parser("grep")
    s.add_argument("jsonl")
    s.add_argument("regex")
    s.set_defaults(fn=cmd_grep)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
