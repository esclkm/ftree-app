// Надписи интерфейса на языке из хранилища. Словарь — I18N_ROWS в site_export.py → data/ui.json.
import {useCallback} from 'react'
import type {GDate, Lang, LangText} from '../data/schema.gen'
import {dict} from '../data'
import {fmtGed} from '../gdate'
import {useAppSelector} from './store'


export const useLang = (): Lang => useAppSelector(s => s.ui.lang)

export function translate(lang: Lang, k: string, ...a: (string | number)[]): string {
  const d = dict()
  let s = d[lang]?.[k] ?? d.ru[k] ?? k
  a.forEach((v, i) => { s = s.replace(`{${i}}`, String(v)) })
  return s
}

export function useT() {
  const lang = useLang()
  return useCallback((k: string, ...a: (string | number)[]) => translate(lang, k, ...a), [lang])
}

/** Имя на языке: польское и испанское, если есть, иначе английское; русское — всегда есть */
export const nameIn = (n: LangText, lang: Lang): string =>
  lang === 'ru' ? n.ru : lang === 'pl' ? n.pl ?? n.en ?? n.ru : lang === 'es' ? n.es ?? n.en ?? n.ru : n.en ?? n.ru

/** Перевод полей на языке страницы (поле tr из translations/<язык>/<вид>/…): нет перевода — русские поля как есть */
type WithTr = {tr?: {pl?: object; es?: object; en?: object} | null}
export const trIn = <T extends WithTr>(x: T, lang: Lang): T =>
  lang === 'ru' || !x.tr ? x : {...x, ...x.tr[lang]}

/** Название источника или документа на языке страницы (titles из translations/<язык>/<sources|documents>/), иначе русское */
export const titleIn = (x: {title: string; titles?: {pl?: string; es?: string; en?: string} | null}, lang: Lang): string =>
  (lang === 'ru' ? undefined : x.titles?.[lang]) || x.title

/** Дата: по-русски — как в карточке («1944 (осень)»), остальным — переводом той же записи (gdate.ts) */
export const dateIn = (d: GDate, lang: Lang): string =>
  lang === 'ru' ? d.ru : fmtGed(d.value + (d.words ? ` (${d.words})` : ''), lang)
