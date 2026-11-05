// Данные сайта — файлы data/*.json (их пишет tools/scripts/site_data/export.py, форма — web/schema/).
// RTK Query скачивает файл один раз и держит его, пока он нужен: вернулись к человеку — без нового запроса.
import {createApi, type BaseQueryFn} from '@reduxjs/toolkit/query/react'
import type {DocFile, GalleryFile, PersonFile, PlaceFile, ProgressFile, ResearchFile, ReviewFile, SiteIndex, SourceFile} from '../data/schema.gen'

export interface LoadError { status: 'not_found' | 'network' | 'bad_data'; path: string }

/** Файл data/…. Хостинг на адрес без файла отвечает главной страницей с кодом 200 (web/README.md) — поэтому
 *  «не JSON» значит «такого нет», а не «сломалось». */
export const dataQuery: BaseQueryFn<string, unknown, LoadError> = async path => {
  let r: Response
  try { r = await fetch(`/data/${path}`) } catch { return {error: {status: 'network', path}} }
  const json = (r.headers.get('content-type') ?? '').includes('json')
  if (r.status === 404 || (r.ok && !json)) return {error: {status: 'not_found', path}}
  if (!r.ok) return {error: {status: 'network', path}}
  try { return {data: await r.json()} } catch { return {error: {status: 'bad_data', path}} }
}

/** v — метка сборки из index.json: новая сборка — новая ссылка, браузер не покажет старый файл */
interface ById { id: string; v: string }
const file = (kind: string) => ({id, v}: ById) => `${kind}/${id}.json?v=${encodeURIComponent(v)}`

export const api = createApi({
  reducerPath: 'data',
  baseQuery: dataQuery,
  keepUnusedDataFor: 600,
  endpoints: b => ({
    index: b.query<SiteIndex, void>({query: () => 'index.json'}),
    person: b.query<PersonFile, ById>({query: file('people')}),
    place: b.query<PlaceFile, ById>({query: file('places')}),
    source: b.query<SourceFile, ById>({query: file('sources')}),
    doc: b.query<DocFile, ById>({query: file('docs')}),  // заметка проекта: расшифровка, находка, документ человека
    gallery: b.query<GalleryFile, string>({query: v => `gallery.json?v=${encodeURIComponent(v)}`}),
    research: b.query<ResearchFile, string>({query: v => `research.json?v=${encodeURIComponent(v)}`}),  // «Что ещё искать»
    review: b.query<ReviewFile, string>({query: v => `review.json?v=${encodeURIComponent(v)}`}),  // «Сверка»
    progress: b.query<ProgressFile, string>({query: v => `progress.json?v=${encodeURIComponent(v)}`}),  // «Состояние дерева», «Что нового»
  }),
})
export const {useIndexQuery, usePersonQuery, usePlaceQuery, useSourceQuery, useDocQuery, useGalleryQuery, useResearchQuery, useReviewQuery, useProgressQuery} = api
