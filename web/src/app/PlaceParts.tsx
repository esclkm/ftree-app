// Части страницы места, общие со страницей её альбома: вводный текст «О месте» сверху; снизу — люди этого места и
// места рядом и похожие.
import {skipToken} from '@reduxjs/toolkit/query'
import {Link} from 'react-router'
import type {PlaceFile} from '../data/schema.gen'
import {Icon} from '../components/Icon'
import {usePlaceQuery} from './api'
import {BioMd} from './BioMd'
import {dateIn, nameIn, useLang, useT} from './i18n'
import {Md} from './Md'
import {PersonLink} from './pages/PersonPage'
import {type Lookup, useIndex, useLinks} from './useIndex'

/** Место по номеру — для альбома, у которого есть карточка места */
export function usePlace(id?: string) {
  const {ix} = useIndex()
  return usePlaceQuery(id && ix ? {id, v: ix.index.built} : skipToken).data
}

/** «О месте»: на языке страницы, нет перевода — русский */
export function PlaceAbout({pl}: {pl: PlaceFile}) {
  const t = useT(), lang = useLang()
  const text = pl.about?.[lang] ?? pl.about?.ru
  if (!text) return null
  return <section className="card prose place-about" data-note-where={t('nw_place_about')}>
    <h2><Icon name="place" />{t('place_about')}</h2><BioMd text={text} /></section>
}

/** Остальной текст карточки места — на языке страницы, если есть перевод (translations/<язык>/places/), иначе русский */
export function PlaceText({pl}: {pl: PlaceFile}) {
  const t = useT(), lang = useLang()
  const tr = lang === 'ru' ? undefined : pl.tr?.[lang]
  const text = tr?.md || pl.md
  if (!text) return null
  return <section className="card prose" data-note-where={t('nw_place_text')}>
    {tr?.md && tr.ai && <p className="tr-note">{t('tr_ai')}</p>}
    {tr?.md && tr.stale && <p className="tr-note warn">{t('tr_stale')}</p>}
    <BioMd text={text} /></section>
}

function PlaceList({ids, ix, km}: {ids: string[]; ix: Lookup; km?: Map<string, number>}) {
  const href = useLinks()
  const t = useT(), lang = useLang()
  return <ul className="plain columns">{ids.flatMap(id => {
    const x = ix.places.get(id)
    return x ? [<li key={id}><Link to={href.place(x.slug)}>{nameIn(x.names, lang)}</Link>
      {km?.has(id) && <span className="life"> · {km.get(id)} {t('km')}</span>}</li>] : []
  })}</ul>
}

type Who = NonNullable<PlaceFile['who']>[number]

/** Чем человек связан с местом: «родился», а у события — ещё годы и суть: «работа, 1931–1941: водила поезда…» */
export function WhoWhat({w}: {w: Who}) {
  const t = useT(), lang = useLang()
  return <span className="life"> — {w.what.map((k, i) => {
    const evs = (w.events ?? []).filter(e => e.what === k && (e.date || e.text))
    return <span key={k}>{i > 0 && '; '}{t(k)}{evs.map((e, j) =>
      <span key={j}>{j > 0 && ';'}{e.date && ` ${dateIn(e.date, lang)}`}{e.text && <>{e.date || j === 0 ? ': ' : ' '}<Md text={e.text} /></>}</span>)}</span>
  })}</span>
}

/** Низ страницы: кто связан с местом, что внутри него, что рядом и что похоже */
export function PlaceLinks({pl, ix}: {pl: PlaceFile; ix: Lookup}) {
  const t = useT()
  // у дома жильцы уже в «Кто жил в доме» (Houses.tsx) — здесь остальные: кто там умер, учился …
  const lived = new Set((pl.residents ?? []).map(r => r.person))
  const who = (pl.who ?? []).filter(w => !lived.has(w.person) || w.what.some(k => k !== 'ev_residence' && k !== 'pp_born')), mentions = pl.mentions ?? [], nearby = pl.nearby ?? []
  const km = new Map(nearby.map(n => [n.place, n.km]))
  return <>
    {who.length > 0 && <section className="card" data-note-where={t('nw_place_people')}>
      <h2><Icon name="fam" />{t('place_people')} <span className="count">{who.length}</span></h2>
      <ul className="plist">{who.map(w =>
        <li key={w.person}><PersonLink id={w.person} ix={ix} /><WhoWhat w={w} /></li>)}</ul>
    </section>}
    {mentions.length > 0 && <section className="card" data-note-where={t('nw_mentions')}>
      <h2><Icon name="fam" />{t('place_mentions')} <span className="count">{mentions.length}</span></h2>
      <ul className="plain columns">{mentions.map(id => <li key={id}><PersonLink id={id} ix={ix} /></li>)}</ul>
    </section>}
    {(pl.inside ?? []).length > 0 && <section className="card">
      <h2><Icon name="place" />{t('place_inside')} <span className="count">{pl.inside!.length}</span></h2>
      <PlaceList ids={pl.inside!} ix={ix} /></section>}
    {nearby.length > 0 && <section className="card">
      <h2><Icon name="map" />{t('place_nearby')}</h2>
      <PlaceList ids={nearby.map(n => n.place)} ix={ix} km={km} /></section>}
    {(pl.similar ?? []).length > 0 && <section className="card">
      <h2><Icon name="place" />{t('place_similar')}</h2>
      <PlaceList ids={pl.similar!} ix={ix} /></section>}
  </>
}
