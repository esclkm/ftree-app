// Вход приложения. Сначала — надписи, значки и общий список (data/ui.json, data/index.json): дерево, карта и «кем
// приходится» строят граф родства сразу при загрузке своего кода, поэтому данные передаём им до неё (data.ts, provide),
// а само приложение (App.tsx) загружаем потом.
import {provide} from '../data'
import type {SiteIndex, UiFile} from '../data/schema.gen'
import {placesFromIndex, treeFromIndex} from './fromIndex'
import {applyTheme} from './theme'

applyTheme()  // до первой отрисовки — без вспышки светлой темы

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`/data/${path}`, {cache: 'no-cache'})  // после выкладки — новые надписи, а не из кэша браузера
  if (!r.ok || !(r.headers.get('content-type') ?? '').includes('json')) throw new Error(path)
  return r.json() as Promise<T>
}

async function start(): Promise<void> {
  const [ui, index] = await Promise.all([get<UiFile>('ui.json'), get<SiteIndex>('index.json')])
  provide({dict: ui.i18n, icons: ui.icons, tree: treeFromIndex(index), places: placesFromIndex(index),
    start: index.start, divorces: index.divorces})
  const {mount} = await import('./App')
  mount(index)
}

// надписи ещё не загружены — эта одна на четырёх языках прямо здесь, язык — из адреса (/pl/…)
const FAILED: Record<string, string> = {
  ru: 'Не удалось загрузить сайт — проверьте связь и обновите страницу.',
  pl: 'Nie udało się załadować strony — sprawdź połączenie i odśwież stronę.',
  es: 'No se pudo cargar el sitio: compruebe la conexión y recargue la página.',
  en: 'The site failed to load — check your connection and reload the page.',
}
start().catch(() => {
  document.getElementById('root')!.textContent = FAILED[location.pathname.split('/')[1]] ?? FAILED.ru
})
