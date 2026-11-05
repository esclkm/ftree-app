#!/usr/bin/env python3
"""Хуки Claude Code для проекта (подключены в .claude/settings.json).

  hook.py after-edit   — после Edit/Write: правка в 3_research/tree → check_tree.py и check_cards.py (запись, из
                         которой получится JSON сайта); ошибки уходят обратно Claude (код 2), чтобы он их исправил.
                         Правка карточки человека → card_doctor.py --fix по ней: дубли фото, источников
                         и фактов убираются сами; о починке и красных сигналах Claude узнаёт (код 2).
                         Правка карточки → check_lifespan.py: год рождения/смерти известен, а born/died пусты — код 2.
                         Правка карточки человека → check_lifeline.py --fix --kin по нему: его рождение (и смерть
                         при жизни родителя) само встаёт в линии жизни родителей, его дети — в его линию (код 2).
                         Правка карточки человека, события или биографии → check_dates.py по этому файлу: даты — как
                         в GEDCOM (ABT 1935, BET 1941 AND 1945; в линии жизни — «ок. 1935», «между 1941 и 1945») — код 2.
                         Правка биографии (3_research/tree/biographies/<Имя> — биография.md) → bio_ids.py --fix (номера, строка в карточке), check_lifespan.py и check_lifeline.py по людям этого файла:
                         линия жизни — только жизнь самого человека, дети из карточек дописываются сами (--fix); check_bio.py по этому файлу — один человек,
                         разделы по порядку, события по времени (код 2 при ошибках).
                         Правка биографии → check_fact_dates.py по её людям: год в линии жизни или в событии, а в
                         карточке нет факта с этим годом, — напоминание Claude (не блокирует): решить, вносить ли.
                         Правка оригинала в 1_sources (кроме inbox/ и описей) → предупреждение.
                         Правка карточки или биографии умершего (или родившегося до 1931) человека, если проверки
                         прошли, → напоминание Claude (не блокирует): оценить поиск по нему, скилл search-after-update;
                         раз в день на человека (tools/.cache/search_after_update.json).
  hook.py pre-read     — перед Read картинки или PDF в главной сессии: отказ, читать помощником sonnet (помощникам — можно).
  hook.py session      — в начале сессии: выключить новые навыки LineTen; короткая сводка (состояние дерева, что не закоммичено,
                         что отстало — sync.py status).
"""
import json
import subprocess
import sys
from pathlib import Path

import paths  # noqa: E402
from paths import ROOT, rel as rel_path  # корень дерева — папка с ftree.toml (paths.find_root)
SRC, INBOX = rel_path(paths.SOURCES) + "/", rel_path(paths.INBOX) + "/"
PEOPLE, EVENTS, TREE, BIOS = (rel_path(p) + "/" for p in (paths.PEOPLE, paths.EVENTS, paths.TREE, paths.BIOS))


def run(*cmd):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def after_edit():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    path = (data.get("tool_input") or {}).get("file_path") or ""
    try:
        rel = Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return 0
    notes = []  # напоминания Claude, которые правку не останавливают (additionalContext)
    if rel.startswith(SRC) and not rel.startswith(INBOX) \
            and not Path(rel).name.startswith("00_ОПИСЬ"):
        print(f"⚠️ {rel} — оригинал на этаже 1, его не правят. Если это вывод или расшифровка — "
              f"перенеси в {paths.RESEARCH.name}/ или {paths.TRANSCRIPTS.name}/ (см. CLAUDE.md).", file=sys.stderr)
        return 2
    if rel.endswith(".md") and (rel.startswith((PEOPLE, EVENTS))
                                or ("/biographies/" in rel and "/translations/" not in rel)):
        code, out = run(sys.executable, str(paths.SCRIPTS / "check_dates.py"), "--fix", "--file", rel)
        if code or "Поправлено:" in out:
            print("Даты — как в GEDCOM (навык dates; все виды — шапка tools/scripts/dates.py). "
                  "Если что-то поправлено само — перечитай файл перед следующей правкой:\n" + out, file=sys.stderr)
            return 2
    if rel.startswith(PEOPLE) and rel.endswith(".md"):
        code, out = run(sys.executable, str(paths.SCRIPTS / "check_lifespan.py"), Path(rel).stem)
        if code:
            print("Годы жизни: год известен, а в карточке пусто — впиши в born/died (посчитан из возраста — "
                  "BET 2005 AND 2006):\n" + out, file=sys.stderr)
            return 2
        # ребёнок добавлен или поправлен в карточке → строка о его рождении (и смерти при жизни родителя) сама
        # встаёт в линии жизни обоих родителей; у самого человека — его дети
        _, out = run(sys.executable, str(paths.SCRIPTS / "check_lifeline.py"), "--fix", "--kin", Path(rel).stem)
        if "Поправлено:" in out:
            print("Линии жизни догнали карточку (check_lifeline.py --fix): дописано в биографии родителей — перечитай их "
                  "перед правкой:\n" + out[out.index("Поправлено:"):], file=sys.stderr)
            return 2
        _, out = run(sys.executable, str(paths.SCRIPTS / "card_doctor.py"), "--fix", Path(rel).stem)
        if "Починено:" in out or "Посмотреть человеку:" in out:
            print("Доктор карточек (card_doctor.py) по этой карточке — если что-то починено, перечитай её "
                  "перед следующей правкой:\n" + "\n".join(out.splitlines()[:-1]), file=sys.stderr)
            return 2
    if "/biographies/" in rel and "/translations/" not in rel and rel.endswith(".md"):
        # биография ↔ карточка по имени: номера в свойствах и строка «Биография:» в карточке — сами
        _, out = run(sys.executable, str(paths.SCRIPTS / "bio_ids.py"), "--fix")
        if "поправлено: 0" not in out:
            print("Биография и карточка связаны по имени (bio_ids.py --fix) — перечитай файл перед правкой:\n" + out,
                  file=sys.stderr)
            return 2
        code, out = run(sys.executable, str(paths.SCRIPTS / "check_lifespan.py"))
        if code:
            print("Годы жизни из заголовка биографии не перенесены в карточку (born/died):\n" + out, file=sys.stderr)
            return 2
        code, out = run(sys.executable, str(paths.SCRIPTS / "check_lifeline.py"), "--fix", "--file", rel)
        if "Поправлено:" in out:
            print("В линию жизни дописаны дети из карточек (check_lifeline.py --fix) — перечитай файл перед правкой:\n"
                  + out[out.index("Поправлено:"):], file=sys.stderr)
            return 2
        if code:
            print("Линия жизни нарушает правило (только жизнь самого человека: дети — рождение и смерть при его "
                  "жизни, после смерти — ничего, без внуков) — исправь:\n" + out, file=sys.stderr)
            return 2
        code, out = run(sys.executable, str(paths.SCRIPTS / "check_bio.py"), "--file", rel)
        if code:
            print("Устройство биографии (check_bio.py): один человек в файле, разделы в порядке из 00_ИНДЕКС, события по "
                  "времени — исправь:\n" + out, file=sys.stderr)
            return 2
        # дата в рассказе, а в карточке нет факта с этим годом — решить, вносить ли (не блокирует)
        _, out = run(sys.executable, str(paths.SCRIPTS / "check_fact_dates.py"), "--file", rel)
        if "· " in out:
            notes.append("Дата есть, факта нет (check_fact_dates.py): в линии жизни или в событиях год, которого карточка "
                         "не знает. По каждой строке реши по источнику: внести факт с источником, дописать год в факт, где "
                         "событие уже есть без года, или — если факт не нужен — строку в ftree.toml, [fact_dates] ok:\n"
                         + "\n".join(x for x in out.splitlines() if x.strip() and not x.startswith("albums")))
    if rel.startswith(TREE):
        code, out = run(sys.executable, str(paths.SCRIPTS / "check_tree.py"))
        if code:
            lines = out.splitlines()
            print("Проверка дерева после правки нашла ошибки — исправь (скилл tree-maintenance):\n"
                  + "\n".join(lines[:25]) + ("\n…" if len(lines) > 26 else ""), file=sys.stderr)
            return 2
        code, out = run(sys.executable, str(paths.SCRIPTS / "check_cards.py"))
        if code:
            lines = out.splitlines()
            print("Карточка записана так, что сайт не соберётся (check_cards.py; формат строки факта — шапка "
                  "tools/scripts/cards/facts.py) — исправь:\n" + "\n".join(lines[:25]), file=sys.stderr)
            return 2
    if note := suggest_search(rel):
        notes.append(note)
    if notes:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "\n\n".join(notes)}},
                         ensure_ascii=False))
    return 0


SEARCHED = paths.CACHE / "search_after_update.json"  # кому уже предлагали поиск: {имя карточки: дата}


def suggest_search(rel):
    """Правка карточки человека или его биографии → напоминание Claude (текст или None): оценить, может ли поиск по этому
    человеку дать новое (скилл search-after-update), — один раз в день на человека. Не блокирует правку: additionalContext."""
    import datetime
    import re
    if not rel.endswith(".md") or "/translations/" in rel:
        return None
    if rel.startswith(PEOPLE):
        name = Path(rel).stem
    elif rel.startswith(BIOS) and rel.endswith(" — биография.md"):
        name = Path(rel).name[:-len(" — биография.md")]
    else:
        return None
    card = paths.PEOPLE / f"{name}.md"
    if not card.exists():
        return None
    text = card.read_text(encoding="utf-8")
    head = text.split("---")[1] if text.startswith("---") else ""
    def field(k):
        m = re.search(rf"^{k}:[ \t]*(.*)$", head, re.M)
        return m.group(1).strip().strip('"') if m else ""
    born = re.search(r"\d{4}", field("born"))
    if not field("died") and born and int(born.group()) > 1930:
        return None  # вероятно, жив — о живых в сети не ищем
    today = datetime.date.today().isoformat()
    try:
        seen = json.loads(SEARCHED.read_text(encoding="utf-8"))
    except Exception:
        seen = {}
    if seen.get(name) == today:
        return None
    seen[name] = today
    SEARCHED.parent.mkdir(parents=True, exist_ok=True)
    SEARCHED.write_text(json.dumps(seen, ensure_ascii=False, indent=1), encoding="utf-8")
    return (f"Поиск после правки: поменялось о «{name}» ({field('born') or '?'}–{field('died') or '?'}, "
            f"приоритет {field('research_priority') or '?'}). Когда правки по нему закончены — скилл search-after-update: "
            f"критично оценить, может ли новое (место, годы, работа, родня) дать документ в открытых источниках; "
            f"если да — поиск в фоне, если нет — одной строкой «поиск не нужен: почему». Не повторять пустое из "
            f"{rel_path(paths.RESEARCH_DONE)}.")


IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".heic", ".gif", ".bmp", ".pdf"}


def pre_read():
    """Главная сессия открывает картинку или PDF — отказ: читает помощник sonnet. Помощники (у них есть agent_id) — свободно.
    Зачем: скан остаётся в разговоре до конца сессии и перечитывается на каждом шаге (навык orchestration)."""
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    path = (data.get("tool_input") or {}).get("file_path") or ""
    if data.get("agent_id") or Path(path).suffix.lower() not in IMAGE_EXT:
        return 0
    # Павла не спрашиваем (решение 14.10.2026): картинки читает помощник sonnet — отказ сразу направляет к нему.
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
          "permissionDecisionReason": "Картинки в главной сессии не читаем: скан остаётся в разговоре и перечитывается "
          "на каждом шаге. Отдай файл помощнику — Agent, model sonnet, ответ до 20–25 строк (вырезки — тоже ему; "
          "навык orchestration)."}}, ensure_ascii=False))
    return 0


def skills_off():
    """Навыки LineTen (их зеркало в ~/.claude/skills) в этом проекте не нужны — выключить новые после синхронизации."""
    import re
    st = ROOT / ".claude" / "settings.json"
    cfg = json.loads(st.read_text(encoding="utf-8"))
    off = cfg.setdefault("skillOverrides", {})
    names = set()
    for f in (Path.home() / ".claude" / "skills").glob("*/SKILL.md"):
        m = re.search(r"^name:\s*[\"']?([^\"'\n]+)", f.read_text(encoding="utf-8"), re.M)
        names.add(m.group(1).strip() if m else f.parent.name)
    new = sorted(n for n in names if off.get(n) != "off")
    if new:
        off.update({n: "off" for n in new})
        cfg["skillOverrides"] = dict(sorted(off.items()))
        st.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return new


def session():
    new = skills_off()
    _, tree = run(sys.executable, str(paths.SCRIPTS / "check_tree.py"), "--quiet")
    _, st = run("git", "status", "--short")
    n = len([x for x in st.splitlines() if x.strip()])
    _, lag = run(sys.executable, str(paths.SCRIPTS / "sync.py"), "status")
    _, doc = run(sys.executable, str(paths.SCRIPTS / "setup.py"), "--short")
    print(f"Проект «Родословная»: правила — CLAUDE.md, карта — START_HERE.md. {tree.splitlines()[-1] if tree else ''}. "
          f"Не закоммичено файлов: {n}. {doc.splitlines()[-1] if doc else ''}. {' '.join(x.rstrip('.') + '.' for x in lag.splitlines() if x.strip()).rstrip('.')}. "
          f"О человеке — скилл person, перед разговором — dig, глава книги — book-chapter, всё обновить — update_all.py."
          + (f" Выключено новых навыков LineTen: {len(new)} (подействует со следующей сессии)." if new else ""))
    return 0


if __name__ == "__main__":
    sys.exit({"after-edit": after_edit, "session": session, "pre-read": pre_read}[sys.argv[1]]())
