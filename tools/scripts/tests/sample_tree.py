"""Дерево для тестов — вымышленный образец, а не живое дерево семьи.

Что делает. Один раз за прогон тестов собирает во временной папке новое дерево — `rodo init` + `rodo import gedcom
tools/sample/sample.ged` (30 вымышленных людей, что в них нарочно — tools/sample/README.md) — и ставит FTREE_ROOT туда.
Поэтому `paths.ROOT`, `cards.load()` и любой скрипт, который тест зовёт, видят образец. Живое дерево тесты не читают и
не меняют; FTREE_ROOT снаружи (своё дерево, несуществующая папка) на тесты не влияет.

Почему собираем, а не храним готовую папку: сборка — меньше секунды, а готовая папка отставала бы от `rodo init` и
импорта; заодно каждый прогон проверяет, что образец собирается.

Как подключить: первой строкой после `sys.path.insert(...)` в тесте, ДО `import paths` и любого скрипта:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import sample_tree  # noqa: E402,F401  — дерево для тестов: вымышленный образец
Что каждый тест подключает его первым, проверяет test_sample_tree.py.

Тесты сайта (web/test) берут данные сайта того же образца:
    tools/py tools/scripts/tests/sample_tree.py --site <папка>   → <папка>/data/*.json (site_export.py --data)
Так зовёт web/test/sampleSite.ts перед тестами; дерево после этого стирается, данные остаются в <папке>.
"""
import atexit
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2]
SAMPLE = TOOLS / "sample" / "sample.ged"
BRANCHES = """
[[branch]]
name = "Ясеневы"
root = "Прокоп Ясенев"
keeper = "Анна"

[[branch]]
name = "Дубняки"
root = "Евстафий Дубняк"
keeper = "Анна"
"""


def _build() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="ftree-test-sample-"))
    atexit.register(shutil.rmtree, tmp, ignore_errors=True)
    root = tmp / "tree"
    env = {k: v for k, v in os.environ.items() if not k.startswith("FTREE_")}
    env["FTREE_ENV_FILE"] = str(tmp / "no-env")          # файл настроек этого Mac — мимо: тесты одинаковы везде
    py = TOOLS / "py"
    r = subprocess.run([str(py), str(TOOLS / "scripts" / "tree_init.py"), str(root), "--no-git", "--title",
                        "Родословная Ясеневых"], env=env, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("образец для тестов: rodo init не прошёл\n" + r.stdout + r.stderr)
    r = subprocess.run([str(py), str(TOOLS / "scripts" / "import_gedcom.py"), str(SAMPLE)], cwd=root,
                       env={**env, "FTREE_ROOT": str(root)}, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("образец для тестов: импорт sample.ged не прошёл\n" + r.stdout + r.stderr)
    with (root / "ftree.toml").open("a", encoding="utf-8") as f:   # две ветки рода, как у настоящего дерева
        f.write(BRANCHES)
    return root


def _site(out: Path, data_only: bool = True) -> None:
    """Выгрузка сайта образца в out: data/*.json (data_only) или вся — с media/, files/, site.json."""
    root = _build().resolve()
    env = {k: v for k, v in os.environ.items() if not k.startswith("FTREE_")}
    env.update(FTREE_ROOT=str(root), FTREE_ENV_FILE=str(root.parent / "no-env"), FTREE_SITE_EXPORT=str(out))
    r = subprocess.run([str(TOOLS / "py"), str(TOOLS / "scripts" / "site_export.py"), *(["--data"] if data_only else [])],
                       cwd=root, env=env,
                       capture_output=True, text=True)
    if r.returncode:
        raise SystemExit("образец: данные сайта не собрались\n" + r.stdout[-3000:] + r.stderr[-3000:])


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--site":
        raise SystemExit("tools/py tools/scripts/tests/sample_tree.py --site <папка>")
    _site(Path(sys.argv[2]).resolve())
    raise SystemExit(0)

ROOT = _build().resolve()

if "paths" in sys.modules and Path(sys.modules["paths"].ROOT) != ROOT:
    raise RuntimeError("paths уже загружен с живым деревом: sample_tree надо подключать в тесте до import paths "
                       f"(сейчас paths.ROOT = {sys.modules['paths'].ROOT})")
os.environ["FTREE_ROOT"] = str(ROOT)
os.environ["FTREE_ENV_FILE"] = str(ROOT.parent / "no-env")
