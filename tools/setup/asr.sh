#!/bin/bash
# Окружения для распознавания звука — скрипт tools/scripts/asr_pipeline.py, скиллы audio-interview и audio-argentina.
# Можно запускать сколько угодно раз: готовое окружение не трогает. Пересоздать одно — удалить его папку и запустить.
#   bash tools/setup/asr.sh            окружения (~2,6 ГБ)
#   bash tools/setup/asr.sh --models   и сразу модели (~4 ГБ), иначе они скачаются при первом запуске asr_pipeline
#
# Куда что ложится (BASE = ~/.local/share/relatives-asr):
#   BASE/whisperenv   Whisper (mlx-whisper; Mac на Apple Silicon), resemblyzer + scikit-learn — кто говорит, ffmpeg
#   BASE/gigaenv      GigaAM v2 и wav2vec2 (испанский). torch 2.5.1 закреплён: новее — ломается GigaAM v2
#   BASE/giga3env     GigaAM v3 с GitHub — отдельно, чтобы не трогать v2
#   BASE/bin/ffmpeg   ссылка на ffmpeg из imageio-ffmpeg
#   BASE/models/wav2vec2-xlsr-53-spanish   испанская модель, переложенная в safetensors (transformers 5 при torch < 2.6
#                                           не открывает старый pytorch_model.bin)
#   ~/.cache/huggingface/hub   whisper-large-v3-mlx (~3 ГБ) и исходник испанской модели
#   ~/.cache/gigaam            GigaAM v2_rnnt, v2_ctc, v3_e2e_rnnt (~1,3 ГБ)
# Версии — те, что работали 02.10.2026. Нужен uv (brew bundle).
set -e
BASE="$HOME/.local/share/relatives-asr"
mkdir -p "$BASE/bin" "$BASE/models"

if [ ! -x "$BASE/whisperenv/bin/python" ]; then
  uv venv "$BASE/whisperenv" --python 3.12
  # setuptools строго < 81: в 81 нет pkg_resources, а его требует webrtcvad (тянет resemblyzer) — иначе падает шаг diarize
  uv pip install --python "$BASE/whisperenv/bin/python" mlx-whisper==0.4.3 imageio-ffmpeg soundfile "setuptools<81" \
    resemblyzer==0.1.4 scikit-learn
fi
if [ ! -x "$BASE/gigaenv/bin/python" ]; then
  uv venv "$BASE/gigaenv" --python 3.12
  uv pip install --python "$BASE/gigaenv/bin/python" gigaam==0.1.0 torch==2.5.1 torchaudio==2.5.1 soundfile "transformers>=5,<6"
fi
if [ ! -x "$BASE/giga3env/bin/python" ]; then
  uv venv "$BASE/giga3env" --python 3.12
  uv pip install --python "$BASE/giga3env/bin/python" "gigaam @ git+https://github.com/salute-developers/GigaAM.git" \
    soundfile torch torchaudio
fi

# ffmpeg: первый запуск свежего бинарника Gatekeeper может убить (код 137) — снимаем карантин заранее
FF=$("$BASE/whisperenv/bin/python" -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())")
xattr -d com.apple.quarantine "$FF" 2>/dev/null || true
chmod +x "$FF"; ln -sf "$FF" "$BASE/bin/ffmpeg"
"$BASE/bin/ffmpeg" -version >/dev/null 2>&1 || "$BASE/bin/ffmpeg" -version >/dev/null

ES="$BASE/models/wav2vec2-xlsr-53-spanish"
if [ ! -s "$ES/model.safetensors" ]; then
  echo "[*] испанская модель wav2vec2 → $ES"
  "$BASE/gigaenv/bin/python" - "$ES" <<'PYEOF'
import sys, torch
from huggingface_hub import snapshot_download
from transformers import Wav2Vec2Config, Wav2Vec2ForCTC, Wav2Vec2Processor
src = snapshot_download("jonatasgrosman/wav2vec2-large-xlsr-53-spanish", allow_patterns=["*.json", "pytorch_model.bin"])
m = Wav2Vec2ForCTC(Wav2Vec2Config.from_pretrained(src))
m.load_state_dict(torch.load(f"{src}/pytorch_model.bin", weights_only=False, map_location="cpu"))
m.save_pretrained(sys.argv[1]); Wav2Vec2Processor.from_pretrained(src).save_pretrained(sys.argv[1])
PYEOF
fi

if [ "$1" = "--models" ]; then
  echo "[*] модели Whisper и GigaAM (~4 ГБ)"
  "$BASE/whisperenv/bin/python" -c "from huggingface_hub import snapshot_download as d; d('mlx-community/whisper-large-v3-mlx')"
  "$BASE/gigaenv/bin/python" -c "import gigaam; [gigaam.load_model(m, device='cpu') for m in ('v2_rnnt', 'v2_ctc')]"
  "$BASE/giga3env/bin/python" -c "import gigaam; gigaam.load_model('v3_e2e_rnnt')"
fi
echo "[OK] окружения распознавания — $BASE"
