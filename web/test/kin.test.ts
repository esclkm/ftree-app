// Родство на выдуманной семье: у каждого известно, кем он приходится «мне» (me). Проверяем названия на всех языках,
// цепочку «через кого» и случаи, где раньше ошибались: падежи, primo segundo, полу-брат, свояк, сват.
import {describe, expect, it} from 'vitest'
import type {Lang, Sex} from '../src/data'
import {Kinship, type Person} from '../src/kin/graph'

const people: Person[] = []
const P = (id: string, g: Sex, p: string[] = [], s: string[] = []) =>
  people.push({id, g, p, s, x: {slug: id, url: `people/${id}.html`, ru: id, en: id, pl: id}})
P('ggf', 'M', [], ['ggm']); P('ggm', 'F', [], ['ggf'])
P('gf', 'M', ['ggf', 'ggm'], ['gm']); P('gm', 'F', [], ['gf'])
P('stefan', 'M', ['ggf', 'ggm'])                                   // брат деда
P('ggaunt', 'F', ['ggf', 'ggm'], ['ggauntH']); P('ggauntH', 'M', [], ['ggaunt'])  // сестра деда и её муж
P('fcousin', 'M', ['stefan']); P('cousin2', 'M', ['fcousin'])      // сын и внук брата деда
P('father', 'M', ['gf', 'gm'], ['mother', 'mother2']); P('mother', 'F', ['mgf'], ['father']); P('mother2', 'F', [], ['father'])
P('mgf', 'M'); P('muncle', 'M', ['mgf'])                           // дед и дядя по матери
P('uncle', 'M', ['gf', 'gm'], ['uncleW']); P('uncleW', 'F', [], ['uncle'])
P('aunt', 'F', ['gf', 'gm'], ['auntH']); P('auntH', 'M', [], ['aunt'])
P('cousin', 'M', ['uncle', 'uncleW']); P('cousinSon', 'M', ['cousin'])
P('me', 'M', ['father', 'mother'], ['wife', 'ex'])
P('sister', 'F', ['father', 'mother'], ['sisterH']); P('sisterH', 'M', [], ['sister']); P('niece', 'F', ['sister', 'sisterH'])
P('halfbro', 'M', ['father', 'mother2'])
P('ex', 'F', [], ['me'])
P('wife', 'F', ['wf', 'wm'], ['me']); P('wf', 'M', [], ['wm']); P('wm', 'F', [], ['wf'])
P('wsis', 'F', ['wf', 'wm'], ['wsisH']); P('wsisH', 'M', [], ['wsis']); P('wbro', 'M', ['wf', 'wm'])
P('son', 'M', ['me', 'wife'], ['sonW']); P('sonW', 'F', ['sonWF'], ['son']); P('sonWF', 'M')
P('stranger', 'F')

const kin = new Kinship(people, {'ex|me': '2010'})
const term = (X: string, L: Lang = 'ru') => kin.relation('me', X, L)?.term?.nom

describe('кровное родство по-русски', () => {
  it.each([
    ['father', 'отец'], ['gf', 'дед'], ['ggf', 'прадед'], ['uncle', 'дядя'], ['aunt', 'тётя'], ['stefan', 'двоюродный дед'],
    ['fcousin', 'двоюродный дядя'], ['cousin2', 'троюродный брат'], ['cousin', 'двоюродный брат'], ['cousinSon', 'двоюродный племянник'],
    ['sister', 'сестра'], ['halfbro', 'единокровный брат'], ['niece', 'племянница'], ['son', 'сын'], ['muncle', 'дядя'],
  ])('%s — %s', (X, want) => expect(term(X)).toBe(want))
})

describe('свойственники по-русски', () => {
  it.each([
    ['wife', 'жена'], ['ex', 'бывшая жена'], ['wf', 'тесть'], ['wm', 'тёща'], ['wsis', 'свояченица'], ['wbro', 'шурин'],
    ['wsisH', 'свояк'], ['uncleW', 'жена дяди'], ['auntH', 'муж тёти'], ['sisterH', 'зять'], ['mother2', 'мачеха'],
    ['sonW', 'невестка'], ['sonWF', 'сват'],
    ['ggauntH', 'муж двоюродной бабушки'],  // родительный падеж прилагательного: «двоюродной», не «двоюродного»
  ])('%s — %s', (X, want) => expect(term(X)).toBe(want))
})

describe('другие языки', () => {
  it.each([
    ['uncle', 'pl', 'stryj'], ['muncle', 'pl', 'wuj'], ['fcousin', 'pl', 'kuzyn ojca'], ['stefan', 'pl', 'brat dziadka'],
    ['cousin2', 'pl', 'kuzyn drugiego stopnia'], ['niece', 'pl', 'siostrzenica'], ['halfbro', 'pl', 'brat przyrodni'], ['wf', 'pl', 'teść'],
    ['stefan', 'en', 'great-uncle'], ['fcousin', 'en', 'first cousin once removed'], ['cousin2', 'en', 'second cousin'],
    ['halfbro', 'en', 'half-brother'], ['sonWF', 'en', "daughter-in-law's father"], ['ex', 'en', 'ex-wife'],
    ['fcousin', 'es', 'tío segundo'], ['cousin2', 'es', 'primo segundo'], ['cousin', 'es', 'primo'], ['stefan', 'es', 'tío abuelo'],
    ['sonWF', 'es', 'consuegro'], ['ggauntH', 'es', 'esposo de la tía abuela'],
  ] as [string, Lang, string][])('%s (%s) — %s', (X, L, want) => expect(term(X, L)).toBe(want))
})

describe('цепочка и крайние случаи', () => {
  it('через кого: от меня к двоюродному брату через отца, деда и дядю', () =>
    expect(kin.relation('me', 'cousin', 'ru')!.path).toEqual(['me', 'father', 'gf', 'uncle', 'cousin']))
  it('брак на пути: тесть через жену', () => expect(kin.relation('me', 'wf', 'ru')!.path).toEqual(['me', 'wife', 'wf']))
  it('сам себе', () => expect(kin.relation('me', 'me', 'ru')!.self).toBe(true))
  it('нет связи', () => expect(kin.relation('me', 'stranger', 'ru')).toBeNull())
  it('нет в данных (пустая карточка дерева)', () => expect(kin.relation('me', 'nobody', 'ru')).toBeNull())
  it('все в семье, кроме чужого, названы на всех языках', () => {
    for (const L of ['ru', 'en', 'es', 'pl'] as Lang[])
      for (const d of people) if (d.id !== 'stranger' && d.id !== 'me') expect(term(d.id, L), `${d.id} ${L}`).toBeTruthy()
  })
})
