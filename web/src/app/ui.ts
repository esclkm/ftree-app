// Состояние интерфейса, которое не приходит с данными: язык. Главный — в адресе (/es/…, LangRoot); для адреса без
// языка — из ?lang=es, потом из памяти браузера, иначе русский.
import {createSlice, type PayloadAction} from '@reduxjs/toolkit'
import type {Lang} from '../data/schema.gen'

export const LANGS: Lang[] = ['ru', 'pl', 'es', 'en']
const isLang = (x: unknown): x is Lang => LANGS.includes(x as Lang)

export function startLang(search = location.search, saved = localStorage.getItem('lang'), path = location.pathname): Lang {
  const first = path.split('/')[1]
  const q = new URLSearchParams(search).get('lang')
  return isLang(first) ? first : isLang(q) ? q : isLang(saved) ? saved : 'ru'
}

export const ui = createSlice({
  name: 'ui',
  initialState: () => ({lang: startLang()}),
  reducers: {setLang(s, a: PayloadAction<Lang>) { s.lang = a.payload }},
})
export const {setLang} = ui.actions
