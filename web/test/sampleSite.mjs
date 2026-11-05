// Перед тестами: данные сайта вымышленного образца (tools/sample/sample.ged → rodo init + импорт → site_export.py --data)
// во временной папке. Тесты берут их через inject('sampleData') — папка data, inject('sampleUi') — data/ui.json.
// Собранный сайт нашего дерева (4_outputs/site) тесты не читают. Типы — test/provided.d.ts.
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

export default function setup(project) {
  const tmp = mkdtempSync(join(tmpdir(), 'ftree-web-sample-'))
  const tools = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'tools')
  execFileSync(join(tools, 'py'), [join(tools, 'scripts', 'tests', 'sample_tree.py'), '--site', join(tmp, 'site')], { stdio: 'inherit' })
  const data = join(tmp, 'site', 'data')
  project.provide('sampleData', data)
  project.provide('sampleUi', JSON.parse(readFileSync(join(data, 'ui.json'), 'utf8')))
  return () => rmSync(tmp, { recursive: true, force: true })
}
