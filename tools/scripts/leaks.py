#!/usr/bin/env python3
"""Пароли, ключи и токены в будущем ftree-app — проверка программой gitleaks (ставится `brew install gitleaks`).

Сторож личного (scan_personal.py) ищет людей семьи; gitleaks — секреты: ключи API, токены, пароли, закрытые ключи.
Смотрит ровно то, что войдёт в приложение (список tools/APP_MANIFEST, `rodo app-files`): файлы копируются во временную
папку, и gitleaks проверяет её. Найденное печатается без самого секрета (--redact).

  rodo leaks              проверить файлы приложения (код выхода 1 — что-то нашлось, 2 — нет gitleaks)
  rodo leaks staged       то же для подготовленного к коммиту (хук pre-commit клона ftree-app)
  rodo leaks range A..B   то же для коммитов A..B (хук pre-push клона ftree-app; одно B — вся история до B)

Ложная тревога (пример ключа в тесте) — строка `gitleaks:allow` в комментарии на той же строке; не прятать настоящее.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

FLAGS = ["--redact", "--no-banner", "--exit-code", "1", "--log-level", "warn", "-v"]


def gitleaks() -> str:
    exe = shutil.which("gitleaks")
    if not exe:
        print("⛔ Нет программы gitleaks — проверка на пароли и ключи не сделана. Поставить: brew install gitleaks")
        sys.exit(2)
    return exe


def run(args: list[str], cwd: Path | None = None) -> int:
    code = subprocess.run([gitleaks(), *args, *FLAGS], cwd=cwd).returncode
    print("🔑 Паролей и ключей не найдено." if code == 0 else "⛔ gitleaks нашёл секрет — убрать до коммита "
          "(ключ — отозвать: раз он был в файле, считать его известным).")
    return code


def cmd_app() -> int:
    import app_files
    with tempfile.TemporaryDirectory(prefix="ftree-app-leaks-") as tmp:
        for rel in app_files.files():
            dst = Path(tmp) / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(paths.APP / rel, dst)
        return run(["dir", tmp])


def main(argv: list[str]) -> int:
    mode = argv[0] if argv else "app"
    if mode == "app":
        return cmd_app()
    if mode == "staged":
        return run(["git", "--pre-commit", "--staged", "."])
    if mode == "range" and len(argv) > 1:
        return run(["git", f"--log-opts={argv[1]}", "."])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
