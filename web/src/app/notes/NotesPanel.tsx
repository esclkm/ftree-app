// Панель заметок справа (только компьютер): общее поле, заметки по людям и местам, у каждой — кусок, к которому она,
// и поле для своих слов. Сверху — «Скопировать для Claude», «Скачать .md», разбор фото, «Очистить».
// Кнопка «Заметки» в шапке — NotesButton; видна всегда на широком экране (скрыть в этом браузере — ?notes=off).
import {type ChangeEvent, useCallback, useEffect, useMemo, useRef, useState} from 'react'
import {Link} from 'react-router'
import {Icon} from '../../components/Icon'
import {useAppSelector} from '../store'
import {useLinks} from '../useIndex'
import {useLang, useT} from '../i18n'
import {kindLabel, marksOf, type Note, type NotesState, photoName, toMarkdown, type Verdict, verdictText} from './model'
import {VERDICT_ICON} from './Pin'
import {useNotesAvailable} from './scope'
import {useNotes} from './useNotes'

export function NotesButton() {
  const available = useNotesAvailable(), notes = useNotes()
  const open = useAppSelector(s => s.notes.open), count = useAppSelector(s => s.notes.items.length), t = useT()
  if (!available) return null
  return <button type="button" className={`notes-btn${open ? ' on' : ''}`} title={t('n_btn_title')}
    onClick={notes.toggle}><Icon name="note" />{t('n_btn')}{count > 0 && <b>{count}</b>}</button>
}

/** Высота поля — по тексту */
function fit(t: HTMLTextAreaElement | null): void {
  if (!t) return
  t.style.height = 'auto'
  t.style.height = `${t.scrollHeight + 2}px`
}

/** Поле, которое растёт по тексту: при вводе и когда появилось (у сохранённой заметки текст уже есть) */
function Grow({value, onChange, placeholder, autoFocus}: {value: string; onChange: (v: string) => void; placeholder?: string; autoFocus?: boolean}) {
  const me = useRef<HTMLTextAreaElement>(null)
  useEffect(() => fit(me.current), [])
  useEffect(() => { if (autoFocus) me.current?.focus() }, [autoFocus])
  const change = useCallback((e: ChangeEvent<HTMLTextAreaElement>) => { fit(e.target); onChange(e.target.value) }, [onChange])
  return <textarea ref={me} rows={2} value={value} placeholder={placeholder} onChange={change} />
}

/** Файл с заметками — на случай, если браузер почистят (положить в 1_sources/inbox/) */
function saveFile(text: string, name: string): void {
  const a = document.createElement('a')
  a.href = URL.createObjectURL(new Blob([text], {type: 'text/markdown;charset=utf-8'}))
  a.download = `${name}_${new Date().toISOString().slice(0, 10)}.md`
  a.click()
  URL.revokeObjectURL(a.href)
}

export function NotesPanel() {
  const available = useNotesAvailable(), notes = useNotes(), href = useLinks(), t = useT()
  const s = useAppSelector(st => st.notes)
  const list = useRef<HTMLDivElement>(null)
  const groups = useMemo(() => {
    const g = new Map<string, Note[]>()
    for (const n of s.items) { const k = `${n.subject.type}:${n.subject.id}`; g.set(k, [...(g.get(k) ?? []), n]) }
    return [...g.values()]
  }, [s.items])
  const on = available && s.open
  useEffect(() => {  // место под панель: страница сужается, а не прячется под неё
    document.body.classList.toggle('notes-open', on)
    return () => document.body.classList.remove('notes-open')
  }, [on])
  useEffect(() => {  // новая заметка — прокрутить к ней (курсор ставит Grow autoFocus)
    if (!s.focus) return
    list.current?.querySelector(`[data-key="${CSS.escape(s.focus)}"]`)?.scrollIntoView({block: 'nearest', behavior: 'smooth'})
  }, [s.focus])
  if (!on) return null
  const photos = s.items.filter(n => n.photo).length

  return <aside className="notes-panel" aria-label={t('n_btn_title')}>
    <header>
      <h2><Icon name="note" />{t('n_btn')} <span className="count">{s.items.length}</span></h2>
      <button type="button" className="icon-btn" title={t('n_close')} aria-label={t('n_close_short')} onClick={notes.close}><Icon name="close" /></button>
    </header>
    <Tools s={s} />
    <div className="notes-list" ref={list}>
      <label className="notes-general"><span>{t('n_general')}</span>
        <Grow value={s.general} onChange={notes.setGeneral} placeholder={t('n_general_ph')} /></label>
      {!s.items.length && <p className="note">{t('n_empty')}</p>}
      {photos > 0 && <p className="note">{t('n_photos', photos)}</p>}
      {groups.map(g => <section key={g[0].subject.type + g[0].subject.id} className="notes-group">
        <h3><Link to={href.at(g[0].subject.path)}>{g[0].subject.name}</Link></h3>
        {g.map(n => <NoteCard key={n.key} n={n} focus={s.focus === n.key} />)}
      </section>)}
    </div>
  </aside>
}

/** Кнопки над списком: скопировать, скачать, разбор фото, очистить */
function Tools({s}: {s: NotesState}) {
  const notes = useNotes(), href = useLinks(), t = useT(), lang = useLang()
  const [copied, setCopied] = useState(false)
  const empty = !s.items.length && !s.general.trim()
  const copy = useCallback(async () => {
    await navigator.clipboard.writeText(toMarkdown(s, lang))
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }, [s, lang])
  const download = useCallback(() => saveFile(toMarkdown(s, lang), t('n_file')), [s, lang, t])
  const clear = useCallback(() => { if (confirm(t('n_clear_confirm'))) notes.clear() }, [notes, t])
  return <div className="notes-tools">
    <button type="button" className="btn small tonal" onClick={copy} disabled={empty}>
      <Icon name={copied ? 'check' : 'copy'} />{t(copied ? 'n_copied' : 'n_copy')}</button>
    <button type="button" className="icon-btn" title={t('n_download')} aria-label={t('n_download_short')} onClick={download}><Icon name="download" /></button>
    <Link className="icon-btn" to={href.at('/review')} title={t('nr_title')} aria-label={t('nr_title')}><Icon name="review" /></Link>
    <button type="button" className="icon-btn" title={t('n_clear')} aria-label={t('n_clear')} disabled={empty} onClick={clear}><Icon name="delete" /></button>
  </div>
}

function NoteCard({n, focus}: {n: Note; focus: boolean}) {
  const notes = useNotes(), t = useT(), lang = useLang()
  useEffect(() => { if (focus) notes.focused() }, [focus, notes])
  const remove = useCallback(() => notes.remove(n.key), [notes, n.key])
  const comment = useCallback((v: string) => notes.comment(n.key, v), [notes, n.key])
  const marks = marksOf(n)
  const toggles = marks.length > 0 && <>
    <div className="verdicts">{marks.map(v => <VerdictToggle key={v} v={v} noteKey={n.key} on={n.verdict === v} />)}</div>
    {n.verdict && <div className="verdict-label">{t(`nv_${n.verdict}`)}</div>}
  </>
  return <article className="note-card" data-key={n.key}>
    <div className="note-head">
      <span className="chip">{kindLabel(n.kind, lang)}</span>
      {n.where && <span className="note-where">{n.where}</span>}
      <button type="button" className="icon-btn small" title={t('n_remove')} aria-label={t('n_remove')} onClick={remove}><Icon name="close" /></button>
    </div>
    {n.photo && <div className="note-photo">
      <img src={n.photo.thumb ?? n.photo.url} alt="" loading="lazy" />
      <div>
        <code>{photoName(n.photo.url)}</code>
        {toggles}
      </div>
    </div>}
    {n.text && <blockquote>{n.text}</blockquote>}
    {!n.photo && toggles && <div className="note-marks">{toggles}</div>}
    <Grow value={n.comment} onChange={comment} placeholder={t('n_comment_ph')} autoFocus={focus} />
  </article>
}

/** Значок пометки в панели (приговор фото, «неверная дата» …): нажал — выбран, ещё раз — снят */
function VerdictToggle({v, noteKey, on}: {v: Verdict; noteKey: string; on: boolean}) {
  const notes = useNotes(), lang = useLang()
  const click = useCallback(() => notes.verdict(noteKey, on ? null : v), [notes, noteKey, on, v])
  return <button type="button" title={verdictText(v, lang)} aria-label={verdictText(v, lang)} className={`v-${v}${on ? ' on' : ''}`} onClick={click}>
    <Icon name={VERDICT_ICON[v]} /></button>
}
