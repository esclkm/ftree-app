#!/usr/bin/env python3
"""Качальщик сканов ГАСО (portal.gaso-smolensk.ru): один поток, пауза, продолжение, манифест.

Качает ТОЛЬКО пока у Павла действует абонемент (иначе это обход оплаты) — поэтому
для настоящего запуска обязателен флаг --subscription-active.
Никаких cookie, паролей и токенов скрипт не знает и не хранит: картинки отдаются
по прямому адресу (так было 01.10.2026). Если сервер начнёт отдавать не картинку
или код 401/403/429 — скрипт останавливается и пишет, что делать.

Примеры (сухой прогон — сеть не трогаем):
  python3 gaso_download.py --kind l --opis 6 --delo 526 --first 160 --last 180 \
      --out $ARCHIVES_LOCAL/raw/gaso/ф48_оп6_д526 --label Ф48_оп6_д526_файл --dry-run
  python3 gaso_download.py --kind page --opis 6 --delo 597 --first 1 --last 240 \
      --out $ARCHIVES_LOCAL/raw/gaso/ф48_оп6_д597 --label Ф48_оп6_д597_файл --subscription-active --pause 1.5
Виды адреса (--kind), см. SKILL.md, «Как устроены адреса»:
  l      оп.6, дела 516-526:   GASO_48_<оп>_<дело>/Ф48_оп<оп>_д<дело>_л_ (<N>).JPG
  l867   оп.4, дело 867:       GASO_48_4_867_3/Ф48_оп4_867_л (<N>).JPG   (нужен --folder для других дел)
  page   оп.6, дела 581,596-601: GASO_48_<оп>_<дело>/Ф.48 оп.<оп> д.<дело>__Страница_<NNN>_Изображение_0001.jpg
  gen    консисторские (оп.3/4): --folder GASO_48_3_320_4 --prefix "1894 г. Ф.48 оп.3 д.320 ч.4"
  custom свой шаблон: --folder ... --name-template "...{n}..." (можно {n:03d}); суффикс _watermark.jpg добавится сам
Выход: 0 — готово; 2 — неверные параметры; 3 — стоп (401/403/429 или пришла не картинка); 4 — сеть/5xx после повторов.
"""
import argparse
import hashlib
import json
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = "https://portal.gaso-smolensk.ru/thumbnails/"
BASE = ROOT + "metrics_smolensky/"
UA = "Mozilla/5.0 (Macintosh) genealogy-personal-use"
# Исчерпанный абонемент: просмотрщик отдаёт HTML-заглушку ≈1,3 КБ (или 302 на подписку) вместо JPEG.
# Настоящий разворот — сотни килобайт; всё меньше этого порога — не скан (идея vdov, CC BY 4.0).
MIN_IMAGE_BYTES = 5000


def is_scan(body):
    """JPEG и не заглушка."""
    return body.startswith(b"\xff\xd8") and len(body) >= MIN_IMAGE_BYTES


def has_scan(path):
    """Лежит ли на диске настоящий скан (не заглушка)."""
    return path.exists() and path.stat().st_size >= MIN_IMAGE_BYTES


def have_scan(path):
    """Как has_scan, но заглушку от прежнего запуска удаляет — иначе она считалась бы скачанной страницей."""
    if path.exists() and not has_scan(path):
        path.unlink()
    return has_scan(path)


def build(args, n):
    o, d = args.opis, args.delo
    if args.kind == "l":
        folder = args.folder or f"GASO_48_{o}_{d}"
        name = f"Ф48_оп{o}_д{d}_л_ ({n})"
    elif args.kind == "l867":
        folder = args.folder or "GASO_48_4_867_3"
        name = f"Ф48_оп4_{d or 867}_л ({n})"
    elif args.kind == "page":
        folder = args.folder or f"GASO_48_{o}_{d}"
        name = f"Ф.48 оп.{o} д.{d}__Страница_{n:03d}_Изображение_0001"
    elif args.kind == "gen":
        if not (args.folder and args.prefix):
            sys.exit("для --kind gen нужны --folder и --prefix")
        folder = args.folder
        name = f"{args.prefix}__Страница_{n:03d}_Изображение_0001"
    else:  # custom
        if not (args.folder and args.name_template):
            sys.exit("для --kind custom нужны --folder и --name-template")
        folder = args.folder
        name = args.name_template.format(n=n - args.offset)
    return ROOT + args.root + "/" + urllib.parse.quote(folder) + "/" + urllib.parse.quote(name + ".JPG_watermark.jpg"
                                                                        if args.kind in ("l", "l867") else
                                                                        name + ".jpg_watermark.jpg"
                                                                        if args.kind in ("page", "gen") else
                                                                        name + "_watermark.jpg")


def load_manifest(path):
    done = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                done[r["n"]] = r
            except Exception:
                pass
    return done


def fetch(url, timeout):
    """Через curl, а не urllib: сертификат портала выдан центром, которого нет в списке Python (CERTIFICATE_VERIFY_FAILED),
    а curl берёт доверенные центры из системы Mac (09.10.2026). Проверку сертификата не отключаем."""
    import subprocess, tempfile, urllib.error
    with tempfile.NamedTemporaryFile(suffix=".part") as tmp:
        r = subprocess.run(["curl", "-s", "-A", UA, "--max-time", str(int(timeout)), "-o", tmp.name,
                            "-w", "%{http_code} %{content_type}", url], capture_output=True, text=True)
        code, _, ctype = r.stdout.partition(" ")
        code = int(code or 0)
        if code == 0:
            raise urllib.error.URLError(f"curl: код выхода {r.returncode}")
        if code >= 400:
            raise urllib.error.HTTPError(url, code, "", {}, None)
        return code, ctype, open(tmp.name, "rb").read()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kind", choices=["l", "l867", "page", "gen", "custom"], required=True)
    ap.add_argument("--opis", type=int, help="номер описи фонда 48 (3, 4, 6)")
    ap.add_argument("--delo", type=int, help="номер дела")
    ap.add_argument("--folder", help="папка на сервере, если не по умолчанию (GASO_48_4_867_3 ...)")
    ap.add_argument("--root", default="metrics_smolensky",
                    help="раздел на сервере: metrics_smolensky (метрики) или revizsky_smolensky (ревизские сказки)")
    ap.add_argument("--prefix", help="для gen: «1894 г. Ф.48 оп.3 д.320 ч.4»")
    ap.add_argument("--name-template", help="для custom: имя без _watermark.jpg, с {n}")
    ap.add_argument("--offset", type=int, default=0,
                    help="для custom: номер на сервере = наш номер − offset (вторая часть дела с нумерацией заново)")
    ap.add_argument("--first", type=int, default=1)
    ap.add_argument("--last", type=int, required=True)
    ap.add_argument("--out", required=True, help="папка вне проекта: $ARCHIVES_LOCAL/raw/gaso/ф<фонд>_оп<опись>_д<дело>")
    ap.add_argument("--label", help="начало имени файла (по умолчанию из --out); для gaso_index — Ф48_оп6_д<дело>_файл")
    ap.add_argument("--pause", type=float, default=1.5, help="секунд между запросами (по умолчанию 1.5)")
    ap.add_argument("--max-miss", type=int, default=8, help="сколько подряд 404 считать концом книги")
    ap.add_argument("--timeout", type=float, default=60)
    ap.add_argument("--retry-missing", action="store_true", help="заново пробовать номера, что раньше дали 404")
    ap.add_argument("--subscription-active", action="store_true",
                    help="Павел подтвердил: абонемент действует прямо сейчас. Без флага сеть не трогаем")
    ap.add_argument("--dry-run", action="store_true", help="только напечатать адреса и план")
    args = ap.parse_args()

    out = Path(args.out).expanduser()
    label = args.label or out.name
    manifest = out / "manifest.jsonl"
    done = load_manifest(manifest)

    if args.dry_run or not args.subscription_active:
        if not args.dry_run:
            print("Нет --subscription-active: делаю только сухой прогон. Абонемент действует? Спросите Павла.")
        shown = 0
        for n in range(args.first, args.last + 1):
            have = has_scan(out / f"{label}_{n:03d}.jpg") or (n in done and done[n].get("status") == 200)
            if shown < 3 or n == args.last:
                print(("есть  " if have else "скачать ") + build(args, n))
                shown += 1
        todo = sum(1 for n in range(args.first, args.last + 1)
                   if not has_scan(out / f"{label}_{n:03d}.jpg") and not (n in done and done[n].get("status") == 404 and not args.retry_missing))
        print(f"к скачиванию: {todo} из {args.last - args.first + 1}; пауза {args.pause} c ≈ {todo * (args.pause + 0.5) / 60:.0f} мин")
        return 0

    out.mkdir(parents=True, exist_ok=True)
    miss = 0
    got = 0
    with manifest.open("a", encoding="utf-8") as mf:
        for n in range(args.first, args.last + 1):
            f = out / f"{label}_{n:03d}.jpg"
            if have_scan(f):
                miss = 0
                continue
            if n in done and done[n].get("status") == 404 and not args.retry_missing:
                miss += 1
                if miss >= args.max_miss:
                    break
                continue
            url = build(args, n)
            for attempt in range(3):
                try:
                    status, ctype, body = fetch(url, args.timeout)
                    break
                except urllib.error.HTTPError as e:
                    status, ctype, body = e.code, "", b""
                    if e.code in (401, 403, 429):
                        print(f"СТОП: сервер ответил {e.code} на номер {n}. Не повторяйте. Скажите Павлу: "
                              "возможно, абонемент закончился или сервер просит притормозить. "
                              "Подождите минимум час, а лучше — до следующего абонемента.")
                        return 3
                    if e.code == 404:
                        break
                    time.sleep(5 * (attempt + 1))
                except Exception as e:  # таймаут, обрыв
                    status, ctype, body = 0, "", b""
                    time.sleep(5 * (attempt + 1))
            else:
                print(f"СТОП: сеть/сервер не отвечает на номер {n} (код {status}). Остановились; запустите снова позже — продолжит с этого места.")
                return 4
            now = time.strftime("%Y-%m-%dT%H:%M:%S")
            if status == 404:
                mf.write(json.dumps({"n": n, "url": url, "status": 404, "ts": now}, ensure_ascii=False) + "\n")
                mf.flush()
                miss += 1
                if miss >= args.max_miss:
                    print(f"{args.max_miss} номеров подряд — 404: похоже, конец книги на номере {n - args.max_miss}.")
                    break
            else:
                if status != 200 or not is_scan(body):
                    print(f"СТОП: на номер {n} пришла не картинка (код {status}, тип {ctype}, {len(body)} байт). "
                          "Вероятно, абонемент закончился или портал отдал страницу входа. Скажите Павлу.")
                    return 3
                tmp = f.with_suffix(".part")
                tmp.write_bytes(body)
                tmp.rename(f)
                miss = 0
                got += 1
                mf.write(json.dumps({"n": n, "url": url, "status": 200, "size": len(body),
                                     "sha256": hashlib.sha256(body).hexdigest(), "file": f.name, "ts": now},
                                    ensure_ascii=False) + "\n")
                mf.flush()
                if got % 25 == 0:
                    print(f"… скачано {got}, последний номер {n}")
            time.sleep(args.pause + random.uniform(0, 0.5))
    print(f"Готово: новых файлов {got}. Папка: {out}. Манифест: {manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
