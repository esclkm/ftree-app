#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Парсит Facebook-экспорт (HTML) — список друзей с РЕАЛЬНЫМИ именами —
и сопоставляет с деревом: (1) точные совпадения с персонами, (2) друзья с
ФАМИЛИЯМИ рода (возможные новые родственники).

Выход: 1_sources/family/social/social_export/facebook_relatives.md (+ facebook_friends.csv)
"""
import os, re, csv, html, json
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import paths as P_
ROOT = str(P_.ROOT)
FB = os.path.join(str(P_.SOCIAL_EXPORT),"facebook")
FR = os.path.join(FB,"connections","friends","your_friends.html")

TR={'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'e','ж':'zh','з':'z','и':'i','й':'i',
'к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f','х':'h',
'ц':'c','ч':'ch','ш':'sh','щ':'sch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya'}
def tl(s): return ''.join(TR.get(c,c) for c in (s or '').lower())
def toks(name):
    out=[]
    for t in tl(name).split():
        t=re.sub(r'[^a-z]','',t)
        if len(t)<3: continue
        t=re.sub(r'(ovich|evich|ova|eva|aya|ski|sky|cki)$','',t) if len(t)>5 else t
        out.append(t)
    return out

def surname_stem(token):
    """нормализуем родовые окончания для сравнения фамилий (муж/жен/польск.)"""
    t=re.sub(r'[^a-z]','',tl(token))
    if len(t)>5:
        t=re.sub(r'(ova|eva|aya|ski|sky|cki|cka)$','',t)
        t=re.sub(r'(ov|ev|in)$','',t)
    return t

txt=open(FR,encoding="utf-8",errors="ignore").read()
friends=[]
for m in re.finditer(r'<h2[^>]*>([^<]+)</h2>\s*<footer[^>]*>.*?<div[^>]*>([^<]*)</div>', txt):
    friends.append((html.unescape(m.group(1).strip()), m.group(2).strip()))
if not friends:  # запасной: просто все <h2>
    friends=[(html.unescape(x.strip()),"") for x in re.findall(r'<h2[^>]*>([^<]+)</h2>', txt)]

P=json.load(open(str(P_.TREE_DATA/"persons.json"),encoding="utf-8"))
relids={r["id"] for r in json.load(open(str(P_.SEARCH/"relatives.json"),encoding="utf-8"))}
persons=[(p["id"],p.get("name",""),set(toks(p.get("name",""))),p["id"] in relids) for p in P]
# фамилии рода (ТОЛЬКО кровные ветви) — стем последнего токена имени
FAMS=set()
for pid,nm,tk,isrel in persons:
    if isrel:
        parts=[p for p in tl(nm).split() if re.sub(r'[^a-z]','',p)]
        if len(parts)>=2:                       # фамилия только при «Имя Фамилия»
            st=surname_stem(parts[-1])
            if len(st)>=4: FAMS.add(st)
FIRST={"dmitri","dmitrii","ivan","pavel","pavl","sergei","sergey","tatyan","natalya","natal",
 "olga","anastasiya","anton","galina","irina","maksim","maria","oleg","svetlana","viktoriya","yana",
 "evgenii","evgeni","aleksandr","aleksander","yuri","yurii","nina","vera","anna","maria"}
FAMS={x for x in FAMS if len(x)>=4 and x not in FIRST}
# ключевые фамилии рода латиницей (стемы), чтобы поймать варианты написания — ftree.toml, [social] key_surnames
FAMS |= {surname_stem(x) for x in P_.tree_conf("social.key_surnames", [])}
FAMS={x for x in FAMS if len(x)>=4}

def match_person(tk):
    best=None
    for pid,nm,ptk,isrel in persons:
        if len(ptk)<2 or len(tk)<2: continue
        inter=len(tk & ptk)
        if inter>=2:
            sc=inter+(5 if isrel else 0)
            if best is None or sc>best[0]: best=(sc,pid,nm,isrel)
    return best

exact=[]; famhits=[]; rest=0
for name,date in friends:
    tk=set(toks(name))
    m=match_person(tk)
    stems={surname_stem(p) for p in name.split()}
    fam = stems & FAMS
    if m:
        exact.append((name,date,m[1],m[2],m[3]))
    elif fam:
        famhits.append((name,date,sorted(fam)))
    else:
        rest+=1

with open(os.path.join(str(P_.SOCIAL_EXPORT),"facebook_friends.csv"),"w",newline="",encoding="utf-8") as f:
    w=csv.writer(f); w.writerow(["name","friend_since","type","match_id","match_name"])
    for n,d,i,nm,r in exact: w.writerow([n,d,"совпадение с деревом",i,nm])
    for n,d,fam in famhits: w.writerow([n,d,"фамилия рода: "+",".join(fam),"",""])

out=[f"# Facebook-друзья ↔ дерево\n",
 f"Всего друзей: **{len(friends)}**. Совпадений с персонами дерева: **{len(exact)}**; "
 f"друзей с фамилией рода (возможная новая родня): **{len(famhits)}**; прочих: {rest}.\n"]
out.append("\n## A. Совпадения с персонами дерева\n")
out.append("| Друг (FB) | Персона дерева | кровный | друзья с |\n|---|---|---|---|")
for n,d,i,nm,r in sorted(exact,key=lambda x:not x[4]):
    out.append(f"| {n} | `{i}` {nm} | {'✅' if r else '(супруг/иное)'} | {d} |")
out.append(f"\n## B. Друзья с ФАМИЛИЕЙ рода — возможные новые родственники ({len(famhits)})\n")
out.append("> Проверьте: кто из них родня и кем приходится.\n")
out.append("| Друг (FB) | фамилия рода | друзья с |\n|---|---|---|")
for n,d,fam in sorted(famhits,key=lambda x:x[2]):
    out.append(f"| {n} | {', '.join(fam)} | {d} |")
# C. полный список друзей — для ручной разметки (друзей мало)
out.append(f"\n## C. ВСЕ друзья ({len(friends)}) — отметьте, кто родня\n")
out.append("| # | Имя друга | в друзьях с |\n|---|---|---|")
for i,(n,d) in enumerate(sorted(friends),1):
    out.append(f"| {i} | {n} | {d} |")
open(os.path.join(str(P_.SOCIAL_EXPORT),"facebook_relatives.md"),"w",encoding="utf-8").write("\n".join(out))

print(f"друзей: {len(friends)} | совпало с деревом: {len(exact)} | фамилия рода: {len(famhits)} | прочих: {rest}")
print("Файлы: 1_sources/family/social/social_export/facebook_relatives.md, facebook_friends.csv")
