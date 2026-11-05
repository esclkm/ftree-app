// Язык — первая часть адреса: /ru/…, /es/…. Он же — язык интерфейса (хранилище ui.lang следует за адресом).
// Адрес без языка — старые ссылки (…/people/x.html, tree.html#…, ?lang=es) — перенаправляем на тот же адрес с языком.
import {useEffect} from 'react'
import {Navigate, useLocation, useParams} from 'react-router'
import type {Lang} from '../data/schema.gen'
import {Layout} from './Layout'
import {useAppDispatch, useAppSelector} from './store'
import {LANGS, setLang, startLang} from './ui'

const isLang = (x?: string): x is Lang => LANGS.includes(x as Lang)

/** Старый адрес → новый: язык спереди, без .html, index — главная; ?lang= убираем (он теперь в пути), # — оставляем */
export function withLang(path: string, search: string, hash: string, lang: Lang): string {
  const clean = path.replace(/\/index\.html$/, '/').replace(/\.html$/, '').replace(/\/+$/, '') || ''
  const q = new URLSearchParams(search)
  q.delete('lang')
  const rest = q.toString()
  return `/${lang}${clean}${rest ? '?' + rest : ''}${hash}`
}

export function LangRoot() {
  const {lang} = useParams(), loc = useLocation(), dispatch = useAppDispatch(), current = useAppSelector(s => s.ui.lang)
  const ok = isLang(lang)
  useEffect(() => { if (ok && lang !== current) dispatch(setLang(lang)) }, [ok, lang, current, dispatch])
  if (!ok) return <Navigate replace to={withLang(loc.pathname, loc.search, loc.hash, startLang(loc.search, localStorage.getItem('lang'), loc.pathname))} />
  return <Layout />
}
