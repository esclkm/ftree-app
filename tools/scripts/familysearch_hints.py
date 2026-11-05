#!/usr/bin/env python3
"""Подсказки FamilySearch к нашим людям — одной командой, и только то, чего в прошлый раз не было.

Зачем. Мы загрузили часть дерева в общее дерево FamilySearch (номера — `familysearch_match.json`). Сайт сам приносит
к людям «подсказки»: подходящие записи из своих указателей и совпадения в чужих деревьях. Раньше проверку делали
руками: сниппет в браузере, потом глазами сравнивали со старым отчётом. Теперь скрипт обходит всех с номерами
в своей вкладке Chrome проекта (вход Павла, `browser_cdp.mjs`), по одному запросу с паузой 1,5 с, и печатает
только новые подсказки и новые чужие правки. Снимок прошлой проверки — `familysearch_hints.json`.

    tools/py tools/scripts/familysearch_hints.py           # проверить, показать новое (снимок не трогает)
    tools/py tools/scripts/familysearch_hints.py --save    # то же и записать снимок: эти подсказки разобраны

Только чтение: на сайт ничего не пишет, подсказки не принимает и не отклоняет. 50 человек ≈ 3 минуты.
После проверки — строка в журнал поиска (`searched.py add familysearch "общее дерево: …"`), по ней sync.py
считает, когда пора следующая.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import paths  # noqa: E402
from paths import ROOT, TREE_DATA  # noqa: E402

MATCH = TREE_DATA / "familysearch_match.json"
SNAP = TREE_DATA / "familysearch_hints.json"
ME = str(paths.tree_conf("familysearch.account", ""))   # аккаунт владельца дерева на FamilySearch: свои правки не показываем

JS = """(async()=>{const ids=%s; const out={}; const sl=ms=>new Promise(r=>setTimeout(r,ms));
const get=async u=>{const r=await fetch(u,{headers:{accept:'application/json'}}); return r.status===200?r.json():r.status;};
for(const id of ids){ const o={hints:[],edits:[]};
 try{const j=await get('/service/tree/tree-data/match/persons/'+id);
  if(typeof j==='number'){ if(j!==204) o.error='HTTP '+j; }
  else for(const m of (j.tdMatches||[])){const p=m.person||{};
   o.hints.push({type:m.matchType,id:(m.matchingRecordId||p.id||'').split('/').pop(),name:p.name||'',
    life:p.lifespan||'',place:p.birth?.details?.place?.originalText||''});}
 }catch(e){o.error=String(e)}
 await sl(1500);
 try{const j=await get('/service/tree/tree-data/contributions/person/'+id);
  if(typeof j!=='number') for(const c of (j.contributions||[])) if(c.contributorName!==%s)
   o.edits.push({date:c.modificationDate,who:c.contributorName,type:c.type});
 }catch(e){o.error=String(e)}
 out[id]=o; if(String(o.error).includes('429')) break; await sl(1500);}
return JSON.stringify(out);})()"""


def fetch(ids):
    """Обход в браузере → {номер FS: {hints, edits, error?}}."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "hints.json"
        js = JS % (json.dumps(ids), json.dumps(ME))
        r = subprocess.run(["node", str(paths.SCRIPTS / "browser_cdp.mjs"), "eval", js, "--out", str(out)],
                           capture_output=True, text=True, timeout=60 + 4 * len(ids))
        if r.returncode or not out.exists():
            sys.exit(f"браузер не ответил: {(r.stderr or r.stdout).strip()[-300:]}\n"
                     "проверить вход: node tools/scripts/browser_cdp.mjs login-check familysearch")
        data = json.loads(out.read_text(encoding="utf-8"))
        return json.loads(data) if isinstance(data, str) else data


def edit_key(e):
    return f"{e['date']} {e['who']} {e['type']}"


def news(now, before):
    """Новое против снимка: [(номер FS, «подсказка»|«правка», строка)]. Кого в снимке не было — всё его новое."""
    out = []
    for fs, o in now.items():
        old = before.get(fs, {})
        seen = {h["id"] for h in old.get("hints", [])}
        out += [(fs, "подсказка", f"{h['type']} {h['id']} | {h['name']} {h['life']} | {h['place']}")
                for h in o.get("hints", []) if h["id"] not in seen]
        seen = {edit_key(e) for e in old.get("edits", [])}
        out += [(fs, "правка", edit_key(e)) for e in o.get("edits", []) if edit_key(e) not in seen]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--save", action="store_true", help="записать снимок: всё показанное считается разобранным")
    a = ap.parse_args()
    match = json.loads(MATCH.read_text(encoding="utf-8"))
    stem = {v["fs"]: v["stem"] for v in match.values()}
    now = fetch(sorted(stem))
    before = json.loads(SNAP.read_text(encoding="utf-8")) if SNAP.exists() else {}
    errors = {fs: o["error"] for fs, o in now.items() if o.get("error")}
    missing = sorted(set(stem) - set(now))
    hinted = sum(1 for o in now.values() if o.get("hints"))
    print(f"проверено {len(now)} из {len(stem)}; подсказки у {hinted}, всего {sum(len(o['hints']) for o in now.values())}")
    for fs, kind, text in news(now, before):
        print(f"  НОВОЕ {kind}: {stem[fs]} ({fs}) — {text}")
    if not news(now, before):
        print("  нового против прошлой проверки нет")
    for fs, err in errors.items():
        print(f"  ошибка: {stem[fs]} ({fs}) — {err}")
    if missing:
        print(f"  не дошли (лимит сайта?): {len(missing)} — повторить через час")
    if a.save and not errors and not missing:
        SNAP.write_text(json.dumps(now, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"снимок: {SNAP.relative_to(ROOT)}")
    elif a.save:
        print("снимок не записан: проверка неполная")


if __name__ == "__main__":
    main()
