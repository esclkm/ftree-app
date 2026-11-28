// «Исследовать» — на главной (/<язык>/?c=<центр>&p=<выбранный>): большой веер предков, нажатие выбирает человека — справа его
// карточка (кем приходится, годы и места, родители, супруги, дети — всё нажимается), под веером — ближняя родня
// выбранного и его семья на одной шкале. Адрес помнит центр и выбранного: ссылку можно отправить.
import {skipToken} from '@reduxjs/toolkit/query'
import {type ReactNode, useEffect, useMemo, useState} from 'react'
import {Link, Navigate, useLocation, useSearchParams} from 'react-router'
import type {LifeEvent} from '../../data/schema.gen'
import {Icon} from '../../components/Icon'
import {relation} from '../../kin'
import {PersonSearch} from '../../components/PersonSearch'
import {tree} from '../../data'
import {setMe, useMe} from '../../me'
import {usePersonQuery} from '../api'
import {AncestorFan} from '../charts/AncestorFan'
import {readGens, saveGens} from '../charts/Ancestors'
import {ancestorSlots, fanCount, genOf, yearsOf} from '../charts/ancestry'
import {FamilySpan} from '../charts/FamilySpan'
import '../charts/charts.scss'
import {dateIn, nameIn, useLang, useT} from '../i18n'
import {Status} from '../Layout'
import {type IndexPerson, type Lookup, useIndex, useLinks} from '../useIndex'

const RECENT = 8

/** Старый адрес /<язык>/explore — на главную с тем же центром и выбранным */
export function ToHome() {
  const {search} = useLocation()
  return <Navigate to={`..${search}`} relative="path" replace />
}

export function Explore() {
  const t = useT(), lang = useLang(), {ix, isLoading, isError} = useIndex(), me = useMe()
  const [params, setParams] = useSearchParams()
  const [gens, setGens] = useState(readGens)
  const [recent, setRecent] = useState<string[]>([])
  const [seen, setSeen] = useState<Set<string>>(() => new Set())
  const bySlug = (s: string | null) => (s && ix ? ix.personBySlug.get(s) : undefined)
  // центр — «я» из «Настроек» или тот, кого прислали ссылкой (?c=); иначе вместо веера — «Выберите себя»
  const center = bySlug(params.get('c')) ?? (ix && me ? ix.people.get(me) : undefined)
  const sel = bySlug(params.get('p')) ?? center
  useEffect(() => {
    if (!sel) return
    setRecent(r => [sel.id, ...r.filter(x => x !== sel.id)].slice(0, RECENT))
    setSeen(s => (s.has(sel.id) ? s : new Set(s).add(sel.id)))
  }, [sel?.id])  // eslint-disable-line react-hooks/exhaustive-deps
  const slots = useMemo(() => (ix && center ? ancestorSlots(ix, center.id, gens) : []), [ix, center?.id, gens])  // eslint-disable-line react-hooks/exhaustive-deps
  if (isError) return <Status state="error" />
  if (isLoading || !ix) return <Status state="loading" />
  if (!center || !sel) return <ChooseMe />

  const pick = (p: IndexPerson) => { const q = new URLSearchParams(params); q.set('p', p.slug); setParams(q, {replace: true}) }
  const recenter = (p: IndexPerson) => { const q = new URLSearchParams(params); q.set('c', p.slug); q.set('p', p.slug); setParams(q) }
  const {known} = fanCount(slots, gens)
  const inFan = new Set(slots.flatMap(p => (p ? [p.id] : [])))
  const seenInFan = [...seen].filter(id => inFan.has(id)).length
  const slot = slots.findIndex(p => p?.id === sel.id)
  const side = slot >= 2 ? ((slot >> (genOf(slot) - 1)) === 2 ? 'dad' : 'mom') : undefined

  return <div className="explore">
    <div className="ex-main">
      <section className="card ex-fan">
        <div className="anc-bar">
          <div><h2><Icon name="tree" />{t('ex_title')}</h2><p className="life">{t('ex_hint')}</p></div>
          <label className="life">{t('fan_gens')}{' '}
            <select value={gens} onChange={e => { const n = Number(e.target.value); setGens(n); saveGens(n) }}>
              {[3, 4, 5, 6, 7, 8].map(n => <option key={n} value={n}>{n}</option>)}
            </select></label>
        </div>
        <AncestorFan id={center.id} ix={ix} gens={gens} onPick={pick} selected={sel.id} />
        <div className="ex-nums">
          <span><b>{known + 1}</b> {t('ex_showing')}</span>
          <span className="hot"><b>{seenInFan}</b> {t('ex_seen')}</span>
          <span><b>{Math.max(0, known + 1 - seenInFan)}</b> {t('ex_left')}</span>
        </div>
        {recent.length > 1 && <div className="ex-recent"><span className="life">{t('ex_recent')}</span>
          {recent.map(id => { const p = ix.people.get(id); return p &&
            <button key={id} className={'ex-chip' + (id === sel.id ? ' on' : '')} onClick={() => pick(p)}>{nameIn(p.names, lang)}</button> })}
        </div>}
        <div className="ex-legend">
          <span><i className="dad" />{t('lg_dad')}</span><span><i className="mom" />{t('lg_mom')}</span>
          <span><i className="gap" />{t('lg_gap')}</span><span><i className="sel" />{t('lg_sel')}</span>
          <span><i className="full" />{t('lg_full')}</span>
        </div>
      </section>
      <Below sel={sel} ix={ix} pick={pick} />
    </div>
    <Preview key={sel.id} sel={sel} center={center} side={side} ix={ix} pick={pick} recenter={recenter} />
  </div>
}

/** «Кто вы?» — пока «я» не выбран: веер строится от вас, родство считается от вас */
function ChooseMe() {
  const t = useT(), people = tree()
  return <section className="card ex-choose">
    <h2><Icon name="person" />{t('ex_choose')}</h2>
    <p className="life">{t('ex_choose_hint')}</p>
    {people && <PersonSearch people={people} placeholder={t('set_me_find')} onPick={setMe} />}
  </section>
}

/** Карточка выбранного справа */
function Preview({sel, center, side, ix, pick, recenter}: {sel: IndexPerson; center: IndexPerson; side?: 'dad' | 'mom'; ix: Lookup
  pick: (p: IndexPerson) => void; recenter: (p: IndexPerson) => void}) {
  const t = useT(), lang = useLang(), href = useLinks()
  const q = usePersonQuery({id: sel.id, v: ix.index.built})
  const f = q.data
  const y = yearsOf(sel.life), female = sel.sex === 'F'
  const r = relation(center.id, sel.id)
  const rel = sel.id === center.id ? t('ex_self') : r?.term?.nom
  const people = (ids: string[]) => [...new Set(ids)].flatMap(id => { const p = ix.people.get(id); return p ? [p] : [] })
  const parents = people(sel.parents), spouses = people(sel.spouses), kids = people(sel.children)
  const st = sel.stats
  const Chips = ({xs}: {xs: IndexPerson[]}) => <div className="ex-chips">{xs.map(p =>
    <button key={p.id} className={`ex-chip ${p.sex === 'F' ? 'f' : 'm'}`} onClick={() => pick(p)}>
      <i />{nameIn(p.names, lang)}{p.life && <small> {p.life}</small>}</button>)}</div>
  const ev = (label: string, e?: LifeEvent) => {
    const place = e?.place ? ix.places.get(e.place) : undefined
    return <div className="ex-ev"><span className="life">{label}</span>
      <b>{e?.date ? dateIn(e.date, lang) : '—'}</b>
      {place && <Link to={href.place(place.slug)}>{nameIn(place.names, lang)}</Link>}</div>
  }
  return <aside className="card ex-side">
    <div className="ex-head">
      {sel.avatar ? <img className="ex-ava" src={sel.avatar} alt="" />
        : <span className={`ex-ava ph c${sel.color ?? 0}`}>{sel.initials ? nameIn(sel.initials, lang) : '?'}</span>}
      <div>
        <h2>{nameIn(sel.names, lang)}</h2>
        <div className="life">{[rel, side && t(side === 'dad' ? 'fan_dad' : 'fan_mom'), sel.life].filter(Boolean).join(' · ')}</div>
      </div>
    </div>
    {y.born !== undefined && y.died !== undefined && <p className="ex-age">{t(female ? 'ex_died_at_f' : 'ex_died_at_m', y.died - y.born)}</p>}
    <div className="ex-evs">
      {ev(t(female ? 'born_f' : 'born_m'), f?.born)}
      {spouses.length > 0 && <div className="ex-ev"><span className="life">{t('ex_married')}</span>
        {spouses.map(p => <button key={p.id} className="linkish" onClick={() => pick(p)}>{nameIn(p.names, lang)}</button>)}</div>}
      {ev(t(female ? 'died_f' : 'died_m'), f?.died)}
    </div>
    {parents.length > 0 && <><h3>{t('fs_parents')}</h3><Chips xs={parents} /></>}
    {spouses.length > 0 && <><h3>{t('fs_spouses')}</h3><Chips xs={spouses} /></>}
    {kids.length > 0 && <><h3>{t('fs_children')} · {kids.length}</h3><Chips xs={kids} /></>}
    {st && (st.bio || st.facts || st.pics || st.texts) ? <>
      <h3>{t('ex_onpage')}</h3>
      <div className="ex-stats">
        {st.bio && <Link to={href.person(sel.slug)}>{t('ex_bio')}</Link>}
        {st.facts > 0 && <Link to={href.person(sel.slug)}>{t('ex_facts', st.facts)}</Link>}
        {st.pics > 0 && <Link to={href.person(sel.slug)}>{t('ex_pics', st.pics)}</Link>}
        {st.texts > 0 && <Link to={href.person(sel.slug)}>{t('ex_texts', st.texts)}</Link>}
      </div></> : null}
    <div className="ex-btns">
      <Link className="btn go" to={href.person(sel.slug)}>{t('ex_open')}</Link>
      {sel.id !== center.id && <button className="btn tonal" onClick={() => recenter(sel)}>{t('ex_center')}</button>}
    </div>
  </aside>
}

/** Под веером: «Ближняя родня» выбранного и его семья на шкале */
function Below({sel, ix, pick}: {sel: IndexPerson; ix: Lookup; pick: (p: IndexPerson) => void}) {
  const t = useT()
  const [tab, setTab] = useState<'ped' | 'time'>('ped')
  const q = usePersonQuery(tab === 'time' ? {id: sel.id, v: ix.index.built} : skipToken)
  return <section className="card ex-below">
    <div className="bio-tabs anc-tabs" role="tablist">
      <button role="tab" aria-selected={tab === 'ped'} className={tab === 'ped' ? 'on' : ''} onClick={() => setTab('ped')}>{t('ex_pedigree')}</button>
      <button role="tab" aria-selected={tab === 'time'} className={tab === 'time' ? 'on' : ''} onClick={() => setTab('time')}>{t('fs_title')}</button>
    </div>
    {tab === 'ped' ? <Pedigree sel={sel} ix={ix} pick={pick} />
      : q.data ? <FamilySpan p={q.data} ix={ix} onPick={pick} bare /> : <Status state="loading" />}
  </section>
}

function Pedigree({sel, ix, pick}: {sel: IndexPerson; ix: Lookup; pick: (p: IndexPerson) => void}) {
  const t = useT(), lang = useLang()
  const get = (id?: string) => (id ? ix.people.get(id) : undefined)
  const s = ancestorSlots(ix, sel.id, 2)
  const kids = sel.children.flatMap(id => { const p = get(id); return p ? [p] : [] })
    .sort((a, b) => (yearsOf(a.life).born ?? 9999) - (yearsOf(b.life).born ?? 9999))
  const gkids = kids.flatMap(k => k.children.flatMap(id => { const p = get(id); return p ? [p] : [] }))
  const Box = ({p, main}: {p?: IndexPerson; main?: boolean}) => p
    ? <button className={`ped-box ${p.sex === 'F' ? 'f' : 'm'}${main ? ' main' : ''}`} onClick={() => pick(p)}>
      <b>{nameIn(p.names, lang)}</b><small>{p.life || '?'}</small></button>
    : <span className="ped-box empty">?</span>
  const row = (label: string, xs: ReactNode) => <div className="ped-row"><span className="ped-label">{label}</span><div className="ped-cells">{xs}</div></div>
  return <div className="ped">
    {row(t('ped_gp'), <><div className="ped-pair"><Box p={s[4]} /><Box p={s[5]} /></div><div className="ped-pair"><Box p={s[6]} /><Box p={s[7]} /></div></>)}
    {row(t('fs_parents'), <><div className="ped-pair"><Box p={s[2]} /></div><div className="ped-pair"><Box p={s[3]} /></div></>)}
    {row('', <Box p={sel} main />)}
    {kids.length > 0 && row(t('fs_children'), kids.map(p => <Box key={p.id} p={p} />))}
    {gkids.length > 0 && row(t('ped_gkids'), gkids.slice(0, 12).map(p => <Box key={p.id} p={p} />))}
    {gkids.length > 12 && <p className="life">{t('ped_more', gkids.length - 12)}</p>}
  </div>
}
