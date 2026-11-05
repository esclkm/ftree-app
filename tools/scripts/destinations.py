"""Куда выкладывать сайт и где хранить медиа — только то, что владелец дерева написал в своём ftree.toml.

Что это. Приложение форкают другие люди. Если бы в коде стояло «по умолчанию — облако и сайт Павла», чужое дерево
молча слало бы фото и сайт к нему. Поэтому значений по умолчанию здесь нет: не задано — ничего никуда не уходит,
а команда объясняет, что вписать. Этот модуль читает и проверяет две части настроек:

  [storage]                       хранилища медиа (фото, сканы, PDF, звук)
  push_after_commit = true        хук после коммита сам отправляет новое (иначе — только `rodo media push`)
  [storage.media]                 открытое хранилище: фото под своими путями (родне можно дать посмотреть)
  kind = "rclone"                 rclone — любой remote rclone (Jottacloud, S3/R2, Google Drive…); local — папка; none
  address = "remote:Папка/"       адрес: remote rclone с папкой, или путь к папке для local
  [storage.private]               закрытое: звук, PDF, старое из истории git — файлы названы по контрольной сумме
  kind = "rclone"
  address = "remote-crypt:"
  encrypted = true                remote — rclone вида crypt: имена и содержимое зашифрованы (проверяет rodo setup)

  [site]
  publish_after_push = true       хук после push в основную ветку сам выкладывает сайт
  [[site.target]]                 цель выкладки, сколько угодно
  kind = "cloudflare-pages"       cloudflare-pages | folder — основной сайт; netlify | cloudflare-worker — зеркало
  project = "…"                   имя проекта (cloudflare-pages), site = "…" (netlify: номер сайта — Site ID; по имени
                                  netlify-cli сайт не находит), name = "…" (cloudflare-worker),
  url = "https://…"               path = "…" (folder); url — адрес, по которому сайт открывают (у основного — обязателен,
                                  если есть зеркало: туда оно пересылает)
  role = "main"                   main — сам сайт (rodo site publish); mirror — адрес-пересылка на основной (rodo site mirror)
  manual = true                   только по имени: rodo site publish <имя цели>

Читают: media.py, setup.py, site_export.py (цели → site.json → сборщик web/scripts/site.mjs), paths.py (для хуков).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import paths

STORAGE_KINDS = ("rclone", "local", "none")
STORES = ("media", "private")
# вид цели → (роль по умолчанию, какие роли можно, ключ имени на хостинге)
TARGET_KINDS = {
    "cloudflare-pages": ("main", ("main",), "project"),
    "folder": ("main", ("main",), "path"),
    "netlify": ("mirror", ("mirror",), "site"),
    "cloudflare-worker": ("mirror", ("mirror",), "name"),
}
HOW_STORAGE = ("в ftree.toml дерева нет [storage.media] / [storage.private] — медиа никуда не отправляется. Вписать, "
               "например (пример):\n  [storage.media]\n  kind = \"rclone\"\n  address = \"мой-remote:Дерево/\"\n"
               "  [storage.private]\n  kind = \"rclone\"\n  address = \"мой-remote-crypt:\"\n  encrypted = true\n"
               "Remote заводит человек: rclone config (или tools/setup/rclone_jotta.sh для Jottacloud). Навык setup.")
HOW_SITE = ("в ftree.toml дерева нет ни одной [[site.target]] — сайт собран, но никуда не выложен. Вписать, "
            "например (пример):\n  [[site.target]]\n  kind = \"cloudflare-pages\"\n  project = \"мой-проект\"\n"
            "  url = \"https://мой-проект.example\"\nВход на хостинг — человек (npx wrangler login). Навык setup.")


class ConfigError(SystemExit):
    """Ошибка в настройках — текст для человека (код выхода 1)."""

    def __init__(self, text: str):
        super().__init__(f"ftree.toml: {text}")


@dataclass(frozen=True)
class Store:
    name: str          # media | private
    kind: str          # rclone | local
    address: str       # remote:папка/ или /путь/
    encrypted: bool

    def label(self) -> str:
        return f"[storage.{self.name}] {self.kind} {self.address}" + (" (шифрованное)" if self.encrypted else "")


def _config(config: dict | None) -> dict:
    return paths.CONFIG if config is None else config


def storage(name: str, config: dict | None = None) -> Store | None:
    """Хранилище `media` или `private` из ftree.toml; не задано или kind = "none" — None."""
    raw = (_config(config).get("storage") or {}).get(name)
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError(f"[storage.{name}] — таблица с kind и address")
    kind = str(raw.get("kind") or "")
    if kind not in STORAGE_KINDS:
        raise ConfigError(f"[storage.{name}] kind = {kind!r} — нужно одно из: {', '.join(STORAGE_KINDS)}")
    if kind == "none":
        return None
    address = str(raw.get("address") or "").strip()
    if not address:
        raise ConfigError(f"[storage.{name}] address — куда класть (remote rclone с папкой или путь к папке)")
    encrypted = raw.get("encrypted", False)
    if not isinstance(encrypted, bool):
        raise ConfigError(f"[storage.{name}] encrypted — true или false")
    if kind == "local":
        if encrypted:
            raise ConfigError(f"[storage.{name}] папка (local) не шифруется — encrypted = false или kind = \"rclone\" "
                              "с remote вида crypt")
        address = str(Path(address).expanduser())
    elif ":" not in address:
        raise ConfigError(f"[storage.{name}] address = {address!r} — у rclone адрес «remote:папка/»")
    if not address.endswith((":", "/")):
        address += "/"
    bad = set(raw) - {"kind", "address", "encrypted"}
    if bad:
        raise ConfigError(f"[storage.{name}]: незнакомые ключи {', '.join(sorted(bad))}")
    return Store(name, kind, address, encrypted)


def stores(config: dict | None = None) -> dict[str, Store]:
    return {n: s for n in STORES if (s := storage(n, config))}


def push_after_commit(config: dict | None = None) -> bool:
    return bool((_config(config).get("storage") or {}).get("push_after_commit")) and bool(stores(config))


def site_targets(config: dict | None = None) -> list[dict]:
    """Цели выкладки из [[site.target]], проверенные; у каждой — kind, role, name (имя на хостинге), url, manual."""
    raw = (_config(config).get("site") or {}).get("target") or []
    if isinstance(raw, dict):
        raw = [raw]
    out, seen = [], set()
    for i, t in enumerate(raw, 1):
        where = f"[[site.target]] №{i}"
        kind = str(t.get("kind") or "")
        if kind not in TARGET_KINDS:
            raise ConfigError(f"{where}: kind = {kind!r} — нужно одно из: {', '.join(TARGET_KINDS)}")
        default_role, roles, key = TARGET_KINDS[kind]
        role = str(t.get("role") or default_role)
        if role not in roles:
            raise ConfigError(f"{where}: {kind} бывает только role = {' / '.join(roles)}")
        name = str(t.get(key) or "").strip()
        if not name:
            raise ConfigError(f"{where}: нужен {key} — имя на хостинге ({kind})")
        if kind == "folder":
            name = str(Path(name).expanduser())
        url = str(t.get("url") or "").strip()
        if url and not url.startswith("https://"):
            raise ConfigError(f"{where}: url = {url!r} — адрес сайта, https://…")
        bad = set(t) - {"kind", "role", key, "url", "manual"}
        if bad:
            raise ConfigError(f"{where}: незнакомые ключи {', '.join(sorted(bad))}")
        if (kind, name) in seen:
            raise ConfigError(f"{where}: {kind} {name!r} уже есть")
        seen.add((kind, name))
        out.append({"kind": kind, "role": role, "name": name, **({"url": url} if url else {}),
                    **({"manual": True} if t.get("manual") else {})})
    mains = [t for t in out if t["role"] == "main"]
    if any(t["role"] == "mirror" for t in out) and not any("url" in t for t in mains):
        raise ConfigError("зеркало пересылает на основной сайт — нужна цель role = \"main\" с url")
    return out


def publish_after_push(config: dict | None = None) -> bool:
    return bool((_config(config).get("site") or {}).get("publish_after_push")) and bool(site_targets(config))


def tree_name(config: dict | None = None) -> str:
    """Имя дерева из [tree] name — для файлов блокировки, логов и метки launchd (не «родословная» вообще)."""
    name = str((_config(config).get("tree") or {}).get("name") or "tree")
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in name) or "tree"


def run_file(what: str, config: dict | None = None) -> Path:
    """/tmp/ftree_<дерево>_<что> — замок или лог фоновой работы этого дерева."""
    return Path("/tmp") / f"ftree_{tree_name(config)}_{what}"
