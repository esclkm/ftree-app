// Общий список (data/index.json) и поиск по нему: человек по номеру и по адресу страницы, место, источник.
import {useMemo} from 'react'
import type {Lang, SiteIndex} from '../data/schema.gen'
import {useIndexQuery} from './api'
import {useLang} from './i18n'

export type IndexPerson = SiteIndex['people'][number]
export type IndexPlace = SiteIndex['places'][number]
export type IndexSource = SiteIndex['sources'][number]

export interface Lookup {
  index: SiteIndex
  people: Map<string, IndexPerson>; personBySlug: Map<string, IndexPerson>
  places: Map<string, IndexPlace>; placeBySlug: Map<string, IndexPlace>
  sources: Map<string, IndexSource>; sourceBySlug: Map<string, IndexSource>
}

export function lookup(index: SiteIndex): Lookup {
  const by = <T extends {id: string; slug: string}>(xs: T[]) =>
    [new Map(xs.map(x => [x.id, x])), new Map(xs.map(x => [x.slug, x]))] as const
  const [people, personBySlug] = by(index.people)
  const [places, placeBySlug] = by(index.places)
  const [sources, sourceBySlug] = by(index.sources)
  return {index, people, personBySlug, places, placeBySlug, sources, sourceBySlug}
}

export function useIndex() {
  const q = useIndexQuery()
  const ix = useMemo(() => (q.data ? lookup(q.data) : undefined), [q.data])
  return {...q, ix}
}

/** Адрес страницы: старые ссылки кончались на .html (они уже у родни) — принимаем и такие */
export const cleanSlug = (slug = ''): string => slug.replace(/\.html$/, '')

/** Адреса страниц — всегда с языком: /ru/people/<slug>. Язык в адресе — один на всё: ссылку отправили, получатель
 *  видит тот же язык. Без языка адрес (старые ссылки …/people/x.html) App.tsx перенаправляет. */
export function links(lang: Lang) {
  const at = (p: string) => `/${lang}${p}`
  return {
    at, home: at('/'),
    person: (slug: string) => at(`/people/${slug}`), place: (slug: string) => at(`/places/${slug}`),
    source: (slug: string) => at(`/sources/${slug}`), album: (slug: string) => at(`/gallery/${slug}`),
    doc: (id: string) => at(`/docs/${id}`),
  }
}
export type Links = ReturnType<typeof links>
export const useLinks = (): Links => links(useLang())
