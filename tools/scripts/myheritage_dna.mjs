/**
 * ДНК на MyHeritage командами: найти совпадения по фамилии и написать совпадению письмо — без модели в каждом шаге.
 *
 * Что это. Работает в своём Chrome проекта (browser_cdp.mjs, порт 9333, вход Павла). Совпадения ищет строка
 * `/dna/matches?search=<фамилия>` — сайт смотрит и имя совпадения, и фамилии предков в его дереве («Lis» находит
 * и «Kowalis»: сверять глазами). Письмо пишется через окно «Skontaktuj się» на странице совпадения.
 * Свой GraphQL-запрос сайт отвергает (403, проверено 02.10.2026), поэтому письмо идёт как у человека: настоящий клик
 * мышью (Input.dispatchMouseEvent — JS-клик кнопка не замечает), поля темы и текста, клик по кнопке отправки.
 * Под капотом страница шлёт POST /web-family-graphql/create_new_thread/ и уходит на /messaging-center/all/mailthread-<номер>.
 * Кнопка «Skontaktuj się» открывает окно письма НОВОЙ вкладкой — скрипт находит её и пишет там.
 * Проверено 29.10.2026: два письма совпадениям ушли и легли в переписку (mailthread-<номер>).
 *
 * Команды (node tools/scripts/myheritage_dna.mjs …):
 *   search <фамилия> [<фамилия> …] [--out файл.tsv] — совпадения: имя, страна, cM, куски, адрес совпадения; пауза 15–20 с
 *   message <адрес совпадения> <тема> <файл с текстом> [--go]
 *                          — без --go: открыть окно, вписать тему и текст и остановиться (Павел смотрит в окне Chrome);
 *                            с --go: отправить и проверить, что открылась переписка. Каждое письмо — только по «да» Павла.
 *
 * Выход: 0 — готово; 1 — ошибка; 2 — неверные параметры; 3 — не вошёл / стоп от сайта.
 */
import fs from 'node:fs';
import { ownTab } from './cdp_tab.mjs';
import { cdpPort } from './settings.mjs';

const PORT = cdpPort();
const BASE = `http://127.0.0.1:${PORT}`;
const SITE = 'https://www.myheritage.pl';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const pause = () => sleep(15000 + Math.random() * 5000);

function connect(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    let id = 0;
    const pending = new Map();
    ws.addEventListener('open', () => resolve({
      send(method, params = {}) {
        return new Promise((res, rej) => { const my = ++id; pending.set(my, { res, rej }); ws.send(JSON.stringify({ id: my, method, params })); });
      },
      close: () => ws.close(),
    }));
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && pending.has(msg.id)) {
        const { res, rej } = pending.get(msg.id);
        pending.delete(msg.id);
        msg.error ? rej(new Error(msg.error.message || JSON.stringify(msg.error))) : res(msg.result);
      }
    });
    ws.addEventListener('error', (e) => reject(new Error('нет связи с Chrome: ' + (e.message || e.type))));
  });
}

const tabs = async () => (await (await fetch(`${BASE}/json`)).json()).filter((t) => t.type === 'page' && t.webSocketDebuggerUrl);

// рабочая вкладка — своя у сессии, как в browser_cdp.mjs (cdp_tab.mjs)
async function page() {
  try { await fetch(`${BASE}/json/version`); } catch { console.error('Chrome не запущен: node tools/scripts/browser_cdp.mjs start'); process.exit(1); }
  const c = await connect((await ownTab(BASE)).webSocketDebuggerUrl);
  await c.send('Runtime.enable');
  return c;
}

async function evaluate(c, expression) {
  const r = await c.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) throw new Error('JS: ' + (r.exceptionDetails.exception?.description || r.exceptionDetails.text));
  return r.result.value;
}

// ждать, пока условие на странице станет истинным (страница — React, грузится частями)
// окно письма иногда открывается отдельной страницей (/messaging-center/all/compose/…): пока она грузится, JS падает
async function waitFor(c, js, timeout = 60000) {
  for (const end = Date.now() + timeout; Date.now() < end; await sleep(1000)) if (await evaluate(c, js).catch(() => false)) return true;
  return false;
}

async function go(c, url) {
  await c.send('Page.navigate', { url });
  await sleep(3000);
  if (await evaluate(c, `/login|signin/i.test(location.pathname)`)) { console.error('не вошёл: войди на MyHeritage в окне Chrome проекта'); process.exit(3); }
}

// настоящий клик мышью по центру элемента
async function click(c, selector) {
  const at = await evaluate(c, `(()=>{const e=document.querySelector(${JSON.stringify(selector)});if(!e)return null;e.scrollIntoView({block:'center'});const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);
  if (!at) throw new Error('нет элемента ' + selector);
  for (const type of ['mouseMoved', 'mousePressed', 'mouseReleased']) await c.send('Input.dispatchMouseEvent', { type, x: at.x, y: at.y, button: 'left', clickCount: 1 });
}

// карточки совпадений на странице списка: имя, страна, cM, куски, адрес; карточка — ближайший предок ссылки
// с «czeka na Twój kontakt»; между числом и «cM» сайт ставит невидимый знак направления (U+200E)
const READ_MATCHES = `(()=>{const out=[];for(const a of document.querySelectorAll('a[href*="/dna/match/"]')){
  let card=a;while(card&&!/czeka na|Skontaktuj/.test(card.innerText||''))card=card.parentElement;if(!card)continue;
  const t=card.innerText,lines=t.split('\\n').map(s=>s.trim()).filter(Boolean);
  const cm=(t.match(/\\(([\\d,]+)[^\\d)]*cM\\)/)||[])[1]||'';const seg=(t.match(/(\\d+)\\s*\\nWspólne segmenty/)||[])[1]||'';
  out.push({name:lines.find(l=>!/^Dodaj etykiety$/.test(l))||'',country:(t.match(/Z:\\s*([^\\n]+)/)||[])[1]||'',cm:cm.replace(',','.').replace(/\\s/g,''),seg,url:a.href.split('?')[0]});}
  const seen=new Set();return out.filter(m=>!seen.has(m.url)&&seen.add(m.url));})()`;

async function cmdSearch(names, out) {
  const c = await page();
  const rows = [];
  try {
    for (const [i, name] of names.entries()) {
      if (i) await pause();
      await go(c, `${SITE}/dna/matches?search=${encodeURIComponent(name)}`);
      await waitFor(c, `/Znaleziono|Nie znaleziono|z podobieństw/.test(document.body.innerText)`);
      const found = await evaluate(c, READ_MATCHES);
      console.log(`=== ${name}: ${found.length}`);
      for (const m of found) { console.log(`${m.name}\t${m.country}\t${m.cm} cM\t${m.seg}\t${m.url}`); rows.push([name, m.name, m.country, m.cm, m.seg, m.url].join('\t')); }
    }
  } finally { c.close(); }
  if (out) { fs.writeFileSync(out, ['фамилия\tимя\tстрана\tcM\tкуски\tадрес', ...rows].join('\n') + '\n'); console.log('→', out); }
}

async function cmdMessage(matchUrl, subject, file, send) {
  const text = fs.readFileSync(file, 'utf8').trim();
  let c = await page();
  try {
    await go(c, matchUrl);
    if (!await waitFor(c, `!!document.querySelector('.contact_match_section button')`)) throw new Error('нет кнопки «Skontaktuj się» — это страница совпадения?');
    const before = new Set((await tabs()).map((t) => t.id));
    await click(c, '.contact_match_section button');
    // окно письма открывается НОВОЙ вкладкой (/messaging-center/all/compose/user-…) — переходим в неё
    let tab = null;
    for (const end = Date.now() + 30000; !tab && Date.now() < end; await sleep(1000)) tab = (await tabs()).find((t) => !before.has(t.id) && /\/messaging-center\/all\/compose\//.test(t.url));
    if (tab) { c.close(); c = await connect(tab.webSocketDebuggerUrl); await c.send('Runtime.enable'); }
    if (!await waitFor(c, `!!document.querySelector('textarea.chat_input_textarea')`)) throw new Error('окно письма не открылось');
    // React: значение через сеттер прототипа и событие input, иначе форма поле не видит
    const filled = await evaluate(c, `(()=>{const set=(e,v)=>{const p=e.tagName=='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(p,'value').set.call(e,v);e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}))};
      const s=document.querySelector('input.subject_text_field');if(s)set(s,${JSON.stringify(subject)});const t=document.querySelector('textarea.chat_input_textarea');set(t,${JSON.stringify(text)});return t.value.length})()`);
    console.log(`вписано: тема «${subject}», текст ${filled} знаков`);
    if (!send) { console.log('не отправлено (нет --go): посмотри окно Chrome'); return; }
    await click(c, 'button.chat_input_button');
    if (!await waitFor(c, `/mailthread-\\d+/.test(location.href)`, 20000)) throw new Error('переписка не открылась — проверь «Wiadomości» руками');
    console.log('отправлено:', await evaluate(c, 'location.href'));
  } finally { c.close(); }
}

const argv = process.argv.slice(2);
const flag = (n) => { const i = argv.indexOf(n); if (i < 0) return null; const v = argv[i + 1]; argv.splice(i, 2); return v; };
const has = (n) => { const i = argv.indexOf(n); if (i < 0) return false; argv.splice(i, 1); return true; };
const cmd = argv[0];
const out = cmd === 'search' ? flag('--out') : null;
const sendIt = has('--go');
const args = argv.slice(1);
if (cmd === 'search' && args.length) await cmdSearch(args, out);
else if (cmd === 'message' && args.length === 3) await cmdMessage(args[0], args[1], args[2], sendIt);
else { console.error('Команды: search <фамилия>… [--out файл] | message <адрес совпадения> <тема> <файл> [--go]'); process.exit(2); }
