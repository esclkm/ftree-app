// Братья и сёстры на схеме — по рождению, человек в центре — на своём месте среди них
import {describe, expect, it} from 'vitest'
import type {TreePerson} from '../src/data'
import {birthOrder} from '../src/tree/order'

const P = (id: string, parents: string[] = [], children: string[] = []) =>
  ({id, data: {}, rels: {parents, spouses: [], children}}) as unknown as TreePerson
// у отца дети уже по рождению: 1828, 1831, 1836, 1839
const people = [P('father', [], ['s1828', 'e1831', 'e1836', 'n1839']), P('s1828', ['father']), P('e1831', ['father']),
  P('e1836', ['father']), P('n1839', ['father']), P('stranger')]

describe('порядок братьев и сестёр', () => {
  it('центр не первым, а по месту среди детей отца', () =>
    expect([people[3], people[4], people[1], people[2]].sort(birthOrder(people)).map(p => p.id))
      .toEqual(['s1828', 'e1831', 'e1836', 'n1839']))
  it('без общего родителя — не двигаем', () => expect(birthOrder(people)(people[1], people[5])).toBe(0))
})
