#!/usr/bin/env python3
"""Выгрузка для сайта родни: дерево (3_research/tree) → папка, из которой сборщик сайта (web/scripts/site.mjs) собирает
сайт, не видя ни одной карточки.

  <выгрузка>/data/*.json   — по схемам web/schema: люди, места, источники, заметки, галерея, план поиска, надписи
  <выгрузка>/media/        — фото, уменьшенные для сайта (не пересжимаются, пока файл есть)
  <выгрузка>/files/        — PDF и другие файлы, на которые есть ссылки
  <выгрузка>/site.json     — что отдавать только по паролю, срок и страны открытого входа, куда выкладывать (ftree.toml [site])

Всё скрытие личного — здесь, до того как файл создан: номера домов, телефоны, почта (site_data/privacy.py), записи
разговоров в семье, закрытые документы, сканы документов живых (по паролю). Папка — paths.SITE_EXPORT
(4_outputs/site_export, в git не хранится).

  rodo site export            всё: data/, media/, files/, site.json
  rodo site export --data     только data/*.json (проверки на GitHub: там нет фото)
  rodo site export --out DIR  в другую папку (тесты)

Здесь же — разбор биографий («Линия жизни», «Память», «Воспоминания»), им пользуются проверки (import site_export as b;
старое имя build_site.py — переходник).
"""
import datetime
import functools
import hashlib
import html
import json
import os
import re
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageFile, ImageOps

# Сканы, скачанные с сайтов архивов (Госкаталог, gwar.mil.ru), бывают недокачаны на несколько байт в конце — картинка
# цела, а Pillow роняет всю сборку (01.10.2026, 10 файлов). Оригиналы в 1_sources не трогаем — читаем как есть.
ImageFile.LOAD_TRUNCATED_IMAGES = True

sys.path.insert(0, str(Path(__file__).resolve().parent))
import destinations  # noqa: E402 — куда выкладывать (ftree.toml, [[site.target]])
import paths  # noqa: E402
import dates  # noqa: E402
import cards  # noqa: E402
from cards import notes  # noqa: E402
import tr_store  # noqa: E402 — переводы мест, фактов и фото
from cards.places import text_of as place_text_of  # noqa: E402
from cards.notes import N, as_list, link_target, year  # noqa: E402,F401 — ими пользуются и другие скрипты (import site_export as b)
from site_data.names import (CYR, PLACE_LATIN, PLACE_SLUG_KEEP, assign_slugs, latin, latin_place, person_names, person_slugs, remember_slugs, place_names,  # noqa: E402,F401
                             slugify, translit)
from site_data import eras, export, life  # noqa: E402
import living as living_rule  # noqa: E402
from site_data import progress as site_progress  # noqa: E402
from site_data.eras import ERA_TR  # noqa: E402,F401
from site_data.life import WHERE_COL, life_year  # noqa: E402,F401
from site_data.privacy import EMAIL, PHONE, Privacy, audio_source, closed_document, is_audio, no_contacts, unpublished  # noqa: E402,F401

OUT = paths.SITE_EXPORT
if __name__ == "__main__" and "--out" in sys.argv:  # до чтения дерева: фото пишутся в OUT по ходу
    OUT = Path(sys.argv[sys.argv.index("--out") + 1]).resolve()


# ---------- чтение дерева ----------

def read_note(p):
    n = notes.read_note(p)
    return n.fm, n.body


people, places, events = {}, {}, []
for p in sorted((paths.TREE / "people").glob("*.md")):
    f, body = read_note(p)
    if f.get("cr_id"):
        people[N(p.stem)] = {"stem": N(p.stem), "f": f, "body": body}
for p in sorted((paths.TREE / "places").glob("*.md")):
    f, body = read_note(p)
    if f.get("cr_id"):
        places[N(p.stem)] = {"stem": N(p.stem), "f": f, "body": body}
for p in sorted((paths.TREE / "events").glob("*.md")):
    f, body = read_note(p)
    if f.get("cr_type") == "event":
        events.append(f)
by_id = {v["f"]["cr_id"]: v for v in people.values()}

# ---------- номера домов и квартир — на сайт не идут (site_data/privacy.py) ----------
_privacy = Privacy([str(pl["f"].get("name") or pl["stem"]) for pl in places.values()],
                   [str(pl["f"].get("name") or pl["stem"]) for pl in places.values() if pl["f"].get("address_public")])
no_address, no_address_name, no_address_html = _privacy.text, _privacy.file_name, _privacy.html

# ---------- имена латиницей (site_data/names.py) ----------

for d in people.values():
    d["id"] = d["f"]["cr_id"]
    d["name"] = str(d["f"].get("name") or d["stem"])
    d.update(person_names(d["name"], as_list(d["f"].get("aliases"))))
for d in places.values():
    d["id"] = d["f"]["cr_id"]
    d.update(place_names(no_address(str(d["f"].get("name") or d["stem"]))))
for coll, folder in ((people, "people"), (places, "places")):
    slugs = assign_slugs([(d["id"], PLACE_SLUG_KEEP.get(d["ru"], d["en"]) if folder == "places" else d["en"],
                           year(d["f"].get("born"))) for d in coll.values()], person_slugs() if folder == "people" else None)
    if folder == "people":
        remember_slugs(slugs)
    for d in coll.values():
        d["slug"], d["url"] = slugs[d["id"]], f"{folder}/{slugs[d['id']]}.html"


def rel_ids(f, key):
    """Связь по номеру (key_id), а если номера нет — по имени."""
    ids = [i for i in as_list(f.get(f"{key}_id")) if i in by_id]
    if not ids:
        ids = [people[t]["id"] for t in map(link_target, as_list(f.get(key))) if t in people]
    return ids


for d in people.values():
    f = d["f"]
    d["father"], d["mother"] = rel_ids(f, "father")[:1], rel_ids(f, "mother")[:1]
    d["spouses"], d["children"] = rel_ids(f, "spouse"), rel_ids(f, "children")
# связи бывают записаны только с одной стороны — достраиваем обратные
for d in people.values():
    for pid in d["father"] + d["mother"]:
        if d["id"] not in by_id[pid]["children"]:
            by_id[pid]["children"].append(d["id"])
    for sid in d["spouses"]:
        if d["id"] not in by_id[sid]["spouses"]:
            by_id[sid]["spouses"].append(d["id"])
    for cid in d["children"]:
        c = by_id[cid]
        key = "father" if d["f"].get("sex") == "male" else "mother"
        if not c[key]:
            c[key] = [d["id"]]

person_events = {}
for e in events:
    # «persons» — верный список; старое «person» у тёзок указывает на однофамильца по голому имени
    for who in dict.fromkeys(link_target(x) for x in as_list(e.get("persons")) or as_list(e.get("person"))):
        if who in people:
            person_events.setdefault(who, []).append(e)

# разводы: пара → год (если известен). На дереве линия между такими супругами — точками
divorces = {}
for e in events:
    if e.get("event_type") == "divorce":
        ids = [people[t]["id"] for t in dict.fromkeys(link_target(x) for x in as_list(e.get("persons"))) if t in people]
        if len(ids) == 2:
            divorces[frozenset(ids)] = year(e.get("date"))


# фото: имя файла → путь (оригиналы и обработанные копии; обработанная реставрация в приоритете)
media_index = {}
for base in (paths.SOURCES, paths.PHOTOS_PROCESSED):
    for p in base.rglob("*"):
        if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp") and "social_export" not in str(p):
            media_index[N(p.name)] = p

# Заметки и файлы, на которые ссылаются карточки: биографии, заметки-источники, полные тексты находок, расшифровки,
# PDF. Страница создаётся для каждой заметки, до которой можно дойти по ссылкам (docs/…), файлы — копируются (files/…).
SKIP_DIRS = ("tools/", ".git/", ".claude/", ".obsidian/", ".wbh-profile/", "node_modules/", paths.rel(paths.SITE) + "/", paths.rel(paths.SITE_EXPORT) + "/", "social_export")
PEOPLE_REL, PLACES_REL, TREE_REL = paths.rel(paths.PEOPLE), paths.rel(paths.PLACES), paths.rel(paths.TREE) + "/"
MAX_FILE = 25 * 1024 * 1024  # больше Cloudflare Pages не принимает
md_by_rel, md_by_stem, file_by_name = {}, {}, {}


def project_files(root):
    """Как root.rglob("*") и в том же порядке (от него зависит, какой из тёзок-файлов победит), но в SKIP_DIRS,
    people/ и places/ не заходит: обход .git и node_modules занимал больше секунды на каждый запуск проверки."""
    def skip(d):
        rel = N(d.relative_to(root).as_posix())
        return any(x in rel + "/" for x in SKIP_DIRS) or rel in (PEOPLE_REL, PLACES_REL)
    dirs = [root]
    for d, sub, _ in root.walk():
        sub[:] = [s for s in sub if not skip(d / s)]
        dirs += [d / s for s in sub]
    for d in dirs:
        with os.scandir(d) as it:
            for e in it:
                yield d / e.name


for p in project_files(paths.ROOT):
    rel = N(p.relative_to(paths.ROOT).as_posix())
    if not p.is_file() or any(x in rel + "/" for x in SKIP_DIRS) or rel.startswith((PEOPLE_REL + "/", PLACES_REL + "/")):
        continue
    if p.suffix == ".md":
        md_by_rel[rel] = p
        # тёзки-файлы: заметка дерева важнее одноимённого файла где-то ещё
        if N(p.stem) not in md_by_stem or rel.startswith(TREE_REL):
            md_by_stem[N(p.stem)] = p
    else:
        file_by_name.setdefault(N(p.name), p)
docs, pending = {}, []  # путь заметки → номер; очередь на выгрузку
copied = set()  # файлы files/, на которые есть ссылка в этой выгрузке; остальные в конце удаляются


def doc_hash(rel):
    """Номер заметки — как у прежних страниц docs/<номер>.html: старые ссылки ведут на ту же заметку."""
    return hashlib.md5(rel.encode()).hexdigest()[:10]


def doc_id(p):
    """Номер заметки для data/docs/<номер>.json; первая ссылка ставит её в очередь выгрузки (SiteExtras.next_doc)."""
    rel = N(p.relative_to(paths.ROOT).as_posix())
    if rel not in docs:
        docs[rel] = doc_hash(rel)
        pending.append(p)
    return docs[rel]


def md_file(target):
    t = N(target.split("#")[0]).strip()
    p = md_by_rel.get(t) or md_by_rel.get(t + ".md") or md_by_stem.get(N(t.split("/")[-1].removesuffix(".md")))
    # расшифровки разговоров в семье на сайт не идут (site_data/privacy.py): ни страницей, ни встроенным текстом
    return None if p and unpublished(p.relative_to(paths.ROOT).as_posix()) else p


def file_url(target):
    p = file_by_name.get(N(target.split("/")[-1]))
    if not p or p.stat().st_size > MAX_FILE or unpublished(p.relative_to(paths.ROOT).as_posix()):
        return None  # аудио разговоров в семье на сайт не копируем (site_data/privacy.py)
    if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
        return photo(p.name)
    dst = OUT / "files" / (hashlib.md5(str(p).encode()).hexdigest()[:8] + "_"
                           + re.sub(r"[^\w.-]", "_", no_address_name(N(p.stem)) + p.suffix))
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dst)
    copied.add(dst.name)
    return "files/" + dst.name


# ---------- текст ----------





# Ссылка на заголовок, в котором сама есть ссылка: [[файл#Имя [[Имя|@I…@]] — мать Павла]] → [[файл#Имя — мать Павла]]
NESTED = re.compile(r"\[\[([^\[\]]+?)\s*\[\[[^\]]*\]\]([^\[\]]*)\]\]")


def plain_head(h):
    return re.sub(r"\s+", " ", re.sub(r"\[\[[^\]]*\]\]|[\[\]*_`]", "", N(h))).strip()








def sections(body, level=3):
    """{'Заголовок': текст} для заголовков нужного уровня."""
    out = {}
    for m in re.finditer(rf"^{'#' * level} (.+)\n(.*?)(?=^#{{1,{level}}} |\Z)", body, re.S | re.M):
        out[N(m.group(1).strip())] = m.group(2)
    return out


def own_head(text):
    """Биография целиком («одна биография — один человек»): свой заголовок-имя в начале файла не показываем —
    имя уже в шапке страницы, а заголовок со строкой «**В дереве:**» сайт принял бы за раздел другого человека
    и спрятал бы линию жизни."""
    text = re.sub(r"\A\s*---\n.*?\n---\n", "", text, flags=re.S)  # шапка перевода (person_id, source_hash …)
    return re.sub(r"\A\s*#[ \t][^\n]*\n", "", text, count=1)


def embed(ref):
    """![[path/file.md#Заголовок]] → текст этого раздела биографии."""
    path, _, head = ref.partition("#")
    p = md_file(path)
    if not p:
        return ""
    text = N(p.read_text(encoding="utf-8"))
    if not head.strip():
        text = own_head(text)
    # «Человек#Раздел» — раздел с таким именем внутри раздела этого человека (одинаковые «Дети», «Что открыто»)
    for part in (h for h in head.split("#") if h.strip()):
        want = plain_head(part)
        m = next((m for m in re.finditer(r"^(#+)\s+(.+)$", text, re.M) if plain_head(m.group(2)) == want), None)
        if not m:
            return ""
        lvl = len(m.group(1))
        rest = text[m.end():]
        end = re.search(rf"^#{{1,{lvl}}}\s", rest, re.M)
        text = rest[:end.start()] if end else rest
    return text


# ---------- фото ----------

def photo(name):
    src = media_index.get(N(link_target(name))) or file_by_name.get(N(link_target(name)))
    if src and src.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
        return None
    if not src:
        return None
    dst = OUT / "media" / (re.sub(r"[^\w.-]", "_", no_address_name(N(src.stem))) + ".jpg")
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((1400, 1400))
            im.save(dst, "JPEG", quality=82)
    return "media/" + dst.name


def thumb(src, small=False):
    """Уменьшенная копия конкретного файла: большая (для окна просмотра) или маленькая (для сетки превью)."""
    key = hashlib.md5(str(src).encode()).hexdigest()[:6] + "_" + re.sub(r"[^\w.-]", "_", no_address(N(src.stem)))[:80]
    dst = OUT / "media" / ("s" if small else "l") / (key + ".jpg")
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((480, 480) if small else (1600, 1600))
            im.save(dst, "JPEG", quality=80)
    return dst.relative_to(OUT).as_posix()




# ---------- языки ----------
# Интерфейс переводится на лету (web/src/i18n.ts): в HTML лежит русский текст с пометкой data-t="ключ", остальные языки — здесь.
# Тексты карточек и биографий остаются на русском — для них в браузере есть кнопка «Перевести».
LANGS = [("ru", "Русский"), ("pl", "Polski"), ("es", "Español"), ("en", "English")]
I18N_ROWS = """
site|Родословная|Genealogia|Genealogía|Family tree
home_title|Родословная|Genealogia|Genealogía|Family tree
nav_home|Главная|Start|Inicio|Home
nav_tree|Дерево|Drzewo|Árbol|Tree
nav_map|Карта|Mapa|Mapa|Map
nav_people|Люди|Osoby|Personas|People
nav_sources|Источники|Źródła|Fuentes|Sources
share|Поделиться ссылкой|Udostępnij link|Compartir enlace|Share link
copied|Ссылка скопирована — её можно отправить|Link skopiowany — można go wysłać|Enlace copiado — ya puede enviarlo|Link copied — you can send it
ru_note|Тексты на этой странице — на русском.|Teksty na tej stronie są po rosyjsku — użyj funkcji „Przetłumacz” w przeglądarce.|Los textos de esta página están en ruso — use «Traducir» en su navegador.|Texts on this page are in Russian — use your browser's Translate button.
born_m|Родился|Urodził się|Nació|Born
born_f|Родилась|Urodziła się|Nació|Born
died_m|Умер|Zmarł|Falleció|Died
died_f|Умерла|Zmarła|Falleció|Died
occupation|Занятие|Zajęcie|Ocupación|Occupation
about|Сведения|Dane|Datos|Details
family|Семья|Rodzina|Familia|Family
father|Отец|Ojciec|Padre|Father
mother|Мать|Matka|Madre|Mother
spouse|Супруг(а)|Małżonek|Cónyuge|Spouse
children|Дети|Dzieci|Hijos|Children
siblings|Братья и сёстры|Rodzeństwo|Hermanos|Siblings
review_title|Сверка|Weryfikacja|Verificación|Review
review_card|Пары карточек: может быть, это один человек или родня — проверить и решить|Pary kart: może to ta sama osoba lub krewni — sprawdzić i zdecydować|Pares de fichas: quizá la misma persona o parientes — verificar y decidir|Pairs of records that may be the same person or relatives — to check and decide
review_ruled_out|Уже проверено — нет|Już sprawdzone — nie|Ya verificado — no|Already checked — no
review_marked|Отмечено в карточках|Oznaczone w kartach|Marcado en las fichas|Marked in the records
review_auto|Найдено автоматически|Znalezione automatycznie|Encontrado automáticamente|Found automatically
review_auto_note|Никто не отмечал, но похожи: одно имя, та же фамилия или место рождения, годы не спорят|Nikt nie oznaczył, ale są podobne: to samo imię, to samo nazwisko lub miejsce urodzenia, lata się nie wykluczają|Nadie lo marcó, pero se parecen: mismo nombre, mismo apellido o lugar de nacimiento, los años no se contradicen|Nobody marked them, but they look alike: same given name, same surname or birthplace, the years agree
review_why|Что совпало|Co się zgadza|Qué coincide|What matches
review_parents|Родители|Rodzice|Padres|Parents
review_decide|Решение (команда для Павла)|Decyzja (polecenie dla Pawła)|Decisión (comando para Pavel)|Decision (command for Pavel)
review_mark|Отметить «возможно»|Oznaczyć «możliwe»|Marcar «posible»|Mark as possible
review_same|Одно лицо — слить карточки|Ta sama osoba — połączyć karty|La misma persona — unir fichas|Same person — merge records
review_yes|Родня — да: связь по документу|Krewni — tak: powiązanie według dokumentu|Parientes — sí: vínculo según documento|Relatives — yes: link by document
review_no|Нет — больше не предлагать|Nie — nie proponować więcej|No — no volver a proponer|No — do not suggest again
maybe_title|Возможно, связан|Możliwe powiązania|Posible relación|Possible connection
maybe_note|Подозрение, не доказано; на дереве не показано|Przypuszczenie, nie udowodnione; nie ma go na drzewie|Sospecha, no probada; no figura en el árbol|A suspicion, not proven; not shown in the tree
maybe_why|На чём держится|Na czym się opiera|En qué se basa|Based on
maybe_same|возможно, тот же человек|możliwe, że to ta sama osoba|posiblemente la misma persona|possibly the same person
maybe_kin|возможно, родня|możliwe, że krewny|posiblemente pariente|possibly a relative
maybe_parent_m|возможно, отец|możliwe, że ojciec|posiblemente el padre|possibly the father
maybe_parent_f|возможно, мать|możliwe, że matka|posiblemente la madre|possibly the mother
maybe_child_m|возможно, сын|możliwe, że syn|posiblemente el hijo|possibly the son
maybe_child_f|возможно, дочь|możliwe, że córka|posiblemente la hija|possibly the daughter
maybe_sibling_m|возможно, брат|możliwe, że brat|posiblemente el hermano|possibly the brother
maybe_sibling_f|возможно, сестра|możliwe, że siostra|posiblemente la hermana|possibly the sister
maybe_pibling_m|возможно, дядя|możliwe, że wujek|posiblemente el tío|possibly the uncle
maybe_pibling_f|возможно, тётя|możliwe, że ciotka|posiblemente la tía|possibly the aunt
maybe_nibling_m|возможно, племянник|możliwe, że bratanek lub siostrzeniec|posiblemente el sobrino|possibly the nephew
maybe_nibling_f|возможно, племянница|możliwe, że bratanica lub siostrzenica|posiblemente la sobrina|possibly the niece
maybe_cousin_m|возможно, двоюродный брат|możliwe, że kuzyn|posiblemente el primo|possibly a cousin
maybe_cousin_f|возможно, двоюродная сестра|możliwe, że kuzynka|posiblemente la prima|possibly a cousin
maybe_grandparent_m|возможно, дед|możliwe, że dziadek|posiblemente el abuelo|possibly the grandfather
maybe_grandparent_f|возможно, бабушка|możliwe, że babcia|posiblemente la abuela|possibly the grandmother
maybe_grandchild_m|возможно, внук|możliwe, że wnuk|posiblemente el nieto|possibly the grandson
maybe_grandchild_f|возможно, внучка|możliwe, że wnuczka|posiblemente la nieta|possibly the granddaughter
maybe_spouse_m|возможно, муж|możliwe, że mąż|posiblemente el esposo|possibly the husband
maybe_spouse_f|возможно, жена|możliwe, że żona|posiblemente la esposa|possibly the wife
show_tree|Показать на дереве|Pokaż na drzewie|Ver en el árbol|Show in tree
show_map|Показать на карте|Pokaż na mapie|Ver en el mapa|Show on map
events|События|Wydarzenia|Acontecimientos|Events
lifeline|Линия жизни|Linia życia|Línea de vida|Timeline
memory|Память|Pamięć|Memoria|Remembrance
recollections|Воспоминания|Wspomnienia|Recuerdos|Memories
open_questions|Открытые вопросы|Otwarte pytania|Preguntas abiertas|Open questions
photos|Фото|Zdjęcia|Fotos|Photos
notes|Заметки, факты и источники|Notatki, fakty i źródła|Notas, datos y fuentes|Notes, facts and sources
ev_birth|Рождение|Narodziny|Nacimiento|Birth
ev_death|Смерть|Śmierć|Fallecimiento|Death
ev_marriage|Брак|Małżeństwo|Matrimonio|Marriage
ev_burial|Похороны|Pogrzeb|Entierro|Burial
ev_occupation|Работа|Praca|Trabajo|Work
ev_residence|Место жительства|Miejsce zamieszkania|Residencia|Residence
ev_custom|Был здесь|Pobyt|Estancia|Stay
ev_war|Фронтовые перевозки|Transport frontowy|Transporte al frente|Front-line transport
ev_kin|Дом родных|Dom bliskich|Casa de familiares|Relatives' home
ev_education|Учёба|Nauka|Estudios|Education
ev_divorce|Развод|Rozwód|Divorcio|Divorce
ev_child|Родился ребёнок|Urodziło się dziecko|Nació un hijo|A child was born
b_bio|биография|biografia|biografía|biography
b_texts|статьи и тексты|artykuły i teksty|artículos y textos|articles and texts
b_facts|факты с источником|fakty ze źródłem|datos con fuente|facts with sources
b_fam|семейные источники|źródła rodzinne|fuentes familiares|family sources
b_web|найдено в интернете|znalezione w internecie|encontrado en internet|found online
b_tree|чужие деревья|inne drzewa|otros árboles|other trees
b_pics|фото|zdjęcia|fotos|photos
b_kids|детей в дереве|dzieci w drzewie|hijos en el árbol|children in the tree
nothing_yet|пока ничего|na razie nic|nada todavía|nothing yet
empty_legend|о человеке пока ничего|brak informacji o osobie|aún sin información|no information yet
kin_legend|точка — родство под сомнением: светло-зелёная вероятно, жёлтая возможно, оранжевая маловероятно, красная не родня; чем бледнее карточка, тем меньше уверенности; без точки — доказано|kropka — pokrewieństwo niepewne: jasnozielona prawdopodobne, żółta możliwe, pomarańczowa mało prawdopodobne, czerwona nie krewny; im bledsza karta, tym mniejsza pewność; bez kropki — udowodnione|punto — parentesco dudoso: verde claro probable, amarillo posible, naranja poco probable, rojo no es pariente; cuanto más pálida la tarjeta, menos certeza; sin punto — probado|dot — kinship in doubt: light green likely, yellow possible, orange unlikely, red not kin; the paler the card, the less certain; no dot — proven
kl_title|Родство|Pokrewieństwo|Parentesco|Kinship
kl_proven|доказано|udowodnione|probado|proven
kl_likely|вероятно|prawdopodobne|probable|likely
kl_possible|возможно|możliwe|posible|possible
kl_unlikely|маловероятно|mało prawdopodobne|poco probable|unlikely
kl_no|не родня|nie krewny|no es pariente|not kin
kl_by_card|проверено и записано в карточке|sprawdzone i zapisane w karcie|verificado y anotado en la ficha|checked and recorded on the card
kl_by_facts|оценка по фактам и источникам|ocena według faktów i źródeł|estimado según los datos y fuentes|estimated from facts and sources
tree_hint|Нажмите на человека — дерево повернётся к нему; ещё раз — откроется его страница.|Kliknij osobę — drzewo ustawi się na niej; kliknij ponownie — otworzy się jej strona.|Pulse sobre una persona para centrar el árbol; pulse otra vez para abrir su página.|Click a person to centre the tree on them; click again to open their page.
search_ph|Найти человека…|Szukaj osoby…|Buscar persona…|Find a person…
unknown|неизвестно|nieznany|desconocido|unknown
people_search|Поиск по имени…|Szukaj po imieniu…|Buscar por nombre…|Search by name…
about_whom|О ком|O kim|Sobre quién|About whom
pp_born|родился(-ась) здесь|urodzeni tutaj|nació aquí|born here
pp_died|умер(ла) здесь|zmarli tutaj|falleció aquí|died here
pp_fact|по фактам|według faktów|según los datos|in the facts
home_intro|Семейное дерево: {0} человек, {1} мест. Собрано из рассказов родителей, семейного архива, документов и открытых источников.|Drzewo rodzinne: {0} osób, {1} miejsc. Zebrane z opowieści rodziców, archiwum rodzinnego, dokumentów i źródeł publicznych.|Árbol familiar: {0} personas, {1} lugares. Reunido a partir de relatos de los padres, el archivo familiar, documentos y fuentes públicas.|Family tree: {0} people, {1} places. Compiled from our parents' stories, the family archive, documents and public sources.
home_bio|Биография написана у {0} из {1} человек.|Biografia napisana dla {0} z {1} osób.|Hay biografía de {0} de {1} personas.|Biographies written for {0} of {1} people.
card_tree|кто чей родственник|kto jest z kim spokrewniony|quién es pariente de quién|who is related to whom
card_map|откуда мы родом|skąd pochodzimy|de dónde venimos|where we come from
card_people|по веткам рода|według gałęzi rodu|por ramas de la familia|by family branch
card_sources|документы, записи, статьи|dokumenty, nagrania, artykuły|documentos, grabaciones, artículos|documents, recordings, articles
branches|Ветки рода|Gałęzie rodu|Ramas de la familia|Family branches
note_family|Факт без пометки «семья» — ещё не проверен по документам.|Fakt bez oznaczenia „rodzina” nie jest jeszcze potwierdzony dokumentami.|Un dato sin la marca «familia» aún no está verificado con documentos.|A fact not marked “family” is not yet confirmed by documents.
map_people|людей|osób|personas|people
no_branch|Прочие люди|Inne osoby|Otras personas|Other people
nav_gallery|Хроника|Kronika|Crónica|Chronicle
gal_intro|Старые снимки мест, где жили предки, и времени, в котором они жили. Это иллюстрации «как там было», а не фото наших родных — если в подписи не сказано иное.|Stare zdjęcia miejsc, w których żyli przodkowie, i czasów, w których żyli. To ilustracje „jak tam było”, a nie zdjęcia naszych krewnych — chyba że podpis mówi inaczej.|Fotos antiguas de los lugares donde vivieron los antepasados y de su época. Son ilustraciones de «cómo era», no fotos de nuestros familiares, salvo que el pie de foto diga lo contrario.|Old photos of the places where our ancestors lived and of their times. They show “what it was like” — they are not photos of our relatives unless the caption says so.
gal_places|Места|Miejsca|Lugares|Places
gal_events|События|Wydarzenia|Eventos|Events
gal_tabs_intro|Места, где жила семья, её дома и события её времени — каждое своей страницей.|Miejsca, w których żyła rodzina, jej domy i wydarzenia jej czasów — każde na osobnej stronie.|Los lugares donde vivió la familia, sus casas y los acontecimientos de su época, cada uno en su propia página.|The places where the family lived, its homes and the events of its time — each on its own page.
gal_themes|Время и события|Czasy i wydarzenia|Épocas y acontecimientos|Times and events
gal_place_photos|Фото места разных лет|Zdjęcia miejsca z różnych lat|Fotos del lugar en distintas épocas|Photos of the place over the years
gal_life_photos|Фото мест из жизни|Zdjęcia miejsc z życia|Fotos de los lugares de su vida|Photos of the places in their life
gal_all|Все фото|Wszystkie zdjęcia|Todas las fotos|All photos
gal_source|Источник|Źródło|Fuente|Source
gal_whose|Чья история|Czyja historia|De quién es la historia|Whose story
gal_exact|Насколько точно|Na ile pewne|Grado de certeza|How exact
gal_note|Под вопросом|Wątpliwości|Dudas|Open question
gal_photos_n|{0} фото|{0} zdjęć|{0} fotos|{0} photos
gal_decade|{0}-е|lata {0}.|años {0}|{0}s
gal_noyear|Год неизвестен|Rok nieznany|Año desconocido|Year unknown
gal_folk|Связаны с местом: {0}|Związani z miejscem: {0}|Vinculados al lugar: {0}|Linked to the place: {0}
gal_folk_more|и ещё {0}|i jeszcze {0}|y {0} más|and {0} more
gal_period|Годы снимков|Lata zdjęć|Años de las fotos|Photo years
gal_from|с|od|desde|from
gal_to|по|do|hasta|to
gal_all_years|все годы|wszystkie lata|todos los años|all years
gal_in_period|{0} из {1} фото|{0} z {1} zdjęć|{0} de {1} fotos|{0} of {1} photos
gal_none_in_period|За эти годы снимков нет.|Brak zdjęć z tych lat.|No hay fotos de esos años.|No photos from these years.
gal_search|Найти: место, событие, человек, год…|Szukaj: miejsce, wydarzenie, osoba, rok…|Buscar: lugar, evento, persona, año…|Search: place, event, person, year…
map_search|Найти место на карте…|Znajdź miejsce na mapie…|Buscar un lugar en el mapa…|Find a place on the map…
search_none|Ничего не нашлось.|Nic nie znaleziono.|No se encontró nada.|Nothing found.
gal_place_page|Страница места|Strona miejsca|Página del lugar|Place page
gal_ours|наше|nasze|nuestro|ours
gal_like|≈ не наше|≈ nie nasze|≈ no es el nuestro|≈ not ours
gal_like_km|{0}, {1} км от деревни {2}|{0}, {1} km od wsi {2}|{0}, a {1} km del pueblo {2}|{0}, {1} km from the village of {2}
gal_legend_ours|то самое место, где жили или куда ходили наши|to samo miejsce, gdzie mieszkali lub dokąd chodzili nasi|el mismo lugar donde vivían o adonde iban los nuestros|the very place where our family lived or went
gal_legend_like|самая похожая деревня рядом: снимков нашей нет, указано, сколько км|najbardziej podobna wieś w pobliżu: zdjęć naszej nie ma, podano odległość w km|el pueblo más parecido cercano: no hay fotos del nuestro; se indica a cuántos km|the most similar village nearby: there are no photos of ours; the distance is given in km
biography|Биография|Biografia|Biografía|Biography
hidden_anc|Есть предки — нажмите, чтобы показать|Są przodkowie — kliknij, aby pokazać|Hay antepasados — pulse para mostrarlos|There are ancestors — click to show
hidden_desc|Есть потомки — нажмите, чтобы показать|Są potomkowie — kliknij, aby pokazać|Hay descendientes — pulse para mostrarlos|There are descendants — click to show
divorced|развод|rozwód|divorcio|divorced
div_legend|точки между супругами — развод|kropki między małżonkami — rozwód|puntos entre cónyuges — divorcio|dotted line between spouses — divorce
mar_legend|цвет линии — дети от второго и следующих браков|kolor linii — dzieci z drugiego i kolejnych małżeństw|el color de la línea indica hijos del segundo matrimonio o siguientes|line colour — children of a second or later marriage
marriage_n|ребёнок от {0}-го брака|dziecko z {0}. małżeństwa|hijo del {0}.º matrimonio|child of marriage no. {0}
places_eras|Места и эпохи|Miejsca i epoki|Lugares y épocas|Places and eras
then|тогда|wtedy|entonces|then
addr_other_years|Снимки этих адресов есть, но из других лет|Zdjęcia tych adresów są, ale z innych lat|Hay fotos de estas direcciones, pero de otros años|These addresses have photos, but from other years
his_eras|какие государства здесь были в эти годы|jakie państwa tu były w tych latach|qué estados hubo aquí en esos años|which states this place belonged to in those years
kin_you|Вы|Ty|Usted|You
kin_self|Это вы|To Ty|Es usted|This is you
kin_not_me|Это не я|To nie ja|No soy yo|Not me
kin_none|Связь с вами в дереве пока не найдена|W drzewie nie znaleziono jeszcze powiązania z Tobą|Aún no se encontró su vínculo en el árbol|No connection to you found in the tree yet
kin_for|Кем приходится для|Kim jest dla|Qué es para|Relation to
kin_back|Снова считать от меня|Znowu liczyć ode mnie|Volver a contar desde mí|Count from me again
kin_other|кем приходится другому…|kim jest dla kogoś innego…|parentesco con otra persona…|related to someone else…
kin_other_ph|Для кого посчитать?|Dla kogo policzyć?|¿Para quién calcular?|Relation to whom?
kin_origin|отсюда|stąd|desde aquí|from here
kin_chart|Схема родства|Schemat pokrewieństwa|Diagrama de parentesco|Relationship chart
kin_close|Закрыть|Zamknij|Cerrar|Close
help|Как читать дерево|Jak czytać drzewo|Cómo leer el árbol|How to read the tree
path_legend|малиновая линия — путь родства к человеку в центре|malinowa linia — droga pokrewieństwa do osoby w środku|línea frambuesa: camino de parentesco hasta la persona del centro|raspberry line — how the person in the centre is related
set_title|Настройки|Ustawienia|Ajustes|Settings
set_anc|Поколений предков|Pokoleń przodków|Generaciones de antepasados|Generations of ancestors
set_desc|Поколений потомков|Pokoleń potomków|Generaciones de descendientes|Generations of descendants
set_me|Кто я|Kim jestem|Quién soy|Who I am
set_me_hint|От этого человека сайт считает, кем вам приходится каждый — в профиле и в дереве.|Od tej osoby strona liczy, kim jest dla Ciebie każdy — w profilu i w drzewie.|Desde esta persona el sitio calcula su parentesco con cada uno, en el perfil y en el árbol.|The site counts from this person how everyone is related to you — on profiles and in the tree.
set_me_find|Найдите себя по имени|Znajdź siebie po imieniu|Búsquese por nombre|Find yourself by name
set_me_change|Выбрать другого|Wybierz kogoś innego|Elegir a otra persona|Pick someone else
set_lang|Язык|Język|Idioma|Language
set_theme|Тема|Motyw|Tema|Theme
set_theme_auto|Как в системе|Jak w systemie|Como en el sistema|Same as the system
set_theme_light|Светлая|Jasny|Clara|Light
set_theme_dark|Тёмная|Ciemny|Oscura|Dark
set_tree_light|Дерево всегда светлое|Drzewo zawsze jasne|Árbol siempre claro|Tree always light
set_all|все|wszystkie|todas|all
set_saved|Настройки хранятся только в этом браузере.|Ustawienia są zapisane tylko w tej przeglądarce.|Los ajustes se guardan solo en este navegador.|Settings are stored only in this browser.
tr_ai|Перевод сделан ИИ и ещё не проверен человеком.|Tłumaczenie wykonała SI i nie zostało jeszcze sprawdzone przez człowieka.|Traducción hecha por IA, aún no revisada por una persona.|Translated by AI, not yet reviewed by a person.
tr_stale|Русский текст изменился после перевода — перевод может отставать.|Tekst rosyjski zmienił się po tłumaczeniu — tłumaczenie może być nieaktualne.|El texto ruso cambió después de la traducción; puede estar desactualizada.|The Russian text changed after translation — it may be out of date.
tr_missing|Перевода на этот язык пока нет — ниже русский текст.|Nie ma jeszcze tłumaczenia — poniżej tekst rosyjski (użyj „Przetłumacz” w przeglądarce).|Aún no hay traducción — abajo está el texto en ruso (use «Traducir» en el navegador).|No translation yet — the Russian text is below (use your browser's Translate).
facts|Факты с источниками|Fakty ze źródłami|Hechos con fuentes|Facts with sources
conf_high|уверенно|pewne|seguro|certain
conf_normal|обычно|zwykłe|normal|usual
conf_low|под вопросом|niepewne|dudoso|uncertain
prov_family|семья|rodzina|familia|family
prov_found|найдено|znalezione|encontrado|found
prov_other_tree|чужое дерево|cudze drzewo|otro árbol|other tree
prov_inference|вывод|wniosek|deducción|inference
src_of|Источники о нём|Źródła o tej osobie|Fuentes sobre esta persona|Sources about this person
documents|Документы|Dokumenty|Documentos|Documents
doc_pdf|PDF|PDF|PDF|PDF
doc_text|Текст|Tekst|Texto|Text
doc_pages|{0} стр.|{0} str.|{0} pág.|{0} p.
doc_private|по паролю|z hasłem|con contraseña|password only
doc_kind_metrics|Метрики|Metryki|Partidas parroquiales|Parish records
doc_kind_civil|Свидетельство ЗАГС|Akt stanu cywilnego|Acta del registro civil|Civil certificate
doc_kind_passport|Паспорт|Paszport|Pasaporte|Passport
doc_kind_labor|Трудовая книжка|Książeczka pracy|Libreta de trabajo|Work record book
doc_kind_military|Военные документы|Dokumenty wojskowe|Documentos militares|Military papers
doc_kind_education|Образование|Wykształcenie|Educación|Education
doc_kind_awards|Награды|Odznaczenia|Condecoraciones|Awards
doc_kind_personal|Анкеты и характеристики|Ankiety i opinie|Formularios y referencias|Forms and references
doc_kind_certificate|Справка|Zaświadczenie|Certificado|Certificate
doc_kind_letter|Письмо|List|Carta|Letter
doc_kind_lists|Списки|Spisy|Listas|Lists
doc_kind_other|Другое|Inne|Otro|Other
place_states|Государства по годам|Państwa według lat|Estados por años|States by year
states_from|Своих записей нет — как у места выше:|Brak własnych zapisów — jak dla miejsca wyżej:|Sin datos propios — como el lugar superior:|No own entries — same as the place above:
place_people|Люди этого места|Ludzie z tego miejsca|Personas de este lugar|People of this place
place_about|О месте|O miejscu|Sobre el lugar|About the place
place_mentions|Упоминаются в биографиях|Wspomniani w biografiach|Mencionados en las biografías|Mentioned in biographies
place_inside|Что внутри|Co jest w środku|Qué hay dentro|Inside
place_nearby|Рядом|W pobliżu|Cerca|Nearby
place_similar|Похожие места|Podobne miejsca|Lugares similares|Similar places
map_tab_places|Все места|Wszystkie miejsca|Todos los lugares|All places
map_tab_houses|Дома|Domy|Casas|Homes
houses_intro|Дома, где жила семья: кто в них жил и когда, как был устроен дом и что с ним стало.|Domy, w których mieszkała rodzina: kto i kiedy w nich mieszkał, jak były zbudowane i co się z nimi stało.|Las casas donde vivió la familia: quién vivió en ellas y cuándo, cómo eran y qué fue de ellas.|The homes where the family lived: who lived there and when, what the house was like and what became of it.
houses_none|Пока ни одного дома.|Na razie żadnego domu.|Todavía no hay casas.|No homes yet.
house_people|Кто жил в доме|Kto mieszkał w domu|Quién vivió en la casa|Who lived here
house_residents|жили|mieszkało|vivieron|lived here
house_built|построен|zbudowany|construida|built
house_gone|дома не стало|domu już nie ma|la casa ya no existe|gone
house_no_date|годы неизвестны|lata nieznane|años desconocidos|years unknown
yr_until|до|do|hasta|until
yr_since|с|od|desde|since
house_kind_private|свой дом|dom własny|casa propia|private house
house_kind_apartment|квартира|mieszkanie|piso|flat
house_kind_barrack|барак|barak|barracón|barrack
house_kind_dorm|общежитие|hotel robotniczy|residencia|hostel
house_kind_hut|хата|chata|choza|cottage
person_homes|Дома, где жил(а)|Domy, w których mieszkał(a)|Casas donde vivió|Homes
km|км|km|km|km
src_people|О ком этот источник|O kim jest to źródło|De quién trata esta fuente|Who this source is about
loading|Загружается…|Wczytywanie…|Cargando…|Loading…
not_found|Такой страницы нет|Nie ma takiej strony|No existe esta página|No such page
load_error|Не удалось загрузить — проверьте связь и обновите страницу|Nie udało się wczytać — sprawdź połączenie i odśwież stronę|No se pudo cargar — revise la conexión y recargue la página|Could not load — check your connection and reload
tree_scheme|Схема|Schemat|Esquema|Chart
tree_steps|По шагам|Krok po kroku|Paso a paso|Step by step
tree_grand|Бабушки и дедушки|Dziadkowie|Abuelos|Grandparents
tree_parents|Родители|Rodzice|Padres|Parents
tree_center|В центре|W centrum|En el centro|In the centre
tree_steps_hint|Нажмите на человека — он встанет в центр; ещё раз — откроется его страница.|Kliknij osobę — stanie w centrum; jeszcze raz — otworzy się jej strona.|Toque a una persona: pasará al centro; otra vez: se abrirá su página.|Tap a person to put them in the centre; tap again to open their page.
nav_lifelines|Линии жизни|Linie życia|Líneas de vida|Lifelines
ll_intro|Жизни нескольких людей на одной шкале лет: что с каждым происходило в одно и то же время.|Życie kilku osób na jednej osi lat: co działo się z każdym w tym samym czasie.|Varias vidas en una misma escala de años: qué le pasaba a cada uno al mismo tiempo.|Several lives on one timeline: what happened to each of them at the same time.
ll_add_ph|Добавить человека…|Dodaj osobę…|Añadir persona…|Add a person…
ll_add|Добавить к сравнению:|Dodaj do porównania:|Añadir a la comparación:|Add to the comparison:
ll_parents|родителей|rodziców|padres|parents
ll_spouses|супругов|małżonków|cónyuges|spouses
ll_children|детей|dzieci|hijos|children
ll_siblings|братьев и сестёр|rodzeństwo|hermanos|siblings
ll_empty|Выберите людей — их жизни встанут одна под другой.|Wybierz osoby — ich życie ułoży się jedno pod drugim.|Elija personas: sus vidas se pondrán una debajo de otra.|Pick people — their lives will line up one under another.
ll_by_year|По годам|Według lat|Por años|By year
ll_compare|Сравнить линии жизни|Porównaj linie życia|Comparar líneas de vida|Compare lifelines
ll_ww1|Первая мировая|I wojna światowa|Primera Guerra Mundial|World War I
ll_ww2|Вторая мировая|II wojna światowa|Segunda Guerra Mundial|World War II
ll_clear|очистить|wyczyść|borrar|clear
ll_pick_hint|Нажмите на шкалу — выберется отрезок до следующего события; проведите по шкале — свой промежуток лет. Ниже останутся только эти годы.|Kliknij oś — zaznaczy się odcinek do następnego wydarzenia; przeciągnij po osi — własny przedział lat. Poniżej zostaną tylko te lata.|Pulse en la escala: se marcará el tramo hasta el siguiente suceso; arrastre sobre la escala: su propio intervalo de años. Abajo quedarán solo esos años.|Click the timeline to pick the stretch up to the next event; drag across it to pick your own span of years. Only those years stay below.
ll_show_all|все годы|wszystkie lata|todos los años|all years
audio_private|Запись разговора в семье. Текст на сайте пока не публикуется — только о ком она.|Nagranie rozmowy w rodzinie. Tekst nie jest jeszcze publikowany na stronie — tylko o kim jest.|Grabación de una conversación familiar. El texto aún no se publica en el sitio: solo de quién trata.|A recording of a family conversation. Its text is not published on the site yet — only who it is about.
oops|Что-то пошло не так на этой странице.|Coś poszło nie tak na tej stronie.|Algo salió mal en esta página.|Something went wrong on this page.
oops_reload|Обновить страницу|Odśwież stronę|Recargar la página|Reload the page
research_title|Что ещё искать|Czego jeszcze szukać|Qué más buscar|What to look for next
research_card|План поиска по предкам: какие архивы, записи и вопросы ещё впереди|Plan poszukiwań przodków: jakie archiwa, zapisy i pytania są jeszcze przed nami|Plan de búsqueda de los antepasados: qué archivos, registros y preguntas quedan por delante|Plan for tracing the ancestors: which archives, records and questions are still ahead
research_updated|Обновлено|Zaktualizowano|Actualizado|Updated
nav_news|Новое|Nowości|Novedades|What's new
news_title|Что нового в дереве|Co nowego w drzewie|Novedades del árbol|What's new in the tree
news_card|какие правки внесены и когда|jakie zmiany i kiedy|qué se cambió y cuándo|what changed and when
news_intro|Что поменялось в дереве по дням: новые люди, годы жизни, факты, биографии, фото и связи. Собрано сравнением дерева день за днём.|Co zmieniło się w drzewie dzień po dniu: nowe osoby, lata życia, fakty, biografie, zdjęcia i powiązania. Zebrane przez porównanie drzewa z dnia na dzień.|Qué cambió en el árbol día a día: personas nuevas, años de vida, hechos, biografías, fotos y vínculos. Se obtiene comparando el árbol de un día con el siguiente.|What changed in the tree day by day: new people, life years, facts, biographies, photos and links. Worked out by comparing the tree from one day to the next.
news_filter|Род:|Ród:|Rama:|Branch:
news_all|все роды|wszystkie rody|todas las ramas|all branches
news_day|новых людей: {0} · всего {1}|nowych osób: {0} · razem {1}|personas nuevas: {0} · en total {1}|new people: {0} · {1} in total
news_removed|объединено карточек: {0}|scalonych kart: {0}|fichas fusionadas: {0}|cards merged: {0}
news_new|новый в дереве|nowa osoba|nuevo en el árbol|new in the tree
news_life|годы|lata|años|years
news_facts|фактов: +{0}|faktów: +{0}|hechos: +{0}|facts: +{0}
news_bio_new|биография|biografia|biografía|biography
news_bio_edit|биография дополнена|biografia uzupełniona|biografía ampliada|biography updated
news_pics|фото: +{0}|zdjęć: +{0}|fotos: +{0}|photos: +{0}
news_parents|родители|rodzice|padres|parents
news_spouses|супруги|małżonkowie|cónyuges|spouses
news_more|ещё {0}|jeszcze {0}|{0} más|{0} more
news_empty|Правок пока нет.|Na razie bez zmian.|Todavía no hay cambios.|No changes yet.
stats_title|Состояние дерева|Stan drzewa|Estado del árbol|State of the tree
stats_card|сколько людей в каждом роду, как глубоко и чем подтверждено|ile osób w każdym rodzie, jak głęboko i czym potwierdzone|cuántas personas en cada rama, hasta dónde llega y con qué se confirma|how many people in each branch, how far back and what proves it
stats_total|Всего {0} человек · биографий {1} · с фото {2} · фактов {3}|Razem {0} osób · biografii {1} · ze zdjęciem {2} · faktów {3}|En total {0} personas · biografías {1} · con foto {2} · hechos {3}|{0} people in total · {1} biographies · {2} with photos · {3} facts
stats_people|по крови|z krwi|de sangre|blood relatives
stats_marriage|и {0} по браку|i {0} przez małżeństwo|y {0} por matrimonio|and {0} by marriage
stats_week|за неделю +{0}|w tydzień +{0}|en una semana +{0}|+{0} this week
stats_root|Начало рода|Początek rodu|Inicio de la rama|Branch starts with
stats_gen|Поколений вглубь|Pokoleń w głąb|Generaciones atrás|Generations back
stats_gen_note|выше деда или бабушки|ponad dziadka lub babcię|por encima del abuelo o la abuela|above the grandparent
stats_anc|Предков известно|Znanych przodków|Antepasados conocidos|Known ancestors
stats_oldest|Самый ранний год рождения|Najwcześniejszy rok urodzenia|Año de nacimiento más antiguo|Earliest birth year
stats_deepest|Дальше всех в глубину|Najdalej w głąb|Los más lejanos|Furthest back
stats_bios|Биографий|Biografii|Biografías|Biographies
stats_pics|С фото|Ze zdjęciem|Con foto|With photos
stats_docs|Рождения и смерти предков — чем подтверждены|Narodziny i zgony przodków — czym potwierdzone|Nacimientos y muertes de los antepasados: con qué se confirman|Ancestors' births and deaths: what proves them
stats_doc_record|документом|dokumentem|con documento|by a document
stats_doc_family|со слов семьи|z relacji rodziny|según la familia|family accounts
stats_doc_none|нечем|niczym|sin confirmar|nothing yet
stats_of|из {0}|z {0}|de {0}|of {0}
stats_note|Цифры пересчитываются при каждой сборке сайта. «Поколений вглубь» — сколько поколений предков известно над дедом или бабушкой, с которых начинается род. Линия под числом — как род рос по дням. Подтверждения считаются по предкам: рождение и смерть каждого (у живых — только рождение).|Liczby są przeliczane przy każdej budowie strony. „Pokoleń w głąb” — ile pokoleń przodków znamy ponad dziadkiem lub babcią, od których zaczyna się ród. Linia pod liczbą — jak ród rósł dzień po dniu. Potwierdzenia liczone są dla przodków: narodziny i zgon każdego (u żyjących — tylko narodziny).|Las cifras se recalculan en cada compilación del sitio. «Generaciones atrás»: cuántas generaciones de antepasados se conocen por encima del abuelo o la abuela con que empieza la rama. La línea bajo la cifra muestra cómo creció la rama día a día. Las confirmaciones se cuentan para los antepasados: nacimiento y muerte de cada uno (de los vivos, solo el nacimiento).|The numbers are recalculated every time the site is built. "Generations back" is how many generations of ancestors are known above the grandparent the branch starts with. The line under the number shows how the branch grew day by day. Proof is counted for the ancestors: each one's birth and death (for the living, birth only).
n_btn|Заметки|Notatki|Notas|Notes
n_btn_title|Заметки для Claude|Notatki dla Claude|Notas para Claude|Notes for Claude
n_close|Закрыть (кнопки «＋» спрячутся)|Zamknij (przyciski «＋» znikną)|Cerrar (los botones «＋» se ocultarán)|Close (the «＋» buttons will hide)
n_close_short|Закрыть|Zamknij|Cerrar|Close
n_general|Общее|Ogólne|General|General
n_general_ph|Что касается всего сайта или многих людей сразу…|Co dotyczy całej strony albo wielu osób naraz…|Lo que afecta a todo el sitio o a muchas personas a la vez…|Anything about the whole site or many people at once…
n_empty|Нажимайте «＋» у строки линии жизни, факта, фото, абзаца или выделите текст мышью — сюда попадёт этот кусок с адресом, где он лежит. Допишите, что не так, и нажмите «Скопировать для Claude».|Klikaj «＋» przy wierszu linii życia, fakcie, zdjęciu, akapicie albo zaznacz tekst myszą — trafi tu ten fragment z adresem, gdzie leży. Dopisz, co jest nie tak, i kliknij «Kopiuj dla Claude».|Pulse «＋» junto a una línea de la cronología, un dato, una foto o un párrafo, o seleccione texto con el ratón: aquí llegará ese fragmento con la dirección donde está. Escriba qué está mal y pulse «Copiar para Claude».|Click «＋» next to a timeline line, a fact, a photo or a paragraph, or select text with the mouse — that piece lands here with the address where it lives. Write what is wrong and click «Copy for Claude».
n_photos|Фото в заметках: {0}|Zdjęcia w notatkach: {0}|Fotos en las notas: {0}|Photos in notes: {0}
n_clear_confirm|Стереть все заметки? Сначала скопируйте или скачайте их.|Usunąć wszystkie notatki? Najpierw je skopiuj lub pobierz.|¿Borrar todas las notas? Primero cópielas o descárguelas.|Erase all notes? Copy or download them first.
n_copied|Скопировано|Skopiowano|Copiado|Copied
n_copy|Скопировать для Claude|Kopiuj dla Claude|Copiar para Claude|Copy for Claude
n_download|Скачать .md (положить в 1_sources/inbox/)|Pobierz .md (do 1_sources/inbox/)|Descargar .md (para 1_sources/inbox/)|Download .md (put it in 1_sources/inbox/)
n_download_short|Скачать .md|Pobierz .md|Descargar .md|Download .md
n_clear|Очистить всё|Wyczyść wszystko|Borrar todo|Clear all
n_remove|Удалить заметку|Usuń notatkę|Eliminar la nota|Delete the note
n_comment_ph|Что не так, как правильно, откуда знаете…|Co jest nie tak, jak powinno być, skąd wiesz…|Qué está mal, cómo es correcto, de dónde lo sabe…|What is wrong, what is right, how you know…
n_file|Заметки|Notatki|Notas|Notes
n_pin|В заметку|Do notatki|A la nota|Add to notes
n_pin_para|Абзац в заметку|Akapit do notatki|Párrafo a la nota|Paragraph to notes
n_pin_photo|Фото в заметку|Zdjęcie do notatki|Foto a la nota|Photo to notes
n_pin_quote|Цитата в заметку|Cytat do notatki|Cita a la nota|Quote to notes
n_pin_person|Заметка о человеке в целом|Notatka o osobie w całości|Nota sobre la persona en general|Note about the person as a whole
n_pin_place|Заметка о месте в целом|Notatka o miejscu w całości|Nota sobre el lugar en general|Note about the place as a whole
n_pin_family|Семья в заметку|Rodzina do notatki|Familia a la nota|Family to notes
n_just_note|Просто заметка|Zwykła notatka|Solo una nota|Just a note
nv_ok|Хорошее, оставить|Dobre, zostawić|Buena, dejarla|Good, keep it
nv_remove|Убрать — не относится|Usunąć — nie dotyczy|Quitar: no corresponde|Remove — not related
nv_better|Найти лучше|Znaleźć lepsze|Buscar una mejor|Find a better one
nv_wrong_place|Не то место или время|Nie to miejsce lub czas|Otro lugar u otra época|Wrong place or time
nv_wrong_person|Не тот человек|Nie ta osoba|Otra persona|Wrong person
nv_caption|Подпись неверна|Błędny podpis|Pie de foto incorrecto|Wrong caption
nv_wrong_date|Неверная дата|Błędna data|Fecha incorrecta|Wrong date
nv_wrong_text|Неверный текст|Błędny tekst|Texto incorrecto|Wrong text
nv_need_source|Нужен источник|Potrzebne źródło|Falta la fuente|Source needed
nv_other_person|Событие другого человека|Wydarzenie innej osoby|Suceso de otra persona|Another person's event
nv_add_event|Не хватает события рядом|Brakuje wydarzenia obok|Falta un suceso al lado|An event is missing nearby
nv_remove_line|Убрать — лишнее|Usunąć — zbędne|Quitar: sobra|Remove — not needed
nvl_ok|хорошее, оставить|dobre, zostawić|buena, dejarla|good, keep it
nvl_remove|убрать — не относится|usunąć — nie dotyczy|quitar: no corresponde|remove — not related
nvl_better|найти лучше (тема верная, снимок плохой)|znaleźć lepsze (temat dobry, zdjęcie słabe)|buscar una mejor (el tema es correcto, la foto es mala)|find a better one (right subject, poor picture)
nvl_wrong_place|не то место или время|nie to miejsce lub czas|otro lugar u otra época|wrong place or time
nvl_wrong_person|не тот человек|nie ta osoba|otra persona|wrong person
nvl_caption|подпись неверна|błędny podpis|pie de foto incorrecto|wrong caption
nvl_wrong_date|неверная дата|błędna data|fecha incorrecta|wrong date
nvl_wrong_text|неверный текст|błędny tekst|texto incorrecto|wrong text
nvl_need_source|нужен источник — откуда это?|potrzebne źródło — skąd to?|falta la fuente: ¿de dónde sale?|source needed — where is this from?
nvl_other_person|событие другого человека — перенести в его линию|wydarzenie innej osoby — przenieść do jej linii|suceso de otra persona: pasarlo a su cronología|another person's event — move it to their timeline
nvl_add_event|не хватает события рядом|brakuje wydarzenia obok|falta un suceso al lado|an event is missing nearby
nvl_remove_line|убрать — лишнее|usunąć — zbędne|quitar: sobra|remove — not needed
nk_whole|В целом|W całości|En general|As a whole
nk_about|Шапка (годы, места, занятие)|Nagłówek (lata, miejsca, zajęcie)|Encabezado (años, lugares, ocupación)|Header (years, places, occupation)
nk_lifeline|Строка линии жизни|Wiersz linii życia|Línea de la cronología|Timeline line
nk_fact|Факт из карточки|Fakt z karty|Dato de la ficha|Fact from the card
nk_stay|«Места и эпохи»|«Miejsca i epoki»|«Lugares y épocas»|«Places and eras»
nk_state|Государства по годам|Państwa według lat|Estados por años|States by year
nk_para|Абзац|Akapit|Párrafo|Paragraph
nk_quote|Цитата|Cytat|Cita|Quote
nk_photo|Фото|Zdjęcie|Foto|Photo
nt_person|человек|osoba|persona|person
nt_place|место|miejsce|lugar|place
nt_source|источник|źródło|fuente|source
nt_album|альбом фото|album zdjęć|álbum de fotos|photo album
n_md_title|Заметки к родословной — {0}|Notatki do drzewa genealogicznego — {0}|Notas para el árbol genealógico — {0}|Family tree notes — {0}
n_md_intro|Правки, собранные на сайте. Поправь исходники по правилам CLAUDE.md проекта (источник → карточка → биография), потом проверки. Человек, место, источник — по номеру (`cr_id` в свойствах карточки в `3_research/tree/`); биография — по пути; фото — по имени файла (на сайте пробелы и знаки стали `_`, длинное имя обрезано до 80 знаков) — в `media` карточек и в `1_sources/`. Цитата — текст, как он был на сайте в момент заметки.|Poprawki zebrane na stronie. Popraw źródła według zasad CLAUDE.md projektu (źródło → karta → biografia), potem kontrole. Osoba, miejsce, źródło — po numerze (`cr_id` we właściwościach karty w `3_research/tree/`); biografia — po ścieżce; zdjęcie — po nazwie pliku (na stronie spacje i znaki zamieniono na `_`, długą nazwę skrócono do 80 znaków) — w `media` kart i w `1_sources/`. Cytat — tekst taki, jaki był na stronie w chwili notatki.|Correcciones reunidas en el sitio. Corrige las fuentes según las reglas de CLAUDE.md del proyecto (fuente → ficha → biografía) y luego las comprobaciones. Persona, lugar, fuente: por número (`cr_id` en las propiedades de la ficha en `3_research/tree/`); biografía: por la ruta; foto: por el nombre del archivo (en el sitio los espacios y signos pasaron a `_`, un nombre largo se corta a 80 caracteres), en `media` de las fichas y en `1_sources/`. La cita es el texto tal como estaba en el sitio al tomar la nota.|Corrections collected on the site. Fix the sources following the project's CLAUDE.md rules (source → card → biography), then run the checks. Person, place, source — by number (`cr_id` in the card properties in `3_research/tree/`); biography — by path; photo — by file name (on the site spaces and signs became `_`, a long name is cut to 80 characters) — in the cards' `media` and in `1_sources/`. A quote is the text as it was on the site when the note was made.
n_md_page|Страница|Strona|Página|Page
n_md_bio|биография|biografia|biografía|biography
n_md_lang|страница на {0}|strona w {0}|página en {0}|page in {0}
n_md_photo|Фото|Zdjęcie|Foto|Photo
n_md_family|из media карточки|z media karty|de media de la ficha|from the card's media
n_md_found|найденное|znalezione|encontrada|found online
n_md_from|откуда|skąd|de dónde|from
n_md_ok|Проверены, оставить ({0})|Sprawdzone, zostawić ({0})|Revisadas, dejarlas ({0})|Checked, keep ({0})
nw_bio|Биография|Biografia|Biografía|Biography
nw_bio_tr|Биография (перевод {0})|Biografia (tłumaczenie {0})|Biografía (traducción {0})|Biography ({0} translation)
nw_lifeline|Линия жизни|Linia życia|Cronología|Timeline
os_style|по старому стилю: {0}|wg kalendarza juliańskiego: {0}|según el calendario juliano: {0}|Old Style: {0}
nw_memory|Память|Pamięć|Memoria|Memory
nw_row|{0}, строка {1}|{0}, wiersz {1}|{0}, línea {1}|{0}, line {1}
nw_questions|Открытые вопросы|Otwarte pytania|Preguntas abiertas|Open questions
nw_recollections|Воспоминания|Wspomnienia|Recuerdos|Recollections
nw_media|Фото (media карточки)|Zdjęcia (media karty)|Fotos (media de la ficha)|Photos (card media)
nw_docs|Документы|Dokumenty|Documentos|Documents
nw_portrait|Портрет (первое фото в media)|Portret (pierwsze zdjęcie w media)|Retrato (primera foto en media)|Portrait (first photo in media)
nw_stays|Места и эпохи|Miejsca i epoki|Lugares y épocas|Places and eras
nw_stays_calc|Места и эпохи (считается из фактов и эпох мест)|Miejsca i epoki (liczone z faktów i epok miejsc)|Lugares y épocas (calculado de los datos y las épocas de los lugares)|Places and eras (worked out from facts and place eras)
nw_life_photos|Фото мест из жизни|Zdjęcia miejsc z życia|Fotos de lugares de su vida|Photos of places from their life
nw_short|Коротко|W skrócie|En resumen|In short
nw_birth|Рождение|Urodzenie|Nacimiento|Birth
nw_death|Смерть|Śmierć|Muerte|Death
nw_occupation|Занятие|Zajęcie|Ocupación|Occupation
nw_family|Семья|Rodzina|Familia|Family
nw_family_links|Семья (связи в карточке)|Rodzina (powiązania w karcie)|Familia (vínculos en la ficha)|Family (links in the card)
nw_maybe|Возможно, связан|Możliwie powiązany|Posiblemente relacionado|Possibly linked
nw_facts|Факты (карточка)|Fakty (karta)|Datos (ficha)|Facts (card)
nw_states|Государства по годам|Państwa według lat|Estados por años|States by year
nw_states_from|Государства по годам (достались от «{0}»)|Państwa według lat (odziedziczone po «{0}»)|Estados por años (heredados de «{0}»)|States by year (inherited from «{0}»)
nw_source_text|Текст источника|Tekst źródła|Texto de la fuente|Source text
nw_research|Что ещё искать|Czego jeszcze szukać|Qué más buscar|What to look for next
nw_place_about|О месте|O miejscu|Sobre el lugar|About the place
nw_place_text|Текст карточки места|Tekst karty miejsca|Texto de la ficha del lugar|Place card text
nw_place_people|Люди этого места|Ludzie z tego miejsca|Personas de este lugar|People of this place
nw_mentions|Упоминаются в биографиях|Wspominani w biografiach|Mencionados en biografías|Mentioned in biographies
nw_house|Кто жил в доме|Kto mieszkał w domu|Quién vivió en la casa|Who lived in the house
nw_house_calc|Кто жил в доме (события «место жительства»)|Kto mieszkał w domu (wydarzenia «miejsce zamieszkania»)|Quién vivió en la casa (sucesos «lugar de residencia»)|Who lived in the house («residence» events)
nw_homes|Дома, где жил|Domy, w których mieszkał|Casas donde vivió|Houses where they lived
nw_photo|Фото|Zdjęcie|Foto|Photo
nw_addr_photos|Фото этого адреса|Zdjęcia tego adresu|Fotos de esta dirección|Photos of this address
nw_place_album|Альбом места «{0}»|Album miejsca «{0}»|Álbum del lugar «{0}»|Place album «{0}»
nw_album|Альбом «{0}»|Album «{0}»|Álbum «{0}»|Album «{0}»
nr_title|Разбор найденных фото|Przegląd znalezionych zdjęć|Revisión de las fotos encontradas|Review of found photos
nr_short|Разбор фото|Przegląd zdjęć|Revisión de fotos|Photo review
nr_count|оценено {0} из {1}|ocenione {0} z {1}|revisadas {0} de {1}|rated {0} of {1}
nr_only_new|только без оценки|tylko bez oceny|solo sin valorar|unrated only
nr_all_done|Все снимки оценены. Снимите галочку «только без оценки», чтобы пройти их заново.|Wszystkie zdjęcia ocenione. Odznacz «tylko bez oceny», aby przejrzeć je od nowa.|Todas las fotos están valoradas. Desmarque «solo sin valorar» para repasarlas de nuevo.|All photos are rated. Untick «unrated only» to go through them again.
nr_prev|Предыдущее|Poprzednie|Anterior|Previous
nr_next|Следующее|Następne|Siguiente|Next
nr_album|Альбом|Album|Álbum|Album
nr_address|Адрес|Adres|Dirección|Address
nr_whose|Чья история|Czyja historia|De quién es la historia|Whose story
nr_exact|Точность|Dokładność|Precisión|Accuracy
nr_question|Под вопросом|Pod znakiem zapytania|En duda|In question
nr_from|Откуда|Skąd|De dónde|Source
nr_file|Файл|Plik|Archivo|File
nr_write|Дописать словами|Dopisz słowami|Escribir con palabras|Add in words
nr_keys|← → листать · 1–6 оценить и дальше · Enter — написать, что именно не так|← → przewijaj · 1–6 oceń i dalej · Enter — napisz, co dokładnie jest nie tak|← → pasar · 1–6 valorar y seguir · Enter: escribir qué está mal exactamente|← → browse · 1–6 rate and move on · Enter — write what exactly is wrong
lb_close|Закрыть|Zamknij|Cerrar|Close
lb_prev|Назад|Wstecz|Anterior|Back
lb_next|Вперёд|Dalej|Siguiente|Forward
"""
I18N = {code: {} for code, _ in LANGS}
for row in I18N_ROWS.strip().splitlines():
    key, *vals = row.split("|")
    for (code, _), v in zip(LANGS, vals):
        I18N[code][key] = v
# заголовок главной с именем рода — у каждого дерева свой: ftree.toml, [site.home_title] (ru / pl / es / en);
# нет раздела — просто «Родословная»
for code, v in dict(paths.tree_conf("site.home_title", {})).items():
    if code in I18N:
        I18N[code]["home_title"] = str(v)
# «Unknown (I25)» — имя неизвестно: подписываем так же, как пустое место в дереве («неизвестно» / «nieznany» …);
# адрес страницы остаётся по номеру, он посчитан выше
def initials(name):
    """Инициалы, как в телефонной книге: первая буква имени и фамилии («Иван Ясенев» → «ИЯ», «Прокоп» → «П»);
    скобки («Мария (2007)») и прозвища в кавычках не считаются"""
    ws = [w for w in re.sub(r"\(.*?\)", " ", name).split() if w[0].isalpha()]
    return (ws[0][0] + (ws[-1][0] if len(ws) > 1 else "")).upper() if ws else ""


for d in people.values():
    d["unk"] = bool(re.match(r"Unknown\b", d["name"]))
    if d["unk"]:
        d.update({code: I18N[code]["unknown"] for code in ("ru", "en", "pl", "es")})
    # круг без фото: инициалы (у неизвестного — пусто, будет значок) и цвет — всегда один и тот же для человека, от его номера
    d["ini"] = None if d["unk"] else {code: initials(d.get(code) or d["en"]) for code in ("ru", "en", "pl", "es")}
    d["col"] = int(hashlib.md5(d["id"].encode()).hexdigest(), 16) % 8








# ---------- страницы ----------

# Контакты живых людей и номера домов — на сайт не идут: site_data/privacy.py (no_contacts, no_address_html).



















def lifespan(d):
    return life.lifespan(d["f"].get("born"), d["f"].get("died"),
                         any(e.get("event_type") in ("death", "burial") for e in person_events.get(d["stem"], [])))


HOME = ("ev_birth", "ev_residence", "ev_child")  # точки, где человек жил; остальные события жильё не меняют
VISIT, VISIT_PAD = ("ev_custom", "ev_occupation", "ev_education", "ev_war", "ev_kin"), 3  # короткие остановки: снимки ±3 года


def person_stays(d):
    """Где человек был и в какие годы: [(с, по, событие, место)]. Точка — рождение, смерть и события с местом и годом.
    Дом (рождение, место жительства, рождение ребёнка) — от этой точки до следующего дома в другом месте; после
    последнего — до смерти, живой — до сегодня. Учёба, работа, брак — только годы самого события. Год смерти (или рождения) неизвестен — до последнего года, про который что-то известно (не додумываем).
    Смерть и похороны — только их год. Событие «1941 - 1945» — не меньше, чем до 1945. Рождение ребёнка — тоже точка."""
    f = d["f"]
    stops = {}
    def add(y0, y1, ev, t):
        k = (y0, ev, t)
        stops[k] = max(stops.get(k, y0), y1 or y0)
    for key, ev, pk in (("born", "ev_birth", "birth_place"), ("died", "ev_death", "death_place")):
        if year(f.get(key)) and f.get(pk) and link_target(f[pk]) in places:
            add(year(f[key]), None, ev, link_target(f[pk]))
    for e in person_events.get(d["stem"], []):
        t = link_target(e["place"]) if e.get("place") else None
        if t in places and year(e.get("date")) and f"ev_{e.get('event_type')}" in I18N["ru"]:
            ys = [int(x) for x in re.findall(r"\d{4}", str(e["date"]))]
            add(ys[0], max(ys), f"ev_{e['event_type']}", t)
    for cid in d["children"]:  # где родился ребёнок — там в тот год были и родители
        c = by_id[cid]["f"]
        if year(c.get("born")) and c.get("birth_place") and link_target(c["birth_place"]) in places:
            add(year(c["born"]), None, "ev_child", link_target(c["birth_place"]))
    order = sorted(stops)
    if not order:
        return []
    alive = bool(year(f.get("born"))) and "–" not in lifespan(d)  # год рождения неизвестен — живым не считаем
    last_known = max(max(stops.values()), year(f.get("born")) or 0)
    end_of_life = datetime.date.today().year if alive else (year(f.get("died")) or last_known)
    def same(a, b):  # Минск и «Минск — Садовая, 12» — не переезд
        return a in place_chain(b) or b in place_chain(a)
    out = []
    for y0, ev, t in order:
        if ev in HOME:
            nxt = next((k[0] for k in order if k[0] > y0 and k[1] in HOME + ("ev_death",) and not same(k[2], t)), None)
            y1 = nxt if nxt else end_of_life
        else:  # учёба, работа, брак, смерть, похороны — только их годы; дом они не меняют
            y1 = y0
        out.append((y0, max(y1, stops[(y0, ev, t)]), ev, t))
    return out




def origin_of(src):
    """Происхождение заметки-источника: семья / найдено / чужое дерево / вывод проекта."""
    p = md_file(link_target(src))
    if not p:
        return ""
    f, _ = read_note(p)
    return str(f.get("origin") or "")


def stats(d):
    """Сколько у человека материала — для значков в дереве, в списке людей и в шапке страницы."""
    f, body = d["f"], d["body"]
    bio = bool(bio_text(d))
    texts = re.search(r"^## Тексты.*?\n(.*?)(?=^## |\Z)", body, re.S | re.M)
    facts = re.search(r"^### Факты \(с источником\)\n(.*?)(?=^##|\Z)", body, re.S | re.M)
    origins = [origin_of(x) for x in as_list(f.get("sources"))]
    return {"bio": bio,
            "texts": len(re.findall(r"^- \[\[", texts.group(1), re.M)) if texts else 0,
            "facts": len(re.findall(r"^- ", facts.group(1), re.M)) if facts else 0,
            "fam": origins.count("семья"), "web": origins.count("найдено"), "tree": origins.count("чужое дерево"),
            "pics": sum(1 for m in as_list(f.get("media")) if photo(m)),
            "langs": sorted(translations.get(d["id"], {}))}


# Значки — контуры из Material Icons (Google, лицензия Apache 2.0), встроены как SVG: без шрифтов и загрузок
ICONS = {
    "search": "M15.5 14h-.79l-.28-.27A6.471 6.471 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z",
    "help": "M11 18h2v-2h-2v2zm1-16C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm0-14c-2.21 0-4 1.79-4 4h2c0-1.1.9-2 2-2s2 .9 2 2c0 2-3 1.75-3 5h2c0-2.25 3-2.5 3-5 0-2.21-1.79-4-4-4z",
    "settings": "M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z",
    "bio": "M21 5c-1.11-.35-2.33-.5-3.5-.5-1.95 0-4.05.4-5.5 1.5-1.45-1.1-3.55-1.5-5.5-1.5S2.45 4.9 1 6v14.65c0 .25.25.5.5.5.1 0 .15-.05.25-.05C3.1 20.45 5.05 20 6.5 20c1.95 0 4.05.4 5.5 1.5 1.35-.85 3.8-1.5 5.5-1.5 1.65 0 3.35.3 4.75 1.05.1.05.15.05.25.05.25 0 .5-.25.5-.5V6c-.6-.45-1.25-.75-2-1zm0 13.5c-1.1-.35-2.3-.5-3.5-.5-1.7 0-4.15.65-5.5 1.5V8c1.35-.85 3.8-1.5 5.5-1.5 1.2 0 2.4.15 3.5.5v11.5z",
    "texts": "M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-5 14H7v-2h7v2zm3-4H7v-2h10v2zm0-4H7V7h10v2z",
    "facts": "M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34a.9959.9959 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z",
    "fam": "M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z",
    "web": "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z",
    "tree": "M22 11V3h-7v3H9V3H2v8h7V8h2v10h4v3h7v-8h-7v3h-2V8h2v3z",
    "pics": "M21 19V5c0-1.1-.9-2-2-2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2zM8.5 13.5l2.5 3.01L14.5 12l4.5 6H5l3.5-4.5z",
    # сколько детей — в карточке дерева: видно и тогда, когда ветка детей свёрнута
    "kids": "M6.5 2c1.1 0 2 .9 2 2s-.9 2-2 2-2-.9-2-2 .9-2 2-2zm9 7.5c0 .83.67 1.5 1.5 1.5s1.5-.67 1.5-1.5S17.83 8 17 8s-1.5.67-1.5 1.5zm3 2.5h-2.84c-.58.01-1.14.32-1.45.86l-.92 1.32L9.72 8c-.37-.63-1.03-.99-1.71-1H5c-1.1 0-2 .9-2 2v6h1.5v7h5V11.61L12.03 16h2.2l.77-1.1V22h4v-5h1v-3.5c0-.82-.67-1.5-1.5-1.5z",
    "person": "M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z",
    "map": "M20.5 3l-.16.03L15 5.1 9 3 3.36 4.9c-.21.07-.36.25-.36.48V20.5c0 .28.22.5.5.5l.16-.03L9 18.9l6 2.1 5.64-1.9c.21-.07.36-.25.36-.48V3.5c0-.28-.22-.5-.5-.5zM15 19l-6-2.11V5l6 2.11V19z",
    "source": "M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z",
    "share": "M18 16.08c-.76 0-1.44.3-1.96.77L8.91 12.7c.05-.23.09-.46.09-.7s-.04-.47-.09-.7l7.05-4.11c.54.5 1.25.81 2.04.81 1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3c0 .24.04.47.09.7L8.04 9.81C7.5 9.31 6.79 9 6 9c-1.66 0-3 1.34-3 3s1.34 3 3 3c.79 0 1.5-.31 2.04-.81l7.12 4.16c-.05.21-.08.43-.08.65 0 1.61 1.31 2.92 2.92 2.92s2.92-1.31 2.92-2.92-1.31-2.92-2.92-2.92z",
    "translate": "M12.87 15.07l-2.54-2.51.03-.03c1.74-1.94 2.98-4.17 3.71-6.53H17V4h-7V2H8v2H1v1.99h11.17C11.5 7.92 10.44 9.75 9 11.35 8.07 10.32 7.3 9.19 6.69 8h-2c.73 1.63 1.73 3.17 2.98 4.56l-5.09 5.02L4 19l5-5 3.11 3.11.76-2.04zM18.5 10h-2L12 22h2l1.12-3h4.75L21 22h2l-4.5-12zm-2.62 7l1.62-4.33L19.12 17h-3.24z",
    "event": "M17 12h-5v5h5v-5zM16 1v2H8V1H6v2H5c-1.11 0-1.99.9-1.99 2L3 19c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2h-1V1h-2zm3 18H5V8h14v11z",
    "home": "M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z",
    "place": "M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z",
    # режим заметок (web/src/app/notes): панель справа, «＋» у данных, разбор фото
    "note": "M3 10h11v2H3v-2zm0-2h11V6H3v2zm0 8h7v-2H3v2zm15.01-3.13l.71-.71c.39-.39 1.02-.39 1.41 0l.71.71c.39.39.39 1.02 0 1.41l-.71.71-2.12-2.12zm-.71.71l-5.3 5.3V21h2.12l5.3-5.3-2.12-2.12z",
    "add": "M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z",
    "close": "M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z",
    "check": "M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z",
    "delete": "M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z",
    "copy": "M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z",
    "download": "M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z",
    "renew": "M17.65 6.35C16.2 4.9 14.21 4 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08c-.82 2.33-3.04 4-5.65 4-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z",
    "place_off": "M12 6.5c1.38 0 2.5 1.12 2.5 2.5 0 .74-.33 1.39-.83 1.85l3.63 3.63c.98-1.86 1.7-3.8 1.7-5.48 0-3.87-3.13-7-7-7-1.98 0-3.76.83-5.04 2.15l3.19 3.19c.46-.52 1.11-.84 1.85-.84zm4.37 9.6l-4.63-4.63-.11-.11L3.27 3 2 4.27l3.18 3.18C5.07 7.95 5 8.47 5 9c0 5.25 7 13 7 13s1.67-1.85 3.38-4.35L18.73 21 20 19.73l-3.63-3.63z",
    "person_off": "M14 8c0-2.21-1.79-4-4-4S6 5.79 6 8s1.79 4 4 4 4-1.79 4-4zm3 2v2h6v-2h-6zM2 18v2h16v-2c0-2.66-5.33-4-8-4s-8 1.34-8 4z",
    "quote": "M6 17h3l2-4V7H5v6h3zm8 0h3l2-4V7h-6v6h3z",
    "review": "M20 2H4c-1.1 0-1.99.9-1.99 2L2 22l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zM6 14v-2.47l6.88-6.88c.2-.2.51-.2.71 0l1.77 1.77c.2.2.2.51 0 .71L8.47 14H6zm12 0h-7.5l2-2H18v2z",
    "prev": "M15.41 7.41L14 6l-6 6 6 6 1.41-1.41L10.83 12z",
    "next": "M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z",
    # «Что нового» и «Состояние дерева»
    "history": "M13 3a9 9 0 0 0-9 9H1l3.89 3.89.07.14L9 12H6c0-3.87 3.13-7 7-7s7 3.13 7 7-3.13 7-7 7c-1.93 0-3.68-.79-4.94-2.06l-1.42 1.42A8.954 8.954 0 0 0 13 21a9 9 0 0 0 0-18zm-1 5v5l4.28 2.54.72-1.21-3.5-2.08V8H12z",
    "stats": "M5 9.2h3V19H5zM10.6 5h2.8v14h-2.8zm5.6 8H19v6h-2.8z",
}








def life_photos(d, stays):
    """Фото мест из жизни человека — для его страницы и для выгрузки JSON (одно правило на обоих).
    Снимки адреса (района) — если он был на этом адресе, общие снимки города — если был в городе; и то и другое — только из
    тех лет, когда он там был. Снимков без года не показываем. Исключение — сам его дом (адрес, где он жил или бывал у
    родных): дом показываем и на снимках других лет, «было — стало». Короткая остановка (проездом, работа, учёба — год-два)
    — снимки ±VISIT_PAD лет: ровно того года почти никогда нет, а порт и пароход за три года не меняются.
    → (группы [(("addr", место) или slug альбома, снимки)], адреса со снимками не из его лет, [(slug альбома, снимки из
    found_photos карточки)])"""
    chosen = {}  # альбом → снимки
    for y0, y1, ev, t in stays:
        if ev in VISIT and y1 - y0 <= 1:
            y0, y1 = y0 - VISIT_PAD, y1 + VISIT_PAD
        chain = place_chain(t)  # «Садовая, 12» → Заречье → Минск: снимки дома, района и общие снимки города
        pool = [r for c in chain for r in addr_photos.get(c, [])]
        pool += [r for c in chain if c in place_albums for r in place_albums[c]["photos"] if not r["addr"]]
        pool += [r for c in chain for r in like_photos.get(c, [])]  # «≈ не наше» — с красной меткой
        for r in pool:
            if r["year"] and (y0 <= r["year"] <= y1 or r["addr"] == t and places[t]["f"].get("place_type") == "house"):
                # снимки его адреса (институт, дом на Луговой, 5) — своей полоской, чтобы их не вытеснили общие виды города
                chosen.setdefault(("addr", r["addr"]) if r["addr"] else r["album"]["slug"], {})[r["path"]] = r
    groups = [(k, sorted(rs.values(), key=lambda r: (r["year"], r["desc"])))
              for k, rs in sorted(chosen.items(), key=lambda kv: not isinstance(kv[0], tuple))]
    other = [t for t in dict.fromkeys(t for _, _, _, t in stays) if t in addr_photos
             and not any(r["path"] in chosen.get(("addr", t), {}) for r in addr_photos[t])]
    # «found_photos:» в карточке — начала имён найденных снимков о его жизни, не привязанных к месту (паровозы
    # на работе Анны Ясеневой, грузовик Ивана Ясенева). Полоской по альбому, после мест.
    pre = [N(str(x)) for x in as_list(d["f"].get("found_photos"))]
    mine = {}
    for a in albums.values():
        for r in a["photos"]:
            if any(N(r["path"].stem).startswith(x) for x in pre):
                mine.setdefault(a["slug"], []).append(r)
    return groups, other, [(slug, sorted(rs, key=lambda r: (r["year"] or 9999, r["desc"]))) for slug, rs in mine.items()]






place_people = {}
place_events = {}  # (место, cr_id) → [(ключ события, дата, коротко что было)] — «кем и когда» на карте, а не просто «работа»
for d in people.values():
    for key, what in (("birth_place", "pp_born"), ("death_place", "pp_died")):
        t = link_target(d["f"].get(key)) if d["f"].get(key) else None
        if t in places:
            place_people.setdefault(t, []).append((d["id"], what))
for e in events:
    t = link_target(e["place"]) if e.get("place") else None
    if t in places and f"ev_{e.get('event_type')}" in I18N["ru"]:
        for who in dict.fromkeys(link_target(x) for x in as_list(e.get("persons"))):
            if who in people:
                place_people.setdefault(t, []).append((people[who]["id"], f"ev_{e['event_type']}"))
                place_events.setdefault((t, people[who]["id"]), []).append((f"ev_{e['event_type']}", e.get("date"), str(e.get("description") or "")))
# ссылка на место в строке факта — тоже «был здесь» (брак в Лесогорске, отъезд из Вербичей); страна, область и район —
# фон, не точка жизни (как в check_fact_places.py). Суть — подпись и текст факта.
FACT_LINE = re.compile(r"^- \*\*(.+?):\*\* (.+?) — \*источник:", re.M)
for d in people.values():
    facts_part = re.split(r"\n#{1,3} ", d["body"].partition("### Факты (с источником)")[2])[0]
    for label, value in FACT_LINE.findall(facts_part):
        for t in dict.fromkeys(link_target(x) for x in re.findall(r"\[\[[^\]]+\]\]", value)):
            if t in places and places[t]["f"].get("place_type") not in ("country", "region", "district", "river") \
                    and label not in ("Заметка", "Ссылка"):
                place_people.setdefault(t, []).append((d["id"], "pp_fact"))
                place_events.setdefault((t, d["id"]), []).append(("pp_fact", None, f"{label}: {value}"))


# ---------- места по годам ----------
# У места в карточке есть раздел «## Государства по годам»: «- 1921–1939 — **Польша** (II Речь Посполитая)».
# Нет раздела — берём у места-родителя (parent_place): кладбище Бреста → Брест.
def era_periods(stem, seen=()):
    pl = places.get(stem)
    if not pl or stem in seen:
        return [], None
    m = re.search(r"^## Государства по годам\n(.*?)(?=^## |\Z)", pl["body"], re.S | re.M)
    if not m:
        par = pl["f"].get("parent_place")
        return era_periods(link_target(par), seen + (stem,)) if par else ([], None)
    periods = []
    for line in re.findall(r"^- (.+)$", m.group(1), re.M):
        for seg in line.split(";"):
            seg = re.sub(r"[*_]", "", seg).strip()
            if mm := re.match(r"(\d{4})\s*[–-]\s*(\d{4})\s*—\s*(.+)", seg):
                periods.append((int(mm[1]), int(mm[2]), mm[3].strip()))
            elif mm := re.match(r"до\s+(\d{4})\s*—\s*(.+)", seg):
                periods.append((0, int(mm[1]) - 1, mm[2].strip()))
            elif mm := re.match(r"с\s+(\d{4})\s*—\s*(.+)", seg):
                periods.append((int(mm[1]), 9999, mm[2].strip()))
    return periods, stem


def era_at(stem, y):
    """Какое государство было в этом месте в этом году: самый узкий подходящий период («1941–1944 — оккупация» важнее «1939–1991 — СССР»)."""
    periods, src = era_periods(stem)
    hits = [x for x in periods if x[0] <= y <= x[1]]
    return (min(hits, key=lambda x: x[1] - x[0])[2], src) if hits else (None, src)






# ---------- переводы биографий ----------
# Русский — основной язык. Перевод — отдельный файл на человека и язык:
#   3_research/tree/translations/<es|pl|en>/biographies/<Имя карточки>.md (общая схема — paths.tr_path)
# В шапке: person_id (номер человека), name_local (имя на этом языке), source_hash (отпечаток русского текста
# в момент перевода). Изменился русский текст — отпечаток не совпадёт, на сайте появится пометка «перевод отстаёт».
TRANSLATIONS = paths.TRANSLATIONS


def bio_refs(d):
    """Биографии человека: своя — по имени карточки (tree/biographies/<Имя> — биография.md), строки в карточке для неё
    не нужно; затем — встроенное в «Рассказ» и прочие ссылки строки «**Биография:**» (заметки на двоих)."""
    own = paths.bio_path(d["stem"])
    body = d["body"]
    story = re.search(r"^## Рассказ\n(.*?)(?=^## |\Z)", body, re.S | re.M)
    refs = re.findall(r"!\[\[([^\]]+)\]\]", story.group(1)) if story else []
    refs += re.findall(r"\*\*Биография:\*\*\s*\[\[([^\]|]+)", NESTED.sub(r"[[\1 \2]]", body))
    first = [N(own.relative_to(paths.ROOT).as_posix())] if own.exists() else []
    return list(dict.fromkeys(first + [N(r) for r in refs]))


def bio_text(d):
    return "\n\n".join(t.strip() for t in (embed(r) for r in bio_refs(d)) if t.strip())


# Линия жизни в биографии — таблица, где одна колонка — дата («Когда», «Год», «Годы», «Дата»), другая — «Что»
# («Что было», «Что произошло», «Что известно»). На сайте она не стоит в тексте, а сливается с событиями дерева в одну
# хронологию («Что» — колонка сразу за датой: «Год | Имя | … | Что известно» — это список детей, а не линия жизни); лишние колонки («Источник», «Статус», «Время на записи») идут мелкой строкой под записью. Название раздела
# любое: «Линия жизни», «Вся жизнь в одной таблице», «Жизнь по годам» или таблица сразу под именем. Всегда берутся
# разделы «Линия жизни» и «Даты, подтверждённые документом» (там колонки могут быть «Когда | Воспоминания | …»).
# Не берутся: таблица под заголовком другого человека («## Анна Ясенева» со строкой «**В дереве:** [[…]]» под ним,
# в старых заголовках — «## Анна … [[Анна Ясенева]]») внутри биографии отца и таблицы-справки («Когда | Чья власть | Что это значило», «Год | Сколько лет | Что это значит»).
# Переводы (es, pl, en) — те же таблицы с переведёнными заголовками и колонками: в тексте перевода их тоже не показываем.
LIFE_HEAD = re.compile(r"Линия жизни|Даты, подтверждённые документом|Línea de vida|Linia życia|Life ?line|Timeline", re.I)
# «Память» — что было после смерти человека: вещи в музее, книга или статья о нём, перезахоронение, доска, посмертная
# реабилитация. Таблица та же («Когда | Что | Где»), стоит сразу за линией жизни; в линию жизни не попадает
# (split_lifeline(text, memory=True) — только она). Правило — навык biography.
MEMORY_HEAD = re.compile(r"^\W*(Память|Pamięć|Memoria|Remembrance|Memory)\W*$", re.I)
WHEN_COL = re.compile(r"(когда|год|годы|дата|даты|cuándo|año|años|fecha|fechas|kiedy|rok|lata|data|daty|when|year|years|date|dates)$", re.I)
WHAT_COL = re.compile(r"(что( было| произошло| известно)?|qué|co|what)$", re.I)
IN_TREE = re.compile(r"\s*\*\*(В дереве|En el árbol|W drzewie|In the tree):\*\*")
TABLE = re.compile(r"^((?:\|[^\n]*(?:\n|$))+)", re.M)


def in_other_person(text, pos):
    """Место внутри раздела другого человека: над ним есть заголовок со строкой «**В дереве:** [[…]]» сразу под ним
    (ребёнок, жена внутри биографии родителя). Свой заголовок человека во встраивание не попадает."""
    stack = []
    for h in re.finditer(r"^(#+)[ \t]+[^\n]*$", text[:pos], re.M):
        lvl = len(h.group(1))
        stack = [x for x in stack if x[0] < lvl] + [(lvl, bool(IN_TREE.match(text[h.end():])))]
    return any(other for _, other in stack)


def split_lifeline(text, memory=False):
    """Текст биографии без таблиц линии жизни + строки таблиц: (ключ сортировки, «когда», «что», [(колонка, значение)]).
    memory=True — то же для таблицы «Память» (после смерти); без него таблица «Память» в линию жизни не идёт."""
    rows, last, cut = [], "0000", []
    head_re = MEMORY_HEAD if memory else LIFE_HEAD
    cells = lambda r: [c.strip() for c in r.replace("\\|", "\x00").strip().strip("|").split("|")]
    plain = lambda h: re.sub(r"[*_`⭐]", "", h).strip()
    for m in TABLE.finditer(text):
        lines = [r for r in m.group(1).splitlines() if r.strip() and not re.fullmatch(r"[\s|:-]+", r)]
        if len(lines) < 2:
            continue
        hm = list(re.finditer(r"^(#+)[ \t]+([^\n]*)$", text[:m.start()], re.M))
        heading = hm[-1] if hm else None
        # между заголовком «Линия жизни» и таблицей — не больше короткой пояснительной строки: тогда уходит и заголовок
        lead = text[heading.end():m.start()].strip() if heading else ""
        if bool(heading is not None and MEMORY_HEAD.search(heading.group(2))) != memory:
            continue
        bare = heading is not None and head_re.search(heading.group(2)) and len(lead) < 300 and "\n\n" not in lead
        if in_other_person(text, m.start()):
            # линия жизни ребёнка или жены внутри биографии родителя: у них своя страница — здесь не показываем вовсе
            if bare:
                cut.append((heading.start(), m.end()))
            continue
        head = [plain(h) for h in cells(lines[0])]
        wi = next((i for i, h in enumerate(head) if WHEN_COL.match(h)), None)
        named = heading is not None and head_re.search(heading.group(2))
        what = (1 if wi == 0 else 0) if wi is not None else None  # «Что» — сразу за датой (или первая, если дата не первая)
        if not named and (wi is None or len(head) < 2 or not WHAT_COL.match(head[what])
                          or (heading is not None and "[[" in heading.group(2))):
            continue
        wi = wi or 0
        order = [wi, 1 if wi == 0 else 0] + [i for i in range(len(head)) if i not in (wi, 1 if wi == 0 else 0)]
        head = [head[i] for i in order]
        for r in lines[1:]:
            c = [x.replace("\x00", "\\|") for x in cells(r)]
            if len(c) < 2:
                continue
            c = [c[i] for i in order if i < len(c)] + c[len(order):]
            when = c[0]
            # сортируем по первой дате ячейки (правило дат — tools/scripts/dates.py): «1925 – 01.08.1928» — это 1925;
            # у строки без даты, «(без даты)», — дата предыдущей строки
            g = dates.ru_or_none(when)
            if g and g.sort_key():
                last = g.sort_key()
            extra = [(head[i] if i < len(head) else "", v) for i, v in enumerate(c[2:], 2) if v not in ("", "—", "-")]
            rows.append((last, when, c[1], extra))
        # из текста убираем таблицу, а её заголовок — если это «Линия жизни» или в разделе, кроме таблицы, ничего нет
        start = m.start()
        if named and bare:
            start = heading.start()
        elif heading and not text[heading.end():m.start()].strip():
            after = text[m.end():]
            nxt = re.search(r"^(#+)[ \t]", after, re.M)
            rest = after[:nxt.start()] if nxt else after
            if not re.sub(r"^-{3,}\s*$", "", rest, flags=re.M).strip() and (not nxt or len(nxt.group(1)) <= len(heading.group(1))):
                start = heading.start()
        cut.append((start, m.end()))
    for a, b in reversed(cut):
        text = text[:a] + text[b:]
    return text, rows


# «Воспоминания» — сценки, которые кто-то помнит о человеке: не биография и не факт для дерева, а то, каким его видели.
# Раздел `## Воспоминания` (после «Каким был»), в нём каждое — `### Название`, первой строкой курсивом — кто вспоминает
# и откуда: `*Вспоминает [[Карточка|Имя]], внучка · А08, 53:25*`, дальше — рассказ или цитата. На сайте — свой блок
# (biography.recollections), из текста биографии раздел убирается. Правило — навык biography.
RECOLL_HEAD = re.compile(r"^(#+)[ \t]+(Воспоминания|Wspomnienia|Recuerdos|Memories|Recollections)[ \t]*$", re.M | re.I)
RECOLL_BY = re.compile(r"^\*([^*\n]+)\*[ \t]*$", re.M)


# «Открытые вопросы» — на сайте свёрнутым блоком (biography.questions), из текста биографии раздел убирается;
# строка «> Источники» за ним остаётся в тексте.
QUESTIONS_HEAD = re.compile(r"^(#+)[ \t]+(Открытые вопросы|Что открыто|Otwarte pytania|Pytania otwarte|Preguntas abiertas|"
                            r"Lo que queda abierto|Open questions)[ \t]*$", re.M | re.I)
SOURCES_LINE = re.compile(r"^>\s*(Источники|Źródła|Fuentes|Sources)\b", re.M | re.I)


def split_section(text, head_re):
    """Текст без раздела (первого заголовка head_re вне чужого человека) + (уровень заголовка, тело раздела) или None."""
    m = next((h for h in head_re.finditer(text) if not in_other_person(text, h.start())), None)
    if not m:
        return text, None
    lvl = len(m.group(1))
    nxt = re.compile(rf"^#{{1,{lvl}}}[ \t]", re.M).search(text, m.end())
    end = nxt.start() if nxt else len(text)
    return text[:m.start()] + text[end:], (lvl, text[m.end():end])


def split_recollections(text):
    """Текст биографии без раздела «Воспоминания» + [(название, «кто вспоминает · откуда», рассказ)]."""
    text, sec = split_section(text, RECOLL_HEAD)
    if not sec:
        return text, []
    lvl, body = sec
    out = []
    for part in re.split(rf"^#{{{lvl + 1}}}[ \t]+", body, flags=re.M)[1:]:
        title, _, body = part.partition("\n")
        body = re.sub(r"^-{3,}[ \t]*$", "", body, flags=re.M).strip()
        by = RECOLL_BY.match(body)
        out.append((title.strip(), by.group(1).strip() if by else "", body[by.end():].strip() if by else body))
    return text, out


def split_questions(text):
    """Текст биографии без «Открытых вопросов» (строка «> Источники» из раздела остаётся в тексте) + их Markdown или ""."""
    m = next((h for h in QUESTIONS_HEAD.finditer(text) if not in_other_person(text, h.start())), None)
    rest, sec = split_section(text, QUESTIONS_HEAD)
    if not sec:
        return text, ""
    body = sec[1]
    src = SOURCES_LINE.search(body)
    tail = body[src.start():] if src else ""
    body = body[:src.start()] if src else body
    body = re.sub(r"^-{3,}[ \t]*$", "", body, flags=re.M).strip()
    return rest[:m.start()] + (tail if tail else "") + rest[m.start():], body


def text_hash(t):
    return hashlib.sha1(re.sub(r"\s+", " ", t).strip().encode()).hexdigest()[:12]


translations = {}  # person_id → {lang: (frontmatter, text)}
for tp in sorted(TRANSLATIONS.glob("*/biographies/*.md")) if TRANSLATIONS.exists() else []:
    tf, tb = read_note(tp)
    pid = tf.get("of_id") or tf.get("person_id") or (people.get(N(tp.stem)) or {}).get("id")
    if pid in by_id:
        translations.setdefault(pid, {})[tp.parent.parent.name] = (tf, tb)
for pid, tr in translations.items():  # имя на языке перевода (Casimiro вместо Kazimierz) — везде на сайте
    for lang, (tf, _) in tr.items():
        if tf.get("name_local"):
            by_id[pid][lang] = str(tf["name_local"])


# ---------- фото мест и времени ----------
# Снимки из 1_sources/found/photos_places (по местам) и photos_history (по темам). Подписи — из описей
# 00_ОПИСЬ*.md (таблица «Файл | Что | Год | Источник | … | Чья история | Точно/типично | ❓»);
# если снимка в описи нет — подпись, год и источник берутся из имени файла «Место_что-снято_1930_pastvu-123.jpg».
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")
COLS = [("file", ("файл",)), ("desc", ("что",)), ("year", ("год",)), ("source", ("источник", "откуда")),
        ("rights", ("автор", "права", "лицензия")), ("whose", ("чья", "история", "кому", "насколько «наше»", "место и чьё")),
        ("exact", ("точно", "место", "насколько точно")), ("note", ("❓",))]


def col_key(h):
    h = h.strip().lower()
    return next((k for k, keys in COLS if any(h.startswith(x) for x in keys)), None)


def read_inventories(root):
    info = {}
    imgs = [p for p in root.rglob("*") if p.suffix.lower() in IMG_EXT]
    for inv in sorted(root.rglob("*.md")):
        here = [p for p in imgs if inv.parent in p.parents]
        section, header = "", None
        for line in N(inv.read_text(encoding="utf-8")).splitlines():
            if line.startswith("#"):
                section, header = line.lstrip("#").strip(), None
                continue
            if not line.startswith("|"):
                header = None if not line.strip() else header
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if re.fullmatch(r"[\s|:-]+", line):
                continue
            if header is None:
                keys = [col_key(c) for c in cells]
                header = keys if "file" in keys or (keys and keys[0] == "whose" and "file" in keys[1:]) else None
                if header is None and any(k == "file" for k in keys):
                    header = keys
                continue
            row = {k: v for k, v in zip(header, cells) if k and v and v not in ("—", "-")}
            names = re.findall(r"`([^`]+)`", row.get("file", "")) or [row.get("file", "")]
            for name in names:
                name = N(name.strip())
                if not name:
                    continue
                if "…" in name:  # «Вербичи_1929…» — все файлы с таким началом; без начала имени («…_целиком») не угадываем
                    pre = name.split("…")[0]
                    hits = [p for p in here if len(pre) >= 4 and N(p.name).startswith(pre)]
                else:
                    hits = [p for p in here if N(p.name) == name]
                shared = len(names) > 1 or "…" in name  # одна строка описи на несколько снимков — её год общий, не точный
                for h in hits:
                    info.setdefault(h, {**row, "section": section, "shared": shared})
    return imgs, info


SRC_LINK = [(r"pastvu-(\d+)", "https://pastvu.com/p/{}", "PastVu"), (r"fotopolska-(\d+)", "https://fotopolska.eu/{},foto.html", "Fotopolska"),
            (r"NARA-(\d+)", "https://catalog.archives.gov/id/{}", "NARA")]


def from_filename(p):
    parts = N(p.stem).split("_")
    Y = r"(1[6-9]\d\d|20[0-2]\d)"
    # год съёмки: отдельное слово «1930» или «фото-2005» важнее года внутри описания («церковь-1873» — год постройки)
    yr = next((int(m[1]) for x in parts if (m := re.fullmatch(rf"(?:ок)?{Y}(?:-\d+|-е|е)?", x))), None) \
        or next((int(m[1]) for x in parts if (m := re.search(rf"фото-{Y}", x))), None) \
        or next((int(m[1]) for x in parts if (m := re.search(Y, x))), None)
    src = next((x for x in parts[1:] if re.match(r"(pastvu|fotopolska|commons|radzima|NARA|Bundesarchiv|Esri|Яндекс|OSM|etomesto|DeutscheFotothek|UWM|Polona|NAC|delcampe|panoramio)", x, re.I)), "")
    words = [x for x in parts if x != src and not re.fullmatch(r"(\d{2}\.)*\d{4}(-\d+)?(е|-е)?|\d{4}-\d{2}|ок\d{4}", x)]
    return yr, src, " ".join(w.replace("-", " ") for w in words)


def photo_record(p, info, album):
    r = info.get(p, {})
    yr_f, src_f, cap_f = from_filename(p)
    # год из имени файла точнее общего года строки описи («1928–1940» на весь ряд снимков)
    if not r.get("year") and (m := re.search(r"\b(1[6-9]\d\d|20[0-2]\d)\b", r.get("source", ""))) and not re.search(r"_(1[6-9]\d\d|20[0-2]\d)_", p.stem):
        yr_f = int(m[1])  # в описи нет колонки «год», но в источнике он есть: «Radzima.org, 2005»
    yr = yr_f if yr_f and (r.get("shared") or not r.get("year")) else (year(r.get("year")) or yr_f)
    year_txt = str(yr_f) if yr_f and (r.get("shared") or not r.get("year")) else (r.get("year") or "")
    if yr_f and re.match(r"до\s", r.get("year", "")) and yr_f < (year(r["year"]) or 0):
        # в описи — срез («до 1915»), в имени файла — год съёмки («1895-98»): он точнее, иначе снимок встанет в 1915
        yr = yr_f
        year_txt = next((x.replace("-", "–") for x in N(p.stem).split("_") if re.fullmatch(rf"{yr_f}(-\d+)?", x)), str(yr_f))
    link = next((u.format(m[1]) for rx, u, _ in SRC_LINK if (m := re.search(rx, p.stem, re.I))), None)
    return {"path": p, "album": album, "year": yr, "year_txt": year_txt,
            "desc": r.get("desc") or cap_f, "whose": r.get("whose", ""), "exact": r.get("exact", ""), "note": r.get("note", ""),
            "source": r.get("source") or src_f, "rights": r.get("rights", ""), "link": link, "section": r.get("section", "")}


def clean_album(name):
    return re.sub(r"^[A-Z]_", "", name).replace("_", " ").replace("-", " ").strip().capitalize()


def album_key(s):
    return re.sub(r"[\s-]+", " ", N(str(s))).strip().lower()


# Папку в 1_sources не переименовать, поэтому альбом находит карточку места и по другим её названиям: по имени без
# уточнения в скобках («Вербичи (Лесогорск)» → «Вербичи») и по aliases («Buenos Aires» → «Буэнос-Айрес»).
# Дефис и пробел — одно и то же. Название, которое подходит к двум карточкам, не используем.
album_place = {}
for stem, pl in places.items():
    for x in {stem, re.sub(r"\s*\(.*?\)", "", stem), *as_list(pl["f"].get("aliases"))}:
        album_place.setdefault(album_key(x), set()).add(stem)
album_place = {k: next(iter(v)) for k, v in album_place.items() if len(v) == 1}

# Альбомы «Хроники → События» — tree/albums.toml: один альбом — история одного человека или семьи. Снимок берём по
# куску имени файла (files), потом отбрасываем лишнее (skip), потом — вся папка (folders); папки не переименовать.
import tomllib  # noqa: E402
_alb_file = paths.TREE / "albums.toml"
_alb = tomllib.loads(_alb_file.read_text(encoding="utf-8")) if _alb_file.exists() else {}
theme_albums, theme_skip = _alb.get("album", []), [N(x) for x in _alb.get("skip", [])]
theme_unplaced = []


def theme_album(p, folder):
    """Альбом событий для снимка из photos_history или None (не показываем)."""
    name = N(p.name)
    for ti in theme_albums:
        if any(N(x) in name for x in ti.get("files", [])):
            return ti
    if any(x in name for x in theme_skip):
        return None
    for ti in theme_albums:
        if N(folder) in [N(x) for x in ti.get("folders", [])]:
            return ti
    theme_unplaced.append(p.name)
    return None


albums = {}  # slug → {title, kind, place (стем карточки или None), photos}
for root, kind in ((paths.PHOTOS_PLACES, "place"), (paths.PHOTOS_HISTORY, "theme")):
    if not root.exists():
        continue
    imgs, info = read_inventories(root)
    for p in sorted(imgs):
        rel = p.relative_to(root).parts
        if kind == "place":  # photos_places/<Страна>/<Место>/файл
            folder = rel[1] if len(rel) > 2 else N(p.stem).split("_")[0]
        else:                # photos_history/<Тема>/…/файл
            folder = rel[0] if len(rel) > 1 else "Разное"
        title = N(folder).replace("-", " ") if kind == "place" else clean_album(N(folder))
        stem = next((k for k in (title, title.replace(" или ", " ")) if k in places), None) \
            or (album_place.get(album_key(title)) if kind == "place" else None)
        title = no_address(title)
        slug = slugify(latin(title, "en"))
        ti = None
        if kind == "theme" and theme_albums:
            if not (ti := theme_album(p, folder)):
                continue
            slug, title = ti["slug"], ti["ru"]
        a = albums.setdefault(slug, {"slug": slug, "title": title, "kind": kind, "place": stem, "photos": [], "info": ti})
        a["photos"].append(photo_record(p, info, a))
        r = a["photos"][-1]
        if ti and r.get("section") and (not re.match(r"\d+[а-я]?\. ", r["section"])
                                        or (ti.get("folders") and N(folder) not in [N(x) for x in ti["folders"]])):
            r["section"] = ""  # заголовок описи или раздел чужой папки — не раздел этой истории: по десятилетиям
if theme_unplaced:
    print(f"albums.toml: снимков событий без альбома (на сайт не идут) — {len(theme_unplaced)}: " + ", ".join(theme_unplaced[:8]))
for a in albums.values():
    a["photos"].sort(key=lambda r: (r["year"] or 9999, r["desc"]))
    a["url"] = f"gallery/{a['slug']}.html"
    a["nm"] = places[a["place"]] if a["place"] else {"ru": a["title"], "en": latin_place(a["title"], "en"), "pl": latin_place(a["title"], "pl")}
    if (ti := a.get("info")) and ti.get("ru"):
        a["nm"] = {c: ti[c] for c in ("ru", "pl", "es", "en") if ti.get(c)}
        for nm_ in ti.get("people", []):
            if nm_ not in people:
                sys.exit(f"albums.toml: альбом {a['slug']}: нет карточки «{nm_}» в tree/people")
place_albums = {a["place"]: a for a in albums.values() if a["place"]}
# В тематическом альбоме у снимка нет места-альбома; место — по первому слову имени файла («Белосток_…» → карточка
# Białystok, через её aliases). Нужно, чтобы на снимке стояло, какое государство было там в тот год.
place_by_name = {N(str(x)): stem for stem, pl in places.items() for x in [stem, *as_list(pl["f"].get("aliases"))]}
for a in albums.values():
    for r in a["photos"]:
        r["era_place"] = a["place"] or place_by_name.get(N(r["path"].stem).split("_")[0])


# Точное место (дом, больница, вуз) — своя карточка места внутри города (parent_place — город). В её шапке
# «photos:» — начала имён файлов, которые сняты именно там: «Лесогорск_Садовая-12». Такие снимки лежат в альбоме
# города, но человеку показываются, только если он связан с этим адресом.
addr_prefix = sorted(((N(str(x)), stem) for stem, pl in places.items() for x in as_list(pl["f"].get("photos"))),
                     key=lambda x: -len(x[0]))
for a in albums.values():
    for r in a["photos"]:
        r["addr"] = next((stem for pre, stem in addr_prefix if N(r["path"].stem).startswith(pre)), None)
addr_photos = {}
for a in albums.values():
    for r in a["photos"]:
        if r["addr"]:
            addr_photos.setdefault(r["addr"], []).append(r)

# «≈ похожее, не наше» (навык photos): снимка нашей деревни нет — снимок самой похожей рядом. В описи «Насколько точно»
# начинается с «≈», имя файла — <Настоящая>_похоже-на-<Наша>-<км>км_…. На сайте — красная метка «≈ не наше · <где>,
# N км от <нашей>»; на странице нашей деревни и в «Фото мест из жизни» — рядом с её снимками, но в её media не кладём.
LIKE_RX = re.compile(r"^([^_]+)_похоже-на-([^_]+?)-(\d+)км_")


def place_names(x):
    """Название места на языках сайта и его карточка (если есть): «Лесогорск» → карточка, «Беловежа» → латиницей."""
    stem = place_by_name.get(x) or album_place.get(album_key(x))
    if stem:
        return {c: places[stem][c] for c in ("ru", "pl", "en")}, stem
    return {"ru": x, "pl": latin_place(x, "pl"), "en": latin_place(x, "en")}, None


like_photos = {}  # наша деревня → снимки похожих
for a in albums.values():
    for r in a["photos"]:
        r["like"] = None
        if not N(r["exact"]).startswith("≈"):
            continue
        r["like"] = {}
        if m := LIKE_RX.match(N(r["path"].stem)):
            real, _ = place_names(m[1].split("-")[0])  # «Лесогорск-Слобода» — слобода на краю Лесогорска
            ours, stem = place_names(m[2])
            r["like"] = {"real": real, "ours": ours, "km": int(m[3]), "ours_place": stem}
            r["era_place"] = r["era_place"] or stem  # государство в тот год — как у нашей деревни рядом
            if stem:
                like_photos.setdefault(stem, []).append(r)


def place_chain(t):
    """Место и все, в которые оно входит: «Минск — университет» → Минск → Беларусь."""
    out = []
    while t in places and t not in out:
        out.append(t)
        t = link_target(places[t]["f"].get("parent_place")) if places[t]["f"].get("parent_place") else None
    return out












def place_source(body):
    """Текст карточки места, который переводят: без заголовка, «Государств по годам» (их переводит eras.py),
    блоков Charted Roots и уже готовых «О месте» на других языках — русский «О месте» остаётся."""
    body = re.sub(r"\A\s*# .*\n", "", body, count=1)
    body = re.sub(r"^## (Государства по годам|O miejscu|Sobre el lugar|About the place)\n.*?(?=^## |\Z)", "", body, flags=re.S | re.M)
    body = re.sub(r"^```.*?^```[ \t]*$", "", body, flags=re.S | re.M)
    return re.sub(r"\n{3,}", "\n\n", body).strip()


class SiteExtras(export.Extras):
    """Стык с выгрузкой JSON (site_data/export.py): биографии, фото, «Места и эпохи», значки, заметки. Переезжают в
    site_data по одной; стык остаётся."""

    def __init__(self):
        self.private = set(doc_scans_of_living())
        self.place_stem = {pl["id"]: stem for stem, pl in places.items()}

    def names(self, pid):
        d = by_id[pid]
        return {"ru": d["ru"], "en": d["en"], "pl": d["pl"], **({"es": d["es"]} if d.get("es") else {})}

    def card(self, pid):
        d = by_id[pid]
        return {"initials": d["ini"], "color": d["col"], "marriage": d["marriage"]}

    def ui(self):
        return {"i18n": I18N, "icons": ICONS}

    def source_text(self, stem):
        p = paths.TREE / "sources" / f"{stem}.md"
        if not p.exists():
            return None
        f, body = read_note(p)
        if audio_source(f):  # запись разговора в семье — только описание (site_data/privacy.py)
            return None
        body = re.sub(r"\A\s*# .*\n", "", body, count=1)  # заголовок — уже в шапке страницы
        # встроенные заметки (расшифровки) — их текстом, как на странице; картинки остаются картинками
        return re.sub(r"!\[\[([^\]|]+?)(?:\|[^\]]*)?\]\]",
                      lambda m: m[0] if re.search(r"\.(jpe?g|png|webp|pdf|m4a|mp3|opus)$", m[1], re.I) else embed(m[1]), body)

    def research(self):
        p = paths.RESEARCH_NEXT
        if not p.exists():
            return None
        f, body = read_note(p)
        body = re.sub(r"\A\s*# .*\n", "", body, count=1).strip()  # заголовок — в шапке страницы, на языке сайта
        # задачи онлайн, оффлайн и сделанное — свои файлы рядом; на сайте — одной страницей, заголовки на ступень ниже
        files = [p] + [x for x in (paths.RESEARCH_ONLINE, paths.RESEARCH_OFFLINE, paths.RESEARCH_DONE) if x.exists()]
        for x in files[1:]:
            body += "\n\n" + re.sub(r"^(#{1,5}) ", r"#\1 ", read_note(x)[1].strip(), flags=re.M)
        # дата правки: updated в свойствах файла, нет — время самого свежего файла
        updated = str(f.get("updated") or datetime.date.fromtimestamp(max(x.stat().st_mtime for x in files)).isoformat())[:10]
        return {"md": body, "updated": updated} if body else None

    @staticmethod
    def photo(r):
        """Снимок галереи → запись для выгрузки (одна форма у галереи и у «фото мест из жизни»)."""
        return {**{k: r[k] or "" for k in ("year_txt", "desc", "whose", "exact", "note", "source", "rights", "section")},
                "year": r["year"], "link": r["link"], "url": "/" + thumb(r["path"]), "thumb": "/" + thumb(r["path"], small=True),
                "era": era_at(r["era_place"], r["year"])[0] if r["era_place"] and r["year"] else None,
                "addr": places[r["addr"]]["id"] if r.get("addr") else None,
                "like": {**r["like"], "ours_place": places[r["like"]["ours_place"]]["id"] if r["like"]["ours_place"] else None}
                if r.get("like") else None,  # «≈ не наше»; без имени по образцу — только «≈» в exact
                "path": r["path"]}  # исходный файл — по его имени ищется перевод подписи (translations/<язык>/photos/)

    def gallery(self):
        out = []
        for a in sorted(albums.values(), key=lambda a: (-len(a["photos"]), a["title"])):
            nm_ = a["nm"]
            ti = a.get("info") or {}
            out.append({"slug": a["slug"], "names": {c: nm_[c] for c in ("ru", "pl", "es", "en") if nm_.get(c)}, "kind": a["kind"],
                        "place": places[a["place"]]["id"] if a["place"] else None,
                        "about": ti.get("about"), "people": [people[n]["id"] for n in ti.get("people", [])],
                        "photos": [self.photo(r) for r in a["photos"]]})
        return out

    def life_photos(self, pid):
        d = by_id[pid]
        groups, other, mine = life_photos(d, person_stays(d))
        out = []
        for k, rs in groups + mine:
            if isinstance(k, tuple):  # снимки точного адреса — подпись и ссылка на это место
                pl = places[k[1]]
                out.append({"names": {c: pl[c] for c in ("ru", "en", "pl")}, "place": pl["id"], "album": None,
                            "photos": [self.photo(r) for r in rs]})
            else:
                a = albums[k]
                out.append({"names": {c: a["nm"][c] for c in ("ru", "en", "pl")}, "place": places[a["place"]]["id"] if a["place"] else None,
                            "album": a["slug"], "photos": [self.photo(r) for r in rs]})
        return out, [places[t]["id"] for t in other]

    def place_people(self, place_id):
        stem = self.place_stem[place_id]
        who = {}
        for pid, what in place_people.get(stem, []):
            who.setdefault(pid, []).append(what)
        out = []
        for pid, ws in who.items():  # «Рождение» и «родился здесь» — одно и то же (как на странице места)
            ws = list(dict.fromkeys(ws))
            if "pp_born" in ws and "ev_birth" in ws: ws.remove("ev_birth")
            if "pp_died" in ws and "ev_death" in ws: ws.remove("ev_death")
            out.append((pid, sorted(ws)))
        return sorted(out, key=lambda x: by_id[x[0]]["ru"])

    def place_events(self, place_id, pid):
        return place_events.get((self.place_stem[place_id], pid), [])

    def place_mentions(self, place_id):
        """Кто упоминает место в своей биографии или карточке ссылкой [[Место]], но не родился, не умер и не жил там по
        событиям дерева — порядок как в списке людей."""
        if not hasattr(self, "_mentions"):
            self._mentions = {}
            for d in sorted(people.values(), key=lambda d: d["ru"]):
                for t in dict.fromkeys(place_by_name.get(link_target(m[0])) for m in re.finditer(r"\[\[[^\]]+\]\]", bio_text(d) + d["body"])):
                    if t:
                        self._mentions.setdefault(t, []).append(d["id"])
        stem = self.place_stem[place_id]
        known = {pid for pid, _ in place_people.get(stem, [])}
        return [pid for pid in self._mentions.get(stem, []) if pid not in known]

    def place_text(self, place_id):
        return place_text_of(places[self.place_stem[place_id]]["body"])

    # ---------- переводы мест, фактов и фото (tr_store.py; схема — paths.tr_path) ----------

    def place_tr(self, place_id):
        """{язык: (тело перевода, перевод ИИ не проверен?, отстаёт от русского?)} — как у биографий."""
        stem = self.place_stem[place_id]
        if not hasattr(self, "_place_tr"):
            self._place_tr = tr_store.load("places")
        cur = tr_store.text_hash(place_source(places[stem]["body"]))
        return {lang: (tb, not tf.get("reviewed"), tf.get("source_hash") != cur)
                for lang, (tf, tb) in self._place_tr.get(stem, {}).items()}

    def fact_tr(self, f):
        """Перевод строки факта по её отпечатку: {язык: {label, text, reasoning, locators}}; строку поправили — нет."""
        if not hasattr(self, "_fact_tr"):
            self._fact_tr = tr_store.facts_index()
        return self._fact_tr.get(tr_store.fact_key(f.label, f.text, f.reasoning), {})

    def source_titles(self, stem, title):
        """Название источника на других языках: {язык: название} (translations/<язык>/sources/<Имя карточки>.md)."""
        if not hasattr(self, "_src_tr"):
            self._src_tr = tr_store.load("sources")
        return {lang: t for lang, (tf, tb) in self._src_tr.get(stem, {}).items()
                if tf.get("source_hash") == tr_store.text_hash(title) and (t := tr_store.sections(tb).get("title"))}

    def occupation_tr(self, text):
        """Поле «Занятие» на других языках: {язык: текст}"""
        if not hasattr(self, "_fact_tr"):
            self._fact_tr = tr_store.facts_index()
        return {k: v["text"] for k, v in self._fact_tr.get(tr_store.occupation_key(str(text).strip()), {}).items() if v.get("text")}

    def photo_tr(self, r):
        """Перевод подписи снимка, если русская подпись с тех пор не менялась: {язык: {desc, whose, exact, note, section}}."""
        if not hasattr(self, "_photo_tr"):
            self._photo_tr = tr_store.load("photos")
        cur = tr_store.photo_hash(r)
        return {lang: tr_store.sections(tb) for lang, (tf, tb) in self._photo_tr.get(Path(r["path"]).stem, {}).items()
                if tf.get("source_hash") == cur}

    def source_media(self, stem):
        p = paths.TREE / "sources" / f"{stem}.md"
        f = read_note(p)[0] if p.exists() else {}
        urls = [u for u in (photo(m) for m in as_list(f.get("media"))) if u]
        return [("/" + u, "/" + N(u) in self.private) for u in dict.fromkeys(urls)]

    def biography(self, pid):
        d = by_id[pid]
        ru = bio_text(d)
        if not ru:
            return None
        rows3 = lambda rs: [(when, what, extra) for _, when, what, extra in rs]
        shown, rows = split_lifeline(ru)
        shown, mem = split_lifeline(shown, memory=True)
        shown, rec = split_recollections(shown)
        shown, qs = split_questions(shown)
        tr = {}
        for lang, (tf, tb) in translations.get(pid, {}).items():
            text, tr_rows = split_lifeline(own_head(tb))
            text, tr_mem = split_lifeline(text, memory=True)
            text, tr_rec = split_recollections(text)
            text, tr_qs = split_questions(text)
            tr[lang] = (text, not tf.get("reviewed"), tf.get("source_hash") != text_hash(ru), rows3(tr_rows), rows3(tr_mem),
                        tr_rec, tr_qs)
        ref = next(iter(bio_refs(d)), "")
        return {"file": N(ref.split("#")[0]), "ru": shown, "lifeline": rows3(rows), "memory": rows3(mem),
                "recollections": rec, "questions": qs, "tr": tr}

    def media(self, pid):
        urls = [u for u in (photo(m) for m in as_list(by_id[pid]["f"].get("media"))) if u]
        return [("/" + u, "/" + N(u) in self.private) for u in dict.fromkeys(urls)]

    def media_url(self, name):
        u = photo(name) or file_url(name)  # снимок — уменьшенной копией, PDF и прочее — файлом
        return "/" + u if u else None

    # ---------- заметки проекта (data/docs/) ----------

    def note(self, target):
        p = md_file(target)
        if not p:
            return None
        if pid := bio_owner(p):  # биография (и её перевод) — это страница человека
            return ("person", pid)
        return ("doc", doc_id(p))

    def next_doc(self):
        if pending:
            return self.doc(pending.pop(0))
        if not hasattr(self, "_goto"):  # старые адреса docs/<номер>.html источников и биографий — на их страницы
            self._goto = [{"id": h, "goto": g} for h, g in old_doc_pages().items() if h not in docs.values()]
        return self._goto.pop(0) if self._goto else None

    def doc(self, p):
        """Заметка, как была её страница docs/<номер>.html: название, где лежит, кто на неё ссылается, снимки, файлы, текст."""
        f, body = read_note(p)
        rel = N(p.relative_to(paths.ROOT).as_posix())
        media, files = [], []
        for m in as_list(f.get("media")):
            t = link_target(m)
            if u := photo(t):
                media.append(("/" + u, "/" + N(u) in self.private))
            elif not md_file(t) and (u := file_url(t)):
                files.append((t, "/" + u))
        return {"id": docs[rel], "title": str(f.get("title") or f.get("name") or N(p.stem)), "path": rel,
                "meta": {k: str(f[k]) for k in ("origin", "repository", "confidence") if f.get(k)},
                "people": [d["id"] for d in sorted(people.values(), key=lambda d: d["ru"])
                           if N(p.stem) in {link_target(x) for x in as_list(d["f"].get("sources"))}],
                "media": list(dict.fromkeys(media)), "files": list(dict.fromkeys(files)), "audio": bool(audio_source(f)),
                "md": re.sub(r"\A\s*# .*\n", "", body, count=1)}  # заголовок — уже в шапке страницы

    def stays(self, pid):
        out = []
        for y0, y1, ev, t in person_stays(by_id[pid]):
            era, _ = era_at(t, y0)
            out.append((y0, y1, ev, places[t]["id"], era))
        return out

    def stats(self, pid):
        return by_id[pid]["st"]

    def progress(self, tree):
        return site_progress.build(tree)

    def documents(self, pid):
        """Документы человека; у названия — переводы (translations/<язык>/documents/<имя файла документа>.md)."""
        if not hasattr(self, "_doc_tr"):
            self._doc_tr = tr_store.load("documents")
        out = []
        for x in person_documents()[0].get(pid, []):
            x = dict(x)
            stem = x.pop("file", None)
            tr = {lang: t for lang, (tf, tb) in self._doc_tr.get(stem, {}).items()
                  if tf.get("source_hash") == tr_store.text_hash(x["title"]) and (t := tr_store.sections(tb).get("title"))}
            out.append({**x, "titles": tr} if tr else x)
        return out


def write_data(tree):
    """data/*.json для приложения — до сборки web/: её тесты проверяют их схемой."""
    for d in people.values():
        d["st"] = stats(d)  # значки «сколько материала» — нужны и страницам, и выгрузке
    for d in people.values():  # порядок детей и браков — общий (cards.tree.order_family): по рождению и по браку
        t = tree.people[d["id"]]
        d["children"], d["spouses"] = list(t.children), list(t.spouses)
    for d in people.values():  # от какого брака родителей ребёнок (цвет линий на дереве)
        d["marriage"] = 0
        fa, mo = (d["father"] or [None])[0], (d["mother"] or [None])[0]
        for par, other in ((fa, mo), (mo, fa)):
            if par and other and len(by_id[par]["spouses"]) > 1 and other in by_id[par]["spouses"]:
                d["marriage"] = by_id[par]["spouses"].index(other) + 1
                break
    export.write(tree, OUT / "data", SiteExtras())




# Сканы документов живых — свидетельство, паспорт, аттестат… Фильтр контактов читает только текст, а номер документа и дата
# рождения — на самом снимке. Такой снимок — по паролю, у кого бы в галерее он ни висел (паспорт Прокопа со страницей детей —
# и у Прокопа). Живой — как в person_stays: год рождения есть, года смерти нет. Тот же список слов — review_photos.DOC_WORDS.
DOC_SCAN = re.compile(r"паспорт|свидетельство|аттестат|удостоверение|диплом|трудов|военн[ыо]|cédula|cedula|\bdni\b", re.I)


def bio_owner(p):
    """cr_id человека, чья это биография (biographies/<Имя карточки> — биография.md, и её переводы), или None."""
    stem = N(p.stem)
    return people[stem.removesuffix(" — биография")]["id"] if stem.endswith(" — биография") and \
        stem.removesuffix(" — биография") in people else None


def old_doc_pages():
    """Номер прежней страницы docs/<номер>.html → (вид, номер) её нынешней страницы: заметки-источники и биографии.
    Сами заметками они не выгружаются — у них свои страницы в приложении."""
    out = {}
    by_stem = {}
    for sp in sorted((paths.TREE / "sources").rglob("*.md")):
        if cid := read_note(sp)[0].get("cr_id"):
            out[doc_hash(N(sp.relative_to(paths.ROOT).as_posix()))] = by_stem[N(sp.stem)] = ("source", str(cid))
    for tp in sorted(TRANSLATIONS.glob("*/sources/*.md")):  # перевод названия источника — тоже на страницу источника
        if N(tp.stem) in by_stem:
            out[doc_hash(N(tp.relative_to(paths.ROOT).as_posix()))] = by_stem[N(tp.stem)]
    for bp in sorted(paths.TREE.rglob("* — биография.md")):
        if pid := bio_owner(bp):
            out[doc_hash(N(bp.relative_to(paths.ROOT).as_posix()))] = ("person", pid)
    return out


def doc_scans_of_living():
    out = set()
    for d in people.values():
        if not living(d):
            continue
        for m in as_list(d["f"].get("media")):
            if DOC_SCAN.search(link_target(m)) and (p := photo(m)):
                out.add("/" + N(p))
    return sorted(out)


def living(d):
    """Живой — по общему правилу (living.py, [privacy] living_years в ftree.toml): смерти нет и родился не раньше
    110 лет назад. Год рождения неизвестен — не живой: иначе паролем закрылись бы все предки без дат."""
    return living_rule.is_living(d["f"].get("born"), d["f"].get("died") or ("?" if "–" in lifespan(d) else None))


@functools.cache
def person_documents():
    """Документы людей для раздела «Документы» в профиле (2_transcripts/documents, правила — навык card-rules):
    {cr_id человека: [{title, kind, years, cover, pdf, doc, pages, private}]}, по годам. Закрытые (`access: closed`) —
    не на сайт вовсе. У живого обложка и PDF — по паролю (как doc_scans_of_living); у умершего PDF открыт, если в тексте
    документа нет почты, телефона и номера дома (сам PDF — сканы без текста, lock_files_with_contacts его не прочтёт)."""
    import documents
    out, open_pdfs = {}, set()
    for md in sorted(documents.DOCUMENTS.glob("*/*.md")):
        rel = md.relative_to(paths.ROOT).as_posix()
        if closed_document(rel):
            continue
        f, body = documents.read(md)
        d = by_id.get(str(f.get("person_id") or ""))
        if not d:
            continue
        pages = as_list(f.get("pages"))
        src = documents.media_file(pages[0]["file"]) if pages and pages[0].get("file") else None
        cover = "/" + thumb(src, small=True) if src and src.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp") else None
        pdf = file_url(md.with_suffix(".pdf").name) if md.with_suffix(".pdf").exists() else None
        private = living(d) or bool(EMAIL.search(body) or PHONE.search(body) or no_address(body) != body)
        if pdf and not private:
            open_pdfs.add("/" + N(pdf))
        named = [people[n] for x in as_list(f.get("people")) if (n := N(str(x)).strip("[]\"")) in people]
        for w in {x["id"]: x for x in [d, *named]}.values():  # и у всех, кто назван в документе (people), — у каждого в профиле
            out.setdefault(w["id"], []).append({
                "title": str(f.get("title") or N(md.stem)), "kind": f.get("kind"), "years": N(md.stem).split(" — ")[0],
                "file": N(md.stem),
                "cover": cover, "pdf": "/" + pdf if pdf else None, "doc": doc_id(md), "pages": len(pages),
                "origin": f.get("origin"), "private": private or living(w)})
    for ds in out.values():
        ds.sort(key=lambda x: x["years"])
    return out, open_pdfs


def private_files():
    """PDF, в тексте которых есть почта, телефон или номер дома, и сканы документов живых (doc_scans_of_living) — в список
    private_files файла site.json (сборщик вписывает его в PRIVATE_FILES проверки входа): без пароля их не отдаём,
    даже пока вход открыт. Страницы сайта контакты уже прячут (no_contacts, no_address), а PDF копируются как есть.
    Скан без текстового слоя (архивные Doc16–Doc30) или нет pdftotext — проверить нельзя, значит, тоже по паролю;
    их расшифровки на страницах сайта открыты. Исключение — PDF документов умерших (person_documents: текст проверен по .md);
    обложки документов живых — тоже по паролю."""
    import subprocess
    docs_of, open_pdfs = person_documents()
    private = []
    for f in sorted((OUT / "files").glob("*")):
        if f.suffix.lower() != ".pdf" or "/files/" + N(f.name) in open_pdfs:
            continue
        try:
            text = subprocess.run(["pdftotext", "-q", str(f), "-"], capture_output=True, text=True).stdout
        except FileNotFoundError:
            text = "@x.xx"
        if len(text.strip()) < 50 or EMAIL.search(text) or PHONE.search(text) or no_address(text) != text:
            private.append("/files/" + N(f.name))
    private += doc_scans_of_living()
    private += sorted({x["cover"] for ds in docs_of.values() for x in ds if x["private"] and x["cover"]})
    return private


def site_json(private):
    """site.json — всё, что сборщику нужно сверх data/ (схема web/schema/site.schema.json)."""
    site = paths.CONFIG.get("site", {})  # вход без пароля: до какой даты и из каких стран (ftree.toml, [site])
    until = str(site.get("open_until") or "")
    if until and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", until):
        raise SystemExit(f"ftree.toml: [site] open_until = {until!r} — нужна дата ГГГГ-ММ-ДД или ''")
    targets = destinations.site_targets()  # куда выкладывать — только то, что вписал владелец дерева; нет — никуда
    return {"schema": "site/1", "built": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "tree": destinations.tree_name(), "owner_login": re.sub(r"[^A-Za-z0-9_.-]", "", str(site.get("owner_login") or "")),
            "realm": re.sub(r"[^\x20-\x7E]|[\"\\\\]", "", str(site.get("realm") or "")),
            "private_files": list(dict.fromkeys(private)), "open_until": until,
            "open_countries": [str(c) for c in site.get("open_countries", [])], "deploy": {"targets": targets},
            "counts": {"people": len(people), "places": len(places), "docs": len(docs), "albums": len(albums),
                       "no_bio": sum(not d["st"]["bio"] for d in people.values()),
                       "files": len(copied), "private": len(private)}}




def run(data_only=False):
    """Выгрузка целиком (или только data/ — data_only). Карточки не по правилам — стоп до того, как что-то записано."""
    tree = cards.load()
    if tree.errors:
        sys.exit("Карточки не по правилам — выгрузка не сделана (rodo check-cards):\n" + "\n".join(map(str, tree.errors)))
    OUT.mkdir(parents=True, exist_ok=True)
    write_data(tree)
    if data_only:
        return
    for f in (OUT / "files").glob("*") if (OUT / "files").exists() else ():  # файлы, на которые больше нет ссылки
        if f.name not in copied:
            f.unlink()
    for f in (OUT / "media").rglob("*.jpg") if (OUT / "media").exists() else ():  # фото, сжатые до 27.09.2026 под старым именем с номером дома
        if no_address(N(f.stem)) != N(f.stem):
            f.unlink(missing_ok=True)
    site = site_json(private_files())
    text = json.dumps(site, ensure_ascii=False, indent=1)
    if not (OUT / "site.json").exists() or (OUT / "site.json").read_text(encoding="utf-8") != text:
        (OUT / "site.json").write_text(text, encoding="utf-8")
    c = site["counts"]
    print(f"Выгрузка: {OUT} — людей {c['people']}, мест {c['places']}, заметок {c['docs']}, файлов {c['files']}; "
          f"без биографии {c['no_bio']}; альбомов {c['albums']}; только по паролю — {c['private']}")


if __name__ == "__main__":
    run(data_only="--data" in sys.argv[1:])
