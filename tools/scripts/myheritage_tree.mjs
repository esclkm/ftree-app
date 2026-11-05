#!/usr/bin/env node
/**
 * Прочитать ЧУЖОЕ дерево MyHeritage (сайт другого человека) — только чтение, без ИИ.
 *
 * Зачем. Smart Match показывает лишь одного человека и его ближайших. Остальное дерево (братья, дети, внуки, супруги)
 * видно на страницах профилей, но родня там без ссылок: её подгружает запрос web-family-graphql/profile_details_data.
 * Скрипт открывает профиль во вкладке Chrome проекта (browser_cdp.mjs, порт 9333, Павел вошёл), ловит ответ этого
 * запроса целиком и идёт по родне в ширину. Ключ сессии (bearer_token) скрипт не видит: запрос шлёт сама страница.
 *
 *   node tools/scripts/myheritage_tree.mjs matches <наш номер>[,<номер>…] [--status 8] [--deep] --out файл.json
 *     совпадения наших людей (8 подтверждённые, 32 ждут, 64 новые, 16 отклонённые; 0 — все): чей сайт, кто ведёт,
 *     номер, имя, даты, родня (ответ web-family-graphql/matches_for_person_fetch_entries). --deep — ещё и профиль
 *     каждого найденного (события с местами и источниками, как в обходе дерева).
 *   node tools/scripts/myheritage_tree.mjs watch [--first <наш номер>,…] [--deep] [--resume]
 *     --first — этих читать первыми и с профилями (прямые предки), остальных — без профилей (в 3–4 раза быстрее);
 *     --deep — профили всем; --resume — продолжить прерванный проход с others/_partial.json.
 *     слежка: все наши люди с подтверждёнными совпадениями → их записи и профили в чужих деревьях → снимок
 *     3_research/tree_data/mh_web/others/<дата>.json, сравнение с прошлым, отчёт findings/_MyHeritage_чужие_деревья_<дата>.md
 *     (новые совпадения, новые/исчезнувшие факты и родня, новые деревья). По ходу — others/_partial.json
 *     (myheritage_compare.py --snapshot …/_partial.json показывает находки, не дожидаясь конца). MyHeritage сам сообщает только о новых совпадениях.
 *   node tools/scripts/myheritage_tree.mjs <сайт> <номер профиля> [--max 40] [--depth 3] [--out файл.json]
 *     <сайт>   — 31 знак, начинается с OYYV (из адреса match-compare: I-<наш>-1-<id>-I-<сайт>-<дерево>-<id>)
 *     <номер>  — номер человека в том дереве (2500026); профиль: /profile-<сайт>-<номер>/x
 *   Вывод: строка на человека — номер · имя · годы · события (дата, место, источник) · родня (кто кем) — и JSON.
 *
 * Как найти сайт и номер: наши совпадения человека —
 *   /discovery-hub/<наш сайт>/matches-for-person/<наш номер>?matchType=2&matchStatus=8   (8 подтверждённые, 32 ждут,
 *   64 новые, 16 отклонённые) → «Review match» → адрес match-compare/…-I-<сайт>-<дерево>-<номер>.
 *
 * Бережём сайт: один профиль в 8–14 с, своя вкладка (открывает и закрывает сама, чужие не трогает); 403/429/капча/Incapsula — СТОП (код 3).
 * Выход: 0 — готово; 1 — ошибка; 2 — неверные параметры; 3 — стоп от сайта.
 */
import fs from 'node:fs';
import { cdpPort, settings } from './settings.mjs';

const PORT = cdpPort();
const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d; };
const pos = args.filter((a, i) => !a.startsWith('--') && !(args[i - 1] || '').startsWith('--'));
const MODE = ['matches', 'watch'].includes(pos[0]) ? pos[0] : 'tree';
const OUR_SITE = settings().MYHERITAGE_SITE;  // номер нашего дерева — ftree.toml, [myheritage] site
let [SITE, START] = MODE === 'tree' ? pos : [OUR_SITE, pos[1]];
if (MODE === 'matches' && !/^\d+(,\d+)*$/.test(START || '')) { console.error('нужно: matches <наш номер>[,<номер>…]'); process.exit(2); }
if (MODE === 'tree' && (!/^[A-Z0-9]{31}$/.test(SITE || '') || !/^\d+$/.test(START || ''))) {
  console.error('нужно: <сайт из 31 знака> <номер профиля> [--max N] [--depth N] [--out файл]'); process.exit(2);
}
const MAX = +opt('--max', 40), DEPTH = +opt('--depth', 3), OUT = opt('--out', null);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// своя вкладка: в том же Chrome могут работать другие сессии — их вкладки не трогаем; в конце закрываем свою
let tab;
try { tab = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' })).json(); }
catch { console.error('Chrome проекта не запущен: node tools/scripts/browser_cdp.mjs start'); process.exit(3); }
const closeTab = () => fetch(`http://127.0.0.1:${PORT}/json/close/${tab.id}`).catch(() => {});
for (const sig of ['SIGTERM', 'SIGINT']) process.on(sig, async () => { await closeTab(); process.exit(130); });
const ws = new WebSocket(tab.webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));
let n = 0; const pending = {}; const listeners = [];
ws.onmessage = (m) => {
  const d = JSON.parse(m.data);
  if (d.id && pending[d.id]) { pending[d.id](d); delete pending[d.id]; return; }
  for (const f of listeners) f(d);
};
const send = (method, params = {}) => new Promise((res) => { const id = ++n; pending[id] = res; ws.send(JSON.stringify({ id, method, params })); });
await send('Network.enable', { maxPostDataSize: 0 });
await send('Page.enable');

/** Открыть профиль и дождаться ответа profile_details_data. */
async function readProfile(id, site = SITE) {
  let reqId = null, status = 0, docStatus = 0;
  const done = new Promise((resolve) => {
    const f = async (d) => {
      if (d.method === 'Network.responseReceived') {
        if (d.params.type === 'Document') docStatus = d.params.response.status;
        if (/profile_details_data/.test(d.params.response.url)) { reqId = d.params.requestId; status = d.params.response.status; }
      }
      if (d.method === 'Network.loadingFinished' && d.params.requestId === reqId) {
        listeners.splice(listeners.indexOf(f), 1);
        const b = await send('Network.getResponseBody', { requestId: reqId });
        resolve(b.result?.body || null);
      }
    };
    listeners.push(f);
    setTimeout(() => { const i = listeners.indexOf(f); if (i >= 0) listeners.splice(i, 1); resolve(null); }, 25000);
  });
  await send('Page.navigate', { url: `https://www.myheritage.com/profile-${site}-${id}/x` });
  const body = await done;
  if ([403, 429].includes(docStatus) || [403, 429].includes(status)) return { stop: `ответ ${docStatus || status}` };
  const t = await send('Runtime.evaluate', { expression: 'document.title + "\\n" + document.body.innerText.slice(0, 400)', returnByValue: true });
  const page = t.result?.result?.value || '';
  if (/Incapsula|captcha|robot/i.test(page)) return { stop: 'защита сайта / капча' };
  if (!body) return { error: 'нет данных о родне', title: page.split('\n')[0] };
  return { title: page.split('\n')[0].replace(/ - .*$/, ''), data: JSON.parse(body).data?.profile?.individual };
}

const OTHERS = settings().MH_OTHERS;           // снимки чужих деревьев (в git не храним)
const REPORT_DIR = settings().FINDINGS;

/** Снимок → {«сайт-номер»: {who, our, name, events, facts:Set, family:Set}} для сравнения. */
function flat(people) {
  const out = {};
  for (const it of Object.values(people)) for (const m of it.matches) {
    const p = m.profile || {};
    out[`${m.site}-${m.id}`] = { our: `${it.name} (${it.our})`, tree: `${m.site_name} — ${m.manager}, ${m.country}`, name: m.name,
      facts: (p.facts || []).map((f) => `${f.title} ${f.date} ${f.place}${f.content ? ' «' + f.content + '»' : ''}`.trim()),
      family: (p.family || []).map((x) => `${x.rel}: ${x.name} ${x.lifespan}`.trim()) };
  }
  return out;
}

/** Сохранить снимок, сравнить с прошлым, записать отчёт. */
function watchReport(people, fresh) {
  fs.mkdirSync(OTHERS, { recursive: true });
  const day = new Date().toISOString().slice(0, 10);
  const prevFile = fs.readdirSync(OTHERS).filter((f) => /^\d{4}-\d\d-\d\d\.json$/.test(f) && f < day + '.json').sort().pop();
  fs.writeFileSync(`${OTHERS}/${day}.json`, JSON.stringify({ read: new Date().toISOString(), people }, null, 1));
  const now = flat(people), was = prevFile ? flat(JSON.parse(fs.readFileSync(`${OTHERS}/${prevFile}`, 'utf8')).people) : null;
  const L = [`# MyHeritage — чужие деревья, где есть наши люди (${day})`, '',
    `Собрано \`node tools/scripts/myheritage_tree.mjs watch\` (навык archive-myheritage-trees). Сравнение — с ${prevFile ? prevFile.replace('.json', '') : '— (первый снимок)'}.`, ''];
  L.push('## Новые совпадения — ждут решения на MyHeritage', '', fresh.length ? fresh.map((x) => `- ${x[1]} (${x[0]}) — ${x[2]}`).join('\n') : 'нет', '');
  L.push('## Что изменилось в чужих деревьях', '');
  let changes = 0;
  if (was) for (const [k, v] of Object.entries(now)) {
    const o = was[k];
    if (!o) { L.push(`- **${v.our}** — новое дерево: ${v.tree}, «${v.name}»`); changes++; continue; }
    const add = (a, b) => a.filter((x) => !b.includes(x));
    const d = [...add(v.facts, o.facts).map((x) => '+ ' + x), ...add(o.facts, v.facts).map((x) => '− ' + x),
      ...add(v.family, o.family).map((x) => '+ ' + x), ...add(o.family, v.family).map((x) => '− ' + x)];
    if (o.name !== v.name) d.unshift(`имя: «${o.name}» → «${v.name}»`);
    if (d.length) { L.push(`- **${v.our}** · ${v.tree}: ${d.join('; ')}`); changes++; }
  }
  if (!was) L.push('первый снимок — сравнивать не с чем');
  else if (!changes) L.push('изменений нет');
  L.push('', '## Деревья на учёте', '', '| Наш человек | Дерево | Их запись |', '|---|---|---|');
  for (const v of Object.values(now)) L.push(`| ${v.our} | ${v.tree} | ${v.name} |`);
  const rep = `${REPORT_DIR}/_MyHeritage_чужие_деревья_${day}.md`;
  fs.writeFileSync(rep, L.join('\n') + '\n');
  console.log(`снимок: ${OTHERS}/${day}.json; отчёт: ${rep}; изменений: ${was ? changes : '—'}`);
}

const num = (s) => (s || '').match(/-(\d+)$/)?.[1];

/** Открыть страницу и вернуть тело первого ответа, чей адрес подходит под re. */
async function capture(url, re) {
  let reqId = null, docStatus = 0;
  const done = new Promise((resolve) => {
    const f = async (d) => {
      if (d.method === 'Network.responseReceived') {
        if (d.params.type === 'Document') docStatus = d.params.response.status;
        if (re.test(d.params.response.url)) reqId = d.params.requestId;
      }
      if (d.method === 'Network.loadingFinished' && d.params.requestId === reqId) {
        listeners.splice(listeners.indexOf(f), 1);
        resolve((await send('Network.getResponseBody', { requestId: reqId })).result?.body || null);
      }
    };
    listeners.push(f);
    setTimeout(() => { const i = listeners.indexOf(f); if (i >= 0) listeners.splice(i, 1); resolve(null); }, 25000);
  });
  await send('Page.navigate', { url });
  const body = await done;
  return { body, stop: [403, 429].includes(docStatus) ? `ответ ${docStatus}` : null };
}

/** Профиль → события и родня (общая часть обхода дерева и --deep). */
function profileOf(id, r) {
  const p = { id, name: r.title, alive: r.data?.is_alive ?? null, facts: [], family: [] };
  for (const f of r.data?.event_facts?.data || []) {
    if (f.is_fact_of_relative) continue;
    const src = (f.citations?.data || []).map((c) => c.source?.name).filter(Boolean);
    p.facts.push({ type: f.type, title: f.title, date: f.date?.text || '', place: f.formatted_place || '', content: f.content || '',
      spouse: f.spouse?.name || '', sources: [...new Set(src)] });
  }
  for (const g of r.data?.family_groups || [])
    for (const x of [g.father, g.mother, g.spouse, ...(g.siblings || []), ...(g.children || [])].filter(Boolean))
      p.family.push({ rel: x.relationship_type, id: num(x.individual?.id), name: x.individual?.name, lifespan: x.individual?.lifespan || '' });
  return p;
}

if (MODE === 'watch') {
  // все наши люди с подтверждёнными совпадениями + сколько новых (ждут решения Павла)
  const list = async (st) => {
    const ids = [];
    for (let off = 0; off < 2000; off += 20) {
      const u = `/FP/API/DiscoveryHub/fetch-matches-by-people.php?action=getResults&s=${OUR_SITE}&lang=EN&familyTreeId=&offset=${off}&count=20` +
        `&filtersState%5BmatchType%5D=2&filtersState%5BmatchStatus%5D=${st}&filtersState%5BconfirmedByOthers%5D=0&filtersState%5BsortBy%5D=4&filtersState%5Bquery%5D=&is_ignored=0`;
      const r = await send('Runtime.evaluate', { expression: `fetch(${JSON.stringify(u)},{credentials:'include'}).then(r=>r.json())`, awaitPromise: true, returnByValue: true });
      const L = r.result?.result?.value?.data?.individualsWithMatches || [];
      ids.push(...L.map((i) => [String(i.individualId), i.fullName, i.numberOfMatches]));
      if (L.length < 20) break;
      await sleep(7000);
    }
    return ids;
  };
  await send('Page.navigate', { url: `https://www.myheritage.com/discovery-hub/${OUR_SITE}/main` }); await sleep(8000);
  const conf = await list(8); await sleep(7000);
  const fresh = await list(64);
  console.log(`подтверждённые совпадения: людей ${conf.length}; новые (ждут решения): ${fresh.map((x) => x[1] + ' ×' + x[2]).join(', ') || 'нет'}`);
  globalThis.WATCH_NEW = fresh;
  const first = (opt('--first', '') || '').split(',').filter(Boolean);    // кого читать первым (напр. прямых предков)
  START = [...first.filter((f) => conf.some((x) => x[0] === f)), ...conf.map((x) => x[0]).filter((x) => !first.includes(x))].join(',');
}

if (MODE === 'matches' || MODE === 'watch') {
  const STATUS = MODE === 'watch' ? '8' : opt('--status', '8'), res = {};
  // профиль в чужом дереве: matches --deep — всем; watch — только тем, кто в --first (прямые предки), или всем с --deep
  const FIRST = (opt('--first', '') || '').split(',').filter(Boolean);
  const deepFor = (our) => args.includes('--deep') || (MODE === 'watch' && (!FIRST.length || FIRST.includes(our)));
  if (MODE === 'watch' && args.includes('--resume') && fs.existsSync(`${OTHERS}/_partial.json`))   // продолжить прерванный
    Object.assign(res, JSON.parse(fs.readFileSync(`${OTHERS}/_partial.json`, 'utf8')).people);
  outer: for (const our of START.split(',')) {
    if (res[our]) continue;
    const DEEP = deepFor(our);
    const q = STATUS === '0' ? '' : `&matchStatus=${STATUS}`;
    const r = await capture(`https://www.myheritage.com/discovery-hub/${OUR_SITE}/matches-for-person/${our}?matchType=2${q}&confirmedByOthers=0`,
      /matches_for_person_fetch_entries/);
    if (r.stop) { console.error(`СТОП (${our}): ${r.stop}`); process.exitCode = 3; break; }
    const ind = r.body ? JSON.parse(r.body).data?.individual : null;
    if (!ind) { console.error(`${our}: нет ответа о совпадениях`); continue; }
    const ev = (e) => (e?.events?.data || []).map((x) => `${x.event_type} ${x.date?.text || ''}${x.place ? ' ' + x.place : ''}`).join('; ');
    const item = { our, name: ind.name, events: ev(ind), matches: [] };
    for (const m of ind.matches?.data || []) {
      const o = m.other_individual || {};
      const site = (o.site?.id || '').replace('site-', ''), oid = num(o.id);
      const mm = { status: m.match_status, site, site_name: o.site?.name, manager: o.site?.creator?.name, country: o.site?.creator?.country,
        id: oid, name: o.name, events: ev(o), fields: Object.fromEntries((m.record?.display_fields || []).map((f) => [f.label, f.value])) };
      if (DEEP && site && oid) {
        await sleep(8000 + Math.random() * 6000);
        const pr = await readProfile(oid, site);
        if (pr.stop) { console.error(`СТОП (${site}-${oid}): ${pr.stop}`); process.exitCode = 3; item.matches.push(mm); res[our] = item; break outer; }
        mm.profile = profileOf(oid, pr);
      }
      item.matches.push(mm);
    }
    res[our] = item;
    if (MODE === 'watch') {   // промежуточный снимок после каждого человека: смотреть по ходу и не терять при остановке
      fs.mkdirSync(OTHERS, { recursive: true });
      fs.writeFileSync(`${OTHERS}/_partial.json`, JSON.stringify({ read: new Date().toISOString(), people: res }, null, 1));
    }
    console.log(`${our} · ${item.name} · ${item.events}`);
    for (const m of item.matches) console.log(`   ${m.status} · ${m.site_name} (${m.manager}, ${m.country}) #${m.id} · ${m.name} · ${m.events}`);
    await sleep(8000 + Math.random() * 6000);
  }
  if (OUT) fs.writeFileSync(OUT, JSON.stringify({ read: new Date().toISOString(), people: res }, null, 1));
  if (MODE === 'watch' && !process.exitCode) watchReport(res, globalThis.WATCH_NEW || []);
  ws.close(); await closeTab(); process.exit(process.exitCode || 0);
}
const people = {}; const queue = [[START, 0]]; const seen = new Set([START]);
while (queue.length && Object.keys(people).length < MAX) {
  const [id, depth] = queue.shift();
  const r = await readProfile(id);
  if (r.stop) { console.error(`СТОП (${id}): ${r.stop}`); process.exitCode = 3; break; }
  const p = profileOf(id, r);
  for (const x of p.family)
    if (x.id && !seen.has(x.id) && depth + 1 <= DEPTH) { seen.add(x.id); queue.push([x.id, depth + 1]); }
  people[id] = p;
  const facts = p.facts.map((f) => `${f.title} ${f.date} ${f.place}${f.content ? ' «' + f.content + '»' : ''}${f.sources.length ? ' [' + f.sources.join('; ') + ']' : ''}`.trim()).join(' · ');
  console.log(`${id} · ${p.name}${p.alive ? ' (жив)' : ''} · ${facts || '—'} · ${p.family.map((x) => `${x.rel}: ${x.name} ${x.lifespan} #${x.id}`).join('; ')}`);
  if (queue.length) await sleep(8000 + Math.random() * 6000);
}
if (OUT) fs.writeFileSync(OUT, JSON.stringify({ site: SITE, start: START, read: new Date().toISOString(), people }, null, 1));
if (queue.length) console.error(`не прочитано (предел --max ${MAX}): ${queue.map((q) => q[0]).join(', ')}`);
ws.close();
await closeTab();
