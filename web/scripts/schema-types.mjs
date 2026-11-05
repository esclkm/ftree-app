// Типы TypeScript из схемы данных (web/schema/*.schema.json) → src/data/schema.gen.ts. Руками этот файл не правим:
// поменялась схема — npm run schema (тест test/schema.test.ts скажет, если забыли).
import { compile } from 'json-schema-to-typescript'
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const web = join(dirname(fileURLToPath(import.meta.url)), '..')
const dir = join(web, 'schema')
const load = name => JSON.parse(readFileSync(join(dir, name), 'utf8'))

// одна корневая схема на все файлы — чтобы общие части (Date, Fact …) стали одним типом, а не копией в каждом
const root = {
  title: 'SiteData',
  type: 'object',
  properties: { index: { $ref: 'index.schema.json' }, person: { $ref: 'person.schema.json' },
    place: { $ref: 'place.schema.json' }, source: { $ref: 'source.schema.json' }, ui: { $ref: 'ui.schema.json' }, gallery: { $ref: 'gallery.schema.json' },
    research: { $ref: 'research.schema.json' }, review: { $ref: 'review.schema.json' }, progress: { $ref: 'progress.schema.json' },
    doc: { $ref: 'doc.schema.json' }, site: { $ref: 'site.schema.json' } },
  required: ['index', 'person', 'place', 'source', 'ui', 'gallery', 'research', 'review', 'progress', 'doc', 'site'],
  additionalProperties: false,
}
// имена типов: у файлов — свои (заголовки схем — по-русски, для людей), у общих частей — как в common.schema.json,
// только Date → GDate, чтобы не спорить со встроенным Date
const TITLES = { index: 'SiteIndex', person: 'PersonFile', place: 'PlaceFile', source: 'SourceFile', ui: 'UiFile', gallery: 'GalleryFile', research: 'ResearchFile', review: 'ReviewFile', progress: 'ProgressFile', doc: 'DocFile', site: 'SiteFile' }
const RENAME = { Date: 'GDate' }

// генератор заводит новый тип там, где рядом со ссылкой на тип стоит описание, — описание у ссылок убираем
function strip(x) {
  if (Array.isArray(x)) return x.map(strip)
  if (x && typeof x === 'object') {
    const out = Object.fromEntries(Object.entries(x).map(([k, v]) => [k, strip(v)]))
    if (out.$ref) delete out.description
    return out
  }
  return x
}
const byId = Object.fromEntries(['common', 'index', 'person', 'place', 'source', 'ui', 'gallery', 'research', 'review', 'progress', 'doc', 'site'].map(n => {
  const s = strip(load(`${n}.schema.json`))
  if (TITLES[n]) s.title = TITLES[n]
  for (const [k, d] of Object.entries(s.$defs ?? {})) d.title = RENAME[k] ?? k
  return [`${n}.schema.json`, s]
}))

export async function generate() {
  const ts = await compile(root, 'SiteData', {
    cwd: dir,
    bannerComment: '// Создано scripts/schema-types.mjs из web/schema/*.schema.json — не править руками: npm run schema',
    additionalProperties: false,
    $refOptions: { resolve: { file: { read: f => JSON.stringify(byId[f.url.split('/').pop()]) } } },
  })
  return ts
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  writeFileSync(join(web, 'src/data/schema.gen.ts'), await generate())
  console.log('src/data/schema.gen.ts — готово')
}
