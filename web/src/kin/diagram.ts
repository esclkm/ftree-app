// Схема родства, как в MyHeritage: цепочка «от меня до человека» деревом. Чистый расчёт клеток, без страницы
// (его проверяет test/diagram.test.ts); рисует components/KinDiagram.tsx.
// Как раскладываем: строка — поколение (вверх — к родителю, вниз — к ребёнку, супруг — та же строка); столбец
// сдвигается вправо на каждом браке и там, где цепочка поворачивает (поднялись до общего предка — спускаемся
// рядом). Внутри одного столбца цепочка идёт только в одну сторону, поэтому клетки не налезают друг на друга.
import type {Kinship} from './graph'

export type StepKind = 'up' | 'down' | 'spouse'
export interface Cell { id: string; col: number; row: number; onPath: boolean }
/** a → b — соседние в цепочке; label — кем b приходится a. «couple» — второй родитель у поворота, рядом с предком */
export interface Link { a: string; b: string; kind: StepKind | 'couple'; from?: [string, string] }
export interface Diagram { cells: Cell[]; links: Link[]; cols: number; rows: number;
  /** поворот у общего предка: кем второй ребёнок приходится первому (брат, сестра) — подпись между ними */
  turns: {a: string; b: string}[] }

export function stepKind(kin: Kinship, a: string, b: string): StepKind {
  if (kin.P[a].p.includes(b)) return 'up'
  if (kin.P[b].p.includes(a)) return 'down'
  return 'spouse'
}

export function layout(kin: Kinship, path: string[]): Diagram {
  const cells: Cell[] = [{id: path[0], col: 0, row: 0, onPath: true}], links: Link[] = [], turns: Diagram['turns'] = []
  let prev: StepKind | null = null
  for (let i = 1; i < path.length; i++) {
    const a = path[i - 1], b = path[i], k = stepKind(kin, a, b), c = cells[cells.length - 1]
    const turn = (prev === 'up' && k === 'down') || (prev === 'down' && k === 'up')
    const col = c.col + (k === 'spouse' || turn ? 1 : 0), row = c.row + (k === 'up' ? -1 : k === 'down' ? 1 : 0)
    let link: Link = {a, b, kind: k}
    if (prev === 'up' && k === 'down') {
      const before = path[i - 2]
      turns.push({a: before, b})
      // второй общий родитель — рядом с предком, линия к ребёнку идёт от пары, как в обычном дереве
      const other = kin.P[before].p.find(p => p !== a && kin.P[b].p.includes(p) && kin.P[p])
      if (other) {
        cells.push({id: other, col, row: c.row, onPath: false})
        links.push({a, b: other, kind: 'couple'})
        link = {a, b, kind: 'down', from: [a, other]}
      }
    }
    cells.push({id: b, col, row, onPath: true})
    links.push(link)
    prev = k
  }
  const top = Math.min(...cells.map(c => c.row))
  for (const c of cells) c.row -= top
  return {cells, links, turns, cols: Math.max(...cells.map(c => c.col)) + 1, rows: Math.max(...cells.map(c => c.row)) + 1}
}
