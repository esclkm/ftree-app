// Шкала лет (pages/Lifelines.tsx): дата — место на шкале.
import type {GDate} from '../data/schema.gen'

/** Дата → год с долей: 22.03.1929 → 1929.2 — чтобы точки одного года стояли по порядку. «После 1949» (sort …99) —
 *  день ограничен 28-м, в следующий год не уходит. */
export function yearOf(d: GDate): number {
  const y = Math.floor(d.sort / 10000), m = Math.floor(d.sort / 100) % 100, day = Math.min(d.sort % 100, 28)
  return y + (m ? (m - 1) / 12 : 0) + (day ? (day - 1) / 365 : 0)
}
