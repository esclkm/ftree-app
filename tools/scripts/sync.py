#!/usr/bin/env python3
"""Синхронизаторы проекта — что само подтягивается за исходными файлами и когда.

Правило одно: источник правды правит человек (карточки, биографии, книги), всё производное догоняет его само.

  pre-commit   — перед коммитом, быстро (~2 с), коммит ждёт:
                 1. ссылки на переименованные заголовки биографий → поправить (anchors.py fix-staged);
                    осталась ссылка в пустоту — коммит стоп: рассказ о человеке пропал бы с сайта;
                    дата не по правилу GEDCOM в карточке или линии жизни коммита (check_dates.py) — коммит стоп;
                 2. производное из дерева — биография ↔ карточка по имени (bio_ids --fix: переименовать биографию вслед
                    за карточкой, номера в свойствах, строка «Биография:» в карточке), ветки lineage (assign_lineage), «Рассказ» и «Тексты» в карточках
                    (texts_section), каталог фото (photo_catalog), дети из карточек в линиях жизни родителей
                    (check_lifeline.py --fix), места в фактах карточек коммита — ссылками, иначе их нет на карте
                    (check_fact_places.py --fix --staged) — пересчитать и добавить в этот же коммит.
  translate    — вручную, по решению (не из хуков git: в хуках git ИИ нет, с 01.10.2026):
                 3. ИИ-перевод биографий, у которых поменялся русский текст (bio_autotranslate.py),
                    и отдельный коммит «Автоперевод биографий» — его post-commit выложит, как любой коммит.
  status       — в начале сессии Claude (hook.py session): что отстало и требует человека —
                 переводы, которые пора сделать или не удалось, PDF старее своего текста (PDF собираем только по просьбе);
                 внешние копии дерева (MyHeritage, Familio, FamilySearch) и план поиска, отставшие от карточек и отчётов;
                 медиа, не ушедшее в облако (post-commit), и аудио, распознанное слежением за папкой, но не разобранное.
                 Всё локально: без сети и без ИИ.

Запуск вручную:  python3 tools/scripts/sync.py status
"""
import datetime
import hashlib
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
import destinations  # где хранить медиа, имя дерева для логов
import paths
from paths import ROOT, rel  # корень дерева — папка с ftree.toml (paths.find_root)
DERIVED = (("bio_ids", "--fix"), ("assign_lineage",), ("texts_section",), ("photo_catalog",), ("check_lifeline", "--fix"),
           ("check_fact_places", "--fix", "--staged"))
# Куда пишут пересчёты DERIVED: карточки, биографии и переводы (bio_ids, assign_lineage, texts_section, check_lifeline) —
# в дереве; photo_catalog — каталог фото. Только это пре-коммит добавляет сам: в те же секунды соседняя сессия Claude
# может править свои файлы (планы, отчёты в <папка поиска>), и они уехали бы в чужой коммит (так было 14.10.2026, d9068fd).
DERIVED_OUT = (rel(paths.TREE) + "/", rel(paths.PHOTO_CATALOG))
LOG = destinations.run_file("autotranslate.log")
PDF_DIRS = tuple(map(rel, (paths.BOOKS, paths.BOOK_TRANSLATIONS, paths.BOOKS_ARGENTINA)))
PEOPLE = rel(paths.PEOPLE)
MH_PLAN = rel(paths.MH_WEB / "plan.json")       # myheritage_plan.py plan — что отнести на сайт
FAMILIO_MATCH = rel(paths.FAMILIO_MATCH)  # меняется при каждом переносе на Familio
SEARCH_LOG = rel(paths.SEARCH_LOG)        # строки «familysearch · общее дерево …» = проверка FS
SEARCH_PLAN = rel(paths.RESEARCH_NEXT)
FINDINGS = rel(paths.FINDINGS)
FS_EVERY = 14      # общее дерево FamilySearch проверять раз в 2–4 недели (план 15)
PLAN_ORDER_DAYS = 7  # «Дальше по порядку (на …)» старше — порядок пора пересмотреть


def py(name, *args):
    r = subprocess.run([sys.executable, str(HERE / f"{name}.py"), *args], cwd=ROOT, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def git(*args):
    return subprocess.run(["git", "-c", "core.quotePath=false", *args], cwd=ROOT, capture_output=True, text=True)


def snap(rel):
    p = ROOT / rel
    return hashlib.md5(p.read_bytes()).hexdigest() if p.exists() else None


def unstaged():
    return set(git("diff", "--name-only").stdout.splitlines())


def split_touched(files):
    """Новые неготовые правки после пересчётов → (что пишут пересчёты — в коммит, всё прочее — только предупредить)."""
    ours = sorted(f for f in files if f.startswith(DERIVED_OUT))
    return ours, sorted(f for f in files if not f.startswith(DERIVED_OUT))


def pre_commit():
    code, out = py("anchors", "fix-staged")
    if code or not out.endswith(": 0"):
        print(out)
        print("✋ Коммит остановлен: ссылка на заголовок, которого нет (раздел удалили или переименовали так, "
              "что не узнать). Поправить ссылку или вернуть заголовок; проверить: python3 tools/scripts/anchors.py")
        return 1
    if out.splitlines()[0].startswith("Ссылки"):
        print(out.splitlines()[0])
    staged = [f for f in git("diff", "--cached", "--name-only", "--diff-filter=AM").stdout.splitlines()
              if f.endswith(".md") and ("/tree/people/" in f or "/tree/events/" in f
                                        or ("/biographies/" in f and "/translations/" not in f))]
    if staged:
        code, out = py("check_dates", *[x for f in staged for x in ("--file", f)])
        if code:
            print(out)
            print("✋ Коммит остановлен: даты не по правилу GEDCOM (навык dates). "
                  "Поправить; что правится само — python3 tools/scripts/check_dates.py --fix")
            return 1
    before = {f: snap(f) for f in unstaged()}
    for cmd in DERIVED:
        py(*cmd)
    after = unstaged()
    touched, foreign = split_touched(after - before.keys())
    if foreign:  # не пересчёт: чужая сессия правит рядом (или bio_ids поправил ссылки на переименованную биографию)
        print(f"⚠️ Не добавлены в коммит — изменились за время пересчёта, но пересчёты туда не пишут ({len(foreign)}): "
              + ", ".join(foreign[:5]) + (" …" if len(foreign) > 5 else "")
              + ". Свои — git add и ещё коммит; чужие (соседняя сессия) — не трогать.")
    if touched:
        git("add", "--", *sorted(touched))
        print(f"Пересчитано и добавлено в коммит: {len(touched)} файлов (ветки, «Рассказ», каталог фото, дети в линиях жизни, места в фактах)")
    both = sorted(f for f in before.keys() & after if snap(f) != before[f])
    if both:  # в файле уже были неготовые правки руками — не добавляем, чтобы не утащить их в коммит
        print("⚠️ Пересчитаны, но в коммит не добавлены — в них есть ещё и неготовые правки: " + ", ".join(both[:5]))
    return 0


def translate():
    with LOG.open("w", encoding="utf-8") as log:
        log.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M} автоперевод\n")
        code, out = py("bio_autotranslate")
        log.write(out + "\n")
    print(out.splitlines()[-1] if out else "Автоперевод: —")
    written = [x.split("Записано: ", 1)[1].split("  ")[0].strip() for x in out.splitlines() if "Записано: " in x]
    if written:  # коммитим только то, что записал автоперевод, — чужие неготовые правки не трогаем
        git("add", "--", *written)  # новый файл git commit по пути не возьмёт, пока он не добавлен
        names = [Path(x).stem for x in written]
        msg = "Автоперевод биографий (ИИ, не проверен): " + ", ".join(names[:6]) + (" …" if len(names) > 6 else "")
        r = subprocess.run(["git", "commit", "-q", "-m", msg, "--", *written], cwd=ROOT, capture_output=True,
                           text=True, env=os.environ)
        print(msg if r.returncode == 0 else f"Коммит переводов не удался: {(r.stdout + r.stderr).strip()[:300]}")
    return 0


def status():
    notes = []
    code, out = py("bio_autotranslate", "--check")
    last = out.splitlines()[-1] if out else ""
    if "пора перевести" in last:
        notes.append(last.replace("Автоперевод: ", "переводы: "))
    if LOG.exists() and "не удалось" in LOG.read_text(encoding="utf-8"):
        notes.append(f"последний автоперевод с ошибками — {LOG}")
    old = []
    for d in PDF_DIRS:
        for md in (ROOT / d).glob("*.md"):
            pdf = md.with_suffix(".pdf")
            if pdf.exists() and md.stat().st_mtime - pdf.stat().st_mtime > 3600:
                old.append(md.stem)
    if old:
        notes.append(f"PDF старее текста ({len(old)}): {', '.join(sorted(old)[:4])}{' …' if len(old) > 4 else ''} — "
                     f"собрать, только если попросят")
    code, out = py("anchors", "check")
    if code:
        notes.append(out.splitlines()[-1].lower())
    for check in (media_lag, audio_lag, myheritage_lag, mh_others_lag, familio_lag, familysearch_lag, search_plan_lag):
        try:
            note = check()
        except Exception as e:  # сводка при старте не должна падать из-за одной проверки
            note = f"{check.__name__}: не удалось проверить ({e})"
        if note:
            notes.append(note)
    print("Отстало: " + "; ".join(notes) if notes else "Отстало: ничего")
    site_open_reminder()
    return 0


def ddmm(d):
    return f"{d:%d.%m}"


def mh_note(plan, stale):
    """План переноса на MyHeritage → строка, если есть что нести на сайт (или план старше карточек)."""
    if plan is None:
        return "MyHeritage: плана нет — tools/py tools/scripts/myheritage_plan.py plan"
    kinds = {}
    for w in plan.get("to_site", []):
        kinds[w["action"]] = kinds.get(w["action"], 0) + 1
    if not kinds and not stale:
        return None
    snap = datetime.date.fromisoformat(plan["snapshot"][:10])
    work = ", ".join(f"{label} {n}" for label, n in (("правок полей", kinds.get("field", 0)),
                                                     ("связей", kinds.get("link", 0)),
                                                     ("новых людей", kinds.get("person", 0))) if n) or "ничего"
    return (f"MyHeritage: снимок сайта {ddmm(snap)}, на сайт — {work}"
            + (" (план устарел — myheritage_plan.py plan)" if stale else "") + " — tools/mh push")


def myheritage_lag():
    import json
    p = ROOT / MH_PLAN
    last = git("log", "-1", "--format=%ct", "--", PEOPLE).stdout.strip()
    stale = not p.exists() or (last and int(last) > p.stat().st_mtime)
    if stale and (ROOT / MH_PLAN).parent.joinpath("snapshot.json").exists():
        py("myheritage_plan", "plan")  # локально, ~1 с: пересчитать от свежих карточек
        stale = not p.exists() or (last and int(last) > p.stat().st_mtime)
    return mh_note(json.loads(p.read_text(encoding="utf-8")) if p.exists() else None, stale)


MH_OTHERS = rel(paths.MH_OTHERS)   # myheritage_tree.mjs watch — снимки чужих деревьев
MH_OTHERS_DAYS = 30                                 # чужие деревья меняются редко: раз в месяц хватает


def mh_others_note(last, today):
    """Дата последнего снимка чужих деревьев → строка, если пора перечитать (или ни разу не читали)."""
    if last is None:
        return "чужие деревья MyHeritage: не на учёте — node tools/scripts/myheritage_tree.mjs watch"
    if (today - last).days < MH_OTHERS_DAYS:
        return None
    return f"чужие деревья MyHeritage: снимок {ddmm(last)} — перечитать: node tools/scripts/myheritage_tree.mjs watch"


def mh_others_lag():
    d = ROOT / MH_OTHERS
    snaps = sorted(d.glob("????-??-??.json")) if d.exists() else []
    last = datetime.date.fromisoformat(snaps[-1].stem) if snaps else None
    return mh_others_note(last, datetime.date.today())


def changed_cards(since):
    """Карточки людей, добавленные и изменённые после коммита since (с неготовыми правками и новыми файлами)."""
    added = modified = 0
    for line in git("diff", "--name-status", "--no-renames", since, "--", PEOPLE).stdout.splitlines():
        added += line.startswith("A")
        modified += line.startswith("M")
    added += len(git("ls-files", "--others", "--exclude-standard", "--", PEOPLE).stdout.splitlines())
    return added, modified


def familio_note(when, added, modified):
    if not added and not modified:
        return None
    return (f"Familio: перенос {ddmm(when)}, после — карточек новых {added}, изменённых {modified} "
            "(грузим только связанных) — familio_sync.py")


def familio_lag():
    r = git("log", "-1", "--format=%h %cs", "--", FAMILIO_MATCH).stdout.split()
    if not r:
        return None
    return familio_note(datetime.date.fromisoformat(r[1]), *changed_cards(r[0]))


def fs_note(last, today, new):
    due = last + datetime.timedelta(days=FS_EVERY)
    if today <= due and not new:
        return None
    parts = [f"FamilySearch: проверка {ddmm(last)}"]
    if today > due:
        parts.append(f"пора проверить подсказки (раз в 2–4 недели, с {ddmm(due)})")
    if new:
        parts.append(f"ещё не там новых карточек ближней родни: {new} — familysearch_export.py build")
    return ", ".join(parts)


def familysearch_lag():
    import json
    log = ROOT / SEARCH_LOG
    days = [r.split("\t")[0] for r in log.read_text(encoding="utf-8").splitlines()
            if "\tfamilysearch\tобщее дерево" in r] if log.exists() else []
    if not days:
        return None
    last = datetime.date.fromisoformat(max(days))
    import familysearch_export as fs
    from cards.tree import load
    T = load()
    branches = [x.strip() for x in str(paths.tree_conf("familysearch.export.branches", "")).split(",") if x.strip()]
    take, _, _ = fs.select(T, branches, 70)   # ветки — как у familysearch_export.py build (ftree.toml)
    linked = json.loads(fs.MATCH.read_text(encoding="utf-8")) if fs.MATCH.exists() else {}
    first = min(v["date"] for v in linked.values()) if linked else last.isoformat()  # день загрузки
    fresh = set(git("log", f"--since={first} 00:00", "--diff-filter=A", "--name-only", "--format=", "--",
                    PEOPLE).stdout.splitlines())
    fresh |= set(git("ls-files", "--others", "--exclude-standard", "--", PEOPLE).stdout.splitlines())
    new = sum(1 for pid in take if pid not in linked and f"{PEOPLE}/{T.people[pid].stem}.md" in fresh)
    return fs_note(last, datetime.date.today(), new)


def plan_note(updated, order_on, finding_days, today):
    newer = [d for d in finding_days if updated is None or d > updated]
    old_order = order_on is not None and (today - order_on).days > PLAN_ORDER_DAYS
    if not newer and not old_order:
        return None
    why = [f"отчётов findings/ новее «Обновлено»: {len(newer)}"] if newer else []
    if old_order:
        why.append(f"«Дальше по порядку» на {ddmm(order_on)}")
    return "план поиска отстал от находок: " + ", ".join(why) + " — ПОИСК_ДАЛЬШЕ.md"


def search_plan_lag():
    import re
    p = ROOT / SEARCH_PLAN
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8")

    def day(pattern):
        m = re.search(pattern, text)
        return datetime.date(int(m[3]), int(m[2]), int(m[1])) if m else None
    finding_days = [datetime.date.fromisoformat(m[1]) for f in (ROOT / FINDINGS).glob("*.md")
                    if (m := re.search(r"_(\d{4}-\d\d-\d\d)\.md$", f.name))]
    return plan_note(day(r"Обновлено: (\d\d)\.(\d\d)\.(\d{4})"),
                     day(r"Дальше по порядку \(на (\d\d)\.(\d\d)\.(\d{4})\)"), finding_days, datetime.date.today())


def media_lag():
    """Медиа в описи, но не в облаке: post-commit отправляет в фоне — не ушло (нет сети) — сказать."""
    p = ROOT / "media/manifest.jsonl"
    if not p.exists() or not destinations.stores():  # хранилище не задано — отправлять некуда, и это не отставание
        return None
    n = sum(1 for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip() and '"pushed"' not in ln)
    if not n:
        return None
    return (f"облако: не отправлено медиа {n} — tools/py tools/scripts/media.py push "
            f"(последняя фоновая отправка — {destinations.run_file('media.log')})")


def audio_lag():
    """Аудио, которое слежение за папкой (audio_watch.py) уже распознало, а расшифровки AudioNN_….md ещё нет."""
    import json
    st = paths.CACHE / "audio_watch.json"
    if not st.exists():
        return None
    files = json.loads(st.read_text(encoding="utf-8")).get("files", {})
    waiting, failed = [], []
    for name, f in files.items():
        slug = f.get("slug", "")
        if f.get("status") == "ready" and not list(paths.TRANSCRIPTS_AUDIO.glob(f"{slug.capitalize()}_*.md")):
            waiting.append(f"{slug} ({name})")
        elif f.get("status") == "failed":
            failed.append(name)
    out = []
    if waiting:
        out.append(f"аудио распознано, ждёт разбора (навык audio-interview): {', '.join(waiting)}")
    if failed:
        out.append(f"аудио не распозналось: {', '.join(failed)} — лог tools/.cache/audio_watch.log")
    return "; ".join(out) or None


def site_open_reminder():
    """Сайт временно открыт без пароля ([site] open_until в ftree.toml) — напоминать каждую сессию, чтобы не забыть."""
    site = paths.CONFIG.get("site", {})
    until = str(site.get("open_until") or "")
    if not until:
        return
    countries = ", ".join(site.get("open_countries", [])[:5]) + (", …" if len(site.get("open_countries", [])) > 5 else "")
    left = (datetime.date.fromisoformat(until) - datetime.date.today()).days
    if left >= 0:
        print(f"⚠️ Сайт открыт БЕЗ ПАРОЛЯ ({countries}) до {until} — осталось {left} дн.; потом пароль вернётся сам. "
              f"Закрыть раньше: open_until = '' в ftree.toml ([site]) и выложить сайт.")
    else:
        print(f"Сайт снова по паролю с {until}; строку open_until в ftree.toml можно очистить.")


if __name__ == "__main__":
    sys.exit({"pre-commit": pre_commit, "translate": translate, "status": status}[sys.argv[1]]())
