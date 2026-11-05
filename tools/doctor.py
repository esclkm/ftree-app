#!/usr/bin/env python3
"""Переходник: проверка установки теперь — `rodo setup --check` (tools/scripts/setup.py, описание — setup/setup.toml).

  tools/py tools/doctor.py            = rodo setup --check
  tools/py tools/doctor.py --short    = rodo setup --short
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
import setup  # noqa: E402

if __name__ == "__main__":
    sys.exit(setup.main(["--short"] if "--short" in sys.argv else ["--check"]))
