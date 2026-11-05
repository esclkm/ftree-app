/**
 * Настройки для скриптов на JS — из того же загрузчика, что у Python (paths.py), чтобы порядок был один:
 * ключ команды > переменная окружения > ~/.config/ftree/env > ftree.toml > значение по умолчанию.
 * Python зовётся один раз и только когда значение понадобилось (`settings()`); переменная окружения с тем же именем
 * (CDP_PORT …) берётся сразу, без Python.
 */
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const PY = fileURLToPath(new URL('../py', import.meta.url));
const PATHS = fileURLToPath(new URL('./paths.py', import.meta.url));
let cache;

/** Все пути и настройки дерева: ROOT, CACHE, CDP_PORT, MYHERITAGE_SITE, MH_OTHERS, FINDINGS … (paths.as_dict). */
export function settings() {
  if (!cache) cache = JSON.parse(execFileSync(PY, [PATHS], { encoding: 'utf8' }));
  return cache;
}

/** Одно значение; переменная окружения с тем же именем — без запуска Python. */
export function setting(name) {
  return process.env[name] || settings()[name];
}

/** Порт своего Chrome проекта (по умолчанию 9333). */
export const cdpPort = () => Number(setting('CDP_PORT'));
