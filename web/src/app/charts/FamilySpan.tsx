// Семья на одной шкале: родители, братья и сёстры (с самим человеком по порядку рождения), супруги, дети — полоса на
// каждую жизнь, фон — годы жизни самого человека. Число в конце — возраст в год смерти; точка — свадьба (из линии
// жизни, если там есть строка о браке). Наведение — подсказка, нажатие — страница человека.
import {Fragment, useState} from 'react'
import {useNavigate} from 'react-router'
import type {PersonFile} from '../../data/schema.gen'
import {Icon} from '../../components/Icon'
import {nameIn, useLang, useT} from '../i18n'
import type {IndexPerson, Lookup} from '../useIndex'
import {useLinks} from '../useIndex'
import {yearOf} from '../timeline'
import {THIS_YEAR, yearsOf} from './ancestry'
import {Tip, useTip} from './Tip'
import './charts.scss'

const W = 900, LABEL = 200, ROW = 26, HEAD = 22, AX = 26, END = 34
const MARRIED = /брак|жени|замуж|свадьб|венча|ślub|boda|casó|marri|wedd/i

interface Row { p: IndexPerson; self?: boolean }

export function FamilySpan({p, ix}: {p: PersonFile; ix: Lookup}) {
  const t = useT(), lang = useLang(), href = useLinks(), navigate = useNavigate()
  const {box, tip, show, hide} = useTip()
  const [hover, setHover] = useState('')
  const get = (id: string) => ix.people.get(id)
  const me = get(p.id)
  if (!me) return null
  const byBirth = (a: IndexPerson, b: IndexPerson) => (yearsOf(a.life).born ?? 9999) - (yearsOf(b.life).born ?? 9999)
  const ids = (xs: string[]) => [...new Set(xs)].flatMap(x => { const q = get(x); return q ? [q] : [] })
  const parents = ids(me.parents).sort((a, b) => (a.sex === b.sex ? 0 : a.sex === 'M' ? -1 : 1))
  const sibs = [...ids(me.parents.flatMap(x => get(x)?.children ?? [])).filter(q => q.id !== me.id), me].sort(byBirth)
  const spouses = ids(me.spouses), kids = ids(me.children).sort(byBirth)
  const groups: [string, Row[]][] = ([
    ['fs_parents', parents.map(q => ({p: q}))],
    [sibs.length > 1 ? 'fs_siblings' : 'fs_self', sibs.map(q => ({p: q, self: q.id === me.id}))],
    ['fs_spouses', spouses.map(q => ({p: q}))],
    ['fs_children', kids.map(q => ({p: q}))],
  ] as [string, Row[]][]).filter(([, rs]) => rs.length)
  const dated = groups.flatMap(([, rs]) => rs).filter(r => yearsOf(r.p.life).born !== undefined)
  if (dated.length < 2) return null

  // свадьба — первая строка линии жизни о браке; только если супруг один, иначе не понять, с кем
  const wedRow = spouses.length === 1 ? p.biography?.lifeline?.find(r => r.date && MARRIED.test(r.text)) : undefined
  const wed = wedRow?.date ? yearOf(wedRow.date) : undefined

  const ys = dated.flatMap(r => { const y = yearsOf(r.p.life); return [y.born!, y.died ?? (y.alive ? THIS_YEAR : y.born!)] })
  const from = Math.floor(Math.min(...ys) / 10) * 10, to = THIS_YEAR + 1
  const x = (y: number) => LABEL + ((y - from) / (to - from)) * (W - LABEL - END)
  const step = to - from > 160 ? 40 : 20
  const ticks: number[] = []
  for (let y = Math.ceil(from / step) * step; y <= to; y += step) ticks.push(y)
  const rowsH = groups.reduce((h, [, rs]) => h + HEAD + rs.length * ROW, 0)
  const H = rowsH + AX + 6
  const own = yearsOf(me.life)
  const ownTo = own.died ?? (own.alive ? to : undefined)

  let y0 = 0
  const body = groups.map(([key, rs]) => {
    const top = y0
    y0 += HEAD + rs.length * ROW
    return <Fragment key={key}>
      <text className="fs-group" x={8} y={top + 15}>{t(key)}</text>
      {rs.map((r, i) => {
        const y = top + HEAD + i * ROW + ROW / 2
        const yr = yearsOf(r.p.life), name = nameIn(r.p.names, lang).replace(/\s*\(.*$/, '')
        const first = name.split(/\s+/)[0]
        const end = yr.died ?? (yr.alive ? THIS_YEAR : undefined)
        const cls = ['fs-row', r.p.sex === 'F' ? 'f' : 'm', r.self ? 'self' : '', hover === r.p.id ? 'on' : hover ? 'dim' : ''].join(' ')
        const go = () => { if (!r.self) navigate(href.person(r.p.slug)) }
        return <g key={r.p.id} className={cls} tabIndex={r.self ? -1 : 0} role={r.self ? undefined : 'link'} aria-label={name}
          onMouseEnter={() => setHover(r.p.id)} onMouseLeave={() => { setHover(''); hide() }}
          onMouseMove={e => show(e, <><b>{name}</b>{r.p.life && <span className="life"> {r.p.life}</span>}
            {yr.born !== undefined && yr.died !== undefined && <div className="life">{t('fs_age', yr.died - yr.born)}</div>}
            {yr.born !== undefined && yr.died === undefined && !yr.alive && <div className="life">{t('fs_no_end')}</div>}</>)}
          onClick={go} onKeyDown={e => { if (e.key === 'Enter') go() }}>
          <rect className="fs-hit" x={0} y={y - ROW / 2} width={W} height={ROW} />
          <text className="fs-name" x={LABEL - 10} y={y + 4} textAnchor="end">{first}
            <tspan className="fs-life">{' '}{r.p.life || '?'}</tspan></text>
          {yr.born !== undefined && (end !== undefined
            ? <line className="fs-bar" x1={x(yr.born)} x2={x(end)} y1={y} y2={y} />
            : <line className="fs-bar open" x1={x(yr.born)} x2={x(Math.min(THIS_YEAR, yr.born + 40))} y1={y} y2={y} />)}
          {yr.born !== undefined && yr.died !== undefined &&
            <text className="fs-age" x={x(yr.died) + 6} y={y + 4}>{yr.died - yr.born}</text>}
          {wed !== undefined && spouses[0]?.id === r.p.id && <circle className="fs-wed" cx={x(wed)} cy={y} r={5}><title>{wedRow?.when}</title></circle>}
        </g>
      })}
    </Fragment>
  })

  return <section className="card fs-card" data-note-where={t('fs_title')}>
    <h2><Icon name="event" />{t('fs_title')}</h2>
    <div className="fs-scroll" ref={box}>
      <svg viewBox={`0 0 ${W} ${H}`} className="fs-svg" role="img" aria-label={t('fs_title')}>
        {own.born !== undefined && ownTo !== undefined &&
          <rect className="fs-own" x={x(own.born)} y={0} width={x(ownTo) - x(own.born)} height={rowsH} />}
        {ticks.map(y => <g key={y} className="fs-tick">
          <line x1={x(y)} x2={x(y)} y1={0} y2={rowsH} />
          <text x={x(y)} y={rowsH + 18} textAnchor="middle">{y}</text>
        </g>)}
        {body}
      </svg>
      <Tip tip={tip} width={box.current?.clientWidth} />
    </div>
    <div className="fs-legend">
      <span><i className="own" />{t('fs_lifetime', nameIn(me.names, lang).split(/\s+/)[0])}</span>
      <span><i className="m" />{t('fs_men')}</span><span><i className="f" />{t('fs_women')}</span>
      {wed !== undefined && <span><i className="wed" />{t('fs_married')}</span>}
      <span className="life">{t('fs_age_note')}</span>
    </div>
  </section>
}
