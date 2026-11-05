#!/usr/bin/env python3
"""Настройщик рабочего места: проверить и собрать всё, что нужно дереву на этом Mac, по описанию в данных.

Что это. Дерево живёт в двух частях: данные (карточки, источники) и приложение (скрипты, сайт). Чтобы с ними работать,
на Mac нужны программы, окружения Python и Node, файл путей `~/.config/ftree/env`, хуки git, входы на сайты, облако.
Что именно включено и куда класть — описано в данных, в `setup/setup.toml`. Этот скрипт проходит по списку пунктов:

  ✅  есть и верно                                  — ничего не делает;
  🛠  нет, но можно сделать самому                  — делает и пишет, что сделал (папки, env, хуки, .venv, npm ci…);
  👤  нужен человек (вход, пароль, ключ хостинга)   — печатает точную команду; сам не делает;
  ⚠️  расходится с setup.toml                       — показывает разницу, правит после «да»;
  📦  тяжёлое (модели на гигабайты)                 — ставит только после «да».

Повторный запуск ничего не меняет, если всё на месте.

  rodo setup                     пройти и сделать, что можно (спросит «да» на расхождения и тяжёлое)
  rodo setup --check             только проверить, ничего не менять (прежний doctor.py)
  rodo setup --short             одна строка для сводки при старте сессии: без сети и тяжёлых проверок
  rodo setup --non-interactive   ничего не спрашивать: делать то, что без выбора, остальное — показать командой
  rodo setup --yes               на все вопросы — «да» (расхождения и тяжёлое тоже)

Две группы, как раньше: «основное» нужно каждый день (проверки, сайт, медиа, коммиты) — его нехватка даёт код выхода 1;
«по задаче» — то, что ставят, когда понадобится. Пароли и входы вводит человек сам; скрипт их не читает и не печатает —
только проверяет, что запись есть. Запускается любым Python 3.11+ (только стандартная библиотека).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent))
import destinations  # noqa: E402 — где хранить медиа и куда выкладывать (ftree.toml дерева)
import paths  # noqa: E402 — пути и настройки (только stdlib)

HOME = Path.home()
SETUP_TOML = "setup/setup.toml"
MAIN, TASK = "основное", "по задаче"

FEATURES = {  # что можно включить в [features] и значение по умолчанию
    "telegram": True, "myheritage": True, "familysearch": True, "chrome": True,
    "asr": False, "photo_restore": False, "image_model": False, "llm": True,
}
# Где хранить медиа и куда выкладывать сайт — не здесь, а в ftree.toml дерева ([storage.*], [[site.target]],
# destinations.py): настройщик проверяет ровно то, что там задано.
PLACES = {"archives": "ARCHIVES_LOCAL", "cache": "FTREE_CACHE", "site_out": "FTREE_SITE_OUT"}  # [places] → имя в env
KEYCHAIN = {"rclone_config": "rclone-config", "crypt_password": "rclone-crypt-password",
            "crypt_salt": "rclone-crypt-salt"}
ENV_HEADER = ("# Пути этого Mac для дерева. Пишет `rodo setup` по setup/setup.toml данных; свои строки можно дописывать —\n"
              "# настройщик меняет только свои имена (FTREE_ROOT, FTREE_APP и папки из [places]).\n")


class SetupError(Exception):
    """setup.toml не читается или в нём ошибка — текст для человека."""


# ── Разбор setup.toml ─────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class Config:
    data: Path                    # папка данных (где лежит setup/)
    mode: str                     # "dev" — приложение папкой на диске; "version" — репозиторий и тег
    app_dir: Path                 # где приложение на этом Mac
    repo: str = ""
    tag: str = ""
    places: dict | None = None    # имя в env → путь
    features: dict | None = None
    keychain: dict | None = None
    keychain_named: frozenset = frozenset()   # какие записи Связки ключей названы в setup.toml явно
    version: str = ""             # с какой версией приложения работает дерево ([app] version)

    def on(self, name: str):
        return (self.features or {}).get(name)


def _expand(value: str, base: Path) -> Path:
    p = Path(os.path.expandvars(str(value))).expanduser()
    return (p if p.is_absolute() else base / p).resolve()


def parse_config(text: str, data: Path) -> Config:
    """Разобрать текст setup.toml. Ошибка — SetupError с понятным текстом."""
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise SetupError(f"{SETUP_TOML}: не читается как TOML — {e}") from None
    unknown = set(raw) - {"app", "places", "features", "keychain"}
    if unknown:
        raise SetupError(f"{SETUP_TOML}: незнакомые разделы {', '.join(sorted(unknown))}")

    app = raw.get("app") or {}
    if "path" in app and ("repo" in app or "tag" in app):
        raise SetupError(f"{SETUP_TOML} [app]: или path (разработка), или repo + tag + dir (версия) — не всё сразу")
    if "path" in app:
        cfg = Config(data, "dev", _expand(app["path"], data))
    elif app.get("repo") and app.get("tag"):
        if not app.get("dir"):
            raise SetupError(f"{SETUP_TOML} [app]: в режиме «версия» нужен dir — куда положить приложение на этом Mac")
        cfg = Config(data, "version", _expand(app["dir"], data), repo=str(app["repo"]), tag=str(app["tag"]))
    else:
        raise SetupError(f"{SETUP_TOML} [app]: нужен path = \"…\" (разработка) или repo, tag и dir (версия)")

    cfg.version = str(app.get("version") or "")
    places = raw.get("places") or {}
    bad = set(places) - set(PLACES)
    if bad:
        raise SetupError(f"{SETUP_TOML} [places]: незнакомые {', '.join(sorted(bad))}; можно: {', '.join(PLACES)}")
    cfg.places = {PLACES[k]: str(_expand(v, data)) for k, v in places.items() if str(v).strip()}

    feats = raw.get("features") or {}
    bad = set(feats) - set(FEATURES)
    if bad:
        raise SetupError(f"{SETUP_TOML} [features]: незнакомые {', '.join(sorted(bad))}; можно: {', '.join(FEATURES)}")
    cfg.features = {**FEATURES, **feats}
    for k, v in cfg.features.items():
        if not isinstance(v, bool):
            raise SetupError(f"{SETUP_TOML} [features] {k}: true или false")
    cfg.keychain = {**KEYCHAIN, **(raw.get("keychain") or {})}
    cfg.keychain_named = frozenset(raw.get("keychain") or {})
    return cfg


def load_config(data: Path) -> Config:
    f = data / SETUP_TOML
    if not f.is_file():
        raise SetupError(f"нет {f} — описания, что ставить. Образец — в приложении (rodo init) или INSTALL.md")
    return parse_config(f.read_text(encoding="utf-8"), data)


# ── ~/.config/ftree/env ───────────────────────────────────────────────────────────────────────────────────────────────

def desired_env(cfg: Config) -> dict[str, str]:
    """Что настройщик хочет видеть в env: папка данных, приложение (если оно не внутри данных), папки из [places]."""
    out = {paths.ROOT_ENV: str(cfg.data)}
    if cfg.app_dir.resolve() != cfg.data.resolve():
        out["FTREE_APP"] = str(cfg.app_dir)
    out.update(cfg.places or {})
    return out


def env_diff(current: dict[str, str], want: dict[str, str]) -> tuple[dict, dict]:
    """(чего нет, что расходится: имя → (было, надо)). Пути сравниваются после раскрытия `~`."""
    norm = lambda v: str(Path(os.path.expandvars(v)).expanduser())  # noqa: E731
    missing = {k: v for k, v in want.items() if k not in current}
    differ = {k: (current[k], v) for k, v in want.items() if k in current and norm(current[k]) != norm(v)}
    return missing, differ


def merge_env(text: str, want: dict[str, str]) -> str:
    """Новый текст env: свои имена — на месте (значение заменено), недостающие — в конец, чужие строки не трогаем."""
    lines, seen = (text.splitlines() if text else ENV_HEADER.splitlines()), set()
    for i, line in enumerate(lines):
        key = line.strip().removeprefix("export ").partition("=")[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and key in want:
            lines[i] = f"{key}={want[key]}"
            seen.add(key)
    lines += [f"{k}={v}" for k, v in want.items() if k not in seen]
    return "\n".join(lines).rstrip("\n") + "\n"


# ── Пункты ────────────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class Item:
    group: str
    what: str
    ok: bool
    kind: str = "human"           # human | self | diff | heavy — что делать, если не ok
    how: str = ""                 # команда или шаг для человека (или что сделает сам)
    fix: Callable[[], bool] | None = None
    diff: str = ""


def sh(*cmd, cwd=None, timeout=120) -> tuple[int, str]:
    try:
        r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, timeout=timeout,
                           cwd=cwd or paths.ROOT)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)


def run_visible(*cmd, cwd=None) -> bool:
    """Команда с выводом на экран (долгие: uv sync, npm ci, установка моделей)."""
    print(f"     $ {' '.join(map(str, cmd))}", flush=True)
    try:
        return subprocess.run([str(c) for c in cmd], cwd=cwd or paths.ROOT).returncode == 0
    except OSError as e:
        print(f"     не запустилось: {e}")
        return False


def imports(py: Path, mods: str) -> bool:
    return py.exists() and sh(py, "-c", f"import {mods}", timeout=180)[0] == 0


def node_major() -> int | None:
    if not shutil.which("node"):
        return None
    m = re.match(r"v(\d+)", sh("node", "-v")[1])
    return int(m.group(1)) if m else None


def keychain_has(service: str) -> bool:
    """Есть ли запись в Связке ключей — без чтения самого пароля."""
    return sh("security", "find-generic-password", "-s", service)[0] == 0


def file_has_key(path: Path, key: str) -> bool:
    """Есть ли в файле настроек строка с этим именем — значение не читаем и не печатаем."""
    try:
        return re.search(rf"^\s*{re.escape(key)}\s*=", path.read_text(encoding="utf-8"), re.M) is not None
    except OSError:
        return False


def cookies_for(profile: Path, domain: str) -> bool:
    """Был ли вход на сайт в Chrome проекта: есть ли его cookie в профиле (копия базы; значения не читаем)."""
    db = profile / "Default" / "Cookies"
    if not db.is_file():
        return False
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "c.sqlite"
        shutil.copyfile(db, copy)
        try:
            with sqlite3.connect(copy) as con:
                n = con.execute("SELECT count(*) FROM cookies WHERE host_key LIKE ?", (f"%{domain}",)).fetchone()[0]
        except sqlite3.Error:
            return False
    return n > 0


def tree_config(data: Path) -> tuple[dict, str]:
    """ftree.toml этой папки данных (не обязательно дерева, в котором стоим) → (настройки, ошибка или "")."""
    try:
        return tomllib.loads((data / paths.CONFIG_NAME).read_text(encoding="utf-8")), ""
    except (OSError, tomllib.TOMLDecodeError) as e:
        return {}, f"{paths.CONFIG_NAME} не читается — {e}"


def rclone_env(cfg: Config) -> dict:
    env = dict(os.environ)
    kc = cfg.keychain or KEYCHAIN
    if keychain_has(kc["rclone_config"]):
        env["RCLONE_PASSWORD_COMMAND"] = f"security find-generic-password -s {kc['rclone_config']} -w"
    return env


def rclone_remotes(cfg: Config) -> dict[str, str]:
    """remote rclone → вид (jottacloud, s3, crypt …); rclone нет или не ответил — {}."""
    try:
        out = subprocess.run(["rclone", "listremotes", "--long"], capture_output=True, text=True, env=rclone_env(cfg),
                             timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}
    return {p[0]: p[1] for p in (ln.split() for ln in out.splitlines()) if len(p) >= 2}


def storage_items(cfg: Config, stores: dict, full: bool) -> Iterator[Item]:
    """Хранилища медиа — ровно те, что заданы в ftree.toml ([storage.media], [storage.private])."""
    app = cfg.app_dir
    if not stores:
        yield Item(TASK, "медиа: хранилище не задано — копии фото и звука только на этом Mac "
                         "(ftree.toml, [storage.media] / [storage.private])", True)
        return
    kc = cfg.keychain or KEYCHAIN
    remotes = rclone_remotes(cfg) if shutil.which("rclone") else {}
    for st in stores.values():
        if st.kind == "local":
            folder = Path(st.address)
            yield Item(MAIN, f"медиа: папка {folder} ([storage.{st.name}])", folder.is_dir(), "self",
                       f"mkdir -p {folder}", make_dir(folder))
            continue
        name = st.address.split(":", 1)[0] + ":"
        if st.address.startswith(":"):  # строка подключения — проверять нечего, кроме ответа
            continue
        yield Item(MAIN, f"медиа: rclone видит {name} ([storage.{st.name}])", name in remotes,
                   how=f"rclone config — завести remote {name.rstrip(':')} (вход — человек); для Jottacloud — "
                       f"sh {app}/tools/setup/rclone_jotta.sh <имя>")
        if st.encrypted and name in remotes:
            yield Item(MAIN, f"медиа: {name} шифрует ([storage.{st.name}] encrypted = true)", remotes[name] == "crypt",
                       how=f"{name} — rclone вида {remotes[name]}: нужен вид crypt (rclone config) или encrypted = false")
        if full and name in remotes:
            ok = subprocess.run(["rclone", "lsf", "--max-depth", "1", st.address], capture_output=True,
                                env=rclone_env(cfg), timeout=180).returncode == 0
            yield Item(MAIN, f"медиа: {st.address} отвечает", ok,
                       how=f"rclone lsd {name}   затем rodo media status — посмотреть, что не так")
    if any(s.encrypted for s in stores.values()):  # пароли шифрования — только если дерево назвало их записи
        for key in ("crypt_password", "crypt_salt"):
            if key in cfg.keychain_named:
                yield Item(MAIN, f"медиа: пароль шифрования в Связке ключей ({kc[key]})", keychain_has(kc[key]),
                           how=f"security add-generic-password -U -a \"$USER\" -s {kc[key]} -w   "
                               "(вставить пароль из приложения «Пароли»; вводит человек)")
    if "rclone_config" in cfg.keychain_named:
        yield Item(MAIN, f"медиа: файл настроек rclone заперт ({kc['rclone_config']})", keychain_has(kc["rclone_config"]),
                   how="rclone config encryption set   (пароль — в Связку ключей под этим именем; человек)")


def site_items(cfg: Config, tree: dict) -> Iterator[Item]:
    """Выкладка сайта — ровно те цели, что заданы в ftree.toml ([[site.target]]): вход на их хостинг."""
    try:
        targets = destinations.site_targets(tree)
    except destinations.ConfigError as e:
        yield Item(MAIN, "сайт: цели выкладки в ftree.toml", False, how=str(e))
        return
    if not targets:
        yield Item(TASK, "сайт: целей выкладки нет — собирается только на этом Mac (ftree.toml, [[site.target]])", True)
        return
    kinds = {t["kind"] for t in targets}
    if kinds & {"cloudflare-pages", "cloudflare-worker"}:
        wr = HOME / "Library/Preferences/.wrangler/config/default.toml"
        yield Item(MAIN, "сайт: вход в Cloudflare (wrangler)", file_has_key(wr, "oauth_token"),
                   how="npx wrangler login   (вход — человек, в браузере)")
    if "netlify" in kinds:
        nl = HOME / "Library/Preferences/netlify/config.json"
        try:
            ok = bool(json.loads(nl.read_text(encoding="utf-8")).get("users"))
        except (OSError, ValueError):
            ok = False
        yield Item(MAIN, "сайт: вход в Netlify", ok, how="npx netlify-cli login   (вход — человек, в браузере)")
    for t in targets:
        if t["kind"] == "folder":
            yield Item(MAIN, f"сайт: папка {t['name']}", Path(t["name"]).parent.is_dir(),
                       how=f"создать папку {Path(t['name']).parent}")
    if any(t["role"] == "mirror" for t in targets):
        key = Path(os.environ.get("FTREE_PROXY_KEY_FILE")
                   or HOME / ".config" / "ftree" / destinations.tree_name(tree) / "proxy_key")
        yield Item(MAIN, f"сайт: секрет зеркала {key}", key.is_file(),
                   how=f"mkdir -p {key.parent} && openssl rand -hex 32 > {key}   и то же значение — секрет PROXY_KEY "
                       "основного сайта на хостинге (человек; навык setup)")


PLUGIN = "ftree@ftree-app"          # навыки-методы приложения: плагин Claude Code (.claude-plugin/ в приложении)
APP_RULES = "tools/CLAUDE.app.md"   # общие правила приложения: CLAUDE.md дерева подключает их строкой @<приложение>/…


def app_version(app: Path) -> str:
    try:
        return str(tomllib.loads((app / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"])
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return ""


def version_ok(need: str, have: str) -> bool:
    """Приложение не старее нужного и той же серии (до 1.0 — первые две цифры), как сверяет tools/rodo."""
    def key(v):
        return tuple(int(x) if x.isdigit() else 0 for x in v.split("."))
    series = (lambda v: key(v)[:2] if key(v)[:1] == (0,) else key(v)[:1])
    return bool(have) and key(have) >= key(need) and series(have) == series(need)


def tilde(p: Path) -> str:
    p = Path(p)
    return "~/" + p.relative_to(HOME).as_posix() if p.is_relative_to(HOME) else str(p)


def rules_line(app: Path) -> str:
    return f"@{tilde(app)}/{APP_RULES}"


def write_rules_line(claude_md: Path, line: str) -> bool:
    """В CLAUDE.md дерева — строка импорта правил приложения: старую (другой путь) заменить, нет — после заголовка."""
    text = claude_md.read_text(encoding="utf-8") if claude_md.exists() else "# Правила дерева\n"
    lines = text.splitlines()
    for i, x in enumerate(lines):
        if x.strip().startswith("@") and x.strip().endswith(APP_RULES):
            lines[i] = line
            break
    else:
        at = next((i + 1 for i, x in enumerate(lines) if x.startswith("# ")), 0)
        lines[at:at] = ["", "Общие правила приложения:", "", line]
    claude_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


MARKETPLACE = {"ftree-app": {"source": {"source": "github", "repo": "esclkm/ftree-app"}}}
def notes_allow(app: Path) -> list[str]:
    """Разрешения на строку подгрузки заметок в начале навыка: `<папка плагина>/tools/rodo skill-notes …` (плагин из
    папки приложения — путь известен) и запасной `rodo skill-notes …` из PATH."""
    return [f"Bash({app}/tools/rodo skill-notes:*)", "Bash(rodo skill-notes:*)"]


def plugin_declared(cs: Path, app: Path) -> bool:
    """Плагин включён, откуда брать — записано, и строка подгрузки заметок разрешена."""
    try:
        d = json.loads(cs.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    allow = (d.get("permissions") or {}).get("allow") or []
    return (bool((d.get("enabledPlugins") or {}).get(PLUGIN)) and "ftree-app" in (d.get("extraKnownMarketplaces") or {})
            and all(x in allow for x in notes_allow(app)))


def declare_plugin(cs: Path, app: Path) -> bool:
    """Дописать в .claude/settings.json дерева плагин и разрешение на вклейку заметок; остальное — как было."""
    try:
        d = json.loads(cs.read_text(encoding="utf-8")) if cs.exists() else {}
    except ValueError:
        return False
    d.setdefault("extraKnownMarketplaces", {}).update(MARKETPLACE)
    d.setdefault("enabledPlugins", {})[PLUGIN] = True
    allow = d.setdefault("permissions", {}).setdefault("allow", [])
    allow += [x for x in notes_allow(app) if x not in allow]
    cs.parent.mkdir(parents=True, exist_ok=True)
    cs.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def plugin_state(data: Path) -> tuple[bool | None, str]:
    """Стоит ли плагин навыков: (да/нет/не проверить, пояснение). Смотрит `claude plugin list` из папки данных."""
    if not shutil.which("claude"):
        return None, "нет программы claude в PATH"
    code, out = sh("claude", "plugin", "list", cwd=data, timeout=60)
    if code != 0:
        return None, f"claude plugin list не ответил: {out[:120]}"
    return PLUGIN in out or "ftree" in out.split(), ""


def make_dir(p: Path) -> Callable[[], bool]:
    def go():
        p.mkdir(parents=True, exist_ok=True)
        return True
    return go


def items(cfg: Config, full: bool) -> Iterator[Item]:
    """Пункты по порядку. Генератор: следующий проверяется после того, как починен предыдущий."""
    app, data = cfg.app_dir, cfg.data
    rodo = app / "tools" / "rodo"
    web = app / "web"

    # приложение
    if cfg.mode == "dev":
        yield Item(MAIN, f"приложение (разработка): {app}", (rodo).is_file(),
                   how=f"положить приложение в {app} (git clone …) или поправить [app] path в {SETUP_TOML}")
    else:
        have = (app / ".git").is_dir()
        yield Item(MAIN, f"приложение {cfg.tag}: {app}", have, "self",
                   f"git clone --branch {cfg.tag} {cfg.repo} {app}",
                   lambda: run_visible("git", "clone", "--branch", cfg.tag, cfg.repo, app, cwd=HOME))
        if have:
            _, at = sh("git", "describe", "--tags", "--exact-match", cwd=app)
            dirty = bool(sh("git", "status", "--porcelain", cwd=app)[1])
            if dirty and at != cfg.tag:
                yield Item(MAIN, f"приложение на {cfg.tag}", False,
                           how=f"в {app} есть несохранённые правки — сохранить или убрать, потом rodo setup")
            else:
                yield Item(MAIN, f"приложение на {cfg.tag}", at == cfg.tag, "diff",
                           f"git -C {app} fetch --tags && git -C {app} checkout {cfg.tag}",
                           lambda: run_visible("git", "-C", app, "fetch", "--tags") and
                           run_visible("git", "-C", app, "checkout", cfg.tag),
                           diff=f"сейчас: {at or 'не на теге'}, надо: {cfg.tag}")

    # файл путей
    env_file = paths.ENV_FILE
    want = desired_env(cfg)
    cur = paths._read_env_file(env_file)
    missing, differ = env_diff(cur, want)

    def write_env():
        env_file.parent.mkdir(parents=True, exist_ok=True)
        old = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
        env_file.write_text(merge_env(old, want), encoding="utf-8")
        return True
    names = ", ".join(want)
    if differ:
        yield Item(MAIN, f"файл путей {env_file}", False, "diff", f"переписать {', '.join(differ)}", write_env,
                   diff="; ".join(f"{k}: было {a}, надо {b}" for k, (a, b) in differ.items()))
    else:
        yield Item(MAIN, f"файл путей {env_file} ({names})", not missing, "self",
                   f"записать {', '.join(missing)}", write_env)

    # Python и программы
    yield Item(MAIN, "uv", shutil.which("uv"), how="brew install uv")
    venv = app / ".venv" / "bin" / "python"
    if not venv.exists():
        yield Item(MAIN, ".venv приложения", False, "self", "uv sync --frozen",
                   lambda: run_visible("uv", "sync", "--frozen", "--project", app) if shutil.which("uv") else False)
    elif full:
        yield Item(MAIN, ".venv: библиотеки (yaml, PIL, numpy, ged4py)", imports(venv, "yaml, PIL, numpy, ged4py"),
                   "self", "uv sync --frozen", lambda: run_visible("uv", "sync", "--frozen", "--project", app))
        if shutil.which("uv"):
            same = "Would make no changes" in sh("uv", "sync", "--frozen", "--dry-run", "--project", app, cwd=app)[1]
            yield Item(MAIN, ".venv совпадает с uv.lock", same, "self", "uv sync --frozen",
                       lambda: run_visible("uv", "sync", "--frozen", "--project", app))
    else:
        yield Item(MAIN, ".venv приложения", True)

    hooks = sh("git", "config", "core.hooksPath", cwd=data)[1]
    # хуки — в приложении; приложение внутри данных — путь от корня, отдельно — полный путь к его tools/githooks
    want = "tools/githooks" if Path(app).resolve() == Path(data).resolve() else str(Path(app) / "tools" / "githooks")
    yield Item(MAIN, f"хуки git — {want}", hooks == want, "self",
               f"git config core.hooksPath {want}",
               lambda: sh("git", "config", "core.hooksPath", want, cwd=data)[0] == 0)

    tree, problem = tree_config(data)
    try:
        stores = destinations.stores(tree)
    except destinations.ConfigError as e:
        stores, problem = {}, problem or str(e)
    progs = [("git", "git"), ("pdftotext", "poppler"), ("gitleaks", "gitleaks")] + ([("rclone", "rclone")] if stores else [])
    for prog, formula in progs:
        yield Item(MAIN, prog, shutil.which(prog), how=f"brew install {formula}")
    asr_home = paths.ASR_HOME
    yield Item(MAIN, "ffmpeg (сжатие звука для облака)", shutil.which("ffmpeg") or (asr_home / "bin/ffmpeg").exists(),
               how="brew install ffmpeg")
    nm = node_major()
    yield Item(MAIN, f"Node 24 (сейчас: {nm or 'нет'})", bool(nm and nm >= 24), how="brew install node@24 (или nvm install 24)")
    yield Item(MAIN, "web/node_modules", (web / "node_modules").is_dir(), "self", "cd web && npm ci",
               lambda: run_visible("npm", "ci", cwd=web) if shutil.which("npm") else False)

    link = HOME / ".local" / "bin" / "rodo"
    linked = link.is_symlink() and link.resolve() == rodo.resolve()
    if link.exists() and not linked:
        yield Item(MAIN, f"команда rodo — {link}", False, "diff", f"ln -sf {rodo} {link}",
                   lambda: sh("ln", "-sf", rodo, link)[0] == 0, diff=f"сейчас ведёт в {link.resolve()}, надо {rodo}")
    else:
        yield Item(MAIN, f"команда rodo — {link}", linked, "self", f"ln -sf {rodo} {link}",
                   lambda: make_dir(link.parent)() and sh("ln", "-sf", rodo, link)[0] == 0)
    if full:
        on_path = str(link.parent) in os.environ.get("PATH", "").split(":")
        yield Item(MAIN, "~/.local/bin в PATH", on_path,
                   how="добавить в ~/.zshrc строку  export PATH=\"$HOME/.local/bin:$PATH\"  и открыть новый терминал")

    # версия приложения — та, с которой работает дерево ([app] version; rodo предупреждает при каждом запуске)
    have = app_version(app)
    if cfg.version:
        yield Item(MAIN, f"версия приложения {have or '?'} — дереву нужна {cfg.version}", version_ok(cfg.version, have),
                   how=f"старее — обновить приложение (git -C {app} pull или тег v{cfg.version}); новее серии — "
                       f"прогнать rodo check и поднять [app] version в {SETUP_TOML}")

    # правила приложения в CLAUDE.md дерева: строка @<приложение>/tools/CLAUDE.app.md (путь — из [app] setup.toml)
    claude_md, line = data / "CLAUDE.md", rules_line(app)
    has = claude_md.exists() and line in claude_md.read_text(encoding="utf-8").splitlines()
    yield Item(MAIN, f"CLAUDE.md дерева подключает правила приложения ({line})", has, "self",
               f"вписать строку {line} в CLAUDE.md", lambda: write_rules_line(claude_md, line))

    # плагин навыков объявлен в .claude/settings.json дерева: откуда брать (GitHub) и что включить — для всех, кто
    # открывает это дерево в Claude Code; сам плагин ставит человек (ниже)
    cs = data / ".claude" / "settings.json"
    declared = plugin_declared(cs, app)
    yield Item(MAIN, f"плагин {PLUGIN} и разрешение на заметки — в .claude/settings.json дерева", declared, "self",
               f"вписать enabledPlugins и extraKnownMarketplaces в {cs}", lambda: declare_plugin(cs, app))

    # навыки Claude — плагин приложения; ставит человек (один раз на Mac), Claude спросит и разрешение на импорт выше
    state, why = plugin_state(data)
    if full or state is False:
        dev = f"; разработка — claude --plugin-dir {app} (навыки прямо из папки приложения)" if cfg.mode == "dev" else ""
        yield Item(TASK, f"навыки Claude: плагин {PLUGIN}" + (f" (не проверить: {why})" if state is None else ""),
                   bool(state), how=f"в папке данных: claude plugin install {PLUGIN} --scope project{dev}; потом в "
                                    "новой сессии Claude вызвать навык (например /ftree:archive-gaso) и увидеть заметки дерева")

    cache = paths.CACHE
    yield Item(MAIN, f"кэш: {cache}", cache.is_dir(), "self", f"mkdir -p {cache}", make_dir(cache))
    yield Item(MAIN, f"сырьё архивов: {paths.ARCHIVES_LOCAL}", paths.ARCHIVES_LOCAL.is_dir(), "self",
               f"mkdir -p {paths.ARCHIVES_LOCAL}", make_dir(paths.ARCHIVES_LOCAL))

    if problem:
        yield Item(MAIN, "ftree.toml: где хранить медиа и куда выкладывать сайт", False,
                   how=f"{problem} — поправить ftree.toml (навык setup)")
    yield from storage_items(cfg, stores, full)
    if not problem:
        yield from site_items(cfg, tree)

    # по задаче: Chrome проекта и входы
    profile = Path(os.environ.get("BROWSER_PROFILE") or paths.ARCHIVES_LOCAL / "browser-profile")
    if cfg.on("chrome") or cfg.on("myheritage") or cfg.on("familysearch"):
        yield Item(TASK, "Google Chrome", Path("/Applications/Google Chrome.app").exists(),
                   how="brew install --cask google-chrome")
        yield Item(TASK, f"Chrome проекта: профиль {profile}", profile.is_dir(),
                   how="rodo browser-cdp start   (откроет свой Chrome; профиль создастся сам)")
    for feat, domain, url in (("myheritage", "myheritage.com", "https://www.myheritage.com"),
                              ("familysearch", "familysearch.org", "https://www.familysearch.org")):
        if cfg.on(feat) and full and profile.is_dir():
            yield Item(TASK, f"вход на {domain} в Chrome проекта", cookies_for(profile, domain),
                       how=f"rodo browser-cdp start {url}   — войти в открывшемся окне (логин и пароль вводит человек; "
                           "отметить «запомнить меня»)")
    if cfg.on("telegram"):
        tg = paths.TELEGRAM_DIR
        yield Item(TASK, f"Телеграм: ключи приложения ({tg}/config.toml)", (tg / "config.toml").is_file(),
                   how=f"на my.telegram.org взять api_id и api_hash, записать в {tg}/config.toml (делает человек)")
        yield Item(TASK, "Телеграм: вход (файл сессии)", (tg / f"{paths.TELEGRAM_SESSION}.session").is_file(),
                   how="rodo tg-group login   (код из Телеграма вводит человек)")

    # по задаче: тяжёлое
    asr = f"bash {app}/tools/setup/asr.sh --models"
    if cfg.on("asr"):
        for env_name, mods in (("whisperenv", "mlx_whisper, resemblyzer, sklearn, soundfile"),
                               ("gigaenv", "gigaam, transformers, soundfile"), ("giga3env", "gigaam, soundfile")):
            py = asr_home / env_name / "bin/python"
            yield Item(TASK, f"звук: окружение {env_name}", imports(py, mods) if full else py.exists(), "heavy",
                       asr + "   (~9 ГБ)", lambda: run_visible("bash", app / "tools/setup/asr.sh", "--models"))
        hf = HOME / ".cache/huggingface/hub"
        models = ((hf / "models--mlx-community--whisper-large-v3-mlx").is_dir()
                  and all((HOME / ".cache/gigaam" / f).exists() for f in ("v2_rnnt.ckpt", "v2_ctc.ckpt", "v3_e2e_rnnt.ckpt"))
                  and (asr_home / "models/wav2vec2-xlsr-53-spanish/model.safetensors").exists())
        yield Item(TASK, "звук: модели Whisper, GigaAM v2/v3, испанская wav2vec2", models, "heavy", asr + "   (~4 ГБ)",
                   lambda: run_visible("bash", app / "tools/setup/asr.sh", "--models"))
    if cfg.on("photo_restore"):
        py = paths.PHOTO_VENV / "bin/python"
        pm, w = paths.PHOTO_MODELS, paths.AI_WEIGHTS
        ready = (imports(py, "gfpgan, realesrgan, cv2, codeformer") if full else py.exists()) and all(p.exists() for p in (
            pm / "GFPGANv1.4.pth", pm / "RealESRGAN_x2plus.pth", w / "CodeFormer/weights/CodeFormer/codeformer.pth",
            w / "gfpgan/weights/detection_Resnet50_Final.pth"))
        yield Item(TASK, "фото: окружение и веса реставрации", ready, "heavy",
                   f"bash {app}/tools/setup/photo.sh   (~2,5 ГБ)", lambda: run_visible("bash", app / "tools/setup/photo.sh"))
    if cfg.on("image_model"):
        yield Item(TASK, "ollama", shutil.which("ollama"), how="brew install ollama")
        manifest = HOME / ".ollama/models/manifests/registry.ollama.ai/library/qwen3-vl/8b-instruct"
        yield Item(TASK, "ollama: модель qwen3-vl:8b-instruct", manifest.exists(), "heavy",
                   "ollama serve &  затем  ollama pull qwen3-vl:8b-instruct   (~6 ГБ)",
                   lambda: bool(shutil.which("ollama")) and run_visible("ollama", "pull", "qwen3-vl:8b-instruct"))
    if cfg.on("llm"):
        import llm  # noqa: E402 — где программа claude (LLM_CLI, PATH или приложение Claude)
        yield Item(TASK, "claude -p для конвейера (llm.py)", llm.cli(),
                   how="поставить приложение Claude (Code) или записать LLM_CLI=<путь к claude> в env")
        yield Item(TASK, "copilot для конвейера (llm.py --model copilot:…)",
                   paths.setting("LLM_COPILOT_CLI") or shutil.which("copilot"),
                   how="npm install -g @github/copilot   затем  copilot  и войти (вход — человек)")

    # сырьё ГАСО — только сведения: скачивать заново — работа, не установка
    gaso = paths.GASO_RAW
    cases = [d for d in gaso.glob("ф48_оп*_д*") if d.is_dir()] if gaso.is_dir() else []
    books = list((paths.ARCHIVES_CATALOG / "gaso").glob("*.book.json"))
    if books:
        yield Item(TASK, f"сырьё ГАСО: {len(cases)} дел из {len(books)} в каталоге", len(cases) >= len(books),
                   how=f"скопировать в {paths.ARCHIVES_LOCAL}/raw/gaso/ с другого Mac или из старой копии; иначе "
                       "скачать — навык archive-gaso")


# ── Проход ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def ask(question: str, args) -> bool:
    if args.yes:
        return True
    if args.non_interactive or args.check or not sys.stdin.isatty():
        return False
    try:
        return input(f"     {question} [y/N] ").strip().lower() in ("y", "yes", "д", "да")
    except EOFError:
        return False


def off_features(cfg: Config) -> list[str]:
    return [k for k, v in (cfg.features or {}).items() if v in (False, [])]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Настройщик рабочего места дерева (setup/setup.toml)")
    ap.add_argument("--check", action="store_true", help="только проверить, ничего не менять")
    ap.add_argument("--short", action="store_true", help="одна строка для сводки при старте сессии")
    ap.add_argument("--non-interactive", action="store_true", help="ничего не спрашивать")
    ap.add_argument("--yes", action="store_true", help="на все вопросы — да")
    ap.add_argument("--data", help="папка данных (по умолчанию — корень дерева)")
    args = ap.parse_args(argv)
    data = Path(args.data).expanduser().resolve() if args.data else paths.ROOT
    try:
        cfg = load_config(data)
    except SetupError as e:
        print(f"Установка: {e}" if args.short else f"❌ {e}")
        return 1

    if args.short:
        res = list(items(cfg, full=False))
        bad = [r for r in res if not r.ok]
        bad_main = [r for r in bad if r.group == MAIN]
        if not bad_main:
            note = f"; по задаче нет: {len(bad)}" if bad else ""
            print(f"Установка: всё на месте{note} (rodo setup --check)")
        else:
            print("Установка: не хватает — " + "; ".join(f"{r.what} → {r.how}" for r in bad_main))
        return 1 if bad_main else 0

    mode = "только проверка" if args.check else "проверка и установка"
    print(f"Настройщик ({mode}): данные {cfg.data}, приложение {cfg.app_dir} "
          f"({'разработка' if cfg.mode == 'dev' else 'версия ' + cfg.tag})")
    group, done, left = None, [], []
    for it in items(cfg, full=True):
        if it.group != group:
            group = it.group
            print(f"\n{group.capitalize()}:")
        if it.ok:
            print(f"  ✅ {it.what}")
            continue
        if args.check:
            mark = {"self": "🛠", "diff": "⚠️", "heavy": "📦"}.get(it.kind, "👤")
            tail = {"self": "сделает сам: rodo setup", "diff": "расходится с setup.toml — rodo setup (спросит)",
                    "heavy": "тяжёлое — rodo setup (спросит)"}.get(it.kind, "")
            print(f"  ❌ {it.what}" + (f"\n       {it.diff}" if it.diff else "")
                  + f"\n       {mark} {it.how}" + (f"   [{tail}]" if tail else ""))
            left.append(it)
            continue
        go = it.kind == "self"
        if it.kind in ("diff", "heavy"):
            print(f"  ⚠️ {it.what}" + (f" — {it.diff}" if it.diff else ""))
            go = ask(f"{'поставить' if it.kind == 'heavy' else 'поправить'}: {it.how}?", args)
        if go:
            ok = bool(it.fix and it.fix())
            print(f"  {'🛠 сделано' if ok else '❌ не вышло'}: {it.what} ({it.how})")
            (done if ok else left).append(it)
        else:
            print(f"  ❌ {it.what}\n       {'👤' if it.kind == 'human' else '⏭ не сейчас —'} {it.how}")
            left.append(it)
    off = off_features(cfg)
    if off:
        print(f"\nВыключено в {SETUP_TOML}: {', '.join(off)}")
    left_main = [i for i in left if i.group == MAIN]
    print(f"\nИтог: сделано сейчас {len(done)}, осталось {len(left)} (из них основного {len(left_main)})")
    if left:
        print("Что осталось, по порядку:\n" + "\n".join(f"  {h}" for h in dict.fromkeys(i.how for i in left)))
    return 1 if left_main else 0


if __name__ == "__main__":
    sys.exit(main())
