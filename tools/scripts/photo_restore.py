#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Восстановление старого фото: (1) обрезка/выпрямление, (2) цветокоррекция,
(3) ИИ-улучшение (GFPGAN — лица + Real-ESRGAN — апскейл).

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
    ap.add_argument("--fidelity",type=float,default=0.7,help="CodeFormer: 0..1 (выше=ближе к оригиналу)")
    ap.add_argument("--detail",action="store_true",help="пост: CLAHE+мягкая детализация (текстура одежды/фона)")
    ap.add_argument("--models",default=str(paths.PHOTO_MODELS))
    a=ap.parse_args()
    img=cv2.imread(a.inp,cv2.IMREAD_COLOR)
    if img is None: sys.exit("не открыть "+a.inp)
    if a.corners:
        q=[[float(v) for v in pair.split(",")] for pair in a.corners.split(";")]
        img=warp(img,q); print("обрезано по ручным углам")
    elif a.auto:
        q=auto_detect(img)
        if q is not None: img=warp(img,q); print("обрезано авто-детектом")
        else: print("ВНИМАНИЕ: авто-углы не найдены — обрезка пропущена (укажи --corners)")
    if not a.no_color: img=color_correct(img); print("цвет скорректирован")
    if not a.no_ai:
        # библиотеки кладут и ищут веса в ./CodeFormer/weights и ./gfpgan/weights от текущей папки —
        # у нас они лежат в paths.AI_WEIGHTS (tools/ai_weights или FTREE_CACHE/ai_weights); выходной путь фиксируем до смены папки
        a.out=os.path.abspath(a.out)
        os.chdir(paths.AI_WEIGHTS)
        img=ai_restore_codeformer(img,a.fidelity) if a.engine=="codeformer" else ai_restore_gfpgan(img,a.models)
        print(f"ИИ-восстановление ({a.engine}) выполнено")
    if a.detail: img=detail_boost(img); print("детализация (CLAHE) применена")
    cv2.imwrite(a.out,img,[cv2.IMWRITE_JPEG_QUALITY,95])
    print("сохранено:",a.out,img.shape)

if __name__=="__main__": main()
