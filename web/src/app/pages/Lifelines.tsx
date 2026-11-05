// Линии жизни нескольких людей на одной шкале лет (/<язык>/lifelines?p=slug1,slug2): у всех годы идут параллельно —
// одна дата на одной вертикали, мышь показывает год сразу у всех. Полоса человека раскрашена государствами, в которых он
// тогда жил («Места и эпохи»), точки — события его линии жизни; под шкалой — все события одним списком по годам.
import {useEffect, useMemo, useRef, useState} from 'react'
import {shallowEqual} from 'react-redux'
import {useSearchParams} from 'react-router'
import type {GDate, LangText, PersonFile} from '../../data/schema.gen'
import {Icon} from '../../components/Icon'
import {matchesName, nameRank, queryWords} from '../../nameSearch'
import {api} from '../api'
import {dateIn, nameIn, useLang, useT} from '../i18n'
import {Status} from '../Layout'
import {Md} from '../Md'
import {useAppDispatch, useAppSelector} from '../store'
import {type IndexPerson, type Lookup, useIndex} from '../useIndex'
import {yearOf} from '../timeline'
import {lifelineRows} from './PersonParts'
import {PersonLink} from './PersonPage'

const PX = 11                  // пикселей на год
// колонка с именами: на телефоне — уже, чтобы шкале осталось место (ширина телефона — как $phone в _mixins.scss)
const LABEL = typeof matchMedia !== 'undefined' && matchMedia('(max-width: 700px)').matches ? 112 : 190
const COLORS = ['#8c4f2b', '#4d6f9c', '#a2536f', '#3f7f5f', '#b07d12', '#6a5acd', '#c0392b', '#2c7a7b']
const STATE_COLORS = ['#e8c8b0', '#bcd0e6', '#e6bfd0', '#c6e0c8', '#efe0a8', '#d4ccef', '#f0c2bb', '#bfe2e2', '#ddd5c9', '#d9e5b3']
const WARS = [{from: 1914, to: 1918, key: 'll_ww1'}, {from: 1939, to: 1945, key: 'll_ww2'}]
const THIS_YEAR = new Date().getFullYear()

// цвет государства — по смыслу, одинаковый у всех людей и на всех шкалах; остальные — по имени из запасных
const STATE_BY_WORD: [RegExp, string][] = [[/оккупац|войн/i, '#f0c2bb'], [/Польш/, '#d4ccef'], [/Российская империя/, '#c6e0c8'],
  [/СССР|ССР|РСФСР|Советская/, '#ddd5c9'], [/Беларусь/, '#bcd0e6'], [/Аргентин/, '#bfe2e2'], [/Парагвай/, '#efe0a8'],
  [/Литв|Латви/, '#d9e5b3'], [/Украин/, '#f3dca0'], [/Германи|Пруссия/, '#e6bfd0']]
const stateColor = (label: string) => STATE_BY_WORD.find(([rx]) => rx.test(label))?.[1]
  ?? STATE_COLORS[[...label].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7) % STATE_COLORS.length]

interface Ev { x: number; when: string; text: string; person: number; memory?: boolean }  // memory — «Память», после смерти
type Range = [number, number]  // годы включительно: [1936, 1945]
/** Блоки списка «По годам»: год и события в нём, по порядку */
type Group = [number, Ev[]]
interface Lane { p: PersonFile; from: number; to: number; dashedEnd: boolean; events: Ev[]; stays: {from: number; to: number; state?: LangText}[]
  after?: number }  // последний год «Памяти» — пунктир за концом жизни до него

/** Скачать людей (data/people/<id>.json) — по одному запросу на человека, как страница человека */
function usePeople(ids: string[], v: string): (PersonFile | undefined)[] {
  const dispatch = useAppDispatch()
  const key = ids.join()
  useEffect(() => {
    const subs = ids.map(id => dispatch(api.endpoints.person.initiate({id, v})))
    return () => subs.forEach(s => s.unsubscribe())
  }, [key, v, dispatch])  // eslint-disable-line react-hooks/exhaustive-deps
  return useAppSelector(s => ids.map(id => api.endpoints.person.select({id, v})(s).data), shallowEqual)
}

function lane(p: PersonFile, idx: number, entry: IndexPerson | undefined, lang: ReturnType<typeof useLang>): Lane {
  const events: Ev[] = []
  const add = (d: GDate | undefined, text: string, memory?: boolean) => {
    if (d) events.push({x: yearOf(d), when: dateIn(d, lang), text, person: idx, ...(memory ? {memory} : {})}) }
  for (const {row, date} of p.biography ? lifelineRows(p.biography, lang) : []) add(date, row.text)
  if (!events.length) { add(p.born?.date, '★'); add(p.died?.date, '✝') }  // нет линии жизни — хотя бы рождение и смерть
  const xs = events.map(e => e.x)
  for (const {row, date} of p.biography ? lifelineRows(p.biography, lang, 'memory') : []) add(date, row.text, true)
  events.sort((a, b) => a.x - b.x)
  const mem = events.filter(e => e.memory).map(e => e.x)
  const born = p.born?.date ? yearOf(p.born.date) : undefined, died = p.died?.date ? yearOf(p.died.date) : undefined
  const alive = !!entry && !entry.life.includes('–')
  const from = born ?? (xs.length ? Math.min(...xs) : THIS_YEAR)
  const last = xs.length ? Math.max(...xs) : from
  const to = died ?? (alive ? THIS_YEAR + 0.5 : Math.max(last, from) + 0.5)
  return {p, from, to, dashedEnd: !died && !alive, events, ...(mem.length ? {after: Math.max(...mem)} : {}),
    stays: (p.stays ?? []).map(s => ({from: s.from, to: s.to + 1, state: s.state}))}
}

export function Lifelines() {
  const t = useT(), {ix} = useIndex()
  const [params, setParams] = useSearchParams()
  const slugs = (params.get('p') ?? '').split(',').filter(Boolean)
  const ids = ix ? slugs.flatMap(s => { const x = ix.personBySlug.get(s); return x ? [x.id] : [] }) : []
  const people = usePeople(ids, ix?.index.built ?? '')
  useEffect(() => { document.title = `${t('nav_lifelines')} — ${t('site')}` }, [t])
  const setIds = (next: string[]) => {
    const q = new URLSearchParams(params)
    const ss = [...new Set(next)].flatMap(id => { const x = ix?.people.get(id); return x ? [x.slug] : [] })
    if (ss.length) q.set('p', ss.join(',')); else q.delete('p')
    setParams(q, {replace: true})
  }
  if (!ix) return <Status state="loading" />
  return <Compare ids={ids} people={people} ix={ix} setIds={setIds} />
}

function Compare({ids, people, ix, setIds}: {ids: string[]; people: (PersonFile | undefined)[]; ix: Lookup; setIds: (ids: string[]) => void}) {
  const t = useT(), lang = useLang()
  const lanes = useMemo(() => people.flatMap((p, i) => (p ? [lane(p, i, ix.people.get(p.id), lang)] : [])), [people, ix, lang])
  const groups = useMemo(() => {
    const out: Group[] = []
    for (const e of lanes.flatMap(l => l.events).sort((a, b) => a.x - b.x || a.person - b.person)) {
      const y = Math.floor(e.x)
      if (out.at(-1)?.[0] === y) out.at(-1)![1].push(e); else out.push([y, [e]])
    }
    return out
  }, [lanes])
  const [range, setRange] = useState<Range | null>(null)  // выбранный промежуток — список ниже показывает только его
  const [hot, setHot] = useState<number | null>(null)     // блок под мышью — подсвечен и на шкале, и в списке
  useEffect(() => setRange(null), [ids.join()])  // eslint-disable-line react-hooks/exhaustive-deps
  return <>
    <h1 className="page-title">{t('nav_lifelines')}</h1>
    <Picker ids={ids} ix={ix} onChange={setIds} />
    <p className="note">{t('ll_intro')}</p>
    {ids.length === 0 ? <section className="card status">{t('ll_empty')}</section>
      : lanes.length < ids.length ? <Status state="loading" />
      : <><Chart lanes={lanes} ix={ix} groups={groups} range={range} setRange={setRange} hot={hot} setHot={setHot} />
        <ByYear lanes={lanes} ix={ix} groups={groups} range={range} setRange={setRange} hot={hot} /></>}
  </>
}

/** Кого сравниваем: цветные метки, поиск по имени, «добавить родителей / супругов / детей / братьев и сестёр» */
function Picker({ids, ix, onChange}: {ids: string[]; ix: Lookup; onChange: (ids: string[]) => void}) {
  const t = useT(), lang = useLang()
  const [q, setQ] = useState('')
  const [cur, setCur] = useState(0)  // выбранная стрелками строка списка
  const found = useMemo(() => {
    const s = q.trim().toLowerCase()
    if (!s) return []
    // выше — у кого с запроса начинается имя или фамилия, потом — где он внутри слова
    const words = queryWords(s)   // слова — в любом порядке: «Ясенев Иван» = «Иван Ясенев»
    return ix.index.people.filter(p => !p.unknown && !ids.includes(p.id) && matchesName(Object.values(p.names), words))
      .map(p => ({p, r: nameRank(Object.values(p.names), words)})).sort((a, b) => a.r - b.r).slice(0, 8).map(x => x.p)
  }, [q, ix, ids])
  const add = (p: IndexPerson) => { onChange([...ids, p.id]); setQ(''); setCur(0) }
  const kin = (pick: (p: IndexPerson) => string[]) => onChange([...ids, ...ids.flatMap(id => pick(ix.people.get(id)!))])
  const siblings = (p: IndexPerson) => p.parents.flatMap(par => ix.people.get(par)?.children ?? [])
  // телефон: поле — к верху экрана, чтобы список подсказок поместился над клавиатурой
  const toTop = (el: HTMLElement) => {
    if (window.matchMedia('(max-width: 700px)').matches) setTimeout(() => el.scrollIntoView({block: 'start', behavior: 'smooth'}), 300)
  }
  return <section className="card ll-pick">
    <div className="ll-search">
      <input className="ll-input" placeholder={t('ll_add_ph')} value={q} autoComplete="off" enterKeyHint="search"
        role="combobox" aria-expanded={found.length > 0} aria-controls="ll-found"
        aria-activedescendant={found[cur] ? `ll-f-${found[cur].id}` : undefined}
        onFocus={e => toTop(e.currentTarget)}
        onChange={e => { setQ(e.target.value); setCur(0) }}
        onKeyDown={e => {
          const go = (i: number) => { setCur(i); document.getElementById(`ll-f-${found[i].id}`)?.scrollIntoView({block: 'nearest'}); e.preventDefault() }
          if (e.key === 'ArrowDown' && found.length) go(Math.min(cur + 1, found.length - 1))
          else if (e.key === 'ArrowUp' && found.length) go(Math.max(cur - 1, 0))
          else if (e.key === 'Enter' && found[cur]) { add(found[cur]); e.preventDefault() }
          else if (e.key === 'Escape') setQ('')
        }} />
      {found.length > 0 && <ul className="ll-found" id="ll-found" role="listbox">{found.map((p, i) =>
        <li key={p.id} id={`ll-f-${p.id}`} role="option" aria-selected={i === cur} className={i === cur ? 'cur' : undefined}
          onMouseEnter={() => setCur(i)}>
          <button onMouseDown={e => e.preventDefault()} onClick={() => add(p)}>{nameIn(p.names, lang)} <span className="life">{p.life}</span></button></li>)}</ul>}
    </div>
    {ids.length > 0 && <div className="chips ll-chosen">
      {ids.map((id, i) => { const x = ix.people.get(id)!
        return <span key={id} className="chip ll-chip" style={{borderColor: COLORS[i % COLORS.length]}}>
          <i style={{background: COLORS[i % COLORS.length]}} />{nameIn(x.names, lang)}
          <button aria-label="×" onClick={() => onChange(ids.filter(y => y !== id))}>×</button></span> })}
      <button className="linkbtn" onClick={() => onChange([])}>{t('ll_clear')}</button>
    </div>}
    {ids.length > 0 && <div className="ll-kin">{t('ll_add')}{' '}
      <button className="chip-btn" onClick={() => kin(p => p.parents)}>{t('ll_parents')}</button>
      <button className="chip-btn" onClick={() => kin(p => p.spouses)}>{t('ll_spouses')}</button>
      <button className="chip-btn" onClick={() => kin(p => p.children)}>{t('ll_children')}</button>
      <button className="chip-btn" onClick={() => kin(siblings)}>{t('ll_siblings')}</button>
    </div>}
  </section>
}

/** Шкала: у всех одна ось лет; вертикальная линия под мышью — один год у всех сразу */
/** Блок списка, в который попадает год: от события до следующего события (год — номер блока) */
function blockOf(groups: Group[], y: number): Range | null {
  let i = -1
  for (let k = 0; k < groups.length && groups[k][0] <= y; k++) i = k
  return i < 0 ? null : [groups[i][0], i + 1 < groups.length ? groups[i + 1][0] - 1 : groups[i][0]]
}

interface Pick { groups: Group[]; range: Range | null; setRange: (r: Range | null) => void; hot: number | null }

function Chart({lanes, ix, groups, range, setRange, hot, setHot}: {lanes: Lane[]; ix: Lookup; setHot: (y: number | null) => void} & Pick) {
  const t = useT(), lang = useLang()
  const y0 = Math.floor(Math.min(...lanes.map(l => Math.min(l.from, ...l.stays.map(s => s.from)))) / 10) * 10 - 5
  const y1 = Math.min(Math.ceil(Math.max(...lanes.map(l => Math.max(l.to, l.after ?? l.to, ...l.stays.map(s => s.to)))) / 10) * 10 + 5, THIS_YEAR + 5)
  const width = (y1 - y0) * PX, X = (y: number) => (y - y0) * PX
  const [cursor, setCursor] = useState<number | null>(null)
  const [drag, setDrag] = useState<{from: number; px: number; to?: number} | null>(null)  // протяжка: откуда и докуда
  const area = useRef<HTMLDivElement>(null)
  const decades: number[] = []
  for (let y = Math.ceil(y0 / 10) * 10; y <= y1; y += 10) decades.push(y)
  // легенда — по времени: какое государство встретилось раньше, то и первым
  const states = new Map<string, {s: LangText; from: number}>()
  lanes.forEach(l => l.stays.forEach(s => {
    if (s.state && (states.get(s.state.ru)?.from ?? Infinity) > s.from) states.set(s.state.ru, {s: s.state, from: s.from})
  }))
  const legend = [...states.values()].sort((a, b) => a.from - b.from).map(x => x.s)
  const yearAt = (clientX: number) => {
    const y = y0 + (clientX - area.current!.getBoundingClientRect().left) / PX
    return y >= y0 && y <= y1 ? y : null
  }
  const block = cursor !== null ? blockOf(groups, cursor) : null
  const move = (e: React.PointerEvent) => {
    const y = yearAt(e.clientX)
    setCursor(y)
    const b = y !== null ? blockOf(groups, y) : null
    setHot(b ? b[0] : null)
    if (drag && y !== null && Math.abs(e.clientX - drag.px) > 6) setDrag({...drag, to: y})
  }
  const down = (e: React.PointerEvent) => {
    if (e.button !== 0 || (e.target as HTMLElement).closest('a')) return
    const y = yearAt(e.clientX)
    if (y !== null) setDrag({from: y, px: e.clientX})
  }
  const up = () => {
    if (!drag) return
    if (drag.to !== undefined) {  // провели — свой промежуток, целыми годами
      const a = Math.floor(Math.min(drag.from, drag.to)), b = Math.floor(Math.max(drag.from, drag.to))
      setRange([a, b])
    } else {                      // нажали — блок до следующего события; второе нажатие по нему же — снять
      const b = blockOf(groups, drag.from)
      setRange(b && !(range && range[0] === b[0] && range[1] === b[1]) ? b : null)
    }
    setDrag(null)
  }
  const shown: Range | null = drag?.to !== undefined
    ? [Math.floor(Math.min(drag.from, drag.to)), Math.floor(Math.max(drag.from, drag.to))] : range
  const band = (r: Range, cls: string) => <i className={cls} style={{left: X(r[0]), width: (r[1] + 1 - r[0]) * PX}} />
  const inShown = (x: number) => !shown || (x >= shown[0] && x < shown[1] + 1)
  return <section className="card ll-card">
    <div className="ll-scroll">
      <div className="ll-grid" style={{width: LABEL + width}}>
        <div className="ll-axis-row">
        <div className="ll-corner" style={{width: LABEL}} />
        <div className="ll-axis" style={{width}}>
          {WARS.filter(w => w.to > y0 && w.from < y1).map(w =>
            <span key={w.key} className="ll-war-label" style={{left: X(w.from), width: (w.to - w.from) * PX}}>{t(w.key)}</span>)}
          {decades.map(y => <span key={y} className="ll-tick" style={{left: X(y)}}>{y}</span>)}
        </div>
        </div>
        <div className={`ll-lanes${shown ? ' picked' : ''}`} onPointerMove={move} onPointerDown={down} onPointerUp={up}
          onPointerCancel={() => setDrag(null)} onPointerLeave={() => { setCursor(null); setHot(null); setDrag(null) }}>
          <div className="ll-overlay" ref={area} style={{left: LABEL, width}}>
            {decades.map(y => <i key={y} className="ll-line" style={{left: X(y)}} />)}
            {WARS.filter(w => w.to > y0 && w.from < y1).map(w => <i key={w.key} className="ll-war" style={{left: X(w.from), width: (w.to - w.from) * PX}} />)}
            {shown && band(shown, 'll-pick-band')}
            {block && !drag?.to && hot !== null && band(block, 'll-hot-band')}
            {cursor !== null && <i className="ll-cursor" style={{left: X(cursor)}}><b>{Math.floor(cursor)}</b></i>}
          </div>
          {lanes.map((l, i) => {
            const color = COLORS[i % COLORS.length]
            return <div key={l.p.id} className="ll-row">
              <div className="ll-name" style={{width: LABEL, borderLeftColor: color}}>
                <PersonLink id={l.p.id} ix={ix} color={color} />
              </div>
              <div className="ll-lane" style={{width}}>
                {l.stays.map((s, k) => <i key={k} className="ll-state" title={s.state ? nameIn(s.state, lang) : ''}
                  style={{left: X(s.from), width: Math.max((s.to - s.from) * PX, 2), background: s.state ? stateColor(s.state.ru) : '#eee'}} />)}
                <i className={`ll-bar${l.dashedEnd ? ' open' : ''}`} style={{left: X(l.from), width: Math.max((l.to - l.from) * PX, 4), background: color}} />
                {l.after !== undefined && l.after > l.to && <i className="ll-after" style={{left: X(l.to), width: (l.after - l.to) * PX, borderColor: color}} />}
                {l.events.map((e, k) => <i key={k} className={`ll-dot${e.memory ? ' memory' : ''}${inShown(e.x) ? '' : ' dim'}`} style={{left: X(e.x), borderColor: color}}
                  title={`${e.when} — ${e.text.replace(/[*`]/g, '').replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')}`} />)}
              </div>
            </div>
          })}
        </div>
      </div>
    </div>
    <p className="note ll-hint">{t('ll_pick_hint')}</p>
    {legend.length > 0 && <div className="ll-legend">{legend.map(s =>
      <span key={s.ru}><i style={{background: stateColor(s.ru)}} />{nameIn(s, lang)}</span>)}</div>}
  </section>
}

/** Все события выбранных людей одним списком по времени — чтобы читать параллельно */
function ByYear({lanes, ix, groups, range, setRange, hot}: {lanes: Lane[]; ix: Lookup} & Pick) {
  const t = useT()
  const years = range ? groups.filter(([y]) => y >= range[0] && y <= range[1]) : groups
  return <section className="card">
    <h2><Icon name="event" />{t('ll_by_year')}
      {range && <span className="chip ll-range">{range[0] === range[1] ? range[0] : `${range[0]}–${range[1]}`}
        <button aria-label={t('ll_show_all')} title={t('ll_show_all')} onClick={() => setRange(null)}>×</button></span>}</h2>
    <ul className="timeline ll-list">{years.map(([y, es]) => <li key={y} className={y === hot ? 'hot' : undefined}>
      <span className="date">{y}</span>
      <span>{es.map((e, k) => <div key={k} className="ll-item">
        <i style={{background: COLORS[e.person % COLORS.length]}} />
        <span><PersonLink id={lanes[e.person].p.id} ix={ix} short color={COLORS[e.person % COLORS.length]} />{e.when !== String(y) && <span className="life"> {e.when}</span>} — {e.memory && <span className="life">{t('memory')}: </span>}<Md text={e.text} /></span>
      </div>)}</span>
    </li>)}</ul>
  </section>
}
