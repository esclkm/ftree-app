// «Хроника»: три вкладки — Места (/gallery, альбомы мест), Дома (/gallery/houses, дома семьи по городам),
// События (/gallery/events, альбомы времени и событий); каждый альбом и дом — своя страница. Альбом — по десятилетиям
// (/gallery/<slug>). Поиск (?q=) — по названию и описанию альбома, людям, месту и подписям снимков; во вкладке «Дома» — по
// дому и городу.
import {useCallback, useEffect, useMemo} from 'react'
import {matchesName, queryWords} from '../../nameSearch'
import {Link, NavLink, useParams, useSearchParams} from 'react-router'
import type {GalleryFile} from '../../data/schema.gen'
import {Icon} from '../../components/Icon'
import {useGalleryQuery} from '../api'
import {nameIn, trIn, useLang, useT} from '../i18n'
import {Status} from '../Layout'
import {type Shot, useLightbox} from '../Lightbox'
import {Faces} from '../Faces'
import {HousesList} from '../Houses'
import {Md} from '../Md'
import {shortUrls} from '../shortUrls'
import {PlaceAbout, PlaceLinks, usePlace} from '../PlaceParts'
import {cleanSlug, type Lookup, useIndex, useLinks} from '../useIndex'
import type {NotePhoto} from '../notes/model'
import {PhotoPin} from '../notes/Pin'
import {NoteScope} from '../notes/scope'
import {PhotoTimeline} from '../PhotoTimeline'

type Album = GalleryFile['albums'][number]
type Photo = Album['photos'][number]

function useGallery() {
  const {ix} = useIndex()
  return useGalleryQuery(ix ? ix.index.built : '', {skip: !ix})
}
const plain = (s = '') => s.replace(/[*`]/g, '').replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
/** Снимок галереи → то, что о нём помнит заметка */
export const notePhoto = (p: Photo): NotePhoto => ({url: p.url, thumb: p.thumb, caption: plain([p.year_txt, p.desc].filter(Boolean).join(' · ')),
  source: p.source ? plain(p.source) : undefined, link: p.link})
export const shotOf = (p: Photo): Shot => ({src: p.url, thumb: p.thumb, caption: [p.year_txt, plain(p.desc)].filter(Boolean).join(' · '),
  info: p.whose || p.exact || p.note || p.source || p.rights ? <>{p.like && <div><PhotoTag p={p} /></div>}<PhotoInfo p={p.like ? {...p, exact: ''} : p} /></> : undefined})

/** Что известно о снимке кроме подписи: чья история, насколько точно, примечание, источник. Под фото в сетке и в окне просмотра. */
export function PhotoInfo({p}: {p: Photo}) {
  const t = useT()
  return <>
    {p.whose && <div><b>{t('gal_whose')}:</b> <Md text={p.whose} /></div>}
    {p.exact && <div><b>{t('gal_exact')}:</b> <Md text={p.exact} /></div>}
    {p.note && <div className="warn"><b>{t('gal_note')}:</b> <Md text={p.note} /></div>}
    {(p.source || p.rights) && <div className="src-line"><b>{t('gal_source')}:</b>{' '}
      {p.link && !(p.source ?? '').includes('http') ? <a href={p.link} target="_blank" rel="noreferrer noopener">{plain(p.source) || p.link}</a> : <Md text={shortUrls(p.source)} />}
      {p.rights && ` · ${p.rights}`}</div>}
  </>
}

/** Годы снимков из адреса: ?from=1920&to=1940 — десятилетия, «по 1940-е» включает 1949. Нет — все годы. */
function usePeriod() {
  const [sp, setSp] = useSearchParams()
  const from = Number(sp.get('from')) || undefined, to = Number(sp.get('to')) || undefined
  const on = from !== undefined || to !== undefined
  const has = useCallback((p: Photo) => !on || (!!p.year && p.year >= (from ?? 0) && p.year <= (to ?? 9990) + 9), [on, from, to])
  const set = (f?: number, t?: number) => {
    const next = new URLSearchParams(sp)
    for (const [k, v] of [['from', f], ['to', t]] as const) { if (v === undefined) next.delete(k); else next.set(k, String(v)) }
    setSp(next, {replace: true})
  }
  return {from, to, on, has, set, query: on ? `?${sp.toString()}` : ''}
}
type Period = ReturnType<typeof usePeriod>

/** Выбор годов: «с 1920-х по 1940-е»; десятилетия — от самого старого снимка до самого нового */
function PeriodPicker({period, photos}: {period: Period; photos: Photo[]}) {
  const t = useT()
  const ys = photos.flatMap(p => (p.year ? [p.year] : []))
  if (!ys.length) return null
  const {from, to, on, set} = period
  // выбранное на общей странице может выходить за годы этого альбома — оно всё равно в списке
  const d0 = Math.floor(Math.min(...ys, from ?? 9999) / 10) * 10, d1 = Math.floor(Math.max(...ys, to ?? 0) / 10) * 10
  const decades = Array.from({length: (d1 - d0) / 10 + 1}, (_, i) => d0 + i * 10)
  const pick = (v: string) => (v ? Number(v) : undefined)
  return <div className="period">
    <Icon name="event" /><b>{t('gal_period')}</b>
    <label>{t('gal_from')} <select value={from ?? ''} onChange={e => { const f = pick(e.target.value); set(f, to !== undefined && f !== undefined && to < f ? f : to) }}>
      <option value="">…</option>{decades.map(d => <option key={d} value={d}>{t('gal_decade', d)}</option>)}</select></label>
    <label>{t('gal_to')} <select value={to ?? ''} onChange={e => { const v = pick(e.target.value); set(from !== undefined && v !== undefined && from > v ? v : from, v) }}>
      <option value="">…</option>{decades.map(d => <option key={d} value={d}>{t('gal_decade', d)}</option>)}</select></label>
    {on && <button className="btn tonal" onClick={() => set()}>{t('gal_all_years')}</button>}
  </div>
}

/** Поле поиска; слова — в адресе (?q=), чтобы пережили переход во вкладку, в альбом и обратно */
function useSearch() {
  const [sp, setSp] = useSearchParams()
  const q = sp.get('q') ?? ''
  const set = (v: string) => { const next = new URLSearchParams(sp); if (v) next.set('q', v); else next.delete('q'); setSp(next, {replace: true}) }
  return {q, words: queryWords(q), set, query: sp.toString() ? `?${sp.toString()}` : ''}
}

export function SearchBox({q, set, ph}: {q: string; set: (v: string) => void; ph: string}) {
  return <div className="search"><Icon name="search" /><input type="search" placeholder={ph} value={q} enterKeyHint="search" autoComplete="off"
    onChange={e => set(e.target.value)} onKeyDown={e => { if (e.key === 'Escape') set('') }} />
    {q && <button className="icon-btn" aria-label="×" onClick={() => set('')}>×</button>}</div>
}

/** Снимки альбома под запрос: совпало название, описание, место или люди альбома — все снимки; иначе — те, в чьей подписи
 *  (вместе с названием альбома: «Вербичи церковь») есть все слова */
function albumHits(a: Album, words: string[], ix: Lookup | undefined, lang: ReturnType<typeof useLang>, ps: Photo[]) {
  if (!words.length) return ps
  const own = [...Object.values(a.names), ...Object.values(a.about ?? {}),
    ...(a.place && ix?.places.get(a.place) ? Object.values(ix.places.get(a.place)!.names) : []),
    ...(a.people ?? []).flatMap(id => (ix?.people.get(id) ? Object.values(ix.people.get(id)!.names) : []))].map(x => plain(String(x)))
  if (matchesName(own, words)) return ps
  return ps.filter(p => { const l = trIn(p, lang)
    return matchesName([...own, ...[p.desc, l.desc, p.year_txt, l.whose, l.section, p.year ? String(p.year) : ''].map(x => plain(x ?? ''))], words) })
}

type Tab = 'places' | 'houses' | 'events'
const TABS = [['places', '', 'place', 'gal_places'], ['houses', '/houses', 'home', 'map_tab_houses'], ['events', '/events', 'event', 'gal_events']] as const

export function GalleryIndex({tab = 'places'}: {tab?: Tab}) {
  const href = useLinks()
  const t = useT(), lang = useLang(), q = useGallery(), {ix} = useIndex(), period = usePeriod(), search = useSearch()
  const title = TABS.find(x => x[0] === tab)![3]
  useEffect(() => { document.title = `${t(title)} — ${t('nav_gallery')} — ${t('site')}` }, [t, title])
  const tabs = <nav className="chips gal-tabs">{TABS.map(([k, path, ic, key]) =>
    <NavLink key={k} end className="chip" to={href.at(`/gallery${path}`) + search.query}><Icon name={ic} />{t(key)}</NavLink>)}</nav>
  const head = <><h1 className="page-title">{t('nav_gallery')}</h1>{tabs}<SearchBox q={search.q} set={search.set} ph={t('gal_search')} /></>
  if (tab === 'houses') return <>{head}<section className="card">{ix ? <HousesList ix={ix} words={search.words} /> : <Status state="loading" />}</section></>
  if (q.isError) return <Status state="error" />
  if (!q.data) return <Status state="loading" />
  const kind = tab === 'places' ? 'place' : 'theme'
  const all = q.data.albums.filter(a => a.kind === kind)
  const shown = all.map(a => ({a, ps: albumHits(a, search.words, ix, lang, a.photos.filter(period.has))})).filter(x => x.ps.length > 0)
  return <>
    {head}
    <p className="note">{t('gal_intro')}</p>
    <PeriodPicker period={period} photos={all.flatMap(a => a.photos)} />
    {!shown.length && <p className="note">{t(search.words.length ? 'search_none' : 'gal_none_in_period')}</p>}
    {shown.length > 0 && <section className="card">
      <div className="albums">{shown.map(({a, ps}) => <AlbumTile key={a.slug} a={a} ps={ps} ix={ix} to={href.album(a.slug) + period.query} on={period.on || search.words.length > 0} lang={lang} />)}</div>
    </section>}
  </>
}

function AlbumTile({a, ps, ix, to, on, lang}: {a: Album; ps: Photo[]; ix?: Lookup; to: string; on: boolean; lang: ReturnType<typeof useLang>}) {
  const t = useT()
  const ys = ps.flatMap(p => (p.year ? [p.year] : []))
  return <Link className="album" to={to}>
    <figure className="cover">{ps[0] && <img loading="lazy" src={ps[0].thumb} alt="" />}
      {ix && a.people && <Faces ids={a.people} ix={ix} />}</figure>
    <div><b>{nameIn(a.names, lang)}</b>
      {a.about && <span className="album-about"><Md text={nameIn(a.about, lang)} /></span>}
      <span>{on ? t('gal_in_period', ps.length, a.photos.length) : t('gal_photos_n', a.photos.length)}{ys.length ? ` · ${Math.min(...ys)}–${Math.max(...ys)}` : ''}</span></div>
  </Link>
}

export function AlbumPage() {
  const href = useLinks()
  const t = useT(), lang = useLang(), {slug} = useParams(), q = useGallery(), {ix} = useIndex(), period = usePeriod()
  const a = q.data?.albums.find(x => x.slug === cleanSlug(slug))
  const has = period.has
  const groups = useMemo(() => {
    const g = new Map<string, Photo[]>()
    for (const p of (a?.photos ?? []).filter(has)) {
      const k = a?.kind === 'theme' && p.section ? `s:${p.section}` : p.year ? `d:${Math.floor(p.year / 10) * 10}` : 'none'
      g.set(k, [...(g.get(k) ?? []), p])
    }
    return [...g.entries()].sort(([x], [y]) => (x === 'none' ? 1 : y === 'none' ? -1 : x.localeCompare(y)))
  }, [a, has])
  const pl = usePlace(a?.place ?? undefined)
  useEffect(() => { if (a) document.title = `${nameIn(a.names, lang)} — ${t('site')}` }, [a, lang, t])
  if (q.isError) return <Status state="error" />
  if (!q.data) return <Status state="loading" />
  if (!a) return <Status state="not_found" />
  const place = a.place ? ix?.places.get(a.place) : undefined
  return <NoteScope subject={{type: 'album', id: a.slug, name: t('nw_album', a.names.ru), path: `/gallery/${a.slug}`}}>
    <section className="hero card"><span className="avatar ph P"><Icon name="pics" /></span>
      <div className="hero-text"><h1>{nameIn(a.names, lang)}</h1><div className="life big">{t('gal_photos_n', a.photos.length)}</div>
        {ix && a.people && <Faces ids={a.people} ix={ix} max={6} />}</div>
      {place && <Link className="btn tonal" to={href.place(place.slug)}><Icon name="place" />{t('gal_place_page')}</Link>}
    </section>
    {a.about && <section className="card prose"><p><Md text={nameIn(a.about, lang)} /></p></section>}
    <PeriodPicker period={period} photos={a.photos} />
    {period.on && !groups.length && <p className="note">{t('gal_none_in_period')}</p>}
    {pl && <PlaceAbout pl={pl} />}
    {groups.length > 0 && <section className="card flat">
      <PhotoTimeline photos={groups.flatMap(([, ps]) => ps)} tags={a.kind === 'place'} where={t('nw_album', a.names.ru)}
        slices={groups.map(([k, ps]) => ({key: k, photos: ps, state: commonEra(ps, lang),
          years: k === 'none' ? t('gal_noyear') : k.startsWith('d:') ? t('gal_decade', k.slice(2)) : <Md text={trIn(ps[0], lang).section || k.slice(2)} />}))} />
    </section>}
    {pl && ix && <PlaceLinks pl={pl} ix={ix} />}
  </NoteScope>
}

/** Государство, которое чаще всего стоит у снимков среза (подпись под годами) */
const commonEra = (ps: Photo[], lang: ReturnType<typeof useLang>) => {
  const n = new Map<string, number>()
  for (const p of ps) if (p.era) n.set(nameIn(p.era, lang), (n.get(nameIn(p.era, lang)) ?? 0) + 1)
  return [...n.entries()].sort((x, y) => y[1] - x[1])[0]?.[0]
}

/** Метка снимка места: золотая «наше · <где>» или красная «≈ не наше · <где>, N км от деревни <нашей>» (навык photos,
 *  «Не наше, но похожее»). «≈» без имени файла по образцу — только «≈ не наше». */
export function PhotoTag({p, ours}: {p: Photo; ours?: string}) {
  const t = useT(), lang = useLang()
  if (p.like || (p.exact ?? '').startsWith('≈')) {
    const l = p.like
    const where = l?.real && l.ours && l.km ? t('gal_like_km', nameIn(l.real, lang), l.km, nameIn(l.ours, lang)) : ''
    return <span className="ph-tag like">{t('gal_like')}{where && ` · ${where}`}</span>
  }
  return <span className="ph-tag">{t('gal_ours')}{ours && ` · ${ours}`}</span>
}

/** Сетка снимков с подписями; нажатие — окно просмотра по всем снимкам этой сетки (или по общему списку shots с from).
 *  tags — метки «наше / ≈ не наше» (у мест; у снимков событий — только «≈»); ours — где снято, для золотой метки. */
export function PhotoGrid({photos, where: own, tags, ours, shots: allShots, from = 0}: {photos: Photo[]; where?: string; tags?: boolean
  ours?: (p: Photo) => string | undefined; shots?: Shot[]; from?: number}) {
  const lang = useLang(), open = useLightbox(), t = useT(), where = own ?? t('nw_photo')
  const shown = photos.map(p => trIn(p, lang))
  const shots = allShots ?? shown.map(shotOf)
  return <div className="ph-grid">{shown.map((p, i) => {
    const like = !!p.like || (p.exact ?? '').startsWith('≈')
    const credit = [p.year_txt, p.era && !tags ? nameIn(p.era, lang) : ''].filter(Boolean).join(' · ')
    return <figure key={p.url} className="ph-card">
      <a href={p.url} className="pin-host" onClick={e => { e.preventDefault(); open(shots, from + i) }}><img loading="lazy" src={p.thumb} alt={plain(p.desc)} />
        <PhotoPin photo={notePhoto(photos[i])} where={where} /></a>
      <figcaption>
        {(tags || like) && <PhotoTag p={p} ours={ours?.(photos[i])} />}
        {p.desc && <div className="cap"><Md text={p.desc} /></div>}
        {credit && <div className="credit">{credit}</div>}
        <PhotoInfo p={like && p.like ? {...p, exact: ''} : p} />
      </figcaption>
    </figure>
  })}</div>
}
