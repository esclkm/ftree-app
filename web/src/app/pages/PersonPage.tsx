// Страница человека: /people/<slug>. Номер человека — из общего списка по адресу, сам человек — data/people/<id>.json.
import {skipToken} from '@reduxjs/toolkit/query'
import {type ReactNode, useEffect} from 'react'
import {Link, useNavigate, useParams} from 'react-router'
import type {Fact, LifeEvent, PersonFile} from '../../data/schema.gen'
import {Icon} from '../../components/Icon'
import {usePersonQuery} from '../api'
import {dateIn, nameIn, titleIn, trIn, useLang, useT} from '../i18n'
import {Md} from '../Md'
import {Status} from '../Layout'
import {Kin} from './Legacy'
import {Avatar, Biography, Documents, LifePhotos, Lifeline, Photos, Questions, Recollections, Stays} from './PersonParts'
import {cleanSlug, type Lookup, useIndex, useLinks} from '../useIndex'
import {Pin} from '../notes/Pin'
import {Homes} from '../Houses'
import {NoteScope} from '../notes/scope'

export function PersonPage() {
  const href = useLinks()
  const {slug} = useParams(), navigate = useNavigate()
  const clean = cleanSlug(slug)
  useEffect(() => { if (clean !== slug) navigate(href.person(clean), {replace: true}) }, [clean, slug, navigate])
  const {ix, isLoading, isError} = useIndex()
  const entry = ix?.personBySlug.get(clean)
  const q = usePersonQuery(entry && ix ? {id: entry.id, v: ix.index.built} : skipToken)
  if (isError) return <Status state="error" />
  if (isLoading || q.isLoading) return <Status state="loading" />
  if (!entry || (q.error && 'status' in q.error && q.error.status === 'not_found')) return <Status state="not_found" />
  if (q.error || !q.data || !ix) return <Status state="error" />
  return <Person p={q.data} ix={ix} />
}

function Person({p, ix}: {p: PersonFile; ix: Lookup}) {
  const href = useLinks()
  const t = useT(), lang = useLang()
  const name = nameIn(p.names.display, lang)
  const me = ix.people.get(p.id)
  useEffect(() => { document.title = `${name} — ${t('site')}` }, [name, t])

  const parents = p.relationships.flatMap(r => r.type === 'parent-child' && r.child === p.id ? [r.parent] : [])
  const children = p.relationships.flatMap(r => r.type === 'parent-child' && r.parent === p.id ? [r.child] : [])
  const couples = p.relationships.flatMap(r => r.type === 'couple' ? [r] : [])
  const siblings = [...new Set(parents.flatMap(id => ix.people.get(id)?.children ?? []))].filter(id => id !== p.id)
  const father = parents.filter(id => ix.people.get(id)?.sex === 'M'), mother = parents.filter(id => ix.people.get(id)?.sex === 'F')
  const male = p.sex === 'M'

  const family: [string, ReactNode[]][] = [
    ['father', father.map(id => <PersonLink key={id} id={id} ix={ix} />)],
    ['mother', mother.map(id => <PersonLink key={id} id={id} ix={ix} />)],
    ['spouse', couples.map(c => {
      const other = c.person1 === p.id ? c.person2 : c.person1
      return <span key={other}><PersonLink id={other} ix={ix} />
        {c.divorced && <span className="life"> · {t('divorced')}{c.divorced !== true ? ' ' + dateIn(c.divorced, lang) : ''}</span>}</span>
    })],
    ['children', children.map(id => <PersonLink key={id} id={id} ix={ix} />)],
    ['siblings', siblings.map(id => <PersonLink key={id} id={id} ix={ix} />)],
  ]

  const subject = {type: 'person' as const, id: p.id, name: nameIn(p.names.display, 'ru'), path: `/people/${p.slug}`, file: p.biography?.file}
  const plainFamily = family.filter(([, v]) => v.length).map(([k]) => {
    const ids = k === 'father' ? father : k === 'mother' ? mother : k === 'children' ? children : k === 'siblings' ? siblings
      : couples.map(c => (c.person1 === p.id ? c.person2 : c.person1))
    return `${t(k)}: ${ids.map(id => { const x = ix.people.get(id); return x ? nameIn(x.names, 'ru') : id }).join(', ')}`
  }).join('\n')

  return <NoteScope subject={subject}>
    <section className="hero card person-hero">
      <Avatar p={p} ix={ix} />
      <div className="hero-text">
        <h1>{name}<Pin kind="whole" title={t('n_pin_person')} /></h1>
        <div className="life big">{me?.life}</div>
      </div>
      <Kin id={p.id} />
      <div className="hero-btns">
        <Link className="btn tonal" to={href.at(`/tree#${p.slug}`)}><Icon name="tree" /><span className="long">{t('show_tree')}</span><span className="short">{t('nav_tree')}</span></Link>
        <Link className="btn tonal" to={href.at(`/lifelines?p=${[p.id, ...parents, ...couples.map(c => (c.person1 === p.id ? c.person2 : c.person1))]
          .flatMap(id => { const x = ix.people.get(id); return x ? [x.slug] : [] }).join(',')}`)}><Icon name="event" /><span className="long">{t('ll_compare')}</span><span className="short">{t('nav_lifelines')}</span></Link>
      </div>
    </section>
    <div className="grid2">
      {(p.born || p.died || p.occupation) && <section className="card" data-note-where={t('nw_short')}>
        <h2><Icon name="person" />{t('about')}</h2>
        <table className="kv"><tbody>
          <LifeRow label={t(male ? 'born_m' : 'born_f')} what={t('nw_birth')} ev={p.born} ix={ix} />
          <LifeRow label={t(male ? 'died_m' : 'died_f')} what={t('nw_death')} ev={p.died} ix={ix} />
          {p.occupation && <tr><th>{t('occupation')}</th><td><Md text={(lang === 'ru' ? undefined : p.occupation_tr?.[lang]) || p.occupation} /><Pin kind="about" where={`${t('nw_short')} › ${t('nw_occupation')}`} text={p.occupation} /></td></tr>}
        </tbody></table>
      </section>}
      <section className="card" data-note-where={t('nw_family')}>
        <h2><Icon name="fam" />{t('family')}<Pin kind="about" where={t('nw_family_links')} text={plainFamily} title={t('n_pin_family')} /></h2>
        <table className="kv"><tbody>
          {family.filter(([, v]) => v.length).map(([k, v]) =>
            <tr key={k}><th>{t(k)}</th><td className="list">{v}</td></tr>)}
        </tbody></table>
        <Possible p={p} ix={ix} />
      </section>
    </div>
    {p.biography && <Lifeline bio={p.biography} />}
    {p.biography && <Biography key={p.id} bio={p.biography} />}
    {p.biography && <Recollections bio={p.biography} />}
    {p.biography && <Questions bio={p.biography} />}
    <Photos p={p} />
    <Documents p={p} />
    {p.facts.length > 0 && <details className="card fold" key={`facts-${p.id}`}>
      <summary><h2><Icon name="source" />{t('facts')} <span className="count">{p.facts.length}</span></h2></summary>
      <ol className="facts">{p.facts.map((f, i) => <FactRow key={i} f={f} ix={ix} />)}</ol>
    </details>}
    <Homes p={p} ix={ix} />
    <Stays p={p} ix={ix} />
    <LifePhotos p={p} ix={ix} />
    {p.sources.length > 0 && <section className="card">
      <h2><Icon name="source" />{t('src_of')}</h2>
      <ul className="plain">{p.sources.map(id => <li key={id}><SourceLink id={id} ix={ix} /></li>)}</ul>
    </section>}
  </NoteScope>
}

/** «Возможно, связан» — подозрение из карточки (maybe_same, maybe_kin), не доказанная связь: пунктиром, под семьёй,
 *  со строкой «на чём держится». На дереве такие связи не рисуются. */
function Possible({p, ix}: {p: PersonFile; ix: Lookup}) {
  const t = useT()
  const rows = (p.possible ?? []).filter(x => ix.people.has(x.person))
  if (!rows.length) return null
  const word = (x: NonNullable<PersonFile['possible']>[number]) => {
    if (x.type === 'same') return t('maybe_same')
    if (!x.relation || x.relation === 'kin') return t('maybe_kin')
    return t(`maybe_${x.relation}_${ix.people.get(x.person)?.sex === 'F' ? 'f' : 'm'}`)
  }
  return <div className="maybe" data-note-where={t('nw_maybe')}>
    <h3>{t('maybe_title')}</h3>
    <p className="note">{t('maybe_note')}</p>
    <ul className="plain">{rows.map(x => <li key={x.type + x.person}>
      <span className="maybe-what">{word(x)}:</span> <PersonLink id={x.person} ix={ix} />
      {x.reason && <div className="reasoning"><b>{t('maybe_why')}:</b> <Md text={x.reason} /></div>}
    </li>)}</ul>
  </div>
}

function LifeRow({label, what, ev, ix}: {label: string; what: string; ev?: LifeEvent; ix: Lookup}) {
  const href = useLinks(), t = useT()
  const lang = useLang()
  if (!ev?.date && !ev?.place) return null
  const place = ev.place ? ix.places.get(ev.place) : undefined
  return <tr><th>{label}</th><td>
    {ev.date && dateIn(ev.date, lang)}
    {place && <>{ev.date && ' · '}<Link to={href.place(place.slug)}>{nameIn(place.names, lang)}</Link></>}
    <Pin kind="about" where={`${t('nw_short')} › ${what}`}
      text={[ev.date?.ru, place && nameIn(place.names, 'ru')].filter(Boolean).join(' · ')} />
  </td></tr>
}

function FactRow({f, ix}: {f: Fact; ix: Lookup}) {
  const t = useT(), lang = useLang()
  const tr = lang === 'ru' ? undefined : f.tr?.[lang]  // перевод строки, если есть
  const v = trIn(f, lang), locs = tr?.locators, date = f.date && tr?.when ? {...f.date, words: tr.when} : f.date
  return <li className={`fact conf-${f.confidence}`}>
    <span className="date">{date ? dateIn(date, lang) : ''}</span>
    <div>
      {v.label && <b>{v.label}: </b>}<Md text={v.text} />
      <Pin kind="fact" where={t('nw_facts')} text={[f.date?.ru, f.label && `${f.label}:`, f.text].filter(Boolean).join(' ') +
        (f.sources.length ? ` — источник: ${f.sources.map(s => [ix.sources.get(s.source)?.title ?? s.source, s.locator].filter(Boolean).join(', ')).join('; ')}` : '')} />
      <div className="src-line">
        <span className="srcs">{f.sources.map((s, i) => <span key={i}>{i > 0 && '; '}<SourceLink id={s.source} ix={ix} />
          {s.locator && <>, <Md text={locs?.[i] || s.locator} /></>}</span>)}</span>
        <span className={`chip conf ${f.confidence}`} title={v.reasoning}>{t(`conf_${f.confidence}`)}</span>
        <span className="chip">{t(`prov_${f.provenance}`)}</span>
      </div>
      {v.reasoning && <div className="reasoning"><Md text={v.reasoning} /></div>}
    </div>
  </li>
}

/** Ссылка на человека; `short` — вместо имени инициалы («ЕБ», полное имя — подсказкой): там, где имён много в столбик;
 *  `color` — цвет человека (линии жизни: имя того же цвета, что его полоса) */
export function PersonLink({id, ix, short, color}: {id: string; ix: Lookup; short?: boolean; color?: string}) {
  const href = useLinks()
  const lang = useLang(), x = ix.people.get(id)
  if (!x) return null
  const name = nameIn(x.names, lang)
  const style = color ? {color} : undefined
  if (short) return <span className="plink"><Link to={href.person(x.slug)} title={name} style={style} className="initials">{initials(name)}</Link></span>
  return <span className="plink"><Link to={href.person(x.slug)} style={style}>{name}</Link>
    {x.life && <span className="life"> {x.life}</span>}</span>
}

/** «Прокоп Ясенев» → «ПЯ»; пояснение тёзки в скобках («Мария (2007)») не в счёт */
const initials = (name: string) => name.replace(/\s*\(.*$/, '').split(/\s+/).filter(Boolean).slice(0, 2)
  .map(w => [...w][0].toUpperCase()).join('')

export function SourceLink({id, ix}: {id: string; ix: Lookup}) {
  const href = useLinks(), lang = useLang()
  const s = ix.sources.get(id)
  return s ? <Link to={href.source(s.slug)}>{titleIn(s, lang)}</Link> : null
}
