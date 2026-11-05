#!/usr/bin/env node
/**
 * Подтвердить или отклонить Smart Match на MyHeritage — пачкой, без ИИ.
 *
 * Зачем. Совпадений сотни, а щёлкать каждое руками — недели. Свой запрос к web-family-graphql сайт не принимает
 * (ключ сессии видит только страница, скрипту его читать нельзя — browser_cdp.mjs guard), поэтому скрипт открывает
 * сравнение совпадения во вкладке Chrome проекта и нажимает кнопку сам; запрос шлёт страница (external_match_update,
 * статус confirmed / undo / rejected), скрипт проверяет надпись «was confirmed» / «was rejected».
 *
 *   node tools/scripts/myheritage_match_set.mjs reject  <наш номер>:<чужой сайт>[:<номер там>] …  [--go]
 *   node tools/scripts/myheritage_match_set.mjs confirm <наш номер>:<чужой сайт>[:<номер там>] …  [--go]
 *     Без --go — только показать, какие совпадения нашлись. Подтверждённое сначала снимается («Undo confirm»),
 *     потом отклоняется. Совпадения человека берутся со страницы matches-for-person (все состояния).
 *   Пример: myheritage_match_set.mjs reject 1500001:OYYV<31 знак сайта> --go
 *
 * Бережём сайт: 6–10 с между действиями, своя вкладка (cdp_tab.mjs); капча / 403 / Incapsula — СТОП (код 3).
 * Выход: 0 — готово; 1 — ошибка; 2 — неверные параметры; 3 — стоп от сайта.
 */
import { ownTab } from './cdp_tab.mjs';
import { cdpPort, settings } from './settings.mjs';

const BASE = `http://127.0.0.1:${cdpPort()}`;
const OUR = settings().MYHERITAGE_SITE;  // номер нашего дерева — ftree.toml, [myheritage] site
const args = process.argv.slice(2);
const ACTION = args[0];
const GO = args.includes('--go');
const items = args.slice(1).filter((a) => !a.startsWith('--')).map((a) => { const [our, site, their] = a.split(':'); return { our, site, their }; });
if (!['reject', 'confirm'].includes(ACTION) || !items.length || items.some((i) => !/^\d+$/.test(i.our) || !/^OYYV\w{27}$/.test(i.site || ''))) {
  console.error('нужно: reject|confirm <наш номер>:<чужой сайт>[:<номер там>] … [--go]'); process.exit(2);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const pause = () => sleep(6000 + Math.random() * 4000);

function connect(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl); let id = 0; const pending = new Map(); const listeners = new Set();
    ws.addEventListener('open', () => resolve({
      send: (method, params = {}) => new Promise((res, rej) => { const my = ++id; pending.set(my, { res, rej }); ws.send(JSON.stringify({ id: my, method, params })); }),
      on: (fn) => { listeners.add(fn); return () => listeners.delete(fn); },
      close: () => ws.close(),
    }));
    ws.addEventListener('message', (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id && pending.has(m.id)) { const { res, rej } = pending.get(m.id); pending.delete(m.id); m.error ? rej(new Error(m.error.message)) : res(m.result); }
      else if (m.method) for (const fn of listeners) fn(m);
    });
    ws.addEventListener('error', () => reject(new Error('нет связи с Chrome проекта')));
  });
}
const c = await connect((await ownTab(BASE)).webSocketDebuggerUrl);
await c.send('Page.enable'); await c.send('Runtime.enable');
const js = async (expression) => {
  const r = await c.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
  return r.result.value;
};
async function nav(url) {
  const loaded = new Promise((res) => { const off = c.on((m) => { if (m.method === 'Page.loadEventFired') { off(); res(); } }); setTimeout(res, 30000); });
  await c.send('Page.navigate', { url }); await loaded; await sleep(2500);
  if (await js(`/captcha|Access denied|Incapsula|403 Forbidden/i.test(document.body.innerText)`)) { console.error('СТОП: сайт показал капчу или запрет'); process.exit(3); }
}
// ждать, пока на странице появится то, что ищем
async function until(expr, ms = 12000) { for (let t = 0; t < ms; t += 500) { if (await js(expr)) return true; await sleep(500); } return false; }
const visible = (sel, text) => `[...document.querySelectorAll(${JSON.stringify(sel)})].some(a=>a.offsetParent${text ? `&&a.textContent.trim()==${JSON.stringify(text)}` : ''})`;
const click = (sel, text) => js(`(()=>{const b=[...document.querySelectorAll(${JSON.stringify(sel)})].find(a=>a.offsetParent${text ? `&&a.textContent.trim()==${JSON.stringify(text)}` : ''}); if(!b) return false; setTimeout(()=>b.click(),100); return true})()`);

let done = 0, failed = 0;
for (const it of items) {
  await nav(`https://www.myheritage.com/discovery-hub/${OUR}/matches-for-person/${it.our}?matchType=2&confirmedByOthers=0`);
  const urls = (await js(`[...document.querySelectorAll("a")].filter(a=>/Review match/.test(a.textContent)).map(a=>a.href)`))
    .filter((u) => u.includes(`-I-${it.site}-`) && (!it.their || u.endsWith(`-${it.their}`)));
  if (!urls.length) { console.log(`${it.our} ${it.site}${it.their ? ':' + it.their : ''}: совпадения нет`); await pause(); continue; }
  for (const u of urls) {
    const tag = `${it.our} → ${u.split('-I-').pop()}`;
    if (!GO) { console.log(`[проба] ${ACTION} ${tag}`); continue; }
    await pause(); await nav(u);
    let ok = false;
    if (ACTION === 'reject') {
      if (await js(visible('a.undo_confirm'))) { await click('a.undo_confirm'); await until(visible('a.reject')); await sleep(1500); }
      if (await click('a.reject')) ok = await until(`/was rejected/.test(document.body.innerText)`);
      else ok = await js(visible('a', 'Undo reject'));                       // уже отклонено
    } else {
      if (await click('a', 'Confirm Match')) ok = await until(`/showExtractWizard/.test(location.href)||/was confirmed|Match confirmed/.test(document.body.innerText)`);
      else ok = await js(`/Match confirmed/.test(document.body.innerText)`);  // уже подтверждено
    }
    console.log(`${ok ? 'готово' : 'НЕ ВЫШЛО'} ${ACTION} ${tag}`); ok ? done++ : failed++;
  }
}
console.log(`итого: ${GO ? `сделано ${done}, не вышло ${failed}` : 'проба, добавь --go'}`);
c.close();
process.exit(failed ? 1 : 0);
