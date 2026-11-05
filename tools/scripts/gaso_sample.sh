#!/bin/bash
# Скачать каждый K-й разворот дела ГАСО — чтобы по выборке найти нужную церковь/деревню в большом деле, не качая всё.
#   tools/scripts/gaso_sample.sh <папка дела в raw/gaso> <папка на сервере> "<имя файла с {n}>" <последний номер> <шаг> [root]
#   tools/scripts/gaso_sample.sh ф48_оп1_д2617 GASO_48_1_2617_3 "Ф48_оп1_д2617_л ({n}).JPG" 739 30
# В имени {n} — номер как есть, {n3} — с нулями (002). Файлы — <папка>/<Папка>_файл_NNN.jpg (как у gaso_download.py), один поток, пауза 1,5 с; уже скачанное пропускает.
set -uo pipefail
DIR="${ARCHIVES_LOCAL:-$HOME/ftree-archives}/raw/gaso/$1"; SF="$2"; TPL="$3"; LAST="$4"; STEP="$5"; ROOT="${6:-metrics_smolensky}"
mkdir -p "$DIR"; LABEL="$(echo "$1" | sed 's/^ф/Ф/')_файл"
for n in $(seq 1 "$STEP" "$LAST"); do
  out="$DIR/${LABEL}_$(printf %03d "$n").jpg"; [ -s "$out" ] && continue
  n3=$(printf %03d "$n"); name="${TPL//\{n3\}/$n3}"; name="${name//\{n\}/$n}"
  url="https://portal.gaso-smolensk.ru/thumbnails/$ROOT/$SF/$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))" "$name")_watermark.jpg"
  code=$(curl -s --max-time 120 -o "$out.part" -w "%{http_code}" "$url")
  if [ "$code" = 200 ]; then mv "$out.part" "$out"; else rm -f "$out.part"; echo "$n: $code"; fi
  case "$code" in 401|403|429) echo "СТОП: $code"; exit 3;; esac
  sleep 1.5
done
echo "$1: $(ls "$DIR"/*.jpg 2>/dev/null | wc -l) файлов"
