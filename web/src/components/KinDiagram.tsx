// Окно «Схема родства»: цепочка от меня до человека деревом — карточки и линии с подписью «кем приходится».
// Раскладку считает kin/diagram.ts; здесь только клетки → точки и рисунок.
import {useEffect} from 'react'
import type {TreePersonData} from '../data'
import {nameOf, t} from '../i18n'
import {kin, personName, relation} from '../kin'
import {layout} from '../kin/diagram'
import {Icon} from './Icon'

const W = 150, H = 96, GX = 76, GY = 64, PAD = 12
const cap = (s = '') => s && s[0].toUpperCase() + s.slice(1)
const word = (a: string, b: string) => cap(relation(a, b)?.term?.nom)

export function KinDiagram({path, title, linkTo, onClose}: {
  path: string[]; title: string; linkTo: (id: string) => string; onClose: () => void
}) {
  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', esc)
    return () => document.removeEventListener('keydown', esc)
  }, [onClose])

  const d = layout(kin, path)
  const at = new Map(d.cells.map(c => [c.id, {x: PAD + c.col * (W + GX), y: PAD + c.row * (H + GY)}]))
  const width = PAD * 2 + d.cols * W + (d.cols - 1) * GX, height = PAD * 2 + d.rows * H + (d.rows - 1) * GY
  const ends = new Set([path[0], path[path.length - 1]])

  const lines = d.links.map(l => {
    const A = at.get(l.a)!, B = at.get(l.b)!
    if (l.kind === 'spouse' || l.kind === 'couple') {
      const y = A.y + H / 2, x1 = A.x + W, x2 = B.x
      return {key: l.a + l.b, pts: [[x1, y], [x2, y]], label: l.kind === 'spouse' ? word(l.a, l.b) : '', lx: (x1 + x2) / 2, ly: y, couple: l.kind === 'couple'}
    }
    // вверх или вниз: от нижнего края верхнего к верхнему краю нижнего, с изломом посередине промежутка
    const up = l.kind === 'up'
    const sx = l.from ? (at.get(l.from[0])!.x + W + at.get(l.from[1])!.x) / 2 : A.x + W / 2
    const sy = l.from ? A.y + H / 2 : up ? A.y : A.y + H
    const ex = B.x + W / 2, ey = up ? B.y + H : B.y
    const my = up ? ey + GY / 2 : ey - GY / 2
    return {key: l.a + l.b, pts: [[sx, sy], [sx, my], [ex, my], [ex, ey]], label: word(l.a, l.b),
      lx: ex, ly: sx === ex ? (sy + ey) / 2 : (my + ey) / 2, couple: false}
  })

  return (
    <div className="kd-back" onClick={onClose}>
      <div className="card kd" role="dialog" aria-label={t('kin_chart')} onClick={e => e.stopPropagation()}>
        <div className="kd-head">
          <div><div className="kd-cap">{t('kin_chart')}</div><b>{personName(path[0])} ⇄ {personName(path[path.length - 1])}</b>
            <div className="kin-term">{title}</div></div>
          <button className="icon-btn" onClick={onClose} title={t('kin_close')} aria-label={t('kin_close')}><Icon name="close" /></button>
        </div>
        <div className="kd-scroll">
          <div className="kd-canvas" style={{width, height}}>
            <svg width={width} height={height}>
              <defs><marker id="kd-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M0 0L10 5L0 10z" /></marker></defs>
              {lines.map(l => <polyline key={l.key} className={l.couple ? 'kd-couple' : 'kd-line'} points={l.pts.map(p => p.join(',')).join(' ')}
                markerEnd={l.couple ? undefined : 'url(#kd-arrow)'} />)}
            </svg>
            {lines.filter(l => l.label).map(l => <span key={'l' + l.key} className="kd-label" style={{left: l.lx, top: l.ly}}>{l.label}</span>)}
            {d.turns.map(tr => {
              const A = at.get(tr.a)!, B = at.get(tr.b)!
              return <span key={'t' + tr.a} className="kd-turn" style={{left: A.x + W, top: A.y, width: B.x - A.x - W, height: H}}>{word(tr.a, tr.b)}</span>
            })}
            {d.cells.map(c => {
              const p = at.get(c.id)!, x = kin.P[c.id].x as Partial<TreePersonData>
              return <a key={c.id} href={linkTo(c.id)} className={'kd-card' + (ends.has(c.id) ? ' end' : '') + (c.onPath ? '' : ' side')}
                style={{left: p.x, top: p.y, width: W, height: H}}>
                {x.avatar ? <img src={x.avatar} alt="" />
                  : <span className={'ph c' + (x.c ?? 0)}>{x.ini ? nameOf(x.ini) : <Icon name="person" />}</span>}
                <span className="kd-name">{personName(c.id)}</span>
                {x.life && <span className="kd-life">{x.life}</span>}
              </a>
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
