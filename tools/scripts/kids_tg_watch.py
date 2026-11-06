"""Следить за папкой детской книги (навык kids-story) и каждую новую картинку сразу слать владельцу в Telegram
«Избранное» — без модели и токенов. Вход в Telegram — сессия tg_group.py (настраивается один раз, см. его справку).

Запуск (держать в фоне: nohup … &, чтобы не зависеть от вкладки терминала):
    tools/py tools/scripts/kids_tg_watch.py <папка книги> [--from-now]
Смотрит pages/ (сцены, портреты, развороты, варианты) и train/ (отобранные для обучения фото — только если
SEND_TRAIN=1). Уже отправленные файлы помнит в pages/.tg_sent (имя + время изменения), повторно не шлёт.
Перерисованная картинка (тот же файл, новое время) уходит снова.
"""
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tg_group  # noqa: E402  вход в Telegram владельца (сессия вне git)

HERE = Path(next(a for a in sys.argv[1:] if not a.startswith("--"))).resolve()
WATCH = [HERE / "pages"] + ([HERE / "train"] if os.environ.get("SEND_TRAIN") else [])
SENT = HERE / "pages" / ".tg_sent"
EXT = {".png", ".jpg", ".jpeg"}
SKIP = ("/v/", "/tmp")  # старые варианты листа героини не шлём


def load_sent() -> set[str]:
    return set(SENT.read_text().splitlines()) if SENT.exists() else set()


def key(p: Path) -> str:
    return f"{p.relative_to(HERE)}|{int(p.stat().st_mtime)}"


def fresh(sent: set[str]) -> list[Path]:
    files = []
    for root in WATCH:
        if root.exists():
            files += [p for p in root.rglob("*") if p.suffix.lower() in EXT and not any(s in str(p) for s in SKIP)]
    # ждём, пока файл допишется: старше 5 секунд
    return sorted((p for p in files if key(p) not in sent and time.time() - p.stat().st_mtime > 5),
                  key=lambda p: p.stat().st_mtime)


async def main() -> None:
    c = tg_group.client()
    await c.connect()
    if not await c.is_user_authorized():
        raise SystemExit("сессия Telegram не авторизована")
    sent = load_sent()
    if "--from-now" in sys.argv:  # всё, что уже лежит, считать отправленным
        for p in fresh(set()):
            sent.add(key(p))
        SENT.write_text("\n".join(sorted(sent)))
        print(f"Старые картинки пропущены: {len(sent)}")
    print("Слежу за", ", ".join(str(w.relative_to(HERE)) for w in WATCH), "— Ctrl-C чтобы остановить")
    while True:
        for p in fresh(sent):
            rel = p.relative_to(HERE)
            try:
                await c.send_file("me", str(p), caption=f"Книга: {rel}", force_document=p.stat().st_size > 9_000_000)
                print(time.strftime("%H:%M:%S"), "→ Избранное:", rel)
            except Exception as e:  # сеть, лимит — попробуем в следующий круг
                print(time.strftime("%H:%M:%S"), "не ушло:", rel, e)
                continue
            sent.add(key(p))
            SENT.write_text("\n".join(sorted(sent)))
        await asyncio.sleep(15)


asyncio.run(main())
