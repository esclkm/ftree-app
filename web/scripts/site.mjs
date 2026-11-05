// Сборщик сайта: папка выгрузки (data/*.json, media/, files/, site.json — их пишет движок, rodo site export) + код
// приложения (src/app) + site_assets → готовый сайт; и выкладка его туда, куда велел владелец дерева. Карточек дерева,
// путей проекта и 3_research/ сборщик не знает: всё, что ему нужно, — в выгрузке (форма — schema/*.schema.json).
//
//   node scripts/site.mjs build   --data <выгрузка> --out <сайт> [--no-app]   собрать (--no-app — взять готовый dist-app/)
//   node scripts/site.mjs publish --data <выгрузка> --out <сайт> [цель…]      собрать и выложить на основные цели
//   node scripts/site.mjs mirror  --data <выгрузка> [цель…]                   выложить зеркала (пересылка на основной)
//
// Цели — site.json → deploy.targets, их пишет выгрузка из ftree.toml дерева ([[site.target]]). Значений по умолчанию
// нет: целей нет — сайт только собирается, выкладки нет. Цель с manual = true — только если названа по имени.
//   cloudflare-pages (основной; проверка входа functions/_middleware.js работает только здесь) · folder (основной:
//   копия папки сайта, для любого хостинга статики — без проверки входа) · netlify, cloudflare-worker (зеркала).
//
// Папки — ключами или FTREE_SITE_EXPORT / FTREE_SITE_OUT; rodo site build|publish подставляет их сам.
// Папку сайта не стираем целиком, а приводим к выгрузке по файлам: в iCloud стёртая и тут же созданная папка
// становится «people 2» (28.09.2026); неизменившиеся файлы остаются байт в байт — выкладка их не грузит заново.
import Ajv2020 from 'ajv/dist/2020.js'
import addFormats from 'ajv-formats'
import { spawnSync } from 'node:child_process'
import { constants, copyFileSync, cpSync, existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, statSync, utimesSync, writeFileSync } from 'node:fs'
import { homedir, tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

export const WEB = join(dirname(fileURLToPath(import.meta.url)), '..')
const ASSETS = join(WEB, 'site_assets')
const SCHEMA = join(WEB, 'schema')
// что лежит в папке сайта; остальное (старые страницы people/, docs/, *.js данных прежних страниц) — удаляется
const MIRRORED = ['data', 'media', 'files']  // из выгрузки, как есть
const KEEP = new Set([...MIRRORED, 'assets', 'functions', 'index.html'])
const ICLOUD_COPY = / \d+(\.\w+)?$/  // «people 2», «index 2.json» — копии, которые оставляет iCloud

/** site.json выгрузки по схеме site.schema.json; не та форма — стоп с понятной строкой. */
export function readSite(data) {
  const file = join(data, 'site.json')
  if (!existsSync(file)) throw new Error(`${file}: нет — сначала выгрузка (rodo site export)`)
  if (!existsSync(join(data, 'data', 'index.json'))) throw new Error(`${data}/data/index.json: нет — выгрузка не закончена`)
  const site = JSON.parse(readFileSync(file, 'utf8'))
  const ajv = new Ajv2020({ allErrors: true, strict: false })
  addFormats(ajv)
  const check = ajv.compile(JSON.parse(readFileSync(join(SCHEMA, 'site.schema.json'), 'utf8')))
  if (!check(site)) throw new Error(`${file}: не по схеме — ${check.errors.map(e => `${e.instancePath} ${e.message}`).join('; ')}`)
  return site
}

/** Проверка входа (functions/_middleware.js) с закрытыми файлами, сроком и странами открытого входа из site.json. */
export function middleware(site) {
  let text = readFileSync(join(ASSETS, 'functions', '_middleware.js'), 'utf8')
  for (const [old, value] of [
    ['/*PRIVATE_FILES*/', JSON.stringify(site.private_files).slice(1, -1)],
    ['/*OPEN_COUNTRIES*/', JSON.stringify(site.open_countries).slice(1, -1)],
    ["const OPEN_UNTIL = ''", `const OPEN_UNTIL = '${site.open_until}'`],
    ["const OWNER = ''", `const OWNER = ${JSON.stringify(site.owner_login || '')}`],
    ["const REALM = 'Family tree'", `const REALM = ${JSON.stringify(site.realm || 'Family tree')}`],
  ]) {
    if (!text.includes(old)) throw new Error(`_middleware.js: нет места для подстановки ${old}`)
    text = text.replace(old, () => value)
  }
  return text
}

// одинаковые размер и время правки (время копии ставим как у оригинала; файловая система округляет его до долей мс)
const same = (a, b) => { const x = statSync(a), y = statSync(b); return x.size === y.size && Math.abs(x.mtimeMs - y.mtimeMs) < 2 }

/** dst — копия src по файлам: новые и изменившиеся (размер, время) — копируются (на APFS — клоном, без места на
 *  диске), лишние — удаляются. → сколько файлов скопировано. */
export function mirror(src, dst) {
  mkdirSync(dst, { recursive: true })
  let n = 0
  const want = new Set(existsSync(src) ? readdirSync(src).filter(x => !ICLOUD_COPY.test(x)) : [])
  for (const name of readdirSync(dst)) if (!want.has(name)) rmSync(join(dst, name), { recursive: true, force: true })
  for (const name of want) {
    const s = join(src, name), d = join(dst, name)
    if (statSync(s).isDirectory()) {
      if (existsSync(d) && !statSync(d).isDirectory()) rmSync(d)
      n += mirror(s, d)
    } else if (!existsSync(d) || statSync(d).isDirectory() || !same(s, d)) {
      if (existsSync(d)) rmSync(d, { recursive: true, force: true })
      copyFileSync(s, d, constants.COPYFILE_FICLONE)
      const t = statSync(s)
      utimesSync(d, t.atime, t.mtime)
      n++
    }
  }
  return n
}

function npm(args) {
  const r = spawnSync('npm', args, { cwd: WEB, stdio: 'inherit' })
  if (r.status !== 0) throw new Error(`npm ${args.join(' ')} — не вышло (код ${r.status})`)
}

/** Собрать сайт из выгрузки. → {site, copied} */
export function build({ data, out, app = true }) {
  data = resolve(data), out = resolve(out)
  const site = readSite(data)
  if (app) npm(['run', 'build:app', '--silent'])
  const dist = join(WEB, 'dist-app')
  if (!existsSync(join(dist, 'index.html'))) throw new Error(`${dist}/index.html: нет — соберите приложение (npm run build:app)`)
  mkdirSync(out, { recursive: true })
  for (const name of readdirSync(out)) if (!KEEP.has(name)) rmSync(join(out, name), { recursive: true, force: true })
  let copied = 0
  for (const dir of MIRRORED) copied += mirror(join(data, dir), join(out, dir))
  copied += mirror(join(dist, 'assets'), join(out, 'assets'))
  const index = readFileSync(join(dist, 'index.html'))
  if (!existsSync(join(out, 'index.html')) || !readFileSync(join(out, 'index.html')).equals(index)) writeFileSync(join(out, 'index.html'), index)
  rmSync(join(out, 'functions'), { recursive: true, force: true })
  cpSync(join(ASSETS, 'functions'), join(out, 'functions'), { recursive: true })
  writeFileSync(join(out, 'functions', '_middleware.js'), middleware(site))
  const c = site.counts ?? {}
  console.log(`Сайт: ${out} — людей ${c.people ?? '?'}, мест ${c.places ?? '?'}, заметок ${c.docs ?? '?'}, файлов ${c.files ?? '?'}; ` +
    `скопировано заново ${copied}; только по паролю ${site.private_files.length}`)
  return { site, copied }
}

function npx(args, cwd) {
  if (spawnSync('npx', ['-y', ...args], { cwd, stdio: 'inherit' }).status !== 0) throw new Error(`npx ${args[0]} — не вышло`)
}

export const NO_TARGETS = 'в настройках дерева нет ни одной [[site.target]] — сайт собран, никуда не выложен. Пример (пример):\n' +
  '  [[site.target]]\n  kind = "cloudflare-pages"\n  project = "мой-проект"\n  url = "https://мой-проект.example"\n' +
  'Потом — rodo site export и rodo site publish; вход на хостинг делает человек (навык setup).'

/** Цели роли role из site.json: без manual — все; названные по имени — только они (manual тоже). */
export function targetsFor(site, role, names = []) {
  const all = (site.deploy?.targets ?? []).filter(t => t.role === role)
  if (!names.length) return all.filter(t => !t.manual)
  const unknown = names.filter(n => !all.some(t => t.name === n))
  if (unknown.length) throw new Error(`нет цели ${role === 'main' ? 'основного сайта' : 'зеркала'}: ${unknown.join(', ')} — есть: ${all.map(t => t.name).join(', ') || 'ни одной'}`)
  return all.filter(t => names.includes(t.name))
}

/** Собрать и выложить на основные цели. Cloudflare Pages: wrangler берёт папку functions/ из папки сайта. */
export function publish(opts) {
  const { site } = build(opts)
  const targets = targetsFor(site, 'main', opts.names)
  if (!targets.length) { console.log(NO_TARGETS); return [] }
  for (const t of targets) {
    if (t.kind === 'cloudflare-pages') {
      npx(['wrangler@4', 'pages', 'deploy', '.', '--project-name', t.name, '--branch', 'main', '--commit-dirty=true'], resolve(opts.out))
    } else if (t.kind === 'folder') {
      const n = mirror(resolve(opts.out), resolve(t.name))
      console.log(`папка ${t.name}: скопировано ${n}. Проверки входа (пароль, закрытые файлы) там нет — она работает только на Cloudflare Pages`)
    } else throw new Error(`${t.kind}: основной сайт так не выкладывается`)
    console.log(`== готово: ${t.url ?? t.name}`)
  }
  return targets
}

// Зеркало для Беларуси: в Беларуси провайдеры режут Cloudflare по-разному (проверено 28.09.2026 через globalping.io):
// «Белтелеком» — имена сайтов Cloudflare Pages, A1, «Активные технологии», «Единые решения» — адреса, где стоит *.workers.dev;
// Netlify открывается у всех. Сайт остаётся на Cloudflare Pages: Netlify только пересылает запрос туда и ответ обратно.
// Страну посетителя сайт по пересланному запросу сам не узнает, поэтому Netlify передаёт её заголовком X-Visitor-Country
// с секретом X-Proxy-Key: из стран открытого входа — «BY», из остальных — «XX» (тогда пароль). Секрет — файл
// ~/.config/ftree/<имя дерева>/proxy_key (или FTREE_PROXY_KEY_FILE), тот же — секрет PROXY_KEY проекта Pages и воркера;
// в git его нет: netlify.toml собирается во временной папке перед выкладкой. Поменял страны или адрес — выложи и сайт,
// и зеркало.
export function origin(site) {
  const main = (site.deploy?.targets ?? []).find(t => t.role === 'main' && t.url)
  if (!main) throw new Error('зеркало пересылает на основной сайт, а у основной цели нет url (настройки дерева, [[site.target]])')
  return main.url
}

export function netlifyToml(site, key) {
  const to = origin(site)
  if (!site.open_countries.length) throw new Error('site.json: open_countries пуст — зеркалу некого пускать без пароля (настройки дерева, [site])')
  const rule = (extra, country) => `[[redirects]]
  from = "/*"
  to = "${to}/:splat"
  status = 200
  force = true${extra}
  headers = {X-Visitor-Country = "${country}", X-Proxy-Key = "${key}"}
`
  return `[build]\n  publish = "public"\n\n${rule(`\n  conditions = {Country = ${JSON.stringify(site.open_countries)}}`, 'BY')}\n${rule('', 'XX')}`
}

export function proxyKeyFile(site) {
  return process.env.FTREE_PROXY_KEY_FILE || join(homedir(), '.config', 'ftree', site.tree ?? 'tree', 'proxy_key')
}

function proxyKey(site) {
  const file = proxyKeyFile(site)
  if (!existsSync(file)) throw new Error(`${file}: нет секрета для зеркала — придумать длинную строку, записать в этот файл ` +
    'и тем же значением — секрет PROXY_KEY проекта Pages (навык setup)')
  return readFileSync(file, 'utf8').trim()
}

/** wrangler.toml воркера-зеркала — из настроек, имя в git не хранится. */
export function workerToml(target) {
  return `name = ${JSON.stringify(target.name)}\nmain = "index.js"\ncompatibility_date = "2026-09-01"\nworkers_dev = true\n`
}

/** Выложить зеркала: Netlify — пересылка по netlify.toml; воркер Cloudflare — web/site_assets/worker/index.js. */
export function mirrorDeploy({ data, names = [] }) {
  const site = readSite(resolve(data))
  const targets = targetsFor(site, 'mirror', names)
  if (!targets.length) { console.log(site.deploy?.targets?.length ? 'зеркал среди целей нет (или все manual — назвать по имени)' : NO_TARGETS); return [] }
  for (const t of targets) {
    const dir = mkdtempSync(join(tmpdir(), 'ftree-mirror-'))
    try {
      if (t.kind === 'netlify') {
        mkdirSync(join(dir, 'public'))
        writeFileSync(join(dir, 'netlify.toml'), netlifyToml(site, proxyKey(site)))
        npx(['netlify-cli@latest', 'deploy', '--prod', '--site', t.name], dir)
      } else if (t.kind === 'cloudflare-worker') {
        copyFileSync(join(ASSETS, 'worker', 'index.js'), join(dir, 'index.js'))
        writeFileSync(join(dir, 'wrangler.toml'), workerToml(t))
        npx(['wrangler@4', 'deploy', '--var', `ORIGIN:${origin(site).replace(/^https:\/\//, '')}`], dir)
      } else throw new Error(`${t.kind}: это не зеркало`)
    } finally { rmSync(dir, { recursive: true, force: true }) }
    console.log(`== зеркало готово: ${t.url ?? t.name}`)
  }
  return targets
}

export function args(argv) {
  const get = k => { const i = argv.indexOf(k); return i >= 0 ? argv[i + 1] : undefined }
  const names = []  // имена целей: всё, что не ключ и не значение ключа
  for (let i = 1; i < argv.length; i++) {
    if (argv[i] === '--data' || argv[i] === '--out') i++
    else if (!argv[i].startsWith('--')) names.push(argv[i])
  }
  return { cmd: argv[0], data: get('--data') ?? process.env.FTREE_SITE_EXPORT, out: get('--out') ?? process.env.FTREE_SITE_OUT,
    app: !argv.includes('--no-app'), names }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const a = args(process.argv.slice(2))
  try {
    if (!['build', 'publish', 'mirror'].includes(a.cmd)) throw new Error('node scripts/site.mjs build|publish|mirror --data <выгрузка> [--out <сайт>]')
    if (!a.data || (a.cmd !== 'mirror' && !a.out)) throw new Error('нужны --data <выгрузка> и --out <сайт> (или FTREE_SITE_EXPORT, FTREE_SITE_OUT)')
    ;({ build, publish, mirror: mirrorDeploy })[a.cmd](a)
  } catch (e) {
    console.error(`Сайт не собран: ${e.message}`)
    process.exit(1)
  }
}
