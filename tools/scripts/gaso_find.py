#!/usr/bin/env python3
"""Локальный поиск кандидатов в метриках ГАСО без сплошного чтения книги.

Движок для gaso_flow.py. Запуск через gaso_flow.py: там лимиты, журнал и
возобновление. Здесь только просмотр выбранных сканов без вызова модели:
    python3 tools/scripts/gaso_find.py --book 597 --pages 185-189

Для нового макета книги укажите --crop x,y,width,height (пиксели оригинала).
Нужен локальный `ollama serve` и установленная qwen3-vl:8b-instruct.
Сканы — вне проекта, только на этом Mac: paths.GASO_RAW ($ARCHIVES_LOCAL/raw/gaso/).
Проверка на двух известных страницах с Сергеем обязательна; даже после неё
ответ модели «нет» НЕ доказывает отсутствие записи. Имена родителей, деревню
и дату кандидата всегда сверяйте с оригинальным разворотом.
"""

import argparse
import base64
import contextlib
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import archives
import paths  # noqa: E402
from paths import ARCHIVES_TEXT, GASO_RAW, ROOT, NoRaw, archive_ref, need_raw

SCANS = GASO_RAW
CACHE = paths.CACHE / "gaso_find"
RESPONSES = ARCHIVES_TEXT / "gaso" / "_jobs" / "model_responses"   # ответы модели (имена) — только на этом Mac
MODEL = "qwen3-vl:8b-instruct"
PROMPT = (
    "Это узкая колонка ИМЕН РОДИВШИХСЯ (рукописные имена слева от текста "
    "родителей) в метрической книге. Перепиши ВСЕ отдельные имена сверху "
    "вниз. В конце напиши: СЕРГЕЙ: ДА / НЕТ / НЕ УВЕРЕН. "
    "Не читай имена родителей."
)
# x, y, width, height: только колонка имён, без имён родителей.
CROPS = {521: (310, 350, 260, 1120), 597: (225, 360, 290, 1120)}
CONTROL = (246, 247)  # д. 521: на обеих страницах Сергей есть, но не наш.
MAX_PAGES = 20


def pages_arg(value: str) -> list[int]:
    match = re.fullmatch(r"(\d+)(?:-(\d+))?", value)
    if not match:
        raise argparse.ArgumentTypeError("укажите номер или диапазон: 185-189")
    first, last = int(match[1]), int(match[2] or match[1])
    if first < 1 or last < first or last - first + 1 > MAX_PAGES:
        raise argparse.ArgumentTypeError(f"диапазон: от 1 до {MAX_PAGES} страниц")
    return list(range(first, last + 1))


def crop_arg(value: str) -> tuple[int, int, int, int]:
    try:
        coords = tuple(int(part) for part in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("формат кропа: x,y,width,height") from exc
    if len(coords) != 4 or min(coords[:2]) < 0 or min(coords[2:]) < 1:
        raise argparse.ArgumentTypeError("формат кропа: x,y,width,height; размеры положительные")
    return coords


def scans() -> Path:
    """Папка со сканами ГАСО; нет её — NoRaw с тем, где лежит и как вернуть."""
    return need_raw(SCANS)


def scan_path(book: int, page: int) -> Path:
    try:
        root = scans()
    except NoRaw as exc:  # копии нет — сказать, где оригинал (каталог 3_research/archives/catalog/gaso/)
        url = archives.gaso_url(f"ф48_оп6_д{book}", page)
        raise NoRaw(f"{exc}\n  этот разворот на сервере ГАСО: {url or '? (дела нет в каталоге)'}") from None
    directory = root / f"ф48_оп6_д{book}"
    matches = list(directory.glob(f"*_{page:03}.jpg"))
    if len(matches) != 1:
        raise FileNotFoundError(f"д. {book}, файл {page}: найдено {len(matches)} сканов в {directory}")
    return matches[0]


def has_sergei(response: str) -> bool | None:
    before_verdict = re.split(r"СЕРГЕЙ\s*:", response, maxsplit=1, flags=re.I)[0]
    if re.search(r"(?im)^\s*Серг(?:ей|ий|iй)\b", before_verdict):
        return True
    match = re.search(r"СЕРГЕЙ\s*:\s*(НЕ\s+УВЕРЕН|ДА|НЕТ)", response.upper())
    if not match or "УВЕРЕН" in match[1]:
        return None
    return match[1] == "ДА"


def cache_path(scan: Path, crop: tuple[int, int, int, int], prompt: str = PROMPT) -> Path:
    source_hash = hashlib.sha256(scan.read_bytes()).hexdigest()
    key = hashlib.sha256(
        json.dumps([source_hash, crop, MODEL, prompt], ensure_ascii=False).encode()
    ).hexdigest()
    return RESPONSES / f"{key}.json"


def check_memory_pressure() -> None:
    if sys.platform != "darwin":
        return
    result = subprocess.run(["memory_pressure", "-Q"], check=True, capture_output=True, text=True)
    match = re.search(r"System-wide memory free percentage:\s*(\d+)%", result.stdout)
    if match is None:
        raise RuntimeError("Не удалось определить свободную память macOS; модель не загружена")
    if int(match[1]) < 25:
        raise RuntimeError(f"Свободной памяти {match[1]}% (<25%); локальная модель не загружена")


@contextlib.contextmanager
def model_lock():
    CACHE.mkdir(parents=True, exist_ok=True)
    with (CACHE / "model.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def screen(scan: Path, crop: tuple[int, int, int, int], prompt: str = PROMPT) -> str:
    with model_lock():
        saved = cache_path(scan, crop, prompt)
        if saved.exists():
            return json.loads(saved.read_text(encoding="utf-8"))["response"]
        return _read_uncached(scan, crop, saved, prompt)


def _read_uncached(scan: Path, crop: tuple[int, int, int, int], saved: Path, prompt: str) -> str:
    x, y, width, height = crop
    with tempfile.TemporaryDirectory(prefix="gaso-find-") as directory:
        image = Path(directory) / "names.jpg"
        subprocess.run(
            ["sips", "-c", str(height), str(width), "--cropOffset", str(y), str(x),
             str(scan), "--out", str(image)],
            check=True, stdout=subprocess.DEVNULL,
        )
        payload = {
            "model": MODEL, "prompt": prompt,
            "images": [base64.b64encode(image.read_bytes()).decode("ascii")],
            "stream": False, "keep_alive": "2m",
            "options": {"temperature": 0, "num_predict": 400, "num_ctx": 4096},
        }
        request = urllib.request.Request(
            "http://127.0.0.1:11434/api/generate",
            json.dumps(payload).encode(),
            {"Content-Type": "application/json"},
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=240) as reply:
                result = json.load(reply)
        except urllib.error.URLError as exc:
            raise RuntimeError("Локальная Ollama недоступна на 127.0.0.1:11434; запустите `ollama serve`") from exc
    response = result.get("response", "")
    if not response or result.get("done_reason") != "stop":
        raise RuntimeError(f"{scan}: локальная модель не закончила ответ: {result.get('done_reason')}")
    RESPONSES.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=RESPONSES, delete=False) as temp:
        json.dump(
            {"scan": archive_ref(scan), "sha256": hashlib.sha256(scan.read_bytes()).hexdigest(),
             "crop": crop, "model": MODEL, "prompt": prompt,
             "seconds": round(time.monotonic() - started, 2), "response": response},
            temp, ensure_ascii=False, indent=2,
        )
        temporary = temp.name
    os.replace(temporary, saved)
    return response


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book", type=int, required=True, help="номер дела описи 6")
    parser.add_argument("--pages", type=pages_arg, required=True, help="номера файлов: 185-189")
    parser.add_argument("--crop", type=crop_arg, help="колонка имён: x,y,width,height")
    args = parser.parse_args()
    crop = args.crop or CROPS.get(args.book)
    if crop is None:
        parser.error(f"для д. {args.book} нужен --crop x,y,width,height")
    try:
        found = [scan_path(args.book, number) for number in args.pages]
    except NoRaw as exc:
        sys.exit(str(exc))
    print(f"Дело {args.book}: {len(found)} файлов; модель {MODEL}; кроп {crop}; облако: нет")
    print("Файлы:", ", ".join(str(number) for number in args.pages))
    print("Это план. Для запуска используйте gaso_flow.py (лимиты и сохранение состояния).")


if __name__ == "__main__":
    main()
