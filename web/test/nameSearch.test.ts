// Поиск по имени: слова в любом порядке, ё = е, надстрочные знаки не важны
import {describe, expect, it} from 'vitest'
import {matchesName, nameRank, queryWords} from '../src/nameSearch'

const prokop = ['Прокоп Ясенев', 'Prokop Yasenev', 'Prokop Jasieniew', '1935–~1947']

describe('nameSearch', () => {
  it('порядок слов не важен', () => {
    expect(matchesName(prokop, queryWords('Ясенев Прокоп'))).toBe(true)
    expect(matchesName(prokop, queryWords('прокоп ясенев'))).toBe(true)
    expect(matchesName(prokop, queryWords('jasieniew pr'))).toBe(true)
    expect(matchesName(prokop, queryWords('Ясенев 1935'))).toBe(true)
  })
  it('каждое слово должно найтись', () => {
    expect(matchesName(prokop, queryWords('Ясенев Мария'))).toBe(false)
    expect(matchesName(prokop, queryWords('   '))).toBe(false)
  })
  it('ё и надстрочные знаки', () => {
    expect(matchesName(['Пётр Ракитин'], queryWords('петр'))).toBe(true)
    expect(matchesName(['Zdzisław Jasieniew'], queryWords('zdzislaw'))).toBe(true)
  })
  it('начало имени — выше', () => {
    expect(nameRank(['Прокоп Ясенев'], queryWords('ясенев пр'))).toBe(0)
    expect(nameRank(['Прокоп Ясенев'], queryWords('сенев'))).toBe(2)
  })
})
