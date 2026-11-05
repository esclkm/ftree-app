// Зеркало сайта — воркер Cloudflare по адресу <имя>.<аккаунт>.workers.dev. Нужен из-за Беларуси: «Белтелеком» обрывает
// все адреса сайтов Cloudflare Pages (проверено 28.09.2026 из Минска и Бреста), а *.workers.dev пропускает. Сайт остаётся на Pages; этот воркер
// только пересылает запрос туда и ответ обратно.
// Страну посетителя сайт по пересланному запросу сам не узнает (увидит страну воркера), поэтому воркер передаёт её
// заголовком X-Visitor-Country вместе с секретом PROXY_KEY — тем же, что в секретах проекта Pages; без секрета заголовку
// не верят (functions/_middleware.js).
// Куда пересылать — переменная ORIGIN воркера: url основной цели ([[site.target]] role = "main"), без https://.
// Выложить: цель kind = "cloudflare-worker" в ftree.toml дерева и rodo site mirror <имя> — wrangler.toml собирается
// из настроек во временной папке (имени воркера в git нет). Секрет — npx wrangler secret put PROXY_KEY --name <имя>.

export default {
  async fetch(request, env) {
    const url = new URL(request.url)
    const self = url.host
    if (!env.ORIGIN) return new Response('ORIGIN не задан (wrangler deploy --var ORIGIN:…)', { status: 500 })
    url.host = env.ORIGIN
    const headers = new Headers(request.headers)
    headers.set('X-Visitor-Country', request.cf?.country || '')
    headers.set('X-Proxy-Key', env.PROXY_KEY || '')
    const res = await fetch(url, { method: request.method, headers, body: request.body, redirect: 'manual' })
    // переадресация со старым адресом — вернуть на этот
    const location = res.headers.get('Location')
    if (!location?.includes(env.ORIGIN)) return res
    const out = new Response(res.body, res)
    out.headers.set('Location', location.replace(env.ORIGIN, self))
    return out
  },
}
