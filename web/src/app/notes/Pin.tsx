// «＋ в заметку» у куска данных — видны, только пока открыта панель заметок (scope.tsx, useEditing).
//  Pin      — строка линии жизни, факт, строка «Мест и эпох», шапка: текст передаётся готовым. У строк (MARKS) «＋»
//             открывает меню «что не так» — неверная дата, нужен источник …; у остального сразу кладёт заметку;
//  BlockPin — абзац или пункт биографии: текст и заголовок берутся со страницы в момент нажатия;
//  PhotoPin — снимок: меню «что с ним не так» (VERDICTS).
// Выбор в меню сразу становится заметкой, «＋» показывает значок выбранного. Меню — поверх страницы (portal):
// снимки лежат в рамках с overflow: hidden, внутри них оно обрезалось бы.
import {type MouseEvent, type RefObject, useCallback, useEffect, useMemo, useRef, useState} from 'react'
import {createPortal} from 'react-dom'
import {Icon} from '../../components/Icon'
import {useLang, useT} from '../i18n'
import {useAppSelector} from '../store'
import {type Kind, MARKS, type NewNote, noteKey, type NotePhoto, type Subject, type Verdict, VERDICTS} from './model'
import {useEditing, useSubject, whereOf} from './scope'
import {useNotes} from './useNotes'

/** Значки пунктов меню (значки Material — ICONS в site_export.py); подписи — nv_* в таблице переводов */
export const VERDICT_ICON: Record<Verdict, string> = {
  ok: 'check', remove: 'delete', better: 'renew', wrong_place: 'place_off', wrong_person: 'person_off', caption: 'facts',
  wrong_date: 'event', wrong_text: 'facts', need_source: 'source', other_person: 'person_off', add_event: 'add', remove_line: 'delete',
}

/** Без Markdown: [имя](person:…) → имя, без звёздочек — в заметке текст, как его видно на странице */
export const plainMd = (s = ''): string => s.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1').replace(/[*`]/g, '')

/** Нажатие на «＋» не должно открыть ссылку или окно фото, внутри которых кнопка лежит */
const stop = (e: MouseEvent) => { e.preventDefault(); e.stopPropagation() }

// ---------- меню у «＋» ----------

type At = {x: number; y: number} | null

/** Меню закрывается щелчком мимо него и прокруткой страницы (но не прокруткой списка заметок — он едет сам) */
function useCloseOnOutside(at: At, close: () => void, box: RefObject<HTMLElement | null>, pop: RefObject<HTMLElement | null>) {
  useEffect(() => {
    if (!at) return
    const outside = (e: Event) => { const t = e.target as Node; if (!box.current?.contains(t) && !pop.current?.contains(t)) close() }
    const scroll = (e: Event) => { if (!(e.target instanceof Element && e.target.closest('.notes-panel'))) close() }
    addEventListener('mousedown', outside)
    addEventListener('scroll', scroll, true)
    return () => { removeEventListener('mousedown', outside); removeEventListener('scroll', scroll, true) }
  }, [at, close, box, pop])
}

/** «＋» с меню пометок: note — заметка без пометки (к ней добавится выбранная), given — уже выбранная */
function MarkPin({note, marks, given, title, className = ''}: {note: NewNote; marks: Verdict[]; given?: Verdict; title: string; className?: string}) {
  const notes = useNotes()
  const [at, setAt] = useState<At>(null)  // где открыто меню (у кнопки) или null
  const box = useRef<HTMLSpanElement>(null), pop = useRef<HTMLSpanElement>(null)
  const close = useCallback(() => setAt(null), [])
  useCloseOnOutside(at, close, box, pop)
  const toggleMenu = useCallback((e: MouseEvent<HTMLButtonElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    const h = 40 * (marks.length + 1) + 12
    setAt(was => was ? null : {x: Math.min(r.left, innerWidth - 260), y: Math.min(r.bottom + 4, innerHeight - h)})
  }, [marks.length])
  const pick = useCallback((verdict?: Verdict) => { notes.add({...note, verdict}); setAt(null) }, [notes, note])
  return <span className={`ppin-wrap ${className}`} ref={box} onClick={stop}>
    <button type="button" className={`npin${given ? ' done v-' + given : ''}`} title={title} aria-label={title} onClick={toggleMenu}>
      <Icon name={given ? VERDICT_ICON[given] : 'add'} /></button>
    {at && createPortal(<span className="pmenu" role="menu" ref={pop} style={{left: at.x, top: at.y}}>
      {marks.map(v => <MenuItem key={v} v={v} on={given === v} pick={pick} />)}
      <MenuItem pick={pick} />
    </span>, document.body)}
  </span>
}

/** Пункт меню; без v — «Просто заметка» (без пометки) */
function MenuItem({v, on, pick}: {v?: Verdict; on?: boolean; pick: (v?: Verdict) => void}) {
  const t = useT()
  const click = useCallback(() => pick(v), [pick, v])
  return <button type="button" role="menuitem" className={v ? `v-${v}${on ? ' on' : ''}` : undefined} onClick={click}>
    <Icon name={v ? VERDICT_ICON[v] : 'note'} />{t(v ? `nv_${v}` : 'n_just_note')}</button>
}

/** Пометка, уже поставленная этому куску (по ключу заметки) */
const useGiven = (key: string | null): Verdict | undefined =>
  useAppSelector(st => key ? st.notes.items.find(n => n.key === key)?.verdict : undefined)

// ---------- «＋» у данных ----------

interface PinProps { kind: Kind; where?: string; text?: string; subject?: Subject; title?: string }

export function Pin({kind, where, text, subject, title: own}: PinProps) {
  const on = useEditing(), ctx = useSubject(), lang = useLang(), notes = useNotes(), t = useT()
  const title = own ?? t('n_pin')
  const s = subject ?? ctx
  const note = useMemo<NewNote | null>(() => s && {subject: s, kind, where, text: text && plainMd(text), lang}, [s, kind, where, text, lang])
  const given = useGiven(note && noteKey(note))
  const add = useCallback((e: MouseEvent) => { stop(e); if (note) notes.add(note) }, [notes, note])
  if (!on || !note) return null
  const marks = MARKS[kind]
  if (marks) return <MarkPin note={note} marks={marks} given={given} title={title} />
  return <button type="button" className="npin" title={title} aria-label={title} onClick={add}><Icon name="add" /></button>
}

/** Текст абзаца без самой кнопки «＋» */
function blockText(block: HTMLElement): string | undefined {
  const copy = block.cloneNode(true) as HTMLElement
  copy.querySelectorAll('.npin').forEach(b => b.remove())
  return copy.textContent?.trim()
}

/** «＋» на полях абзаца биографии или текста места: что за абзац и под каким заголовком — со страницы */
export function BlockPin() {
  const on = useEditing(), s = useSubject(), lang = useLang(), notes = useNotes(), t = useT()
  const me = useRef<HTMLButtonElement>(null)
  const click = useCallback((e: MouseEvent) => {
    stop(e)
    const block = me.current?.parentElement
    if (block && s) notes.add({subject: s, kind: 'para', where: whereOf(block), text: blockText(block), lang})
  }, [notes, s, lang])
  if (!on || !s) return null
  return <button type="button" ref={me} className="npin block" title={t('n_pin_para')} aria-label={t('n_pin_para')} onClick={click}>
    <Icon name="add" /></button>
}

export function PhotoPin({photo, where, subject}: {photo: NotePhoto; where?: string; subject?: Subject}) {
  const on = useEditing(), ctx = useSubject(), lang = useLang(), t = useT()
  const s = subject ?? ctx
  const note = useMemo<NewNote | null>(() => s && {subject: s, kind: 'photo', where, photo, lang}, [s, where, photo, lang])
  const given = useAppSelector(st => s ? st.notes.items.find(n => n.photo?.url === photo.url && n.subject.id === s.id)?.verdict : undefined)
  if (!on || !note) return null
  return <MarkPin note={note} marks={VERDICTS} given={given} title={t('n_pin_photo')} className="ppin" />
}
