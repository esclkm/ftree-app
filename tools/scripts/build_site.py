#!/usr/bin/env python3
"""Переходник: прежняя команда сайта. Выгрузка — site_export.py (rodo site export), сборка из выгрузки —
web/scripts/site.mjs (rodo site build). Без ключей — выгрузка и сборка подряд, как раньше; --data — только data/*.json.
Скрипты, которые берут отсюда разбор биографий (import build_site as b), получают тот же модуль site_export."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
if __name__ == "__main__":
    import paths
    args = sys.argv[1:]
    subprocess.run([sys.executable, str(Path(__file__).with_name("site_export.py")), *args], check=True)
    if "--data" not in args:
        subprocess.run(["node", str(paths.WEB / "scripts" / "site.mjs"), "build", "--data", str(paths.SITE_EXPORT),
                        "--out", str(paths.SITE)], check=True)
else:
    import site_export
    sys.modules[__name__] = site_export
