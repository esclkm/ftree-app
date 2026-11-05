# Программы для приложения и дерева. Поставить: brew bundle (в папке приложения). Проверить: rodo setup --check
brew "git"
brew "gh"            # GitHub из командной строки (запросы на слияние)
brew "python@3.12"   # запасной Python; основной — .venv, его ставит uv
brew "uv"            # окружения Python: uv sync, tools/setup/*.sh
brew "node@24"       # сборка интерфейса сайта (web/: npm ci, npm run build); на этом Mac — через nvm, тоже 24
brew "gitleaks"       # пароли и ключи в коде приложения: rodo leaks, хуки клона ftree-app (scan_personal.py install)
brew "rclone"        # медиа в облако — rclone (media.py; хранилище — [storage.*] в ftree.toml дерева)
brew "ffmpeg"        # сжатие звука для облака (media.py); у распознавания — свой, в ~/.local/share/relatives-asr
brew "poppler"       # pdftotext: текст PDF для сайта (site_export.py)
brew "ollama"        # локальная модель для картинок qwen3-vl (gaso_find.py): ollama pull qwen3-vl:8b-instruct
cask "google-chrome" # свой Chrome с постоянным входом на сайты архивов (tools/scripts/browser_cdp.mjs)
cask "obsidian"      # читать дерево и схемы; для скриптов не нужен
