#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Восстановление старого фото: (1) обрезка/выпрямление, (2) царапины и заломы (--scratches),
(3) цветокоррекция, (4) ИИ-улучшение (CodeFormer/GFPGAN — лица + Real-ESRGAN — апскейл),
(5) раскраска отдельной копией (--colorize, photo_colorize.py: цвет от FLUX, яркость своя).
Царапины: детектор Microsoft BOPBTL даёт маску, LaMa закрашивает только её — вне маски пиксели не меняются.

Запуск (через ИИ-venv, см. tools/setup/photo.sh):
  $HOME/.relatives_ai_venv/bin/python tools/scripts/photo_restore.py --in IN.jpg --out OUT.jpg [опции]

Опции обрезки:
  --corners "x1,y1;x2,y2;x3,y3;x4,y4"  4 угла фото в исходнике (в любом порядке) -> выпрямить
  --auto                                попытаться найти углы автоматически (контур)
  (без обоих — без обрезки, весь кадр)
  --no-color   пропустить цветокоррекцию
  --no-ai      пропустить ИИ-этап (только обрезка+цвет)
  --models DIR каталог весов (по умолч. $REL_AI_MODELS или ~/.relatives_ai_models)
"""
import argparse, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402 — только stdlib
import numpy as np
import cv2

def order_pts(p):
    p=np.array(p,dtype="float32"); s=p.sum(1); d=np.diff(p,axis=1)
    return np.array([p[np.argmin(s)],p[np.argmin(d)],p[np.argmax(s)],p[np.argmax(d)]],dtype="float32")  # TL,TR,BR,BL

def auto_detect(img):
    H,W=img.shape[:2]; sc=900.0/H
    small=cv2.resize(img,(int(W*sc),900))
    g=cv2.GaussianBlur(cv2.cvtColor(small,cv2.COLOR_BGR2GRAY),(5,5),0)
    ed=cv2.dilate(cv2.Canny(g,40,140),np.ones((5,5),np.uint8),iterations=2)
    cnts,_=cv2.findContours(ed,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    A=small.shape[0]*small.shape[1]
    for c in sorted(cnts,key=cv2.contourArea,reverse=True)[:8]:
        ap=cv2.approxPolyDP(c,0.02*cv2.arcLength(c,True),True)
        if len(ap)==4 and 0.3*A<cv2.contourArea(c)<0.98*A:
            return ap.reshape(4,2)/sc
    return None

def warp(img,quad):
    r=order_pts(quad); tl,tr,br,bl=r
    w=int(max(np.linalg.norm(br-bl),np.linalg.norm(tr-tl)))
    h=int(max(np.linalg.norm(tr-br),np.linalg.norm(tl-bl)))
    M=cv2.getPerspectiveTransform(r,np.array([[0,0],[w-1,0],[w-1,h-1],[0,h-1]],dtype="float32"))
    return cv2.warpPerspective(img,M,(w,h),flags=cv2.INTER_CUBIC)

def color_correct(img):
    b,g,r=cv2.split(img.astype("float32"))
    mm=(b.mean()+g.mean()+r.mean())/3
    b*=mm/max(b.mean(),1); g*=mm/max(g.mean(),1); r*=mm/max(r.mean(),1)        # gray-world WB
    img=cv2.merge([np.clip(x,0,255) for x in (b,g,r)]).astype("uint8")
    out=[]
    for ch in cv2.split(img):                                                 # перцентильный стретч
        lo,hi=np.percentile(ch,0.5),np.percentile(ch,99.5)
        out.append(np.clip((ch.astype("float32")-lo)*255/max(hi-lo,1),0,255).astype("uint8"))
    img=cv2.merge(out)
    hsv=cv2.cvtColor(img,cv2.COLOR_BGR2HSV).astype("float32"); hsv[:,:,1]=np.clip(hsv[:,:,1]*1.3,0,255)
    return cv2.cvtColor(hsv.astype("uint8"),cv2.COLOR_HSV2BGR)

def detail_boost(img):
    """Локальный контраст (CLAHE) + мягкая детализация — текстура одежды/фона без ореолов."""
    lab=cv2.cvtColor(img,cv2.COLOR_BGR2LAB); l,a,b=cv2.split(lab)
    l=cv2.createCLAHE(clipLimit=1.8,tileGridSize=(8,8)).apply(l)
    img=cv2.cvtColor(cv2.merge([l,a,b]),cv2.COLOR_LAB2BGR)
    blur=cv2.GaussianBlur(img,(0,0),1.4)
    return cv2.addWeighted(img,1.5,blur,-0.5,0)

def detect_scratches(img, scale=(256, 512, 768), thr=0.2, grow=3):
    """Маска царапин, заломов и трещин — детектор из Microsoft «Bringing Old Photos Back to Life» (MIT).
    Сеть смотрит на серую копию, где короткая сторона = scale. Масштабов можно несколько — маски складываются:
    на 256 видны грубые заломы, на 768 — тонкие царапины, 1024 почти слепой. Порог 0.2: на 0.4 залом через лицо
    остаётся рваным (проба 23.11.2026, портрет 1910-х), на 0.1 маска уже заливает край плеча и завиток волос.
    Возвращает маску 0/255 размера исходника, расширенную на grow пикселей (чтобы закрыть края царапины)."""
    import torch, torch.nn.functional as F
    glob = paths.PHOTO_MODELS / "repos" / "BOPBTL" / "Global"
    ckpt = glob / "checkpoints" / "detection" / "FT_Epoch_latest.pt"
    if not ckpt.is_file(): sys.exit(f"нет весов детектора царапин {ckpt} — запусти tools/setup/photo.sh")
    sys.path.insert(0, str(glob))
    from detection_models import networks
    net = networks.UNet(in_channels=1, out_channels=1, depth=4, conv_num=2, wf=6, padding=True, batch_norm=True,
                        up_mode="upsample", with_tanh=False, sync_bn=True, antialiasing=True)
    net.load_state_dict(torch.load(str(ckpt), map_location="cpu")["model_state"]); net.eval()
    H, W = img.shape[:2]; gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    m = np.zeros((H, W), "uint8")
    for sc in ([scale] if isinstance(scale, int) else scale):
        k = sc / min(H, W)
        h, w = max(16, int(round(H*k/16))*16), max(16, int(round(W*k/16))*16)
        t = (torch.from_numpy(cv2.resize(gray, (w, h), interpolation=cv2.INTER_AREA)).float()/255.0 - 0.5)/0.5
        with torch.no_grad():
            p = torch.sigmoid(net(t[None, None]))[0, 0].numpy()
        m |= cv2.resize((p >= thr).astype("uint8")*255, (W, H), interpolation=cv2.INTER_NEAREST)
    if grow > 0:
        m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*grow+1, 2*grow+1)))
    return m

def _line_strength(img):
    """Насколько каждый пиксель похож на тонкую линию (светлую или тёмную) относительно соседей. Чернила (цветные) — 0."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY); sat = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[:, :, 1]
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
    r = cv2.morphologyEx(g, cv2.MORPH_TOPHAT, ker).astype(np.float32) + cv2.morphologyEx(g, cv2.MORPH_BLACKHAT, ker)
    r[sat > 70] = 0
    return r / (cv2.GaussianBlur(r, (0, 0), 40) + 3)   # на зашумлённом фоне линия должна выделяться сильнее

def _best_seam(rel, margin):
    """Самый «линейный» путь слева направо: в каждом столбце — одна строка, сдвиг вверх/вниз штрафуется.
    Считается на копии 1/8 по ширине и 1/2 по высоте — так путь жёсткий, как сгиб бумаги, а не петляет по шуму.
    Возвращает (сила пути в медианах, y для каждого x полного размера)."""
    H, W = rel.shape; kx, ky = 1/8, 1/2
    R = cv2.resize(rel, None, fx=kx, fy=ky, interpolation=cv2.INTER_AREA)
    med = float(np.median(R[R > 0])) if (R > 0).any() else 1.0
    x0, x1 = int(margin*kx), int((W-margin)*kx); R = R[:, x0:x1]; h, w = R.shape
    acc = R[:, 0].copy(); back = np.zeros((h, w), np.int8)
    for x in range(1, w):
        st = np.vstack([np.r_[-1e9, acc[:-1]]-med, acc, np.r_[acc[1:], -1e9]-med])
        i = st.argmax(0); back[:, x] = i-1; acc = st.max(0)+R[:, x]
    y = int(acc.argmax()); ys = [y]
    for x in range(w-1, 0, -1): ys.append(ys[-1]-back[ys[-1], x])
    ys = np.array(ys[::-1])/ky; xs = (np.arange(w)+x0+0.5)/kx
    return acc.max()/w/med, np.interp(np.arange(W), xs, ys)

def detect_folds(img, min_strength=1.42, core=4, reach=10):
    """Маска длинных заломов (сгибов бумаги) поперёк снимка — горизонтальных и вертикальных.
    Детектор BOPBTL видит короткие царапины, а сгиб — тонкий, рваный, то светлее, то темнее соседей — пропускает.
    Здесь ищется один самый «линейный» путь через весь снимок в каждом направлении; он считается заломом, только если
    его сила ≥ min_strength медиан. Путь ищется по карте, размытой ВДОЛЬ линии: иначе на лице он соскальзывал
    на контур подбородка (на 30–40 px ниже залома). Проба 23.11.2026, портрет 1910-х: залом 1,46, ложный
    вертикальный путь 1,38 — запас маленький, маску проверять глазами (--save-mask). На групповом снимке у хаты
    ложный путь по пиджакам дал 2,07 — порогом не отсечь; поэтому --folds не включён по умолчанию.
    Маска: сплошная полоса ±core пикселей вдоль пути + сильные «линейные» пиксели в ±reach (залом немного виляет)."""
    H, W = img.shape[:2]; m = np.zeros((H, W), np.uint8)
    for vertical in (False, True):
        src = img.transpose(1, 0, 2).copy() if vertical else img
        rel = _line_strength(src); h, w = rel.shape
        mg = int(.04*min(h, w)); rel[:mg] = 0; rel[-mg:] = 0; rel[:, :mg] = 0; rel[:, -mg:] = 0
        s, yy = _best_seam(cv2.GaussianBlur(rel, (0, 0), sigmaX=25, sigmaY=0.7), mg)
        print(f"залом {'вертикальный' if vertical else 'горизонтальный'}: сила {s:.2f} (порог {min_strength})"
              + ("" if s >= min_strength else " — не найден"))
        if s < min_strength: continue
        mm = np.zeros((h, w), np.uint8)
        for x in range(mg, w-mg):
            c = int(round(yy[x]))
            mm[max(0, c-core):c+core+1, x] = 255
            a, b = max(0, c-reach), min(h, c+reach+1)
            mm[a:b, x][rel[a:b, x] > 1.0] = 255
        mm = cv2.dilate(mm, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
        m |= mm.T if vertical else mm
    return m

def inpaint_lama(img, mask, models, tile=1024, pad=128):
    """Закрасить ТОЛЬКО пиксели маски моделью LaMa (Apache-2.0); всё вне маски остаётся исходным байт в байт.
    Большой снимок режется на куски tile×tile с запасом pad — LaMa лучше всего работает около 1000 пикселей."""
    import torch
    wp = os.path.join(models, "big-lama.pt")
    if not os.path.isfile(wp):
        print("ВНИМАНИЕ: нет big-lama.pt — закрашиваю простым cv2.inpaint (хуже на широких дефектах)")
        return cv2.inpaint(img, mask, 3, cv2.INPAINT_TELEA)
    lama = torch.jit.load(wp, map_location="cpu").eval()
    out = img.copy(); H, W = img.shape[:2]
    for y0 in range(0, H, tile):
        for x0 in range(0, W, tile):
            y1, x1 = min(H, y0+tile), min(W, x0+tile)
            if not mask[y0:y1, x0:x1].any(): continue
            Y0, X0, Y1, X1 = max(0, y0-pad), max(0, x0-pad), min(H, y1+pad), min(W, x1+pad)
            im, mk = img[Y0:Y1, X0:X1], mask[Y0:Y1, X0:X1]
            h, w = im.shape[:2]; ph, pw = (8-h % 8) % 8, (8-w % 8) % 8
            im_p = cv2.copyMakeBorder(im, 0, ph, 0, pw, cv2.BORDER_REFLECT)
            mk_p = cv2.copyMakeBorder(mk, 0, ph, 0, pw, cv2.BORDER_CONSTANT, value=0)
            ti = torch.from_numpy(cv2.cvtColor(im_p, cv2.COLOR_BGR2RGB)).permute(2, 0, 1)[None].float()/255
            tm = (torch.from_numpy(mk_p)[None, None].float() > 127).float()
            with torch.no_grad():
                r = lama(ti, tm)[0].permute(1, 2, 0).clamp(0, 1).numpy()
            r = cv2.cvtColor((r*255).round().astype("uint8"), cv2.COLOR_RGB2BGR)[:h, :w]
            sel = mk[y0-Y0:y1-Y0, x0-X0:x1-X0] > 127
            out[y0:y1, x0:x1][sel] = r[y0-Y0:y1-Y0, x0-X0:x1-X0][sel]
    return out

def keep_small_faces(pre, out, min_face=160):
    """Мелким лицам вернуть их до-ИИ вид (с мягким краем). Лицо в ~100 px модель не восстанавливает, а рисует заново:
    на снимке у хаты (23.11.2026) у пожилой женщины один глаз вышел закрытым, другой — выпученным, у всех — голубые глаза.
    Крупные лица (~260 px, пляжный портрет) модель трогает. Зовётся из папки весов (os.chdir в main)."""
    import torch
    from facexlib.detection import init_detection_model
    torch.backends.mps.is_available = lambda: False
    if out.shape[:2] != pre.shape[:2]:
        pre = cv2.resize(pre, (out.shape[1], out.shape[0]), interpolation=cv2.INTER_CUBIC)
    det = init_detection_model("retinaface_resnet50", half=False, device="cpu", model_rootpath="gfpgan/weights")
    with torch.no_grad():
        faces = det.detect_faces(pre, 0.5)
    m = np.zeros(out.shape[:2], np.float32); n = 0
    for f in faces:
        x1, y1, x2, y2 = map(int, f[:4]); w = x2 - x1
        if w >= min_face: continue
        p = int(w * .35); n += 1
        cv2.rectangle(m, (max(0, x1-p), max(0, y1-p)), (x2+p, y2+p), 1.0, -1)
    if n:
        m = cv2.GaussianBlur(m, (0, 0), 6)[..., None]
        out = (pre * m + out * (1 - m)).astype(np.uint8)
    print(f"мелкие лица (< {min_face} px) оставлены как были: {n} из {len(faces)}")
    return out

def ai_restore_gfpgan(img, models):
    from basicsr.archs.rrdbnet_arch import RRDBNet
    from realesrgan import RealESRGANer
    from gfpgan import GFPGANer
    bg=RealESRGANer(scale=2,model_path=os.path.join(models,"RealESRGAN_x2plus.pth"),
        model=RRDBNet(num_in_ch=3,num_out_ch=3,num_feat=64,num_block=23,num_grow_ch=32,scale=2),
        tile=400,tile_pad=10,pre_pad=0,half=False)
    rest=GFPGANer(model_path=os.path.join(models,"GFPGANv1.4.pth"),upscale=2,arch="clean",
        channel_multiplier=2,bg_upsampler=bg)
    _,_,out=rest.enhance(img,has_aligned=False,only_center_face=False,paste_back=True)
    return out

def ai_restore_codeformer(img, fidelity=0.7, upscale=2):
    import torch
    torch.backends.mps.is_available=lambda:False        # на Mac: всё на CPU (иначе MPS/CPU конфликт)
    import tempfile
    from codeformer.app import inference_app
    tmp=tempfile.mktemp(suffix=".png"); cv2.imwrite(tmp,img)
    res=inference_app(image=tmp,background_enhance=True,face_upsample=True,upscale=upscale,codeformer_fidelity=fidelity)
    out=cv2.imread(res) if isinstance(res,str) else None
    if out is None:
        import numpy as np
        arr=np.array(res); out=cv2.cvtColor(arr,cv2.COLOR_RGB2BGR) if arr.ndim==3 else arr
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--in",dest="inp",required=True); ap.add_argument("--out",required=True)
    ap.add_argument("--corners"); ap.add_argument("--auto",action="store_true")
    ap.add_argument("--no-color",action="store_true"); ap.add_argument("--no-ai",action="store_true")
    ap.add_argument("--engine",choices=["gfpgan","codeformer"],default="codeformer",
                    help="codeformer (естественнее на групповых/старых) или gfpgan")
    ap.add_argument("--fidelity",type=float,default=0.7,help="CodeFormer: 0..1 (выше=ближе к оригиналу). Мелкие лица (~100 px, групповой снимок) — 0.9–1.0: на 0.7 модель рисует свои глаза")
    ap.add_argument("--detail",action="store_true",help="пост: CLAHE+мягкая детализация (текстура одежды/фона)")
    ap.add_argument("--scratches",action="store_true",help="найти царапины/заломы и закрасить только их (BOPBTL + LaMa)")
    ap.add_argument("--scratch-scale",default="256,512,768",help="детектор: короткая сторона, px, через запятую — маски складываются (256 — грубые заломы, 768 — тонкие)")
    ap.add_argument("--scratch-thr",type=float,default=0.2,help="детектор: порог 0..1 (ниже — ловит больше заломов, но и лишнее)")
    ap.add_argument("--scratch-grow",type=int,default=3,help="расширить маску на N пикселей")
    ap.add_argument("--folds",action="store_true",help="ещё найти длинные заломы через весь снимок (сгибы бумаги) и закрасить их")
    ap.add_argument("--fold-strength",type=float,default=1.42,help="заломы: насколько путь должен выделяться (ниже — найдёт и слабые, и ложные)")
    ap.add_argument("--save-mask",action="store_true",help="сохранить маску царапин рядом: <out>_маска.png (проверить глазами)")
    ap.add_argument("--colorize",action="store_true",help="ещё и раскрасить — отдельным файлом <out>_раскраска.jpg (photo_colorize.py)")
    ap.add_argument("--color-engine",choices=["flux","ddcolor"],default="flux",help="flux — различает кожу/одежду (~7 мин); ddcolor — быстро, но на портретах сепия")
    ap.add_argument("--color-strength",type=float,help="насыщенность раскраски (по умолчанию: flux — 2.2, ddcolor — 1.0)")
    ap.add_argument("--color-hint",default="",help="раскраска flux: подсказка цветов по-английски (\"dark brown hair\")")
    ap.add_argument("--erase",help="убрать чужой цветной предмет (палец на ч/б карточке): \"x1,y1,x2,y2\" в координатах исходника, несколько — через ;")
    ap.add_argument("--erase-sat",type=int,default=45,help="erase: насыщенность, выше которой пиксель — предмет (ч/б карточка ≈ 0–30)")
    ap.add_argument("--bw",action="store_true",help="считать снимок ч/б (по умолчанию — сам, по насыщенности)")
    ap.add_argument("--color-photo",action="store_true",help="снимок цветной — не переводить в серый")
    ap.add_argument("--stains",action="store_true",help="убрать цветные пятна (ржавчина, подтёки) с ч/б карточки — по насыщенности")
    ap.add_argument("--stain-sat",type=int,default=60,help="stains: насыщенность пятна (ч/б карточка ≈ 0–30; пляж 1930-х: 60 → 2,6%% снимка)")
    ap.add_argument("--min-face",type=int,default=160,help="лица уже N px модель не трогает — оставляет как были (0 — трогать все)")
    ap.add_argument("--lift",help="проявить фигуру в тени: \"x1,y1,x2,y2\" (координаты исходника), несколько — через ;")
    ap.add_argument("--color-unify",default="",help="раскраска: рамки одного цвета (участки забора) \"x1,y1,x2,y2;…\" — в координатах результата")
    ap.add_argument("--color-recolor",default="",help="раскраска: синие пятна в рамке — цветом образца (см. photo_colorize.py --recolor)")
    ap.add_argument("--models",default=str(paths.PHOTO_MODELS))
    a=ap.parse_args()
    a.out=os.path.abspath(a.out)
    img=cv2.imread(a.inp,cv2.IMREAD_COLOR)
    if img is None: sys.exit("не открыть "+a.inp)
    if a.erase:  # до обрезки — координаты исходника; цветной чужой предмет (палец) на ч/б карточке ищется по насыщенности
        em=np.zeros(img.shape[:2],np.uint8); sat=cv2.cvtColor(img,cv2.COLOR_BGR2HSV)[:,:,1]
        for box in a.erase.split(";"):
            x1,y1,x2,y2=[int(float(v)) for v in box.split(",")]
            em[y1:y2,x1:x2][sat[y1:y2,x1:x2]>a.erase_sat]=255
        em=cv2.morphologyEx(em,cv2.MORPH_CLOSE,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(25,25)))
        em=cv2.dilate(em,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(31,31)))
        print(f"убрать предмет: {100*(em>0).mean():.1f}% снимка")
        if a.save_mask: cv2.imwrite(os.path.splitext(a.out)[0]+"_маска_предмет.png",em)
        img=inpaint_lama(img,em,a.models)
    if a.stains:  # рыжие/жёлтые пятна (ржавчина, подтёки) на ч/б карточке — цветные, ищутся по насыщенности; до обрезки
        sat=cv2.cvtColor(img,cv2.COLOR_BGR2HSV)[:,:,1]
        sm=((sat>a.stain_sat)*255).astype(np.uint8)
        sm=cv2.morphologyEx(sm,cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
        sm=cv2.dilate(sm,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(9,9)))
        print(f"цветные пятна: {100*(sm>0).mean():.1f}% снимка")
        if a.save_mask: cv2.imwrite(os.path.splitext(a.out)[0]+"_маска_пятна.png",sm)
        img=inpaint_lama(img,sm,a.models)
    if a.lift:  # проявить фигуру в тени (человек в тёмном проёме): местный контраст и подъём теней, только в рамке, с мягким краем.
        # Это тон, а не дорисовка: проявляется то, что уже есть на снимке. Черт, которых нет, не появится.
        for box in a.lift.split(";"):
            x1,y1,x2,y2=[int(float(v)) for v in box.split(",")]
            lab=cv2.cvtColor(img,cv2.COLOR_BGR2LAB); L=lab[:,:,0]
            reg=cv2.createCLAHE(clipLimit=3.0,tileGridSize=(4,4)).apply(L[y1:y2,x1:x2])
            reg=(255*((reg/255.0)**0.75)).astype(np.uint8)
            m=np.zeros(L.shape,np.float32); m[y1:y2,x1:x2]=1; m=cv2.GaussianBlur(m,(0,0),max(4,(x2-x1)/12))
            L2=L.copy(); L2[y1:y2,x1:x2]=reg
            lab[:,:,0]=(L2*m+L*(1-m)).astype(np.uint8); img=cv2.cvtColor(lab,cv2.COLOR_LAB2BGR)
        print("тени проявлены:",a.lift)
    if a.corners:
        q=[[float(v) for v in pair.split(",")] for pair in a.corners.split(";")]
        img=warp(img,q); print("обрезано по ручным углам")
    elif a.auto:
        q=auto_detect(img)
        if q is not None: img=warp(img,q); print("обрезано авто-детектом")
        else: print("ВНИМАНИЕ: авто-углы не найдены — обрезка пропущена (укажи --corners)")
    stem=os.path.splitext(a.out)[0]
    if a.scratches or a.folds:  # до цвета и ИИ: детектор учили на исходных, а лицевая модель «запомнила» бы царапину как черту лица
        m=np.zeros(img.shape[:2],np.uint8)
        if a.scratches: m|=detect_scratches(img,[int(v) for v in a.scratch_scale.split(",")],a.scratch_thr,a.scratch_grow)
        if a.folds: m|=detect_folds(img,a.fold_strength)
        share=100.0*(m>0).mean()
        if a.save_mask: cv2.imwrite(stem+"_маска.png",m); print("маска:",stem+"_маска.png")
        if share>15: print(f"ВНИМАНИЕ: маска закрывает {share:.0f}% снимка — детектор принял за дефект что-то лишнее; "
                           "подними --scratch-thr или посмотри --save-mask")
        img=inpaint_lama(img,m,a.models); print(f"царапины закрашены: {share:.1f}% пикселей, остальное не тронуто")
    # ч/б карточка (почти нет насыщенности): дальше работаем в сером. Иначе цветокоррекция даёт оттенок, а модель лиц
    # «дорисовывает» по нему цвет — на снимке у хаты 23.11.2026 у всех 10 человек вышли одинаковые голубые глаза.
    bw=a.bw or (not a.color_photo and np.median(cv2.cvtColor(img,cv2.COLOR_BGR2HSV)[:,:,1])<40)
    if not a.no_color: img=color_correct(img); print("цвет скорректирован")
    if bw: img=cv2.cvtColor(cv2.cvtColor(img,cv2.COLOR_BGR2GRAY),cv2.COLOR_GRAY2BGR); print("ч/б снимок: работаем в сером")
    if not a.no_ai:
        # библиотеки кладут и ищут веса в ./CodeFormer/weights и ./gfpgan/weights от текущей папки —
        # у нас они лежат в paths.AI_WEIGHTS (tools/ai_weights или FTREE_CACHE/ai_weights); выходной путь зафиксирован выше
        os.chdir(paths.AI_WEIGHTS)
        pre=img.copy()
        img=ai_restore_codeformer(img,a.fidelity) if a.engine=="codeformer" else ai_restore_gfpgan(img,a.models)
        print(f"ИИ-восстановление ({a.engine}) выполнено")
        if a.min_face>0: img=keep_small_faces(pre,img,a.min_face)
        if bw: img=cv2.cvtColor(cv2.cvtColor(img,cv2.COLOR_BGR2GRAY),cv2.COLOR_GRAY2BGR)  # цвет от модели лиц — выдумка
    if a.detail: img=detail_boost(img); print("детализация (CLAHE) применена")
    cv2.imwrite(a.out,img,[cv2.IMWRITE_JPEG_QUALITY,95])
    print("сохранено:",a.out,img.shape)
    if a.colorize:  # отдельный процесс: у DDColor свой basicsr, он подменил бы pip-овый (см. photo_colorize.py)
        import subprocess
        subprocess.run([sys.executable,os.path.join(os.path.dirname(os.path.abspath(__file__)),"photo_colorize.py"),
                        "--in",a.out,"--out",stem+"_раскраска.jpg","--engine",a.color_engine,
                        ]+(["--strength",str(a.color_strength)] if a.color_strength is not None else [])
                        +(["--hint",a.color_hint] if a.color_hint else [])+(["--unify",a.color_unify] if a.color_unify else [])+(["--recolor",a.color_recolor] if a.color_recolor else []))  # не удалась раскраска — реставрация уже сохранена

if __name__=="__main__": main()
