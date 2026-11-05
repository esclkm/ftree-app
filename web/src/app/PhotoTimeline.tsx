// Лента снимков по срезам лет — как на странице «Деревни предков по годам»: слева крупные годы среза и государство
// тогда, справа снимки сеткой. Срез — одно государство (эпоха снимка); снимки без эпохи — по десятилетиям, без года — в конце.
// Для страницы места, «Фото мест из жизни» и альбома.
import type {ReactNode} from 'react'
import type {GalleryFile} from '../data/schema.gen'
import {nameIn, trIn, useLang, useT} from './i18n'
import {PhotoGrid, shotOf} from './pages/Gallery'

type Photo = GalleryFile['albums'][number]['photos'][number]
export type Slice = {key: string; years: ReactNode; state?: string; photos: Photo[]}

const span = (ys: number[]): ReactNode => {
  const a = Math.min(...ys), b = Math.max(...ys)
  return a === b ? String(a) : <>{a}–<wbr />{b}</>
}

/** Годы снимка: год для сортировки и годы из подписи («1915–1918», «1895–98») — чтобы срез показал весь промежуток */
const yearsOf = (p: Photo): number[] => {
  const ys = p.year ? [p.year] : []
  for (const m of (p.year_txt ?? '').matchAll(/(1[6-9]\d\d|20\d\d)(?:\s*[–-]\s*(\d{2,4})\b)?/g)) {
    ys.push(Number(m[1]))
    if (m[2]) ys.push(Number(m[2].length === 2 ? m[1].slice(0, 2) + m[2] : m[2]))
  }
  return ys
}

/** Срезы по эпохам: одно государство — один срез, годы — от самого старого снимка среза до самого нового */
export function eraSlices(photos: Photo[], lang: ReturnType<typeof useLang>, noYear: string, decade: (d: number) => string): Slice[] {
  const by = new Map<string, Photo[]>()
  for (const p of [...photos].sort((x, y) => (x.year ?? 9999) - (y.year ?? 9999))) {
    const k = p.era ? `e:${p.era.ru}` : p.year ? `d:${Math.floor(p.year / 10) * 10}` : 'none'
    by.set(k, [...(by.get(k) ?? []), p])
  }
  const first = (ps: Photo[]) => ps[0].year ?? 9999
  return [...by.entries()].sort(([, a], [, b]) => first(a) - first(b)).map(([key, ps]) => {
    const ys = ps.flatMap(yearsOf)
    return {key, photos: ps,
      years: key === 'none' ? noYear : key.startsWith('d:') ? decade(Number(key.slice(2))) : span(ys),
      state: ps[0].era ? nameIn(ps[0].era, lang) : undefined}
  })
}

/** Подписи меток над лентой — только если есть хоть один «≈ не наше» */
export function TagLegend({photos}: {photos: Photo[]}) {
  const t = useT()
  if (!photos.some(p => p.like || (p.exact ?? '').startsWith('≈'))) return null
  return <div className="ph-legend">
    <span><span className="ph-tag">{t('gal_ours')}</span> {t('gal_legend_ours')}</span>
    <span><span className="ph-tag like">{t('gal_like')}</span> {t('gal_legend_like')}</span>
  </div>
}

/** Лента: срезы готовые (slices) или по эпохам из photos; perSlice — сколько снимков показать в срезе (остальные —
 *  по ссылке «все фото» снаружи). Окно просмотра листает все показанные снимки подряд. */
export function PhotoTimeline({photos, slices: own, where, tags = true, ours, perSlice}: {photos: Photo[]; slices?: Slice[]; where?: string
  tags?: boolean; ours?: (p: Photo) => string | undefined; perSlice?: number}) {
  const t = useT(), lang = useLang()
  const slices = (own ?? eraSlices(photos, lang, t('gal_noyear'), d => t('gal_decade', d)))
    .map(s => ({...s, photos: perSlice ? s.photos.slice(0, perSlice) : s.photos}))
  const flat = slices.flatMap(s => s.photos)
  const shots = flat.map(p => {
    const s = shotOf(trIn(p, lang)), o = ours?.(p)
    return o ? {...s, caption: [o, s.caption].filter(Boolean).join(' · ')} : s
  })
  const from = slices.map((_, i) => slices.slice(0, i).reduce((n, s) => n + s.photos.length, 0))
  return <>
    {tags && <TagLegend photos={flat} />}
    {slices.map((s, i) => <div key={s.key} className="ph-era">
      <div className="ph-era-head"><div className="ph-years">{s.years}</div>{s.state && <div className="ph-state">{s.state}</div>}</div>
      <PhotoGrid photos={s.photos} where={where} tags={tags} ours={ours} shots={shots} from={from[i]} />
    </div>)}
  </>
}
