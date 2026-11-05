"""«Состояние дерева» и «Что нового» — data/progress.json.

Зачем. Правок стало много (до 38 коммитов в день), и по сайту не видно, где дерево растёт, а где стоит. Здесь две вещи:

  branches — по каждому роду из ftree.toml: сколько людей (по крови и по браку), на сколько поколений вглубь известны
             предки деда или бабушки, с которых род начинается, самый ранний предок, сколько рождений и смертей предков
             подтверждено документом (те же правила, что coverage.py), у скольких биография и фото, рост по дням;
  days     — лента: что поменялось в дереве за каждый день — новые люди, годы жизни, факты, биографии, фото, связи.

Ленту не пишем из текстов коммитов: там бывает то, что на сайт не выносим. Её считает сравнение снимков дерева — по
последнему коммиту каждого дня (git archive → cards.load), снимок только из того, что посетитель и так видит на сайте.
Снимки кэшируются в tools/.cache/progress/<коммит>.json; без git (или без истории) — лента пустая, цифры есть.
Последний день — нынешнее дерево (с несохранёнными правками), а не последний коммит.
"""
import datetime
import hashlib
import json
import re
import subprocess
import tarfile
import tempfile
from pathlib import Path

import cards
import coverage
import paths
from cards.notes import as_list

SNAP = 1                         # версия снимка: поменял поля — поднять, старый кэш не читается
CACHE = paths.CACHE / "progress"
UNKNOWN = re.compile(r"Unknown\b")
BIO = " — биография"
DAYS = 90                        # сколько последних дней в ленте


def _life(p):
    from .life import lifespan
    return lifespan(p.born, p.died)


def snapshot(tree, root):
    """{cr_id: что о человеке видно на сайте} — имя, годы, ветки, сколько фактов и фото, биография (отпечаток текста),
    родители, супруги. root — папка дерева (3_research/tree), биографии — root/biographies."""
    bios = {}
    for f in sorted((root / "biographies").glob(f"*{BIO}.md")):
        bios[f.name[:-len(BIO) - 3]] = hashlib.sha1(f.read_bytes()).hexdigest()[:10]
    return {p.id: {"name": p.name, "life": _life(p), "ln": [str(x) for x in as_list(p.fm.get("lineage"))],
                   "lm": [str(x) for x in as_list(p.fm.get("lineage_by_marriage"))], "facts": len(p.facts),
                   "pics": len(as_list(p.fm.get("media"))), "bio": bios.get(p.stem, ""),
                   "parents": p.father + p.mother, "spouses": list(p.spouses)}
            for p in tree.people.values()}


def _git(*args):
    return subprocess.run(["git", *args], cwd=paths.ROOT, capture_output=True, text=True, check=True).stdout


def _at(commit):
    """Снимок дерева на коммите — из кэша или git archive во временную папку. Нет дерева в коммите — None."""
    cached = CACHE / f"{commit}.json"
    if cached.exists():
        d = json.loads(cached.read_text(encoding="utf-8"))
        if d.get("v") == SNAP:
            return d["people"]
    rel = paths.TREE.relative_to(paths.ROOT).as_posix()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            raw = subprocess.run(["git", "archive", commit, rel], cwd=paths.ROOT, capture_output=True, check=True).stdout
        except subprocess.CalledProcessError:
            return None
        with tempfile.TemporaryFile() as f:
            f.write(raw)
            f.seek(0)
            with tarfile.open(fileobj=f) as tar:
                tar.extractall(tmp, filter="data")
        root = Path(tmp) / rel
        if not (root / "people").is_dir():
            return None
        people = snapshot(cards.load(root), root)
    CACHE.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps({"v": SNAP, "people": people}, ensure_ascii=False), encoding="utf-8")
    return people


def day_commits():
    """[(дата, последний коммит дня)] по главной линии истории, от старых к новым; первый — первый коммит с деревом."""
    try:
        rows = [ln.split("\t") for ln in _git("log", "--first-parent", "--format=%H\t%cs", "HEAD").splitlines()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    last = {}
    for h, d in rows:          # git log — от новых к старым: первый за день — последний
        last.setdefault(d, h)
    return sorted(last.items())


def changes(old, new):
    """Что поменялось между снимками: [{id, new?, life?, facts?, bio?, pics?, parents?, spouses?}], сколько убрано."""
    items = []
    for pid, b in new.items():
        if UNKNOWN.match(b["name"]):
            continue
        a = old.get(pid)
        if a is None:
            items.append({"id": pid, "new": True})
            continue
        x = {"id": pid}
        if a["life"] != b["life"]:
            x["life"] = [a["life"], b["life"]]
        if b["facts"] > a["facts"]:
            x["facts"] = b["facts"] - a["facts"]
        if b["bio"] != a["bio"] and b["bio"]:
            x["bio"] = "edit" if a["bio"] else "new"
        if b["pics"] > a["pics"]:
            x["pics"] = b["pics"] - a["pics"]
        if more := [i for i in b["parents"] if i not in a["parents"]]:
            x["parents"] = more
        if more := [i for i in b["spouses"] if i not in a["spouses"]]:
            x["spouses"] = more
        if len(x) > 1:
            items.append(x)
    return items, sum(1 for pid in old if pid not in new)


def _branch_count(snap, branch):
    return sum(1 for x in snap.values() if branch in x["ln"] and not UNKNOWN.match(x["name"]))


def days(now):
    """Лента по дням (новые сверху) и рост веток: {ветка: [{date, people}, …]}. now — снимок нынешнего дерева."""
    today = datetime.date.today().isoformat()
    snaps = []
    for d, h in day_commits():
        if d != today and (s := _at(h)) is not None:
            snaps.append((d, s))
    snaps.append((today, now))
    out = []
    for (_, a), (d, b) in zip(snaps, snaps[1:]):
        items, removed = changes(a, b)
        if items or removed:
            out.append({"date": d, "people": sum(1 for x in b.values() if not UNKNOWN.match(x["name"])),
                        "removed": removed, "items": items})
    growth = {name: [{"date": d, "people": _branch_count(s, name)} for d, s in snaps] for name in paths.LINES}
    return out[::-1][:DAYS], growth


def _ancestors(tree, root):
    """{cr_id: поколение над корнем}: 0 — сам дед или бабушка, 1 — его родители …"""
    return coverage.ancestors(tree, [tree.people[root]])


def _docs(tree, ids):
    """Рождения и смерти предков: всего, документом (📄 запись / 📃 документ), только со слов семьи, нигде."""
    n = {"events": 0, "record": 0, "family": 0, "none": 0}
    for pid in ids:
        p = tree.people[pid]
        cls = coverage.classify(tree, p)
        for ev in ("birth", "death"):
            if ev == "death" and coverage.alive(p):
                continue
            best, _ = coverage.summary(tree, cls.get(ev, []))
            n["events"] += 1
            n["record" if best in ("record", "doc") else "family" if best in ("family", "tree") else "none"] += 1
    return n


def branch(tree, name, root_stem, growth):
    root = next((p.id for p in tree.people.values() if p.stem == root_stem), None)
    people = [p for p in tree.people.values() if not UNKNOWN.match(p.name)]
    blood = [p for p in people if name in [str(x) for x in as_list(p.fm.get("lineage"))]]
    marriage = [p for p in people if name in [str(x) for x in as_list(p.fm.get("lineage_by_marriage"))]
                and p not in blood]
    anc = _ancestors(tree, root) if root else {}
    dated = [(tree.people[i].born.first_year, i) for i in anc if tree.people[i].born and tree.people[i].born.first_year]
    deepest = max(anc.values(), default=0)
    bios = {f.name[:-len(BIO) - 3] for f in paths.BIOS.glob(f"*{BIO}.md")}
    hist = growth.get(name, [])
    ago = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    week = next((h["people"] for h in reversed(hist) if h["date"] <= ago), None)
    return {"key": name, "root": root, "people": len(blood), "by_marriage": len(marriage),
            "generations": deepest, "ancestors": max(len(anc) - 1, 0),
            "deepest": [i for i, g in anc.items() if g == deepest and g > 0][:4],
            "oldest": ({"id": min(dated)[1], "year": min(dated)[0]} if dated else None),
            "docs": _docs(tree, list(anc)),
            "bios": sum(1 for p in blood if p.stem in bios),
            "pics": sum(1 for p in blood if as_list(p.fm.get("media"))),
            "week": (len(blood) - week) if week is not None else None,
            "growth": hist}


def build(tree):
    now = snapshot(tree, paths.TREE)
    feed, growth = days(now)
    people = [p for p in tree.people.values() if not UNKNOWN.match(p.name)]
    return {"schema": "progress/1",
            "total": {"people": len(people), "bios": sum(1 for x in now.values() if x["bio"] and not UNKNOWN.match(x["name"])),
                      "pics": sum(1 for p in people if as_list(p.fm.get("media"))),
                      "facts": sum(len(p.facts) for p in people)},
            "branches": [branch(tree, name, root, growth) for name, root in paths.LINES.items()],
            "days": feed}


if __name__ == "__main__":   # tools/py tools/scripts/site_data/progress.py — посчитать и показать коротко
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    r = build(cards.load())
    for b in r["branches"]:
        print(b["key"], b["people"], "+", b["by_marriage"], "поколений", b["generations"], "старший", b["oldest"], b["docs"], "неделя", b["week"])
    for d in r["days"][:5]:
        print(d["date"], d["people"], len(d["items"]), "убрано", d["removed"])
