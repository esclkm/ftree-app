#!/usr/bin/env python3
"""ГАСО: «открыть» дыры в деле — пролистать развороты в просмотрщике, чтобы сервер начал отдавать их по прямому адресу.

Зачем. Сервер ГАСО отдаёт картинку разворота по прямому адресу (`gaso_download.py`) только после того, как её хоть раз
показал просмотрщик (навык archive-gaso, «Дыры 404»). Раньше это делали руками: опись → дело → «Просмотр сканов» →
пагинатор миниатюр → щелчок → стрелка вправо N раз — 10–15 шагов и несколько минут на каждое дело. Скрипт делает то же
одной командой в своей вкладке Chrome проекта (`browser_cdp.mjs eval`) и в конце закрывает просмотрщик (about:blank).

    tools/py tools/scripts/gaso_unlock.py --opis-id 1034 --delo 2691 --from 223 --to 238
    затем: python3 .claude/skills/archive-gaso/gaso_download.py … --first 223 --last 238 --retry-missing --subscription-active

Нужно: вход Павла в Chrome проекта (`browser_cdp.mjs login-check gaso`) и действующий абонемент (остаток печатается
до и после). Абонемент тратится слабо: 32 разворота ≈ 9 секунд (02.11.2026). Разворот, который никто не открывал, сервер готовит
долго (до минуты) — скрипт ждёт до 90 с на шаг; для 30+ разворотов запускать в фоне. Номер разворота = номер файла на сервере.
`--opis-id` — номер описи на портале (`opisView.jsf?id=`): ф. 48 оп. 1 — 1034, оп. 2 — 1035, оп. 3 — 1037, оп. 6 — 1040.
"""
import argparse
import json
import re
import subprocess
import sys
import time
from functools import partial

print = partial(print, flush=True)  # noqa: A001 — вывод сразу, скрипт идёт минутами
from pathlib import Path

CDP = str(Path(__file__).resolve().parent / "browser_cdp.mjs")
PORTAL = "https://portal.gaso-smolensk.ru/page/portal"


def cdp(*args: str, timeout: int = 300) -> str:
    try:
        r = subprocess.run(["node", CDP, *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        sys.exit(f"browser_cdp {args[0]}: нет ответа за {timeout} с — проверить вкладку (browser_cdp.mjs status)")
    out = (r.stdout or "").strip().splitlines()
    if r.returncode or not out:
        sys.exit(f"browser_cdp {args[0]}: {(r.stderr or r.stdout).strip()[-300:]}")
    return out[-1]


def js(body: str, timeout: int = 300) -> str:
    return cdp("eval", "(async()=>{const w=ms=>new Promise(r=>setTimeout(r,ms));" + body + "})()", timeout=timeout)


def remaining() -> str:
    cdp("nav", f"{PORTAL}/personalAccount.jsf")
    time.sleep(2)
    m = re.findall(r"\d\d:\d\d:\d\d", cdp("eval", "document.body.innerText.replace(/\\s+/g,' ')"))
    return m[0] if m else "нет абонемента"


def open_delo(opis_id: int, delo: str) -> str:
    cdp("nav", f"{PORTAL}/opisView.jsf?id={opis_id}")
    want = json.dumps(rf"Д\. {re.escape(delo)}\.")
    found = js(f"""
const want=new RegExp({want});
[...document.querySelectorAll("a")].find(a=>a.textContent.trim()==="Единицы хранения").click(); await w(3000);
const s=[...document.querySelectorAll("select")].find(x=>[...x.options].some(o=>o.value==="200"));
s.value="200"; s.dispatchEvent(new Event("change",{{bubbles:true}})); await w(4000);
const pag=()=>[...document.querySelectorAll(".ui-paginator")].map(x=>({{x,t:(x.querySelector(".ui-paginator-current")||{{}}).textContent||""}}))
  .filter(o=>/из \\d{{3,}}/.test(o.t)).map(o=>o.x)[0];
const row=()=>[...document.querySelectorAll("table tbody tr")].find(t=>want.test(t.innerText));
const first=pag().querySelector(".ui-paginator-first"); if(first && !first.className.includes("disabled")){{const c=pag().querySelector(".ui-paginator-current").textContent; first.click(); for(let k=0;k<40 && pag().querySelector(".ui-paginator-current").textContent===c;k++) await w(250);}}
for(let i=0;i<40 && !row();i++){{const c=pag().querySelector(".ui-paginator-current").textContent; const nx=pag().querySelector(".ui-paginator-next");
  if(nx.className.includes("disabled")) break; nx.click(); for(let k=0;k<40 && pag().querySelector(".ui-paginator-current").textContent===c;k++) await w(250); await w(500);}}
const tr=row(); if(tr){{return tr.innerText.replace(/\\s+/g," ").slice(0,90);}}
return "нет";""")
    if found == "нет":
        sys.exit(f"дело {delo} в описи {opis_id} не найдено")
    time.sleep(2)
    cdp("eval", "(()=>{const r=[...document.querySelectorAll('table tbody tr')].find(t=>new RegExp(" + want +
        ").test(t.innerText)); setTimeout(()=>r.querySelector('a').click(),100); return 'ok'})()")
    for _ in range(20):
        time.sleep(1)
        if "sourceInfo" in cdp("eval", "location.href"):
            break
    else:
        sys.exit("дело не открылось (страница описи осталась) — запустить ещё раз")
    try:
        js("""await w(2500); const b=[...document.querySelectorAll("a,button,span")].find(x=>/Просмотр сканов/.test(x.textContent));
if(!b) return "нет"; setTimeout(()=>(b.closest("a,button")||b).click(),100); return "ok";""")
    except SystemExit:
        pass  # страница уходит на просмотрщик посреди вызова — это нормально
    time.sleep(7)
    return found


def flip(first: int, last: int) -> list[str]:
    """Встать на разворот first-1 (миниатюра с индексом first-2) и листать вправо до last."""
    target = first - 2
    got = js(f"""const target={target};
const P=()=>document.getElementById("form:dataPreview_paginator_bottom");
const cur=()=>P().querySelector(".ui-paginator-current").textContent;
const find=()=>[...document.querySelectorAll("a.ui-commandlink")].find(a=>a.id.startsWith("form:dataPreview:"+target+":"));
for(let k=0;k<60 && !P();k++) await w(500); if(!P()) return "нет просмотрщика: "+location.href;
for(let i=0;i<200 && !find();i++){{const c=cur(); P().querySelector(".ui-paginator-next").click();
  for(let k=0;k<30 && cur()===c;k++) await w(200); await w(800);}}
const a=find(); if(!a) return "не дошёл: "+cur();
const bg=()=>getComputedStyle(document.querySelector(".scanImage")).backgroundImage; const b0=bg(); a.click();
for(let k=0;k<40 && bg()===b0;k++) await w(250);
return "ok "+cur();""", timeout=900)
    if not got.startswith("ok"):
        js('setTimeout(()=>{location.href="about:blank"},50); return "";')
        sys.exit(got)
    seen = js(f"""const out=[]; const bg=()=>getComputedStyle(document.querySelector(".scanImage")).backgroundImage;
try{{for(let i=0;i<{last - first + 1};i++){{const b=bg(); document.querySelector(".btn-right").click();
  let k=0; for(;k<360 && bg()===b;k++) await w(250); if(k>=360){{out.push("СТОП"); break;}}
  await w(400); out.push(decodeURIComponent(bg()).match(/\\((\\d+)\\)|Страница_(\\d+)/)?.slice(1).find(Boolean)||"?");}}}}
finally{{setTimeout(()=>{{location.href="about:blank"}},50);}}
return out.join(",");""", timeout=1800)
    return seen.split(",")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--opis-id", type=int, required=True)
    p.add_argument("--delo", required=True)
    p.add_argument("--from", dest="first", type=int, required=True)
    p.add_argument("--to", dest="last", type=int, required=True)
    a = p.parse_args()
    print("абонемент до:", remaining())
    print("дело:", open_delo(a.opis_id, a.delo))
    seen = flip(a.first, a.last)
    print(f"пролистано {len(seen)}: {seen[0]}…{seen[-1]}" if seen else "ничего не пролистано")
    print("абонемент после:", remaining())
    return 0 if seen and "СТОП" not in seen else 1


if __name__ == "__main__":
    sys.exit(main())
