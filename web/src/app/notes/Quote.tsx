// «＋ цитата»: выделил мышью кусок текста на странице человека или места — рядом кнопка, в заметку попадает ровно он.
// К кому и откуда — по обёртке страницы (NoteScope, data-subject) и разделу (data-note-where). Работает, пока
// открыта панель заметок; в самой панели не срабатывает.
import {type MouseEvent, useCallback, useEffect, useState} from 'react'
import {Icon} from '../../components/Icon'
import {useLang, useT} from '../i18n'
import type {Subject} from './model'
import {subjectOf, useEditing, whereOf} from './scope'
import {useNotes} from './useNotes'

interface Found { text: string; subject: Subject; where?: string; x: number; y: number }

function selected(): Found | null {
  const sel = getSelection()
  if (!sel || sel.isCollapsed || !sel.rangeCount) return null
  const text = sel.toString().replace(/\s+/g, ' ').trim()
  if (text.length < 2) return null
  const range = sel.getRangeAt(0)
  const node = range.commonAncestorContainer
  const el = node instanceof Element ? node : node.parentElement
  if (!el || el.closest('.notes-panel, input, textarea')) return null
  const subject = subjectOf(el)
  if (!subject) return null
  const r = range.getBoundingClientRect()
  return {text, subject, where: whereOf(el), x: r.right, y: r.bottom}
}

/** Щелчок по кнопке не должен снять выделение раньше, чем мы его прочтём */
const keepSelection = (e: MouseEvent) => e.preventDefault()
const inPanel = (e: Event) => e.target instanceof Element && !!e.target.closest('.notes-panel')

/** Выделенный текст, пока режим включён; прокрутка страницы и снятое выделение прячут кнопку */
function useSelection(on: boolean): [Found | null, () => void] {
  const [found, setFound] = useState<Found | null>(null)
  const drop = useCallback(() => setFound(null), [])
  useEffect(() => {
    if (!on) return
    const up = () => setTimeout(() => setFound(selected()), 0)  // выделение двойным щелчком обновляется после mouseup
    const change = () => { if (getSelection()?.isCollapsed) drop() }
    const scroll = (e: Event) => { if (!inPanel(e)) drop() }
    document.addEventListener('mouseup', up)
    document.addEventListener('keyup', up)
    document.addEventListener('selectionchange', change)
    addEventListener('scroll', scroll, true)
    return () => {
      document.removeEventListener('mouseup', up)
      document.removeEventListener('keyup', up)
      document.removeEventListener('selectionchange', change)
      removeEventListener('scroll', scroll, true)
    }
  }, [on, drop])
  return [on ? found : null, drop]
}

export function QuoteButton() {
  const on = useEditing(), lang = useLang(), notes = useNotes(), t = useT()
  const [found, drop] = useSelection(on)
  const add = useCallback(() => {
    if (!found) return
    notes.add({subject: found.subject, kind: 'quote', where: found.where, text: found.text, lang})
    getSelection()?.removeAllRanges()
    drop()
  }, [found, notes, lang, drop])
  if (!found) return null
  return <button type="button" className="quote-pin" style={{left: Math.min(found.x, innerWidth - 150), top: found.y + 6}}
    onMouseDown={keepSelection} onClick={add}><Icon name="quote" />{t('n_pin_quote')}</button>
}
