// «Состояние дерева» и «Что нового» — data/progress.json (tools/scripts/site_data/progress.py).
// Состояние: по каждому роду — сколько людей, как глубоко известны предки, чем подтверждены их рождения и смерти.
// Лента: что поменялось в дереве по дням — сравнение снимков дерева, не тексты коммитов.
import {skipToken} from '@reduxjs/toolkit/query/react'
import {useEffect, useState} from 'react'
import {Link} from 'react-router'
import type {Branch, Change, Day} from '../../data/schema.gen'
import {Icon} from '../../components/Icon'
import {useProgressQuery} from '../api'
import {nameIn, useLang, useT} from '../i18n'
import {Status} from '../Layout'
import {useIndex, useLinks} from '../useIndex'
import {PersonLink} from './PersonPage'

const LOCALE = {ru: 'ru-RU', pl: 'pl-PL', es: 'es-ES', en: 'en-GB'} as const
const SHOWN = 12   // в группе дня больше — остальные под «ещё N»

function useProgress() {
  const {ix, isLoading} = useIndex()
  const q = useProgressQuery(ix ? ix.index.built : skipToken)
  return {ix, q, loading: isLoading || q.isLoading}
}

/** Имя рода на языке страницы — из index.json (branches) */
function useBranchName() {
  const lang = useLang(), t = useT(), {ix} = useIndex()
  return (key: string) => {
    if (key === 'Без ветки') return t('no_branch')
    const b = ix?.index.branches.find(x => x.key === key)
    return b ? nameIn(b.names, lang) : key
  }
}

/** Рост по дням — линия без осей: видно, где род рос, а где стоял */
function Sparkline({points}: {points: Branch['growth']}) {
  if (points.length < 2) return null
  const w = 240, h = 36, ys = points.map(p => p.people), lo = Math.min(...ys), hi = Math.max(...ys)
  const x = (i: number) => (i / (points.length - 1)) * w, y = (v: number) => hi === lo ? h / 2 : h - 2 - ((v - lo) / (hi - lo)) * (h - 4)
  return <svg className="spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true">
    <polyline points={points.map((p, i) => `${x(i)},${y(p.people)}`).join(' ')} />
  </svg>
}

/** Полоса «чем подтверждено»: документом / со слов семьи / нечем */
function DocsBar({d}: {d: Branch['docs']}) {
  const t = useT()
  if (!d.events) return null
  const pc = (n: number) => `${(n / d.events) * 100}%`
  return <div className="docs">
    <div className="bar" role="img" aria-label={`${t('stats_doc_record')} ${d.record}, ${t('stats_doc_family')} ${d.family}, ${t('stats_doc_none')} ${d.none}`}>
      <span className="rec" style={{width: pc(d.record)}} /><span className="fam" style={{width: pc(d.family)}} /><span className="none" style={{width: pc(d.none)}} />
    </div>
    <div className="legend"><span><i className="rec" />{t('stats_doc_record')} {d.record}</span>
      <span><i className="fam" />{t('stats_doc_family')} {d.family}</span>
      <span><i className="none" />{t('stats_doc_none')} {d.none}</span>
      <span className="life">{t('stats_of', d.events)}</span></div>
  </div>
}

export function ProgressPage() {
  const t = useT(), href = useLinks(), branch = useBranchName(), {ix, q, loading} = useProgress()
  useEffect(() => { document.title = `${t('stats_title')} — ${t('site')}` }, [t])
  if (loading) return <Status state="loading" />
  if (q.error && 'status' in q.error && q.error.status === 'not_found') return <Status state="not_found" />
  if (!q.data || !ix) return <Status state="error" />
  const {total, branches} = q.data
  return <>
    <section className="hero card"><div className="hero-text">
      <h1>{t('stats_title')}</h1>
      <div className="life big">{t('stats_card')}</div>
      <div className="life">{t('stats_total', total.people, total.bios, total.pics, total.facts)}</div>
      <p><Link to={href.at('/news')}><Icon name="history" /> {t('news_title')} →</Link></p>
    </div></section>
    <div className="stats-grid">{branches.map(b =>
      <section className="card stat" key={b.key}>
        <h2><Link to={href.at(`/people#${ix.index.branches.find(x => x.key === b.key)?.slug ?? ''}`)}>{branch(b.key)}</Link></h2>
        <div className="big-num">{b.people} <span className="life">{t('stats_people')}</span></div>
        <div className="life">{t('stats_marriage', b.by_marriage)}{b.week ? <> · <b className="up">{t('stats_week', b.week)}</b></> : null}</div>
        <Sparkline points={b.growth} />
        <table className="kv"><tbody>
          {b.root && <tr><th>{t('stats_root')}</th><td><PersonLink id={b.root} ix={ix} /></td></tr>}
          <tr><th>{t('stats_gen')}</th><td><b>{b.generations}</b> <span className="life">{t('stats_gen_note')}</span></td></tr>
          <tr><th>{t('stats_anc')}</th><td>{b.ancestors}</td></tr>
          {b.oldest && b.oldest.id !== b.root && <tr><th>{t('stats_oldest')}</th><td><PersonLink id={b.oldest.id} ix={ix} /></td></tr>}
          {b.deepest.length > 0 && <tr><th>{t('stats_deepest')}</th><td className="list">{b.deepest.map(id => <PersonLink key={id} id={id} ix={ix} />)}</td></tr>}
          <tr><th>{t('stats_bios')}</th><td>{b.bios}</td></tr>
          <tr><th>{t('stats_pics')}</th><td>{b.pics}</td></tr>
        </tbody></table>
        <h3>{t('stats_docs')}</h3>
        <DocsBar d={b.docs} />
      </section>)}
    </div>
    <p className="note">{t('stats_note')}</p>
  </>
}

/** Одна строка ленты: человек и что у него поменялось */
function ChangeRow({c}: {c: Change}) {
  const t = useT(), {ix} = useIndex()
  if (!ix) return null
  const links = (ids: string[]) => ids.filter(i => ix.people.has(i)).map(i => <PersonLink key={i} id={i} ix={ix} />)
  return <li>
    <PersonLink id={c.id} ix={ix} />
    <span className="chips">
      {c.new && <span className="chip ours">{t('news_new')}</span>}
      {c.life && <span className="chip">{t('news_life')}: {c.life[0] || '—'} → {c.life[1] || '—'}</span>}
      {c.facts && <span className="chip">{t('news_facts', c.facts)}</span>}
      {c.bio && <span className="chip">{t(c.bio === 'new' ? 'news_bio_new' : 'news_bio_edit')}</span>}
      {c.pics && <span className="chip">{t('news_pics', c.pics)}</span>}
    </span>
    {c.parents && c.parents.some(i => ix.people.has(i)) && <span className="rel">{t('news_parents')}: {links(c.parents)}</span>}
    {c.spouses && c.spouses.some(i => ix.people.has(i)) && <span className="rel">{t('news_spouses')}: {links(c.spouses)}</span>}
  </li>
}

function DayCard({day, only, open}: {day: Day; only: string; open: boolean}) {
  const t = useT(), lang = useLang(), branch = useBranchName(), {ix} = useIndex()
  if (!ix) return null
  const groups = new Map<string, Change[]>()
  for (const c of day.items) {
    const p = ix.people.get(c.id)
    if (!p) continue   // карточку потом слили или убрали
    const key = p.lineage?.[0] ?? 'Без ветки'
    if (only && !p.lineage?.includes(only)) continue
    groups.set(key, [...groups.get(key) ?? [], c])
  }
  if (!groups.size) return null
  const added = day.items.filter(c => c.new && ix.people.has(c.id)).length
  const when = new Date(day.date + 'T12:00:00').toLocaleDateString(LOCALE[lang], {weekday: 'short', day: 'numeric', month: 'long'})
  return <details className="card day" open={open}>
    <summary><h2>{when}</h2>
      <span className="life">{t('news_day', added, day.people)}{day.removed ? ` · ${t('news_removed', day.removed)}` : ''}</span></summary>
    {[...groups].map(([key, items]) => <div key={key} className="day-branch">
      <h3>{branch(key)} <span className="count">{items.length}</span></h3>
      <ul className="changes">{items.slice(0, SHOWN).map(c => <ChangeRow key={c.id} c={c} />)}</ul>
      {items.length > SHOWN && <details className="more"><summary>{t('news_more', items.length - SHOWN)}</summary>
        <ul className="changes">{items.slice(SHOWN).map(c => <ChangeRow key={c.id} c={c} />)}</ul></details>}
    </div>)}
  </details>
}

export function NewsPage() {
  const t = useT(), href = useLinks(), branch = useBranchName(), {ix, q, loading} = useProgress()
  const [only, setOnly] = useState('')
  useEffect(() => { document.title = `${t('news_title')} — ${t('site')}` }, [t])
  if (loading) return <Status state="loading" />
  if (q.error && 'status' in q.error && q.error.status === 'not_found') return <Status state="not_found" />
  if (!q.data || !ix) return <Status state="error" />
  return <>
    <section className="hero card"><div className="hero-text">
      <h1>{t('news_title')}</h1>
      <div className="life big">{t('news_intro')}</div>
      <p><Link to={href.at('/progress')}><Icon name="stats" /> {t('stats_title')} →</Link></p>
      <label className="life">{t('news_filter')}{' '}
        <select value={only} onChange={e => setOnly(e.target.value)}>
          <option value="">{t('news_all')}</option>
          {q.data.branches.map(b => <option key={b.key} value={b.key}>{branch(b.key)}</option>)}
        </select></label>
    </div></section>
    {q.data.days.length ? q.data.days.map((d, i) => <DayCard key={d.date} day={d} only={only} open={i < 3} />)
      : <p className="note">{t('news_empty')}</p>}
  </>
}
