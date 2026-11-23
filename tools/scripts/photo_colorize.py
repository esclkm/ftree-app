#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Раскраска чёрно-белого фото без искажений формы.

Главный приём, общий для обоих движков: от модели берётся ТОЛЬКО цвет (каналы a/b в пространстве Lab),
а яркость L — все контуры, лица, складки, трещины — остаётся из исходника пиксель в пиксель.
Что бы модель ни дорисовала в чертах лица, на итоговом снимке этого не будет. Цвет — догадка модели.

Движки:
  flux    (по умолчанию) — FLUX.3 klein edit через mflux, локально на Mac (~7 мин на снимок, ~8 ГБ памяти).
          Различает кожу, губы, волосы, одежду. Сама модель слегка перерисовывает лицо — поэтому
          её картинка идёт только донором цвета, слегка размытого.
  ddcolor — DDColor (Apache-2.0), ~20 с. Проба 23.11.2026 на портрете 1910-х: залил всё одной охрой, как сепия.
          Годится для снимков с явными предметами (улица, природа); на студийном портрете — нет.

Отдельный процесс от photo_restore.py: у DDColor своя папка basicsr, она подменила бы pip-овый.
  $HOME/.relatives_ai_venv/bin/python tools/scripts/photo_colorize.py --in BW.jpg --out COLOR.jpg [--engine flux|ddcolor]
"""
import argparse, os, shutil, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402 — только stdlib
import cv2
import numpy as np

DDCOLOR = {"modelscope": "ddcolor_modelscope", "artistic": "ddcolor_artistic"}  # папки весов в PHOTO_MODELS
FLUX_MODEL = "mflux-community/flux-3-image-klein-mflux-q8"
FLUX_PROMPT = ("Colorize this old black-and-white photograph with realistic natural colors: natural skin tone, "
               "hair, clothing and background colors typical of the era. Keep the image exactly the same: "
               "same face, same details, same composition, no changes except adding color.")


def gray3(img):
    """Чистый серый: желтизна старой бумаги иначе собьёт модель."""
    return cv2.cvtColor(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)


def transfer_color(src, donor, blur=True):
    """Яркость — из src, цвет (a/b) — из donor (размер подгоняется). Размытие цвета прячет мелкие сдвиги донора."""
    H, W = src.shape[:2]
    donor = cv2.resize(donor, (W, H), interpolation=cv2.INTER_CUBIC)
    L = cv2.cvtColor(src, cv2.COLOR_BGR2LAB)[:, :, 0]
    ab = cv2.cvtColor(donor, cv2.COLOR_BGR2LAB)[:, :, 1:].astype("float32")
    if blur:
        ab = cv2.GaussianBlur(ab, (0, 0), max(1.0, W / 400))
    return cv2.cvtColor(np.dstack([L, np.clip(ab, 0, 255).astype("uint8")]), cv2.COLOR_LAB2BGR)


def donor_flux(img, steps=None, seed=7, prompt=FLUX_PROMPT):
    exe = shutil.which("mflux-generate-flux3-edit")
    if not exe:
        sys.exit("нет mflux-generate-flux3-edit — поставь mflux (uv tool install mflux) или возьми --engine ddcolor")
    tmp = tempfile.mkdtemp(prefix="colorize_")
    H, W = img.shape[:2]; src = os.path.join(tmp, "in.jpg"); dst = os.path.join(tmp, "out.png")
    # macOS обрывает долгую задачу на видеокарте («Impacting Interactivity»), особенно пока за Маком работают.
    # Цвет потом всё равно размывается, поэтому меньший размер почти не вредит: каждая попытка — легче предыдущей.
    tries = [(1024, []), (1024, ["--low-ram"]), (768, ["--low-ram"])]
    for attempt, (side, extra) in enumerate(tries, 1):
        k = min(1.0, side / max(H, W))
        cv2.imwrite(src, cv2.resize(gray3(img), (int(W*k)//16*16, int(H*k)//16*16), interpolation=cv2.INTER_AREA))
        cmd = [exe, "--model", FLUX_MODEL, "--image-paths", src, "--prompt", prompt, "--seed", str(seed),
               "--output", dst] + (["--steps", str(steps)] if steps else []) + extra
        if subprocess.run(cmd).returncode == 0 and os.path.isfile(dst): break
        print(f"FLUX не досчитал (попытка {attempt} из {len(tries)})" + (" — пробую легче" if attempt < len(tries) else ""))
    else:
        sys.exit("FLUX не досчитал ни разу: оставь Мак без дела на время раскраски или возьми --engine ddcolor")
    out = cv2.imread(dst)
    shutil.rmtree(tmp, ignore_errors=True)
    return out


def donor_ddcolor(img, model="modelscope", input_size=512):
    import torch
    repo = paths.PHOTO_MODELS / "repos" / "DDColor"
    if not repo.is_dir():
        sys.exit(f"нет кода DDColor в {repo} — запусти tools/setup/photo.sh")
    sys.path.insert(0, str(repo))
    from ddcolor import DDColor, ColorizationPipeline, build_ddcolor_model
    wdir = paths.PHOTO_MODELS / DDCOLOR[model]
    wfile = wdir / "pytorch_model.bin"
    if not wfile.is_file():
        sys.exit(f"нет весов DDColor в {wdir} — запусти tools/setup/photo.sh")
    m = build_ddcolor_model(DDColor, model_path=str(wfile), input_size=input_size, model_size="large",
                            device=torch.device("cpu"))
    return ColorizationPipeline(m, input_size=input_size, device=torch.device("cpu")).process(gray3(img))


def tame(col, strength=1.0, max_chroma=32.0):
    """Насыщенность ×strength, но без «кричащих» мест (проба 23.11.2026, пляж 1930-х):
    - тёмное (волосы, тени) почти без цвета: в почти чёрном лёгкий синий сдвиг после усиления давал синие волосы;
    - цвет не выше max_chroma: иначе кожа на усилении ×2,2 выходит «варёной», красно-оранжевой."""
    lab = cv2.cvtColor(col, cv2.COLOR_BGR2LAB).astype("float32")
    L = lab[:, :, 0] * 100 / 255; ab = (lab[:, :, 1:] - 128) * strength   # OpenCV хранит L в 0..255 — переводим в 0..100
    ab *= np.clip((L - 20) / 50, 0, 1)[..., None] ** 1.5          # L 20 и ниже — серый, от 70 — цвет полностью
    dark = L < 60                                                  # синевы в волосах и тенях на старом фото не бывает:
    ab[:, :, 1][dark] = np.maximum(ab[:, :, 1][dark], 0)          # синюю составляющую в тёмном — в ноль
    c = np.hypot(ab[:, :, 0], ab[:, :, 1])
    ab *= (np.minimum(c, max_chroma) / np.maximum(c, 1e-6))[..., None]
    lab[:, :, 1:] = 128 + ab
    return cv2.cvtColor(np.clip(lab, 0, 255).astype("uint8"), cv2.COLOR_LAB2BGR)


def colorize(inp, out, engine="flux", model="modelscope", strength=1.0, steps=None, seed=7, hint="", unify="", donor_path=None, recolor="", soften=""):
    img = cv2.imread(inp, cv2.IMREAD_COLOR)
    if img is None:
        sys.exit("не открыть " + inp)
    prompt = FLUX_PROMPT + (" Colors to use: " + hint.strip() + "." if hint else "")
    if donor_path:
        donor = cv2.imread(donor_path)
    else:
        donor = donor_flux(img, steps, seed, prompt) if engine == "flux" else donor_ddcolor(img, model)
        cv2.imwrite(os.path.splitext(out)[0] + "_донор.png", donor)   # сырой цвет модели — для перекраски без её повтора
    col = transfer_color(img, donor, blur=(engine == "flux"))
    col = tame(col, strength)
    if unify:  # все рамки (участки одного забора) — одним цветом: оттенок первой рамки; яркость не трогаем
        boxes = [[int(float(v)) for v in bx.split(",")] for bx in unify.split(";")]
        lab = cv2.cvtColor(col, cv2.COLOR_BGR2LAB); x1, y1, x2, y2 = boxes[0]
        ref = np.median(lab[y1:y2, x1:x2, 1:].reshape(-1, 2).astype(np.float32), 0).astype(np.uint8)
        for x1, y1, x2, y2 in boxes: lab[y1:y2, x1:x2, 1:] = ref
        col = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR); print("один цвет в рамках:", unify)
    for item in (recolor.split(";") if recolor else []):  # «синий кусок ноги»: синеватые пиксели рамки — цветом образца
        box, ref = item.split("@")
        whole = ref.endswith("!"); ref = ref.rstrip("!")   # «!» — перекрасить всё в рамке (налёт на подбородке), не только синее
        x1, y1, x2, y2 = [int(float(v)) for v in box.split(",")]; r1, r2, r3, r4 = [int(float(v)) for v in ref.split(",")]
        lab = cv2.cvtColor(col, cv2.COLOR_BGR2LAB).astype(np.float32)
        refab = np.median(lab[r2:r4, r1:r3, 1:].reshape(-1, 2), 0)
        # плавно: чем синее пиксель, тем больше берёт от образца; край рамки размыт — без «прямоугольной заплатки»
        box_m = np.zeros(lab.shape[:2], np.float32); box_m[y1:y2, x1:x2] = 1
        box_m = cv2.GaussianBlur(box_m, (0, 0), max(3, (x2 - x1) / 20))
        w = box_m if whole else np.clip((2 - (lab[:, :, 2] - 128)) / 4, 0, 1) * box_m  # b ≤ -2 — от образца, b ≥ 2 — свой
        w = cv2.GaussianBlur(w, (0, 0), 2)[..., None]
        lab[:, :, 1:] = lab[:, :, 1:] * (1 - w) + refab * w
        col = cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)
        print(f"синее в рамке {box} — цветом образца {ref}: {float((w > .5).mean() * 100):.2f}% снимка")
    for item in (soften.split(";") if soften else []):  # «обожжённое» лицо: цвет в рамке ×k, с мягким краем
        box, k = item.split("*"); k = float(k)
        x1, y1, x2, y2 = [int(float(v)) for v in box.split(",")]
        lab = cv2.cvtColor(col, cv2.COLOR_BGR2LAB).astype(np.float32)
        m = np.zeros(lab.shape[:2], np.float32); m[y1:y2, x1:x2] = 1
        m = cv2.GaussianBlur(m, (0, 0), max(3, (x2 - x1) / 8))[..., None]
        lab[:, :, 1:] = 128 + (lab[:, :, 1:] - 128) * (1 - m + m * k)
        col = cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR); print("цвет приглушён:", item)
    cv2.imwrite(out, col, [cv2.IMWRITE_JPEG_QUALITY, 95])
    print(f"раскрашено ({engine}):", out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--engine", choices=["flux", "ddcolor"], default="flux")
    ap.add_argument("--model", choices=sorted(DDCOLOR), default="modelscope", help="только для ddcolor")
    ap.add_argument("--strength", type=float, help="насыщенность: <1 приглушить, >1 усилить (по умолчанию flux — 2.2: цвет FLUX\n                    со старой бумаги бледный, 2.2 выбран 23.11.2026; ddcolor — 1.0)")
    ap.add_argument("--steps", type=int, help="flux: шагов (по умолчанию модели — 16)")
    ap.add_argument("--seed", type=int, default=7, help="flux: другой seed — другой вариант цветов")
    ap.add_argument("--hint", default="", help="flux: подсказка цветов по-английски, что известно из жизни: "
                    "\"dark brown hair, faded navy swimsuit\" — модель иначе гадает (на пляже 1930-х дала синие волосы)")
    ap.add_argument("--unify", default="", help="сделать рамку одного цвета (забор): \"x1,y1,x2,y2\", несколько — через ;")
    ap.add_argument("--donor", help="готовая картинка-донор цвета (пропустить FLUX — для перекраски без 7 минут)")
    ap.add_argument("--recolor", default="", help="синие пятна в рамке перекрасить цветом образца: \"x1,y1,x2,y2@rx1,ry1,rx2,ry2\" (образец — например, лицо того же человека)")
    ap.add_argument("--soften", default="", help="приглушить цвет в рамке: \"x1,y1,x2,y2*0.7\", несколько — через ;")
    a = ap.parse_args()
    st = a.strength if a.strength is not None else (2.2 if a.engine == "flux" else 1.0)
    colorize(a.inp, a.out, a.engine, a.model, st, a.steps, a.seed, a.hint, a.unify, a.donor, a.recolor, a.soften)


if __name__ == "__main__":
    main()
