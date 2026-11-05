#!/usr/bin/env python3
"""Одна обёртка для всех вызовов модели из скриптов проекта (навык orchestration, «claude -p налегке»).

Зачем: `claude -p`, запущенный из папки проекта, на старте каждого вызова читает CLAUDE.md, память и настройки —
47 тыс. токенов ещё до работы. Отсюда же, из пустой папки и без личных настроек, — около 600. Лимит подписки общий
с главной сессией, поэтому у конвейера свой дневной потолок и журнал.

Что делает обёртка:
  - запускает `claude -p` из пустой папки tools/.cache/llm/cwd: свой системный промпт, `--setting-sources ""`,
    без навыков, без MCP, без сохранения сессии; модель по задаче (по умолчанию haiku);
  - картинку даёт только через инструмент Read (`--tools Read`): копия кладётся в ту же пустую папку;
  - пишет каждый вызов в tools/.cache/llm/llm_calls.jsonl: дата, задача, модель, токены, длительность;
  - держит дневной потолок настоящих вызовов (LLM_DAILY_CAP, по умолчанию 200; ответ из кэша не считается)
    и при ответе «лимит исчерпан» останавливается — без повторов в цикле;
  - кэширует ответ по (сумма входа и картинки, системный промпт, модель): дважды одно не спрашиваем.

Второй путь — GitHub Copilot CLI (`copilot`, с 08.10.2026): модель с приставкой `copilot:` (`copilot:gemini-3.8-flash`,
`copilot:claude-sonnet-5.5`) идёт туда — свой лимит запросов GitHub, подписку Claude не тратит. Так же из пустой папки,
без инструментов (`--available-tools=`), без AGENTS.md и встроенных MCP; картинки — вложением (`--attachment`);
системный промпт — в начале текста (своего флага у copilot нет). Свой дневной потолок (LLM_COPILOT_CAP, по умолчанию
100); в журнал идёт и цена вызова по счёту GitHub (premium, nano_aiu).

    tools/py tools/scripts/llm.py status            # сегодня: вызовов / потолок, токены
    echo "Привет" | tools/py tools/scripts/llm.py ask --task test --system "Ответь одним словом"
    echo "Привет" | tools/py tools/scripts/llm.py ask --task test --system "…" --model copilot:gemini-3.8-flash

Из кода: `import llm; llm.ask("перевод", text, system=…)`; `llm.Limit` — потолок или лимит подписки.
"""
import argparse
import datetime as dt
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import paths  # noqa: E402
from paths import ROOT

CACHE = paths.CACHE / "llm"          # вне git (.gitignore: tools/.cache)
WORK = CACHE / "cwd"                               # пустая папка: claude -p не видит ни CLAUDE.md, ни .claude/
ANSWERS = CACHE / "answers"
LOG = CACHE / "llm_calls.jsonl"
DEFAULT_CAP = 200
COPILOT = "copilot:"                               # приставка модели: звать GitHub Copilot CLI, а не claude
DEFAULT_COPILOT_CAP = 100
LIMIT_WORDS = re.compile(r"usage limit|limit reached|rate limit|out of (?:extra )?usage|лимит", re.I)


class Limit(RuntimeError):
    """Дневной потолок конвейера или лимит подписки: дальше сегодня не звать."""


def cli() -> str | None:
    """Программа claude: из PATH (LLM_CLI — подменить), иначе встроенная в приложение Claude (новейшая версия)."""
    if paths.setting("LLM_CLI"):                    # переменная или ~/.config/ftree/env
        return paths.setting("LLM_CLI")
    if found := shutil.which("claude"):
        return found
    base = os.path.expanduser("~/Library/Application Support/Claude/claude-code")
    apps = glob.glob(f"{base}/*/claude.app/Contents/MacOS/claude") + \
        glob.glob(f"{base}/*/*/claude.app/Contents/MacOS/claude")   # с 2.1.28x — ещё папка-хэш внутри версии
    version = lambda p: [int(x) for x in re.findall(r"/claude-code/([\d.]+)/", p)[0].split(".")]
    return max(apps, key=version) if apps else None


def copilot_cli() -> str | None:
    """Программа copilot (GitHub Copilot CLI): LLM_COPILOT_CLI — подменить, иначе из PATH."""
    return paths.setting("LLM_COPILOT_CLI") or shutil.which("copilot")


def is_copilot(model: str) -> bool:
    return model.startswith(COPILOT)


def cap(copilot: bool = False) -> int:
    if copilot:
        return int(os.environ.get("LLM_COPILOT_CAP") or DEFAULT_COPILOT_CAP)
    return int(os.environ.get("LLM_DAILY_CAP") or DEFAULT_CAP)


def today() -> str:
    return dt.datetime.now().astimezone().date().isoformat()


def calls_today() -> list[dict]:
    if not LOG.exists():
        return []
    rows = (json.loads(line) for line in LOG.read_text(encoding="utf-8").splitlines() if line.strip())
    return [r for r in rows if r.get("day") == today()]


def used_today(copilot: bool = False) -> int:
    """Настоящих вызовов сегодня (из кэша — не считаются); у Claude и у Copilot счёт свой."""
    return sum(1 for r in calls_today() if not r.get("cached") and is_copilot(r.get("model", "")) == copilot)


def log(row: dict) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as file:
        file.write(json.dumps({"day": today(), "at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                               **row}, ensure_ascii=False) + "\n")


def key(prompt: str, system: str, model: str, image: Path | list[Path] | None) -> str:
    images = image if isinstance(image, list) else [image] if image else []
    digest = [hashlib.sha256(p.read_bytes()).hexdigest() for p in images]
    parts = [hashlib.sha256(prompt.encode()).hexdigest(), system, model,
             (digest[0] if len(digest) == 1 else digest) if digest else None]
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


def ask(task: str, prompt: str, system: str, model: str = "haiku", image: Path | str | list | None = None,
        cache: bool = True, timeout: int = 1800) -> str:
    """Ответ модели на prompt (текст на вход), с системным промптом; image — путь к картинке, список путей (несколько
    картинок за один вызов: служебное начало вызова ≈16 тыс. токенов делится на все) или None."""
    if isinstance(image, (list, tuple)):
        image = [Path(p) for p in image] if len(image) > 1 else (Path(image[0]) if image else None)
    else:
        image = Path(image) if image else None
    k = key(prompt, system, model, image)
    saved = ANSWERS / f"{k}.json"
    if cache and saved.exists():
        log({"task": task, "model": model, "cached": True, "key": k})
        return json.loads(saved.read_text(encoding="utf-8"))["result"]
    if is_copilot(model):
        if used_today(True) >= cap(True):
            raise Limit(f"потолок Copilot: {used_today(True)} вызовов сегодня из {cap(True)} (LLM_COPILOT_CAP) — "
                        "продолжить завтра")
        text = ask_copilot(task, prompt, system, model, image, k, timeout)
        ANSWERS.mkdir(parents=True, exist_ok=True)
        saved.write_text(json.dumps({"task": task, "model": model, "result": text}, ensure_ascii=False),
                         encoding="utf-8")
        return text
    if used_today() >= cap():
        raise Limit(f"потолок конвейера: {used_today()} вызовов сегодня из {cap()} (LLM_DAILY_CAP) — продолжить завтра")
    program = cli()
    if not program:
        raise RuntimeError("нет программы claude (Claude Code): поставить приложение Claude или LLM_CLI=<путь>")
    WORK.mkdir(parents=True, exist_ok=True)
    cmd = [program, "-p", "--model", model, "--system-prompt", system, "--setting-sources", "",
           "--disable-slash-commands", "--strict-mcp-config", "--no-session-persistence", "--output-format", "json"]
    with tempfile.TemporaryDirectory(dir=WORK) as folder:
        if isinstance(image, list):
            copies = []
            for i, img in enumerate(image, 1):
                copies.append(Path(folder) / f"image{i}{img.suffix.lower()}")
                shutil.copyfile(img, copies[-1])
            cmd += ["--tools", "Read", "--allowedTools", "Read"]
            listing = "\n".join(f"{i}. {c}" for i, c in enumerate(copies, 1))
            prompt = (f"Картинки ({len(copies)}), прочитай каждую инструментом Read по полному пути, по порядку:\n"
                      f"{listing}\n\n{prompt}")
        elif image:
            copy = Path(folder) / f"image{image.suffix.lower()}"
            shutil.copyfile(image, copy)
            cmd += ["--tools", "Read", "--allowedTools", "Read"]
            prompt = f"Картинка: {copy} (прочитай её инструментом Read по этому полному пути).\n\n{prompt}"
        else:
            cmd += ["--tools", ""]
        started = time.monotonic()
        result = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=WORK)
    seconds = round(time.monotonic() - started, 1)
    try:
        reply = json.loads(result.stdout)
    except json.JSONDecodeError:
        reply = {"is_error": True, "result": (result.stderr or result.stdout).strip()[:500]}
    usage = reply.get("usage") or {}
    text = str(reply.get("result") or "")
    failed = bool(result.returncode or reply.get("is_error"))
    log({"task": task, "model": model, "cached": False, "key": k, "ok": not failed, "seconds": seconds,
         "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
         "cache_read_tokens": usage.get("cache_read_input_tokens"),
         "cache_write_tokens": usage.get("cache_creation_input_tokens"),
         **({"error": text[:300]} if failed else {})})
    if failed:
        if LIMIT_WORDS.search(text):
            raise Limit(f"лимит подписки: {text[:200]} — не повторять, продолжить после сброса")
        raise RuntimeError(f"claude -p: {text[:500]}")
    ANSWERS.mkdir(parents=True, exist_ok=True)
    saved.write_text(json.dumps({"task": task, "model": model, "result": text}, ensure_ascii=False), encoding="utf-8")
    return text


def ask_copilot(task: str, prompt: str, system: str, model: str, image: Path | list[Path] | None, k: str,
                timeout: int) -> str:
    """Один вызов `copilot` налегке: пустая папка, без инструментов, картинки вложением; ответ — последнее сообщение."""
    program = copilot_cli()
    if not program:
        raise RuntimeError("нет программы copilot (GitHub Copilot CLI): npm i -g @github/copilot, потом copilot login")
    WORK.mkdir(parents=True, exist_ok=True)
    images = image if isinstance(image, list) else [image] if image else []
    with tempfile.TemporaryDirectory(dir=WORK) as folder:
        usage_file = Path(folder) / "usage.json"
        cmd = [program, "--model", model[len(COPILOT):], "--available-tools=", "--no-custom-instructions",
               "--disable-builtin-mcps", "--no-ask-user", "--output-format", "json",
               "--usage-output-file", str(usage_file)]
        for i, img in enumerate(images, 1):
            copy = Path(folder) / f"image{i}{img.suffix.lower()}"
            shutil.copyfile(img, copy)
            cmd += ["--attachment", str(copy)]
        text_in = f"<instructions>\n{system}\n</instructions>\n\n{prompt}"
        started = time.monotonic()
        result = subprocess.run(cmd, input=text_in, capture_output=True, text=True, timeout=timeout, cwd=folder)
        seconds = round(time.monotonic() - started, 1)
        usage = json.loads(usage_file.read_text(encoding="utf-8")) if usage_file.exists() else {}
    messages, code = [], result.returncode
    for line in result.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "assistant.message" and (event.get("data") or {}).get("content"):
            messages.append(event["data"]["content"])
        elif event.get("type") == "result":
            code = code or event.get("exitCode") or 0
    text = messages[-1] if messages else ""
    failed = bool(code or not text)
    if failed:
        # ошибка сессии (например, 402 quota_exceeded) приходит строкой session.error — её и показываем
        errors = [line for line in result.stdout.splitlines() if '"session.error"' in line]
        text = text or (errors[-1] if errors else (result.stderr or result.stdout).strip()[-500:])
    tokens = usage.get("tokenDetails") or {}
    log({"task": task, "model": model, "cached": False, "key": k, "ok": not failed, "seconds": seconds,
         "input_tokens": (tokens.get("input") or {}).get("tokenCount"),
         "output_tokens": (tokens.get("output") or {}).get("tokenCount"),
         "premium": usage.get("totalPremiumRequestCost"), "nano_aiu": usage.get("totalNanoAiu"),
         **({"error": text[:300]} if failed else {})})
    if failed:
        if LIMIT_WORDS.search(text) or re.search(r"quota|premium request", text, re.I):
            raise Limit(f"лимит Copilot: {text[:200]} — не повторять, продолжить после сброса")
        raise RuntimeError(f"copilot: {text[:500]}")
    return text


def status() -> None:
    rows = calls_today()
    real = [r for r in rows if not r.get("cached")]
    claude = [r for r in real if not is_copilot(r.get("model", ""))]
    tokens = lambda name: sum(r.get(name) or 0 for r in claude)
    print(f"LLM сегодня: вызовов {len(claude)} из {cap()} (из кэша ещё {len(rows) - len(real)}); "
          f"токенов: вход {tokens('input_tokens')}, кэш {tokens('cache_read_tokens') + tokens('cache_write_tokens')}, "
          f"выход {tokens('output_tokens')}; программа: {cli() or 'нет'}")
    gh = [r for r in real if is_copilot(r.get("model", ""))]
    print(f"Copilot сегодня: вызовов {len(gh)} из {cap(True)}; цена по счёту GitHub (premium): "
          f"{sum(r.get('premium') or 0 for r in gh)}; программа: {copilot_cli() or 'нет'}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    p = sub.add_parser("ask")
    p.add_argument("--task", required=True)
    p.add_argument("--system", required=True)
    p.add_argument("--model", default="haiku", help="haiku | sonnet | copilot:<модель copilot> (свой лимит GitHub)")
    p.add_argument("--image")
    p.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()
    if args.command == "status":
        status()
        return 0
    try:
        print(ask(args.task, sys.stdin.read(), args.system, args.model, args.image, cache=not args.no_cache))
    except Limit as exc:
        print(f"СТОП: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
