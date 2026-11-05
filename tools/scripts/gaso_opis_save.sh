#!/bin/bash
# Снять названия всех дел описи ГАСО в каталог (вход не нужен) — чтобы искать по ним grep, а не ходить на портал заново.
#   tools/scripts/gaso_opis_save.sh <фонд> <опись> <id описи на портале>
#   tools/scripts/gaso_opis_save.sh 48 1 1034   → 3_research/archives/catalog/gaso/описи/ф48_оп1.txt
# id описи — на странице фонда на gaso-smolensk.ru (ссылка opisView.jsf?id=…). Работает через свой Chrome проекта
# (browser_cdp.mjs); по 200 строк на страницу, пауза 3,5 с между страницами. Длинный ответ browser_cdp кладёт во
# временный файл — скрипт забирает его сам.
set -euo pipefail
F="$1"; OP="$2"; ID="$3"
# дерево — из папки, откуда позвали, до смены папки (иначе paths.py возьмёт дерево из ~/.config/ftree/env)
[ -n "${FTREE_ROOT:-}" ] || FTREE_ROOT=$("$(dirname "$0")/../py" "$(dirname "$0")/paths.py" ROOT) || exit 2
export FTREE_ROOT
cd "$(dirname "$0")/../.."
OUT="$(tools/py tools/scripts/paths.py ARCHIVES_CATALOG)/gaso/описи/ф${F}_оп${OP}.txt"
B() { node tools/scripts/browser_cdp.mjs "$@"; }
B nav "https://portal.gaso-smolensk.ru/page/portal/opisView.jsf?id=$ID" >/dev/null
sleep 5
JS='(async()=>{const w=ms=>new Promise(r=>setTimeout(r,ms)); const a=[...document.querySelectorAll("a")].find(a=>a.textContent.trim()==="Единицы хранения"); if(!a) return "НЕТ ВКЛАДКИ"; a.click(); await w(4500); const s=[...document.querySelectorAll("select")].find(x=>[...x.options].some(o=>o.value==="200")); if(s){s.value="200"; s.dispatchEvent(new Event("change",{bubbles:true})); await w(6000);} let out=[], seen=new Set(); for(let p=1;p<200;p++){ const rows=[...document.querySelectorAll("table tbody tr")].map(tr=>tr.innerText.replace(/\s+/g," ").trim()).filter(t=>/^Ф\. '"$F"'\. Оп\./.test(t)); if(!rows.length||seen.has(rows[0])) break; seen.add(rows[0]); out.push(...rows); const nx=document.querySelector(".ui-paginator-next:not(.ui-state-disabled)"); if(!nx) break; nx.click(); await w(3500);} return out.join("\n")})()'
R=$(B eval "$JS")
P=$(echo "$R" | grep -oE "/var/folders/[^ ]+\.txt" || true)
{
  echo "# ГАСО ф. $F, оп. $OP — названия дел; https://portal.gaso-smolensk.ru/page/portal/opisView.jsf?id=$ID; снято $(date +%d.%m.%Y)"
  if [ -n "$P" ]; then grep "^Ф\. $F\." "$P"; else echo "$R" | grep "^Ф\. $F\." || true; fi
} > "$OUT"
echo "$OUT: $(( $(wc -l < "$OUT") - 1 )) дел"
