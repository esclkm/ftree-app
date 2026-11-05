#!/bin/bash
# Узнать адрес сканов дела ГАСО в просмотрщике: открыть дело в описи → «Просмотр сканов» → щёлкнуть первую миниатюру →
# прочитать адрес картинки и число снимков. Нужен вход в кабинет и абонемент (просмотрщик тратит ≈1 мин на дело).
#   tools/scripts/gaso_viewer_url.sh <фонд> <опись> <id описи> <дело> [<дело> …]
#   tools/scripts/gaso_viewer_url.sh 48 1 1034 2617 2618
# Вывод: «д.<дело> | <адрес первой картинки> | <N из M записей>». Опись должна лежать в
# 3_research/archives/catalog/gaso/описи/ф<ф>_оп<о>.txt (снять: gaso_opis_save.sh) — по ней скрипт знает, что дело есть.
set -uo pipefail
F="$1"; OP="$2"; ID="$3"; shift 3
# дерево — из папки, откуда позвали, до смены папки (иначе paths.py возьмёт дерево из ~/.config/ftree/env)
[ -n "${FTREE_ROOT:-}" ] || FTREE_ROOT=$("$(dirname "$0")/../py" "$(dirname "$0")/paths.py" ROOT) || exit 2
export FTREE_ROOT
cd "$(dirname "$0")/../.."
B() { node tools/scripts/browser_cdp.mjs "$@"; }
for D in "$@"; do
  B nav "https://portal.gaso-smolensk.ru/page/portal/opisView.jsf?id=$ID" >/dev/null; sleep 5
  R=$(B eval "(async()=>{const w=ms=>new Promise(r=>setTimeout(r,ms)); [...document.querySelectorAll('a')].find(a=>a.textContent.trim()==='Единицы хранения').click(); await w(4500); const s=[...document.querySelectorAll('select')].find(x=>[...x.options].some(o=>o.value==='200')); if(s){s.value='200'; s.dispatchEvent(new Event('change',{bubbles:true})); await w(6000);} for(let k=0;k<40;k++){ const tr=[...document.querySelectorAll('table tbody tr')].find(tr=>new RegExp('Д\\\\. $D\\\\.').test(tr.innerText)); if(tr){ setTimeout(()=>tr.querySelector('a').click(),100); return 'ok';} const nx=document.querySelector('.ui-paginator-next:not(.ui-state-disabled)'); if(!nx) return 'нет дела'; nx.click(); await w(4500);} return 'нет дела'})()")
  if [ "$R" != "ok" ]; then echo "д.$D | $R"; continue; fi
  sleep 8
  B eval 'setTimeout(()=>{const b=[...document.querySelectorAll("button")].find(a=>/Просмотр сканов/.test(a.innerText)); b&&b.click()},100); "ok"' >/dev/null
  sleep 12
  echo "д.$D | $(B eval '(async()=>{const w=ms=>new Promise(r=>setTimeout(r,ms)); const box=document.querySelector("#form\\:dataPreview"); if(!box) return "нет просмотрщика (вход? абонемент?) "+location.href; const items=[...box.querySelectorAll("a, div[onclick], .ui-datagrid-column > *")].filter(e=>e.offsetWidth>30); if(items[0]) items[0].click(); await w(5000); return decodeURIComponent(getComputedStyle(document.querySelector(".scanImage")).backgroundImage)+" | "+(box.querySelector(".ui-paginator")||{}).innerText?.replace(/\s+/g," ")})()')"
  B nav "https://portal.gaso-smolensk.ru/page/portal/opisView.jsf?id=$ID" >/dev/null   # закрыть просмотрщик
done
