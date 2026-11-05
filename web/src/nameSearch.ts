// Поиск человека по имени: слова запроса — в любом порядке и в любой записи имени.
// «Ясенев Иван», «Иван Ясенев», «jasieniew iw», «Мария 1937» — одно и то же. Ё = Е, регистр и надстрочные знаки
// (ł, ż, á) не важны: «Krakow» находит «Kraków».

/** Строка для сравнения: нижний регистр, без надстрочных знаков, ё → е. */
export const fold = (s: string): string =>
  s.toLowerCase().replace(/ё/g, 'е').replace(/ł/g, 'l').normalize('NFD').replace(/[̀-ͯ]/g, '')

/** Слова запроса (пусто — запроса нет). */
export const queryWords = (q: string): string[] => fold(q).split(/[\s,]+/).filter(Boolean)

/** Подходит ли человек: каждое слово запроса есть внутри хоть одной из его строк (записи имени, годы). */
export function matchesName(texts: readonly string[], words: readonly string[]): boolean {
  if (!words.length) return false
  const key = fold(texts.join(' '))
  return words.every(w => key.includes(w))
}

/** Порядок в выдаче: 0 — слово запроса стоит в начале какой-то записи имени, 1 — с него начинается слово, 2 — внутри. */
export function nameRank(texts: readonly string[], words: readonly string[]): number {
  const ns = texts.map(fold)
  if (ns.some(n => words.every(w => n.split(/[\s(,-]+/).some(x => x.startsWith(w))) && words.some(w => n.startsWith(w)))) return 0
  if (ns.some(n => words.every(w => n.split(/[\s(,-]+/).some(x => x.startsWith(w))))) return 1
  return 2
}
