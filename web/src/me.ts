// «Я» — человек, от которого сайт считает родство. Выбирают кнопкой «Это я»; хранится только в этом браузере
// (localStorage 'me'), на сервер не уходит. Ссылка ?me=<slug> ставит «я» сразу — её можно отправить родственнику.
import {useSyncExternalStore} from 'react'
import {kin} from './kin'

const KEY = 'me'
const listeners = new Set<() => void>()

const fromLink = new URLSearchParams(location.search).get('me')
if (fromLink && kin.bySlug[fromLink]) localStorage.setItem(KEY, kin.bySlug[fromLink])

export function getMe(): string | null {
  const id = localStorage.getItem(KEY)
  return id && kin.P[id] ? id : null
}
export function setMe(id: string | null): void {
  if (id) localStorage.setItem(KEY, id); else localStorage.removeItem(KEY)
  listeners.forEach(f => f())
}
/** «Я» в компоненте React: сменили — компонент перерисуется сам */
export function useMe(): string | null {
  return useSyncExternalStore(f => { listeners.add(f); return () => listeners.delete(f) }, getMe)
}
