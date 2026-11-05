#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Парсит Instagram-экспорт (HTML) и сопоставляет аккаунты с родственниками в дереве.
Источник: 1_sources/family/social/social_export/instagram
Выход: 1_sources/family/social/social_export/instagram_relatives.md (+ _all_handles.csv)

Сопоставление: транслитерация имени персоны (кириллица->латиница) и поиск в IG-логине
(логины обычно = имяфамилия слитно). Близкие контакты (переписки) помечаются отдельно.
"""
import os, re, csv, html, json
from collections import OrderedDict

import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import paths as P_
ROOT = str(P_.ROOT)
IG = os.path.join(str(P_.SOCIAL_EXPORT), "instagram")
OUTMD = os.path.join(str(P_.SOCIAL_EXPORT), "instagram_relatives.md")
OUTCSV = os.path.join(str(P_.SOCIAL_EXPORT), "instagram_all_handles.csv")

def read(path):
    try: return open(path, encoding="utf-8", errors="ignore").read()
    except FileNotFoundError: return ""

# --- собрать аккаунты из following/followers ---
def extract_handles(htmltext):
    out = OrderedDict()
    # ссылки вида instagram.com/<handle> с текстом-таймстампом рядом
    for m in re.finditer(r'instagram\.com/(?:_u/)?([A-Za-z0-9_.]+)', htmltext):
        h = m.group(1).strip().strip('/')
        if h and h.lower() not in ("p","reel","explore","accounts","_u"):
            out.setdefault(h, h)
    return out

following = extract_handles(read(os.path.join(IG,"connections/followers_and_following/following.html")))
followers = extract_handles(read(os.path.join(IG,"connections/followers_and_following/followers_1.html")))

# --- близкие контакты: имена папок переписок ---
inbox = os.path.join(IG,"your_instagram_activity/messages/inbox")
chats = []
if os.path.isdir(inbox):
    for d in os.listdir(inbox):
        slug = re.sub(r'_\d+$','',d)         # убрать числовой ID
        chats.append((slug, d))

allh = OrderedDict()
for h,t in following.items(): allh.setdefault(h,set()).add("подписка")
for h,t in followers.items(): allh.setdefault(h,set()).add("подписчик")
chat_slugs = {c[0] for c in chats}

# --- дерево: транслит-ключи персон ---
TR={'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'e','ж':'zh','з':'z','и':'i','й':'i',
'к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f','х':'h',
'ц':'c','ч':'ch','ш':'sh','щ':'sch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya'}
def tl(s): return ''.join(TR.get(c,c) for c in (s or '').lower())
P = json.load(open(str(P_.TREE_DATA/"persons.json"),encoding="utf-8"))
rel = {r["id"] for r in json.load(open(str(P_.SEARCH/"relatives.json"),encoding="utf-8"))}
persons=[]
for p in P:
    toks=[re.sub(r'[^a-z]','',tl(t)) for t in (p.get("name","")).split()]
    toks=[t for t in toks if len(t)>=3]
    persons.append((p["id"], p.get("name",""), toks, p["id"] in rel))

def match_handle(h):
    hl=re.sub(r'[^a-z]','',h.lower())
    best=None
    for pid,nm,toks,isrel in persons:
        if len(toks)<2: continue
        # все токены имени должны встречаться в логине (в любом порядке)
        if all(t in hl for t in toks):
            sc=sum(len(t) for t in toks)+(5 if isrel else 0)
            if best is None or sc>best[0]: best=(sc,pid,nm,isrel)
        # или фамилия+первая буква имени
    return best

rows=[]
for h,kinds in allh.items():
    disp = following.get(h) or followers.get(h) or ""
    m=match_handle(h)
    in_chat = any(h.lower() in s or s in h.lower() for s in chat_slugs)
    rows.append({"handle":h,"kinds":"+".join(sorted(kinds)),"chat":in_chat,
                 "match_id":m[1] if m else "","match_name":m[2] if m else "",
                 "is_relative":(m[3] if m else False)})

# CSV всех
with open(OUTCSV,"w",newline="",encoding="utf-8") as f:
    w=csv.DictWriter(f,fieldnames=["handle","kinds","chat","match_id","match_name","is_relative"])
    w.writeheader()
    for r in rows: w.writerow(r)

matched=[r for r in rows if r["match_id"]]
matched.sort(key=lambda r:(not r["is_relative"], not r["chat"]))

with open(OUTMD,"w",encoding="utf-8") as f:
    f.write("# Instagram-экспорт ↔ дерево\n\n")
    f.write(f"Аккаунтов в экспорте: подписок {len(following)}, подписчиков {len(followers)}, "
            f"переписок {len(chats)}.\n\n")
    f.write(f"## Сопоставлено с персонами дерева ({len(matched)})\n\n")
    f.write("| IG-аккаунт | связь | переписка | Персона в дереве | кровный |\n|---|---|---|---|---|\n")
    for r in matched:
        f.write(f"| [{r['handle']}](https://instagram.com/{r['handle']}) | {r['kinds']} | "
                f"{'💬' if r['chat'] else ''} | `{r['match_id']}` {r['match_name']} | "
                f"{'✅' if r['is_relative'] else '(супруг/иное)'} |\n")
    # --- близкие контакты (переписки): нестрогий матч + число фото ---
    def lenient(slug):
        sl=re.sub(r'[^a-z]','',slug.lower()); best=None
        for pid,nm,toks,isrel in persons:
            if len(toks)<2: continue
            if all(t in sl for t in toks):       # требуем имя+фамилию (надёжно)
                sc=sum(len(t) for t in toks)+(5 if isrel else 0)
                if best is None or sc>best[0]: best=(sc,pid,nm,isrel)
        return best
    f.write(f"\n## Близкие контакты (переписки) — высокая ценность ({len(chats)})\n\n")
    f.write("> В папках переписок есть присланные фото — возможны семейные снимки для книги.\n\n")
    f.write("| Контакт (slug) | фото в чате | Вероятная персона |\n|---|---|---|\n")
    for slug,d in sorted(chats):
        ph=os.path.join(inbox,d,"photos")
        nph=len([x for x in os.listdir(ph)]) if os.path.isdir(ph) else 0
        m=lenient(slug)
        guess=(f"`{m[1]}` {m[2]}"+(" ✅кровный" if m[3] else "")) if m else "—"
        f.write(f"| `{slug}` | {nph or ''} | {guess} |\n")

print(f"following={len(following)} followers={len(followers)} chats={len(chats)}")
print(f"сопоставлено с деревом: {len(matched)} (из них кровных: {sum(1 for r in matched if r['is_relative'])})")
print("Файлы: 1_sources/family/social/social_export/instagram_relatives.md, instagram_all_handles.csv")
