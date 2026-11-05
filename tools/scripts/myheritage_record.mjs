// Записывает запросы страниц MyHeritage (метод, адрес, тело, статус, начало ответа) в JSONL.
// Подключается к браузеру целиком: новые вкладки придерживаются до подключения записи — их первые запросы не теряются.
// Заголовки не пишутся; значения полей с опасными именами и длинные hex-строки вырезаются.
import fs from 'node:fs';
import { cdpPort } from './settings.mjs';
const PORT = cdpPort(), OUT = process.argv[2];
const skip = /\.(png|jpe?g|gif|svg|webp|woff2?|css|ico|mp4|js)(\?|$)|google|facebook|doubleclick|hotjar|analytics|sentry|clarity|bing|tiktok|pinterest|criteo|optimizely/i;

const BAD = /token|sess|csrf|xsrf|captcha|email|password|passwd|auth|cookie|secret|key/i;
const scrub = (s) => {
  if (!s) return s;
  s = s.replace(/(name="([^"]+)"\r?\n\r?\n)([^\r\n]*)/g, (m, h, n) => BAD.test(n) ? h + '<СКРЫТО>' : m);
  s = s.replace(/(^|&|\?)([^=&?]+)=([^&]*)/g, (m, a, n) => { let d = n; try { d = decodeURIComponent(n); } catch {} return BAD.test(d) ? a + n + '=<СКРЫТО>' : m; });
  s = s.replace(/"([^"]+)"\s*:\s*"[^"]*"/g, (m, n) => BAD.test(n) ? '"' + n + '":"<СКРЫТО>"' : m);
  return s.replace(/\b[0-9a-f]{24,}\b/gi, '<HEX>');
};
function write(rec) {
  if (/login|password|auth|mfa|register|Incapsula/i.test(rec.url)) return;
  rec.url = scrub(rec.url); rec.body = scrub(rec.body); rec.resp = scrub(rec.resp || null);
  fs.appendFileSync(OUT, JSON.stringify(rec) + '\n');
}

const ver = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json();
const ws = new WebSocket(ver.webSocketDebuggerUrl);
let n = 0; const pending = {}; const req = {};
const send = (method, params = {}, sessionId) => {
  const id = ++n; ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
  return new Promise((res) => { pending[id] = res; setTimeout(() => { delete pending[id]; res(null); }, 4000); });
};
const key = (sid, rid) => sid + ':' + rid;

ws.onopen = async () => {
  await send('Target.setDiscoverTargets', { discover: true });
  await send('Target.setAutoAttach', { autoAttach: true, waitForDebuggerOnStart: true, flatten: true });
  // уже открытые вкладки
  const ts = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json();
  for (const t of ts) if (t.type === 'page' && /myheritage/.test(t.url)) send('Target.attachToTarget', { targetId: t.id, flatten: true });
  console.log('пишу в', OUT);
};
ws.onmessage = async (m) => {
  const d = JSON.parse(m.data);
  if (d.id && pending[d.id]) { pending[d.id](d.result); delete pending[d.id]; return; }
  const sid = d.sessionId;
  if (d.method === 'Target.attachedToTarget') {
    const s = d.params.sessionId;
    await send('Network.enable', { maxPostDataSize: 200000 }, s);
    await send('Target.setAutoAttach', { autoAttach: true, waitForDebuggerOnStart: true, flatten: true }, s);
    send('Runtime.runIfWaitingForDebugger', {}, s);
    return;
  }
  if (d.method === 'Target.targetCreated' && d.params.targetInfo.type === 'page') return; // авто-подключение сделает своё
  if (d.method === 'Network.requestWillBeSent') {
    const r = d.params.request, k = key(sid, d.params.requestId);
    const prev = req[k];
    if (prev && d.params.redirectResponse) { prev.status = d.params.redirectResponse.status; prev.redirect = r.url.split('?')[0]; delete req[k]; write(prev); }
    if (skip.test(r.url) || !/myheritage/.test(r.url)) return;
    const doc = d.params.type === 'Document';
    if (r.method === 'GET' && !doc && !/api|graph|ajax|\.php|json/i.test(r.url)) return;
    req[k] = { t: new Date().toISOString(), type: d.params.type, method: r.method, url: r.url, body: r.postData || null };
  }
  if (d.method === 'Network.responseReceived' && req[key(sid, d.params.requestId)]) req[key(sid, d.params.requestId)].status = d.params.response.status;
  if (d.method === 'Network.loadingFinished' && req[key(sid, d.params.requestId)]) {
    const k = key(sid, d.params.requestId), rec = req[k]; delete req[k];
    const body = await send('Network.getResponseBody', { requestId: d.params.requestId }, sid);
    rec.resp = body && !body.base64Encoded ? body.body.slice(0, rec.type === 'Document' ? 0 : 3000) : null;
    write(rec);
  }
};
