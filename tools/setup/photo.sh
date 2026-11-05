#!/bin/bash
# Окружение для реставрации фото (GFPGAN, Real-ESRGAN, CodeFormer) — скрипт tools/scripts/photo_restore.py, скилл photo-restore.
# Можно запускать сколько угодно раз: что уже стоит, не трогает.
#
# Куда что ложится:
#   ~/.relatives_ai_venv        — Python 3.12 с torch 2.2.2 и библиотеками (~2 ГБ)
#   ~/.relatives_ai_models      — веса GFPGAN 1.4 и Real-ESRGAN x2 (~400 МБ)
#   tools/ai_weights/           — веса CodeFormer и распознавания лиц (~800 МБ; вне git). Библиотеки ищут их от текущей
#                                 папки, photo_restore.py переходит сюда сам.
# Все веса — с выпусков на GitHub; размеры сверены с нашими 02.10.2026, байт в байт.
# Нужен uv (brew bundle). Версии закреплены: с новыми torch и numpy basicsr не работает.
set -e
VENV="$HOME/.relatives_ai_venv"
MODELS="$HOME/.relatives_ai_models"
WEIGHTS="$(cd "$(dirname "$0")/../.." && pwd)/tools/ai_weights"
PY="$VENV/bin/python"

[ -x "$PY" ] || { echo "[*] создаю окружение $VENV"; uv venv "$VENV" --python 3.12; }

if ! "$PY" -c "import gfpgan, realesrgan, cv2, codeformer" 2>/dev/null; then
  echo "[*] ставлю torch/gfpgan/realesrgan/codeformer (большая загрузка ~2 ГБ)…"
  uv pip install --python "$PY" torch==2.2.2 torchvision==0.17.2
  uv pip install --python "$PY" "numpy<2" basicsr==1.4.2 facexlib==0.3.0 gfpgan==1.3.8 realesrgan==0.3.0 opencv-python codeformer-pip
  # шим: в torchvision>=0.17 удалён functional_tensor, который импортирует basicsr
  "$PY" - <<'PYEOF'
import os, torchvision
p=os.path.join(os.path.dirname(torchvision.__file__),'transforms','functional_tensor.py')
open(p,'w').write("from torchvision.transforms.functional import rgb_to_grayscale\n")
print("shim:",p)
PYEOF
fi

get() {  # get <куда> <адрес>: качает, только если файла нет
  [ -s "$1" ] && return 0
  mkdir -p "$(dirname "$1")"; echo "[*] качаю $(basename "$1")"
  curl -fsSL -o "$1.part" "$2" && mv "$1.part" "$1"
}
GH=https://github.com
get "$MODELS/GFPGANv1.4.pth"        $GH/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.4.pth
get "$MODELS/RealESRGAN_x2plus.pth" $GH/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth
DET=$GH/xinntao/facexlib/releases/download/v0.1.0/detection_Resnet50_Final.pth
PARSE=$GH/xinntao/facexlib/releases/download/v0.2.2/parsing_parsenet.pth
get "$WEIGHTS/gfpgan/weights/detection_Resnet50_Final.pth"             $DET
get "$WEIGHTS/gfpgan/weights/parsing_parsenet.pth"                     $PARSE
get "$WEIGHTS/CodeFormer/weights/facelib/detection_Resnet50_Final.pth" $DET
get "$WEIGHTS/CodeFormer/weights/facelib/parsing_parsenet.pth"         $PARSE
get "$WEIGHTS/CodeFormer/weights/CodeFormer/codeformer.pth"            $GH/sczhou/CodeFormer/releases/download/v0.1.0/codeformer.pth
get "$WEIGHTS/CodeFormer/weights/realesrgan/RealESRGAN_x2plus.pth"     $GH/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth

echo "[OK] готово. venv=$VENV  models=$MODELS  weights=$WEIGHTS"
echo "Запуск: $PY tools/scripts/photo_restore.py --in IN.jpg --out OUT.jpg [--corners ... | --auto]"
