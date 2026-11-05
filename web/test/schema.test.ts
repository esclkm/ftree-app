// Данные сайта — ровно по схеме: каждый файл data/*.json, который выгрузил site_export.py, проверяется web/schema/.
// Здесь — на данных вымышленного образца (test/sampleSite.ts); данные нашего дерева сверяет проверка данных
// `npm run check-data` (после rodo site export --data). Схема и типы TypeScript (src/data/schema.gen.ts) не должны
// разойтись: поменял схему — npm run schema.
import {describe, expect, inject, it} from 'vitest'
import generated from '../src/data/schema.gen.ts?raw'
import {checkData} from '../scripts/check-data.mjs'
import {generate} from '../scripts/schema-types.mjs'

describe('схема данных', () => {
  it('типы TypeScript не отстали от схемы', async () => expect(await generate()).toBe(generated))

  it('все файлы data/ образца по схеме', () => {
    const {files, bad} = checkData(inject('sampleData'))
    expect(files).toBeGreaterThan(30)
    expect(bad.slice(0, 20)).toEqual([])
  })
})
