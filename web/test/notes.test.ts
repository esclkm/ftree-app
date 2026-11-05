// Заметки для Claude (src/app/notes/model.ts): включение по адресу, повторное «＋», выгрузка текстом.
import {beforeAll, describe, expect, inject, it} from 'vitest'
import {provide} from '../src/data'
import {marksOf, type NotesState, notes, notesActions, notesEnabled, photoName, type Subject, toMarkdown} from '../src/app/notes/model'

const savva: Subject = {type: 'person', id: 'aaa-001-aaa-001', name: 'Савва Ясенев', path: '/people/savva-yasenev',
  file: '3_research/search/biographies/20_БИО_Савва_Ясенев.md'}
const empty: NotesState = {enabled: true, open: false, general: '', items: []}
const mem = () => { const m = new Map<string, string>()
  return {getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), removeItem: (k: string) => void m.delete(k)} }

describe('режим заметок', () => {
  it('включён без параметров; ?notes=off выключает и запоминает, ?notes — возвращает', () => {
    const s = mem()
    expect(notesEnabled('', s)).toBe(true)
    expect(notesEnabled('?notes=off', s)).toBe(false)
    expect(notesEnabled('', s)).toBe(false)
    expect(notesEnabled('?notes', s)).toBe(true)
    expect(notesEnabled('', s)).toBe(true)
  })
  it('тот же кусок второй раз — не новая заметка, а переход к ней; приговор фото обновляется', () => {
    const line = {subject: savva, kind: 'lifeline' as const, where: 'Линия жизни, строка 3', text: '1944 (осень) — переезд в Брест'}
    let s = notes.reducer(empty, notesActions.add(line))
    s = notes.reducer(s, notesActions.add(line))
    expect(s.items).toHaveLength(1)
    expect(s.open).toBe(true)
    expect(s.focus).toBe(s.items[0].key)
    const photo = {subject: savva, kind: 'photo' as const, photo: {url: '/media/l/c18f7d_Минск_вокзал.jpg'}}
    s = notes.reducer(s, notesActions.add({...photo, verdict: 'better'}))
    s = notes.reducer(s, notesActions.add({...photo, verdict: 'remove', quiet: true}))
    expect(s.items).toHaveLength(2)
    expect(s.items[1].verdict).toBe('remove')
    expect(s.items[1]).not.toHaveProperty('quiet')
  })
  it('имя фото на сайте → имя файла', () => {
    expect(photoName('/media/l/c18f7d_%D0%9C%D0%B8%D0%BD%D1%81%D0%BA.jpg')).toBe('Минск')
    expect(photoName('/media/Феврония-Ясенева_портрет.jpg')).toBe('Феврония-Ясенева_портрет')
  })
})

// надписи — из данных сайта вымышленного образца (data/ui.json пишет site_export.py; test/sampleSite.mjs)
beforeAll(() => {
  provide({dict: inject('sampleUi').i18n})
})

describe('выгрузка для Claude', () => {
  it('по людям: номер, биография, кусок, свои слова; «оставить» без слов — одной строкой', () => {
    let s = notes.reducer(empty, notesActions.add({subject: savva, kind: 'lifeline', where: 'Линия жизни, строка 3', text: '1944 (осень) — переезд', lang: 'es'}))
    s = notes.reducer(s, notesActions.edit({key: s.items[0].key, comment: 'Не осень, а весна 1945 — Аудио 05, 12:30'}))
    s = notes.reducer(s, notesActions.add({subject: savva, kind: 'photo', photo: {url: '/media/l/abc123_Брест_вокзал.jpg'}, verdict: 'ok'}))
    s = notes.reducer(s, notesActions.setGeneral('Везде «Сава», не «Савватий»'))
    const md = toMarkdown(s, 'ru', new Date(2026, 8, 29))
    expect(md).toContain('# Заметки к родословной — 29.09.2026')
    expect(md).toContain('## Общее\n\nВезде «Сава», не «Савватий»')
    expect(md).toContain('## Савва Ясенев — человек, `aaa-001-aaa-001`')
    expect(md).toContain('биография: `3_research/search/biographies/20_БИО_Савва_Ясенев.md`')
    expect(md).toContain('1. **Строка линии жизни** · Линия жизни, строка 3 · страница на ES\n   > 1944 (осень) — переезд\n   Не осень, а весна 1945')
    expect(md).toContain('Проверены, оставить (1): `Брест_вокзал`')
  })
  it('на языке страницы: заголовок, вид куска, пометка; другой язык заметки — помечен', () => {
    const s = notes.reducer(empty, notesActions.add({subject: savva, kind: 'lifeline', where: 'Linia życia, wiersz 5', text: '1954 — аттестат', verdict: 'wrong_date', lang: 'ru'}))
    const md = toMarkdown(s, 'pl', new Date(2026, 8, 29))
    expect(md).toContain('# Notatki do drzewa genealogicznego — 29.09.2026')
    expect(md).toContain('## Савва Ясенев — osoba, `aaa-001-aaa-001`')
    expect(md).toContain('Strona: `/pl/people/savva-yasenev`')
    expect(md).toContain('1. **Wiersz linii życia** · Linia życia, wiersz 5 · strona w RU · **błędna data**')
  })
  it('пометка строки — в заголовке пункта; у строк свой список, у абзаца — никакого', () => {
    const s = notes.reducer(empty, notesActions.add({subject: savva, kind: 'lifeline', where: 'Линия жизни, строка 5', text: '1954 — аттестат', verdict: 'wrong_date'}))
    expect(toMarkdown(s)).toContain('1. **Строка линии жизни** · Линия жизни, строка 5 · **неверная дата**')
    expect(marksOf({kind: 'lifeline'})).toContain('other_person')
    expect(marksOf({kind: 'para'})).toEqual([])
    expect(marksOf({kind: 'photo', photo: {url: '/media/x.jpg'}})).toContain('better')
  })
})
