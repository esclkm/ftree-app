#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Расшифровка семейных аудиозаписей в несколько независимых проходов.

Зачем несколько. Одна модель на часовой записи обязательно где-то ошибётся, а хуже
того — молча пропустит кусок. Whisper на первой записи проглотил 87 участков, местами
по 25 секунд. Поэтому вторая модель идёт СПЛОШНЫМ проходом по всей записи, не оглядываясь
на то, что нашла первая.

Проходы:
  1. Whisper large-v3   — знаки препинания, заглавные буквы, время каждого слова.
  2. GigaAM v2 RNNT     — обучена на русской речи, устроена иначе → ошибается в других местах.
  3. GigaAM v2 CTC      — тот же звук, другой способ собирать буквы в слова. Для плохой связи.
  4. Whisper на втором языке (--lang es) — когда в разговоре звучит другой язык.
     Русская модель испанскую речь «переводит» или теряет; испанский проход её слышит.
     + wav2vec2 на том же языке (шаг w2v) — другое устройство, чем у Whisper:
     собирает слова по звукам (CTC), без языковой «догадки» — ошибается в других местах.
  5. GigaAM v3 e2e     — третье поколение (2025), с пунктуацией; идёт по копии с выровненной
                          громкостью (audio_boost.wav). ⭐ Слышит тихого собеседника в телефоне
                          заметно лучше v2: на Аудио 07 разобрал ответы отца, которые v2 терял.
  6. Спасательный проход — Whisper без подсказки по выровненной копии, окнами 40–90 сек
                          вокруг каждой дыры основного прохода (шаг rescue).
  7. Голоса             — кто говорит, скользящим окном (Resemblyzer + KMeans).
  8. Сборка             — черновик: Whisper как основа, дыры закрываются GigaAM,
                          под репликами — G3 (GigaAM v3) и испанский вариант, если отличаются;
                          в дырах — ещё и спасательный Whisper.

Запуск:
    python3 tools/scripts/asr_pipeline.py all "1_sources/family/audio/Lipowa 3.opus" --slug audio02 --ctc
    python3 tools/scripts/asr_pipeline.py all "…/Lipowa 9.opus" --slug audio07 --preset <набор из ftree.toml>

Окружения ставятся один раз: ~/.local/share/relatives-asr (см. скилл audio-interview).
"""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402

BASE = paths.ASR_HOME  # окружения распознавания (tools/setup/asr.sh); другая папка — FTREE_ASR_HOME
WHISPER_PY = BASE / "whisperenv/bin/python"
GIGA_PY = BASE / "gigaenv/bin/python"
GIGA3_PY = BASE / "giga3env/bin/python"   # GigaAM v3 — отдельное окружение, чтобы не трогать рабочее v2
FFMPEG = BASE / "bin/ffmpeg"
SR = 16000

# Имена и места рода — подсказка моделям (иначе редкая деревня или фамилия превращается в обычное слово).
# Подсказка своя у каждого дерева: ftree.toml, [asr] prompt / prompt_es; нет — модели слушают без подсказки.
PROMPT = str(paths.tree_conf("asr.prompt", ""))
PROMPT_ES = str(paths.tree_conf("asr.prompt_es", ""))
# Готовые наборы для постоянных собеседников: второй язык и имена их ветки — [asr.preset.<имя>] в ftree.toml
# (lang2, prompt_extra; file_words — по имени файла набор включает audio_watch.py).
PRESETS = dict(paths.tree_conf("asr.preset", {}))


def run(py, code, **kw):
    """Выполнить код в нужном окружении."""
    return subprocess.run([str(py), "-c", code], check=True, **kw)


def workdir(slug):
    d = paths.TRANSCRIPTS_AUDIO / f"_raw_{slug}"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------- 0. подготовка
def cmd_prepare(a):
    d = workdir(a.slug)
    wav = d / "audio.wav"
    subprocess.run([str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y",
                    "-i", a.audio, "-ac", "1", "-ar", str(SR),
                    "-c:a", "pcm_s16le", str(wav)], check=True)
    # Копия с выровненной громкостью: тихий голос в телефоне поднимается, громкий — нет.
    # По ней идут GigaAM v3 и спасательный проход. В git не кладём (.gitignore), делается заново.
    subprocess.run([str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav),
                    "-af", "highpass=f=80,dynaudnorm=f=150:g=15:m=30",
                    "-c:a", "pcm_s16le", str(d / "audio_boost.wav")], check=True)
    run(WHISPER_PY, f"""
import soundfile as sf, numpy as np
info = sf.info({str(wav)!r}); dur = info.frames/info.samplerate
x,_ = sf.read({str(wav)!r}, dtype='float32')
rms = float(np.sqrt((x**2).mean())); peak = float(np.abs(x).max())
sil = 100*float((np.abs(x) < 0.002).mean())
print('длительность : %d мин %02d сек' % (dur//60, dur%60))
print('громкость    : RMS %.4f, пик %.3f' % (rms, peak))
print('тишина       : %.1f%%' % sil)
if rms < 0.02: print('⚠️  запись тихая — третий проход (--ctc) особенно полезен')
""")
    print("wav:", wav)


# ---------------------------------------------------------------- 1. Whisper
def cmd_whisper(a):
    d = workdir(a.slug); wav = d / "audio.wav"
    lang = a.lang or "ru"
    out = d / ("whisper.json" if lang == "ru" else f"whisper_{lang}.json")
    prompt = PROMPT if lang == "ru" else PROMPT_ES if lang == "es" else ""
    if a.prompt_extra:
        prompt += " " + a.prompt_extra
    os.environ["PATH"] = f"{BASE/'bin'}:{os.environ['PATH']}"
    run(WHISPER_PY, f"""
import json, time, mlx_whisper
t0 = time.time()
r = mlx_whisper.transcribe({str(wav)!r},
        path_or_hf_repo="mlx-community/whisper-large-v3-mlx",
        language={lang!r}, task="transcribe", word_timestamps=True,
        condition_on_previous_text=False,
        temperature=(0.0,0.2,0.4,0.6,0.8,1.0),
        initial_prompt={prompt!r}, verbose=False)
json.dump(r, open({str(out)!r}, "w"), ensure_ascii=False, indent=1)
print("Whisper: %d реплик за %d сек" % (len(r["segments"]), time.time()-t0))
""")


# ---------------------------------------------------------------- 2-3. GigaAM
GIGA_CODE = """
import json, time, sys
import numpy as np, soundfile as sf, torch, gigaam
SR, CHUNK, OVER = 16000, 22.0, 2.0
audio, _ = sf.read({wav!r}, dtype="float32")
m = gigaam.load_model({model!r}, device="cpu")
def asr(c):
    w = torch.from_numpy(c).to(m._device).to(m._dtype).unsqueeze(0)
    l = torch.full([1], w.shape[-1], device=m._device)
    with torch.inference_mode():
        e, el = m.forward(w, l)
        return m.decoding.decode(m.head, e, el)[0]
dur = len(audio)/SR; out = []; t0 = time.time(); t = 0.0
while t < dur:
    b = min(t+CHUNK, dur)
    out.append({{"start": round(t,2), "end": round(b,2),
                 "text": asr(audio[int(t*SR):int(b*SR)])}})
    if len(out) % 20 == 0:
        print("  %d/%d сек" % (b, dur), file=sys.stderr, flush=True)
    t += CHUNK - OVER
json.dump(out, open({out!r}, "w"), ensure_ascii=False, indent=1)
print("GigaAM {model}: %d кусков за %d сек" % (len(out), time.time()-t0))
"""


def cmd_gigaam(a):
    d = workdir(a.slug); wav = d / "audio.wav"
    model = "v2_ctc" if a.ctc else "v2_rnnt"
    out = d / ("gigaam_ctc.json" if a.ctc else "gigaam.json")
    run(GIGA_PY, GIGA_CODE.format(wav=str(wav), model=model, out=str(out)))


# ---------------------------------------------------------------- 3б. wav2vec2 (второй язык)
# Модель с Hugging Face лежит в старом формате (pytorch_model.bin), а transformers 5 при torch < 2.6
# его не открывает. Поэтому держим локальную копию в safetensors — она делается один раз:
#   Wav2Vec2ForCTC(cfg).load_state_dict(torch.load(bin, weights_only=False)); save_pretrained(dst)
# (подробно — скилл audio-interview). Обновлять torch ради этого нельзя: может сломаться GigaAM.
W2V_MODELS = {"es": str(BASE / "models/wav2vec2-xlsr-53-spanish")}
W2V_CODE = """
import json, time, sys
import numpy as np, soundfile as sf, torch
from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
SR, CHUNK, OVER = 16000, 22.0, 2.0
audio, _ = sf.read({wav!r}, dtype="float32")
proc = Wav2Vec2Processor.from_pretrained({model!r})
m = Wav2Vec2ForCTC.from_pretrained({model!r}).eval()
dev = "cpu"  # на MPS у wav2vec2 падает свёртка (Output channels > 65536)
m.to(dev)
dur = len(audio)/SR; out = []; t0 = time.time(); t = float({start})
while t < dur:
    b = min(t+CHUNK, dur)
    x = proc(audio[int(t*SR):int(b*SR)], sampling_rate=SR, return_tensors="pt").input_values.to(dev)
    with torch.inference_mode():
        ids = m(x).logits.argmax(-1)
    out.append({{"start": round(t,2), "end": round(b,2), "text": proc.batch_decode(ids.cpu())[0]}})
    if len(out) % 20 == 0:
        print("  %d/%d сек" % (b, dur), file=sys.stderr, flush=True)
    t += CHUNK - OVER
json.dump(out, open({out!r}, "w"), ensure_ascii=False, indent=1)
print("wav2vec2 {lang}: %d кусков за %d сек" % (len(out), time.time()-t0))
"""


def cmd_w2v(a):
    d = workdir(a.slug); wav = d / "audio.wav"
    lang = a.lang if a.lang != "ru" else (a.lang2 or "es")
    run(GIGA_PY, W2V_CODE.format(wav=str(wav), model=W2V_MODELS[lang], lang=lang,
                                 start=a.start, out=str(d / f"w2v_{lang}.json")))


# ---------------------------------------------------------------- 4. голоса
def cmd_diarize(a):
    d = workdir(a.slug); wav = d / "audio.wav"
    run(WHISPER_PY, f"""
import json, sys
import numpy as np, torch, soundfile as sf
from resemblyzer import VoiceEncoder
from resemblyzer.audio import wav_to_mel_spectrogram, normalize_volume
from resemblyzer.hparams import mel_window_step, partials_n_frames
from sklearn.cluster import KMeans
SR=16000; HOP_F=int(round(0.5*(1000/mel_window_step))); WIN=partials_n_frames
wav,_ = sf.read({str(wav)!r}, dtype="float32")
wav = normalize_volume(wav, -30, increase_only=True)
mel = wav_to_mel_spectrogram(wav)
starts = np.arange(0, len(mel)-WIN, HOP_F)
e = mel.mean(axis=1)
win_e = np.array([e[s:s+WIN].mean() for s in starts])
speech = win_e > np.percentile(win_e, 20)
enc = VoiceEncoder(); embs = np.zeros((len(starts),256), dtype=np.float32)
idx = np.where(speech)[0]
for i in range(0, len(idx), 256):
    ch = idx[i:i+256]
    batch = np.stack([mel[starts[j]:starts[j]+WIN] for j in ch])
    with torch.no_grad():
        embs[ch] = enc(torch.from_numpy(batch).to(enc.device)).cpu().numpy()
lab = np.full(len(starts), -1, int)
lab[idx] = KMeans(2, n_init=50, random_state=0).fit(embs[idx]).labels_
sm = lab.copy()
for i in range(len(lab)):
    w = lab[max(0,i-2):i+3]; w = w[w>=0]
    if len(w): sm[i] = np.bincount(w).argmax()
lab = sm
mid = (starts + WIN/2)/(1000/mel_window_step)
data = json.load(open({str(d/'whisper.json')!r}))
words = [w for s in data["segments"] for w in s.get("words",[])]
def who(t0,t1):
    m = (mid>=t0-0.3)&(mid<=t1+0.3)&(lab>=0)
    if not m.any(): m = (np.abs(mid-(t0+t1)/2)<2.0)&(lab>=0)
    return int(np.bincount(lab[m]).argmax()) if m.any() else None
prev=0
for w in words:
    s = who(w["start"], w["end"]); w["speaker"] = prev if s is None else s; prev = w["speaker"]
turns=[]
for w in words:
    if not turns or w["speaker"]!=turns[-1]["speaker"] or w["start"]-turns[-1]["end"]>1.5:
        turns.append({{"speaker":w["speaker"],"start":w["start"],"end":w["end"],"words":[w]}})
    else:
        turns[-1]["end"]=w["end"]; turns[-1]["words"].append(w)
for t in turns: t["text"] = "".join(x["word"] for x in t["words"]).strip()
json.dump(turns, open({str(d/'turns.json')!r}, "w"), ensure_ascii=False, indent=1)
c={{0:0.0,1:0.0}}
for t in turns: c[t["speaker"]] += t["end"]-t["start"]
print("голоса: реплик %d | S0 %.1f мин | S1 %.1f мин" % (len(turns), c[0]/60, c[1]/60))
""")


# ---------------------------------------------------------------- 5. сборка
def norm(t):
    t = t.lower().replace("ё", "е")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s-]", " ", t)).strip().split()


def mmss(s):
    return "%02d:%02d" % (int(s) // 60, int(s) % 60)


# ---------------------------------------------------------------- 5. GigaAM v3 по выровненной копии
GIGA3_CODE = """
import json, os, sys, time, tempfile, soundfile as sf, gigaam
x, sr = sf.read({wav!r}, dtype="float32")
m = gigaam.load_model({model!r})
CH, OV = 22.0, 2.0; t = 0.0; out = []; t0 = time.time(); dur = len(x)/sr
while t < dur:
    b = min(t+CH, dur); fn = tempfile.mktemp(suffix=".wav"); sf.write(fn, x[int(t*sr):int(b*sr)], sr)
    r = m.transcribe(fn); os.remove(fn)
    out.append({{"start": round(t,2), "end": round(b,2), "text": r if isinstance(r, str) else getattr(r, "text", str(r))}})
    if len(out) % 20 == 0:
        print("  %d/%d сек" % (b, dur), file=sys.stderr, flush=True)
    t += CH - OV
json.dump(out, open({out!r}, "w"), ensure_ascii=False, indent=1)
print("GigaAM {model}: %d кусков за %d сек" % (len(out), time.time()-t0))
"""


def cmd_giga3(a):
    d = workdir(a.slug)
    if not GIGA3_PY.exists():
        print("⚠️  нет окружения giga3env — GigaAM v3 пропущен (как поставить — скилл audio-interview)")
        return
    wav = d / "audio_boost.wav"
    if not wav.exists():
        wav = d / "audio.wav"
    env = dict(os.environ, PATH=f"{BASE/'bin'}:{os.environ.get('PATH', '')}")  # v3 читает звук через ffmpeg
    subprocess.run([str(GIGA3_PY), "-c", GIGA3_CODE.format(wav=str(wav), model="v3_e2e_rnnt",
                                                            out=str(d / "gigaam3.json"))],
                   check=True, env=env)


# ---------------------------------------------------------------- 6. спасательный проход Whisper
RESCUE_CODE = """
import json, mlx_whisper, soundfile as sf
x, sr = sf.read({wav!r}, dtype="float32"); out = []
for a, b in {wins!r}:
    r = mlx_whisper.transcribe(x[int(a*sr):int(b*sr)], path_or_hf_repo="mlx-community/whisper-large-v3-mlx",
            language="ru", condition_on_previous_text=False, temperature=(0.0, 0.2, 0.4))
    for s in r["segments"]:
        if s["text"].strip():
            out.append({{"start": round(a+s["start"],2), "end": round(a+s["end"],2), "text": s["text"].strip()}})
    print("  окно %d–%d сек" % (a, b), flush=True)
json.dump(out, open({out!r}, "w"), ensure_ascii=False, indent=1)
"""


def rescue_windows(W, dur, pad=15.0, maxlen=90.0):
    """Окна вокруг дыр Whisper: дыра + по 15 сек с краёв, соседние склеиваются, длинные режутся.
    Окно не короче 40 сек — узкое окно выдумывает слова (скилл audio-interview)."""
    gaps, prev = [], 0.0
    for w in W:
        if w["start"] - prev > 3.0:
            gaps.append((prev, w["start"]))
        prev = max(prev, w["end"])
    if dur - prev > 3.0:
        gaps.append((prev, dur))
    wins = []
    for g0, g1 in gaps:
        a, b = max(0.0, g0 - pad), min(dur, g1 + pad)
        if b - a < 40.0:
            c = (a + b) / 2; a, b = max(0.0, c - 20.0), min(dur, c + 20.0)
        if wins and a <= wins[-1][1] and b - wins[-1][0] <= maxlen:
            wins[-1] = (wins[-1][0], b)
        else:
            wins.append((a, b))
    out = []
    for a, b in wins:
        while b - a > maxlen:
            out.append((a, a + maxlen)); a += maxlen - 10.0
        out.append((a, b))
    return [(round(a, 1), round(b, 1)) for a, b in out]


def cmd_rescue(a):
    d = workdir(a.slug)
    W = json.load(open(d / "whisper.json"))["segments"]
    wav = d / "audio_boost.wav"
    if not wav.exists():
        wav = d / "audio.wav"
    dur = float(subprocess.run([str(WHISPER_PY), "-c", f"import soundfile as sf;i=sf.info({str(wav)!r});print(i.frames/i.samplerate)"],
                               capture_output=True, text=True, check=True).stdout)
    wins = rescue_windows(W, dur)
    print(f"спасательный проход: {len(wins)} окон, {sum(b-a for a, b in wins)/60:.1f} мин звука")
    run(WHISPER_PY, RESCUE_CODE.format(wav=str(wav), wins=wins, out=str(d / "rescue.json")))


def cmd_merge(a):
    import difflib
    d = workdir(a.slug)
    W = json.load(open(d / "whisper.json"))["segments"]
    G = json.load(open(d / "gigaam.json"))
    C = json.load(open(d / "gigaam_ctc.json")) if (d / "gigaam_ctc.json").exists() else None
    G3 = json.load(open(d / "gigaam3.json")) if (d / "gigaam3.json").exists() else None
    RS = json.load(open(d / "rescue.json")) if (d / "rescue.json").exists() else None
    turns = json.load(open(d / "turns.json")) if (d / "turns.json").exists() else None
    L2 = sorted(d.glob("whisper_*.json"))
    L2 = [(f.stem.split("_", 1)[1].upper(), json.load(open(f))["segments"]) for f in L2]
    V2 = [(f.stem.split("_", 1)[1].upper() + "-w2v", json.load(open(f)))
          for f in sorted(d.glob("w2v_*.json"))]

    def seg_at(t0, t1, segs):
        return " ".join(s["text"].strip() for s in segs
                        if min(s["end"], t1) - max(s["start"], t0) >= 0.5 * (s["end"] - s["start"])
                        and s["text"].strip())

    def giga_at(t0, t1, src):
        out = []
        for c in src:
            if c["end"] > t0 and c["start"] < t1 and c["text"].strip():
                if min(c["end"], t1) - max(c["start"], t0) >= 2.0:
                    out.append(c["text"].strip())
        return " / ".join(out)

    # дыры Whisper
    gaps, prev = [], 0.0
    for w in W:
        if w["start"] - prev > 3.0:
            gaps.append((prev, w["start"]))
        prev = max(prev, w["end"])
    gmap = {w["start"]: giga_at(w["start"], w["end"], G) for w in W}

    # Совпадение считаем по ВСЕМУ тексту, а не по репликам: у моделей разная нарезка,
    # и поштучное сравнение коротких реплик с 22-секундными кусками даёт бессмысленно
    # низкие числа.
    def agree(x, y):
        sm = difflib.SequenceMatcher(None, x, y, autojunk=False)
        return sum(b.size for b in sm.get_matching_blocks())

    aw = norm(" ".join(s["text"] for s in W))
    ag = norm(" ".join(c["text"] for c in G))
    same, total = agree(aw, ag), max(len(aw), len(ag))
    if C:
        ac = norm(" ".join(c["text"] for c in C))
        print("GigaAM ↔ CTC: %.1f%%" % (100 * agree(ag, ac) / max(len(ag), len(ac))))
    if G3:
        a3 = norm(" ".join(c["text"] for c in G3))
        print("Whisper ↔ GigaAM v3: %.1f%%" % (100 * agree(aw, a3) / max(len(aw), len(a3))))

    lines = []
    prev = 0.0
    for w in W:
        if w["start"] - prev > 3.0:
            g = giga_at(prev, w["start"], G)
            g3 = giga_at(prev, w["start"], G3) if G3 else ""
            rs = seg_at(prev, w["start"], RS) if RS else ""
            if g or g3 or rs:
                lines.append(f"\n>> ПРОПУСК WHISPER {mmss(prev)}-{mmss(w['start'])} | GigaAM слышит:\n>> {g}")
                if g3:
                    lines.append(f">> G3 (v3, выровн.): {g3}")
                if rs:
                    lines.append(f">> Whisper-спас (выровн.): {rs}")
                lines.append("")
        sp = ""
        if turns:
            cand = [t for t in turns if t["start"] <= w["start"] <= t["end"]]
            if cand:
                sp = f"S{cand[0]['speaker']} "
        lines.append(f"[{mmss(w['start'])}] {sp}{w['text'].strip()}")
        if C:
            c = giga_at(w["start"], w["end"], C)
            gg = gmap[w["start"]]
            if c and norm(c) != norm(w["text"]) and norm(c) != norm(gg):
                lines.append(f"      · CTC: {c}")
        if G3:
            x = giga_at(w["start"], w["end"], G3)
            if x and norm(x) != norm(w["text"]) and norm(x) != norm(gmap[w["start"]]):
                lines.append(f"      · G3: {x}")
        for tag, segs in L2:
            x = seg_at(w["start"], w["end"], segs)
            if x and norm(x) != norm(w["text"]):
                lines.append(f"      · {tag}: {x}")
        for tag, chunks in V2:
            x = giga_at(w["start"], w["end"], chunks)
            if x:
                lines.append(f"      · {tag}: {x}")
        prev = max(prev, w["end"])
    draft = d / "draft.txt"
    draft.write_text("\n".join(lines), encoding="utf-8")
    print(f"совпадение Whisper↔GigaAM: {100*same/max(total,1):.1f}%")
    print(f"дыр Whisper >3 сек: {len(gaps)}")
    print("черновик:", draft)


def cmd_all(a):
    cmd_prepare(a)
    lang2, a.lang = a.lang2, "ru"; cmd_whisper(a)
    a.ctc = False; cmd_gigaam(a)
    if a.want_ctc:
        a.ctc = True; cmd_gigaam(a)
    cmd_giga3(a)
    if lang2:
        a.lang = lang2; cmd_whisper(a)
        if lang2 in W2V_MODELS:
            cmd_w2v(a)
    cmd_rescue(a); cmd_diarize(a); cmd_merge(a)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("prepare", "whisper", "gigaam", "giga3", "rescue", "w2v", "diarize", "merge", "all"):
        s = sub.add_parser(name)
        s.add_argument("audio", nargs="?", default="")
        s.add_argument("--slug", required=True)
        s.add_argument("--ctc", action="store_true",
                       help="третий проход GigaAM CTC — для плохой связи")
        s.add_argument("--lang", default="ru", help="язык прохода whisper (ru, es, …)")
        s.add_argument("--lang2", default="", help="для all: ещё один проход Whisper на этом языке")
        s.add_argument("--start", type=float, default=0.0, help="w2v: с какой секунды (второй язык часто не с начала)")
        s.add_argument("--prompt-extra", default="", help="имена и места этой записи — в подсказку")
        s.add_argument("--preset", default="", choices=["", *PRESETS],
                       help="готовый набор собеседника из ftree.toml ([asr.preset.<имя>]): второй язык + имена")
    a = p.parse_args()
    if a.preset:
        pr = PRESETS[a.preset]
        a.lang2 = a.lang2 or pr["lang2"]
        a.prompt_extra = a.prompt_extra or pr["prompt_extra"]
        a.ctc = True
    a.want_ctc = a.ctc
    {"prepare": cmd_prepare, "whisper": cmd_whisper, "gigaam": cmd_gigaam, "giga3": cmd_giga3,
     "rescue": cmd_rescue, "w2v": cmd_w2v,
     "diarize": cmd_diarize, "merge": cmd_merge, "all": cmd_all}[a.cmd](a)


if __name__ == "__main__":
    main()
