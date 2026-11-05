#!/usr/bin/env python3
"""План «Что ещё искать» не отстаёт от сделанного и держит один формат.

План — четыре файла в <папка поиска>/: ПОИСК_ДАЛЬШЕ.md (вход: порядок, правила, «Следующий свободный номер»,
«Обновлено»), ПОИСК_ОНЛАЙН.md (задачи О, П, Р, Н), ПОИСК_ОФФЛАЙН.md (письма А, вопросы родным С), ПОИСК_СДЕЛАНО.md
(нашлось и пусто). Нашли или пусто — строку задачи удаляют из открытых, а в «Сделано» номер пишут в колонку «Было».

  ОШИБКА    номер повторяется среди открытых задач;
  ОШИБКА    номер закрыт («Было» в «Сделано»), а задача ещё висит в открытых;
  ОШИБКА    в строке открытой задачи стоит ✅ или ⛔ — её место в «Сделано»;
  ОШИБКА    у строки открытой задачи не 6 колонок (№, Ветка, Что найти, Где, Что сделано и следующий шаг, Отчёт)
            или у строки «Сделано» не 6 (Дата, Было, Ветка, Что искали и где, Итог, Отчёт);
  ОШИБКА    «Следующий свободный номер» не больше всех занятых и закрытых (номер нельзя дать второй задаче);
  ОШИБКА    в findings/ есть отчёт с датой новее «Обновлено:» — его ещё не сверили с планом.

  python3 tools/scripts/check_search_plan.py
Код выхода 1, если есть ошибки.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

KINDS = "ОПРНАС"
TASK = re.compile(rf"^\|\s*([{KINDS}])(\d+)\s*\|.*$", re.M)
ID = re.compile(rf"([{KINDS}])(\d+)")
DONE_ROW = re.compile(r"^\|\s*(\d{2}\.\d{2}\.\d{4}|—)\s*\|.*$", re.M)
NEXT = re.compile(r"Следующий свободный номер:([^\n]*)")
DATE_FILE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
UPDATED = re.compile(r"Обновлено:\s*(\d{2})\.(\d{2})\.(\d{4})")


def cells(line):
    """Колонки строки таблицы; «|» внутри [[ссылки|подписи]] и «\\|» колонку не делят."""
    line = re.sub(r"\[\[[^\]]*\]\]", lambda m: m[0].replace("|", "¦"), line.strip().strip("|"))
    return re.split(r"(?<!\\)\|", line)


def check(plan, open_text, done, findings_dates):
    errors = []
    open_ids = {}
    for m in TASK.finditer(open_text):
        tid, line = m.group(1) + m.group(2), m.group(0)
        if tid in open_ids:
            errors.append(f"номер {tid} повторяется среди открытых задач")
        open_ids[tid] = line
        if "✅" in line or "⛔" in line:
            errors.append(f"{tid}: в открытой задаче стоит ✅/⛔ — перенести в «Сделано», номер — в «Было»")
        if len(cells(line)) != 6:
            errors.append(f"{tid}: колонок {len(cells(line))}, а нужно 6 (№, Ветка, Что найти, Где, шаг, Отчёт)")

    closed = set()
    for m in DONE_ROW.finditer(done):
        c = cells(m.group(0))
        if len(c) != 6:
            errors.append(f"«Сделано»: колонок {len(c)}, а нужно 6 — {m.group(0)[:80]}")
            continue
        closed |= {a + b for a, b in ID.findall(c[1])}
    for tid in sorted(closed & open_ids.keys()):
        errors.append(f"{tid} закрыт («Было» в «Сделано»), но ещё висит в открытых — удалить строку задачи")

    m = NEXT.search(plan)
    if not m:
        errors.append("нет строки «Следующий свободный номер: О…, П…, Р…, Н…, А…, С…»")
    else:
        nxt = {k: int(v) for k, v in ID.findall(m.group(1))}
        for tid in set(open_ids) | closed:
            k, n = tid[0], int(tid[1:])
            if n >= nxt.get(k, 0):
                errors.append(f"«Следующий свободный номер» для {k} должен быть больше {n} (занят {tid})")

    u = UPDATED.search(plan)
    if not u:
        errors.append("нет строки «Обновлено: ДД.ММ.ГГГГ»")
    else:
        upd = (u.group(3), u.group(2), u.group(1))
        newer = sorted(name for name, d in findings_dates if d > upd)
        if newer:
            errors.append("отчёты новее «Обновлено» — сверить с планом и поставить дату: " + ", ".join(newer))
    return errors


def main():
    read = lambda p: p.read_text(encoding="utf-8") if p.exists() else ""  # noqa: E731
    plan_files = (paths.RESEARCH_NEXT, paths.RESEARCH_ONLINE, paths.RESEARCH_OFFLINE, paths.RESEARCH_DONE)
    if not any(p.exists() for p in plan_files):   # новое дерево (rodo init): плана поиска ещё нет — проверять нечего
        print(f"План поиска: файлов нет ({paths.rel(paths.RESEARCH_NEXT)} и др.) — проверять нечего")
        return 0
    findings = []
    for f in (paths.PAVEL / "findings").glob("*.md"):
        m = DATE_FILE.search(f.stem)
        if m:
            findings.append((f.name, m.groups()))
    errors = check(read(paths.RESEARCH_NEXT), read(paths.RESEARCH_ONLINE) + "\n" + read(paths.RESEARCH_OFFLINE),
                   read(paths.RESEARCH_DONE), findings)
    for e in errors:
        print("ОШИБКА  " + e)
    print(f"План поиска: ошибок {len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
