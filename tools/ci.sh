#!/bin/sh
# Все проверки дерева подряд. Так их запускает GitHub на каждый запрос на слияние (.github/workflows/checks.yml);
# на Mac — то же самое: tools/ci.sh. Код выхода не 0, если хоть одна проверка нашла ошибку или если пересчёт веток
# и доктор карточек что-то поменяли (значит, в коммите забыли пересчитать — на Mac это делает хук pre-commit).
# Фото, звука и PDF на GitHub нет (они в облаке): перед проверками media.py stub ставит пустышки по описи.
set -u
# Дерево — до смены папки: из той, откуда позвали (вверх до ftree.toml), если FTREE_ROOT не задан явно. Иначе после cd
# в приложение paths.py нашёл бы дерево из ~/.config/ftree/env — проверка ушла бы в чужое (настоящее) дерево.
if [ -z "${FTREE_ROOT:-}" ]; then
  FTREE_ROOT=$("$(dirname "$0")/py" "$(dirname "$0")/scripts/paths.py" ROOT) || exit 2
fi
export FTREE_ROOT
cd "$(dirname "$0")/.." || exit 2
PY=tools/py
S=tools/scripts
FAILED=""

group() { [ -n "${GITHUB_ACTIONS:-}" ] && echo "::group::$1" || echo "== $1"; }
endgroup() { [ -n "${GITHUB_ACTIONS:-}" ] && echo "::endgroup::"; return 0; }
# Проверки только читают — идут одновременно, каждая в свой файл; вывод — потом, по порядку (было по очереди ~30 с, стало ~13 с)
JOBS=$(mktemp -d "${TMPDIR:-/tmp}/ftree-ci.XXXXXX")
trap 'rm -rf "$JOBS"' EXIT
N=0
job() {  # job <check|report> <название> <команда…> — report: только отчёт, ошибка проверку не валит
  N=$((N + 1)); n=$(printf %02d $N)
  printf '%s\n%s\n' "$1" "$2" >"$JOBS/$n.name"; shift 2
  ( "$@" >"$JOBS/$n.out" 2>&1; echo $? >"$JOBS/$n.code" ) &
}
check() { job check "$@"; }
report() { job report "$@"; }

[ -n "${CI:-}" ] && $PY $S/media.py stub

# Дерево, которое проверяем, — найдено выше, до смены папки. Скрипты — из приложения (папка этого файла), git — в папке
# дерева.
TREE=$FTREE_ROOT
[ "${1:-}" = "--root" ] && { echo "$TREE"; exit 0; }   # какое дерево проверили бы — и выйти (тест, отладка)

# пересчёт: ветки и доктор карточек не должны ничего менять в закоммиченном
before=$(git -C "$TREE" diff | shasum)
$PY $S/assign_lineage.py >/dev/null && $PY $S/card_doctor.py --fix --quiet >/dev/null
if [ "$(git -C "$TREE" diff | shasum)" != "$before" ]; then
  group "пересчёт веток и доктор карточек поменяли файлы"
  git -C "$TREE" -c core.quotepath=false diff --stat
  endgroup
  FAILED="$FAILED
  ✗ ветки или карточки не пересчитаны: tools/py $S/assign_lineage.py; tools/py $S/card_doctor.py --fix — и в коммит"
fi

check "дерево (check_tree)"               $PY $S/check_tree.py
check "карточки для сайта (check_cards)"  $PY $S/check_cards.py
check "линии жизни (check_lifeline)"      $PY $S/check_lifeline.py
check "годы жизни (check_lifespan)"       $PY $S/check_lifespan.py
check "имена в карточках (check_names)"   $PY $S/check_names.py
check "биографии (check_bio)"             $PY $S/check_bio.py
check "даты (check_dates)"                $PY $S/check_dates.py
check "стиль дат до 1918 (date_styles)"   $PY $S/date_styles.py
check "документы (documents.py check)"    $PY $S/documents.py check
check "MyHeritage (myheritage_update lint)" $PY $S/myheritage_update.py lint
check "план поиска (check_search_plan)" $PY $S/check_search_plan.py
check "брак, развод, дети — у обоих (check_family_sync)" $PY $S/check_family_sync.py
check "места в фактах — ссылками, иначе нет на карте (check_fact_places)" $PY $S/check_fact_places.py
check "журнал поиска (searched)" $PY $S/searched.py check
check "каталог архивов (archives lint)" $PY $S/archives.py lint
check "скорость вопросов к дереву (check_tree_speed)" $PY $S/check_tree_speed.py
# тесты — про код приложения, не про проверяемое дерево: идут на вымышленном образце (tests/sample_tree.py собирает его
# из tools/sample/sample.ged и сам ставит FTREE_ROOT), живое дерево не читают
# FTREE_CI_SKIP_TESTS=1 — без тестов: так ci.sh зовёт тест «из коробки» (tests/test_import_gedcom.py), иначе тесты по кругу
[ -z "${FTREE_CI_SKIP_TESTS:-}" ] && \
check "тесты скриптов"                    env -u FTREE_ROOT $PY -m unittest discover -s $S/tests -q
report "ссылки (check_links) — только отчёт"   sh -c "$PY $S/check_links.py | tail -3"
report "логика семьи по датам (check_family_logic) — только отчёт" $PY $S/check_family_logic.py --quiet
report "дата есть, факта нет (check_fact_dates) — только отчёт" sh -c "$PY $S/check_fact_dates.py | tail -1"
wait

for f in "$JOBS"/*.name; do
  n=${f%.name}
  kind=$(sed -n 1p "$f"); name=$(sed -n 2p "$f"); code=$(cat "$n.code")
  group "$name"
  cat "$n.out"
  endgroup
  [ "$kind" = check ] && [ "$code" -ne 0 ] && { FAILED="$FAILED
  ✗ $name (код $code)"; [ -n "${GITHUB_ACTIONS:-}" ] && echo "::error::$name: ошибки — подробно в шаге выше"; }
done

if [ -n "$FAILED" ]; then
  echo "Не прошло:$FAILED"
  exit 1
fi
echo "Все проверки прошли."
