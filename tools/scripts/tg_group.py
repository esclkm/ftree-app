"""Читаем публичную группу Telegram под аккаунтом Павла — текст сообщений в файл, без картинок.

Зачем: в группах вроде «Уезды Беларуси» люди выкладывают ссылки на архивы, указатели, сканы. Бот туда не попадёт,
а под своим аккаунтом видна вся история, даже без вступления в группу.

Вход — один раз, QR-кодом: телефон → Настройки → Устройства → Подключить устройство. Это новая строка в
«Устройствах»; удалить её можно там же. Ключ входа (файл .session) и api_id/api_hash лежат ВНЕ репозитория:
  ~/.config/ftree-telegram/config.toml   — api_id = 123, api_hash = "…"  (берутся на my.telegram.org)
  ~/.config/ftree-telegram/pavel.session — ключ от аккаунта: никому, ни в git, ни в облако.

  tools/py tools/scripts/tg_group.py login
  tools/py tools/scripts/tg_group.py topics https://t.me/<группа>      # подгруппы форума с номерами
  tools/py tools/scripts/tg_group.py dump https://t.me/<группа>        # всё; повторный запуск — только новое
  tools/py tools/scripts/tg_group.py dump https://t.me/<группа> --topic 24122   # одна подгруппа
  tools/py tools/scripts/tg_group.py search https://t.me/<группа> Вербичи
  tools/py tools/scripts/tg_group.py get https://t.me/<группа> 664 719  # файлы этих сообщений → <группа>/files/
  tools/py tools/scripts/tg_group.py dump -- -100XXXXXXXXXX          # закрытый чат — по номеру (без ссылки)
  tools/py tools/scripts/tg_group.py find "Духовщинский уезд" "Смоленский уезд"   # найти группы по словам
  tools/py tools/scripts/tg_group.py ctx https://t.me/<группа> 91919 95353  # сообщение с соседями: весь разговор

Выгрузка — 1_sources/found/telegram/<группа>/messages.jsonl, по строке на сообщение.
"""
import argparse
import asyncio
import json
import sys
import tomllib
from pathlib import Path

from telethon import TelegramClient

sys.path.insert(0, str(Path(__file__).parent))
import paths  # noqa: E402
from paths import FOUND  # noqa: E402

CONF_DIR = paths.TELEGRAM_DIR       # config.toml и ключ входа; другая папка — FTREE_TELEGRAM_DIR
OUT_DIR = FOUND / "telegram"


def client() -> TelegramClient:
    conf_file = CONF_DIR / "config.toml"
    if not conf_file.is_file():
        CONF_DIR.mkdir(parents=True, exist_ok=True)
        raise SystemExit(f"нет {conf_file}: впишите туда api_id = … и api_hash = \"…\" с my.telegram.org")
    conf = tomllib.loads(conf_file.read_text(encoding="utf-8"))
    if not conf.get("api_id") or not conf.get("api_hash"):
        raise SystemExit(f"в {conf_file} пустые api_id / api_hash: возьмите их на my.telegram.org → API development tools")
    # flood_sleep_threshold: Telegram просит подождать — ждём сами, а не падаем
    return TelegramClient(str(CONF_DIR / paths.TELEGRAM_SESSION), int(conf["api_id"]), conf["api_hash"],
                          flood_sleep_threshold=120, device_model="ftree (Mac)")


async def login(c: TelegramClient) -> None:
    await c.connect()
    if await c.is_user_authorized():
        print("уже вошли:", (await c.get_me()).first_name)
        return
    import qrcode
    from telethon.errors import SessionPasswordNeededError
    qr = await c.qr_login()
    while True:
        q = qrcode.QRCode(border=1)
        q.add_data(qr.url)
        q.print_ascii(invert=True)
        print("Телефон: Настройки → Устройства → Подключить устройство → наведите на код (живёт ~30 с)")
        try:
            await qr.wait(timeout=30)
            break
        except asyncio.TimeoutError:
            await qr.recreate()
        except SessionPasswordNeededError:
            import getpass
            await c.sign_in(password=getpass.getpass("Облачный пароль Telegram (не показывается): "))
            break
    print("вошли:", (await c.get_me()).first_name)


def peer(link: str) -> str | int:
    """Ссылка на публичную группу — как есть; закрытый чат — его номер (-100…), иначе Telethon ищет такое имя."""
    return int(link) if link.lstrip("-").isdigit() else link


def row(m) -> dict:
    s = m.sender
    name = None
    if s is not None:
        name = getattr(s, "title", None) or " ".join(filter(None, [getattr(s, "first_name", None),
                                                                    getattr(s, "last_name", None)]))
    return {"id": m.id, "date": m.date.isoformat(), "from": name, "from_id": m.sender_id,
            "reply_to": m.reply_to_msg_id, "text": m.message or "",
            "media": type(m.media).__name__.removeprefix("MessageMedia") if m.media else None,
            "file": m.file.name if m.file and m.file.name else None}


async def topics(c: TelegramClient, link: str) -> None:
    from telethon.tl.functions.messages import GetForumTopicsRequest
    ent = await c.get_entity(peer(link))
    r = await c(GetForumTopicsRequest(peer=ent, offset_date=None, offset_id=0, offset_topic=0, limit=100))
    for t in r.topics:
        print(t.id, getattr(t, "title", "?"))


async def dump(c: TelegramClient, link: str, topic: int | None = None) -> None:
    ent = await c.get_entity(peer(link))
    folder = OUT_DIR / (getattr(ent, "username", None) or str(ent.id))
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / (f"topic_{topic}.jsonl" if topic else "messages.jsonl")
    last = 0
    if out.is_file():
        for line in out.open(encoding="utf-8"):
            last = max(last, json.loads(line)["id"])
    n = 0
    with out.open("a", encoding="utf-8") as f:
        # wait_time — пауза между пачками по 100: читаем бережно
        async for m in c.iter_messages(ent, reverse=True, min_id=last, reply_to=topic, wait_time=1):
            f.write(json.dumps(row(m), ensure_ascii=False) + "\n")
            n += 1
            if n % 1000 == 0:
                print(n, m.date.date(), flush=True)
    print(f"{getattr(ent, 'title', link)}: новых {n} → {out}")


async def get(c: TelegramClient, link: str, ids: list[int]) -> None:
    ent = await c.get_entity(peer(link))
    folder = OUT_DIR / (getattr(ent, "username", None) or str(ent.id)) / "files"
    folder.mkdir(parents=True, exist_ok=True)
    for m in await c.get_messages(ent, ids=ids):
        if m is None or not m.file:
            print(f"{m.id if m else '?'}: файла нет")
            continue
        # номер сообщения в имени: одинаковые имена файлов в группе не затирают друг друга
        path = await m.download_media(file=str(folder / f"{m.id}_{m.file.name or 'file'}"))
        print(f"{m.id}: {path}")


async def search(c: TelegramClient, link: str, query: str) -> None:
    ent = await c.get_entity(peer(link))
    name = getattr(ent, "username", None)
    async for m in c.iter_messages(ent, search=query, limit=200, wait_time=1):
        url = f"https://t.me/{name}/{m.id}" if name else f"https://t.me/c/{ent.id}/{m.id}"
        print(f"{m.date.date()} {url}\n  {(m.message or '').replace(chr(10), ' ')[:300]}")


async def find(c: TelegramClient, queries: list[str]) -> None:
    from telethon.tl.functions.contacts import SearchRequest
    seen = set()
    for q in queries:
        r = await c(SearchRequest(q=q, limit=30))
        for ch in r.chats:
            if ch.id in seen:
                continue
            seen.add(ch.id)
            kind = "канал" if getattr(ch, "broadcast", False) else "форум" if getattr(ch, "forum", False) else "группа"
            print(f"{q} | https://t.me/{getattr(ch, 'username', None) or ch.id} | {ch.title} | {kind}, "
                  f"{getattr(ch, 'participants_count', None) or '?'} участн.")
        await asyncio.sleep(3)


async def ctx(c: TelegramClient, link: str, ids: list[int]) -> None:
    ent = await c.get_entity(peer(link))
    for i in ids:
        print(f"######## {i}")
        for m in await c.get_messages(ent, ids=list(range(i - 6, i + 8))):
            if m and (m.message or m.file):
                f = f" [{m.file.name}]" if m.file and m.file.name else ""
                print(f"[{m.id}]{f} {(m.message or '').replace(chr(10), ' ')[:600]}")
        await asyncio.sleep(2)


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["login", "topics", "dump", "search", "get", "find", "ctx"])
    ap.add_argument("link", nargs="?")
    ap.add_argument("query", nargs="?")
    ap.add_argument("more", nargs="*", help="для get и ctx — ещё номера сообщений; для find — ещё слова")
    ap.add_argument("--topic", type=int, help="номер подгруппы форума (список — команда topics)")
    a = ap.parse_args()
    c = client()
    # не `async with c`: он сам спрашивает номер телефона, а мы входим только QR-кодом
    await c.connect()
    try:
        if a.cmd == "login":
            return await login(c)
        if not await c.is_user_authorized():
            raise SystemExit("сначала: tg_group.py login")
        if a.cmd == "find":
            await find(c, [q for q in [a.link, a.query, *a.more] if q])
        elif a.cmd == "ctx":
            await ctx(c, a.link, [int(i) for i in [a.query, *a.more] if i])
        elif a.cmd == "topics":
            await topics(c, a.link)
        elif a.cmd == "dump":
            await dump(c, a.link, a.topic)
        elif a.cmd == "get":
            await get(c, a.link, [int(i) for i in [a.query, *a.more] if i])
        else:
            await search(c, a.link, a.query)
    finally:
        await c.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
