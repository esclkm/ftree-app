// Язык сайта и кнопка «Поделиться». Словарь I18N — из data/ui.json (I18N_ROWS в site_export.py).
// Язык берётся из ссылки (?lang=es) и запоминается; по умолчанию — русский.
import {dict, type Lang, type Names} from './data'
import {fmtGed, fmtIso} from './gdate'

const I18N = dict()
const browser = typeof location !== 'undefined'  // в тестах (Vitest) браузера нет — модуль загружается и без него
const q = browser ? new URLSearchParams(location.search).get('lang') : null
if (q && q in I18N) localStorage.setItem('lang', q)
const saved = browser ? localStorage.getItem('lang') : null
/** Язык страницы. Нынешние страницы задают его один раз при загрузке; приложение (src/app) меняет его setLanguage() */
export let LANG: Lang = saved && saved in I18N ? saved as Lang : 'ru'
if (browser) document.documentElement.lang = LANG
export function setLanguage(lang: Lang): void { LANG = lang; if (browser) document.documentElement.lang = lang }

export const t = (k: string, ...a: (string | number)[]): string => {
  let s = I18N[LANG]?.[k] ?? I18N.ru[k] ?? k
  a.forEach((v, i) => { s = s.replace(`{${i}}`, String(v)) })
  return s
}
/** имя: по-русски — кириллицей, по-польски — польской латиницей, остальным — английской */
export const nameOf = (x: Names): string => LANG === 'ru' ? x.ru : LANG === 'pl' ? x.pl : LANG === 'es' ? (x.es || x.en) : x.en
export const altName = (x: Names): string => LANG === 'ru' ? x.en : x.ru
export const esc = (s: unknown): string => String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]!))

// Даты «1971-03-05» и «1986-02» — по-местному: «5 марта 1971», «февраль 1986» (web/src/gdate.ts)
export const fmtDate = (iso: string): string => fmtIso(iso, LANG)

export function snack(msg: string): void {
  const s = document.getElementById('snack') as (HTMLElement & {_t?: number}) | null
  if (!s) return
  s.textContent = msg; s.classList.add('on')
  clearTimeout(s._t); s._t = window.setTimeout(() => s.classList.remove('on'), 3000)
}

// Ссылка на эту страницу с языком: получатель откроет её сразу на своём языке и на том же человеке
async function share(): Promise<void> {
  const u = new URL(location.href)
  u.searchParams.set('lang', LANG)
  const link = u.href
  if (navigator.share && matchMedia('(pointer: coarse)').matches) {
    try { await navigator.share({title: document.title, url: link}); return } catch { /* отменили — копируем */ }
  }
  try { await navigator.clipboard.writeText(link); snack(t('copied')) } catch { prompt('', link) }
}

function bioTabs(): void {
  // биография: показываем перевод на языке сайта, если он есть; иначе русский текст и подсказку
  document.querySelectorAll<HTMLElement>('.bio').forEach(card => {
    const missing = card.querySelector<HTMLElement>('.missing')
    const show = (lang: string) => {
      card.querySelectorAll<HTMLElement>('.bio-lang').forEach(b => { b.hidden = b.dataset.lang !== lang })
      card.querySelectorAll<HTMLElement>('[data-bl]').forEach(b => b.classList.toggle('on', b.dataset.bl === lang))
    }
    const has = !!card.querySelector(`.bio-lang[data-lang="${LANG}"]`)
    show(has ? LANG : 'ru')
    if (missing) missing.hidden = has || LANG === 'ru'
    const tabs = card.querySelectorAll<HTMLElement>('[data-bl]')
    tabs.forEach(b => { b.onclick = () => { show(b.dataset.bl!); if (missing) missing.hidden = true } })
    const bar = card.querySelector<HTMLElement>('.bio-tabs')
    if (bar && tabs.length < 2) bar.hidden = true
  })
}

/** Перевести надписи страницы: русский уже в HTML, остальные языки подставляем из словаря */
export function applyLang(): void {
  document.querySelectorAll('time[datetime]').forEach(e => { e.textContent = fmtDate(e.getAttribute('datetime')!) })
  // даты карточек («ABT 1935») — на любом языке; даты линии жизни — русский текст уже как надо (со ⭐ и словами), остальным — перевод
  document.querySelectorAll<HTMLElement>('time[data-ged]').forEach(e => { e.textContent = fmtGed(e.dataset.ged!, LANG) })
  if (LANG !== 'ru') document.querySelectorAll<HTMLElement>('.date[data-ged]').forEach(e => { e.textContent = fmtGed(e.dataset.ged!, LANG) })
  if (LANG !== 'ru') {
    document.querySelectorAll<HTMLElement>('[data-t]').forEach(e => { e.textContent = t(e.dataset.t!, ...(e.dataset.a ? e.dataset.a.split('|') : [])) })
    document.querySelectorAll<HTMLInputElement>('[data-tp]').forEach(e => { e.placeholder = t(e.dataset.tp!) })
    document.querySelectorAll<HTMLElement>('[data-tt]').forEach(e => { e.title = t(e.dataset.tt!) })
    document.querySelectorAll<HTMLElement>('.nm').forEach(e => {
      e.textContent = (LANG === 'pl' ? e.dataset.pl : LANG === 'es' ? e.dataset.es || e.dataset.en : e.dataset.en) ?? e.textContent
    })
    document.querySelectorAll<HTMLElement>('.tr').forEach(e => { e.textContent = e.dataset[LANG] || e.textContent })
    const h = document.querySelector('h1')
    if (h) document.title = h.textContent + ' — ' + t('site')
  } else {
    document.querySelectorAll('.ru-note').forEach(e => e.remove())  // русским подсказка про перевод не нужна
  }
  bioTabs()
  const sel = document.getElementById('lang') as HTMLSelectElement | null
  if (sel) {
    sel.value = LANG
    sel.onchange = () => {
      localStorage.setItem('lang', sel.value)
      const u = new URL(location.href); u.searchParams.set('lang', sel.value); location.href = u.href
    }
  }
  const btn = document.getElementById('share')
  if (btn) btn.onclick = share
}
