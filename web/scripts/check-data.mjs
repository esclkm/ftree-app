// Данные сайта — ровно по схеме: каждый файл data/*.json, который выгрузил site_export.py, сверяется с web/schema/.
// Тест (test/schema.test.ts) зовёт это на данных вымышленного образца; данные нашего дерева — проверка данных:
//   node scripts/check-data.mjs <папка data>      (npm run check-data без папки — data/ выгрузки дерева после rodo site export --data)
import Ajv2020 from 'ajv/dist/2020.js'
import addFormats from 'ajv-formats'
import { execFileSync } from 'node:child_process'
import { readdirSync, readFileSync } from 'node:fs'
import { dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const SCHEMA = join(dirname(fileURLToPath(import.meta.url)), '..', 'schema')
const KIND = [[/^index\.json$/, 'index'], [/^ui\.json$/, 'ui'], [/^gallery\.json$/, 'gallery'], [/^research\.json$/, 'research'],
  [/^review\.json$/, 'review'], [/^progress\.json$/, 'progress'], [/^people\//, 'person'], [/^places\//, 'place'], [/^sources\//, 'source'], [/^docs\//, 'doc']]

/** Ошибки по всем файлам папки data (пусто — всё по схеме) и сколько файлов проверено. */
export function checkData(dir) {
  const ajv = new Ajv2020({ allErrors: true, strict: false })
  addFormats(ajv)
  for (const name of readdirSync(SCHEMA).filter(n => n.endsWith('.schema.json')))
    ajv.addSchema(JSON.parse(readFileSync(join(SCHEMA, name), 'utf8')), name)
  const files = readdirSync(dir, { recursive: true }).map(String).filter(n => n.endsWith('.json')).sort()
  const bad = []
  for (const file of files) {
    const path = relative(dir, join(dir, file)).split('\\').join('/')
    const kind = KIND.find(([rx]) => rx.test(path))?.[1]
    const check = kind && ajv.getSchema(`${kind}.schema.json`)
    if (!check) { bad.push(`${path}: непонятно, чей это файл`); continue }
    if (!check(JSON.parse(readFileSync(join(dir, file), 'utf8'))))
      bad.push(...(check.errors ?? []).map(e => `${path} ${e.instancePath} ${e.message}`))
  }
  return { files: files.length, bad }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  // без папки — data/ выгрузки дерева (paths.py SITE_EXPORT: FTREE_ROOT или дерево, в котором стоишь)
  const app = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
  const dir = process.argv[2] ?? join(execFileSync(join(app, 'tools', 'py'), [join(app, 'tools', 'scripts', 'paths.py'), 'SITE_EXPORT'],
    { encoding: 'utf8' }).trim(), 'data')
  const { files, bad } = checkData(dir)
  if (!files) { console.error(`${dir}: нет файлов данных — сначала rodo site export --data`); process.exit(1) }
  for (const line of bad.slice(0, 50)) console.log(line)
  console.log(bad.length ? `Данные сайта не по схеме: ${bad.length} (файлов ${files})` : `Данные сайта по схеме: файлов ${files}`)
  process.exit(bad.length ? 1 : 0)
}
