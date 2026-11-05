#!/bin/sh
# Выгрузка + сборка + выкладка сайта для родни — туда, куда велел владелец дерева (ftree.toml, [[site.target]]).
# Запускается сам после push в master, если в ftree.toml [site] publish_after_push = true (tools/githooks/pre-push);
# вручную — rodo site all. Два шага: выгрузка (rodo site export — карточки → 4_outputs/site_export) и сборка с выкладкой
# (rodo site publish — web/scripts/site.mjs, карточек не видит). Целей нет — сайт собирается, но никуда не уходит.
# Пароль на сайт — секрет SITE_PASSWORD в настройках проекта на хостинге (в коде его нет; см. functions/_middleware.js).
#
# Первый раз на новом компьютере — вход на хостинг (например, npx wrangler login); навык setup.
set -e
# дерево — из папки, откуда позвали, до смены папки (иначе paths.py возьмёт дерево из ~/.config/ftree/env)
[ -n "${FTREE_ROOT:-}" ] || FTREE_ROOT=$("$(dirname "$0")/../py" "$(dirname "$0")/paths.py" ROOT) || exit 2
export FTREE_ROOT
cd "$(dirname "$0")/../.."
setting() { tools/py tools/scripts/paths.py "$1"; }   # настройки — тем же загрузчиком, что у скриптов

# Коммиты подряд: выкладка уже идёт — отмечаем «надо ещё раз» и выходим; идущая выкладка повторит себя в конце
LOCK="$(setting RUN_PREFIX)publish.lock"
if ! mkdir "$LOCK" 2>/dev/null; then touch "$LOCK/again"; echo "Выкладка уже идёт — она повторится с последними правками."; exit 0; fi
trap 'rm -rf "$LOCK"' EXIT
# Только сборка и выкладка — без ИИ. Переводы биографий, которые отстали от русского текста, хук git не делает:
# их видно в сводке при старте сессии (sync.py status), переводят по решению — tools/py tools/scripts/sync.py translate.
while :; do
  rm -f "$LOCK/again"
  echo "== $(date '+%Y-%m-%d %H:%M:%S') сборка и выкладка"
  tools/rodo site export
  tools/rodo site publish   # копии iCloud «страница 2.html» сборщик на сайт не пускает
  [ -e "$LOCK/again" ] || break
done
echo "== готово"
