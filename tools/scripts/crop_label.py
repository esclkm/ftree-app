"""Где искать оригинал вырезки — строкой в указателе папки, а не на картинке (просьба Павла, 13.10.2026).

Вырезку пересылают и смотрят через месяц, а по имени «д210_разв101» не понять, какой это архив и фонд. Скрипт пишет в
`00_ГДЕ_ИСКАТЬ.md` той же папки строку: файл вырезки — что на ней — архив, фонд, опись, дело, разворот (номер файла
скана), путь к скану на этом Mac, адрес на сервере архива. Повторный запуск для того же файла заменяет его строку.

  tools/py tools/scripts/crop_label.py <вырезка.jpg> [<ещё.jpg> …] --fond 10 --opis 3 --delo 210 --spread 101 \
      [--what "Вербичи, двор 4 — Прокоп Ясенев"]

Путь и адрес берутся из манифеста скачанного дела (`$ARCHIVES_LOCAL/raw/gaso/ф<ф>_оп<о>_д<д>/manifest.jsonl`).
Для PDF родным (`metric_pdf.py`) те же реквизиты — функция `reference()`.
"""
import argparse
import json
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import paths  # noqa: E402

ARCH = {"gaso": "ГАСО (Государственный архив Смоленской области, portal.gaso-smolensk.ru)"}
INDEX = "00_ГДЕ_ИСКАТЬ.md"


def server_url(fond: str, opis: str, delo: str, spread: int) -> tuple[str, str]:
    """(файл на этом Mac, адрес на сервере) — по манифесту скачанного дела."""
    folder = Path(paths.GASO_RAW) / f"ф{fond}_оп{opis}_д{delo}"
    local = next(iter(sorted(folder.glob(f"*_{spread:03d}.jpg"))), None)
    url = ""
    man = folder / "manifest.jsonl"
    if man.exists():
        for line in man.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec.get("n") == spread and rec.get("status") == 200:
                url = urllib.parse.unquote(rec["url"])
    return (str(local).replace(str(Path.home()), "~") if local else "нет на этом Mac"), url


def reference(arch: str, fond: str, opis: str, delo: str, spread: int) -> str:
    local, url = server_url(fond, opis, delo, spread)
    ref = f"{ARCH[arch]}, ф. {fond}, оп. {opis}, д. {delo}, разворот (файл скана) {spread}; скан: `{local}`"
    return ref + (f"; на сервере: {url}" if url else "")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("crops", nargs="+", type=Path)
    ap.add_argument("--arch", default="gaso", choices=ARCH)
    ap.add_argument("--fond", required=True)
    ap.add_argument("--opis", required=True)
    ap.add_argument("--delo", required=True)
    ap.add_argument("--spread", type=int, required=True, help="номер разворота (файла скана), не лист")
    ap.add_argument("--what", default="", help="что на вырезке, коротко")
    a = ap.parse_args()
    ref = reference(a.arch, a.fond, a.opis, a.delo, a.spread)
    for c in a.crops:
        idx = c.parent / INDEX
        lines = idx.read_text(encoding="utf-8").splitlines() if idx.exists() else [
            "# Вырезки — где искать оригинал", "", "Одна строка — одна вырезка: что на ней и откуда скан.", ""]
        lines = [ln for ln in lines if not ln.startswith(f"- `{c.name}`")]
        lines.append(f"- `{c.name}` — {a.what + ' — ' if a.what else ''}{ref}")
        idx.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"{idx}: {c.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
