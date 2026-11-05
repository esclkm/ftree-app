/**
 * Своя вкладка у каждой сессии в общем Chrome проекта (порт 9333).
 *
 * Зачем. Несколько сессий Claude ходят в один Chrome (вход Павла один на всех). Раньше каждая брала «первую
 * вкладку» — и сессии уводили страницу друг у друга (31.10.2026: поиск по FamilySearch и сверка MyHeritage).
 * Теперь у сессии своя вкладка: номер сессии (CLAUDE_CODE_SESSION_ID; руками — CDP_OWNER) → номер вкладки,
 * реестр — $ARCHIVES_LOCAL/browser-tabs.json. Закрылась вкладка — при следующей команде откроется новая.
 * Без номера сессии (Павел в терминале) — первая вкладка, которую не заняла ни одна сессия.
 *
 *   import { ownTab, tabOwners, releaseTab } from './cdp_tab.mjs';
 *   const t = await ownTab(BASE);   // {id, url, webSocketDebuggerUrl}
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { setting } from './settings.mjs';

const ARCHIVES = setting('ARCHIVES_LOCAL').replace(/^~/, os.homedir());  // сырьё архивов (paths.py)
const REG = path.join(ARCHIVES, 'browser-tabs.json');
export const OWNER = process.env.CDP_OWNER || process.env.CLAUDE_CODE_SESSION_ID || '';
const LABEL = process.env.CDP_LABEL || '';

const json = async (base, p, opt) => (await fetch(base + p, opt)).json();
const pages = async (base) => (await json(base, '/json')).filter((t) => t.type === 'page' && t.webSocketDebuggerUrl && !t.url.startsWith('devtools://'));

function read() { try { return JSON.parse(fs.readFileSync(REG, 'utf8')); } catch { return {}; } }
function write(reg) { fs.mkdirSync(ARCHIVES, { recursive: true }); fs.writeFileSync(REG + '.tmp', JSON.stringify(reg, null, 1)); fs.renameSync(REG + '.tmp', REG); }

// реестр без закрытых вкладок
async function live(base) {
  const open = await pages(base);
  const ids = new Set(open.map((t) => t.id));
  const reg = read();
  for (const k of Object.keys(reg)) if (!ids.has(reg[k].tab)) delete reg[k];
  return { open, reg };
}

export async function ownTab(base) {
  const { open, reg } = await live(base);
  if (!OWNER) {
    const taken = new Set(Object.values(reg).map((r) => r.tab));
    const free = open.find((t) => !taken.has(t.id));
    if (free) return free;
    return json(base, '/json/new?about:blank', { method: 'PUT' });
  }
  const mine = reg[OWNER] && open.find((t) => t.id === reg[OWNER].tab);
  const t = mine || (await json(base, '/json/new?about:blank', { method: 'PUT' }));
  reg[OWNER] = { tab: t.id, who: LABEL || reg[OWNER]?.who || OWNER.slice(0, 8), at: new Date().toISOString().slice(0, 16) };
  write(reg);
  return t;
}

// {номер вкладки: «чья»} — для status
export async function tabOwners(base) {
  const { reg } = await live(base);
  write(reg);
  return Object.fromEntries(Object.entries(reg).map(([k, r]) => [r.tab, `${r.who}${k === OWNER ? ' (эта сессия)' : ''}, с ${r.at}`]));
}

// закрыть свою вкладку в конце работы
export async function releaseTab(base) {
  const reg = read();
  if (!OWNER || !reg[OWNER]) return false;
  await fetch(`${base}/json/close/${reg[OWNER].tab}`).catch(() => {});
  delete reg[OWNER]; write(reg);
  return true;
}
