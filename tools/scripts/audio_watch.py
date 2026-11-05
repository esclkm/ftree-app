#!/usr/bin/env python3
"""Слежение за папкой с аудио: скопировал запись — дальше всё само, без Claude.

Что делает. macOS (launchd, WatchPaths) запускает этот скрипт, как только в 1_sources/family/audio что-то поменялось.
Для каждой новой записи (.m4a, .wav, .mp3 …):
  1. ждёт, пока копирование закончится (размер перестал расти);
  2. распознаёт по ОРИГИНАЛУ — asr_pipeline.py all … --ctc (на сжатой копии тихий голос в телефоне модели слышат
     хуже, а дважды одно не распознаём); номер — следующий audioNN, черновик — 2_transcripts/audio/_raw_audioNN/;
  3. сжимает в Opus 24 кбит/с, моно (как копия в облаке) — «<имя>.opus» рядом; оригинал — в Корзину macOS
     (решение Павла 01.11.2026: оригинал звука не храним; из Корзины его ещё можно вернуть);
  4. вносит .opus в опись медиа и отправляет в шифрованное облако (media.py push);
  5. показывает уведомление. В сводке при старте сессии: «аудио распознано, ждёт разбора» — пока нет AudioNN_….md.
Не распозналось — оригинал не трогает, пишет в лог и в сводку.

Второй язык: имя файла подходит под file_words набора [asr.preset.<имя>] в ftree.toml — этот набор (второй язык и
имена собеседника); иначе обычный проход с --ctc.

Команды:
  audio_watch.py install    — поставить слежение (launchd); всё, что уже лежит в папке, — отмечено как разобранное
  audio_watch.py uninstall  — снять слежение
  audio_watch.py status     — что видит, что распознано, что ждёт
  audio_watch.py run        — один проход (так зовёт launchd; можно руками)
  audio_watch.py compress-old — то, что уже лежит в папке, — в .opus, оригинал в Корзину, ссылки в .md — на .opus
Лог — tools/.cache/audio_watch.log, состояние — tools/.cache/audio_watch.json (только на этом Mac).
"""
import datetime
import fcntl
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import media  # noqa: E402
import destinations  # noqa: E402
import paths  # noqa: E402

ROOT = paths.ROOT
AUDIO = paths.AUDIO
TRANSCRIPTS = paths.TRANSCRIPTS_AUDIO
EXT = {".m4a", ".wav", ".mp3", ".aac", ".ogg", ".flac", ".amr", ".caf", ".aiff"}  # .opus — уже сжатое, не трогаем
CACHE = paths.CACHE
STATE = CACHE / "audio_watch.json"
LOG = CACHE / "audio_watch.log"
LABEL = f"com.ftree.{destinations.tree_name()}.audio-watch"   # своё у каждого дерева: два дерева — два слежения
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def preset_for(name):
    """Набор распознавания по имени файла: первый [asr.preset.<имя>], чьё file_words подходит (без учёта регистра)."""
    for key, pr in dict(paths.tree_conf("asr.preset", {})).items():
        if pr.get("file_words") and re.search(pr["file_words"], name, re.I):
            return key
    return None


def log(msg):
    CACHE.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")


def load_state():
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"files": {}}


def save_state(st):
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STATE)


def notify(text):
    subprocess.run(["osascript", "-e", f'display notification {json.dumps(text)} with title "Родословная"'],
                   capture_output=True)


def recordings():
    return sorted(p for p in AUDIO.iterdir() if p.suffix.lower() in EXT and not p.name.startswith("."))


def settled(p, wait=5, rounds=3):
    """Копирование закончилось: размер не менялся три замера подряд."""
    last = -1
    same = 0
    while same < rounds:
        if not p.exists():
            return False
        size = p.stat().st_size
        same = same + 1 if size == last and size > 0 else 0
        last = size
        time.sleep(wait)
    return True


def next_slug(st):
    nums = [int(m[1]) for d in TRANSCRIPTS.iterdir() if (m := re.match(r"(?:_raw_audio|Audio)(\d+)", d.name))]
    nums += [int(f["slug"][5:]) for f in st["files"].values() if f.get("slug", "").startswith("audio")]
    return f"audio{max(nums, default=0) + 1:02d}"


def duration(p):
    out = subprocess.run([media.ffmpeg(), "-nostdin", "-i", str(p)], capture_output=True, text=True).stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0.0


def compress(src):
    """Opus рядом с оригиналом; длительность сверить — иначе оригинал не трогаем."""
    out = src.with_suffix(".opus")
    n = 2
    while out.exists():
        out = src.with_name(f"{src.stem}_{n}.opus")
        n += 1
    tmp = out.with_suffix(".part.opus")
    subprocess.run([media.ffmpeg(), "-nostdin", "-loglevel", "error", "-y", "-i", str(src), "-vn", *media.OPUS, str(tmp)],
                   check=True)
    a, b = duration(src), duration(tmp)
    if not b or abs(a - b) > 2:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"сжатая копия длиной {b:.0f} с, оригинал {a:.0f} с")
    tmp.replace(out)
    return out


def to_trash(p):
    trash = Path(os.environ.get("MEDIA_TRASH") or Path.home() / ".Trash")
    dest = trash / p.name
    n = 2
    while dest.exists():
        dest = trash / f"{p.stem} {n}{p.suffix}"
        n += 1
    try:
        shutil.move(str(p), dest)
    except PermissionError:  # фоновой задаче macOS может не дать Корзину напрямую — тогда через Finder
        subprocess.run(["osascript", "-e", f'tell application "Finder" to delete (POSIX file {json.dumps(str(p))})'],
                       check=True, capture_output=True)
        return trash / p.name
    return dest


def process(p, st):
    name = p.name
    slug = next_slug(st)
    st["files"][name] = {"status": "asr", "slug": slug, "at": datetime.datetime.now().isoformat(timespec="seconds")}
    save_state(st)
    log(f"{name}: распознаю как {slug}")
    notify(f"Новая запись «{name}» — распознаю ({slug}); это может занять час")
    cmd = ["nice", "-n", "10", str(paths.PY), str(paths.SCRIPTS / "asr_pipeline.py"), "all", str(p),
           "--slug", slug, *(["--preset", preset] if (preset := preset_for(name)) else ["--ctc"])]
    with LOG.open("a", encoding="utf-8") as f:
        code = subprocess.run(cmd, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT).returncode
    if code:
        st["files"][name]["status"] = "failed"
        save_state(st)
        log(f"{name}: распознавание упало (код {code}) — оригинал на месте")
        notify(f"«{name}» не распозналось — см. tools/.cache/audio_watch.log")
        return
    try:
        opus = compress(p)
    except Exception as e:  # сжатие не вышло — черновик есть, оригинал остаётся
        st["files"][name] |= {"status": "ready", "note": f"не сжато: {e}"}
        save_state(st)
        log(f"{name}: распознано, но не сжато ({e})")
        return
    trashed = to_trash(p)
    ctx = media.make_ctx(str(ROOT))
    rel = p.relative_to(ROOT).as_posix()
    with media.locked(ctx):  # оригинал мог попасть в опись коммитом, пока шло распознавание, — теперь его место у .opus
        rows = media.load(ctx)
        if rows.pop(rel, None) is not None:
            media.save(ctx, rows)
    subprocess.run([str(paths.PY), str(paths.SCRIPTS / "media.py"), "push"], cwd=ROOT,
                   stdout=LOG.open("a", encoding="utf-8"), stderr=subprocess.STDOUT)
    st["files"][name] |= {"status": "ready", "opus": opus.relative_to(ROOT).as_posix(), "trash": str(trashed)}
    st["files"][opus.name] = {"status": "seeded"}
    save_state(st)
    log(f"{name}: готово — черновик _raw_{slug}, звук {opus.name}, оригинал в Корзине")
    notify(f"«{name}» распознано ({slug}), сжато в {opus.name}. Разбор — навык audio-interview")


def cmd_run():
    CACHE.mkdir(parents=True, exist_ok=True)
    with open(CACHE / "audio_watch.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0  # уже идёт проход — он заберёт и новое (после каждой записи смотрит папку заново)
        while True:
            st = load_state()
            todo = [p for p in recordings() if p.name not in st["files"]]
            if not todo:
                return 0
            p = todo[0]
            if settled(p):
                process(p, st)


def cmd_compress_old():
    """Записи, которые уже лежат в папке (распознаны раньше), — в .opus, оригинал в Корзину (решение Павла 01.11.2026).
    Сжатая копия у отправленной записи уже есть в кэше media.py — та самая, что в облаке: берём её, ничего не грузим
    заново; опись указывает на тот же файл в облаке. Ссылки в .md (путь и [[имя]]) — на .opus."""
    ctx = media.make_ctx(str(ROOT))
    st = load_state()
    done = 0
    for p in recordings():
        rel = p.relative_to(ROOT).as_posix()
        with media.locked(ctx):
            rows = media.load(ctx)
        row = rows.get(rel, {})
        copy = row.get("copy") or {}
        cached = ctx.cache / "opus" / f"{row.get('sha256')}.opus"
        out = p.with_suffix(".opus")
        if out.exists():
            print(f"пропуск — уже есть {out.name}")
            continue
        if copy and cached.exists() and hashlib.sha256(cached.read_bytes()).hexdigest() == copy["sha256"]:
            shutil.copy2(cached, out)
        else:
            out = compress(p)
        a, b = duration(p), duration(out)
        if not b or abs(a - b) > 2:
            out.unlink()
            print(f"✋ {p.name}: сжатая копия {b:.0f} с, оригинал {a:.0f} с — оригинал не тронут")
            continue
        to_trash(p)
        new_rel = out.relative_to(ROOT).as_posix()
        with media.locked(ctx):
            rows = media.load(ctx)
            old = rows.pop(rel, None) or {}
            digest, size = media.sha256(ctx, new_rel)
            rows[new_rel] = media.new_row(new_rel, digest, size) | (
                {"added": old["added"]} if old.get("added") else {}) | (
                {"pushed": old["pushed"]} if old.get("pushed") and digest == copy.get("sha256") else {})
            touched = media.fix_links(ctx, rows | {rel: old}, rel, new_rel)
            media.save(ctx, rows)
        for f in media.md_files(ctx):  # имя файла в тексте: «(`Lipowa 8.m4a`, 26.09.2026)»
            t = f.read_text(encoding="utf-8")
            if f"`{p.name}`" in t:
                f.write_text(t.replace(f"`{p.name}`", f"`{out.name}`"), encoding="utf-8")
                touched.append(f.relative_to(ROOT).as_posix())
        st["files"][p.name] = st["files"].get(p.name, {}) | {"opus": new_rel}
        st["files"][out.name] = {"status": "seeded"}
        done += 1
        print(f"{p.name} → {out.name}: {a / 60:.0f} мин, {row.get('size', 0) / 1e6:.0f} → "
              f"{out.stat().st_size / 1e6:.1f} МБ; ссылки — {len(set(touched))} файлов")
    save_state(st)
    print(f"Сжато: {done}. Оригиналы — в Корзине macOS (место освободится, когда её очистить).")
    return 0


def cmd_install():
    st = load_state()
    seeded = [p.name for p in recordings() if p.name not in st["files"]]
    for name in seeded:
        st["files"][name] = {"status": "seeded"}
    save_state(st)
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    plist = {"Label": LABEL, "ProgramArguments": [str(paths.PY), str(Path(__file__).resolve()), "run"],
             "WatchPaths": [str(AUDIO)], "WorkingDirectory": str(ROOT),
             "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"},
             "StandardOutPath": str(LOG), "StandardErrorPath": str(LOG), "ProcessType": "Background"}
    with PLIST.open("wb") as f:
        plistlib.dump(plist, f)
    uid = str(os.getuid())
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"], capture_output=True)
    r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(PLIST)], capture_output=True, text=True)
    if r.returncode:
        print(f"launchctl не принял: {r.stderr.strip()}")
        return 1
    print(f"Слежение стоит: {AUDIO.relative_to(ROOT)} → распознать, сжать, в облако. "
          f"Уже лежащее отмечено разобранным: {len(seeded)}. Лог: {LOG.relative_to(ROOT)}")
    return 0


def cmd_uninstall():
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True)
    PLIST.unlink(missing_ok=True)
    print("Слежение снято.")
    return 0


def cmd_status():
    on = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"], capture_output=True).returncode == 0
    st = load_state()
    print(f"Слежение: {'стоит' if on else 'не стоит (audio_watch.py install)'}; папка {AUDIO.relative_to(ROOT)}")
    for name, f in st["files"].items():
        if f.get("status") != "seeded":
            print(f"  {f['status']:7} {f.get('slug', ''):8} {name}  {f.get('note', '')}")
    new = [p.name for p in recordings() if p.name not in st["files"]]
    if new:
        print(f"  ждут: {', '.join(new)}")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    fn = {"run": cmd_run, "compress-old": cmd_compress_old, "install": cmd_install, "uninstall": cmd_uninstall, "status": cmd_status}.get(cmd)
    if not fn:
        print(__doc__)
        sys.exit(2)
    sys.exit(fn())
