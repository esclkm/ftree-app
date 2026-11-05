/**
 * Свой Chrome для сайтов архивов: постоянный вход Павла, файлы — сразу в нужную папку, без модели в каждом шаге.
 *
 * Что это. Отдельный Chrome со своим профилем ($ARCHIVES_LOCAL/browser-profile — вне проекта, git и облака).
 * Павел один раз входит в нём на FamilySearch, Radzima, ГАСО («запомнить меня»), и вход живёт между сессиями и
 * перезагрузками. Скрипт управляет этим Chrome по протоколу DevTools (CDP) через порт только на 127.0.0.1.
 * Пароли и cookie скрипт не видит и не печатает: вход подставляет сам браузер. Обобщение wbh_cdp.mjs (там — WBH).
 * История — документ дерева проект/ОРКЕСТРАЦИЯ_ЖУРНАЛ.md, задача B1. Node 24, без npm-пакетов.
 *
 * Команды (node tools/scripts/browser_cdp.mjs …):
 *   start [url]                 — запустить Chrome с портом управления (уже запущен — ничего не делает)
 *   stop                        — закрыть его (в конце работы: пока он открыт, порт доступен любой программе на Mac)
 *   status                      — запущен ли, какие вкладки и чья какая (сессии — каждая в своей, см. cdp_tab.mjs)
 *   release                     — закрыть свою вкладку (в конце работы сессии; Chrome остаётся для других)
 *   nav <url>                   — открыть адрес в своей вкладке сессии и дождаться загрузки
 *   text [N]                    — видимый текст страницы, первые N знаков (по умолчанию 3000)
 *   eval '<js>' [--out файл]    — выполнить JS на странице (можно await); короткий ответ — сюда, длинный — в файл
 *   shot <файл.png>             — снимок видимой части (только если текста мало)
 *   login-check <сайт> [--wait] — вошёл ли Павел: familysearch | radzima | gaso. Не вошёл — открывает страницу входа
 *                                 и пишет «войди в окне Chrome»; с --wait ждёт входа до 10 минут
 *   download <папка> <url> [имя]          — скачать файл с входом Павла (fetch внутри страницы) прямо в папку
 *   batch <папка> <список.tsv> [--pause 3] — то же пачкой: строки «url<TAB>имя»; пауза между файлами ≥3 с
 *       [--isolated] [--warm <url>]       — сайт без входа: своё окно-контекст (не сбивает вкладку и загрузки других
 *                                         сессий); --warm — сначала открыть этот адрес (пропуск защиты сайта)
 *   fs-frames <папка> <список.tsv>         — кадры FamilySearch: строки «3Q9M-…<TAB>имя» (адрес строит сам)
 *
 * Выход: 0 — готово; 1 — ошибка; 2 — неверные параметры; 3 — не вошёл / стоп от сайта (401, 403, 429, капча).
 * Переменные: BROWSER_PROFILE (папка профиля), CDP_PORT (порт; по умолчанию 9333 — настройки paths.py; у wbh_cdp — 9222), CHROME (программа).
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ownTab, tabOwners, releaseTab, OWNER } from './cdp_tab.mjs';
import { cdpPort, setting } from './settings.mjs';

const PORT = cdpPort();  // 9333, если не задан (paths.py: CDP_PORT)
const BASE = `http://127.0.0.1:${PORT}`;
const ARCHIVES = setting('ARCHIVES_LOCAL').replace(/^~/, os.homedir());  // сырьё архивов (paths.py)
const PROFILE = process.env.BROWSER_PROFILE || path.join(ARCHIVES, 'browser-profile');
const CHROME = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const MAX_PRINT = 4000; // длиннее — в файл: в разговор идёт только итог
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Признак входа на каждом сайте. js возвращает {in: true|false, why}. Проверено — [П], догадка — [В] (см. навыки archive-*).
const SITES = {
  familysearch: {
    check: 'https://www.familysearch.org/en/search/',
    login: 'https://www.familysearch.org/en/search/',
    // [П 02.10] без входа в шапке кнопка «Sign In» (иногда ещё и уход на ident.familysearch.org/…/login);
    // уход на вход бывает не всегда — одного адреса мало, ложное «вошёл» было
    js: `(async()=>{await new Promise(z=>setTimeout(z,3000));const h=location.hostname;const s=[...document.querySelectorAll('a,button')].filter(e=>/^\\s*sign in\\s*$/i.test(e.innerText||'')).length;return {in:h==='www.familysearch.org'&&s===0,why:h+location.pathname+(s?', видна «Sign In»':'')}})()`,
  },
  radzima: {
    // любая страница прихода: без Premium на ней заглушка. Какой приход — настройка дерева ([radzima] check в ftree.toml)
    check: setting('RADZIMA_CHECK') || 'https://www.radzima.net/ru/',
    login: 'https://www.radzima.net/ru/login/',
    // [П 30.09] без Premium-входа на странице прихода заглушка и нет ссылок на FamilySearch
    js: `(()=>{const t=document.body.innerText;const stub=/Для пользователей с Premium планом доступны/.test(t);const fs=document.querySelectorAll('a[href*="familysearch"]').length;return {in:!stub&&(fs>0||t.length>3000),why:'stub '+stub+', ссылок FS '+fs+', длина '+t.length}})()`,
  },
  gaso: {
    check: 'https://portal.gaso-smolensk.ru/page/portal/personalAccount.jsf',
    login: 'https://portal.gaso-smolensk.ru/page/portal/personalAccount.jsf',
    // [П 01.10] без входа в кабинете кнопка «Войти в кабинет»; абонемент — отдельная строка
    js: `(()=>{const t=document.body.innerText;const out=/Войти в кабинет/.test(t);const none=/нет купленных абонементов/i.test(t);return {in:!out,why:out?'видна «Войти в кабинет»':(none?'вошёл, абонемента нет':'вошёл')}})()`,
  },
};
const STOP_SIGNS = /are you a robot|unusual activity|captcha|подтвердите, что вы не робот|too many requests|слишком много запросов/i;

// ---------- CDP ----------

async function json(p, opts) {
  const r = await fetch(BASE + p, opts);
  if (!r.ok) throw new Error(`${p}: ${r.status}`);
  return r.json();
}

async function running() {
  try { return await json('/json/version'); } catch { return null; }
}

function connect(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    let id = 0;
    const pending = new Map();
    const listeners = new Set();
    ws.addEventListener('open', () => resolve({
      send(method, params = {}) {
        return new Promise((res, rej) => {
          const my = ++id;
          pending.set(my, { res, rej });
          ws.send(JSON.stringify({ id: my, method, params }));
        });
      },
      on(fn) { listeners.add(fn); return () => listeners.delete(fn); },
      close: () => ws.close(),
    }));
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && pending.has(msg.id)) {
        const { res, rej } = pending.get(msg.id);
        pending.delete(msg.id);
        msg.error ? rej(new Error(msg.error.message || JSON.stringify(msg.error))) : res(msg.result);
      } else if (msg.method) for (const fn of listeners) fn(msg);
    });
    ws.addEventListener('error', (e) => reject(new Error('нет связи с Chrome: ' + (e.message || e.type))));
  });
}

async function needChrome() {
  const v = await running();
  if (!v) { console.error(`Chrome не запущен: node tools/scripts/browser_cdp.mjs start`); process.exit(1); }
  return v;
}

// рабочая вкладка — своя у каждой сессии (cdp_tab.mjs): другие сессии её не трогают, и мы — их
async function page() {
  await needChrome();
  const c = await connect((await ownTab(BASE)).webSocketDebuggerUrl);
  await c.send('Page.enable');
  await c.send('Runtime.enable');
  return c;
}

// отдельная вкладка для проверки: вкладку, где Павел вводит пароль, не перезагружаем
async function scratchTab(fn) {
  const t = await json('/json/new?about:blank', { method: 'PUT' });
  const c = await connect(t.webSocketDebuggerUrl);
  try { await c.send('Page.enable'); await c.send('Runtime.enable'); return await fn(c); }
  finally { c.close(); await fetch(`${BASE}/json/close/${t.id}`).catch(() => {}); }
}

async function evaluate(c, expression) {
  const r = await c.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) throw new Error('JS: ' + (r.exceptionDetails.exception?.description || r.exceptionDetails.text));
  return r.result.value;
}

async function navigate(c, url, timeout = 30000) {
  const loaded = new Promise((res) => {
    const off = c.on((m) => { if (m.method === 'Page.loadEventFired') { off(); res(true); } });
    setTimeout(() => { off(); res(false); }, timeout);
  });
  let r = await c.send('Page.navigate', { url });
  if (r.errorText === 'net::ERR_ABORTED') { await sleep(2000); r = await c.send('Page.navigate', { url }); } // перебила переадресация
  if (r.errorText) throw new Error(`${url}: ${r.errorText}`);
  const ok = await loaded;
  await sleep(1500); // страницы на React дорисовывают после load
  return ok;
}

async function origin(c) { return evaluate(c, 'location.origin'); }

// Секреты в разговор не выносим: выражения, которые читают cookie или хранилище входа, не выполняем.
function guard(js) {
  if (/document\.cookie|localStorage|sessionStorage|indexedDB|Network\.get|Storage\.get|password|token/i.test(js)) {
    console.error('✋ Не выполняю: выражение читает cookie, хранилище или пароль. Вход — только внутри браузера.');
    process.exit(2);
  }
}

function emit(value, out) {
  const s = typeof value === 'string' ? value : JSON.stringify(value, null, 1);
  if (out || s.length > MAX_PRINT) {
    const f = out || path.join(os.tmpdir(), `browser_cdp_${Date.now()}.txt`);
    fs.writeFileSync(f, s);
    console.log(`→ ${f} (${s.length} знаков)`);
  } else console.log(s);
}

// ---------- команды ----------

// «Продолжить с того места» (restore_on_startup = 1): так Chrome сохраняет и входы, которые живут до закрытия браузера
// (ГАСО: без этого после stop вход терялся [П 02.10]). Только в этом профиле; пока Chrome закрыт — он перепишет файл.
function keepSessions() {
  const f = path.join(PROFILE, 'Default', 'Preferences');
  let prefs = {};
  try { prefs = JSON.parse(fs.readFileSync(f, 'utf8')); } catch { /* новый профиль */ }
  if (prefs.session?.restore_on_startup === 1) return;
  prefs.session = { ...(prefs.session || {}), restore_on_startup: 1 };
  fs.mkdirSync(path.dirname(f), { recursive: true });
  fs.writeFileSync(f, JSON.stringify(prefs));
}

async function cmdStart(url) {
  const v = await running();
  if (v) { console.log(`уже запущен: ${v.Browser}, порт ${PORT}`); return; }
  if (!fs.existsSync(CHROME)) { console.error(`нет Chrome: ${CHROME} (brew install --cask google-chrome)`); process.exit(1); }
  fs.mkdirSync(PROFILE, { recursive: true, mode: 0o700 });
  keepSessions();
  const child = spawn(CHROME, [
    `--user-data-dir=${PROFILE}`, `--remote-debugging-port=${PORT}`, '--remote-debugging-address=127.0.0.1',
    '--no-first-run', '--no-default-browser-check', url || 'about:blank',
  ], { detached: true, stdio: 'ignore' });
  child.unref();
  for (let i = 0; i < 40; i++) {
    await sleep(500);
    const ok = await running();
    if (ok) { console.log(`запущен: ${ok.Browser}, порт 127.0.0.1:${PORT}, профиль ${PROFILE}. В конце — stop`); return; }
  }
  console.error('Chrome не ответил за 20 с. Открыт ли он уже с этим профилем без порта? Закрой окно и повтори start');
  process.exit(1);
}

async function cmdStop() {
  const v = await running();
  if (!v) { console.log('не запущен'); return; }
  const b = await connect(v.webSocketDebuggerUrl);
  await b.send('Browser.close').catch(() => {});
  for (let i = 0; i < 20 && (await running()); i++) await sleep(250);
  console.log((await running()) ? 'не закрылся — закрой окно руками' : 'закрыт');
}

async function cmdStatus() {
  const v = await running();
  if (!v) { console.log(`не запущен (порт ${PORT}, профиль ${PROFILE})`); return; }
  console.log(`запущен: ${v.Browser}, порт ${PORT}, профиль ${PROFILE}`);
  const who = await tabOwners(BASE);
  for (const t of await json('/json')) if (t.type === 'page') console.log(`  вкладка ${t.id.slice(0, 6)} [${who[t.id] || 'ничья'}]: ${t.url.slice(0, 110)}`);
  console.log(OWNER ? `эта сессия: ${OWNER.slice(0, 8)}` : 'номера сессии нет — команды берут ничью вкладку');
}

async function loginState(c, site) {
  await navigate(c, site.check);
  for (let i = 0; ; i++) {
    try {
      const text = await evaluate(c, 'document.body ? document.body.innerText.slice(0, 5000) : ""');
      if (STOP_SIGNS.test(text)) return { stop: true, why: 'сайт просит доказать, что не робот, или ограничил запросы' };
      return await evaluate(c, site.js);
    } catch (e) { // страница ушла посреди проверки — обычно переадресация на вход; дождаться и спросить снова
      if (i >= 3 || !/navigated or closed|context was destroyed/i.test(e.message)) throw e;
      await sleep(2500);
    }
  }
}

async function cmdLoginCheck(name, wait) {
  const site = SITES[name];
  if (!site) { console.error(`сайт: ${Object.keys(SITES).join(' | ')}`); process.exit(2); }
  await needChrome();
  let s = await scratchTab((c) => loginState(c, site));
  if (s.stop) { console.log(`✋ ${name}: ${s.why} — стоп, сказать Павлу`); process.exitCode = 3; return; }
  if (s.in) { console.log(`вошёл (${name}: ${s.why})`); return; }
  const c = await page();
  try { await navigate(c, site.login); } finally { c.close(); }
  console.log(`не вошёл (${name}: ${s.why}). Павлу: войди в окне Chrome (профиль browser-profile) — страница входа открыта; отметь «запомнить меня»`);
  if (!wait) { process.exitCode = 3; return; }
  for (let i = 0; i < 40; i++) { // 10 минут, раз в 15 с — в отдельной вкладке
    await sleep(15000);
    s = await scratchTab((c2) => loginState(c2, site));
    if (s.in) { console.log(`вошёл (${name}: ${s.why})`); return; }
  }
  console.log('не вошёл за 10 минут'); process.exitCode = 3;
}

// Скачать один файл: fetch внутри страницы того же сайта (вход подставит браузер) → <a download> → в папку.
// Ссылка — через createElementNS: на сайте-картинке (photos.szukajwarchiwach.gov.pl) страница не HTML, и обычная <a> без click().
async function fetchToDir(c, b, dir, url, name) {
  const want = new URL(url).origin;
  if ((await origin(c)) !== want) await navigate(c, want + '/');
  const started = new Promise((res) => {
    const timer = setTimeout(() => { off(); res(null); }, 60000);
    const off = b.on((m) => {
      if (m.method === 'Browser.downloadProgress' && m.params.state !== 'inProgress') { clearTimeout(timer); off(); res(m.params); }
    });
  });
  const r = await evaluate(c, `(async()=>{try{const r=await fetch(${JSON.stringify(url)},{credentials:'include'});
    if(!r.ok)return {status:r.status};const b=await r.blob();const a=document.createElementNS('http://www.w3.org/1999/xhtml','a');a.href=URL.createObjectURL(b);
    a.download=${JSON.stringify(name)};(document.body||document.documentElement).appendChild(a);a.click();a.remove();return {status:200,size:b.size,type:b.type}}
    catch(e){return {status:0,err:String(e)}}})()`);
  if (r.status === 200 && /html/.test(r.type || '')) r.status = 'HTML'; // заглушка защиты сайта (Incapsula ≈ 1 КБ) вместо файла
  if (r.status !== 200) return { ok: false, line: `${r.status || 'ERR'} ${name}${r.err ? ' ' + r.err : ''}`, stop: [401, 403, 429].includes(r.status) };
  const done = await started;
  const f = path.join(dir, name);
  if (!done || done.state !== 'completed' || !fs.existsSync(f)) return { ok: false, line: `не сохранился ${name}` };
  const size = fs.statSync(f).size;
  return { ok: size === r.size, line: `${size} ${name}${size === r.size ? '' : ` (ждали ${r.size})`}` };
}

// isolated — сайт без входа (szukajwarchiwach): своё окно-контекст без cookie Павла. Не трогает рабочую вкладку
// других сессий и не уводит их загрузки в нашу папку (папка загрузок задаётся только этому контексту). warm — адрес,
// который открыть сначала: защита сайта (Incapsula) ставит пропуск при заходе на сам сайт.
async function cmdDownload(dir, items, pause, { isolated = false, warm = '' } = {}) {
  dir = path.resolve(dir.replace(/^~/, os.homedir()));
  fs.mkdirSync(dir, { recursive: true });
  const v = await needChrome();
  const b = await connect(v.webSocketDebuggerUrl);
  let c, ctx;
  if (isolated) {
    ctx = (await b.send('Target.createBrowserContext', { disposeOnDetach: true })).browserContextId;
    const { targetId } = await b.send('Target.createTarget', { url: 'about:blank', browserContextId: ctx });
    c = await connect(`${BASE.replace('http', 'ws')}/devtools/page/${targetId}`);
    await c.send('Page.enable'); await c.send('Runtime.enable');
  } else c = await page();
  if (warm) { await navigate(c, warm); await sleep(3000); }
  await b.send('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: dir, eventsEnabled: true, ...(ctx ? { browserContextId: ctx } : {}) });
  let got = 0, skipped = 0;
  try {
    for (let i = 0; i < items.length; i++) {
      const [url, name] = items[i];
      if (fs.existsSync(path.join(dir, name)) && fs.statSync(path.join(dir, name)).size > 0) { skipped++; continue; } // продолжение
      const r = await fetchToDir(c, b, dir, url, name);
      console.log(r.line);
      if (r.ok) got++;
      if (r.stop) { console.log(`✋ сайт ответил ${r.line.split(' ')[0]} — стоп: не вошёл или лимит. login-check, потом пауза ≥10 мин`); process.exitCode = 3; break; }
      if (i < items.length - 1) await sleep(pause * 1000);
    }
  } finally {
    if (ctx) { c.close(); await b.send('Target.disposeBrowserContext', { browserContextId: ctx }).catch(() => {}); }
    else { await b.send('Browser.setDownloadBehavior', { behavior: 'default' }).catch(() => {}); c.close(); } // Павлу — снова «Загрузки»
    b.close();
  }
  console.log(`итог: скачано ${got} из ${items.length}${skipped ? `, уже были ${skipped}` : ''} → ${dir}`);
  if (got + skipped < items.length && !process.exitCode) process.exitCode = 1;
}

function readList(file, toUrl) {
  return fs.readFileSync(file, 'utf8').split('\n').map((l) => l.trim()).filter((l) => l && !l.startsWith('#')).map((l) => {
    const [a, n] = l.split('\t');
    const url = toUrl(a.trim());
    const name = (n || '').trim() || path.basename(new URL(url).pathname);
    return [url, name.replace(/[/\\:]/g, '_')];
  });
}

const fsFrame = (id) => `https://www.familysearch.org/service/records/storage/deepzoomcloud/dz/v1/3:1:${id.replace(/^3:1:/, '')}/dist.jpg`;

async function main() {
  const argv = process.argv.slice(2);
  const flag = (k) => { const i = argv.indexOf(k); if (i < 0) return undefined; const v = argv[i + 1]; argv.splice(i, 2); return v; };
  const has = (k) => { const i = argv.indexOf(k); if (i < 0) return false; argv.splice(i, 1); return true; };
  const out = flag('--out');
  const pause = Math.max(3, Number(flag('--pause') || 3)); // меньше 3 с — терялись файлы и злим сайт
  const wait = has('--wait');
  const [cmd, ...rest] = argv;
  switch (cmd) {
    case 'start': return cmdStart(rest[0]);
    case 'stop': return cmdStop();
    case 'status': return cmdStatus();
    case 'release': console.log((await releaseTab(BASE)) ? 'своя вкладка закрыта' : 'своей вкладки нет'); return;
    case 'nav': { const c = await page(); try { await navigate(c, rest[0]); console.log(await evaluate(c, 'location.href')); } finally { c.close(); } return; }
    case 'text': { const c = await page(); try { emit(await evaluate(c, `document.body.innerText.slice(0, ${Number(rest[0] || 3000)})`), out); } finally { c.close(); } return; }
    case 'eval': { const js = rest.join(' '); guard(js); const c = await page(); try { emit(await evaluate(c, js), out); } finally { c.close(); } return; }
    case 'shot': {
      const c = await page();
      try { const r = await c.send('Page.captureScreenshot', { format: 'png' }); fs.writeFileSync(rest[0] || '/tmp/browser_shot.png', Buffer.from(r.data, 'base64')); console.log('→', rest[0] || '/tmp/browser_shot.png'); } finally { c.close(); }
      return;
    }
    case 'login-check': return cmdLoginCheck(rest[0], wait);
    case 'download': {
      if (rest.length < 2) break;
      const name = rest[2] || path.basename(new URL(rest[1]).pathname);
      return cmdDownload(rest[0], [[rest[1], name]], pause);
    }
    case 'batch': if (rest.length < 2) break; return cmdDownload(rest[0], readList(rest[1], (u) => u), pause, { isolated: has('--isolated'), warm: flag('--warm') || '' });
    case 'fs-frames': if (rest.length < 2) break; return cmdDownload(rest[0], readList(rest[1], fsFrame), pause);
  }
  console.error('Команды: start | stop | status | release | nav | text | eval | shot | login-check | download | batch | fs-frames (подробно — в шапке файла)');
  process.exitCode = 2;
}

main().catch((e) => { console.error('Ошибка:', e.message); process.exitCode = 1; });
