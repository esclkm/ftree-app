// Тема: как в системе, светлая или тёмная. Выбор хранится в этом браузере; «как в системе» — без data-theme на <html>,
// тогда цвета берёт @media (prefers-color-scheme) в styles/_tokens.scss.
import {useState} from 'react'

export type Theme = 'auto' | 'light' | 'dark'
export const THEMES: Theme[] = ['auto', 'light', 'dark']
const KEY = 'theme'

function stored(): Theme {
  try { const v = localStorage.getItem(KEY); return v === 'light' || v === 'dark' ? v : 'auto' } catch { return 'auto' }
}
const TREE_KEY = 'tree-light'  // «дерево всегда светлое» — не всем нравится тёмное дерево
const treeLight = (): boolean => { try { return localStorage.getItem(TREE_KEY) === '1' } catch { return false } }

export function applyTheme(v: Theme = stored(), tree = treeLight()): void {
  const d = document.documentElement.dataset
  if (v === 'auto') delete d.theme; else d.theme = v
  if (tree) d.tree = 'light'; else delete d.tree
}
export function useTheme(): [Theme, (v: Theme) => void] {
  const [value, setValue] = useState(stored)
  const save = (v: Theme) => {
    try { if (v === 'auto') localStorage.removeItem(KEY); else localStorage.setItem(KEY, v) } catch { /* закрытое хранилище — только на эту страницу */ }
    applyTheme(v)
    setValue(v)
  }
  return [value, save]
}

export function useTreeLight(): [boolean, (v: boolean) => void] {
  const [value, setValue] = useState(treeLight)
  const save = (v: boolean) => {
    try { if (v) localStorage.setItem(TREE_KEY, '1'); else localStorage.removeItem(TREE_KEY) } catch { /* только на эту страницу */ }
    applyTheme(stored(), v)
    setValue(v)
  }
  return [value, save]
}
