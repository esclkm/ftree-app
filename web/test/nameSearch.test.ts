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

describe('любой язык и запись', () => {
  const rakitin = ['Сергей Ракитин', 'Siarhei Rakitin', 'Sergiusz Rakitin']
  const hleb = ['Глеб Карашко', 'Gleb Karashko', 'Gleb Karaszko']
  it('язык и порядок слов не важны, можно вперемешку', () => {
    expect(matchesName(rakitin, queryWords('Rakitin Сергей'))).toBe(true)
    expect(matchesName(rakitin, queryWords('ракитин siarhei'))).toBe(true)
  })
  it('другая запись латиницей — по скелету', () => {
    expect(matchesName(hleb, queryWords('Hleb Karaško'))).toBe(true)
    expect(matchesName(['Алёна Борисова'], queryWords('Barysava Alyona'))).toBe(true)
    expect(matchesName(['Прокоп Ракитин'], queryWords('Prakop'))).toBe(true)
    expect(matchesName(['Иван Харак'], queryWords('Charak'))).toBe(false)  // польское ch = х — пока не умеем
    expect(matchesName(['Иван Харак'], queryWords('Kharak Ivan'))).toBe(true)
  })
  it('не та раскладка', () => {
    expect(matchesName(rakitin, queryWords('Hfrbnby'))).toBe(true)
    expect(matchesName(rakitin, queryWords('кфлшешт'))).toBe(true)
  })
  it('скелет не ловит лишнего', () => {
    expect(matchesName(rakitin, queryWords('ан'))).toBe(false)
    expect(matchesName(rakitin, queryWords('Карашко'))).toBe(false)
    expect(nameRank(rakitin, queryWords('Hfrbnby'))).toBe(3)
  })
})
