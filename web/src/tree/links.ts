// Линии дерева: несколько браков — у второго и следующих свой цвет (линия между супругами и линии от пары к детям);
// развод — линия между супругами точками; углы линий «родители → ребёнок» — скруглённые (roundLinks).
import {select} from 'd3'
import type {TreeDatum} from 'family-chart'
import {divorces} from '../data'
import {t} from '../i18n'
import {onPath} from './path'

export const MCOL = ['#1c8fa6', '#e09100', '#8e5cc2', '#3f9b4a']
type Pt = [number, number]
type Link = {spouse?: boolean; source: TreeDatum | TreeDatum[]; target: TreeDatum | TreeDatum[]; d?: Pt[]; _d?: () => Pt[]; curve?: boolean}
type MaskPath = SVGPathElement & {_line?: SVGPathElement}

/** a — тот, у кого на дереве показаны супруги; у второго супруга тоже бывает несколько браков */
function marriageNo(a?: TreeDatum, b?: TreeDatum): number {
  for (const [p, o] of [[a, b], [b, a]]) {
    const sp = p?.data.rels.spouses || []
    if (o && sp.length > 1 && sp.includes(o.data.id)) return sp.indexOf(o.data.id) + 1
  }
  return 0
}

export function colorLinks(svg: SVGElement): void {
  const DIV = divorces()
  select(svg).selectAll<SVGPathElement, Link>('path.link').each(function (l) {
    let n = 0
    if (l.spouse) n = marriageNo(l.source as TreeDatum, l.target as TreeDatum)
    // линия к ребёнку — по номеру брака, записанному у самого ребёнка: второй родитель на дереве может быть не показан
    else if (Array.isArray(l.source)) n = (l.target as TreeDatum).data.data.mar || 0
    else if (Array.isArray(l.target)) n = l.source.data.data.mar || 0
    // первый брак — обычная линия; цвет — только у второго и следующих: по цвету видно, что дети от другого брака
    if (n > 1) { this.style.setProperty('stroke', MCOL[(n - 2) % MCOL.length], 'important'); this.style.setProperty('stroke-width', 'var(--mar-w, 1.75px)') }
    else { this.style.removeProperty('stroke'); this.style.removeProperty('stroke-width') }
    this.dataset.mar = String(n)
    // развод — точками (дата, если известна, — во всплывающей подсказке)
    const key = l.spouse ? [(l.source as TreeDatum).data.id, (l.target as TreeDatum).data.id].sort().join('|') : null
    if (key && key in DIV) {
      this.style.setProperty('stroke-dasharray', '0.1 7'); this.style.setProperty('stroke-linecap', 'round')
      this.style.setProperty('stroke-width', 'var(--div-w, 3px)')
      const tt = this.querySelector('title') || this.appendChild(document.createElementNS('http://www.w3.org/2000/svg', 'title'))
      tt.textContent = t('divorced') + (DIV[key] ? ' ' + DIV[key] : '')
    } else this.style.removeProperty('stroke-dasharray')
  })
  const paths = () => [...svg.querySelectorAll<SVGPathElement>('path.link')]
  // линия ко второму супругу идёт от человека через первого и перекрывает первую — первые браки рисуем поверх
  paths().filter(e => +e.dataset.mar! > 0).sort((a, b) => +b.dataset.mar! - +a.dataset.mar!).forEach(e => e.parentNode!.appendChild(e))
  // под линией развода — подложка цвета фона: иначе между точками просвечивает линия ко второму супругу
  svg.querySelectorAll('path.div-mask').forEach(m => m.remove())
  for (const e of paths()) {
    if (!e.style.strokeDasharray) continue
    const m = document.createElementNS('http://www.w3.org/2000/svg', 'path') as MaskPath
    m.setAttribute('class', 'div-mask'); m.setAttribute('fill', 'none'); m._line = e
    e.parentNode!.insertBefore(m, e); e.parentNode!.appendChild(e)
  }
  followMasks(svg)
}

/** линии «выезжают» с анимацией — подложка повторяет форму своей линии каждый кадр, пока анимация идёт (~3 с) */
function followMasks(svg: SVGElement, until = performance.now() + 3000): void {
  svg.querySelectorAll<MaskPath>('path.div-mask').forEach(m => m._line && m.setAttribute('d', m._line.getAttribute('d') || ''))
  if (performance.now() < until) requestAnimationFrame(() => followMasks(svg, until))
}

const ids = (end: TreeDatum | TreeDatum[]) => (Array.isArray(end) ? end : [end]).map(d => d.data.id)

/** Путь родства — линии между соседями на пути толще и цвета --path (поверх цвета брака, поэтому тоже в style);
 *  толщина — переменная --path-w в _tree.scss, та же, что у рамки карточек на пути */
export function highlightPath(svg: SVGElement, edges: Set<string>): void {
  select(svg).selectAll<SVGPathElement, Link>('path.link').each(function (l) {
    const on = edges.size > 0 && onPath(edges, ids(l.source), ids(l.target))
    this.classList.toggle('kin-path', on)
    if (on) { this.style.setProperty('stroke', 'var(--path)', 'important'); this.style.setProperty('stroke-width', 'var(--path-w, 2px)') }
  })
  // подсвеченные — поверх остальных
  svg.querySelectorAll('path.link.kin-path').forEach(e => e.parentNode!.appendChild(e))
}


// ---------- скруглённые углы ----------
// Библиотека рисует линию «родители → ребёнок» ломаной вниз — вбок — вниз и сглаживает её кривой (d3.curveBasis):
// углы выходят широкими и размытыми, а радиус не настраивается. Поэтому после каждой её перерисовки мы рисуем эти
// линии сами — прямыми отрезками со скруглением радиуса --link-r (_tree.scss) — и сами же анимируем, по тем же точкам.

type RoundPath = SVGPathElement & {__pts?: Pt[]; __transition?: Record<string, {name: string}>}

/** Точки ломаной (child → вниз → вбок → вниз → parents: [a, b, b, c, c, e]) → путь со скруглёнными углами */
export function roundedPath(pts: Pt[], r: number): string {
  const [x0, y0] = pts[0], [, hy] = pts[1], [x1, y1] = pts[pts.length - 1]
  const dx = x1 - x0
  if (Math.abs(dx) < 0.5) return `M${x0},${y0}L${x1},${y1}`  // ребёнок ровно под родителями — прямая
  const R = Math.max(0, Math.min(r, Math.abs(dx) / 2, Math.abs(hy - y0), Math.abs(y1 - hy)))
  const sx = Math.sign(dx), s1 = Math.sign(hy - y0) || 1, s2 = Math.sign(y1 - hy) || 1
  return `M${x0},${y0}L${x0},${hy - s1 * R}Q${x0},${hy} ${x0 + sx * R},${hy}`
    + `L${x1 - sx * R},${hy}Q${x1},${hy} ${x1},${hy + s2 * R}L${x1},${y1}`
}

const lerp = (a: Pt[], b: Pt[], k: number): Pt[] => b.map((p, i) => [a[i][0] + (p[0] - a[i][0]) * k, a[i][1] + (p[1] - a[i][1]) * k])

export function roundLinks(svg: SVGElement, ms: number): void {
  const r = parseFloat(getComputedStyle(svg).getPropertyValue('--link-r')) || 6
  select(svg).selectAll<RoundPath, Link>('path.link').each(function (l) {
    if (!l?.curve || !l.d || l.d.length < 4) return  // линии супругов — прямые, их не трогаем
    // уходящая линия (у библиотеки — переход «op»): не мешаем ей исчезнуть и удалиться
    if (Object.values(this.__transition ?? {}).some(x => x.name === 'op')) return
    const to = l.d, from = this.__pts ?? (l._d ? l._d() : to)
    this.__pts = to
    const same = from.length === to.length && from.every((p, i) => p[0] === to[i][0] && p[1] === to[i][1])
    const path = select(this).interrupt('path')  // вместо анимации библиотеки — своя, по тем же точкам
    if (same || !ms) { path.attr('d', roundedPath(to, r)).style('opacity', 1); return }
    path.transition('path').duration(ms).style('opacity', 1)
      .attrTween('d', () => (k: number) => roundedPath(lerp(from.length === to.length ? from : to, to, k), r))
  })
}
