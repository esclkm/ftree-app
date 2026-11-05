// Действия с заметками для компонентов: вызов по имени (notes.add(…), notes.close()), без dispatch в разметке.
// Функции стабильны между отрисовками — их можно отдавать прямо в onClick / onChange.
import {useMemo} from 'react'
import {useAppDispatch} from '../store'
import {type NewNote, notesActions, type Verdict} from './model'

export function useNotes() {
  const dispatch = useAppDispatch()
  return useMemo(() => ({
    toggle: () => { dispatch(notesActions.toggle()) },
    close: () => { dispatch(notesActions.toggle(false)) },
    add: (n: NewNote) => { dispatch(notesActions.add(n)) },
    comment: (key: string, comment: string) => { dispatch(notesActions.edit({key, comment})) },
    verdict: (key: string, verdict: Verdict | null) => { dispatch(notesActions.edit({key, verdict})) },
    remove: (key: string) => { dispatch(notesActions.remove(key)) },
    setGeneral: (text: string) => { dispatch(notesActions.setGeneral(text)) },
    clear: () => { dispatch(notesActions.clear()) },
    focused: () => { dispatch(notesActions.focused()) },
  }), [dispatch])
}
export type NotesApi = ReturnType<typeof useNotes>
