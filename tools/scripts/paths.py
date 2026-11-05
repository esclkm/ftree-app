"""Все пути проекта в одном месте. Скрипты берут их отсюда, а не собирают сами.

Проект разложен на четыре этажа (подробно — START_HERE.md в корне):
  1_sources      — оригиналы: сканы, аудио, фото, выгрузки. Не правим.
  2_transcripts  — расшифровки: текст источника слово в слово.
  3_research     — наши выводы: дерево (Obsidian), биографии, поиск, запросы.
  4_outputs      — то, что отдаём людям: книги, анкеты, PDF.
Если папка переедет — поправить здесь, остальные скрипты подхватят.
"""
import json
import os
import shlex
import sys
import tomllib
from pathlib import Path

CONFIG_NAME = "ftree.toml"                           # отмечает корень дерева; в нём ветки и кто их ведёт
ROOT_ENV = "FTREE_ROOT"

# ── Настройки: один загрузчик на все скрипты ─────────────────────────────────────────────────────────────────────────
# Откуда берётся значение, по старшинству: ключ команды (override) > переменная окружения > файл ~/.config/ftree/env
# (строки ИМЯ=значение, вне всех репозиториев; пишет его настройщик) > ftree.toml дерева > значение по умолчанию.
# Без файла env и переменных всё работает как раньше: значения по умолчанию — нынешние пути этого Mac.
ENV_FILE = Path(os.environ.get("FTREE_ENV_FILE") or "~/.config/ftree/env").expanduser()
_OVERRIDES: dict[str, str] = {}


def _read_env_file(path: Path) -> dict[str, str]:
    """«ИМЯ=значение» построчно; `export`, кавычки, `~` и `$HOME` понимает; пустые строки и `#` — пропуск."""
    out = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        parts = shlex.split(value, comments=True) or [""]
        out[key.strip()] = os.path.expandvars(parts[0])
    return out


_ENV_FILE_VALUES = _read_env_file(ENV_FILE)


def override(name: str, value) -> None:
    """Ключ команды сильнее всего: `paths.override("CDP_PORT", args.port)` до того, как значение понадобится."""
    if value not in (None, ""):
        _OVERRIDES[name] = str(value)


def _toml_get(config: dict, dotted: str | None):
    node = config
    for part in (dotted or "").split(".") if dotted else ():
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if dotted else None


def setting(name: str, default=None, toml: str | None = None):
    """Значение настройки `name` по старшинству (см. выше). `toml` — ключ в ftree.toml через точку («myheritage.site»).
    Из окружения и файла env приходит строка; из ftree.toml — как записано (число, список, таблица)."""
    for source in (_OVERRIDES, os.environ, _ENV_FILE_VALUES):
        if source.get(name) not in (None, ""):
            return source[name]
    value = _toml_get(globals().get("CONFIG") or {}, toml)
    return default if value is None else value


def setting_path(name: str, default, toml: str | None = None) -> Path:
    """То же для папки или файла: `~` раскрыт."""
    return Path(str(setting(name, default, toml))).expanduser()


def tree_conf(dotted: str, default=None):
    """Правило или справочник самого дерева из ftree.toml («lifeline.ok», «asr.prompt»): то, что в коде было бы
    именами наших людей и мест. Нет в ftree.toml — `default` (у нового дерева обычно пусто)."""
    value = _toml_get(globals().get("CONFIG") or {}, dotted)
    return default if value is None else value


def _tree_above(base: Path) -> Path | None:
    for d in (base, *base.parents):
        if (d / CONFIG_NAME).is_file():
            return d
    return None


def find_root(start: Path | None = None) -> Path:
    """Корень дерева — папка с ftree.toml. Порядок: переменная FTREE_ROOT; вверх от текущей папки (работаешь внутри
    дерева — значит, с ним: так копия дерева в другой папке не уходит в основное); FTREE_ROOT из файла env (позвали
    из чужой папки — дерево этого Mac; пишет `rodo setup`); вверх от этого файла (запасное, пока приложение внутри данных)."""
    if os.environ.get(ROOT_ENV):
        return Path(os.environ[ROOT_ENV]).expanduser().resolve()
    if found := _tree_above(Path(start or Path.cwd()).resolve()):
        return found
    if _ENV_FILE_VALUES.get(ROOT_ENV):
        return Path(_ENV_FILE_VALUES[ROOT_ENV]).expanduser().resolve()
    if found := _tree_above(Path(__file__).resolve().parent):
        return found
    raise SystemExit(f"нет {CONFIG_NAME} ни выше {Path.cwd()}, ни выше {Path(__file__).parent} — где корень дерева?")


ROOT = find_root()
CONFIG = tomllib.loads((ROOT / CONFIG_NAME).read_text(encoding="utf-8"))
# ветка → карточка деда или бабушки (имя файла без .md), в порядке ftree.toml
LINES = {b["name"]: b["root"] for b in CONFIG.get("branch", [])}


def rel(path) -> str:
    """Путь от корня дерева в виде «3_research/tree/people» — для сравнения с путями из git и из текста. Папка вне дерева
    (сайт собирают в другое место) — полным путём: с путями внутри дерева она тогда просто не совпадёт."""
    path = Path(path)
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        try:
            return path.resolve().relative_to(ROOT.resolve()).as_posix()
        except ValueError:
            return path.as_posix()


# ── Приложение (скрипты, сайт) и то, что привязано к этому Mac ───────────────────────────────────────────────────────
APP = setting_path("FTREE_APP", Path(__file__).resolve().parents[2])   # где лежат tools/ и web/; пока = корень дерева
TOOLS = APP / "tools"
SCRIPTS = TOOLS / "scripts"
PY = TOOLS / "py"                                    # Python проекта (.venv)
TREE_SCRIPTS = ROOT / "tools" / "scripts"            # скрипты только этого дерева (книги о его людях) — в данных, не в
# приложении (строки «tree» в tools/APP_MANIFEST); rodo и update_all.py ищут скрипт сначала в приложении, потом здесь
WEB = APP / "web"                                    # код сайта (TypeScript + React, Vite)
SITE_ASSETS = WEB / "site_assets"                    # что сборщик сайта кладёт на хостинг как есть (functions/; netlify/, worker/ — зеркала)
_CACHE_HOME = setting("FTREE_CACHE")                 # кэш и веса моделей; не задан — внутри tools/, как раньше
CACHE = Path(_CACHE_HOME).expanduser() if _CACHE_HOME else ROOT / "tools" / ".cache"
AI_WEIGHTS = CACHE / "ai_weights" if _CACHE_HOME else ROOT / "tools" / "ai_weights"   # CodeFormer, распознавание лиц
CDP_PORT = int(setting("CDP_PORT", 9333))            # свой Chrome проекта (browser_cdp.mjs), вход Павла на сайтах
ASR_HOME = setting_path("FTREE_ASR_HOME", "~/.local/share/relatives-asr")       # распознавание звука (asr.sh)
PHOTO_VENV = setting_path("FTREE_PHOTO_VENV", "~/.relatives_ai_venv")           # реставрация фото (photo.sh)
PHOTO_MODELS = setting_path("REL_AI_MODELS", "~/.relatives_ai_models")          # веса GFPGAN и Real-ESRGAN
TELEGRAM_DIR = setting_path("FTREE_TELEGRAM_DIR", "~/.config/ftree-telegram")   # config.toml (api_id) и ключ входа
TELEGRAM_SESSION = setting("FTREE_TELEGRAM_SESSION", "tree", toml="telegram.session")                   # имя файла .session в этой папке

# 1 — оригиналы. Три папки по происхождению:
#   family/       — дала семья: архив, аудио, фото, документы, наши соцсети, отчёт генеалога
#   found/        — найдено в открытых источниках: онлайн-архивы, фото мест, иллюстрации
#   others_trees/ — чужие и сторонние деревья: MyHeritage, дальше — аргентинские
SOURCES = ROOT / "1_sources"
FAMILY = SOURCES / "family"
FOUND = SOURCES / "found"
OTHERS_TREES = SOURCES / "others_trees"
FAMILY_ARCHIVE = FAMILY / "family_archive"           # PDF архива «Машинисты»
AUDIO = FAMILY / "audio"                             # разговоры с родителями
PHOTOS_FAMILY = FAMILY / "photos_family"
SOCIAL_EXPORT = FAMILY / "social" / "social_export"
ARCHIVES_ONLINE = FOUND / "archives_online"          # Arolsen, ОБД, «Память народа», перепись 1921
PHOTOS_PLACES = FOUND / "photos_places"              # по стране и городу, общие для всех деревьев
PHOTOS_HISTORY = FOUND / "photos_history"            # иллюстрации к главам по темам
MYHERITAGE = OTHERS_TREES / "myheritage"             # исходный GEDCOM + фото из MyHeritage
MYHERITAGE_GED = MYHERITAGE / setting("FTREE_MYHERITAGE_GED", "export.ged", toml="myheritage.gedcom")  # выгрузка MyHeritage
PORTRAITS = MYHERITAGE / "photos"                    # фото людей из MyHeritage (I5xxxxx_…)
INBOX = SOURCES / "inbox"                            # всё новое — сюда, потом разнести

# 2 — расшифровки
TRANSCRIPTS = ROOT / "2_transcripts"
TRANSCRIPTS_AUDIO = TRANSCRIPTS / "audio"
TRANSCRIPTS_ARCHIVE = TRANSCRIPTS / "family_archive"
DOCUMENTS = TRANSCRIPTS / "documents"                # документы людей: <карточка>/…
PHOTOS_PROCESSED = TRANSCRIPTS / "photos_processed" # обработанные копии фото (оригинал — на этаже 1)
PHOTOS_RESTORED = PHOTOS_PROCESSED / "restored"      # реставрация (I5xxxxx_… — чей портрет)
PHOTOS_BOOK_SMALL = PHOTOS_PROCESSED / "book_small"  # уменьшенные копии для книг, имя + «_мал»

# 3 — исследование
RESEARCH = ROOT / "3_research"
TREE = RESEARCH / "tree"                             # заметки Obsidian: люди, места, источники, события
BIOS = TREE / "biographies"                          # биографии: «<Имя карточки> — биография.md», по одной на человека
BIO_SUFFIX = " — биография"                          # имя файла = имя карточки + это; переименовал карточку — bio_ids.py --fix
TRANSLATIONS = TREE / "translations"                 # все переводы: <es|pl|en>/<вид>/<имя оригинала>.md (+ 00_АВТОПЕРЕВОД.md)
TR_KINDS = ("biographies", "places", "facts", "photos", "sources", "documents")  # биография, место (и дом), факты человека,
# подпись фото, название источника, название документа человека


def tr_path(lang, kind, name):
    """Файл перевода: translations/<язык>/<вид>/<имя оригинала>.md — имя карточки, у фото — имя файла без расширения."""
    return TRANSLATIONS / lang / kind / f"{name}.md"
PEOPLE = TREE / "people"                             # карточки людей
PLACES = TREE / "places"
EVENTS = TREE / "events"
TREE_SOURCES = TREE / "sources"                      # карточки источников
TREE_DATA = RESEARCH / "tree_data"                   # машинные выгрузки дерева (json/csv/ged)
ENRICHED_GED = TREE_DATA / "enriched.ged"
GED_BACKUPS = TREE_DATA / ".ged_backups"
MH_WEB = TREE_DATA / "mh_web"                        # снимки нашего дерева на MyHeritage (myheritage_web.mjs)
MH_OTHERS = MH_WEB / "others"                        # снимки чужих деревьев MyHeritage (в git не храним)
FAMILIO_MATCH = TREE_DATA / "familio_match.json"
PERSON_SLUGS = TREE_DATA / "person_slugs.json"      # адреса страниц людей на сайте, однажды выданные (site_data.names)
GRAMPS_ARCHIVE = TREE_DATA / "gramps_archive"       # выгрузка Gramps 26.09.2026 и её сборка — архив, не пересобирать
PLACES_GEO = GRAMPS_ARCHIVE / "build" / "places_geo.json"   # места 26.09: старые написания → название, координаты
MOVED_LEGACY = TREE_DATA / "MOVED_2026-09-26.csv"   # ручная таблица переездов 26.09 (запасная для moves.py)
MOVED_TABLE = TREE_DATA / "MOVED.csv"               # все переезды по истории git (moves.py table), в git не храним
ARCHIVES_NOTES = RESEARCH / "archives"               # наши описи и каталоги архивов, варианты имён
ARCHIVES_CATALOG = ARCHIVES_NOTES / "catalog"
NAME_FORMS = ARCHIVES_NOTES / "варианты_имён.toml"
PHOTO_CATALOG = RESEARCH / "КАТАЛОГ_ФОТО.md"
TEMPLATES = RESEARCH / "templates"
DOSSIERS = RESEARCH / "_dossiers"
PAVEL = RESEARCH / setting("FTREE_RESEARCH_DIR", "search", toml="tree.research_dir")  # поиск: планы, журнал, находки
# (папка поиска — [tree] research_dir в ftree.toml; rodo init пишет «search»)
BIOGRAPHIES = PAVEL / "biographies"                  # документы по дереву Павла: индекс, линии рода, хронология, пробелы
SEARCH = PAVEL / "search"
FINDINGS = PAVEL / "findings"                        # отчёты о находках
MYHERITAGE_IDS = PAVEL / "myheritage_ids.json"       # наш номер карточки → номер человека на MyHeritage
RESEARCH_NEXT = PAVEL / "ПОИСК_ДАЛЬШЕ.md"               # «Что ещё искать» — вход: порядок, правила, по людям (сайт: /sources/next)
RESEARCH_ONLINE = PAVEL / "ПОИСК_ОНЛАЙН.md"             # задачи в сети: О, П, Р, Н
RESEARCH_OFFLINE = PAVEL / "ПОИСК_ОФФЛАЙН.md"           # письма в архивы (А) и вопросы родным (С)
RESEARCH_DONE = PAVEL / "ПОИСК_СДЕЛАНО.md"              # что уже искали: нашлось и пусто
RESEARCH_BY_PLACE = PAVEL / "ПОИСК_ПО_АРХИВАМ.md"       # те же открытые задачи по месту поиска (собирает search_by_place.py)
SEARCH_LOG = PAVEL / "ИСКАЛИ_журнал.tsv"                # журнал: какие кадры, запросы, дела и кого смотрели (searched.py)
# заметки этого дерева к навыкам: что искали, что нашли, решения (rodo skill-notes) — [skills] notes_dir в ftree.toml
# (от корня дерева; rodo init пишет «3_research/search/навыки»); не задано — <папка поиска>/навыки
SKILL_NOTES = ROOT / str(setting("FTREE_SKILL_NOTES", "", toml="skills.notes_dir") or (PAVEL / "навыки").relative_to(ROOT))

# 4 — для людей
OUTPUTS = ROOT / "4_outputs"
OUTPUTS_PAVEL = OUTPUTS / setting("FTREE_OUTPUTS_DIR", PAVEL.name, toml="tree.outputs_dir")  # анкеты, книги — [tree] outputs_dir
OUTPUTS_ARGENTINA = OUTPUTS / "argentina"
BOOKS = OUTPUTS_PAVEL / "books"
BOOK_AUTO = OUTPUTS_PAVEL / "book_auto"
BOOK_TRANSLATIONS = OUTPUTS_PAVEL / "book_translations"
BOOKS_ARGENTINA = OUTPUTS_ARGENTINA / "books"
FIGURES = BOOKS / "figures"
SITE = setting_path("FTREE_SITE_OUT", OUTPUTS / "site")  # готовый сайт для родни (web/scripts/site.mjs build), в git не хранится
SITE_EXPORT = setting_path("FTREE_SITE_EXPORT", OUTPUTS / "site_export")  # выгрузка для сайта: data/, media/, files/, site.json (site_export.py)


# Сырьё архивов — вне проекта, вне git и вне облака: только на этом Mac (2,9 ГБ сканов ГАСО и т.п.).
# В проект из сырья попадает только страница о нашем человеке — копией в 1_sources/found/ (документ дерева проект/ХРАНЕНИЕ.md, «Страницы архивов»).
# Где она — переменная ARCHIVES_LOCAL (пишет `rodo setup` в ~/.config/ftree/env из [places] archives в setup.toml
# дерева); не задана — ~/ftree-archives. В тексте и JSON путь пишем от этой папки: в .md — `<папка>/raw/gaso/…` той
# же записью, что в настройке, с «~» (check_links.py понимает), в JSON — "archives:raw/gaso/…". В навыках и
# справке папка названа `$ARCHIVES_LOCAL`; узнать её — `tools/py tools/scripts/paths.py ARCHIVES_LOCAL`.
ARCHIVES_ENV = "ARCHIVES_LOCAL"
ARCHIVES_DEFAULT = "~/ftree-archives"
ARCHIVES_LOCAL = setting_path(ARCHIVES_ENV, ARCHIVES_DEFAULT)
# как папку пишем в тексте: «~/…», если она в домашней папке
ARCHIVES_HOME = ("~/" + ARCHIVES_LOCAL.relative_to(Path.home()).as_posix()
                 if ARCHIVES_LOCAL.is_relative_to(Path.home()) else str(ARCHIVES_LOCAL))
ARCHIVES_RAW = ARCHIVES_LOCAL / "raw"                # сканы как скачаны: raw/<архив>/<фонд_опись_дело>/
ARCHIVES_TEXT = ARCHIVES_LOCAL / "text"              # распознанный текст чужих страниц: text/<архив>/<дело>/
ARCHIVES_ANALYTICS = ARCHIVES_LOCAL / "analytics"    # аналитика деревни: analytics/<приход>/ — все записи, с деревом не смешивать
GASO_RAW = ARCHIVES_RAW / "gaso"                     # ГАСО (Смоленск): 25 дел, ф48_оп<N>_д<N>/
RUSNEB_RAW = ARCHIVES_RAW / "rusneb_2026-09-30"      # справочники НЭБ (PDF списков мест и приходов)
ARCHIVES_REF = "archives:"                           # приставка пути от ARCHIVES_LOCAL в JSON
# где сырьё лежало до 02.10.2026; в gaso_smolensk/ остались опись и выписки — уехали только папки дел ф48_…
_OLD_RAW = (("1_sources/found/archives_online/gaso_smolensk/", GASO_RAW, "ф48"),
            ("1_sources/found/archives_online/rusneb_2026-09-30/", RUSNEB_RAW, ""))

RAW_HELP = {
    "gaso": "навык archive-gaso; адреса сканов на сервере архива — "
            "1_sources/found/archives_online/gaso_smolensk/00_ОПИСЬ_сканы_ГАСО_2026-10-01.md "
            "(доступ к сканам — платный час абонемента, повторного нет: сначала искать копию)",
    "rusneb_2026-09-30": "навык archive-rusneb (нужен российский адрес)",
}


class NoRaw(FileNotFoundError):
    """Нет папки с сырьём архива: на этом Mac его не скачивали или папка переехала."""


def need_raw(directory):
    """Папка сырья или понятная ошибка: где её ждали и как вернуть."""
    directory = Path(directory)
    if directory.is_dir():
        return directory
    try:
        archive = directory.relative_to(ARCHIVES_RAW).parts[0]
    except (ValueError, IndexError):
        archive = directory.name
    raise NoRaw(
        f"нет сырья: {directory}\n"
        f"  где лежит: только на этом Mac, вне проекта и облака; обычно — {ARCHIVES_HOME}/raw/{archive}/ "
        f"(другая папка — переменная {ARCHIVES_ENV})\n"
        f"  как вернуть: скопировать с другого Mac или из старой копии проекта; иначе скачать заново — "
        f"{RAW_HELP.get(archive, 'навык этого архива (archive-*)')}"
    )


def archive_ref(path):
    """Путь к файлу для записи в JSON: от папки архивов, от корня проекта или (иначе) полный."""
    path = Path(path)
    for base, prefix in ((ARCHIVES_LOCAL, ARCHIVES_REF), (ROOT, "")):
        try:
            return prefix + path.relative_to(base).as_posix()
        except ValueError:
            pass
    return str(path)


def archive_path(ref):
    """Обратно к archive_ref; понимает и старые пути сырья внутри проекта, и `<ARCHIVES_HOME>/…` («~/ftree-archives/…»)."""
    ref = str(ref)
    if ref.startswith(ARCHIVES_REF):
        return ARCHIVES_LOCAL / ref[len(ARCHIVES_REF):]
    if ref.startswith(ARCHIVES_HOME + "/"):
        return ARCHIVES_LOCAL / ref[len(ARCHIVES_HOME) + 1:]
    for old, new, first in _OLD_RAW:
        if ref.startswith(old) and ref[len(old):].startswith(first):
            return new / ref[len(old):]
    return Path(ref) if Path(ref).is_absolute() else ROOT / ref


def bio_path(stem):
    """Файл биографии человека по имени его карточки (tree/people/<stem>.md)."""
    return BIOS / f"{stem}{BIO_SUFFIX}.md"


def bio_owner(path):
    """Имя карточки по файлу биографии — или None, если это не файл биографии."""
    s = Path(path).stem
    return s[: -len(BIO_SUFFIX)] if s.endswith(BIO_SUFFIX) else None


# Настройки дерева из ftree.toml — то, что раньше было зашито в код
MYHERITAGE_SITE = setting("FTREE_MYHERITAGE_SITE", "", toml="myheritage.site")   # номер нашего дерева на MyHeritage


def as_dict() -> dict:
    """Всё, что нужно скриптам на других языках (JS, sh): пути и настройки после загрузчика."""
    import destinations  # читает CONFIG этого модуля — импорт здесь, не наверху
    site = CONFIG.get("site", {})
    return {
        "ROOT": str(ROOT), "APP": str(APP), "TOOLS": str(TOOLS), "SCRIPTS": str(SCRIPTS), "PY": str(PY), "WEB": str(WEB),
        "SITE": str(SITE), "SITE_EXPORT": str(SITE_EXPORT), "SITE_ASSETS": str(SITE_ASSETS), "CACHE": str(CACHE), "AI_WEIGHTS": str(AI_WEIGHTS),
        "ARCHIVES_LOCAL": str(ARCHIVES_LOCAL), "CDP_PORT": CDP_PORT, "ASR_HOME": str(ASR_HOME),
        "PHOTO_VENV": str(PHOTO_VENV), "PHOTO_MODELS": str(PHOTO_MODELS),
        "MH_WEB": str(MH_WEB), "MH_OTHERS": str(MH_OTHERS), "MYHERITAGE_IDS": str(MYHERITAGE_IDS),
        "FINDINGS": str(FINDINGS), "ARCHIVES_CATALOG": str(ARCHIVES_CATALOG), "MYHERITAGE_SITE": MYHERITAGE_SITE,
        "MYHERITAGE_URL_NAME": str(tree_conf("myheritage.url_name", "family")),
        "RADZIMA_CHECK": str(setting("RADZIMA_CHECK", "", toml="radzima.check")),
        # куда выкладывать и где хранить — только из настроек дерева (destinations.py); хуки спрашивают здесь
        "TREE_NAME": destinations.tree_name(), "RUN_PREFIX": str(destinations.run_file("")),
        "MEDIA_PUSH_AFTER_COMMIT": "1" if destinations.push_after_commit() else "",
        "SITE_PUBLISH_AFTER_PUSH": "1" if destinations.publish_after_push() else "",
        "SITE_TARGETS": destinations.site_targets(),
        "OPEN_UNTIL": str(site.get("open_until", "")), "OPEN_COUNTRIES": list(site.get("open_countries", [])),
    }


if __name__ == "__main__":
    # tools/py tools/scripts/paths.py            — всё JSON (так берут настройки .mjs и .sh)
    # tools/py tools/scripts/paths.py ИМЯ        — одно значение (список — JSON)
    values = as_dict()
    if len(sys.argv) > 1:
        v = values.get(sys.argv[1])
        if v is None:
            raise SystemExit(f"нет настройки {sys.argv[1]}; есть: {', '.join(values)}")
        print(json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v)
    else:
        print(json.dumps(values, ensure_ascii=False, indent=1))
