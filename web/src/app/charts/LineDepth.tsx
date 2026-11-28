// Глубина линий: полукруг, клин на каждого прадеда и прабабушку (слева — сторона отца, справа — матери). Длина клина —
// год рождения самого раннего известного предка этой линии: чем дальше от центра, тем глубже в прошлое. Кольца — века.
// Наведение — кто этот предок и сколько поколений; нажатие — его страница.
import {useState} from 'react'
import {useNavigate} from 'react-router'
import {nameIn, useLang, useT} from '../i18n'
import type {Lookup} from '../useIndex'
import {useLinks} from '../useIndex'
import {type LineDepth as Depth, lineDepths, THIS_YEAR, yearsOf} from './ancestry'
import {Tip, useTip} from './Tip'

const R0 = 70, R = 330, PAD = 14
const LEVEL = 3

const pt = (r: number, a: number): [number, number] => [r * Math.cos(a), -r * Math.sin(a)]
function seg(r0: number, r1: number, a0: number, a1: number): string {
  const [x0, y0] = pt(r1, a0), [x1, y1] = pt(r1, a1), [x2, y2] = pt(r0, a1), [x3, y3] = pt(r0, a0)
  return `M${x0},${y0}A${r1},${r1} 0 0 1 ${x1},${y1}L${x2},${y2}A${r0},${r0} 0 0 0 ${x3},${y3}Z`
}

export function LineDepthChart({id, ix}: {id: string; ix: Lookup}) {
  const t = useT(), lang = useLang(), href = useLinks(), navigate = useNavigate()
  const {box, tip, show, hide} = useTip()
  const [hover, setHover] = useState(-1)
  const lines = lineDepths(ix, id, LEVEL)
  const years = lines.flatMap(l => (l?.year !== undefined ? [l.year] : []))
  // внутренний край — около рождения прадедов (последний известный год среди них), внешний — век до самого раннего
  const rootYears = lines.flatMap(l => { const b = l && yearsOf(l.root.life).born; return b ? [b] : [] })
  const me = ix.people.get(id), meBorn = yearsOf(me?.life).born
  const top = Math.min(THIS_YEAR, Math.ceil((rootYears.length ? Math.max(...rootYears) : (meBorn ?? THIS_YEAR) - 60) / 50) * 50)
  const oldest = years.length ? Math.min(...years) : top - 200
  const bottom = Math.min(top - 200, Math.floor((oldest - 30) / 100) * 100)
  const r = (y: number) => R0 + ((top - Math.min(top, y)) / (top - bottom)) * (R - R0)
  const rings: number[] = []
  for (let y = Math.floor(top / 100) * 100; y >= bottom; y -= 100) if (y < top) rings.push(y)
  const n = lines.length, gap = 0.012
  const W = 2 * (R + PAD)

  const tipFor = (l: Depth) => <>
    <b>{nameIn(l.root.names, lang)}</b>{l.root.life && <span className="life"> {l.root.life}</span>}
    {l.earliest && l.earliest !== l.root
      ? <div>{t('depth_earliest')}: <b>{nameIn(l.earliest.names, lang)}</b> <span className="life">{l.earliest.life}</span></div>
      : null}
    <div className="life">{l.year !== undefined ? t('depth_tip', l.generations, l.people) : t('depth_none')}</div>
  </>

  return <div className="fan depth" ref={box}>
    <svg viewBox={`${-W / 2} ${-R - PAD} ${W} ${R + PAD + 34}`} className="fan-svg" role="img" aria-label={t('depth_title')}>
      {rings.map(y => <g key={y} className="depth-ring">
        <path d={`M${-r(y)},0A${r(y)},${r(y)} 0 0 1 ${r(y)},0`} />
        <text x={-r(y)} y={22} textAnchor="middle">{y}</text>
        <text x={r(y)} y={22} textAnchor="middle">{y}</text>
      </g>)}
      {lines.map((l, i) => {
        const a0 = Math.PI - (i * Math.PI) / n - gap, a1 = Math.PI - ((i + 1) * Math.PI) / n + gap
        if (!l) return <path key={i} className="depth-wedge none" d={seg(R0, R0 + 10, a0, a1)} />
        const outer = l.year !== undefined ? r(l.year) : R0 + 10
        const mid = (a0 + a1) / 2, [lx, ly] = pt(outer + 18, mid)
        const cls = ['depth-wedge', i < n / 2 ? 'dad' : 'mom', hover === i ? 'on' : hover >= 0 ? 'dim' : ''].join(' ')
        const target = l.earliest ?? l.root
        return <g key={i} className={cls} tabIndex={0} role="link" aria-label={nameIn(target.names, lang)}
          onMouseEnter={() => setHover(i)} onMouseMove={e => show(e, tipFor(l))}
          onMouseLeave={() => { setHover(-1); hide() }}
          onClick={() => navigate(href.person(target.slug))}
          onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); navigate(href.person(target.slug)) } }}>
          <path d={seg(R0, outer, a0, a1)} />
          <text className="depth-year" x={lx} y={ly + 5} textAnchor="middle">{l.year ?? '?'}</text>
        </g>
      })}
      <path className="depth-me" d={`M${-R0 + 6},0A${R0 - 6},${R0 - 6} 0 0 1 ${R0 - 6},0Z`} />
      {me && <text className="fan-me" y={-16} textAnchor="middle">{nameIn(me.names, lang).split(/\s+/)[0]}</text>}
      <line className="fan-base" x1={-R} x2={R} y1={0} y2={0} />
    </svg>
    <Tip tip={tip} width={box.current?.clientWidth} />
    <p className="note">{t('depth_note')}</p>
  </div>
}
