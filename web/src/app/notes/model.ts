// Заметки для Claude: Павел ходит по сайту и копит правки — к строке линии жизни, факту, фото, абзацу, выделенной
// цитате. Каждая заметка помнит, к кому она (номер человека, места, альбома) и откуда кусок (файл биографии, раздел),
// поэтому в выгрузке (toMarkdown) Claude найдёт исходник, на каком бы языке ни была открыта страница.
// Режим включён всегда (кнопка «Заметки» — на широком экране); ?notes=off выключает его в этом браузере, ?notes — возвращает.
// Родня кнопки не видит. Хранится в localStorage этого браузера — поэтому в панели есть «Скачать .md».
import {createSlice, type PayloadAction} from '@reduxjs/toolkit'
import type {Lang} from '../../data/schema.gen'
import {translate} from '../i18n'

/** К кому заметка: заметки группируются по нему. path — адрес страницы без языка (/people/<slug>) */
export interface Subject {
  type: 'person' | 'place' | 'source' | 'album'
  id: string
  name: string
  path: string
  file?: string  // биография (у человека) — путь в проекте
}
export type Kind = 'whole' | 'about' | 'lifeline' | 'fact' | 'stay' | 'state' | 'para' | 'quote' | 'photo'
/** Приговор фото (меню у «＋» на снимке и клавиши 1–6 в разборе) */
export type PhotoVerdict = 'remove' | 'better' | 'wrong_place' | 'wrong_person' | 'caption' | 'ok'
export const VERDICTS: PhotoVerdict[] = ['ok', 'remove', 'better', 'wrong_place', 'wrong_person', 'caption']
/** Что не так со строкой данных (меню у «＋» строки линии жизни, факта, «Мест и эпох» …) */
export type TextMark = 'wrong_date' | 'wrong_text' | 'need_source' | 'other_person' | 'add_event' | 'remove_line'
export type Verdict = PhotoVerdict | TextMark
const ROW: TextMark[] = ['wrong_date', 'wrong_text', 'need_source', 'remove_line']
export const MARKS: Partial<Record<Kind, TextMark[]>> = {
  lifeline: ['wrong_date', 'wrong_text', 'need_source', 'other_person', 'add_event', 'remove_line'],
  fact: ROW, about: ROW, stay: ['wrong_date', 'wrong_text', 'remove_line'], state: ['wrong_date', 'wrong_text', 'remove_line'],
}
/** Какие пометки бывают у заметки: у фото — приговоры, у строк — MARKS, у абзаца и цитаты — никаких */
export const marksOf = (n: Pick<Note, 'kind' | 'photo'>): Verdict[] => n.photo ? VERDICTS : MARKS[n.kind] ?? []

export interface NotePhoto {
  url: string
  thumb?: string
  caption?: string
  source?: string
  link?: string
  family?: boolean  // из media карточки (снимок семьи), а не найденный в сети
}

export interface Note {
  key: string
  subject: Subject
  kind: Kind
  where?: string  // «Линия жизни», «Биография › Детство» …
  text?: string   // сам кусок: строка, факт, абзац, цитата
  lang?: Lang     // на каком языке была страница — у переводов свой текст
  photo?: NotePhoto
  verdict?: Verdict
  comment: string
  at: number
}

export interface NotesState {
  enabled: boolean
  open: boolean
  general: string
  items: Note[]
  focus?: string  // только что добавленная — панель прокручивает к ней и ставит курсор
}

const STORE = 'notes', OFF = 'notes-off'

/** Режим включён? Да, пока в этом браузере не открыли адрес с ?notes=off; ?notes — снова включает */
export function notesEnabled(search = location.search, storage: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'> = localStorage): boolean {
  const q = new URLSearchParams(search).get('notes')
  if (q !== null) {
    if (q === 'off' || q === '0') storage.setItem(OFF, '1')
    else storage.removeItem(OFF)
  }
  return storage.getItem(OFF) !== '1'
}

function saved(): Pick<NotesState, 'general' | 'items' | 'open'> {
  try {
    const x = JSON.parse(localStorage.getItem(STORE) ?? '{}')
    return {general: typeof x.general === 'string' ? x.general : '', items: Array.isArray(x.items) ? x.items : [], open: !!x.open}
  } catch { return {general: '', items: [], open: false} }
}
export const persist = (s: NotesState): void =>
  localStorage.setItem(STORE, JSON.stringify({general: s.general, items: s.items, open: s.open}))

/** Одинаковый кусок дважды не добавляется — нажатие «＋» ещё раз просто ведёт к заметке */
export const noteKey = (n: Pick<Note, 'subject' | 'kind' | 'where' | 'text' | 'photo'>): string =>
  [n.subject.type, n.subject.id, n.kind, n.where ?? '', n.photo?.url ?? n.text ?? ''].join('|')

/** quiet — не открывать панель и не ставить курсор в заметку (разбор фото: там клавиши 1–6 — приговор, а не текст) */
export type NewNote = Omit<Note, 'key' | 'comment' | 'at'> & {comment?: string; quiet?: boolean}

export const notes = createSlice({
  name: 'notes',
  initialState: (): NotesState => {
    const enabled = typeof location !== 'undefined' && notesEnabled()
    return {enabled, ...(enabled ? saved() : {general: '', items: [], open: false})}
  },
  reducers: {
    toggle(s, a: PayloadAction<boolean | undefined>) { s.open = a.payload ?? !s.open },
    add(s, a: PayloadAction<NewNote>) {
      const {quiet, ...note} = a.payload
      const key = noteKey(note)
      const was = s.items.find(n => n.key === key)
      if (was) { if (note.verdict) was.verdict = note.verdict }
      else s.items.push({...note, key, comment: note.comment ?? '', at: Date.now()})
      if (quiet) return
      s.open = true
      s.focus = key
    },
    edit(s, a: PayloadAction<{key: string; comment?: string; verdict?: Verdict | null}>) {
      const n = s.items.find(x => x.key === a.payload.key)
      if (!n) return
      if (a.payload.comment !== undefined) n.comment = a.payload.comment
      if (a.payload.verdict !== undefined) n.verdict = a.payload.verdict ?? undefined
    },
    remove(s, a: PayloadAction<string>) { s.items = s.items.filter(n => n.key !== a.payload) },
    setGeneral(s, a: PayloadAction<string>) { s.general = a.payload },
    clear(s) { s.items = []; s.general = ''; s.focus = undefined },
    focused(s) { s.focus = undefined },
  },
})
export const notesActions = notes.actions

// ---------- выгрузка для Claude ----------

/** Подписи — из таблицы переводов (I18N_ROWS в site_export.py): вид куска nk_*, пометка nvl_*, к кому nt_* */
export const kindLabel = (k: Kind, lang: Lang): string => translate(lang, `nk_${k}`)
export const verdictText = (v: Verdict, lang: Lang): string => translate(lang, `nvl_${v}`)

/** Имя файла на сайте → исходное имя, насколько его можно восстановить: /media/l/c18f7d_Минск_вокзал.jpg → Минск_вокзал */
export const photoName = (url: string): string =>
  decodeURIComponent(url).replace(/^.*\/media\/(?:[ls]\/[0-9a-f]{6}_)?/, '').replace(/\.jpe?g$/i, '')

const quote = (s: string) => s.trim().split('\n').map(l => `   > ${l}`).join('\n')

function item(n: Note, i: number, lang: Lang): string {
  const t = (k: string, ...a: (string | number)[]) => translate(lang, k, ...a)
  const head = [`**${kindLabel(n.kind, lang)}**`]
  if (n.where) head.push(n.where)
  if (n.lang && n.lang !== lang) head.push(t('n_md_lang', n.lang.toUpperCase()))
  if (n.verdict) head.push(`**${verdictText(n.verdict, lang)}**`)
  const out = [`${i}. ${head.join(' · ')}`]
  if (n.photo) {
    const p = n.photo
    out.push(`   ${t('n_md_photo')}: \`${photoName(p.url)}\` (${t(p.family ? 'n_md_family' : 'n_md_found')})` +
      (p.source ? ` · ${t('n_md_from')}: ${p.source}` : '') + (p.link ? ` · ${p.link}` : ''))
    if (p.caption) out.push(quote(p.caption))
  }
  if (n.text) out.push(quote(n.text))
  if (n.comment.trim()) out.push(n.comment.trim().split('\n').map(l => `   ${l}`).join('\n'))
  return out.join('\n')
}

const LOCALE: Record<Lang, string> = {ru: 'ru-RU', pl: 'pl-PL', es: 'es-ES', en: 'en-GB'}

/** Все заметки → текст для Claude на языке страницы: по людям и местам, у каждого — номер и файлы, где искать */
export function toMarkdown(s: Pick<NotesState, 'general' | 'items'>, lang: Lang = 'ru', now = new Date()): string {
  const t = (k: string, ...a: (string | number)[]) => translate(lang, k, ...a)
  const out = [`# ${t('n_md_title', now.toLocaleDateString(LOCALE[lang]))}`, '', t('n_md_intro')]
  if (s.general.trim()) out.push('', `## ${t('n_general')}`, '', s.general.trim())
  const groups = new Map<string, Note[]>()
  for (const n of s.items) {
    const k = `${n.subject.type}:${n.subject.id}`
    groups.set(k, [...(groups.get(k) ?? []), n])
  }
  for (const list of groups.values()) {
    const sub = list[0].subject
    const ok = list.filter(n => n.verdict === 'ok' && !n.comment.trim())
    const rest = list.filter(n => !ok.includes(n))
    out.push('', `## ${sub.name} — ${t(`nt_${sub.type}`)}, \`${sub.id}\``, '')
    out.push(`${t('n_md_page')}: \`/${lang}${sub.path}\`` + (sub.file ? ` · ${t('n_md_bio')}: \`${sub.file}\`` : ''))
    if (rest.length) out.push('', rest.map((n, i) => item(n, i + 1, lang)).join('\n\n'))
    if (ok.length) out.push('', `${t('n_md_ok', ok.length)}: ` + ok.map(n => `\`${photoName(n.photo?.url ?? '')}\``).join(', '))
  }
  return out.join('\n') + '\n'
}
