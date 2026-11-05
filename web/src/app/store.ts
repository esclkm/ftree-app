// Хранилище приложения: данные (RTK Query), интерфейс (язык) и заметки автора (notes/model.ts). Язык и заметки
// запоминаются в браузере.
import {configureStore, createListenerMiddleware} from '@reduxjs/toolkit'
import {useDispatch, useSelector} from 'react-redux'
import {setLanguage} from '../i18n'
import {api} from './api'
import {notes, persist} from './notes/model'
import {setLang, ui} from './ui'

const remember = createListenerMiddleware()
remember.startListening({
  actionCreator: setLang,
  // нынешние дерево, карта и «кем приходится» (src/tree, src/map, src/kin) берут язык оттуда же
  effect: ({payload}) => { localStorage.setItem('lang', payload); setLanguage(payload) },
})
remember.startListening({
  predicate: a => a.type.startsWith(`${notes.name}/`),
  effect: (_, api) => { const s = (api.getState() as {notes: ReturnType<typeof notes.reducer>}).notes; if (s.enabled) persist(s) },
})

export function makeStore() {
  const store = configureStore({
    reducer: {[api.reducerPath]: api.reducer, ui: ui.reducer, notes: notes.reducer},
    middleware: m => m().prepend(remember.middleware).concat(api.middleware),
  })
  // язык из адреса (/pl/…) — начальное состояние, setLang не приходит: дереву и карте сказать сразу, иначе их
  // подсказки остаются на языке прошлого захода (05.10.2026)
  setLanguage(store.getState().ui.lang)
  return store
}
export type AppStore = ReturnType<typeof makeStore>
export type RootState = ReturnType<AppStore['getState']>
export const useAppSelector = useSelector.withTypes<RootState>()
export const useAppDispatch = useDispatch.withTypes<AppStore['dispatch']>()
