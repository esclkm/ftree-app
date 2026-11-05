#!/usr/bin/env python3
"""Скорость вопросов к дереву (tree.py) на этом дереве — проверка данных: дерево растёт, и команды не должны тормозить.

Чтение дерева — до 3 с (на Mac ≈0,75 с при 970 карточках; сервер GitHub медленнее), каждая команда — до 0,5 с и не
длиннее 20 строк. Люди для вопросов — корни веток из ftree.toml, так что в скрипте нет ни одного имени.
Раньше это мерил тест tests/test_tree_cli.py на живом дереве; тесты теперь идут на вымышленном образце (этап 4).

  rodo check-tree-speed
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cards  # noqa: E402
import paths  # noqa: E402
import tree as T  # noqa: E402

LOAD_MAX, CMD_MAX, LINES_MAX = 3.0, 0.5, 20


def main() -> int:
    t0 = time.perf_counter()
    tree = cards.load()
    load = time.perf_counter() - t0
    problems = [f"чтение дерева {load:.2f} с (предел {LOAD_MAX} с)"] if load > LOAD_MAX else []
    roots = [r for r in paths.LINES.values() if r in {p.name for p in tree.people.values()}]
    argv_list = [["gaps"]]
    if roots:
        surname = roots[0].split()[-1]
        argv_list += [["who", roots[0]], ["find", surname]]
    if len(roots) > 1:
        argv_list.append(["kin", roots[0], roots[1]])
    for argv in argv_list:
        t0 = time.perf_counter()
        out = T.run(argv, tree)
        took = time.perf_counter() - t0
        if took > CMD_MAX:
            problems.append(f"tree.py {argv[0]}: {took:.2f} с (предел {CMD_MAX} с)")
        if len(out) > LINES_MAX:
            problems.append(f"tree.py {argv[0]}: {len(out)} строк (предел {LINES_MAX})")
    print("\n".join(problems) or f"Вопросы к дереву быстрые: чтение {load:.2f} с, команд {len(argv_list)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
