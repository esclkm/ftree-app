// Расчёты для графиков предков и семьи — только по общему списку людей (data/index.json): родители, пол, годы жизни.
// Без React: их проверяют тесты (test/ancestry.test.ts).
import type {IndexPerson, Lookup} from '../useIndex'

export const THIS_YEAR = new Date().getFullYear()

export interface Years {
  born?: number; died?: number
  /** жив: годы жизни без черты («1986») */
  alive: boolean
  /** год рождения или смерти примерный («~1850», «<1900», «>1950») */
  approx: boolean
}

/** «~1850–>1920» → {born: 1850, died: 1920}; «1986» — родился, жив; «?–?» и пусто — ничего */
export function yearsOf(life: string | undefined): Years {
  const s = (life ?? '').trim()
  const [a = '', b] = s.split('–')
  const num = (x: string | undefined) => { const m = x?.match(/\d{3,4}/); return m ? Number(m[0]) : undefined }
  const born = num(a), died = num(b)
  return {born, died, alive: b === undefined && born !== undefined, approx: /[~<>]/.test(s)}
}

/** Предки по номерам Аненталя: слот 1 — сам человек, у слота k отец — 2k, мать — 2k+1. Поколение g — слоты 2^g…2^(g+1)−1.
 *  Отца и мать различаем по полу; двое родителей одного пола или без пола — по порядку в списке. */
export function ancestorSlots(ix: Lookup, id: string, gens: number): (IndexPerson | undefined)[] {
  const slots: (IndexPerson | undefined)[] = new Array(2 ** (gens + 1)).fill(undefined)
  slots[1] = ix.people.get(id)
  for (let k = 1; k < 2 ** gens; k++) {
    const p = slots[k]
    if (!p) continue
    const ps = p.parents.flatMap(x => { const q = ix.people.get(x); return q ? [q] : [] })
    const f = ps.find(q => q.sex === 'M'), m = ps.find(q => q.sex === 'F')
    const rest = ps.filter(q => q !== f && q !== m)
    slots[2 * k] = f ?? rest.shift()
    slots[2 * k + 1] = m ?? rest.shift()
  }
  return slots
}

/** Поколение слота: 1 → 0, 2–3 → 1, 4–7 → 2 … */
export const genOf = (slot: number): number => Math.floor(Math.log2(slot))

export interface LineDepth {
  /** с кого начинается линия (прадед или прабабушка) и его слот */
  root: IndexPerson; slot: number
  /** самый ранний по году рождения предок линии (может быть и сам root) и год */
  earliest?: IndexPerson; year?: number
  /** на сколько поколений над центром уходит линия */
  generations: number
  /** людей в линии, считая root */
  people: number
}

/** Насколько далеко в прошлое уходит каждая линия поколения `level` (3 — прадеды и прабабушки): все их предки,
 *  самый ранний год рождения и самое глубокое поколение. Человек, попавший в две линии (браки родни), считается в обеих. */
export function lineDepths(ix: Lookup, id: string, level = 3): (LineDepth | undefined)[] {
  const slots = ancestorSlots(ix, id, level)
  const out: (LineDepth | undefined)[] = []
  for (let s = 2 ** level; s < 2 ** (level + 1); s++) {
    const root = slots[s]
    if (!root) { out.push(undefined); continue }
    let earliest: IndexPerson | undefined, year: number | undefined, generations = level, people = 0
    const seen = new Set<string>()
    let wave: IndexPerson[] = [root], g = level
    while (wave.length) {
      const next: IndexPerson[] = []
      for (const p of wave) {
        if (seen.has(p.id)) continue
        seen.add(p.id); people++
        generations = Math.max(generations, g)
        const b = yearsOf(p.life).born
        if (b !== undefined && (year === undefined || b < year)) { year = b; earliest = p }
        for (const x of p.parents) { const q = ix.people.get(x); if (q && !seen.has(q.id)) next.push(q) }
      }
      wave = next; g++
    }
    out.push({root, slot: s, earliest, year, generations, people})
  }
  return out
}

/** Сколько предков известно в поколениях 1…gens (без самого человека) и сколько мест всего */
export function fanCount(slots: (IndexPerson | undefined)[], gens: number): {known: number; total: number} {
  let known = 0
  for (let k = 2; k < 2 ** (gens + 1); k++) if (slots[k]) known++
  return {known, total: 2 ** (gens + 1) - 2}
}
