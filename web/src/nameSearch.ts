// Поиск человека по имени: слова запроса — в любом порядке, на любом языке и в любой записи имени.
// «Ясенев Иван», «Иван Ясенев», «jasieniew iw», «Мария 1937» — одно и то же. Ё = Е, регистр и надстрочные знаки
// (ł, ż, á) не важны: «Krakow» находит «Kraków».
// Если прямого совпадения нет — сравниваем «скелет» слова: латиницей, без гласных, с одинаковой записью похожих
// звуков. Так «Hleb» находит «Глеб», «Barysava» — «Борисова», «Karaško» — «Карашко», «Prakop» — «Прокоп».
// И раскладка клавиатуры: «Hfrbnby» (набрано по-русски в английской раскладке) находит «Ракитин».

/** Строка для сравнения: нижний регистр, без надстрочных знаков, ё → е. */
export const fold = (s: string): string =>
  s.toLowerCase().replace(/ё/g, 'е').replace(/ł/g, 'l').normalize('NFD').replace(/[̀-ͯ]/g, '')

/** Слова запроса (пусто — запроса нет). */
export const queryWords = (q: string): string[] => fold(q).split(/[\s,]+/).filter(Boolean)

const CYR: Record<string, string> = {
  а: 'a', б: 'b', в: 'v', г: 'g', д: 'd', е: 'e', ж: 'zh', з: 'z', и: 'i', й: 'i', к: 'k', л: 'l', м: 'm', н: 'n',
  о: 'o', п: 'p', р: 'r', с: 's', т: 't', у: 'u', ф: 'f', х: 'kh', ц: 'ts', ч: 'ch', ш: 'sh', щ: 'sh', ъ: '', ы: 'y',
  ь: '', э: 'e', ю: 'yu', я: 'ya', і: 'i', ў: 'u', ї: 'i', є: 'e', ґ: 'g',
}

/** Скелет слова: латиницей, согласные, похожие звуки — одной буквой. «Карашко», «Karashko», «Karaszko», «Karaško» → «krsk». */
export function skeleton(word: string): string {
  const lat = [...word.toLowerCase().replace(/š/g, 'sh').replace(/č/g, 'ch').replace(/[žż]/g, 'zh')]
    .map(c => CYR[c] ?? c).join('')
  return fold(lat)
    .replace(/kh/g, 'h').replace(/sz/g, 's').replace(/cz/g, 'c').replace(/sh/g, 's').replace(/ch/g, 'c').replace(/zh/g, 'z')
    .replace(/t[sz]/g, 'c').replace(/w/g, 'v').replace(/g/g, 'h').replace(/q/g, 'k').replace(/x/g, 'ks')
    .replace(/[^a-z0-9]/g, '').replace(/[aeiouyj]/g, '').replace(/(.)\1+/g, '$1')
}

const EN = "qwertyuiop[]asdfghjkl;'zxcvbnm,.`"
const RU = 'йцукенгшщзхъфывапролджэячсмитьбюё'
/** Слово, набранное не в той раскладке: «hfrbnby» → «ракитин», «кфлшешт» → «rakitin». Не похоже — пусто. */
export function swapLayout(word: string): string {
  const to = /[a-z]/.test(word) ? [EN, RU] : /[а-яё]/.test(word) ? [RU, EN] : null
  if (!to) return ''
  const out = [...word].map(c => { const i = to[0].indexOf(c); return i < 0 ? c : to[1][i] }).join('')
  return out === word ? '' : fold(out)
}

/** Скелеты всех слов имени — для сравнения с началом слова */
const skeletons = (texts: readonly string[]): string[] => texts.flatMap(t => fold(t).split(/[\s(),–-]+/)).map(skeleton).filter(Boolean)

/** Слово запроса нашлось: прямо (внутри строки), в другой раскладке или по скелету — с начала слова имени.
 *  Скелет — только если в слове запроса хотя бы две согласные: иначе «ан» нашёл бы половину дерева. */
function wordFound(w: string, key: string, skels: () => string[]): boolean {
  if (key.includes(w)) return true
  const sw = swapLayout(w)
  if (sw && key.includes(sw)) return true
  return [w, sw].some(x => { const s = x && skeleton(x); return !!s && s.length >= 2 && skels().some(n => n.startsWith(s)) })
}

/** Подходит ли человек: каждое слово запроса есть хоть в одной из его строк (записи имени, годы). */
export function matchesName(texts: readonly string[], words: readonly string[]): boolean {
  if (!words.length) return false
  const key = fold(texts.join(' '))
  let sk: string[] | undefined
  const skels = () => (sk ??= skeletons(texts))
  return words.every(w => wordFound(w, key, skels))
}

/** Порядок в выдаче: 0 — слово запроса стоит в начале какой-то записи имени, 1 — с него начинается слово, 2 — внутри,
 *  3 — нашлось только по скелету или в другой раскладке. */
export function nameRank(texts: readonly string[], words: readonly string[]): number {
  const ns = texts.map(fold)
  if (ns.some(n => words.every(w => n.split(/[\s(,-]+/).some(x => x.startsWith(w))) && words.some(w => n.startsWith(w)))) return 0
  if (ns.some(n => words.every(w => n.split(/[\s(,-]+/).some(x => x.startsWith(w))))) return 1
  const key = ns.join(' ')
  return words.every(w => key.includes(w)) ? 2 : 3
}
