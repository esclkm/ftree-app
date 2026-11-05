// Какие линии дерева подсвечивать на пути «я → отец → дед → дядя»
import {describe, expect, it} from 'vitest'
import {onPath, pathEdges} from '../src/tree/path'

const edges = pathEdges(['me', 'father', 'gf', 'uncle'])

describe('путь родства на дереве', () => {
  it('линия от пары родителей к ребёнку — на пути, если один из родителей сосед на пути', () =>
    expect(onPath(edges, ['father', 'mother'], ['me'])).toBe(true))
  it('линия к брату — не на пути', () => expect(onPath(edges, ['father', 'mother'], ['sister'])).toBe(false))
  it('направление линии не важно', () => expect(onPath(edges, ['gf'], ['father'])).toBe(true))
  it('люди на пути, но не соседи — не линия пути', () => expect(onPath(edges, ['me'], ['gf'])).toBe(false))
  it('нет пути — ничего не подсвечено', () => expect(onPath(pathEdges([]), ['a'], ['b'])).toBe(false))
})
