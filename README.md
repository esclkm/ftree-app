# ftree-app

**English** · [Русский](#русский)

A toolkit for keeping a family tree as plain Markdown files in git — and turning it into a private website for
relatives. The tree itself (people, places, sources, biographies) lives in **your own repository**; this repository
is only the code: no family data inside.

- **`rodo`** — one command for everything: create a tree, import GEDCOM, run checks, build the site.
- **Cards** — one Markdown file per person, place, source and event, with facts that always cite a source and a
  confidence level. Dates follow GEDCOM (`ABT 1935`, `BET 1941 AND 1945`), including Julian/Gregorian dates before 1918.
- **Checks** — about twenty checks keep the tree consistent (both spouses carry the same marriage, a child is in the
  parent's life line, a year in a story is backed by a fact…). They run before each commit and on GitHub.
- **Site** — `web/` is a React app in four languages (RU, PL, ES, EN). The engine exports JSON (`web/schema/`); living
  people, addresses and closed documents are hidden *before* the files are written. Hosting: a folder, Cloudflare
  Pages (with a password), Netlify or a Worker mirror — only where your tree's `ftree.toml` says.
- **Claude Code skills** — `.claude/skills/` hold the method (how to write a card, a biography, read a parish record,
  search an archive). Load them as a plugin; each tree keeps its own notes next to the data (`rodo skill-notes <skill>`).

### Quick start (macOS)

```bash
git clone https://github.com/esclkm/ftree-app ~/ftree-app
cd ~/ftree-app && brew bundle && uv sync --frozen && (cd web && npm ci)
tools/rodo link                                   # puts `rodo` into ~/.local/bin
rodo init ~/my-tree --title "Family tree of …"    # empty tree: folders, ftree.toml, setup/, git
cd ~/my-tree
rodo import gedcom ~/Downloads/export.ged         # your GEDCOM → cards (into an empty tree)
rodo setup                                        # checks the workplace, fixes what it can, tells you the rest
rodo check                                        # all checks
rodo site export && rodo site build               # site → 4_outputs/site
```

Try it on the fictional sample first: `rodo import gedcom ~/ftree-app/tools/sample/sample.ged`
(about 30 invented people; `tools/sample/README.md` lists what is deliberately tricky in it).

Importing into a tree that already has people does not merge anything: it writes a report and `maybe_same` hints
(`--dry-run` only shows what would happen).

### Layout

| Path | What |
|---|---|
| `tools/rodo`, `tools/scripts/` | the engine: card library (`cards/`), checks, import, site export, storage |
| `tools/githooks/` | git hooks of a tree (`rodo hook install`) |
| `tools/init_template/`, `tools/sample/` | what `rodo init` writes; the fictional GEDCOM sample |
| `tools/CLAUDE.app.md` | rules for Claude shared by every tree (a tree's `CLAUDE.md` imports it) |
| `web/` | site app, JSON schemas, site builder (`web/scripts/site.mjs`), hosting assets |
| `.claude/skills/`, `.claude-plugin/` | skills as a Claude Code plugin |

### Claude Code plugin

A tree made by `rodo init` already declares the plugin in its `.claude/settings.json` (`extraKnownMarketplaces` →
GitHub `esclkm/ftree-app`, `enabledPlugins` → `ftree@ftree-app`); `rodo setup` adds it to an older tree. Install it
once per Mac, from the tree's folder:

```bash
claude plugin install ftree@ftree-app --scope project
```

Skills then appear as `ftree:<skill>`. Each skill starts with a line that pastes the tree's own notes for it
(`rodo skill-notes --embed <skill>`; no notes — nothing). While developing, `claude --plugin-dir ~/ftree-app` loads
the skills straight from the app folder for one session.

### Versions

A tree records the app version it works with (`[app] version` in `setup/setup.toml`); `rodo` compares it on every
run and warns when the app is older, or from another series (before 1.0 — the first two numbers).

### Tests

`rodo test` — unit tests on the fictional sample and invented examples only (they never read a real tree; names,
places, dates and addresses in tests and comments are made up). The GitHub workflow builds a tree from
scratch: `rodo init` → import `sample.ged` → all checks → tests → site export and build.

License: MIT.

---

## Русский

Набор инструментов, чтобы вести родословное дерево обычными файлами Markdown в git — и собирать из него закрытый сайт
для родни. Само дерево (люди, места, источники, биографии) лежит **в вашем репозитории**; здесь только код, данных
семьи здесь нет.

- **`rodo`** — одна команда на всё: создать дерево, загрузить GEDCOM, проверить, собрать сайт.
- **Карточки** — один файл на человека, место, источник, событие; у каждого факта — источник и уверенность. Даты — как
  в GEDCOM, с двумя календарями до 1918 года.
- **Проверки** — около двадцати: брак у обоих супругов, ребёнок в линии жизни родителя, год в рассказе подтверждён
  фактом… Идут перед каждым коммитом и на GitHub.
- **Сайт** — приложение `web/` на четырёх языках. Движок выгружает JSON; живые люди, адреса и закрытые документы
  скрываются до того, как файлы записаны. Куда выкладывать — только то, что вписано в `ftree.toml` дерева.
- **Навыки Claude Code** — метод работы (карточка, биография, метрика, архив) плагином; заметки своего дерева — рядом с
  данными (`rodo skill-notes <навык>`).

### Начать (macOS)

```bash
git clone https://github.com/esclkm/ftree-app ~/ftree-app
cd ~/ftree-app && brew bundle && uv sync --frozen && (cd web && npm ci)
tools/rodo link                                   # команда rodo в ~/.local/bin
rodo init ~/my-tree --title "Родословная …"       # пустое дерево: этажи, ftree.toml, setup/, git
cd ~/my-tree
rodo import gedcom ~/Downloads/export.ged         # свой GEDCOM → карточки (в пустое дерево)
rodo setup                                        # рабочее место: проверит, поставит, скажет, что сделать человеку
rodo check                                        # все проверки
rodo site export && rodo site build               # сайт → 4_outputs/site
```

Пример — вымышленное дерево: `rodo import gedcom ~/ftree-app/tools/sample/sample.ged` (около 30 выдуманных людей; что
в нём нарочно сложного — `tools/sample/README.md`). В живое дерево импорт ничего не сливает: отчёт и подсказки
`maybe_same` (`--dry-run` — только показать).

Плагин навыков объявлен в `.claude/settings.json` дерева (`rodo init` пишет, `rodo setup` дописывает в старое дерево);
поставить один раз на Mac из папки дерева: `claude plugin install ftree@ftree-app --scope project`. Навыки —
`ftree:<навык>`; в начале каждого — строка, которая сама вклеивает заметки дерева к нему. Для разработки —
`claude --plugin-dir ~/ftree-app`. Дерево записывает, с какой версией приложения работает (`[app] version` в
`setup/setup.toml`), `rodo` сверяет при каждом запуске. Тесты — `rodo test`: только вымышленный образец и выдуманные
примеры (имена, места, даты, адреса в тестах и комментариях придуманы). Лицензия — MIT.
