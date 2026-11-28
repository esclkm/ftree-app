// Веер предков: полукруг, в центре человек, каждое кольцо — поколение (родители, деды, прадеды …). Слева — сторона отца,
// справа — матери. Наведение подсвечивает путь от предка к центру, нажатие открывает его страницу. Пустое место, у
// которого ребёнок известен, — «здесь можно искать»: залито плотнее остальных пустых.
import {useState} from 'react'
import {useNavigate} from 'react-router'
import {nameIn, useLang, useT} from '../i18n'
import type {IndexPerson, Lookup} from '../useIndex'
import {useLinks} from '../useIndex'
import {ancestorSlots, fanCount, genOf} from './ancestry'
import {Tip, useTip} from './Tip'

const R0 = 46                                   // центр — полукруг самого человека
const RING = [0, 78, 70, 62, 58, 54, 50, 46, 42] // ширина кольца по поколениям
const PAD = 8

const pt = (r: number, a: number): [number, number] => [r * Math.cos(a), -r * Math.sin(a)]
/** Кусок кольца между углами a0 > a1 (радианы, π — слева, 0 — справа) */
function seg(r0: number, r1: number, a0: number, a1: number): string {
  const [x0, y0] = pt(r1, a0), [x1, y1] = pt(r1, a1), [x2, y2] = pt(r0, a1), [x3, y3] = pt(r0, a0)
  return `M${x0},${y0}A${r1},${r1} 0 0 1 ${x1},${y1}L${x2},${y2}A${r0},${r0} 0 0 0 ${x3},${y3}Z`
}

/** Имя по-строчно: имя и фамилия; длинное — обрезать до места */
function lines(full: string, room: number, fs: number): string[] {
  const max = Math.max(2, Math.floor(room / (fs * 0.56)))
  const cut = (s: string) => (s.length > max ? s.slice(0, max - 1) + '…' : s)
  const w = full.replace(/\s*\(.*$/, '').split(/\s+/).filter(Boolean)
  return w.length <= 1 ? [cut(w[0] ?? '')] : [cut(w[0]), cut(w.slice(1).join(' '))]
}

/** onCenter — двойное нажатие ставит человека в центр веера; onPick — нажатие выбирает человека (страница «Исследовать»), без него — открывает его страницу; selected — выбранный */
export function AncestorFan({id, ix, gens, onPick, onCenter, selected}: {id: string; ix: Lookup; gens: number
  onPick?: (p: IndexPerson) => void; onCenter?: (p: IndexPerson) => void; selected?: string}) {
  const t = useT(), lang = useLang(), href = useLinks(), navigate = useNavigate()
  const {box, tip, show, hide} = useTip()
  const [hover, setHover] = useState(0)
  const slots = ancestorSlots(ix, id, gens)
  const radius = (g: number) => R0 + RING.slice(1, g + 1).reduce((a, b) => a + b, 0)
  const R = radius(gens), W = 2 * (R + PAD), H = R + PAD + 46
  const path = new Set<number>()
  for (let k = hover; k >= 1; k = k >> 1) path.add(k)
  const {known, total} = fanCount(slots, gens)
  const go = (p: IndexPerson) => (onPick ? onPick(p) : navigate(href.person(p.slug)))
  // до какого поколения заполнены все места — красная дуга
  let full = 0
  for (let g = 1; g <= gens; g++) { let all = true; for (let k = 2 ** g; k < 2 ** (g + 1); k++) if (!slots[k]) all = false; if (!all) break; full = g }
  const side = (k: number) => (k < 2 ? '' : (k >> (genOf(k) - 1)) === 2 ? 'dad' : 'mom')

  const cells = []
  for (let k = 2; k < 2 ** (gens + 1); k++) {
    const g = genOf(k), i = k - 2 ** g, n = 2 ** g
    const a0 = Math.PI - (i * Math.PI) / n, a1 = Math.PI - ((i + 1) * Math.PI) / n
    const r0 = radius(g - 1), r1 = radius(g)
    const p = slots[k], child = slots[k >> 1]
    const gap = !p && !!child   // ребёнок известен, родитель — нет
    const cls = ['fan-cell', side(k), p ? 'known' : gap ? 'gap' : 'none', p && p.id === selected ? 'sel' : '', hover && path.has(k) ? 'on' : '', hover && !path.has(k) ? 'dim' : ''].join(' ')
    const mid = (a0 + a1) / 2, rm = (r0 + r1) / 2, deg = (mid * 180) / Math.PI
    let label = null
    if (p) {
      const name = nameIn(p.names, lang)
      const arcLen = (r1 - r0 > 0 ? rm * (a0 - a1) : 0) - 4
      const radial = arcLen < (r1 - r0)   // узкий кусок — подпись вдоль радиуса
      const fs = Math.max(7, Math.min(13, (radial ? arcLen : (r1 - r0) / 2.6) * (radial ? 0.42 : 1)))
      const ls = lines(name, (radial ? r1 - r0 : arcLen) - 6, fs).slice(0, radial && arcLen < fs * 2.2 ? 1 : 2)
      const [x, y] = pt(rm, mid)
      const rot = radial ? (deg > 90 ? 180 - deg : -deg) : 90 - deg
      label = <text className="fan-name" transform={`translate(${x},${y}) rotate(${rot})`} fontSize={fs} textAnchor="middle">
        {ls.map((s, j) => <tspan key={j} x={0} dy={j === 0 ? `${(-(ls.length - 1) * 0.55 + 0.35).toFixed(2)}em` : '1.1em'}
          className={j ? 'sur' : ''}>{s}</tspan>)}
      </text>
    }
    cells.push(<g key={k} className={cls}
      onMouseEnter={() => setHover(k)}
      onMouseMove={e => show(e, p
        ? <><b>{nameIn(p.names, lang)}</b>{p.life && <span className="life"> {p.life}</span>}
          <div className="life">{t(g === 1 ? 'fan_g1' : g === 2 ? 'fan_g2' : 'fan_gn', g)} · {t(side(k) === 'dad' ? 'fan_dad' : 'fan_mom')}</div></>
        : <><b>{t('fan_unknown')}</b>{gap && <div className="life">{t('fan_gap')}</div>}</>)}
      onMouseLeave={() => { setHover(0); hide() }}
      onClick={() => p && go(p)}
      onDoubleClick={() => { if (p && onCenter) { hide(); setHover(0); onCenter(p) } }}
      onKeyDown={e => { if (p && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); go(p) } }}
      tabIndex={p ? 0 : -1} role={p ? 'link' : undefined} aria-label={p ? nameIn(p.names, lang) : undefined}>
      <path d={seg(r0, r1, a0, a1)} />{label}
    </g>)
  }
  const me = slots[1]
  return <div className="fan" ref={box}>
    <svg viewBox={`${-W / 2} ${-R - PAD} ${W} ${H}`} className="fan-svg" role="img" aria-label={t('fan_count', known, total, gens)}>
      {cells}
      <path className={`fan-cell me ${hover ? 'on' : ''} ${onPick ? 'pick' : ''}`} onClick={() => { if (onPick && me) onPick(me) }} d={`M${-R0},0A${R0},${R0} 0 0 1 ${R0},0Z`} />
      <line className="fan-base" x1={-R} x2={R} y1={0} y2={0} />
      {full > 0 && <path className="fan-full" d={`M${-radius(full)},0A${radius(full)},${radius(full)} 0 0 1 ${radius(full)},0`}><title>{t('fan_full', full)}</title></path>}
      {Array.from({length: gens}, (_, i) => i + 1).flatMap(g => [-1, 1].map(sgn =>
        <text key={`${g}${sgn}`} className="fan-gnum" x={sgn * (radius(g - 1) + radius(g)) / 2} y={16} textAnchor="middle">{g}</text>))}
      {me && <text className="fan-me" y={36} textAnchor="middle">{nameIn(me.names, lang)}</text>}
    </svg>
    <Tip tip={tip} width={box.current?.clientWidth} />
    <p className="fan-sum"><b>{t('fan_count', known, total, gens)}</b>{full > 0 && <span className="life"> · {t('fan_full', full)}</span>}</p>
  </div>
}
