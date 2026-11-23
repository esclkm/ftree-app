#!/bin/bash
# Окружение для реставрации фото (GFPGAN, Real-ESRGAN, CodeFormer) — скрипт tools/scripts/photo_restore.py, скилл photo-restore.
# Можно запускать сколько угодно раз: что уже стоит, не трогает.
#
# Куда что ложится:
#   ~/.relatives_ai_venv        — Python 3.12 с torch 2.2.2 и библиотеками (~2 ГБ)
#   ~/.relatives_ai_models      — веса GFPGAN 1.4 и Real-ESRGAN x2 (~400 МБ), LaMa (~200 МБ), DDColor (2 модели),
#                                 код BOPBTL и DDColor в repos/ с детектором царапин
#   tools/ai_weights/           — веса CodeFormer и распознавания лиц (~800 МБ; вне git). Библиотеки ищут их от текущей
#                                 папки, photo_restore.py переходит сюда сам.
# Все веса — с выпусков на GitHub; размеры сверены с нашими 02.10.2026, байт в байт.
# Нужен uv (brew bundle). Версии закреплены: с новыми torch и numpy basicsr не работает.
set -e
VENV="$HOME/.relatives_ai_venv"
MODELS="$HOME/.relatives_ai_models"
# куда класть веса лиц — туда же, где их ищет photo_restore.py (paths.AI_WEIGHTS: дерево или FTREE_CACHE),
# а не рядом со скриптом: иначе запуск из папки приложения качал вторую копию (~800 МБ)
WEIGHTS="$(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import paths; print(paths.AI_WEIGHTS)' "$(cd "$(dirname "$0")/../scripts" && pwd)")"
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

# --- царапины (BOPBTL: детектор, MIT) + закраска (LaMa, Apache-2.0) + раскраска (DDColor, Apache-2.0) ---
REPOS="$MODELS/repos"
clone() {  # clone <папка> <адрес>: код моделей — вне git проекта
  [ -d "$REPOS/$1" ] && return 0
  mkdir -p "$REPOS"; echo "[*] клонирую $1"; git clone -q --depth 1 "$2" "$REPOS/$1"
}
clone BOPBTL  $GH/microsoft/Bringing-Old-Photos-Back-to-Life
clone DDColor $GH/piddnad/DDColor
SBN="$REPOS/BOPBTL/Global/detection_models/sync_batchnorm"
if [ ! -d "$SBN" ]; then
  git clone -q --depth 1 $GH/vacancy/Synchronized-BatchNorm-PyTorch "$REPOS/_sbn" \
    && cp -r "$REPOS/_sbn/sync_batchnorm" "$SBN" && rm -rf "$REPOS/_sbn"
fi
DETW="$REPOS/BOPBTL/Global/checkpoints/detection/FT_Epoch_latest.pt"
if [ ! -s "$DETW" ]; then  # в архиве ~2 ГБ все сети BOPBTL; берём только детектор царапин, архив удаляем
  get "$MODELS/bopbtl_global.zip" $GH/microsoft/Bringing-Old-Photos-Back-to-Life/releases/download/v1.0/global_checkpoints.zip
  unzip -q -o "$MODELS/bopbtl_global.zip" 'checkpoints/detection/*' -d "$REPOS/BOPBTL/Global" && rm -f "$MODELS/bopbtl_global.zip"
fi
get "$MODELS/big-lama.pt" $GH/enesmsahin/simple-lama-inpainting/releases/download/v0.1.0/big-lama.pt
"$PY" -c "import huggingface_hub" 2>/dev/null || uv pip install --python "$PY" "huggingface-hub<0.30"
for m in ddcolor_modelscope ddcolor_artistic; do
  [ -n "$(ls "$MODELS/$m" 2>/dev/null)" ] && continue
  echo "[*] качаю $m (Hugging Face)"
  "$PY" -c "from huggingface_hub import snapshot_download as d; d('piddnad/$m', local_dir='$MODELS/$m')"
done

echo "[OK] готово. venv=$VENV  models=$MODELS  weights=$WEIGHTS"
echo "Запуск: $PY tools/scripts/photo_restore.py --in IN.jpg --out OUT.jpg [--corners ... | --auto]"
