"""Текст из карточки → текст для JSON: Markdown, а ссылки Obsidian — ссылки по номеру.

  «жил у [[Иван Jasieniew|сына Ивана]] в [[Брест]]» → «жил у [сына Сергея](person:tmt-…) в [Брест](place:ncx-…)»

Адрес страницы по номеру строит приложение — так в данных нет ни путей, ни HTML; у картинок и файлов — адрес на сайте.
Ссылка на другую заметку проекта (расшифровку, полный текст находки) — [подпись](doc:<номер>), если выгрузка её
публикует (note); иначе — словами. Контакты и номера домов вырезаются здесь же (site_data.privacy).
"""
import re

from cards.notes import N
from .privacy import no_contacts

WIKI = re.compile(r"!?\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]")
MEDIA = re.compile(r"\.(jpe?g|png|webp|pdf|m4a|mp3|opus)$", re.I)


class Text:
    def __init__(self, tree, privacy, media_url=lambda name: None, note=lambda target: None):
        self.privacy, self.media_url, self.note = privacy, media_url, note
        self.links = {}
        for kind, coll, names in (("source", tree.sources, lambda s: [s.stem, s.title]),
                                  ("place", tree.places, lambda p: [p.stem, p.name, *p.aliases]),
                                  ("person", tree.people, lambda p: [p.stem])):
            for x in coll.values():
                for n in names(x):
                    self.links.setdefault(n, (kind, x.id))

    def clean(self, s):
        """Строка, которую увидит посетитель: без контактов и номеров домов."""
        return self.privacy.text(no_contacts(N(str(s))))

    def __call__(self, s):
        """Текст с разметкой: ссылки Obsidian → [подпись](вид:номер), остальное — как есть."""
        def link(m):
            target = N(m[1].split("/")[-1].removesuffix(".md")).strip()
            label = (m[2] or target).strip()
            if MEDIA.search(target):  # картинка в тексте ![[x.jpg]] — картинкой, ссылка на файл — ссылкой; нет на сайте — подпись
                url = self.media_url(target)
                return (f"![{label}]({url})" if m[0].startswith("!") else f"[{label}]({url})") if url else label
            if label.startswith("@I"):  # «[[Имя|@I25@]]» — подпись — номер MyHeritage: показываем имя
                label = target
            hit = self.links.get(target) or self.note(m[1])
            return f"[{label}]({hit[0]}:{hit[1]})" if hit else label
        return self.clean(WIKI.sub(link, str(s)))
