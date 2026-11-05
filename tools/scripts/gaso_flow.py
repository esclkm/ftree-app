#!/usr/bin/env python3
"""Оркестратор локального поиска в уже скачанных метриках ГАСО.

Карточка задачи и журнал вызовов сохраняются между сессиями; изображения в
контекст Claude не передаются. Никаких облачных вызовов и правок дерева.

    python3 tools/scripts/gaso_flow.py init ivan-verbichi --book 597 --pages 185-189 \
        --objective "Иван, отец Прокоп, Вербичи, около июля 1894" \
        --range-evidence "Вербичи, отдел рождений 1894; проверить по оригиналу"
    python3 tools/scripts/gaso_flow.py plan ivan-verbichi
    python3 tools/scripts/gaso_flow.py run ivan-verbichi --count 5
    python3 tools/scripts/gaso_flow.py inspect ivan-verbichi --page 185
    python3 tools/scripts/gaso_flow.py review ivan-verbichi --page 185 \
        --decision not-match --evidence "проверено на оригинале: другой отец"

Сканы — вне проекта, только на этом Mac (paths.GASO_RAW); в карточке задачи путь — «archives:raw/gaso/…».
Перед run запустите локальную `ollama serve`. Страница без обнаруженного имени
остаётся непроверенной: отрицание VLM не доказывает отсутствия записи.
"""

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

import gaso_find as finder
from paths import ARCHIVES_TEXT, ROOT, TREE, NoRaw, archive_path, archive_ref, need_raw

JOBS = ARCHIVES_TEXT / "gaso" / "_jobs"   # задачи и журнал вызовов; в ответах модели — чужие имена, поэтому не в git
LEDGER = JOBS / "calls.jsonl"
JOB_PAGE_CAP = 50
RUN_PAGE_CAP = 20


@contextlib.contextmanager
def flow_lock():
    finder.CACHE.mkdir(parents=True, exist_ok=True)
    with (finder.CACHE / "flow.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def job_path(job_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", job_id):
        raise ValueError("ID задачи: латинские строчные буквы, цифры и дефис (до 64 символов)")
    return JOBS / f"{job_id}.json"


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())
        temporary = file.name
    os.replace(temporary, path)


def load(job_id: str) -> dict:
    path = job_path(job_id)
    if not path.exists():
        raise FileNotFoundError(f"Нет задачи {job_id}; сначала выполните init")
    job = json.loads(path.read_text(encoding="utf-8"))
    if job.get("version") != 1:
        raise ValueError(f"Неизвестная версия карточки: {path}")
    return job


def day() -> str:
    return dt.datetime.now().astimezone().date().isoformat()


def used_today() -> int:
    if not LEDGER.exists():
        return 0
    return sum(
        1 for line in LEDGER.read_text(encoding="utf-8").splitlines()
        if (row := json.loads(line))["day"] == day() and row["kind"] == "model_attempt"
    )


def model_call(job_id: str, scan: Path, crop: tuple[int, int, int, int], prompt: str = finder.PROMPT) -> str:
    cached = finder.cache_path(scan, crop, prompt).exists()
    if not cached:
        finder.check_memory_pressure()
        JOBS.mkdir(parents=True, exist_ok=True)
        with LEDGER.open("a", encoding="utf-8") as file:
            file.write(json.dumps(
                {"day": day(), "kind": "model_attempt", "job": job_id,
                 "scan": archive_ref(scan), "model": finder.MODEL, "usd": 0},
                ensure_ascii=False,
            ) + "\n")
            file.flush()
            os.fsync(file.fileno())
    try:
        return finder.screen(scan, crop, prompt)
    except Exception as exc:
        JOBS.mkdir(parents=True, exist_ok=True)
        with LEDGER.open("a", encoding="utf-8") as file:
            file.write(json.dumps(
                {"day": day(), "kind": "model_error", "job": job_id,
                 "scan": archive_ref(scan), "model": finder.MODEL,
                 "cached": cached, "error": str(exc), "usd": 0},
                ensure_ascii=False,
            ) + "\n")
            file.flush()
            os.fsync(file.fileno())
        raise


def create(args: argparse.Namespace) -> None:
    if len(args.pages) > JOB_PAGE_CAP:
        raise ValueError(f"Больше {JOB_PAGE_CAP} страниц в задаче запрещено: сначала сузьте диапазон")
    crop = args.crop or finder.CROPS.get(args.book)
    if crop is None:
        raise ValueError(f"Для д. {args.book} сначала проверьте расположение имён и укажите --crop")
    for page in args.pages:
        finder.scan_path(args.book, page)
    path = job_path(args.job)
    if path.exists():
        raise FileExistsError(f"{path} уже существует: продолжайте задачу, не перезаписывайте")
    save(path, {
        "version": 1, "id": args.job, "objective": args.objective,
        "range_evidence": args.range_evidence, "book": args.book,
        "crop": list(crop), "model": finder.MODEL, "created": day(),
        "pages": {str(page): {"state": "queued"} for page in args.pages},
    })
    print(f"Создана задача {path}; {len(args.pages)} страниц. Модель не запускалась.")


def plan(job: dict) -> None:
    states = Counter(item["state"] for item in job["pages"].values())
    remaining = [p for p, item in job["pages"].items() if item["state"] == "queued"]
    print(f"{job['id']}: {job['objective']}")
    print(f"Д. {job['book']}; диапазон: {job['range_evidence']}; кроп: {job['crop']}")
    if job.get("blocked_reason"):
        print(f"ОСТАНОВЛЕНО: {job['blocked_reason']}")
    print(f"Статусы: {dict(states)}; очередные файлы: {', '.join(remaining[:RUN_PAGE_CAP]) or 'нет'}")
    print(f"Партия: до {min(RUN_PAGE_CAP, len(remaining))} страниц за запуск; "
          f"{used_today()} локальных вызовов сегодня; дневного лимита нет; облачные: 0")
    print("Сначала inspect/review кандидатов; отрицания VLM не исключают страницы.")


def run(job: dict, count: int) -> None:
    if job.get("blocked_reason"):
        raise RuntimeError(f"Задача остановлена: {job['blocked_reason']}")
    if not 1 <= count <= RUN_PAGE_CAP:
        raise ValueError(f"За один запуск: 1–{RUN_PAGE_CAP} страниц")
    if job["model"] != finder.MODEL:
        raise RuntimeError("Модель в карточке не совпадает с текущей: нужен новый контроль и новая задача")
    queued = [p for p, item in job["pages"].items() if item["state"] == "queued"][:count]
    plan(job)
    if not queued:
        return
    controls = [(finder.scan_path(521, number), finder.CROPS[521]) for number in finder.CONTROL]
    targets = [(page, finder.scan_path(job["book"], int(page))) for page in queued]
    for scan, crop in controls:
        answer = model_call(job["id"], scan, crop)
        if finder.has_sergei(answer) is not True:
            raise RuntimeError(f"Контроль провален: {scan.name}; сначала исправьте макет/модель")
    print("Контроль 2/2. Результаты модели — кандидаты, не транскрипция источника.")
    for page, scan in targets:
        started = time.monotonic()
        response = model_call(job["id"], scan, tuple(job["crop"]))
        verdict = finder.has_sergei(response)
        status = "candidate" if verdict is True else "uncertain" if verdict is None else "screened_unverified"
        cache = finder.cache_path(scan, tuple(job["crop"]))
        job["pages"][page] = {
            "state": status, "scan": archive_ref(scan),
            "sha256": json.loads(cache.read_text(encoding="utf-8"))["sha256"],
            "cache_key": cache.stem, "processed": day(), "response": response,
        }
        save(job_path(job["id"]), job)
        print(f"Файл {page}: {status}; {round(time.monotonic()-started, 1)} с; "
              f"откройте оригинал перед review", flush=True)


def inspect(job: dict, page: int) -> None:
    item = job["pages"].get(str(page))
    if item is None or item["state"] == "queued":
        raise ValueError(f"Файл {page} ещё не обработан в этой задаче")
    verify_scan(item)
    if "response" not in item:
        cache = finder.RESPONSES / f"{item['cache_key']}.json"
        if not cache.exists():
            raise FileNotFoundError(f"Нет ответа в карточке или кэше: {cache}; оригинал: {item['scan']}")
        item["response"] = json.loads(cache.read_text(encoding="utf-8"))["response"]
        save(job_path(job["id"]), job)
    print(f"{item['scan']}\nСтатус: {item['state']}; sha256: {item['sha256']}")
    print("Ответ локальной модели (НЕ источник):\n" + item["response"])
    print("Проверьте исходный JPG; для подтверждения нужны отец, место и дата.")


def reclassify(job: dict, page: int) -> None:
    item = job["pages"].get(str(page))
    if item is None or item["state"] not in {"candidate", "uncertain", "screened_unverified"}:
        raise ValueError(f"Файл {page} нельзя переклассифицировать без сохранённого ответа")
    verify_scan(item)
    if "response" not in item:
        inspect(job, page)
    verdict = finder.has_sergei(item["response"])
    state = "candidate" if verdict is True else "uncertain" if verdict is None else "screened_unverified"
    if state != item["state"]:
        item["previous_state"] = item["state"]
        item["state"] = state
        save(job_path(job["id"]), job)
    print(f"Файл {page}: {state}; исходный ответ сохранён, факт не подтверждён")


def review(job: dict, args: argparse.Namespace) -> None:
    key = str(args.page)
    item = job["pages"].get(key)
    if item is None or item["state"] not in {"candidate", "uncertain", "screened_unverified"}:
        raise ValueError(f"Файл {key} не ожидает проверки человеком")
    verify_scan(item)
    if args.decision == "confirmed" and not args.source:
        raise ValueError("Для подтверждения укажите --source: шифр источника/лист")
    if args.decision == "not-match" and not args.evidence:
        raise ValueError("Для отклонения укажите --evidence: что проверено на оригинале")
    item["state"] = args.decision
    item["review"] = {"evidence": args.evidence, "source": args.source, "date": day()}
    save(job_path(job["id"]), job)
    print(f"Файл {key}: {args.decision}. Записи в дереве нет.")


def verify_scan(item: dict) -> None:
    scan = archive_path(item["scan"])
    if not scan.exists():
        need_raw(finder.SCANS)  # нет всей папки сырья — объясняет, где лежит и как вернуть
        raise FileNotFoundError(f"Нет скана {scan}; в задаче: {item['scan']}")
    if hashlib.sha256(scan.read_bytes()).hexdigest() != item["sha256"]:
        raise RuntimeError(f"Скан изменился после чтения: {scan}; требуется повторная проверка")


def handoff(job: dict) -> None:
    for page, item in job["pages"].items():
        if item["state"] == "confirmed":
            print(f"{page}: {item['scan']}; {item['review']['source']}; "
                  f"{item['review']['evidence']}")
    print("Вносить в карточку/биографию только после проверки оригинала; автоматически дерево не меняется.")


def curated(job: dict, args: argparse.Namespace) -> None:
    item = job["pages"].get(str(args.page))
    if item is None or item["state"] != "confirmed":
        raise ValueError("В дерево можно отмечать только подтверждённую человеком запись")
    card = (TREE / "people" / f"{args.person}.md").resolve()
    if card.parent != (TREE / "people").resolve() or not card.is_file():
        raise ValueError("Нужна существующая карточка из tree/people/")
    if item["review"]["source"] not in card.read_text(encoding="utf-8"):
        raise ValueError(f"В карточке нет шифра источника {item['review']['source']}; сначала внесите факт")
    item["state"] = "curated"
    item["card"] = str(card.relative_to(ROOT.resolve()))
    save(job_path(job["id"]), job)
    print(f"Внесено: {item['card']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "plan", "run", "inspect", "reclassify", "review", "handoff", "curated"):
        cmd = commands.add_parser(name)
        cmd.add_argument("job", help="ID задачи, например sergei-khokhlovo")
        if name == "init":
            cmd.add_argument("--book", type=int, required=True)
            cmd.add_argument("--pages", type=lambda v: page_range(v), required=True)
            cmd.add_argument("--crop", type=finder.crop_arg)
            cmd.add_argument("--objective", required=True)
            cmd.add_argument("--range-evidence", required=True)
        if name == "run":
            cmd.add_argument("--count", type=int, default=5)
        if name in ("inspect", "reclassify", "review", "curated"):
            cmd.add_argument("--page", type=int, required=True)
        if name == "review":
            cmd.add_argument("--decision", choices=("confirmed", "not-match"), required=True)
            cmd.add_argument("--evidence", required=True, help="что прочитано на оригинале")
            cmd.add_argument("--source", help="архив/фонд/опись/дело/лист (для confirmed)")
        if name == "curated":
            cmd.add_argument("--person", required=True, help="точное имя карточки в tree/people/")
    args = parser.parse_args()
    try:
        dispatch(args)
    except NoRaw as exc:
        sys.exit(str(exc))


def dispatch(args: argparse.Namespace) -> None:
    with flow_lock():
        if args.command == "init":
            create(args)
            return
        job = load(args.job)
        if args.command == "plan":
            plan(job)
        elif args.command == "run":
            run(job, args.count)
        elif args.command == "inspect":
            inspect(job, args.page)
        elif args.command == "reclassify":
            reclassify(job, args.page)
        elif args.command == "review":
            review(job, args)
        elif args.command == "handoff":
            handoff(job)
        else:
            curated(job, args)


def page_range(value: str) -> list[int]:
    match = re.fullmatch(r"(\d+)(?:-(\d+))?", value)
    if not match:
        raise argparse.ArgumentTypeError("укажите диапазон файлов: 185-189")
    start, end = int(match[1]), int(match[2] or match[1])
    if start < 1 or end < start or end - start + 1 > JOB_PAGE_CAP:
        raise argparse.ArgumentTypeError(f"от 1 до {JOB_PAGE_CAP} файлов на задачу")
    return list(range(start, end + 1))


if __name__ == "__main__":
    main()
