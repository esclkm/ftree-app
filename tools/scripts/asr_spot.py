#!/usr/bin/env python3
"""Точечная перепроверка спорных мест записи — широкими окнами, Whisper на двух языках, без подсказки.

Зачем. Узкое окно (15–20 сек) не только проясняет, но и выдумывает слова из обрезка. Поэтому окна —
40–60 сек, а подтверждением считается совпадение двух моделей, из которых одна шла без подсказки.

Запуск (из корня проекта):
    python3 tools/scripts/asr_spot.py --slug audio06 --langs ru,es  07:00-07:50 19:30-21:40 …
Окна — «мм:сс-мм:сс». Результат — 2_transcripts/audio/_raw_<slug>/spot/spot_<время>.json и печать на экран.
"""
import argparse, json, pathlib, subprocess, sys, time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import paths  # noqa: E402

BASE = paths.ASR_HOME
CODE = """
import json, mlx_whisper, soundfile as sf
x, sr = sf.read({wav!r}, dtype='float32'); out = {{}}
for name, a, b in {spots!r}:
    for lang in {langs!r}:
        r = mlx_whisper.transcribe(x[int(a*sr):int(b*sr)], path_or_hf_repo="mlx-community/whisper-large-v3-mlx",
                language=lang, condition_on_previous_text=False, temperature=(0.0, 0.2, 0.4))
        out[name + "|" + lang] = " ".join(s["text"].strip() for s in r["segments"])
        print("##", name, lang, "::", out[name + "|" + lang], flush=True)
json.dump(out, open({out!r}, "w"), ensure_ascii=False, indent=1)
"""


def sec(t):
    m, s = t.split(":"); return int(m) * 60 + int(s)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--slug", required=True); p.add_argument("--langs", default="ru,es")
    p.add_argument("windows", nargs="+")
    a = p.parse_args()
    d = paths.TRANSCRIPTS_AUDIO / f"_raw_{a.slug}"; (d / "spot").mkdir(exist_ok=True)
    spots = [(w, sec(w.split("-")[0]), sec(w.split("-")[1])) for w in a.windows]
    out = d / "spot" / f"spot_{time.strftime('%Y%m%d_%H%M%S')}.json"
    env = {"PATH": f"{BASE/'bin'}:/usr/bin:/bin"}
    subprocess.run([str(BASE / "whisperenv/bin/python"), "-c",
                    CODE.format(wav=str(d / "audio.wav"), spots=spots, langs=a.langs.split(","), out=str(out))],
                   check=True, env=env)
    print("сохранено:", out)


if __name__ == "__main__":
    main()
