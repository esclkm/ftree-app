#!/usr/bin/env python3
"""Обновить всё одной командой — Obsidian для этого не нужен, всё работает с файлами.

Порядок (каждый шаг опирается на предыдущий):
  1. check_tree     — связи, тёзки, пол родителей, фото, источники (при ошибках — стоп)
  1б. card_doctor   — дубли фото, источников и фактов в карточках убрать; красные сигналы показать
  2. assign_lineage — ветки по 8 дедушкам и бабушкам
  3. texts_section  — в карточках «Рассказ» и «Тексты»
  4. photo_catalog  — 3_research/КАТАЛОГ_ФОТО.md
  5. check_links    — битые ссылки
  5'. possible      — страница «Сверка»: пары «возможно, тот же человек / родня» рядом, с решениями
  5'''. search_by_place — «Поиск по архивам»: открытые задачи плана по месту, где искать
  5''. coverage     — «Документы по людям»: чем подтверждено рождение, брак, смерть предков; где документа нет
  5а. check_lifeline — линии жизни: только жизнь самого человека (показать нарушения)
  5а'. check_lifespan — годы жизни: известны, а в карточке пусто (показать)
  5а''. check_bio    — биографии: один человек в файле, разделы по порядку, события по времени (показать)
  5б. moves fix     — какие из них чинятся по истории переездов в git
  5в. anchors fix   — ссылки на переименованные заголовки биографий
  5г. bio_autotranslate — перевести биографии, у которых поменялся русский текст (кого — translations/00_АВТОПЕРЕВОД.md);
                      пропустить: --no-translate
  6. --dossiers     — «всё о человеке» для прямых предков (3_research/_dossiers/)
  7. --books        — черновики книг (ручные правки не затираются: новое — в _generated/)

Запуск:  python3 tools/scripts/update_all.py [--dossiers] [--books] [--no-translate]
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
import paths
from paths import ROOT  # корень дерева — папка с ftree.toml (paths.find_root)


def run(name, *args, stop_on_error=False):
    script = HERE / f"{name}.py"
    if not script.is_file():                  # скрипт только этого дерева (книги) — в данных: paths.TREE_SCRIPTS
        script = paths.TREE_SCRIPTS / f"{name}.py"
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, (str(HERE), os.environ.get("PYTHONPATH"))))}
    r = subprocess.run([sys.executable, str(script), *args], cwd=ROOT, capture_output=True, text=True, env=env)
    out = (r.stdout + r.stderr).strip().splitlines()
    print(f"• {name}: {out[-1] if out else 'ok'}")
    if r.returncode and stop_on_error:
        print("\n".join(out[:30]))
        sys.exit("Стоп: сначала исправьте ошибки дерева (скилл tree-maintenance).")
    return out


run("check_tree", stop_on_error=True)
for line in run("card_doctor", "--fix"):
    if line.startswith("  "):
        print("   " + line)
run("assign_lineage")
run("texts_section")
run("photo_catalog")
run("check_links", "--quiet")
run("possible")             # страница «Сверка» (3_research/tree/_СВЕРКА.md): все пары «возможно, тот же / родня»
run("search_by_place")      # «Поиск по архивам» (<папка поиска>/ПОИСК_ПО_АРХИВАМ.md)
run("coverage", "--write")   # чем подтверждены рождение, брак, смерть предков (3_research/tree/_ДОКУМЕНТЫ_ПО_ЛЮДЯМ.md)
for line in run("check_lifespan"):
    if line.startswith("  ✗"):
        print("   " + line)
for line in run("check_lifeline"):
    if line.startswith("  ✗"):
        print("   " + line)
here = ""
for line in run("check_bio"):  # устройство биографий: один человек, порядок разделов, события по времени
    if line.startswith(paths.rel(paths.RESEARCH) + "/"):
        here = line
    elif line.startswith("  ✗"):
        print(f"   {here}:{line[3:]}")
run("moves", "fix")          # ссылки, сломанные переездами, — по истории git (исправить: moves.py fix --apply)
run("anchors", "fix")        # [[…_БИО_….md#Заголовок]] после переименования заголовка
if "--no-translate" not in sys.argv:
    run("bio_autotranslate")  # переводит Claude; нет ни программы claude, ни ключа — только скажет, что пора
if "--dossiers" in sys.argv:
    import re
    people = [p.stem for p in paths.PEOPLE.glob("*.md")
              if re.search(r"^  - Прямой-предок$", p.read_text(encoding="utf-8"), re.M)]
    run("person_dossier", *people)
    print(f"  досье: {len(people)} прямых предков → 3_research/_dossiers/")
if "--books" in sys.argv:
    run("build_book")
    run("book_to_pdf")
    run("rod_to_pdf")
