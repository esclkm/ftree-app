"""Опись медиа и облако: фото, сканы, PDF и звук живут вне git, их копия — в хранилище, которое задал владелец дерева.

Что это. Картинки, PDF и звук больше не хранятся в git (там им тесно и опасно: GitHub, история). Вместо них в git —
опись `media/manifest.jsonl`: по строке на файл — путь, контрольная сумма, размер, вид, куда и под каким именем ушёл
в облако. Сам файл лежит на диске, как раньше. Хранилищ два, оба — в ftree.toml дерева (destinations.py); значений по
умолчанию в коде нет: не задано — медиа никуда не уходит, `media.py push` говорит, что вписать.
  • открытое `[storage.media]` — **фото** (jpg, png, webp, heic…) под своими путями, как в проекте: эти папки можно
    дать родне посмотреть. Переименовал на диске — `media.py mv`, и в хранилище тоже;
  • закрытое `[storage.private]` — **звук и PDF** (записи разговоров, документы живых) и старое из истории git. Файл
    назван по контрольной сумме (`media/ab/ab12….pdf`): одинаковое не дублируется. `encrypted = true` — remote rclone
    вида crypt (имена и содержимое зашифрованы): в remote другого вида с этой пометкой отправка не пойдёт.
    Звук идёт сжатой копией (Opus 24 кбит/с, моно: 100 МБ → ~10 МБ); оригинал — только на Mac.
Подробно — документ дерева проект/ХРАНЕНИЕ.md (опись медиа и облако; пароль шифрования).

Команды:
  media.py status                 — что в описи, что не отправлено, что новое или изменилось на диске, чего нет локально
  media.py add                    — только внести новое в опись, без облака (так делает pre-commit; отправит post-commit)
  media.py push [--history] [-n]  — внести новое в опись и отправить в облако; --history — ещё медиа из истории git,
                                    которых уже нет на диске (вид history); -n — только показать
  media.py pull <путь>… | --all [--dest папка] [--history]
                                  — скачать из облака (новый Mac); звук приходит сжатой копией `<имя>.opus`
  media.py verify [--deep]        — облако против описи: каждый файл на месте, размер совпадает; --deep — ещё сверка
                                    содержимого (rclone check / cryptcheck) для того, что есть на диске
  media.py mv <старый> <новый>    — переименовать файл на диске, в описи и в открытом облаке, поправить ссылки в .md
  media.py rm <путь> [--force]    — убрать файл с диска (в Корзину), из описи и из открытого облака (в его корзину);
                                    семейный оригинал — только с --force
  media.py check-staged           — для pre-commit: медиа в индексе git — стоп (новое на диске pre-commit вносит сам: add)
  media.py stub                   — только на GitHub (CI): пустые файлы по описи, чтобы проверки видели «файл есть»

Вид хранилища: `rclone` — любой remote rclone (Jottacloud, S3/R2, Google Drive…), `local` — папка, `none` — никуда.
Переменные (обычно не нужны; или ~/.config/ftree/env — paths.setting): MEDIA_ROOT — корень проекта; MEDIA_REMOTE,
MEDIA_OPEN_REMOTE — адрес закрытого и открытого хранилища вместо ftree.toml (для проверок); MEDIA_CACHE — где хранить сжатый звук и кэш сумм; FFMPEG — путь к ffmpeg. Пароль файла настроек rclone берётся из
Связки ключей (`rclone-config`), если он там есть; в файлах проекта пароля нет.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tempfile
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import destinations  # где хранить: [storage.media] и [storage.private] в ftree.toml дерева, без значений по умолчанию
import paths  # раскладка этажей (пути от корня одинаковы в любом дереве)

_R = paths.rel
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".heic", ".gif"}
AUDIO_EXT = {".m4a", ".wav", ".mp3"}
MEDIA_EXT = PHOTO_EXT | AUDIO_EXT | {".pdf", ".opus"}
# Где искать медиа. Остальное (web/, web/site_assets/ — картинки кода; 4_outputs/ — собирается заново) — не медиа.
SCAN_DIRS = tuple(map(_R, (paths.SOURCES, paths.TRANSCRIPTS, paths.RESEARCH)))
_GASO_OLD = _R(paths.ARCHIVES_ONLINE / "gaso_smolensk")
# Что не идёт ни в опись, ни в облако (раздел 4 плана):
EXCLUDE = (
    f"{_GASO_OLD}/ф48*/*",                             # папки дел — сырьё ГАСО → $ARCHIVES_LOCAL/raw;
    # страница о нашем человеке — файлом прямо в gaso_smolensk/ с именем по содержанию: это находка, идёт в опись
    f"{_R(paths.ARCHIVES_ONLINE)}/rusneb_*/*",          # справочники-сканы >20 МБ → archives/raw (решение 8)
    f"{_R(paths.TRANSCRIPTS_AUDIO)}/_raw_*/*",          # копии звука для распознавания — делаются заново из m4a
    f"{_R(paths.FAMILY)}/social/*.zip",                 # выгрузки соцсетей → ~/Backups/social_raw
)
# Медиа из истории git: что из этого НЕ берём (код, сборки, профиль браузера, чужие переписки, копии звука)
HISTORY_EXCLUDE = (".wbh-profile/*", "tools/*", f"{_R(paths.OUTPUTS)}/*", "web/*", "output/*.pdf", "data/social_export/*",
                   "*/_raw_*/*.wav", f"{_GASO_OLD}/ф48*/*")
CODE_MEDIA = ("web/",)          # картинки, которые остаются в git (это код)
MANIFEST = Path("media") / "manifest.jsonl"
OPUS = ["-c:a", "libopus", "-b:a", "24k", "-ac", "1", "-application", "voip"]
COPY_FORMAT = "opus-24k-mono"
OPEN, CRYPT = "open", "crypt"


@dataclass
class Ctx:
    root: Path
    remote: str | None        # закрытое хранилище (звук, PDF, история); None — не задано, туда ничего не уходит
    open_remote: str | None   # открытое хранилище (фото); None — не задано
    cache: Path
    encrypted: bool = False   # закрытое помечено encrypted = true: remote обязан быть вида crypt
    _hashes: dict = field(default_factory=dict)
    _names: dict = field(default_factory=dict)  # (хранилище, имя в NFC) → имя, как оно записано в облаке

    @property
    def manifest(self) -> Path:
        return self.root / MANIFEST

    @property
    def hash_cache(self) -> Path:
        return self.cache / "hashes.json"

    def base(self, store: str) -> str | None:
        return self.open_remote if store == OPEN else self.remote

    def configured(self) -> list[str]:
        return [s for s in (OPEN, CRYPT) if self.base(s)]


def _slash(remote: str | None) -> str | None:
    if not remote:
        return None
    return remote if remote.endswith((":", "/")) else remote + "/"


STORE_NAME = {OPEN: "открытое ([storage.media])", CRYPT: "закрытое ([storage.private])"}


def make_ctx(root: str | None = None, remote: str | None = None, open_remote: str | None = None) -> Ctx:
    root_p = Path(root or os.environ.get("MEDIA_ROOT") or _tree_root())
    configured = destinations.stores(_toml(root_p))
    private, media_store = configured.get("private"), configured.get("media")
    encrypted = bool(not (remote or paths.setting("MEDIA_REMOTE")) and private and private.encrypted)
    remote = remote or paths.setting("MEDIA_REMOTE") or (private.address if private else None)
    open_remote = open_remote or paths.setting("MEDIA_OPEN_REMOTE") or (media_store.address if media_store else None)
    cache = Path(os.environ.get("MEDIA_CACHE")
                 or (paths.CACHE if root_p.resolve() == paths.ROOT.resolve() else root_p / "tools" / ".cache") / "media")
    ctx = Ctx(root_p, _slash(remote), _slash(open_remote), cache, encrypted=encrypted)
    if ctx.hash_cache.exists():
        ctx._hashes = json.loads(ctx.hash_cache.read_text(encoding="utf-8"))
    return ctx


def _tree_root() -> Path:
    return paths.find_root()


def _toml(root: Path) -> dict:
    f = root / "ftree.toml"
    if not f.exists():
        return {}
    import tomllib
    return tomllib.loads(f.read_text(encoding="utf-8"))


# ---------- опись ----------

def load(ctx: Ctx) -> dict[str, dict]:
    if not ctx.manifest.exists():
        return {}
    rows = (json.loads(line) for line in ctx.manifest.read_text(encoding="utf-8").splitlines() if line.strip())
    return {r["path"]: r for r in rows}


def save(ctx: Ctx, rows: dict[str, dict]) -> None:
    ctx.manifest.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(rows[p], ensure_ascii=False, sort_keys=True) + "\n" for p in sorted(rows))
    tmp = ctx.manifest.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(ctx.manifest)
    ctx.cache.mkdir(parents=True, exist_ok=True)
    ctx.hash_cache.write_text(json.dumps(ctx._hashes, ensure_ascii=False), encoding="utf-8")


@contextlib.contextmanager
def locked(ctx: Ctx):
    """Опись правит один процесс за раз: фоновая отправка (post-commit) и коммит соседней сессии не затрут друг друга."""
    ctx.cache.mkdir(parents=True, exist_ok=True)
    with open(ctx.cache / "manifest.lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def excluded(rel: str, patterns=EXCLUDE) -> bool:
    return any(fnmatch.fnmatch(rel, p) for p in patterns)


def is_media(rel: str) -> bool:
    return Path(rel).suffix.lower() in MEDIA_EXT


def icloud_copy(folder: Path, name: str) -> bool:
    """Мусорная копия iCloud: «фото 2.jpg» рядом с «фото.jpg». «Lipowa 2.m4a» без «Lipowa.m4a» — настоящий файл."""
    m = re.fullmatch(r"(.+) \d+(\.[^.]+)", name)
    return bool(m) and (folder / (m.group(1) + m.group(2))).exists()


def scan(ctx: Ctx) -> list[str]:
    """Медиа на диске (пути от корня), которые должны быть в описи."""
    found = []
    for top in SCAN_DIRS:
        for dirpath, dirs, files in os.walk(ctx.root / top):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for name in files:
                rel = (Path(dirpath) / name).relative_to(ctx.root).as_posix()
                if is_media(rel) and not excluded(rel) and not icloud_copy(Path(dirpath), name):
                    found.append(rel)
    return sorted(found)


def kind_of(rel: str) -> str:
    if Path(rel).suffix.lower() in AUDIO_EXT:
        return "audio"
    if rel.startswith(_R(paths.FAMILY) + "/"):
        return "family"
    if rel.startswith(_R(paths.PHOTOS_PROCESSED) + "/"):
        return "processed"
    return "found"


def store_of(rel: str, kind: str) -> str:
    """Фото — в открытое хранилище (родня смотрит в приложении); звук, PDF и старое из истории — в шифрованное."""
    return OPEN if Path(rel).suffix.lower() in PHOTO_EXT and kind != "history" else CRYPT


def sha256(ctx: Ctx, rel: str) -> tuple[str, int]:
    """Сумма файла; пересчёт, только если поменялись размер, inode или время (кэш)."""
    p = ctx.root / rel
    st = p.stat()
    key = [st.st_size, st.st_ino, st.st_mtime_ns]
    hit = ctx._hashes.get(rel)
    if hit and hit[:3] == key:
        return hit[3], st.st_size
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    ctx._hashes[rel] = key + [h.hexdigest()]
    return h.hexdigest(), st.st_size


def remote_name(digest: str, ext: str) -> str:
    return f"media/{digest[:2]}/{digest}{ext.lower()}"


def new_row(rel: str, digest: str, size: int) -> dict:
    kind = kind_of(rel)
    store = store_of(rel, kind)
    remote = rel if store == OPEN else None if kind == "audio" else remote_name(digest, Path(rel).suffix)
    return {"path": rel, "sha256": digest, "size": size, "kind": kind, "store": store, "remote": remote,
            "added": date.today().isoformat()}


def refresh(ctx: Ctx, rows: dict[str, dict]) -> dict[str, list[str]]:
    """Сверить опись с диском: новое — внести, изменённое — обновить. Вернуть, что нашлось."""
    report = {"new": [], "changed": [], "missing": []}
    on_disk = scan(ctx)
    for rel in on_disk:
        digest, size = sha256(ctx, rel)
        row = rows.get(rel)
        if row and row["sha256"] == digest:
            continue
        if row and size == 0 and row.get("size", 0) > 0:
            # пустой файл там, где в описи настоящий, — пустышка (media.py stub для проверок) или недокачанное: опись
            # не трогать, иначе её строка станет пустой, а отправка затрёт настоящий файл в хранилище
            continue
        report["changed" if row else "new"].append(rel)
        rows[rel] = new_row(rel, digest, size) | ({"added": row["added"]} if row else {})
    disk = set(on_disk)
    report["missing"] = [p for p, r in rows.items() if p not in disk and r["kind"] != "history"]
    return report


# ---------- rclone и ffmpeg ----------

def _env() -> dict:
    env = dict(os.environ)
    if "RCLONE_PASSWORD_COMMAND" not in env and not env.get("MEDIA_NO_KEYCHAIN"):
        probe = subprocess.run(["security", "find-generic-password", "-s", "rclone-config", "-w"],
                               capture_output=True, text=True)
        if probe.returncode == 0:
            env["RCLONE_PASSWORD_COMMAND"] = "security find-generic-password -s rclone-config -w"
    return env


def redact(text: str) -> str:
    """Убрать из текста пароли строки подключения (`password=…`): их «маскировка» в rclone обратима."""
    return re.sub(r"(password2?|pass|token)=[^,:'\"\s]+", r"\1=***", text or "")


def rclone(*args, check=True, capture=True) -> subprocess.CompletedProcess:
    r = subprocess.run(["rclone", *args], capture_output=capture, text=True, env=_env())
    if capture:
        r.stderr = redact(r.stderr)
    if check and r.returncode != 0:
        raise SystemExit(f"rclone {args[0]}: ошибка {r.returncode}\n{r.stderr[-2000:]}")
    return r


def remote_type(address: str) -> str:
    """Вид remote rclone по адресу: «имя:папка» → из rclone listremotes --long; «:crypt,…:» — строка подключения."""
    if address.startswith(":"):
        return re.split(r"[,:]", address[1:], maxsplit=1)[0]
    name = address.split(":", 1)[0] + ":"
    for line in rclone("listremotes", "--long", check=False).stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == name:
            return parts[1]
    return ""


def encryption_problem(ctx: Ctx) -> str | None:
    """Закрытое помечено encrypted = true, а remote не шифрует — текст для человека; всё верно — None."""
    if not ctx.encrypted or not ctx.remote:
        return None
    kind = remote_type(ctx.remote)
    if kind == "crypt":
        return None
    return (f"[storage.private] encrypted = true, а {redact(ctx.remote)} — " + (f"rclone вида {kind}" if kind else "не remote rclone")
            + ": звук и PDF ушли бы незашифрованными. Нужен remote вида crypt (rclone config) или encrypted = false")


def remote_listing(ctx: Ctx) -> dict[tuple[str, str], int] | None:
    """Что лежит в облаке: (хранилище, имя) → размер. None — облако недоступно. Незаданное хранилище — пропускаем."""
    out: dict[tuple[str, str], int] = {}
    for store, base, prefix in ((CRYPT, ctx.remote and ctx.remote + "media", "media/"), (OPEN, ctx.open_remote, "")):
        if not base:
            continue
        r = rclone("lsjson", "-R", "--files-only", "--no-mimetype", "--no-modtime", base, check=False)
        if r.returncode != 0:
            if "directory not found" in (r.stderr or ""):
                continue
            print(f"⚠ облако {redact(base)} недоступно: {r.stderr.strip()[-300:]}", file=sys.stderr)
            return None
        for e in json.loads(r.stdout or "[]"):
            k = (store, nfc(prefix + e["Path"]))
            out[k] = e["Size"]
            ctx._names[k] = prefix + e["Path"]
    return out


def nfc(name: str) -> str:
    """Одна запись букв: macOS пишет «й» двумя знаками (NFD), Jottacloud хранит одним (NFC) — сравниваем в NFC."""
    return unicodedata.normalize("NFC", name)


def key(row: dict) -> tuple[str, str]:
    return row.get("store", CRYPT), nfc(row["remote"])


def ffmpeg() -> str:
    for cand in (os.environ.get("FFMPEG"), shutil.which("ffmpeg"), str(paths.ASR_HOME / "bin/ffmpeg")):
        if cand and Path(cand).exists():
            return cand
    raise SystemExit("нет ffmpeg: brew install ffmpeg (или FFMPEG=путь)")


def audio_copy(ctx: Ctx, row: dict) -> Path:
    """Сжатая копия звука (Opus 24 кбит/с, моно) — в кэше, по сумме оригинала; делается один раз."""
    out = ctx.cache / "opus" / f"{row['sha256']}.opus"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".part.opus")
        subprocess.run([ffmpeg(), "-nostdin", "-loglevel", "error", "-y", "-i", str(ctx.root / row["path"]),
                        "-vn", "-map_metadata", "-1", *OPUS, str(tmp)], check=True)
        tmp.replace(out)
    return out


def prepare_audio(ctx: Ctx, row: dict) -> Path:
    src = audio_copy(ctx, row)
    if not row.get("copy"):
        h = hashlib.sha256(src.read_bytes()).hexdigest()
        row["copy"] = {"format": COPY_FORMAT, "sha256": h, "size": src.stat().st_size}
        row["remote"] = remote_name(h, ".opus")
    return src


def remote_size(row: dict) -> int:
    return row["copy"]["size"] if row.get("copy") else row["size"]


# ---------- медиа из истории git ----------

def history_rows(ctx: Ctx, rows: dict[str, dict]) -> list[dict]:
    """Медиа, которые были в git, а на диске и в описи их нет (по содержимому). Сумма — из самого блоба."""
    git = ["git", "-C", str(ctx.root)]
    if subprocess.run([*git, "rev-parse"], capture_output=True).returncode != 0:
        return []
    known = {r["sha256"] for r in rows.values()}
    objs = subprocess.run([*git, "-c", "core.quotepath=false", "rev-list", "--objects", "--all"],
                          capture_output=True, text=True, check=True).stdout.splitlines()
    out, seen = [], set()
    for line in objs:
        oid, _, rel = line.partition(" ")
        if not rel or not is_media(rel) or excluded(rel, HISTORY_EXCLUDE) or oid in seen or rel in rows:
            continue
        seen.add(oid)
        data = subprocess.run([*git, "cat-file", "blob", oid], capture_output=True, check=True).stdout
        digest = hashlib.sha256(data).hexdigest()
        if digest in known:
            continue
        known.add(digest)
        last = subprocess.run([*git, "log", "-1", "--format=%h", "--all", "--", rel],
                              capture_output=True, text=True).stdout.strip()
        out.append({"path": rel, "sha256": digest, "size": len(data), "kind": "history", "store": CRYPT,
                    "blob": oid, "commit": last, "added": date.today().isoformat(),
                    "remote": remote_name(digest, Path(rel).suffix)})
    return out


# ---------- команды ----------

def stage_dir(items: list[tuple[str, Path]]) -> Path:
    """Временная папка со ссылками «имя в облаке → файл на диске» — чтобы отправить всё одним вызовом rclone."""
    tmp = Path(tempfile.mkdtemp(prefix="media_stage_"))
    for name, src in items:
        dst = tmp / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            dst.symlink_to(src.resolve())
    return tmp


def cmd_status(ctx: Ctx, args) -> int:
    rows = load(ctx)
    rep = refresh(ctx, dict(rows))
    kinds: dict[str, list] = {}
    for r in rows.values():
        kinds.setdefault(f"{r['kind']} ({r.get('store', CRYPT)})", []).append(r)
    print(f"Опись: {len(rows)} файлов, {sum(r['size'] for r in rows.values()) / 1e6:.0f} МБ на диске")
    for k, rs in sorted(kinds.items()):
        print(f"  {k:20} {len(rs):5}  в облаке {sum(1 for r in rs if r.get('pushed')):5}")
    unsent = [p for p, r in rows.items() if not r.get("pushed")]
    for label, items in (("не в описи (новые)", rep["new"]), ("изменились на диске", rep["changed"]),
                         ("не отправлены в облако", unsent), ("нет локально (media.py pull)", rep["missing"])):
        if items:
            print(f"{label}: {len(items)}")
            for p in items[:10]:
                print(f"  {p}")
            if len(items) > 10:
                print(f"  … ещё {len(items) - 10}")
    # опись не трогаем — status только смотрит; кэш сумм сохраняем, чтобы в следующий раз не считать заново
    ctx.cache.mkdir(parents=True, exist_ok=True)
    ctx.hash_cache.write_text(json.dumps(ctx._hashes, ensure_ascii=False), encoding="utf-8")
    return 1 if rep["new"] or rep["changed"] or unsent else 0


def cmd_add(ctx: Ctx, args) -> int:
    with locked(ctx):
        rows = load(ctx)
        rep = refresh(ctx, rows)
        if rep["new"] or rep["changed"]:
            save(ctx, rows)
    for p in rep["new"] + rep["changed"]:
        print(f"в опись: {p}")
    return 0


def not_configured(ctx: Ctx) -> int:
    print(destinations.HOW_STORAGE)
    return 0


def cmd_push(ctx: Ctx, args) -> int:
    if not ctx.configured():  # хранилище не задано — ничего никуда; опись живёт и так (её ведёт pre-commit)
        return not_configured(ctx)
    for store in (OPEN, CRYPT):
        if not ctx.base(store):
            print(f"{STORE_NAME[store]} не задано в ftree.toml — туда ничего не отправляется")
    blocked = encryption_problem(ctx)
    if blocked:
        print(f"✋ {blocked}")
    # опись — под замком только на чтение и запись; сама отправка (минуты на большой звук) идёт без замка
    with locked(ctx):
        rows = load(ctx)
        rep = refresh(ctx, rows)
        if args.history:
            for r in history_rows(ctx, rows):
                rows[r["path"]] = r
        print(f"новых {len(rep['new'])}, изменилось {len(rep['changed'])}, нет локально {len(rep['missing'])}")
        usable = {s for s in ctx.configured() if not (s == CRYPT and blocked)}
        todo = [r for r in rows.values() if not r.get("pushed") and r.get("store", CRYPT) in usable
                and (r["kind"] == "history" or (ctx.root / r["path"]).exists())]
        if args.dry_run:
            for store in sorted(usable):
                part = [r for r in todo if r.get("store", CRYPT) == store]
                print(f"в {redact(ctx.base(store))}: {len(part)} файлов, {sum(r['size'] for r in part) / 1e6:.0f} МБ (до сжатия звука)")
            return 0
        items, blobs_dir = [], Path(tempfile.mkdtemp(prefix="media_blobs_"))
        for r in todo:
            if r["kind"] == "audio":
                items.append((prepare_audio(ctx, r), r))
            elif r["kind"] == "history":
                blob = blobs_dir / r["sha256"]
                blob.write_bytes(subprocess.run(["git", "-C", str(ctx.root), "cat-file", "blob", r["blob"]],
                                                capture_output=True, check=True).stdout)
                items.append((blob, r))
            else:
                items.append((ctx.root / r["path"], r))
        save(ctx, rows)  # опись — до отправки: прервётся rclone — опись уже знает про файлы
    if not items:
        print("отправлять нечего")
        return 0
    for store in (OPEN, CRYPT):
        part = [(r["remote"], src) for src, r in items if r.get("store", CRYPT) == store]
        if not part:
            continue
        tmp = stage_dir(part)
        print(f"отправляю {len(part)} файлов в {redact(ctx.base(store))} …", flush=True)
        # шифрованное: имя = сумма, значит есть — то же самое; открытое: имя = путь, сверяем по содержимому
        how = ["--ignore-existing"] if store == CRYPT else ["--checksum"]
        rclone("copy", "-L", *how, "--transfers", "4", "--stats-one-line", "--stats", "60s",
               str(tmp), ctx.base(store), check=False, capture=False)
        shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(blobs_dir, ignore_errors=True)
    listing = remote_listing(ctx)
    sent = {r["path"]: r for _, r in items if listing is not None and listing.get(key(r)) == remote_size(r)}
    with locked(ctx):  # опись перечитать: пока шла отправка, её мог дописать коммит соседней сессии
        rows = load(ctx)
        for path, r in sent.items():
            if path in rows and rows[path]["sha256"] == r["sha256"]:
                rows[path]["pushed"] = date.today().isoformat()
        save(ctx, rows)
    print(f"в облаке: {len(sent)} из {len(items)}" + ("" if len(sent) == len(items) else " — остальное: media.py push ещё раз"))
    return 0 if len(sent) == len(items) and not blocked else 1


def cmd_verify(ctx: Ctx, args) -> int:
    if not ctx.configured():
        return not_configured(ctx)
    rows = {p: r for p, r in load(ctx).items() if ctx.base(r.get("store", CRYPT))}  # сверяем только заданное
    listing = remote_listing(ctx)
    if listing is None:
        return 2
    bad = []
    for r in rows.values():
        if not r.get("remote"):
            bad.append(f"нет имени в облаке (звук не сжат — media.py push): {r['path']}")
        elif key(r) not in listing:
            bad.append(f"нет в облаке: {r['path']}")
        elif listing[key(r)] != remote_size(r):
            bad.append(f"размер в облаке {listing[key(r)]} ≠ {remote_size(r)}: {r['path']}")
        elif r["kind"] != "history" and (ctx.root / r["path"]).exists() and sha256(ctx, r["path"])[0] != r["sha256"]:
            bad.append(f"на диске изменился (media.py push): {r['path']}")
    notes = []
    if args.deep and not bad:
        for store in ctx.configured():
            items = []
            for r in rows.values():
                if r.get("store", CRYPT) != store:
                    continue
                if r["kind"] == "audio":
                    cached = ctx.cache / "opus" / f"{r['sha256']}.opus"
                    if cached.exists():
                        items.append((r["remote"], cached))
                elif r["kind"] != "history" and (ctx.root / r["path"]).exists():
                    items.append((r["remote"], ctx.root / r["path"]))
            if not items:
                continue
            tmp = stage_dir(items)
            if store == CRYPT:
                res = rclone("cryptcheck", "-L", "--one-way", str(tmp / "media"), ctx.remote + "media", check=False)
            else:
                res = rclone("check", "-L", "--one-way", str(tmp), ctx.open_remote, check=False)
            shutil.rmtree(tmp, ignore_errors=True)
            notes.append(f"{store}: содержимое сверено у {len(items)}")
            if res.returncode != 0:
                bad.append(f"{store} check: " + (res.stderr or "").strip()[-1500:])
    expected = {key(r) for r in rows.values() if r.get("remote")}
    orphans = set(listing) - expected
    for b in bad[:50]:
        print("✗", b)
    extra = ""
    if orphans:
        by = {s: sum(1 for k in orphans if k[0] == s) for s in (OPEN, CRYPT)}
        extra = f"; в облаке лишних: открытом {by[OPEN]}, шифрованном {by[CRYPT]} (старые версии или переименованное)"
    print(f"Проверка: в описи {len(rows)}, в облаке {len(listing)}, расхождений {len(bad)}"
          + (f"; {', '.join(notes)}" if notes else "") + extra)
    return 1 if bad else 0


def cmd_pull(ctx: Ctx, args) -> int:
    rows = load(ctx)
    dest = Path(args.dest) if args.dest else ctx.root
    want = [r for r in rows.values() if (args.all and (args.history or r["kind"] != "history"))
            or r["path"] in args.paths]
    unknown = [p for p in args.paths if p not in rows]
    for p in unknown:
        print(f"нет в описи: {p}")
    items = []
    for r in want:
        target = dest / r["path"]
        if r.get("copy"):
            target = target.with_suffix(".opus")  # звук в облаке — сжатая копия
        if target.exists() and not args.dest:
            continue
        if not r.get("pushed"):
            print(f"не было в облаке: {r['path']}")
            continue
        items.append((r, target))
    if not items:
        print("скачивать нечего")
        return 1 if unknown else 0
    lost = sorted({STORE_NAME[r.get("store", CRYPT)] for r, _ in items if not ctx.base(r.get("store", CRYPT))})
    if lost:
        print(f"✋ хранилище не задано в ftree.toml: {', '.join(lost)} — откуда скачивать?\n{destinations.HOW_STORAGE}")
        return 2
    if remote_listing(ctx) is None:
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="media_pull_"))
    real = lambda r: ctx._names.get(key(r), r["remote"])  # noqa: E731 — имя, как его записало облако
    for store in (OPEN, CRYPT):
        names = sorted({real(r) for r, _ in items if r.get("store", CRYPT) == store})
        if names:
            (tmp / f"{store}.txt").write_text("".join(n + "\n" for n in names), encoding="utf-8")
            rclone("copy", "--files-from", str(tmp / f"{store}.txt"), ctx.base(store), str(tmp / store), capture=False)
    bad = 0
    for r, target in items:
        got = tmp / r.get("store", CRYPT) / real(r)
        want_sha = r["copy"]["sha256"] if r.get("copy") else r["sha256"]
        if not got.exists() or hashlib.sha256(got.read_bytes()).hexdigest() != want_sha:
            print(f"✗ не сошлась сумма: {r['path']}")
            bad += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(got, target)  # копия, а не перенос: одинаковые файлы в облаке лежат одним
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"скачано {len(items) - bad} из {len(items)}, суммы сверены")
    return 1 if bad or unknown else 0


def md_files(ctx: Ctx):
    """Где искать ссылки на медиа: все .md, кроме оригиналов (описи `00_ОПИСЬ_*` в оригиналах — можно)."""
    for dirpath, dirs, files in os.walk(ctx.root):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", paths.OUTPUTS.name)]
        for name in files:
            if not name.endswith(".md"):
                continue
            p = Path(dirpath) / name
            rel = p.relative_to(ctx.root).as_posix()
            if rel.startswith(_R(paths.SOURCES) + "/") and not name.startswith("00_ОПИСЬ"):
                continue
            yield p


def fix_links(ctx: Ctx, rows: dict, old: str, new: str | None) -> list[str]:
    """Поправить ссылки: полный путь и `[[имя файла]]` (если имя файла в описи одно). new=None — убрать строку media."""
    old_name = Path(old).name
    unique = sum(1 for p in rows if Path(p).name == old_name) <= 1
    touched = []
    for p in md_files(ctx):
        text = p.read_text(encoding="utf-8")
        if old not in text and old_name not in text:
            continue
        orig = text
        if new is None:
            lines = [ln for ln in text.splitlines(keepends=True)
                     if not (unique and ln.strip() in (f'- "[[{old_name}]]"', f"- '[[{old_name}]]'", f"- [[{old_name}]]"))]
            text = "".join(lines)
        else:
            text = text.replace(old, new)
            if unique and Path(new).name != old_name:
                text = text.replace(f"[[{old_name}]]", f"[[{Path(new).name}]]").replace(f"[[{old_name}|", f"[[{Path(new).name}|")
        if text != orig:
            p.write_text(text, encoding="utf-8")
            touched.append(p.relative_to(ctx.root).as_posix())
        if new is None and (old in text or (unique and f"[[{old_name}" in text)):
            print(f"  ⚠ ссылка осталась (убрать руками): {p.relative_to(ctx.root)}")
    return touched


def cmd_mv(ctx: Ctx, args) -> int:
    rows = load(ctx)
    old, new = args.old, args.new
    if old not in rows:
        raise SystemExit(f"нет в описи: {old}")
    if new in rows or (ctx.root / new).exists():
        raise SystemExit(f"уже есть: {new}")
    row = rows[old]
    if row.get("store") == OPEN and row.get("pushed") and not ctx.open_remote:
        print("⚠ открытое хранилище ([storage.media]) не задано — в облаке файл остался под старым именем")
    elif row.get("store") == OPEN and row.get("pushed"):  # в открытом облаке имя = путь: переименовать и там
        remote_listing(ctx)
        rclone("moveto", ctx.open_remote + ctx._names.get(key(row), old), ctx.open_remote + nfc(new))
    (ctx.root / new).parent.mkdir(parents=True, exist_ok=True)
    if (ctx.root / old).exists():
        (ctx.root / old).rename(ctx.root / new)
    rows.pop(old)
    row["path"] = new
    if row.get("store") == OPEN:
        row["remote"] = new
    rows[new] = row
    ctx._hashes.pop(old, None)
    touched = fix_links(ctx, rows, old, new)
    save(ctx, rows)
    print(f"переименовано; ссылки поправлены в {len(touched)} файлах" + "".join(f"\n  {t}" for t in touched))
    return 0


def cmd_rm(ctx: Ctx, args) -> int:
    rows = load(ctx)
    row = rows.get(args.path)
    if not row:
        raise SystemExit(f"нет в описи: {args.path}")
    if row["kind"] in ("family", "audio") and not args.force:
        raise SystemExit("это семейный оригинал: удалять только с --force и после «да» Павла")
    src = ctx.root / args.path
    if src.exists():
        trash = Path(os.environ.get("MEDIA_TRASH") or Path.home() / ".Trash")
        trash.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), trash / f"{src.stem}_{row['sha256'][:8]}{src.suffix}")
    if row.get("store") == OPEN and row.get("pushed") and not ctx.open_remote:
        print("⚠ открытое хранилище ([storage.media]) не задано — из облака файл не убран")
    elif row.get("store") == OPEN and row.get("pushed"):  # родня не должна видеть убранное; облако — в свою корзину
        remote_listing(ctx)
        rclone("deletefile", ctx.open_remote + ctx._names.get(key(row), row["remote"]), check=False)
    rows.pop(args.path)
    ctx._hashes.pop(args.path, None)
    touched = fix_links(ctx, rows | {args.path: row}, args.path, None)
    save(ctx, rows)
    kept = "копия в шифрованном облаке остаётся" if row.get("store") != OPEN else "из открытого облака — в его корзину"
    print(f"убрано в Корзину и из описи; строки media убраны в {len(touched)} файлах; {kept}")
    return 0


def cmd_check_staged(ctx: Ctx, args) -> int:
    staged = subprocess.run(["git", "-C", str(ctx.root), "-c", "core.quotepath=false", "diff", "--cached",
                             "--name-only", "--diff-filter=AM"], capture_output=True, text=True).stdout.splitlines()
    in_git = [p for p in staged if is_media(p) and not p.startswith(CODE_MEDIA)]
    for p in in_git[:20]:
        print(f"✋ медиа в коммите (им место в описи, не в git): {p}")
    return 1 if in_git else 0


def cmd_stub(ctx: Ctx, args) -> int:
    """Пустой файл на место каждого файла описи, которого нет на диске, — для проверок без облака (GitHub Actions).
    Проверки тогда отличают «файла нет нигде» от «файл в облаке». Только при CI: на Mac пустышка ушла бы в облако
    поверх настоящего файла."""
    if not os.environ.get("CI"):
        print("✋ stub — только для проверок на GitHub (переменная CI). Здесь нужные файлы — media.py pull")
        return 1
    stamp = time.time() + 86400  # одно время у всех: «PDF старее страниц» (documents.py) не ловит пустышки
    made = 0
    for rel in load(ctx):
        f = ctx.root / rel
        if not f.exists():
            f.parent.mkdir(parents=True, exist_ok=True)
            f.touch()
            os.utime(f, (stamp, stamp))
            made += 1
    print(f"пустышек по описи: {made}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root")
    ap.add_argument("--remote")
    ap.add_argument("--open-remote")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("add")
    p = sub.add_parser("push")
    p.add_argument("--history", action="store_true")
    p.add_argument("-n", "--dry-run", action="store_true")
    p = sub.add_parser("pull")
    p.add_argument("paths", nargs="*")
    p.add_argument("--all", action="store_true")
    p.add_argument("--history", action="store_true")
    p.add_argument("--dest")
    p = sub.add_parser("verify")
    p.add_argument("--deep", action="store_true")
    p = sub.add_parser("mv")
    p.add_argument("old")
    p.add_argument("new")
    p = sub.add_parser("rm")
    p.add_argument("path")
    p.add_argument("--force", action="store_true")
    sub.add_parser("check-staged")
    sub.add_parser("stub")
    args = ap.parse_args(argv)
    ctx = make_ctx(args.root, args.remote, args.open_remote)
    return {"status": cmd_status, "push": cmd_push, "pull": cmd_pull, "verify": cmd_verify, "mv": cmd_mv,
            "rm": cmd_rm, "check-staged": cmd_check_staged, "add": cmd_add, "stub": cmd_stub}[args.cmd](ctx, args)


if __name__ == "__main__":
    sys.exit(main())
