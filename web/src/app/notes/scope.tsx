// К кому относится кусок страницы и когда показывать «＋». Страница человека, места, альбома оборачивает себя в
// <NoteScope subject=…>: кнопкам — через контекст, выделенному тексту (Quote.tsx) — через data-subject на обёртке.
// Раздел страницы помечается data-note-where="Биография" — из него и ближайшего заголовка складывается «где».
import {createContext, type ReactNode, useContext, useSyncExternalStore} from 'react'
import {useAppSelector} from '../store'
import type {Subject} from './model'

const Ctx = createContext<Subject | null>(null)
export const useSubject = (): Subject | null => useContext(Ctx)

export function NoteScope({subject, children}: {subject: Subject; children: ReactNode}) {
  return <Ctx.Provider value={subject}><div className="note-scope" data-subject={JSON.stringify(subject)}>{children}</div></Ctx.Provider>
}

/** Только компьютер: на узком экране панели нет (она заняла бы весь экран) */
const WIDE = '(min-width: 1024px)'
const wide = () => typeof matchMedia !== 'undefined' && matchMedia(WIDE).matches
function subscribe(cb: () => void) {
  if (typeof matchMedia === 'undefined') return () => {}
  const m = matchMedia(WIDE)
  m.addEventListener('change', cb)
  return () => m.removeEventListener('change', cb)
}
export const useDesktop = (): boolean => useSyncExternalStore(subscribe, wide, () => false)

/** Режим включён в этом браузере и экран широкий — видна кнопка «Заметки» */
export function useNotesAvailable(): boolean {
  const enabled = useAppSelector(s => s.notes.enabled)
  return useDesktop() && enabled
}
/** Панель открыта — видны «＋» у данных и «＋ цитата» у выделения */
export function useEditing(): boolean {
  const open = useAppSelector(s => s.notes.open)
  return useNotesAvailable() && open
}

/** «Где» для куска страницы: раздел (data-note-where) и ближайший заголовок перед куском внутри текста */
export function whereOf(el: Element | null): string | undefined {
  if (!el) return undefined
  const section = el.closest<HTMLElement>('[data-note-where]')
  const parts = section?.dataset.noteWhere ? [section.dataset.noteWhere] : []
  const prose = el.closest('.prose')
  if (prose) {
    let head: Element | undefined
    for (const h of prose.querySelectorAll('h1, h2, h3, h4, h5'))
      if (h.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING && !h.contains(el)) head = h
    const t = head?.textContent?.trim()
    if (t && !parts.includes(t)) parts.push(t)
  }
  return parts.join(' › ') || undefined
}

export function subjectOf(el: Element | null): Subject | null {
  const raw = el?.closest<HTMLElement>('.note-scope')?.dataset.subject
  if (!raw) return null
  try { return JSON.parse(raw) as Subject } catch { return null }
}
