// Части приложения, которые не видно глазами: разбор текста фактов, загрузка data/*.json, язык из ссылки.
import {renderToStaticMarkup} from 'react-dom/server'
import {MemoryRouter} from 'react-router'
import {afterEach, describe, expect, it, vi} from 'vitest'
import type {SiteIndex} from '../src/data/schema.gen'
import {dataQuery} from '../src/app/api'
import {fieldLines} from '../src/app/BioMd'
import {render} from '../src/app/Md'
import {withLang} from '../src/app/LangRoot'
import {yearOf} from '../src/app/timeline'
import {startLang} from '../src/app/ui'
import {cleanSlug, lookup} from '../src/app/useIndex'

const index: SiteIndex = {
  schema: 'index/1', built: '2026-09-28T12:00:00+00:00', start: 'aaa-001-aaa-001', divorces: {}, branches: [],
  people: [{id: 'aaa-001-aaa-001', slug: 'sergey-yasenev-1929', names: {ru: 'Сергей Ясенев', en: 'Sergey Yasenev', pl: 'Siergiej Jasieniew'},
    sex: 'M', life: '1929–2000', parents: [], spouses: [], children: []}],
  places: [{id: 'bbb-001-bbb-001', slug: 'verbichi', names: {ru: 'Вербичи'}, people: 1}],
  sources: [{id: 'ccc-001-ccc-001', slug: 'audio-01', title: 'Аудио 01', provenance: 'family'}],
}
// data-discover — служебная метка React Router у ссылок, к делу не относится
const html = (text: string) =>
  renderToStaticMarkup(<MemoryRouter>{render(text, lookup(index), 'ru')}</MemoryRouter>).replaceAll(' data-discover="true"', '')

describe('текст фактов', () => {
  it('ссылки по номеру → адреса страниц', () => {
    expect(html('жил у [сына Сергея](person:aaa-001-aaa-001) в [Вербичах](place:bbb-001-bbb-001)'))
      .toBe('жил у <a href="/ru/people/sergey-yasenev-1929">сына Сергея</a> в <a href="/ru/places/verbichi">Вербичах</a>')
  })
  it('номера нет в дереве — остаются слова', () => expect(html('[кто-то](person:zzz-999-zzz-999)')).toBe('кто-то'))
  it('файл — только подпись', () => expect(html('[фото](media:Савва.jpg)')).toBe('фото'))
  it('жирный и курсив, вложенные ссылки', () =>
    expect(html('**был в [Вербичах](place:bbb-001-bbb-001)** и *всё*'))
      .toBe('<b>был в <a href="/ru/places/verbichi">Вербичах</a></b> и <i>всё</i>'))
  it('пометка в обратных кавычках', () => expect(html('годы — `[вывод]`')).toBe('годы — <code>[вывод]</code>'))
  it('HTML в тексте — просто текст', () => expect(html('<script>alert(1)</script>')).toBe('&lt;script&gt;alert(1)&lt;/script&gt;'))
  it('адрес сайта — ссылка наружу', () =>
    expect(html('см. https://maz.by/x')).toBe('см. <a href="https://maz.by/x" target="_blank" rel="noreferrer noopener">https://maz.by/x</a>'))
  it('[подпись](адрес сайта) — ссылка наружу с подписью', () =>
    expect(html('[PastVu 862159](https://pastvu.com/p/862159)')).toBe('<a href="https://pastvu.com/p/862159" target="_blank" rel="noreferrer noopener">PastVu 862159</a>'))
})

describe('загрузка data/*.json', () => {
  afterEach(() => { vi.unstubAllGlobals() })
  const answer = (body: string, type: string, status = 200) => vi.stubGlobal('fetch', vi.fn(async () => new Response(body, {status, headers: {'content-type': type}})))
  const call = (path: string) => dataQuery(path, {} as never, {})
  it('JSON — данные', async () => { answer('{"a":1}', 'application/json'); expect(await call('index.json')).toEqual({data: {a: 1}}) })
  it('хостинг вместо файла отдал главную (200, HTML) — «нет такого»', async () => {
    answer('<!doctype html>', 'text/html'); expect(await call('people/x.json')).toEqual({error: {status: 'not_found', path: 'people/x.json'}})
  })
  it('404 — «нет такого»', async () => { answer('', 'text/plain', 404); expect((await call('p.json')).error?.status).toBe('not_found') })
  it('нет связи', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('offline') }))
    expect((await call('p.json')).error?.status).toBe('network')
  })
})

describe('язык и адреса', () => {
  it('язык в пути — главный', () => expect(startLang('?lang=es', 'pl', '/en/people/x')).toBe('en'))
  it('язык из ?lang важнее запомненного', () => expect(startLang('?lang=es', 'pl', '/people/x')).toBe('es'))
  it('запомненный, если в ссылке нет', () => expect(startLang('', 'pl', '/')).toBe('pl'))
  it('непонятный — русский', () => expect(startLang('?lang=xx', 'de', '/')).toBe('ru'))
  it('старая ссылка на человека', () => expect(withLang('/people/sergey-yasenev-1929.html', '?lang=es', '', 'es')).toBe('/es/people/sergey-yasenev-1929'))
  it('старое дерево с человеком в центре', () => expect(withLang('/tree.html', '', '#sergey-yasenev-1929', 'ru')).toBe('/ru/tree#sergey-yasenev-1929'))
  it('главная', () => expect(withLang('/index.html', '', '', 'pl')).toBe('/pl'))
  it('«я» в ссылке остаётся', () => expect(withLang('/people/x', '?me=pavel&lang=en', '', 'en')).toBe('/en/people/x?me=pavel'))
  it('старые ссылки .html', () => expect(cleanSlug('sergey-yasenev-1929.html')).toBe('sergey-yasenev-1929'))
})

describe('текст биографии', () => {
  it('перенос внутри абзаца — пробел', () => expect(fieldLines('пять раз меняли\nгосударство')).toBe('пять раз меняли\nгосударство'))
  it('строки шапки — каждая с новой строки', () =>
    expect(fieldLines('**Кто:** Сергей\n**Родился:** 1929')).toBe('**Кто:** Сергей  \n**Родился:** 1929'))
  it('после пустой строки — без лишнего переноса', () => expect(fieldLines('текст\n\n**Кто:** он')).toBe('текст\n\n**Кто:** он'))
})

describe('шкала лет', () => {
  const d = (sort: number) => ({value: '', ru: '', sort})
  it('22.03.1929 — чуть правее начала 1929', () => expect(yearOf(d(19290322))).toBeCloseTo(1929 + 2 / 12 + 21 / 365, 5))
  it('только год — ровно начало года', () => expect(yearOf(d(19290000))).toBe(1929))
  it('«после 1949» (+99) не уходит в следующий год', () => expect(Math.floor(yearOf(d(19490099)))).toBe(1949))
})
