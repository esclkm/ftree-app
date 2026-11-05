/**
 * Маленький CDP-хелпер для совместной работы с Chrome (без Playwright).
 * Использует встроенный в Node 24 глобальный WebSocket — никаких npm-пакетов.
 *
 * Запуск Chrome (один раз):
 *   "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
 *     --remote-debugging-port=9222 --user-data-dir="$PWD/.wbh-profile" \
 *     "https://wbh.wp.mil.pl/pl/skanywyszukiwarka_zaawansowana/"
 *
 * Команды:
 *   node tools/scripts/wbh_cdp.mjs targets                 — список вкладок
 *   node tools/scripts/wbh_cdp.mjs nav <url>               — открыть URL в активной вкладке
 *   node tools/scripts/wbh_cdp.mjs eval '<js-выражение>'   — выполнить JS на странице, вернуть JSON
 *   node tools/scripts/wbh_cdp.mjs url                      — текущий URL вкладки
 */

const PORT = process.env.CDP_PORT || 9222;
const BASE = `http://127.0.0.1:${PORT}`;

async function pickTarget() {
  const res = await fetch(`${BASE}/json`);
  const list = await res.json();
  // предпочитаем вкладку wbh, иначе первую обычную страницу
  const pages = list.filter((t) => t.type === 'page' && t.webSocketDebuggerUrl);
  if (!pages.length) throw new Error('Нет открытых вкладок (page targets). Открыт ли Chrome с --remote-debugging-port?');
  return pages.find((t) => /wbh\.wp\.mil\.pl/.test(t.url)) || pages[0];
}

function cdp(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    let id = 0;
    const pending = new Map();
    ws.addEventListener('open', () =>
      resolve({
        send(method, params = {}) {
          return new Promise((res, rej) => {
            const myId = ++id;
            pending.set(myId, { res, rej });
            ws.send(JSON.stringify({ id: myId, method, params }));
          });
        },
        close: () => ws.close(),
      })
    );
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && pending.has(msg.id)) {
        const { res, rej } = pending.get(msg.id);
        pending.delete(msg.id);
        msg.error ? rej(new Error(JSON.stringify(msg.error))) : res(msg.result);
      }
    });
    ws.addEventListener('error', (e) => reject(new Error('WS error: ' + (e.message || e.type))));
  });
}

async function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  if (cmd === 'targets') {
    const res = await fetch(`${BASE}/json`);
    const list = await res.json();
    for (const t of list) console.log(`${t.type}\t${t.url}`);
    return;
  }
  const t = await pickTarget();
  const client = await cdp(t.webSocketDebuggerUrl);
  try {
    if (cmd === 'nav') {
      await client.send('Page.enable');
      await client.send('Page.navigate', { url: rest[0] });
      console.log('navigated:', rest[0]);
    } else if (cmd === 'shot') {
      const fs = await import('node:fs');
      await client.send('Page.enable');
      const r = await client.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
      fs.writeFileSync(rest[0] || '/tmp/wbh_shot.png', Buffer.from(r.data, 'base64'));
      console.log('saved', rest[0] || '/tmp/wbh_shot.png');
    } else if (cmd === 'imgdata') {
      // вытащить same-origin картинку как data-URL через canvas и сохранить
      const fs = await import('node:fs');
      const url = rest[0];
      const out = rest[1] || '/tmp/wbh_img.jpg';
      const r = await client.send('Runtime.evaluate', {
        expression: `(async()=>{const img=new Image();img.crossOrigin="anonymous";const ok=await new Promise(res=>{img.onload=()=>res(true);img.onerror=()=>res(false);img.src=${JSON.stringify(url)};setTimeout(()=>res(false),15000);});if(!ok||!img.naturalWidth)return "__FAIL__";const c=document.createElement("canvas");c.width=img.naturalWidth;c.height=img.naturalHeight;c.getContext("2d").drawImage(img,0,0);return c.toDataURL("image/jpeg",0.92);})()`,
        returnByValue: true,
        awaitPromise: true,
      });
      const val = typeof r.result.value === 'string' ? r.result.value : '';
      const b64 = val === '__FAIL__' ? '' : val.split(',')[1];
      if (!b64) { console.error('FAIL (нет/не загрузилось):', url); process.exitCode = 1; }
      else { fs.writeFileSync(out, Buffer.from(b64, 'base64')); console.log('saved', out); }
    } else if (cmd === 'url') {
      const r = await client.send('Runtime.evaluate', { expression: 'location.href', returnByValue: true });
      console.log(r.result.value);
    } else if (cmd === 'eval') {
      const expr = rest.join(' ');
      const r = await client.send('Runtime.evaluate', {
        expression: expr,
        returnByValue: true,
        awaitPromise: true,
      });
      if (r.exceptionDetails) {
        console.error('JS-исключение:', JSON.stringify(r.exceptionDetails.exception?.description || r.exceptionDetails, null, 2));
        process.exitCode = 1;
      } else {
        const v = r.result.value;
        console.log(typeof v === 'string' ? v : JSON.stringify(v, null, 2));
      }
    } else {
      console.error('Команды: targets | nav <url> | url | eval <js>');
      process.exitCode = 2;
    }
  } finally {
    client.close();
  }
}

main().catch((e) => {
  console.error('Ошибка:', e.message);
  process.exitCode = 1;
});
