#!/usr/bin/env node
/**
 * Дерево на сайте MyHeritage ⇄ наши карточки — сторона браузера: прочитать дерево и загрузить правки. Без ИИ.
 *
 * Зачем. Дерево MyHeritage ищет совпадения (Smart Matches) только по тому, что лежит в нём. Импорт GEDCOM всегда
 * создаёт второе дерево, а Family Tree Builder на этом Mac не работает — поэтому правим сам сайт теми же запросами,
 * которые шлёт его страница. Запросы идут из вкладки Chrome проекта, где вошёл Павел (browser_cdp.mjs, порт 9333):
 * пароль, cookie и защитные поля скрипт не видит и не печатает.
 *
 * Одной командой: tools/mh pull | push [--go] | status | plan.
 * Три шага (сравнение карточек со снимком — myheritage_plan.py, он не ходит в сеть):
 *   1. node tools/scripts/myheritage_web.mjs collect          — прочитать всё дерево 1 → снимок на диск
 *   2. tools/py tools/scripts/myheritage_plan.py plan         — снимок против карточек → список работ (plan_to_site.md)
 *      Павел просматривает список и вычёркивает лишнее: строка с «[ ]» вместо «[x]» не загрузится.
 *   3. node tools/scripts/myheritage_web.mjs upload [--go]    — выполнить список; без --go — только показать
 *   потом снова collect: сверка того, что легло на сайт.
 *
 * События (с 25.10.2026): событие из 3_research/tree/events с полем mh_fact: IMMI (прибытие) · EMIG (отъезд) · RESI
 *   (жительство) уходит на сайт каждому его человеку, кто есть на сайте и не жив. Без mh_fact событие не грузится — так
 *   на сайт идут переезды и жизнь за границей, по которым MyHeritage ищет судовые списки и переписи. Жительство — форма
 *   адреса (город, страна), галочка «текущий адрес» снимается. Сделанное по журналу второй раз не уходит.
 *
 * Брак, развод, работа, главное фото (с 04.11.2026; список составляет myheritage_plan.py):
 *   family     — дата и место брака (развод — статус Divorced) в форме профиля одного из супругов: поля marriageDate<n>,
 *                marriagePlace<n>, relationshipWithSpouse<n>; на сайте видно у обоих; уже так — не пишем;
 *   occupation — событие OCCU («Zatrudnienie», категория 12), текст — в «Opis»;
 *   photo      — главное фото тем, у кого на сайте фото нет: профиль → круг фото → файл → OK (как человек).
 *   Только на myheritage.pl: на .com те же запросы дают 403 (04.11.2026), поэтому вкладка .pl берётся первой.
 *
 * Прочее:
 *   status                — сколько сделано сегодня, что в журнале, когда был снимок
 *   peek <адрес>          — только чтение: поля формы по адресу страницы (без защитных); для разведки
 *   probe <номер> '<json>' [--go] — пробная запись одному человеку, для разведки и починки; json — как patch в plan.json
 *   --limit N             — upload: не больше N работ за запуск
 *   --relink              — upload: связь, где у ребёнка на сайте ДРУГИЕ родители, — отвязать от них и привязать к нашим
 *                           (без флага такая связь останавливается с объяснением: это правка чужих связей)
 *   --only field|person|event|link|family|occupation|photo — upload: только этот вид работ;  --work <номер работы> — только одна
 *
 * Бережём сайт (стоит защита Imperva/Incapsula) — всё это зашито, отключить нельзя:
 *   • один запрос в 6–12 с (случайно), одна вкладка, по очереди; язык сайта не трогаем;
 *   • пачка 25 работ, потом пауза 5–10 мин; за день не больше 1000 чтений и 400 записей;
 *   • 403/429, страница Incapsula или капча — СТОП сразу (код 3), повторять нельзя, капчу решает Павел;
 *   • каждая работа — строка в журнале; сделанное повторно не выполняется, запуск продолжается с места.
 * Выход: 0 — готово; 1 — ошибка; 2 — неверные параметры; 3 — стоп от сайта / не открыт MyHeritage.
 *
 * Файлы (3_research/tree_data/mh_web/, в git не храним): snapshot.json · plan.json · plan_to_site.md ·
 * journal.jsonl · state.json. Единственное, что лежит в git: <папка поиска>/myheritage_ids.json — «карточка → номер
 * человека, которого мы создали на сайте». Потеряешь — при следующем запуске создадим тех же людей второй раз.
 */
import fs from 'node:fs';
import path from 'node:path';
import { cdpPort, settings } from './settings.mjs';

const ROOT = settings().ROOT;  // корень дерева (paths.py)
export const DATA = settings().MH_WEB;
const F = {
  snapshot: path.join(DATA, 'snapshot.json'),
  plan: path.join(DATA, 'plan.json'),
  planMd: path.join(DATA, 'plan_to_site.md'),
  journal: path.join(DATA, 'journal.jsonl'),
  state: path.join(DATA, 'state.json'),
  idMap: settings().MYHERITAGE_IDS,
};
const PORT = cdpPort();
const TREE_ID = '1';                       // основное дерево (решил Павел 02.10.2026); 4 — наш импорт, его удалят
const LIMITS = { readsPerDay: 1000, writesPerDay: 400, batch: 25 };   // 10.10.2026 Павел поднял: 400→1000 чтений, 150→400 записей
const PACE = [6000, 12000];                // мс между запросами
const BATCH_PAUSE = [300000, 600000];      // мс между пачками
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const rnd = ([a, b]) => a + Math.random() * (b - a);
const log = (...a) => console.log(new Date().toTimeString().slice(0, 8), ...a);

class Stop extends Error {}                // сайт просит остановиться — дальше не идём

// ─── Журнал, счётчики за день, файлы ──────────────────────────────────────────────────────────

fs.mkdirSync(DATA, { recursive: true });
const readJson = (p, dflt) => (fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, 'utf8')) : dflt);
const writeJson = (p, v) => fs.writeFileSync(p, JSON.stringify(v, null, 1) + '\n');
const journal = (rec) => fs.appendFileSync(F.journal, JSON.stringify({ t: new Date().toISOString(), ...rec }) + '\n');
const doneIds = () =>
  new Set(
    fs.existsSync(F.journal)
      ? fs.readFileSync(F.journal, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l)).filter((r) => r.status === 'ok').map((r) => r.work)
      : [],
  );
const today = () => new Date().toLocaleDateString('sv');
function counters() {
  const s = readJson(F.state, {});
  if (s.day !== today()) return { day: today(), reads: 0, writes: 0 };
  return s;
}
const bump = (kind) => { const s = counters(); s[kind]++; writeJson(F.state, s); return s; };

// ─── Вкладка Chrome по CDP ─────────────────────────────────────────────────────────────────────

let ws, msgId = 0, lastReq = 0;
const waiting = new Map();

// Chrome проекта общий: другая сессия может увести вкладку на свой сайт (11.10.2026 — на hryc.by посреди записи, запросы
// ушли туда и вернули 404). Поэтому перед каждым запросом проверяем адрес, а уведённую вкладку меняем на свою.
let homeUrl = null;   // адрес дерева со своим номером сайта — для своей вкладки
async function connect(fresh = false) {
  let tabs;
  try { tabs = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json(); }
  catch { throw new Stop(`Chrome проекта не запущен (порт ${PORT}): node tools/scripts/browser_cdp.mjs start, войди в MyHeritage`); }
  const isTree = (t) => t.type === 'page' && /myheritage\.[a-z.]+\/(family-trees|pedigree|research|discovery|site-family-tree)/.test(t.url) && /[A-Z0-9]{31}/.test(t.url);
  // 04.11.2026: на myheritage.com те же запросы — 403 (вход Павла и коды форм — на .pl): вкладку .pl берём первой
  let tab = fresh ? null : (tabs.find((t) => isTree(t) && /myheritage\.pl\//.test(t.url)) || tabs.find(isTree));
  if (!tab && homeUrl) {
    tab = await (await fetch(`http://127.0.0.1:${PORT}/json/new?${homeUrl}`, { method: 'PUT' })).json();
    await sleep(10000);
  }
  if (!tab) throw new Stop('нет вкладки MyHeritage: открой своё дерево в Chrome проекта (node tools/scripts/browser_cdp.mjs start https://www.myheritage.pl/family-trees)');
  if (!homeUrl && /[A-Z0-9]{31}/.test(tab.url)) homeUrl = tab.url;
  try { ws?.close(); } catch {}
  ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Stop('нет связи с вкладкой')); });
  ws.onmessage = (m) => {
    const d = JSON.parse(m.data);
    if (d.id && waiting.has(d.id)) { waiting.get(d.id)(d); waiting.delete(d.id); }
  };
}

/** Любая команда CDP в своей вкладке (для загрузки файла: DOM.setFileInputFiles). */
async function cdp(method, params = {}) {
  const id = ++msgId;
  const reply = new Promise((res) => waiting.set(id, res));
  ws.send(JSON.stringify({ id, method, params }));
  const d = await reply;
  if (d.error) throw new Error(`${method}: ${d.error.message}`);
  return d.result;
}

async function rawEval(expression) {
  const id = ++msgId;
  const reply = new Promise((res) => waiting.set(id, res));
  ws.send(JSON.stringify({ id, method: 'Runtime.evaluate', params: { expression, returnByValue: true } }));
  return (await reply).result?.result?.value;
}

/** Выполнить функцию внутри страницы. Всё секретное (защитные поля формы) остаётся там: наружу идёт только ответ. */
async function inPage(fn, ...args) {
  if (!/myheritage\./.test(await rawEval('location.hostname') || '')) {
    log('вкладку MyHeritage увели на другой сайт — открываю свою');
    await connect(true);
    if (!/myheritage\./.test(await rawEval('location.hostname') || '')) throw new Stop('не вернуть вкладку на MyHeritage — открой дерево в Chrome проекта');
  }
  const id = ++msgId;
  const expression = `(async () => { ${LIB}; return (${fn})(...${JSON.stringify(args)}); })()`;
  const reply = new Promise((res) => waiting.set(id, res));
  ws.send(JSON.stringify({ id, method: 'Runtime.evaluate', params: { expression, awaitPromise: true, returnByValue: true } }));
  const d = await reply;
  if (d.result?.exceptionDetails) throw new Error('ошибка в странице: ' + (d.result.exceptionDetails.exception?.description || '').split('\n')[0]);
  return d.result?.result?.value;
}

/** Пауза и счётчик перед каждым запросом к сайту. kind — reads | writes. */
async function pace(kind) {
  const s = counters();
  const cap = kind === 'reads' ? LIMITS.readsPerDay : LIMITS.writesPerDay;
  if (s[kind] >= cap) throw new Stop(`дневной предел ${kind}: ${cap} — продолжим завтра`);
  const wait = lastReq ? Math.max(0, lastReq + rnd(PACE) - Date.now()) : 0;
  await sleep(wait);
  lastReq = Date.now();
  bump(kind);
}

/** Ответ сайта похож на стоп? Тогда дальше нельзя. */
function guard(r, what) {
  const body = typeof r.text === 'string' ? r.text.slice(0, 4000) : '';
  if (r.status === 403 || r.status === 429 || /Incapsula|captcha|Request unsuccessful/i.test(body))
    throw new Stop(`${what}: сайт ответил ${r.status}${/captcha/i.test(body) ? ' (капча)' : ''} — стоп, позови Павла`);
  if (r.status >= 500) throw new Error(`${what}: сайт ответил ${r.status}`);
}

// ─── Код, который выполняется внутри страницы ──────────────────────────────────────────────────

/** Общие помощники — вставляются в начало каждого запроса внутри страницы (там нет импортов). */
const LIB = `
  const unwrap = (txt) => { try { const j = JSON.parse(txt); return typeof j === 'string' ? j : (Object.values(j).find((v) => typeof v === 'string' && v.includes('<')) || txt); } catch { return txt; } };
  const loadForm = async (url, formId) => {
    const r = await fetch(url, { credentials: 'include' });
    const txt = unwrap(await r.text());
    const doc = new DOMParser().parseFromString(txt, 'text/html');
    const form = doc.getElementById(formId) || doc.querySelector('form');
    return { status: r.status, form, doc, txt };
  };
  const valuesOf = (form) => {
    const vals = new Map();
    for (const e of form.elements) {
      if (!e.name || e.disabled) continue;
      if ((e.type === 'radio' || e.type === 'checkbox') && !e.checked) continue;
      vals.set(e.name, e.tagName === 'SELECT' ? (e.selectedOptions[0]?.value ?? '') : e.value);
    }
    return vals;
  };
  const applyPatch = (vals, patch) => {
    // как форма пишет «года нет» (в польском — «Rok»): берём из пустого поля года
    const yearEmpty = [...vals].find(([k, v]) => /^gdp_secondDateYear_/.test(k) && !/^\\d+$/.test(v))?.[1] ?? '';
    const set = (k, v) => { if (!vals.has(k)) throw new Error('в форме нет поля ' + k); vals.set(k, String(v)); };
    for (const k of ['firstName', 'lastName', 'marriedName', 'birthPlace', 'deathPlace', 'isAlive', 'gender']) if (k in patch) set(k, patch[k]);
    for (const [k, v] of Object.entries(patch.extra || {})) set(k, v);   // поля пары: marriagePlace0, relationshipWithSpouse0
    for (const [prefix, d] of Object.entries(patch.dates || {})) {
      set('gdp_dateType_' + prefix, d.type);
      set('gdp_firstOperatorType_' + prefix, d.op1);
      set('gdp_secondOperatorType_' + prefix, d.op2 ?? '');
      set('gdp_firstDateYear_' + prefix, d.y1);
      set('gdp_firstDateMonth_' + prefix, d.m1 || 0);
      set('gdp_firstDateDay_' + prefix, d.d1 || 0);
      set('gdp_secondDateYear_' + prefix, d.y2 || yearEmpty);
      set('gdp_secondDateMonth_' + prefix, d.m2 || 0);
      set('gdp_secondDateDay_' + prefix, d.d2 || 0);
      set('gdp_firstDateText_' + prefix, '');
    }
  };
  const post = async (url, vals) => {
    const body = new URLSearchParams();
    for (const [k, v] of vals) body.append(k, v);
    if (!body.has('csrf_token')) {
      const k = Object.keys(window).find((k) => /^(csrf|mhXsrf)/i.test(k) && typeof window[k] === 'string');
      if (k) body.append('csrf_token', window[k]);
    }
    const r = await fetch(url, { method: 'POST', credentials: 'include', body });
    const text = (await r.text()).slice(0, 600);
    return { status: r.status, text };
  };
  const scrub = (t) => t.replace(/(csrf|token|sess)[^,}]*/gi, '$1:<скрыто>');
`;

const PAGE = {
  siteId: () => {
    const m = (location.pathname + location.search).match(/[A-Z0-9]{31}/);
    return m ? m[0] : null;
  },
  /** GET → {status, text}. */
  get: async (url) => {
    const r = await fetch(url, { credentials: 'include' });
    return { status: r.status, text: await r.text() };
  },
  /** Форма профиля человека → публичные поля (без защитных). */
  readProfile: async (ind, site) => {
    const { status, form, txt } = await loadForm(`/FP/Library/Profile/EditProfile/Popup/editProfile.php?individualID=${ind}&s=${site}`, 'editProfileForm');
    if (status !== 200 || !form) return { status, text: txt.slice(0, 500), fields: null };
    const keep = /^(firstName|lastName|marriedName|gender|isAlive|birthPlace|deathPlace|spouseID\d+|spouseFamilyID\d+|marriagePlace\d+|relationshipWithSpouse\d+|gdp_.*(birthDate|deathDate|marriageDate\d+)$)/;
    const fields = {};
    for (const [k, v] of valuesOf(form)) if (keep.test(k)) fields[k] = v;
    return { status, fields };
  },
  /**
   * Записать поля основы: читаем форму, меняем только указанное, шлём её обратно целиком.
   * patch: {firstName?, lastName? (при рождении), marriedName? (после замужества), birthPlace?, deathPlace?, isAlive?, dates?: {birthDate?, deathDate?: {type, op1, op2, y1, m1, d1, y2, m2, d2}}}
   */
  saveProfile: async (ind, site, patch) => {
    const { status, form, txt } = await loadForm(`/FP/Library/Profile/EditProfile/Popup/editProfile.php?individualID=${ind}&s=${site}`, 'editProfileForm');
    if (status !== 200 || !form) return { status, error: 'нет формы', text: txt.slice(0, 300) };
    const vals = valuesOf(form);
    applyPatch(vals, patch);
    const r = await post('/FP/Library/Profile/EditProfile/Popup/saveProfile.php', vals);
    let result = null;
    try { result = JSON.parse(r.text).result; } catch {}
    return { status: r.status, result, text: result === true ? '' : scrub(r.text) };
  },
  /**
   * Добавить человеку событие (Immigration · Emigration · Residence) формой окна «Добавить факт» [П 25.10.2026]:
   * /FP/genealogy-event-dialog.php → форма genealogyEventDialogForm → /FP/API/Profile/EventPopup/event-popup-save.php.
   * Категория 8 («Проживание»), вид 5 — событие одного человека. ev: {fact, date: {type, op1, …}|null, place, header}.
   */
  addEvent: async (site, ind, ev) => {
    const lang = document.documentElement.lang || 'PL';
    // категория: 8 — «Проживание» (IMMI, EMIG, RESI), 12 — «Работа» (OCCU, «Zatrudnienie», текст — в «Opis» = factHeader) [П 04.11.2026]
    const q = new URLSearchParams({ s: site, individualId: ind, eventGenealogyType: 5, eventCategory: ev.category || 8, eventType: ev.fact, origin: 'profile', lang });
    const { status, form, txt } = await loadForm('/FP/genealogy-event-dialog.php?' + q, 'genealogyEventDialogForm');
    if (status !== 200 || !form) return { status, error: 'нет формы события', text: txt.slice(0, 300) };
    const vals = valuesOf(form);
    if (ev.fact === 'RESI') {
      // жительство — форма адреса (action=residence): город и страна отдельно, дата addressDate; галочку «текущий адрес»
      // (стоит по умолчанию) снимаем — это прошлое жительство, не нынешний адрес
      if (vals.get('action') !== 'residence') return { status, error: 'форма жительства не та: action=' + vals.get('action') };
      vals.delete('isCurrentAddress');
      const parts = String(ev.place || '').split(',').map((x) => x.trim()).filter(Boolean);
      if (parts.length) { vals.set('addressCity', parts[0]); if (parts.length > 1) vals.set('addressCountry', parts.at(-1)); }
      if (ev.date) applyPatch(vals, { dates: { addressDate: ev.date } });
    } else {
      if (vals.get('factType') !== ev.fact) return { status, error: 'форма не того вида: ' + vals.get('factType') };
      if (ev.date) applyPatch(vals, { dates: { factDate: ev.date } });
      if (ev.place) vals.set('factPlace', ev.place);
      if (ev.header) vals.set('factHeader', ev.header);
    }
    const r = await post('/FP/API/Profile/EventPopup/event-popup-save.php', vals);
    let j = null;
    try { j = JSON.parse(r.text); } catch {}
    return { status: r.status, ok: j?.status === 0 || j?.status === '0', text: (j?.status === 0 || j?.status === '0') ? '' : scrub(r.text) };
  },
  /**
   * Связать двух людей, которые уже есть на сайте: родитель → ребёнок [П 25.10.2026]. Так делает пункт «Connect to person»
   * в дереве: окно /FP/API/FamilyTree/nt-attach.php (там childInFamilyIds — нынешние семьи-родители ребёнка), проверка
   * person-attachability.php (ответ: можно ли и в какие семьи родителя), запись attach-detach-process.php action=attach.
   * Если у ребёнка уже есть биологические родители, сайт добавил бы новых вторым набором (приёмными) — поэтому без relink
   * останавливаемся, а с relink сначала отвязываем от старой семьи (action=detach), потом привязываем как биологического.
   */
  linkParent: async (site, child, parent, relink) => {
    const H = { 'content-type': 'application/x-www-form-urlencoded; charset=UTF-8', 'x-requested-with': 'XMLHttpRequest' };
    const base = `s=${site}&siteID=${site}`;
    const page = await (await fetch(`/FP/API/FamilyTree/nt-attach.php?${base}&individualID=${child}&lang=PL`, { credentials: 'include' })).text();
    let fams = {};
    try { fams = JSON.parse((page.match(/childInFamilyIds = (\{[^;]*\});/) || [])[1].replace(/\\"/g, '"')); } catch {}
    const check = async () => (await fetch('/FP/API/FamilyTree/person-attachability.php', { method: 'POST', credentials: 'include', headers: H,
      body: `${base}&familyTreeID=1&personBID=${child}&displayLang=PL&personAID=${parent}&relationship=parent&json=1` })).json();
    const c = await check();
    const res = c.personAttachability?.result;
    if (res === 'ERROR' && /już|already/i.test(c.description || '')) return { status: 200, ok: true, already: true };
    if (res === 'ERROR') return { status: 200, error: 'сайт не даёт: ' + (c.description || '') };
    const post = (body) => fetch('/FP/API/FamilyTree/attach-detach-process.php', { method: 'POST', credentials: 'include', headers: H, body }).then((r) => r.json());
    let list = c.parentFamilies || [], old = fams.biological;
    // 25.10.2026: Иван — сын Анны в семье с Прокопом; семью «Витольд + Анна» сайт не предлагал, пока Иван
    // не отвязан от старой семьи. Поэтому при relink и пустом списке — сначала отвязка, потом снова проверка.
    if (!list.length && old && relink) {
      const d = await post(`action=detach&${base}&dataLanguage=DF&relationship=parent&familyID=${old}&childID=${child}&json=1`);
      if (!d.success) return { status: 200, error: 'отвязка не прошла: ' + JSON.stringify(d).slice(0, 200) };
      old = null;
      await new Promise((z) => setTimeout(z, 6000));
      list = (await check()).parentFamilies || [];
    }
    if (list.length !== 1) return { status: 200, error: 'у родителя семей ' + list.length + ' (' + list.map((f) => f.id + ' ' + f.name).join('; ') + ') — выбери руками' };
    const fam = list[0].id;
    if (old && String(old) !== String(fam)) {
      if (!relink) return { status: 200, error: `у ребёнка на сайте другие родители (семья ${old}) — перевесить к семье ${fam}: upload --only link --relink` };
      const d = await post(`action=detach&${base}&dataLanguage=DF&relationship=parent&familyID=${old}&childID=${child}&json=1`);
      if (!d.success) return { status: 200, error: 'отвязка не прошла: ' + JSON.stringify(d).slice(0, 200) };
      await new Promise((z) => setTimeout(z, 6000));
    }
    const a = await post(`action=attach&${base}&dataLanguage=DF&relationship=parent&childID=${child}&familyID=${fam}&familyType=biological&json=1`);
    if (!a.success) return { status: 200, error: 'привязка не прошла: ' + JSON.stringify(a).slice(0, 200) };
    const v = await check();                                           // проверка: теперь сайт должен сказать «уже родитель»
    return { status: 200, ok: v.personAttachability?.result === 'ERROR' && /już|already/i.test(v.description || ''), text: v.description || '' };
  },
  /**
   * Создать человека рядом с anchor. spec: {file: addChild|addParent|addPartner|addSibling, anchor, gender, patch, otherParent?}
   * otherParent (номер на сайте или null) — только для addChild: к какой семье пристроить ребёнка; null — без второго родителя.
   * Отвечает номером нового человека (из ответа сайта) — по нему вызывающий записывает «карточка → номер».
   */
  addPerson: async (site, spec) => {
    const lang = document.documentElement.lang || 'PL';
    const url = `/FP/Library/Profile/AddIndividual/${spec.file}.php?s=${site}&lang=${lang}&sourceIndividualID=${spec.anchor}&gender=${spec.gender}`;
    const { status, form, txt } = await loadForm(url, 'addIndividualForm');
    if (status !== 200 || !form) return { status, error: 'нет формы создания', text: txt.slice(0, 300) };
    const vals = valuesOf(form);
    if (spec.file === 'addChild') {
      const sel = form.querySelector('[name="parentOfChild"]');
      const options = sel ? [...sel.options].map((o) => o.value) : [];
      let want = '-1';                                                    // без второго родителя
      if (spec.otherParent) {
        const a = await loadForm(`/FP/Library/Profile/EditProfile/Popup/editProfile.php?individualID=${spec.anchor}&s=${site}`, 'editProfileForm');
        const av = a.form ? valuesOf(a.form) : new Map();
        const n = [...av].find(([k, v]) => /^spouseID\d+$/.test(k) && v === String(spec.otherParent));
        const fam = n ? av.get('spouseFamilyID' + n[0].replace('spouseID', '')) : null;
        if (!fam || !options.includes(fam)) return { status: 200, error: 'нет семьи с вторым родителем ' + spec.otherParent + ' (варианты: ' + options.join(',') + ')' };
        want = fam;
      } else if (!options.includes('-1')) {
        return { status: 200, error: 'нет варианта «без второго родителя» (варианты: ' + options.join(',') + ')' };
      }
      vals.set('parentOfChild', want);
    }
    applyPatch(vals, { ...spec.patch, gender: spec.gender });
    const r = await post('/FP/Library/Profile/AddIndividual/addIndividual.php', vals);
    let j = null;
    try { j = JSON.parse(r.text); } catch {}
    const found = [];
    const walk = (o) => { if (o && typeof o === 'object') for (const [k, v] of Object.entries(o)) { if (/^individualid$/i.test(k) && /^\d+$/.test(String(v))) found.push(String(v)); else walk(v); } };
    walk(j);
    return { status: r.status, result: j?.result, ind: found[0] || null, text: j?.result === true && found[0] ? '' : scrub(r.text) };
  },
};

const siteId = async () => {
  const s = await inPage(PAGE.siteId);
  if (!s) throw new Stop('на вкладке MyHeritage нет номера сайта в адресе — открой страницу своего дерева');
  return s;
};

async function read(kind, what, fn, ...args) {
  await pace('reads');
  const r = await inPage(fn, ...args);
  guard(r, what);
  return r;
}

// ─── collect ──────────────────────────────────────────────────────────────────────────────────

const slim = (p, site) => ({
  id: p.id.replace(site + '-', ''),
  firstName: p.firstName, lastName: p.lastName, name: p.name,
  aka: (p.names || []).map((n) => n.n).filter((n) => n && n !== `${p.firstName} ${p.lastName}`),
  gender: p.gender, alive: p.alive === '1',
  birthDate: p.birthDate, birthYear: p.birthYear, deathDate: p.deathDate, deathYear: p.deathYear,
  birthPlace: p.birthPlace?.name || '', deathPlace: p.deathPlace?.name || '',
  relatives: Object.fromEntries(Object.entries(p.relatives || {}).map(([k, v]) => [k, (v.persons || []).map((x) => x.id.replace(site + '-', ''))])),
  photo: !!p.photo?.url,
  smart: { confirmed: +p.smartMatches?.confirmedCount || 0, pending: +p.smartMatches?.pendingCount || 0 },
  records: { confirmed: +p.recordMatches?.confirmedCount || 0, pending: +p.recordMatches?.pendingCount || 0 },
});

async function collect() {
  await connect();
  const site = await siteId();
  const persons = {};
  let total = null;
  for (let page = 1; page <= 30; page++) {
    const r = await read('reads', `список людей, стр. ${page}`, PAGE.get, `/pedigree-tree-${site}/${settings().MYHERITAGE_URL_NAME}?action=list&treeId=${TREE_ID}&relatives=1&page=${page}&perPage=100`);
    let j;
    try { j = JSON.parse(r.text); } catch { throw new Error(`стр. ${page}: ответ не JSON (${r.text.slice(0, 120)})`); }
    const list = j.data?.persons || [];
    total = j.data?.treeSize ?? total;
    const before = Object.keys(persons).length;
    for (const p of list) persons[p.id.replace(site + '-', '')] = slim(p, site);
    log(`стр. ${page}: ${list.length}, всего ${Object.keys(persons).length}`);
    if (list.length < 100 || Object.keys(persons).length === before) break;   // короткая страница или повторы — конец
  }
  writeJson(F.snapshot, { collected: new Date().toISOString(), site, treeId: TREE_ID, treeSize: total, count: Object.keys(persons).length, persons });
  log(`снимок: ${Object.keys(persons).length} человек (treeSize сайта: ${total}) → ${path.relative(ROOT, F.snapshot)}`);
}

// ─── upload ───────────────────────────────────────────────────────────────────────────────────

/** Что оставил в списке Павел: [x] — грузим, [ ] или нет строки — нет. */
function approvedIds() {
  const md = fs.readFileSync(F.planMd, 'utf8');
  return new Set([...md.matchAll(/^- \[x\] `([^`]+)`/gim)].map((m) => m[1]));
}

async function runField(item, site) {
  const before = await read('reads', `${item.ind}: форма`, PAGE.readProfile, item.ind, site);
  if (!before.fields) throw new Error(`форма ${item.ind}: ${before.status} ${before.text || ''}`);
  await pace('writes');
  const w = await inPage(PAGE.saveProfile, item.ind, site, item.patch);
  guard(w, `${item.ind}: запись`);
  if (w.error || w.result !== true) throw new Error(`запись ${item.ind}: ${w.error || ''} ${w.status} ${w.text}`);
  const after = await read('reads', `${item.ind}: проверка`, PAGE.readProfile, item.ind, site);
  const bad = [];
  const want = item.expect || {};
  for (const [k, v] of Object.entries(want)) if (String(after.fields?.[k] ?? '') !== String(v)) bad.push(`${k}: ждали «${v}», на сайте «${after.fields?.[k]}»`);
  if (bad.length) throw new Error(`после записи ${item.ind} на сайте не то: ${bad.join('; ')}`);
}

/** Прошлый запуск мог оборваться между «отправили» и «записали номер» — тогда человек на сайте уже есть, а у нас его нет. */
function hasDanglingPending(work) {
  if (!fs.existsSync(F.journal)) return false;
  const rows = fs.readFileSync(F.journal, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l)).filter((r) => r.work === work);
  const last = rows.at(-1);
  return !!last && last.status === 'pending';
}

const ADD_FILE = { father: 'addParent', mother: 'addParent', spouse: 'addPartner', child: 'addChild' };

async function runPerson(item, site) {
  const ids = readJson(F.idMap, {});
  if (ids[item.cr_id]) return;                                        // уже создан (номер записан)
  if (hasDanglingPending(item.work)) throw new Error(`${item.cr_id}: прошлый запуск оборвался посреди создания — сделай collect, найди человека на сайте и впиши номер в ${path.relative(ROOT, F.idMap)} сам`);
  const anchor = item.anchor || ids[item.anchor_cr];
  if (!anchor) { log('ждёт', item.cr_id, '— «к кому» ещё не создан'); throw new Wait(); }
  let other = item.other || (item.other_cr ? ids[item.other_cr] : null) || null;
  if (item.other_cr && !other) {
    // второго родителя создадим в этом же списке — ждём его; его строка не отмечена (⚠ имя из одного слова и т. п.) —
    // ждать нечего: ребёнок встаёт с одним родителем (решение Павла 04.11.2026), второго привяжет потом работа link
    const otherWork = PLAN_ROWS.find((w) => w.action === 'person' && w.cr_id === item.other_cr);
    if (otherWork && APPROVED.has(otherWork.work)) { log('ждёт', item.cr_id, '— второй родитель ещё не создан'); throw new Wait(); }
    log(' ', item.cr_id, '— второй родитель не в работе: создаю с одним');
    other = null;
  }
  const gender = item.sex === 'F' ? 'F' : 'M';
  const spec = { file: ADD_FILE[item.rel], anchor, gender, patch: item.patch, otherParent: item.rel === 'child' ? other : null };
  await pace('reads');                                                // форма создания (внутри ещё до двух чтений — в счётчик не идут, они редкие)
  journal({ work: item.work, status: 'pending', text: item.text });
  await pace('writes');
  const w = await inPage(PAGE.addPerson, site, spec);
  guard(w, `${item.cr_id}: создание`);
  if (w.error || w.result !== true || !w.ind) { journal({ work: item.work, status: 'error', error: w.error || w.text }); throw new Error(`создание ${item.cr_id}: ${w.error || ''} ${w.status} ${w.text || ''}`); }
  ids[item.cr_id] = w.ind;
  writeJson(F.idMap, ids);                                           // сначала номер, потом проверка: потеряем номер — задвоим человека
  const after = await read('reads', `${w.ind}: проверка`, PAGE.readProfile, w.ind, site);
  const f = after.fields || {};
  const bad = [];
  if (String(f.firstName ?? '') !== String(item.patch.firstName ?? '')) bad.push(`имя «${f.firstName}»`);
  if (String(f.lastName ?? '') !== String(item.patch.lastName ?? '')) bad.push(`фамилия «${f.lastName}»`);
  if ('marriedName' in item.patch && String(f.marriedName ?? '') !== String(item.patch.marriedName)) bad.push(`фамилия после замужества «${f.marriedName}»`);
  if (bad.length) throw new Error(`создан ${w.ind} (${item.cr_id}), но на сайте не то: ${bad.join('; ')}`);
  log(`  номер на сайте: ${w.ind} (записан в ${path.relative(ROOT, F.idMap)})`);
}

async function runEvent(item, site) {
  const ids = readJson(F.idMap, {});
  const ind = item.ind || ids[item.cr_id];
  if (!ind) { log('ждёт', item.cr_id, '— человек ещё не создан'); throw new Wait(); }
  await pace('reads');                                                // форма события
  await pace('writes');
  const w = await inPage(PAGE.addEvent, site, ind, { fact: item.fact, category: item.fact === 'OCCU' ? 12 : 8, date: item.date, place: item.place, header: item.header });
  guard(w, `${ind}: событие`);
  if (w.error || !w.ok) throw new Error(`событие ${ind} (${item.cr_id}): ${w.error || ''} ${w.status} ${w.text || ''}`);
}

let RELINK = false;
let APPROVED = new Set(), PLAN_ROWS = [];                            // отмеченное в списке и весь список — для runPerson                                                   // upload --relink: можно перевешивать ребёнка от других родителей

async function runLink(item, site) {
  const [child, parent] = item.rel === 'child' ? [item.other, item.ind] : ['father', 'mother'].includes(item.rel) ? [item.ind, item.other] : [null, null];
  if (!child) throw new Error(`связь «${item.rel}» пока не умеем — только родитель и ребёнок`);
  await pace('reads');
  await pace('writes');
  const w = await inPage(PAGE.linkParent, site, child, parent, RELINK);
  guard(w, `${child}: связь`);
  if (w.error || !w.ok) throw new Error(`связь ${child} ← ${parent}: ${w.error || ''} ${w.text || ''}`);
  if (w.already) log('  уже связаны на сайте');
}

class Wait extends Error {}                                          // не ошибка: работа ждёт другую, останется на следующий запуск

/**
 * Брак и развод пары [П 04.11.2026]: в форме профиля (той же, что для имени и годов) у каждого супруга n есть поля
 * spouseID<n>, gdp_*_marriageDate<n>, marriagePlace<n> и relationshipWithSpouse<n> (Married · Divorced · …). Пишем туда:
 * дата и место брака; развод — статус Divorced (даты развода в форме нет). Сверка — тем же чтением формы.
 */
async function runFamily(item, site) {
  const ids = readJson(F.idMap, {});
  const a = item.a || ids[item.a_cr], b = item.b || ids[item.b_cr];
  if (!a || !b) { log('ждёт', item.work, '— супруг ещё не создан'); throw new Wait(); }
  const before = await read('reads', `${a}: форма`, PAGE.readProfile, a, site);
  const f = before.fields;
  if (!f) throw new Error(`форма ${a}: ${before.status} ${before.text || ''}`);
  const n = Object.keys(f).find((k) => /^spouseID\d+$/.test(k) && f[k] === String(b))?.replace('spouseID', '');
  if (n === undefined) throw new Error(`у ${a} на сайте нет супруга ${b} — сначала связь`);
  const patch = { extra: {}, dates: {} }, expect = {};
  if (item.kind === 'DIV') { patch.extra['relationshipWithSpouse' + n] = 'Divorced'; expect['relationshipWithSpouse' + n] = 'Divorced'; }
  else {
    if (item.date) { patch.dates['marriageDate' + n] = item.date; expect['gdp_firstDateYear_marriageDate' + n] = item.date.y1; }
    if (item.place) { patch.extra['marriagePlace' + n] = item.place; expect['marriagePlace' + n] = item.place; }
  }
  const same = Object.entries(expect).every(([k, v]) => String(f[k] ?? '') === String(v));
  if (same) { log('  на сайте уже так'); return; }
  const was = item.kind === 'DIV' ? f['relationshipWithSpouse' + n] : `${f['gdp_firstDateYear_marriageDate' + n]} ${f['marriagePlace' + n] || ''}`.trim();
  if (was && !/^(Rok|Married)?$/.test(was)) log(`  на сайте было: ${was} — меняем на карточку`);
  await pace('writes');
  const w = await inPage(PAGE.saveProfile, a, site, patch);
  guard(w, `${a}: брак`);
  if (w.error || w.result !== true) throw new Error(`запись брака ${a}: ${w.error || ''} ${w.status} ${w.text}`);
  const after = await read('reads', `${a}: проверка`, PAGE.readProfile, a, site);
  const bad = Object.entries(expect).filter(([k, v]) => String(after.fields?.[k] ?? '') !== String(v)).map(([k, v]) => `${k}: ждали «${v}», на сайте «${after.fields?.[k]}»`);
  if (bad.length) throw new Error(`после записи брака ${a} на сайте не то: ${bad.join('; ')}`);
}

/**
 * Главное фото [П 04.11.2026] — так, как это делает человек: профиль → круг фото («Dodaj zdjęcie»,
 * .editable_profile_photo.size_xxxlarge, у кого фото нет — класс mode_add) → окно с input#ppuFile → файл → OK.
 * Файл подставляет сам Chrome (DOM.setFileInputFiles) — в страницу и наружу ничего не уходит, кроме самого снимка.
 * Проверка: у круга пропал mode_add. Фото на сайте уже есть — не трогаем (заменять главное фото — решение Павла).
 */
async function runPhoto(item, site) {
  const file = path.join(ROOT, item.file);
  if (!fs.existsSync(file)) throw new Error(`нет файла ${item.file} — пересобери сайт (rodo site export)`);
  const back = await rawEval('location.href');
  const host = new URL(back).origin;
  await pace('reads');
  await cdp('Page.navigate', { url: `${host}/profile-${site}-${item.ind}/x` });
  const waitFor = async (js, ms = 30000) => { for (let t = 0; t < ms; t += 1000) { if (await rawEval(js)) return true; await sleep(1000); } return false; };
  try {
    if (!(await waitFor(`!!document.querySelector('.editable_profile_photo.size_xxxlarge')`))) throw new Error(`${item.ind}: на профиле нет круга фото`);
    if (!(await rawEval(`document.querySelector('.editable_profile_photo.size_xxxlarge').classList.contains('mode_add')`))) { log('  на сайте фото уже есть — не трогаем'); return; }
    await rawEval(`document.querySelector('.editable_profile_photo.size_xxxlarge').click()`);
    if (!(await waitFor(`!!document.querySelector('#ppuFile')`))) throw new Error(`${item.ind}: окно загрузки не открылось`);
    const { root } = await cdp('DOM.getDocument', { depth: 0 });
    const { nodeId } = await cdp('DOM.querySelector', { nodeId: root.nodeId, selector: '#ppuFile' });
    await pace('writes');
    await cdp('DOM.setFileInputFiles', { nodeId, files: [file] });
    await rawEval(`document.querySelector('#ppuFile').dispatchEvent(new Event('change', { bubbles: true }))`);
    await sleep(4000);
    const ok = `[...document.querySelectorAll('button,a,input[type=button]')].filter((e) => (e.innerText || e.value || '').trim() === 'OK' && e.offsetParent).pop()`;
    if (!(await waitFor(`!!(${ok})`, 20000))) throw new Error(`${item.ind}: нет кнопки OK`);
    await rawEval(`(${ok}).click()`);
    const done = await waitFor(`(() => { const e = document.querySelector('.editable_profile_photo.size_xxxlarge'); return e && !e.classList.contains('mode_add'); })()`, 60000);
    const body = await rawEval('document.body.innerText.slice(0, 3000)');
    guard({ status: 200, text: body }, `${item.ind}: фото`);
    if (!done) throw new Error(`${item.ind}: после OK фото на профиле не появилось`);
  } finally {
    await cdp('Page.navigate', { url: back });
    await sleep(8000);
  }
}

const RUNNERS = { field: runField, person: runPerson, event: runEvent, link: runLink, family: runFamily, occupation: runEvent, photo: runPhoto };

async function upload(args) {
  const go = args.includes('--go');
  RELINK = args.includes('--relink');
  const limit = Number((args[args.indexOf('--limit') + 1]) || Infinity) || Infinity;
  const plan = readJson(F.plan, null);
  if (!plan) throw new Error('нет plan.json — сначала: tools/py tools/scripts/myheritage_plan.py plan');
  if (!fs.existsSync(F.planMd)) throw new Error('нет plan_to_site.md');
  const ok = approvedIds(), done = doneIds();
  APPROVED = ok; PLAN_ROWS = plan.to_site;
  const only = args.includes('--only') ? args[args.indexOf('--only') + 1] : null;
  const one = args.includes('--work') ? args[args.indexOf('--work') + 1] : null;
  const queue = plan.to_site.filter((w) => ok.has(w.work) && !done.has(w.work) && (!only || w.action === only) && (!one || w.work === one));
  const skipped = plan.to_site.filter((w) => !ok.has(w.work)).length;
  log(`работ в списке ${plan.to_site.length}: вычеркнуто ${skipped}, уже сделано ${plan.to_site.filter((w) => done.has(w.work)).length}, к загрузке ${queue.length}`);
  const unknown = queue.filter((w) => !RUNNERS[w.action]);
  if (unknown.length) log(`не умеем автоматически (${unknown.length}): ` + [...new Set(unknown.map((w) => w.action))].join(', ') + ' — пропущены, сделай руками');
  const todo = queue.filter((w) => RUNNERS[w.action]).slice(0, limit);
  if (!go) {
    for (const w of todo) log('[проба]', w.work, '—', w.text);
    log(`проба: ${todo.length} работ. Выполнить: добавь --go`);
    return;
  }
  await connect();
  const site = await siteId();
  if (plan.site && plan.site !== site) throw new Stop(`список составлен для сайта ${plan.site}, а открыт ${site}`);
  let n = 0, pausedAt = 0;
  for (const w of todo) {
    if (n && n % LIMITS.batch === 0 && pausedAt !== n) {   // одна пауза на пачку — ошибка не держит n и не зацикливает паузы
      pausedAt = n; const ms = rnd(BATCH_PAUSE); log(`пачка из ${LIMITS.batch} готова — пауза ${Math.round(ms / 60000)} мин`); await sleep(ms); }
    try {
      await RUNNERS[w.action](w, site);
      journal({ work: w.work, status: 'ok', text: w.text });
      log('готово', w.work, '—', w.text);
    } catch (e) {
      if (e instanceof Stop) { journal({ work: w.work, status: 'stop', error: e.message }); throw e; }
      if (e instanceof Wait) { waited++; continue; }
      journal({ work: w.work, status: 'error', error: e.message });
      log('ОШИБКА', w.work, e.message);
      if (++errors >= 3) throw new Error('три ошибки подряд — стоп, разберись');
      continue;
    }
    errors = 0; n++;
  }
  if (waited) log(`ждут своей очереди: ${waited} — запусти upload ещё раз (после создания тех, от кого они зависят)`);
  log(`сделано ${n} из ${todo.length}. Теперь: node tools/scripts/myheritage_web.mjs collect — сверка`);
}
let errors = 0, waited = 0;

/** Проба на одном человеке: то же, что upload делает с одной работой, но правку задаёшь сам. */
async function probe(ind, json, args) {
  const patch = JSON.parse(json);
  const expect = Object.fromEntries([...['firstName', 'lastName', 'marriedName', 'isAlive', 'birthPlace', 'deathPlace'].filter((k) => k in patch).map((k) => [k, patch[k]]),
    ...Object.entries(patch.dates || {}).map(([pre, d]) => [`gdp_firstDateYear_${pre}`, d.y1])]);
  if (!args.includes('--go')) { log('[проба] записали бы', ind, JSON.stringify(patch), '— добавь --go'); return; }
  await connect();
  const site = await siteId();
  await runField({ ind, patch, expect }, site);
  journal({ work: `probe:${ind}`, status: 'probe', text: json });
  log('готово, на сайте как просили:', JSON.stringify(expect));
}

// ─── status, peek ─────────────────────────────────────────────────────────────────────────────

function status() {
  const s = counters(), snap = readJson(F.snapshot, null), plan = readJson(F.plan, null), done = doneIds();
  console.log(`сегодня: чтений ${s.reads}/${LIMITS.readsPerDay}, записей ${s.writes}/${LIMITS.writesPerDay}`);
  console.log(snap ? `снимок: ${snap.collected}, людей ${snap.count}` : 'снимка нет — collect');
  console.log(plan ? `список работ: ${plan.to_site.length}, сделано по журналу ${plan.to_site.filter((w) => done.has(w.work)).length}` : 'списка работ нет — myheritage_plan.py plan');
  const last = new Map();                              // по каждой работе — её последняя запись; тревожные — что осталось
  if (fs.existsSync(F.journal)) for (const l of fs.readFileSync(F.journal, 'utf8').split('\n').filter(Boolean)) { const r = JSON.parse(l); last.set(r.work, r); }
  const errs = [...last.values()].filter((r) => ['error', 'stop', 'pending'].includes(r.status)).slice(-5);
  for (const e of errs) console.log(`  ${e.status}: ${e.work} ${e.error}`);
}

async function peek(url) {
  await connect();
  const site = await siteId();
  const r = await read('reads', 'peek', PAGE.get, url + (url.includes('?') ? '&' : '?') + 's=' + site);
  let txt = r.text;
  try { const j = JSON.parse(txt); txt = typeof j === 'string' ? j : (Object.values(j).find((v) => typeof v === 'string' && v.includes('<')) || txt); } catch {}
  const fields = [...txt.matchAll(/<(?:input|select|textarea)\b[^>]*\bname="([^"]+)"[^>]*?(?:\bvalue="([^"]*)")?[^>]*>/g)]
    .filter(([, n]) => !/csrf|token|^s$|siteid|password|email|sess/i.test(n)).map(([, n, v]) => `${n}=${v ?? ''}`);
  console.log(r.status, txt.length, 'знаков;', fields.length, 'полей');
  console.log(fields.slice(0, 80).join('\n'));
}

// ─── main ─────────────────────────────────────────────────────────────────────────────────────

const [cmd, ...rest] = process.argv.slice(2);
try {
  if (cmd === 'collect') await collect();
  else if (cmd === 'upload') await upload(rest);
  else if (cmd === 'status') status();
  else if (cmd === 'peek' && rest[0]) await peek(rest[0]);
  else if (cmd === 'probe' && rest[1]) await probe(rest[0], rest[1], rest);
  else { console.error('команды: collect | upload [--go] [--limit N] | status | peek <адрес> | probe <номер> '<json>' [--go]   (подробно — шапка файла)'); process.exit(2); }
  ws?.close();
} catch (e) {
  ws?.close();
  if (e instanceof Stop) { console.error('СТОП:', e.message); process.exit(3); }
  console.error('ОШИБКА:', e.message); process.exit(1);
}
