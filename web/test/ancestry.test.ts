// Расчёты графиков предков (src/app/charts/ancestry.ts) на выдуманной семье: годы, места в веере, глубина линий.
import {describe, expect, it} from 'vitest'
import type {SiteIndex} from '../src/data/schema.gen'
import {ancestorSlots, fanCount, genOf, lineDepths, yearsOf} from '../src/app/charts/ancestry'
import {lookup} from '../src/app/useIndex'

type P = {id: string; sex: 'M' | 'F'; life?: string; parents?: string[]}
function family(ps: P[]) {
  const people = ps.map(p => ({id: p.id, slug: p.id, names: {ru: p.id}, sex: p.sex, life: p.life ?? '', parents: p.parents ?? [],
    spouses: [], children: ps.filter(c => c.parents?.includes(p.id)).map(c => c.id)}))
  return lookup({people, places: [], sources: []} as unknown as SiteIndex)
}

describe('yearsOf', () => {
  it('читает годы жизни в любом виде', () => {
    expect(yearsOf('1877–1948')).toEqual({born: 1877, died: 1948, alive: false, approx: false})
    expect(yearsOf('1986')).toMatchObject({born: 1986, alive: true})
    expect(yearsOf('~1850–?')).toMatchObject({born: 1850, died: undefined, alive: false, approx: true})
    expect(yearsOf('?–<1920')).toMatchObject({born: undefined, died: 1920})
    expect(yearsOf('')).toMatchObject({born: undefined, alive: false})
  })
})

describe('ancestorSlots', () => {
  // мать записана первой — отец всё равно встаёт в слот 2
  const ix = family([
    {id: 'me', sex: 'F', life: '1990', parents: ['mom', 'dad']},
    {id: 'dad', sex: 'M', life: '1960', parents: ['gf']},
    {id: 'mom', sex: 'F', life: '1962'},
    {id: 'gf', sex: 'M', life: '1930–2000', parents: ['ggm']},
    {id: 'ggm', sex: 'F', life: '~1905–1980'},
  ])
  const s = ancestorSlots(ix, 'me', 3)
  it('отец — 2k, мать — 2k+1', () => {
    expect(s[1]?.id).toBe('me'); expect(s[2]?.id).toBe('dad'); expect(s[3]?.id).toBe('mom')
    expect(s[4]?.id).toBe('gf'); expect(s[5]).toBeUndefined(); expect(s[9]?.id).toBe('ggm')
  })
  it('считает известных', () => expect(fanCount(s, 3)).toEqual({known: 4, total: 14}))
  it('поколение слота', () => { expect(genOf(1)).toBe(0); expect(genOf(3)).toBe(1); expect(genOf(15)).toBe(3) })
})

describe('lineDepths', () => {
  const ix = family([
    {id: 'me', sex: 'M', parents: ['d', 'm']},
    {id: 'd', sex: 'M', parents: ['g1', 'g2']}, {id: 'm', sex: 'F'},
    {id: 'g1', sex: 'M', parents: ['a', 'b']}, {id: 'g2', sex: 'F'},
    {id: 'a', sex: 'M', life: '1880–1940', parents: ['old']}, {id: 'b', sex: 'F', life: '1885'},
    {id: 'old', sex: 'M', life: '~1850–?', parents: ['older']}, {id: 'older', sex: 'M'},
  ])
  const lines = lineDepths(ix, 'me')
  it('клин на каждого прадеда: самый ранний год и глубина', () => {
    expect(lines).toHaveLength(8)
    expect(lines[0]).toMatchObject({year: 1850, generations: 5, people: 3})
    expect(lines[0]?.earliest?.id).toBe('old')
    expect(lines[1]).toMatchObject({year: 1885, generations: 3, people: 1})
    expect(lines[2]).toBeUndefined()
  })
})
