// Рамка каждой страницы: шапка с разделами, выбором языка и шестерёнкой «Настройки»; на широком экране — кнопка и панель заметок справа.
import {useEffect, useRef} from 'react'
import {Link, NavLink, Outlet, useLocation, useNavigate} from 'react-router'
import type {Lang} from '../data/schema.gen'
import {Icon} from '../components/Icon'
import {useLang, useT} from './i18n'
import {LightboxProvider} from './Lightbox'
import {NotesButton, NotesPanel} from './notes/NotesPanel'
import {QuoteButton} from './notes/Quote'
import {LANGS} from './ui'
import {useLinks} from './useIndex'

/** Телефон: прокрутили вниз — строка с названием и языком уезжает за верх экрана, остаётся узкое меню; вернулись к
 *  началу — шапка целиком. Сдвиг, а не скрытие: высота шапки в потоке не меняется, текст под ней не прыгает. */
function useCompactBar(path: string) {
  const ref = useRef<HTMLElement>(null)
  const check = useRef(() => {})
  useEffect(() => {
    const bar = ref.current
    if (!bar) return
    const phone = window.matchMedia('(max-width: 700px)')  // $phone в _mixins.scss
    let on = false
    const update = () => {
      const nav = bar.querySelector('nav')
      // два порога, а не один: свёрнутая шапка ниже, страница от этого сдвигается — с одним порогом шапка прыгала
      // туда-сюда («больше-меньше») на одной и той же прокрутке
      const y = window.scrollY
      const want = phone.matches && (on ? y > 20 : y > 80)
      if (want === on) return
      on = want
      bar.classList.toggle('compact', on)
      bar.style.transform = on && nav ? `translateY(-${nav.offsetTop - 2}px)` : ''
    }
    check.current = update
    window.addEventListener('scroll', update, {passive: true})
    phone.addEventListener('change', update)
    update()
    return () => { window.removeEventListener('scroll', update); phone.removeEventListener('change', update) }
  }, [])
  // другая страница — с её начала и с шапкой целиком (карта и дерево не прокручиваются: события прокрутки на них не будет)
  const first = useRef(true)
  useEffect(() => {
    if (first.current) { first.current = false; return }
    window.scrollTo(0, 0)
    const id = requestAnimationFrame(() => check.current())
    return () => cancelAnimationFrame(id)
  }, [path])
  return ref
}

export function Layout() {
  const t = useT(), lang = useLang(), href = useLinks(), loc = useLocation(), navigate = useNavigate(), bar = useCompactBar(loc.pathname)
  // другой язык — тот же адрес с другим языком спереди: /ru/people/x → /es/people/x
  const switchTo = (l: Lang) => navigate(loc.pathname.replace(/^\/\w\w(?=\/|$)/, `/${l}`) + loc.search + loc.hash)
  return <>
    <header className="appbar" ref={bar}>
      <Link className="brand" to={href.home}><Icon name="tree" />{t('site')}</Link>
      <nav>
        {([['nav_tree', '/tree', 'tree'], ['nav_map', '/map', 'map'], ['nav_people', '/people', 'fam'], ['nav_lifelines', '/lifelines', 'event'], ['nav_gallery', '/gallery', 'pics'], ['nav_sources', '/sources', 'source'], ['nav_news', '/news', 'history']] as const).map(([k, to, ic]) =>
          <NavLink key={k} to={href.at(to)} title={t(k)} end className={({isActive}) => isActive ? 'on' : undefined}><Icon name={ic} /><span>{t(k)}</span></NavLink>)}
      </nav>
      <div className="actions">
        <NotesButton />
        <select id="lang" aria-label="Language" value={lang} onChange={e => switchTo(e.target.value as Lang)}>
          {LANGS.map(c => <option key={c} value={c}>{c.toUpperCase()}</option>)}
        </select>
        <NavLink className={({isActive}) => 'setlink' + (isActive ? ' on' : '')} to={href.at('/settings')} title={t('set_title')} aria-label={t('set_title')}><Icon name="settings" /></NavLink>
      </div>
    </header>
    <LightboxProvider>
      <main>
        <Outlet />
      </main>
      <NotesPanel />
      <QuoteButton />
    </LightboxProvider>
  </>
}

/** Загрузка, «нет такой страницы», ошибка связи — одинаково на всех страницах */
export function Status({state}: {state: 'loading' | 'not_found' | 'error'}) {
  const t = useT()
  return <section className="card status">{t(state === 'loading' ? 'loading' : state === 'not_found' ? 'not_found' : 'load_error')}</section>
}
