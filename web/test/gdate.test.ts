// Даты GEDCOM на языке страницы: та же запись, что в карточке (tools/scripts/dates.py)
import {describe, expect, it} from 'vitest'
import {fmtGed} from '../src/gdate'

describe('даты GEDCOM по-русски', () => {
  it('точная дата — полностью', () => expect(fmtGed('1971-03-05', 'ru')).toBe('5 марта 1971'))
  it('только месяц', () => expect(fmtGed('1986-02', 'ru')).toBe('февраль 1986'))
  it('около', () => expect(fmtGed('ABT 1935', 'ru')).toBe('ок. 1935'))
  it('до мая — месяц в родительном', () => expect(fmtGed('BEF 1944-05', 'ru')).toBe('до мая 1944'))
  it('между — в творительном', () => expect(fmtGed('BET 2024-10 AND 2025-08', 'ru')).toBe('между октябрём 2024 и августом 2025'))
  it('десятилетие', () => expect(fmtGed('BET 1950 AND 1959', 'ru')).toBe('1950-е'))
  it('всё это время', () => expect(fmtGed('FROM 1941 TO 1945', 'ru')).toBe('1941–1945'))
  it('несколько десятилетий', () => expect(fmtGed('FROM 1960 TO 1979', 'ru')).toBe('1960-е–1970-е'))
  it('десятилетие целиком — всё ещё годы', () => expect(fmtGed('FROM 1960 TO 1969', 'ru')).toBe('1960–1969'))
  it('слова из источника остаются', () => expect(fmtGed('AFT 1945 (после войны)', 'ru')).toBe('после 1945 (после войны)'))
  it('даты нет — только слова', () => expect(fmtGed('(без даты)', 'ru')).toBe('(без даты)'))
  it('не дата — как есть', () => expect(fmtGed('при Польше', 'ru')).toBe('при Польше'))
})

describe('даты GEDCOM на других языках', () => {
  it('испанский', () => expect(fmtGed('ABT 1935', 'es')).toBe('hacia 1935'))
  it('польский', () => expect(fmtGed('BET 1941 AND 1945', 'pl')).toBe('między 1941 a 1945'))
  it('английский: десятилетие', () => expect(fmtGed('BET 1950 AND 1959', 'en')).toBe('1950s'))
  it('английский: точная дата', () => expect(fmtGed('AFT 1971-03-05', 'en')).toBe('after 5 March 1971'))
  it('польский: месяц после «ok.» — римской цифрой', () => expect(fmtGed('ABT 1986-02', 'pl')).toBe('ok. II 1986'))
  it('польский: месяц без приставки — словом', () => expect(fmtGed('1986-02', 'pl')).toBe('luty 1986'))
  it('частые слова переводятся', () => expect(fmtGed('BET 1964 AND 1976 (детство, примерно)', 'es')).toBe('entre 1964 y 1976 (infancia, aproximadamente)'))
  it('редкие слова — как в источнике', () => expect(fmtGed('1923 (ст. Лесогорск)', 'en')).toBe('1923 (ст. Лесогорск)'))
  it('только слова — переводятся', () => expect(fmtGed('(без даты)', 'pl')).toBe('(bez daty)'))
})
