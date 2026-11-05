// Главная, «Люди» по веткам рода, список источников — как на нынешнем сайте.
import {useEffect, useMemo, useState} from 'react'
import {Link} from 'react-router'
import type {Stats} from '../../data'
import {Icon} from '../../components/Icon'
import {matchesName, queryWords} from '../../nameSearch'
import {Badges} from '../Badges'
import {nameIn, titleIn, useLang, useT} from '../i18n'
import {Status} from '../Layout'
import {type IndexPerson, useIndex, useLinks} from '../useIndex'
import {PersonLink} from './PersonPage'

const TILES = [['nav_tree', 'card_tree', '/tree', 'tree'], ['nav_map', 'card_map', '/map', 'map'],
  ['nav_gallery', 'gal_tabs_intro', '/gallery', 'pics'], ['nav_people', 'card_people', '/people', 'fam'],
  ['nav_lifelines', 'll_compare', '/lifelines', 'event'],
  ['nav_sources', 'card_sources', '/sources', 'source'], ['news_title', 'news_card', '/news', 'history'],
  ['stats_title', 'stats_card', '/progress', 'stats']] as const

export function Home() {
  const href = useLinks()
  const t = useT(), lang = useLang(), {ix} = useIndex()
  useEffect(() => { document.title = t('home_title') }, [t])
  if (!ix) return <Status state="loading" />
  const people = ix.index.people, withBio = people.filter(p => (p.stats as Stats | undefined)?.bio).length
  return <>
    <section className="hero card home"><div className="hero-text">
      <h1>{t('home_title')}</h1>
      <p>{t('home_intro', people.length, ix.index.places.length)}</p>
      <p className="life">{t('home_bio', withBio, people.length)}</p>
    </div></section>
    <div className="tiles">{TILES.map(([k, sub, to, ic]) =>
      <Link key={k} className="tile" to={to}><Icon name={ic} /><b>{t(k)}</b>{t(sub)}</Link>)}</div>
    <section className="card"><h2><Icon name="fam" />{t('branches')}</h2>
      <ul className="branches">{ix.index.branches.map(b =>
        <li key={b.slug}><Link to={href.at(`/people#${b.slug}`)}>{b.key === 'Без ветки' ? t('no_branch') : nameIn(b.names, lang)}</Link>
          <span className="count">{b.people}</span></li>)}</ul>
    </section>
    <p className="note">{t('note_family')}</p>
  </>
}

const birth = (p: IndexPerson) => parseInt(p.life.replace(/^~/, ''), 10) || 9999

export function People() {
  const t = useT(), lang = useLang(), {ix} = useIndex()
  const [q, setQ] = useState('')
  useEffect(() => { document.title = `${t('nav_people')} — ${t('site')}` }, [t])
  // переход по ссылке «ветка» с главной: дождаться списка и прокрутить к ней
  useEffect(() => { if (ix && location.hash) document.getElementById(decodeURIComponent(location.hash.slice(1)))?.scrollIntoView() }, [ix])
  const groups = useMemo(() => {
    if (!ix) return []
    const words = queryWords(q)   // слова — в любом порядке: «Ясенев Иван» = «Иван Ясенев»
    const shown = ix.index.people.filter(p => !p.unknown && (!words.length || matchesName(Object.values(p.names), words)))
    return ix.index.branches.map(b => ({b, ps: shown.filter(p => (p.lineage?.length ? p.lineage : ['Без ветки']).includes(b.key))
      .sort((x, y) => birth(x) - birth(y) || nameIn(x.names, lang).localeCompare(nameIn(y.names, lang)))})).filter(g => g.ps.length)
  }, [ix, q, lang])
  if (!ix) return <Status state="loading" />
  return <>
    <h1 className="page-title">{t('nav_people')}</h1>
    <div className="search"><Icon name="person" /><input placeholder={t('people_search')} value={q} onChange={e => setQ(e.target.value)} autoComplete="off" /></div>
    {groups.map(({b, ps}) => <section key={b.slug} className="card" id={b.slug}>
      <h2><Icon name="fam" />{b.key === 'Без ветки' ? t('no_branch') : nameIn(b.names, lang)} <span className="count">{ps.length}</span></h2>
      <ul className="plist">{ps.map(p => <li key={p.id}><PersonLink id={p.id} ix={ix} /> <Badges st={p.stats as Stats | undefined} /></li>)}</ul>
    </section>)}
  </>
}

export function Sources() {
  const href = useLinks()
  const t = useT(), lang = useLang(), {ix} = useIndex()
  useEffect(() => { document.title = `${t('nav_sources')} — ${t('site')}` }, [t])
  if (!ix) return <Status state="loading" />
  const list = [...ix.index.sources].sort((a, b) => a.title.localeCompare(b.title, 'ru'))
  return <>
    <h1 className="page-title">{t('nav_sources')}</h1>
    <div className="tiles"><Link className="tile" to={href.at('/sources/next')}><Icon name="source" /><b>{t('research_title')} →</b>{t('research_card')}</Link>
      <Link className="tile" to={href.at('/sources/review')}><Icon name="fam" /><b>{t('review_title')} →</b>{t('review_card')}</Link></div>
    <section className="card"><ul className="plist">{list.map(s =>
      <li key={s.id}><Link to={href.source(s.slug)}>{titleIn(s, lang)}</Link> <span className="chip">{t(`prov_${s.provenance}`)}</span></li>)}</ul></section>
  </>
}
