#!/usr/bin/env python3
"""ГАСО: снять адреса всех разворотов дела, у которого картинки лежат под шифрами (ЗАГС ф. Р-3315, сборные книги).

Зачем. У таких дел имя файла на сервере — случайный шифр (`thumbnails/upload/13/7e/f0e4….jpg_watermark.jpg`), номер не
подставить. Адрес каждого разворота видно только в просмотрщике. Скрипт открывает дело (через опись), щёлкает первую
миниатюру, жмёт «вправо» до конца и после каждой смены картинки записывает адрес. Потом качает по списку `curl` —
картинки по прямому адресу абонемент не тратят. Просмотрщик закрывается в конце (about:blank).

    tools/py tools/scripts/gaso_record.py --opis-id 5865 --delo 172 --out <archives>/raw/gaso/фР3315_оп2_д172 --label Р3315_оп2_д172
    tools/py tools/scripts/gaso_record.py … --download-only        # адреса уже сняты — только докачать

Нужно: вход владельца в Chrome проекта и действующий абонемент (остаток печатается до и после). 600 разворотов ≈ 5 мин,
абонемента ≈ 1 мин (15.10.2026). Опись ф. Р-3315 оп. 2 — `opisView.jsf?id=5865`.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gaso_unlock as g  # noqa: E402

print = g.print  # noqa: A001


def long_js(body: str, timeout: int) -> str:
    out = g.js(body, timeout=timeout)
    if out.startswith("→ "):  # browser_cdp кладёт длинный ответ в файл
        out = Path(out[2:].split(" (")[0].strip()).read_text()  # «→ /путь.txt (22175 знаков)»
    return out


def record(partial: Path | None = None) -> list[str]:
    # всё ожидание — из Python: таймеры страницы во вкладке не на экране замирают (17.11.2026, д. 427, 430)
    PAG = '(document.getElementById("form:dataPreview_paginator_bottom")||{querySelector:()=>null}).querySelector(".ui-paginator-current")?.textContent||"-"'
    BG0 = '(getComputedStyle(document.querySelector(".scanImage")||document.body).backgroundImage||"-")'
    # кнопку «Просмотр сканов» страница рисует с задержкой, а щелчок через setTimeout в фоновой вкладке откладывается —
    # если остались на странице дела, ждём кнопку из Python и жмём напрямую
    BTN = '[...document.querySelectorAll("a,button")].filter(x=>/Просмотр сканов/.test(x.textContent)).length+""'
    for _ in range(60):
        if "sourceInfo" not in g.cdp("eval", "location.href"):
            break
        if g.cdp("eval", BTN) != "0":
            try:
                g.cdp("eval", '(()=>{[...document.querySelectorAll("a,button")].find(x=>/Просмотр сканов/.test(x.textContent)).click(); return "ok"})()')
            except SystemExit:
                pass  # страница ушла на просмотрщик посреди вызова
            time.sleep(5)
            continue
        time.sleep(1)
    else:
        sys.exit("на странице дела нет кнопки «Просмотр сканов» за минуту — дело не оцифровано?")
    got = ""
    for _ in range(120):
        got = g.cdp("eval", PAG)
        if "из" in got:
            break
        time.sleep(1)
    else:
        try:
            g.js('setTimeout(()=>{location.href="about:blank"},50); return "";')
        except SystemExit:
            pass
        sys.exit("нет просмотрщика (2 минуты): " + g.cdp("eval", "location.href"))
    b0 = g.cdp("eval", BG0)
    g.cdp("eval", '(()=>{const a=[...document.querySelectorAll("a.ui-commandlink")].find(a=>a.id.startsWith("form:dataPreview:0:")); if(a) a.click(); return a?"ok":"нет"})()')
    for _ in range(240):
        time.sleep(0.5)
        bg = g.cdp("eval", BG0)
        if bg != b0 and "thumbnails" in bg:
            break
    total = int(got.split("из")[-1].split()[0])
    print(f"разворотов в деле: {total}")
    # по 40 шагов за вызов: просмотрщик остаётся открытым между вызовами, адреса сразу в файл — долгое дело не теряется
    have = partial.read_text().split() if partial and partial.exists() else []
    if len(have) > 1:
        # продолжить: встать на последний снятый разворот (миниатюра № len-1) и листать дальше
        idx = len(have) - 1
        print(f"продолжаю с {len(have)}")
        for _ in range(200):
            if g.cdp("eval", f'[...document.querySelectorAll("a.ui-commandlink")].some(a=>a.id.startsWith("form:dataPreview:{idx}:"))?"есть":"нет"') == "есть":
                break
            cur = g.cdp("eval", PAG)
            g.cdp("eval", '(()=>{const p=document.getElementById("form:dataPreview_paginator_bottom"); p.querySelector(".ui-paginator-next").click(); return "ok"})()')
            for _ in range(40):
                time.sleep(0.5)
                if g.cdp("eval", PAG) != cur:
                    break
            time.sleep(1)
        b1 = g.cdp("eval", BG0)
        g.cdp("eval", f'(()=>{{const a=[...document.querySelectorAll("a.ui-commandlink")].find(a=>a.id.startsWith("form:dataPreview:{idx}:")); if(a) a.click(); return a?"ok":"нет"}})()')
        for _ in range(240):
            time.sleep(0.5)
            if g.cdp("eval", BG0) != b1:
                break
        urls = have
    else:
        urls = [g.js("""return getComputedStyle(document.querySelector(".scanImage")).backgroundImage
      .replace(/^url\\("?/,"").replace(/"?\\)$/,"");""")]
        if partial:
            partial.write_text(urls[0] + "\n")
    # Ждём смену картинки из Python, а не таймерами страницы: во вкладке не на экране Chrome через 5 минут
    # притормаживает setTimeout до раза в минуту (17.11.2026: д. 399 не сдвинулась за 6 минут).
    BG = 'getComputedStyle(document.querySelector(".scanImage")).backgroundImage.replace(/^url\\("?/,"").replace(/"?\\)$/,"")'
    try:
        while len(urls) < total:
            prev = urls[-1]
            g.cdp("eval", '(()=>{document.querySelector(".btn-right").click(); return "ok"})()')
            for k in range(360):  # до 3 минут: разворот, который никто не открывал, сервер готовит долго
                time.sleep(0.5)
                cur = g.cdp("eval", BG)
                if cur and cur != prev and "thumbnails" in cur:
                    break
                if k in (120, 240):  # щелчок мог потеряться — нажать ещё раз
                    g.cdp("eval", '(()=>{document.querySelector(".btn-right").click(); return "ok"})()')
            else:
                urls.append("СТОП")
                print(f"  стоп на {len(urls)}: картинка не сменилась за 2 минуты")
                break
            urls.append(cur)
            if partial:
                with partial.open("a") as f:
                    f.write(cur + "\n")
            if len(urls) % 40 == 0:
                print(f"  {len(urls)}/{total}")
    finally:
        try:  # страница уходит на about:blank посреди вызова — пустой ответ здесь не ошибка
            g.js('setTimeout(()=>{location.href="about:blank"},50); return "";')
        except SystemExit:
            pass
    return urls


def download(out: Path, label: str, pause: float) -> tuple[int, int]:
    urls = (out / "urls.txt").read_text().split()
    ok = bad = 0
    for i, u in enumerate(urls, 1):
        f = out / f"{label}_файл_{i:03d}.jpg"
        if f.exists() and f.stat().st_size > 5000:
            ok += 1
            continue
        part = f.with_suffix(".part")
        code = subprocess.run(["curl", "-s", "--max-time", "90", "-o", str(part), "-w", "%{http_code}", u],
                              capture_output=True, text=True).stdout
        if code == "200" and part.exists() and part.stat().st_size > 5000 and part.read_bytes()[:2] == b"\xff\xd8":
            part.rename(f)
            ok += 1
        else:
            part.unlink(missing_ok=True)
            bad += 1
            if code in ("302", "401", "403", "429"):
                sys.exit(f"СТОП: {code} на {i} — абонемент? вход?")
        time.sleep(pause)
    return ok, bad


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--opis-id", type=int, required=True)
    p.add_argument("--delo", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--label", required=True)
    p.add_argument("--pause", type=float, default=1.0)
    p.add_argument("--download-only", action="store_true")
    p.add_argument("--record-only", action="store_true")
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    if not a.download_only:
        print("абонемент до:", g.remaining())
        print("дело:", g.open_delo(a.opis_id, a.delo))
        urls = record(a.out / "urls.partial.txt")
        (a.out / "urls.txt").write_text("\n".join(u for u in urls if u != "СТОП") + "\n")
        print(f"адресов: {len(urls)}" + (" (оборвалось)" if "СТОП" in urls else ""))
        print("абонемент после:", g.remaining())
        if "СТОП" in urls:
            return 1
    if not a.record_only:
        ok, bad = download(a.out, a.label, a.pause)
        print(f"скачано {ok}, не скачалось {bad}")
        return 0 if not bad else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
