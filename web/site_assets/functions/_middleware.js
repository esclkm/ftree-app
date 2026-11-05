// Вход на сайт (Cloudflare Pages): у каждого человека своё имя и пароль. Срабатывает до любой страницы, картинки и файла.
// Пароли в код не пишем — это секреты проекта в Cloudflare (Workers & Pages → <проект: [site] project в ftree.toml> → Settings → Variables and Secrets):
//   USER_<ИМЯ> — пароль этого человека, например USER_MARIA для имени «maria» (имя без учёта регистра);
//   SITE_PASSWORD — пароль владельца; его имя — [site] owner_login в ftree.toml (нет — у сайта только USER_<ИМЯ>).
// Добавить человека:  npx wrangler pages secret put USER_ИМЯ --project-name <проект>  → и выложить сайт заново.
// Браузер запоминает вход до закрытия.
//
// ВРЕМЕННО ОТКРЫТО: пожилой родне трудно вводить имя и пароль, поэтому посетители из стран OPEN_COUNTRIES входят без
// пароля — до даты OPEN_UNTIL включительно. После неё пароль снова спрашивается у всех, сам, без правок.
// Дата и страны — настройки дерева (ftree.toml, [site] open_until и open_countries); выгрузка кладёт их в site.json, сборщик вписывает сюда при
// сборке. Не вписал (пусто) — сайт закрыт паролем для всех. Закрыть раньше — open_until = '' и выложить сайт. Сколько
// осталось, пишет сводка в начале сессии (sync.py status). Тот же список стран — у зеркала (rodo site mirror
// читает его оттуда же).
// Даже при открытом входе пароль нужен: поисковым роботам и файлам из PRIVATE_FILES (PDF с почтами, телефонами и номерами
// домов — PDF не почистить, как страницы; сканы документов живых — свидетельства, паспорта, аттестаты; список — из
// site.json выгрузки, вписывает сборщик). Такой файл открытому посетителю отдаётся ответом «нет доступа» без окна входа; войти, чтобы
// видеть и их, — по адресу /login.
const OWNER = '' // имя владельца для SITE_PASSWORD: сборщик — из site.json ([site] owner_login в ftree.toml)
const REALM = 'Family tree' // имя в окне входа: сборщик — из site.json ([site] realm в ftree.toml)
const OPEN_UNTIL = '' // сборщик (web/scripts/site.mjs) — из site.json выгрузки: [site] open_until
const OPEN_COUNTRIES = [/*OPEN_COUNTRIES*/]  // страна — по IP, её сообщает Cloudflare (request.cf.country)
const PRIVATE_FILES = [/*PRIVATE_FILES*/]
// Роботы и программы без браузера — только по паролю, даже из открытых стран: поисковики (и их помощники вроде GoogleOther,
// YandexImages), ИИ-сборщики (GPTBot, ChatGPT-User, ClaudeBot, Perplexity, Meta, Cohere…), архивы, превью ссылок в
// мессенджерах и скачивалки (curl, python, Go, Java…). Пустое имя программы — тоже робот. Viber и браузер приложения Яндекса
// не трогаем: через них родня и открывает ссылки.
const BOT = new RegExp([
  'bot', 'crawl', 'spider', 'slurp', 'archiv', 'scrap', 'preview', 'embedly', 'facebookexternalhit', 'meta-external',
  'google', 'compatible; yandex', 'chatgpt', 'openai', 'gpt', 'claude', 'anthropic', 'perplexity', 'cohere', 'diffbot',
  'ai2', 'omgili', 'curl', 'wget', 'python', 'requests', 'aiohttp', 'httpx', 'urllib', 'go-http', 'axios', 'node-fetch',
  'undici', 'okhttp', 'java/', 'libwww', 'httpclient', 'http-client', 'headless', 'phantom', 'selenium', 'puppeteer',
  'playwright', '^whatsapp/', '^$',
].join('|'), 'i')
// никаких поисковиков, архивов, превью и обучения ИИ — ни при каком входе
const HIDDEN = { 'X-Robots-Tag': 'noindex, nofollow, noarchive, nosnippet, noimageindex, noai, noimageai', 'Referrer-Policy': 'no-referrer' }
// robots.txt: всем — нельзя; ИИ-сборщики, которые слушают только своё имя, названы отдельно
const ROBOTS = ['*', 'Googlebot', 'Google-Extended', 'GoogleOther', 'Bingbot', 'Yandex', 'Applebot', 'Applebot-Extended',
  'GPTBot', 'ChatGPT-User', 'OAI-SearchBot', 'ClaudeBot', 'Claude-User', 'Claude-SearchBot', 'anthropic-ai', 'CCBot',
  'PerplexityBot', 'Perplexity-User', 'Bytespider', 'meta-externalagent', 'FacebookBot', 'Amazonbot', 'cohere-ai',
  'Diffbot', 'ia_archiver', 'archive.org_bot', 'SemrushBot', 'AhrefsBot', 'MJ12bot', 'PetalBot', 'Timpibot', 'YouBot']
  .map(ua => `User-agent: ${ua}\nDisallow: /\n`).join('\n')

// Страна посетителя. Через адреса для Беларуси (зеркало на Netlify — web/site_assets/netlify,
// воркер *.workers.dev — web/site_assets/worker) запрос приходит от пересыльщика, и страну сообщает он — заголовком, которому верим только вместе с секретом PROXY_KEY
function country(request, env) {
  const key = request.headers.get('X-Proxy-Key')
  if (env.PROXY_KEY && key === env.PROXY_KEY) return request.headers.get('X-Visitor-Country')
  return request.cf?.country
}

// посетитель входит без пароля (открытая страна, до OPEN_UNTIL, не робот)
function isOpen(request, env) {
  if (!OPEN_UNTIL || new Date() > new Date(OPEN_UNTIL + 'T23:59:59Z')) return false
  if (!OPEN_COUNTRIES.includes(country(request, env))) return false
  return !BOT.test(request.headers.get('User-Agent') || '')
}

const isPrivate = path => PRIVATE_FILES.includes(decodeURIComponent(path).normalize('NFC'))

function loggedIn(request, env) {
  const auth = request.headers.get('Authorization') || ''
  if (!auth.startsWith('Basic ')) return false
  // имя и пароль приходят в base64. Русские буквы браузеры кодируют по-разному (Chrome — UTF-8, Safari — бывает
  // Latin-1), поэтому пробуем оба прочтения; пробелы по краям (часто прилипают при вводе в Cloudflare) не считаем
  const raw = atob(auth.slice(6))
  const utf8 = new TextDecoder().decode(Uint8Array.from(raw, c => c.charCodeAt(0)))
  for (const text of [utf8, raw]) {
    const [user = '', pass = ''] = text.split(/:(.*)/s)
    const name = user.trim().toUpperCase()
    const expected = env['USER_' + name] || (OWNER && name === OWNER.toUpperCase() ? env.SITE_PASSWORD : undefined)
    if (expected && pass.trim() === String(expected).trim()) return true
  }
  return false
}

export async function onRequest({ request, env, next }) {
  const path = new URL(request.url).pathname
  // «страница 2.html» — копии, которые оставляет iCloud; у настоящих файлов сайта пробелов в имени нет
  if (/ \d+\.\w+$/.test(decodeURIComponent(path))) return new Response('Нет такой страницы', { status: 404, headers: HIDDEN })
  if (path === '/robots.txt') {
    return new Response(ROBOTS, { headers: { 'Content-Type': 'text/plain', ...HIDDEN } })
  }
  const open = isOpen(request, env), user = loggedIn(request, env)
  // /login — войти по имени и паролю, даже когда сайт открыт: после входа браузер сам подставляет их ко всем файлам сайта
  // адрес без имени сайта: иначе через Netlify (адрес для Беларуси) браузер ушёл бы на адрес Cloudflare Pages, который там режут
  if (path === '/login' && user) return new Response(null, { status: 302, headers: { Location: '/', ...HIDDEN } })
  // Открытому посетителю закрытый файл (скан паспорта, PDF с телефонами) просто не отдаём — без окна входа. Иначе такая
  // картинка на странице или в дереве открывала окно имени и пароля на каждом шаге (28.09.2026).
  if (open && !user && isPrivate(path)) {
    return new Response('Этот файл — только после входа: /login', { status: 403, headers: { 'Content-Type': 'text/plain; charset=utf-8', ...HIDDEN } })
  }
  if ((!open || path === '/login') && !user) {
    return new Response('Нужны имя и пароль', {
      status: 401,
      headers: { 'WWW-Authenticate': `Basic realm="${REALM}", charset="UTF-8"`, 'Content-Type': 'text/plain; charset=utf-8', ...HIDDEN },
    })
  }
  const res = await next()
  const out = new Response(res.body, res)
  for (const [k, v] of Object.entries(HIDDEN)) out.headers.set(k, v)
  // страницу не держат общие кэши по дороге; сам браузер может
  out.headers.set('Cache-Control', 'private, max-age=0, must-revalidate')
  return out
}
