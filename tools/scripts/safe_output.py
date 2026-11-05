"""Запись сгенерированных файлов без потери ручных правок.

Скрипт запоминает отпечаток (хэш) того, что сам записал, в `_generated/.hashes.json` рядом с файлом.
При следующей сборке:
  — файл не меняли руками (отпечаток совпал) или его ещё нет → перезаписываем как обычно;
  — файл правили руками → НЕ трогаем, новую версию кладём в `_generated/<имя>` и предупреждаем.
Так в 2026-09 автосборка книги вернула бы исправленную 17.09 ошибку — теперь не вернёт.

Использование:  with safe_open(path) as f: f.write(text)
"""
import hashlib
import io
import json
import os
import re

WARNINGS = []


def _h(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class safe_open(io.StringIO):
    def __init__(self, path, *a, **k):
        super().__init__()
        self.path = path

    def __exit__(self, *exc):
        text = self.getvalue()
        folder, name = os.path.split(self.path)
        gen = os.path.join(folder, "_generated")
        store = os.path.join(gen, ".hashes.json")
        hashes = json.load(open(store, encoding="utf-8")) if os.path.exists(store) else {}
        current = open(self.path, encoding="utf-8").read() if os.path.exists(self.path) else None
        if current is None or current == text or hashes.get(name) == _h(current):
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(text)
            hashes[name] = _h(text)
        else:
            os.makedirs(gen, exist_ok=True)
            # черновик лежит на папку глубже — относительные ссылки на картинки и файлы сдвигаем на ../
            deeper = re.sub(r'((?:src|href)="|\]\()(?!https?:|#|/|data:)([^")\s]+)', r"\1../\2", text)
            with open(os.path.join(gen, name), "w", encoding="utf-8") as f:
                f.write(deeper)
            WARNINGS.append(f"⚠️ {self.path} правили руками — не тронут; новая версия: _generated/{name}")
        os.makedirs(gen, exist_ok=True)
        with open(store, "w", encoding="utf-8") as f:
            json.dump(hashes, f, ensure_ascii=False, indent=1)
        return super().__exit__(*exc)
