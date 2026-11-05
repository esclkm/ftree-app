// Схема родства: клетки цепочки не налезают друг на друга, поворот у общего предка уходит вправо, супруг — та же строка.
import {describe, expect, it} from 'vitest'
import type {Sex} from '../src/data'
import {layout} from '../src/kin/diagram'
import {Kinship, type Person} from '../src/kin/graph'

const people: Person[] = []
const P = (id: string, g: Sex, p: string[] = [], s: string[] = []) =>
  people.push({id, g, p, s, x: {slug: id, url: `people/${id}.html`, ru: id, en: id, pl: id}})
P('roman', 'M', [], ['efimia']); P('efimia', 'F', [], ['roman'])
P('grigory', 'M', ['roman', 'efimia']); P('vasily', 'M', ['roman', 'efimia'])
P('sergey', 'M', ['grigory']); P('alex', 'M', ['sergey']); P('pavel', 'M', ['alex'])
P('olga', 'F', ['vasily'], ['basilio']); P('basilio', 'M', [], ['olga'])
const kin = new Kinship(people)

describe('схема родства', () => {
  const path = kin.relation('pavel', 'basilio', 'ru')!.path
  const d = layout(kin, path)
  const at = (id: string) => d.cells.find(c => c.id === id)!

  it('цепочка — от меня вверх до прадеда, вниз к Ольге, вправо к мужу', () =>
    expect(path).toEqual(['pavel', 'alex', 'sergey', 'grigory', 'roman', 'vasily', 'olga', 'basilio']))
  it('предок наверху, рядом — второй родитель', () => {
    expect(at('roman')).toMatchObject({col: 0, row: 0})
    expect(at('efimia')).toMatchObject({col: 1, row: 0, onPath: false})
  })
  it('спуск — в соседнем столбце, муж — справа на той же строке', () => {
    expect(at('vasily')).toMatchObject({col: 1, row: 1})
    expect(at('olga')).toMatchObject({col: 1, row: 2})
    expect(at('basilio')).toMatchObject({col: 2, row: 2})
    expect(at('pavel')).toMatchObject({col: 0, row: 4})
  })
  it('клетки не совпадают', () => expect(new Set(d.cells.map(c => `${c.col},${c.row}`)).size).toBe(d.cells.length))
  it('у поворота — подпись между братьями', () => expect(d.turns).toEqual([{a: 'grigory', b: 'vasily'}]))
})
