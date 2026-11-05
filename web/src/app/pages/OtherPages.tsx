// Место, источник, заметка проекта, «Что ещё искать», «Сверка», «нет такой страницы».
import {skipToken} from '@reduxjs/toolkit/query'
import {useEffect} from 'react'
import {Link, Navigate, useNavigate, useParams} from 'react-router'
import {useDocQuery, usePlaceQuery, useResearchQuery, useReviewQuery, useSourceQuery} from '../api'
import {dateIn, nameIn, titleIn, useLang, useT} from '../i18n'
import {Status} from '../Layout'
import {cleanSlug, useIndex, useLinks} from '../useIndex'
import {Icon} from '../../components/Icon'
import {BioMd} from '../BioMd'
import {Md} from '../Md'
import type {ReviewFile} from '../../data/schema.gen'
import {PlacePhotos} from '../PlacePhotos'
import {PlaceAbout, PlaceLinks, PlaceText} from '../PlaceParts'
import {HouseChips, HouseResidents} from '../Houses'
import {PersonLink} from './PersonPage'
import {Pin} from '../notes/Pin'
import {NoteScope} from '../notes/scope'

export function PlacePage() {
  const href = useLinks()
  const t = useT(), lang = useLang(), {slug} = useParams(), navigate = useNavigate()
  const clean = cleanSlug(slug)
  useEffect(() => { if (clean !== slug) navigate(href.place(clean), {replace: true}) }, [clean, slug, navigate])
  const {ix, isLoading} = useIndex()
  const entry = ix?.placeBySlug.get(clean)
  const q = usePlaceQuery(entry && ix ? {id: entry.id, v: ix.index.built} : skipToken)
  if (isLoading || q.isLoading) return <Status state="loading" />
  if (!entry) return <Status state="not_found" />
  if (!q.data || !ix) return <Status state="error" />
  const pl = q.data, parent = pl.parent ? ix.places.get(pl.parent) : undefined
  const from = pl.states_from ? ix.places.get(pl.states_from) : undefined
  return <NoteScope subject={{type: 'place', id: pl.id, name: pl.names.ru, path: `/places/${pl.slug}`}}>
    <section className="hero card"><div className="hero-text">
      <h1>{nameIn(pl.names, lang)}<Pin kind="whole" title={t('n_pin_place')} /></h1>
      {parent && <div className="life big"><Link to={href.place(parent.slug)}>{nameIn(parent.names, lang)}</Link></div>}
      <HouseChips pl={pl} />
    </div>
    {(entry.lat !== undefined || pl.house) && <Link className="btn tonal" to={href.at(`${pl.house ? '/map/houses' : '/map'}#${pl.slug}`)}><Icon name="map" />{t('show_map')}</Link>}
    </section>
    <PlaceAbout pl={pl} />
    <HouseResidents pl={pl} ix={ix} />
    {pl.states && pl.states.length > 0 && <section className="card" data-note-where={t('nw_states')}>
      <h2>{t('place_states')}</h2>
      {from && <p className="note">{t('states_from')} <Link to={href.place(from.slug)}>{nameIn(from.names, lang)}</Link></p>}
      <ul className="plain">{pl.states.map((s, i) =>
        <li key={i}><span className="date">{dateIn(s.date, lang)}</span> — {s.main ? <b>{nameIn(s.state, lang)}</b> : nameIn(s.state, lang)}
          <Pin kind="state" where={from ? t('nw_states_from', from.names.ru) : t('nw_states')} text={`${s.date.ru} — ${s.state.ru}`} /></li>)}</ul>
    </section>}
    <PlacePhotos placeId={pl.id} />
    <PlaceText pl={pl} />
    <PlaceLinks pl={pl} ix={ix} />
  </NoteScope>
}

export function SourcePage() {
  const t = useT(), lang = useLang(), {slug} = useParams()
  const {ix, isLoading} = useIndex()
  const entry = ix?.sourceBySlug.get(cleanSlug(slug))
  const q = useSourceQuery(entry && ix ? {id: entry.id, v: ix.index.built} : skipToken)
  if (isLoading || q.isLoading) return <Status state="loading" />
  if (!entry) return <Status state="not_found" />
  if (!q.data || !ix) return <Status state="error" />
  const s = q.data
  return <NoteScope subject={{type: 'source', id: s.id, name: s.title, path: `/sources/${s.slug}`}}>
    <section className="hero card"><div className="hero-text">
      <h1>{titleIn(s, lang)}</h1>
      <div className="life big">{t(`prov_${s.provenance}`)}{s.author && ` · ${s.author}`}{s.repository && ` · ${s.repository}`}</div>
    </div></section>
    {s.people.length > 0 && <section className="card">
      <h2>{t('src_people')}</h2>
      <ul className="plain columns">{s.people.map(id => <li key={id}><PersonLink id={id} ix={ix} /></li>)}</ul>
    </section>}
    {s.media && s.media.some(m => !m.private) && <section className="card"><div className="ph-grid">{s.media.filter(m => !m.private).map(m =>
      <a key={m.url} href={m.url} className="ph-card"><img loading="lazy" src={m.url} alt="" /></a>)}</div></section>}
    {s.audio && <section className="card"><p className="note">{t('audio_private')}</p></section>}
    {s.md && <section className="card prose" data-note-where={t('nw_source_text')}><BioMd text={s.md} /></section>}
  </NoteScope>
}

const DOC_ID = /^[0-9a-f]{10}$/

/** Заметка проекта (data/docs/<номер>.json): расшифровка, полный текст находки, документ человека — то, на что есть
 *  ссылка в текстах сайта. Номер — тот же, что у прежней страницы docs/<номер>.html: старые ссылки открывают её же, а
 *  старый адрес источника или биографии (goto) ведёт на их нынешнюю страницу. Текст — по-русски. */
export function DocPage() {
  const t = useT(), lang = useLang(), href = useLinks(), {id} = useParams()
  const clean = cleanSlug(id), ok = DOC_ID.test(clean)
  const {ix, isLoading} = useIndex()
  const q = useDocQuery(ok && ix ? {id: clean, v: ix.index.built} : skipToken)
  const d = q.data
  useEffect(() => { if (d?.title) document.title = `${d.title} — ${t('site')}` }, [d, t])
  if (isLoading || q.isLoading) return <Status state="loading" />
  if (!ok || (q.error && 'status' in q.error && q.error.status === 'not_found')) return <Status state="not_found" />
  if (!d || !ix) return <Status state="error" />
  if (d.goto) {
    const to = d.goto.kind === 'person' ? ix.people.get(d.goto.id) : ix.sources.get(d.goto.id)
    if (!to) return <Status state="not_found" />
    return <Navigate replace to={d.goto.kind === 'person' ? href.person(to.slug) : href.source(to.slug)} />
  }
  const meta = [d.path, ...Object.values(d.meta ?? {})].filter(Boolean).join(' · ')
  return <NoteScope subject={{type: 'source', id: `doc:${d.id}`, name: `${d.title} (${d.path ?? ''})`, path: `/docs/${d.id}`}}>
    <section className="hero card doc"><div className="hero-text">
      <h1>{d.title}</h1>
      {meta && <div className="life">{meta}</div>}
    </div></section>
    {lang !== 'ru' && <p className="note">{t('ru_note')}</p>}
    {d.people && d.people.length > 0 && <section className="card">
      <h2><Icon name="fam" />{t('about_whom')}</h2>
      <ul className="plain columns">{d.people.map(pid => <li key={pid}><PersonLink id={pid} ix={ix} /></li>)}</ul>
    </section>}
    {((d.media ?? []).some(m => !m.private) || (d.files ?? []).length > 0) && <section className="card">
      {(d.media ?? []).some(m => !m.private) && <div className="ph-grid">{(d.media ?? []).filter(m => !m.private).map(m =>
        <a key={m.url} href={m.url} className="ph-card"><img loading="lazy" src={m.url} alt="" /></a>)}</div>}
      {(d.files ?? []).length > 0 && <ul>{(d.files ?? []).map(f => <li key={f.url}><a href={f.url} target="_blank" rel="noopener">{f.name}</a></li>)}</ul>}
    </section>}
    {d.audio && <section className="card"><p className="note">{t('audio_private')}</p></section>}
    {d.md && <section className="card prose"><BioMd text={d.md} /></section>}
  </NoteScope>
}

/** «Что ещё искать» — план поиска по предкам (data/research.json из <папка поиска>/ПОИСК_ДАЛЬШЕ.md). Текст — по-русски. */
export function ResearchPage() {
  const t = useT(), lang = useLang(), {ix, isLoading} = useIndex()
  useEffect(() => { document.title = `${t('research_title')} — ${t('site')}` }, [t])
  const q = useResearchQuery(ix ? ix.index.built : skipToken)
  if (isLoading || q.isLoading) return <Status state="loading" />
  if (q.error && 'status' in q.error && q.error.status === 'not_found') return <Status state="not_found" />
  if (!q.data) return <Status state="error" />
  const r = q.data
  return <NoteScope subject={{type: 'source', id: 'research', name: `${t('research_title')} (ПОИСК_ДАЛЬШЕ.md)`, path: '/sources/next'}}>
    <section className="hero card"><div className="hero-text">
      <h1>{t('research_title')}</h1>
      <div className="life big">{t('research_card')}</div>
      {r.updated && <div className="life">{t('research_updated')}: {r.updated.split('-').reverse().join('.')}</div>}
    </div></section>
    {lang !== 'ru' && <p className="note">{t('ru_note')}</p>}
    <section className="card prose" data-note-where={t('nw_research')}><BioMd text={r.md} /></section>
  </NoteScope>
}

/** «Сверка»: пары карточек, которые, возможно, один человек или родня, — отмеченные в карточках (maybe_*) и найденные
 *  скриптом (possible.auto). Карточки рядом и команды решений: сайт сам ничего не меняет. */
export function ReviewPage() {
  const t = useT(), lang = useLang(), {ix, isLoading} = useIndex(), href = useLinks()
  useEffect(() => { document.title = `${t('review_title')} — ${t('site')}` }, [t])
  const q = useReviewQuery(ix ? ix.index.built : skipToken)
  if (isLoading || q.isLoading) return <Status state="loading" />
  if (!q.data || !ix) return <Status state="error" />
  const what = (p: ReviewFile['pairs'][number]) => p.type === 'same' ? t('maybe_same')
    : !p.relation || p.relation === 'kin' ? t('maybe_kin')
    : t(`maybe_${p.relation}_${ix.people.get(p.b.person)?.sex === 'F' ? 'f' : 'm'}`)
  const Side = ({s}: {s: ReviewFile['pairs'][number]['a']}) => {
    const place = (id?: string) => { const x = id ? ix.places.get(id) : undefined; return x ? <Link to={href.place(x.slug)}>{nameIn(x.names, lang)}</Link> : null }
    return <div className="review-side">
      <PersonLink id={s.person} ix={ix} />
      <table className="kv"><tbody>
        {(s.born || s.birth_place) && <tr><th>{t('ev_birth')}</th><td>{s.born && dateIn(s.born, lang)} {place(s.birth_place)}</td></tr>}
        {(s.died || s.death_place) && <tr><th>{t('ev_death')}</th><td>{s.died && dateIn(s.died, lang)} {place(s.death_place)}</td></tr>}
        {s.parents.length > 0 && <tr><th>{t('review_parents')}</th><td className="list">{s.parents.map(id => <PersonLink key={id} id={id} ix={ix} />)}</td></tr>}
        <tr><th>{t('nav_sources')}</th><td>{s.sources}</td></tr>
      </tbody></table>
    </div>
  }
  const group = (src: 'marked' | 'auto') => q.data!.pairs.filter(p => p.source === src && ix.people.has(p.a.person) && ix.people.has(p.b.person))
  const Pairs = ({src}: {src: 'marked' | 'auto'}) => <>{group(src).map(p =>
    <section className="card review-pair" key={p.a.person + p.b.person}>
      <h3>{what(p)}</h3>
      <div className="review-sides"><Side s={p.a} /><Side s={p.b} /></div>
      {p.reason && <div className="reasoning"><b>{t('maybe_why')}:</b> <Md text={p.reason} /></div>}
      {p.why && <div className="reasoning"><b>{t('review_why')}:</b> {p.why.join(', ')}</div>}
      <details className="review-cmd"><summary>{t('review_decide')}</summary>
        {(['mark', 'same', 'yes', 'no'] as const).map(k => p.commands[k] &&
          <p key={k}><b>{t(`review_${k}`)}</b><br /><code>{p.commands[k]}</code></p>)}
      </details>
    </section>)}</>
  return <>
    <section className="hero card"><div className="hero-text">
      <h1>{t('review_title')}</h1>
      <div className="life big">{t('review_card')}</div>
      <div className="life">{t('review_ruled_out')}: {q.data.ruled_out}</div>
    </div></section>
    <h2 className="page-title">{t('review_marked')} <span className="count">{group('marked').length}</span></h2>
    <Pairs src="marked" />
    <h2 className="page-title">{t('review_auto')} <span className="count">{group('auto').length}</span></h2>
    <p className="note">{t('review_auto_note')}</p>
    <Pairs src="auto" />
  </>
}

export const NotFound = () => <Status state="not_found" />
