// Строка источника под фото: голые адреса — ссылкой с именем сайта, готовые ссылки — как были.
import {describe, expect, it} from 'vitest'
import {shortUrls} from '../src/app/shortUrls'

describe('shortUrls', () => {
  it('голый адрес → имя сайта', () => {
    expect(shortUrls('https://pastvu.com/p/862159 (из Госкаталога: https://goskatalog.ru/portal/#/collections?id=15211155)'))
      .toBe('[pastvu.com](https://pastvu.com/p/862159) (из Госкаталога: [goskatalog.ru](https://goskatalog.ru/portal/#/collections?id=15211155))')
  })
  it('готовая ссылка не меняется', () => {
    const s = '[PastVu 2327404](https://pastvu.com/p/2327404) · [https://x.org/a](https://x.org/a)'
    expect(shortUrls(s)).toBe(s)
  })
  it('www. не показываем; пусто — пусто', () => {
    expect(shortUrls('www: https://www.fotopolska.eu/1')).toBe('www: [fotopolska.eu](https://www.fotopolska.eu/1)')
    expect(shortUrls(undefined)).toBe('')
  })
})
