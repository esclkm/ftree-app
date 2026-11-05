// Текст из data/*.json → React. Разметка простая (site_data/text.py): [подпись](person:<id>) и такие же ссылки на места,
// источники и заметки (doc:<номер>), [подпись](https://…) — ссылка на другой сайт, **жирный**, *курсив*, `пометка`, адреса сайтов. HTML в данных нет, и здесь он не вставляется — только текст и ссылки.
import type {ReactNode} from 'react'
import {Link} from 'react-router'
import type {Lang} from '../data/schema.gen'
import {nameIn, titleIn, useLang} from './i18n'
import {links, type Lookup, useIndex} from './useIndex'

const TOKEN = /\[([^\]]+)\]\((person|place|source|doc|media):([^)\s]+)\)|\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)|\*\*(.+?)\*\*|\*(.+?)\*|(https?:\/\/[^\s)»,]+)|`([^`]+)`/g

export function target(kind: string, id: string, ix: Lookup | undefined, lang: Lang): string | undefined {
  const href = links(lang)
  if (kind === 'person') { const p = ix?.people.get(id); return p && href.person(p.slug) }
  if (kind === 'place') { const p = ix?.places.get(id); return p && href.place(p.slug) }
  if (kind === 'source') { const s = ix?.sources.get(id); return s && href.source(s.slug) }
  if (kind === 'doc') return /^[0-9a-f]{10}$/.test(id) ? href.doc(id) : undefined  // заметка: data/docs/<номер>.json
  return undefined  // файлы (media:) — страницы у них пока нет: только подпись
}

// сравнение подписи с именем: без скобок, двоеточий и хвоста « — биография…» (ссылка на файл биографии)
const bare = (s: string) => s.replace(/\s+—\s+биография.*$/, '').replace(/[():]/g, '').replace(/\s+/g, ' ').trim()

/** Подпись ссылки на языке страницы: если подпись — просто русское имя карточки ([[Вербичи]] без своей подписи),
 *  на другом языке показываем имя на этом языке (Werbicze, Kazimierz (Kazik) Jasieniew). Своя подпись остаётся как есть. */
export function shownLabel(kind: string, id: string, label: string, ix: Lookup | undefined, lang: Lang): string {
  if (lang === 'ru' || !ix) return label
  if (kind === 'source') { const s = ix.sources.get(id); return s && bare(label) === bare(s.title) ? titleIn(s, lang) : label }
  const names = kind === 'person' ? ix.people.get(id)?.names : kind === 'place' ? ix.places.get(id)?.names : undefined
  return names && bare(label) === bare(names.ru) ? nameIn(names, lang) : label
}

export function render(text: string, ix: Lookup | undefined, lang: Lang, key = 'm'): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0, n = 0
  for (const m of text.matchAll(TOKEN)) {
    if (m.index > last) out.push(text.slice(last, m.index))
    const k = `${key}.${n++}`
    if (m[1] !== undefined) {
      const to = target(m[2], m[3], ix, lang)
      const shown = shownLabel(m[2], m[3], m[1], ix, lang)
      out.push(to ? <Link key={k} to={to}>{shown}</Link> : shown)
    } else if (m[4] !== undefined) out.push(<a key={k} href={m[5]} target="_blank" rel="noreferrer noopener">{m[4]}</a>)
    else if (m[6] !== undefined) out.push(<b key={k}>{render(m[6], ix, lang, k)}</b>)
    else if (m[7] !== undefined) out.push(<i key={k}>{render(m[7], ix, lang, k)}</i>)
    else if (m[8] !== undefined) out.push(<a key={k} href={m[8]} target="_blank" rel="noreferrer noopener">{m[8]}</a>)
    else out.push(<code key={k}>{m[9]}</code>)
    last = m.index + m[0].length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

export function Md({text}: {text: string}) {
  const {ix} = useIndex(), lang = useLang()
  return <>{render(text, ix, lang)}</>
}
