// Названия родства на четырёх языках. Только слова — кто кому кем приходится, считает graph.ts.
// Кровное родство задаётся двумя числами: a — шагов вверх от меня до общего предка, b — вниз от него к человеку.
// Пример: a = 2, b = 2 — общий дед, человек — внук деда по другой ветке, то есть двоюродный брат.
import type {Lang, Sex} from '../data'

/** Название: именительный падеж, родительный (для «брат дедушки») и пол — испанскому нужен артикль del / de la */
export interface Word { nom: string; gen: string; f: boolean }
/** Сколько шагов вверх и вниз до человека */
export interface Steps { a: number; b: number }
/** half — пол общего родителя у брата/сестры по одному родителю; side — пол моего родителя на пути (польск. stryj/wuj);
 *  sib — пол моего брата/сестры на пути к племяннику (польск. bratanek/siostrzeniec) */
export interface BloodCtx { half?: Sex; side?: Sex; sib?: Sex | null }

const rep = (s: string, n: number) => s.repeat(Math.max(0, n))
const w = (nom: string, gen: string | null, f: boolean): Word => ({nom, gen: gen ?? nom, f})

const RU_GEN: Record<string, string> = {отец: 'отца', мать: 'матери', дед: 'деда', бабушка: 'бабушки', сын: 'сына', дочь: 'дочери',
  внук: 'внука', внучка: 'внучки', брат: 'брата', сестра: 'сестры', дядя: 'дяди', тётя: 'тёти', племянник: 'племянника',
  племянница: 'племянницы', муж: 'мужа', жена: 'жены', отчим: 'отчима', мачеха: 'мачехи', зять: 'зятя', невестка: 'невестки',
  тесть: 'тестя', тёща: 'тёщи', свёкор: 'свёкра', свекровь: 'свекрови', шурин: 'шурина', свояченица: 'свояченицы', деверь: 'деверя',
  золовка: 'золовки', пасынок: 'пасынка', падчерица: 'падчерицы', сват: 'свата', сватья: 'сватьи', свояк: 'свояка'}
// прилагательные: одно правило на слово, первое подходящее («двоюродная» → «двоюродной», а не дальше в «-ого»)
const RU_ADJ_GEN: [RegExp, string][] = [[/([жшчщ])ая$/, '$1ей'], [/ая$/, 'ой'], [/[ыо]й$/, 'ого'], [/ий$/, 'его']]
export const ruGen = (s: string): string => s.split(' ').map(x => {
  const pra = x.match(/^(?:пра)*/)![0], core = x.slice(pra.length)
  if (RU_GEN[core]) return pra + RU_GEN[core]
  const rule = RU_ADJ_GEN.find(([re]) => re.test(x))
  return rule ? x.replace(rule[0], rule[1]) : x
}).join(' ')
const PL_GEN: Record<string, string> = {ojciec: 'ojca', matka: 'matki', dziadek: 'dziadka', babcia: 'babci', syn: 'syna', córka: 'córki',
  wnuk: 'wnuka', wnuczka: 'wnuczki', brat: 'brata', siostra: 'siostry', stryj: 'stryja', wuj: 'wuja', wujek: 'wujka', ciotka: 'ciotki',
  bratanek: 'bratanka', bratanica: 'bratanicy', siostrzeniec: 'siostrzeńca', siostrzenica: 'siostrzenicy', kuzyn: 'kuzyna',
  kuzynka: 'kuzynki', mąż: 'męża', żona: 'żony', przyrodni: 'przyrodniego', przyrodnia: 'przyrodniej', zięć: 'zięcia',
  synowa: 'synowej', szwagier: 'szwagra', szwagierka: 'szwagierki', bratowa: 'bratowej', teść: 'teścia', teściowa: 'teściowej',
  ojczym: 'ojczyma', macocha: 'macochy', pasierb: 'pasierba', pasierbica: 'pasierbicy', swat: 'swata', swatowa: 'swatowej',
  były: 'byłego', była: 'byłej'}
const plGen = (s: string): string => s.split(' ').map(x => {
  const pra = x.match(/^(?:pra)*/)![0], core = x.slice(pra.length)
  return PL_GEN[core] ? pra + PL_GEN[core] : x
}).join(' ')

/** Слово на языке L с родительным падежом там, где он нужен */
export const word = (L: Lang, s: string, f: boolean): Word => L === 'ru' ? w(s, ruGen(s), f) : L === 'pl' ? w(s, plGen(s), f) : w(s, null, f)

const RU_ADJ = ['', '', 'двоюродн', 'троюродн', 'четвероюродн', 'пятиюродн', 'шестиюродн', 'семиюродн', 'восьмиюродн', 'девятиюродн']
const ruAdj = (m: number, f: boolean) => m < 2 ? '' : (RU_ADJ[m] || `${m}-юродн`) + (f ? 'ая ' : 'ый ')
const EN_ORD = ['', '', 'first', 'second', 'third', 'fourth', 'fifth', 'sixth', 'seventh', 'eighth', 'ninth']
const EN_REM = ['', ' once removed', ' twice removed', ' three times removed', ' four times removed']
const ES_ORD = ['', '', 'segundo', 'tercero', 'cuarto', 'quinto', 'sexto', 'séptimo', 'octavo']
const PL_ORD = ['', '', '', 'drugiego', 'trzeciego', 'czwartego', 'piątego', 'szóstego']

type BloodFn = (a: number, b: number, f: boolean, ctx: BloodCtx) => Word | null
/** Кровное родство; null — у языка нет отдельного слова, тогда graph.ts описывает через звено («kuzyn ojca») */
export const BLOOD: Record<Lang, BloodFn> = {
  ru(a, b, f, ctx) {
    const m = Math.min(a, b), d = Math.abs(a - b), ru = (s: string) => word('ru', s, f)
    if (b === 0) return ru(a === 1 ? (f ? 'мать' : 'отец') : rep('пра', a - 2) + (f ? 'бабушка' : 'дед'))
    if (a === 0) return ru(b === 1 ? (f ? 'дочь' : 'сын') : rep('пра', b - 2) + (f ? 'внучка' : 'внук'))
    if (d === 0) return ru(m === 1 && ctx.half ? (ctx.half === 'M' ? 'единокровн' : 'единоутробн') + (f ? 'ая сестра' : 'ый брат')
      : ruAdj(m, f) + (f ? 'сестра' : 'брат'))
    // брат деда — двоюродный дед, но брат отца — просто дядя: у дедов прилагательное на ступень старше
    if (a > b) return ru(d === 1 ? ruAdj(m, f) + (f ? 'тётя' : 'дядя') : ruAdj(m + 1, f) + rep('пра', d - 2) + (f ? 'бабушка' : 'дед'))
    return ru(ruAdj(m, f) + (d === 1 ? '' : rep('пра', d - 2) + (f ? 'внучатая ' : 'внучатый ')) + (f ? 'племянница' : 'племянник'))
  },
  en(a, b, f, ctx) {
    const m = Math.min(a, b), d = Math.abs(a - b), g = (n: number) => rep('great-', n), en = (s: string) => w(s, null, f)
    if (b === 0) return en(a === 1 ? (f ? 'mother' : 'father') : g(a - 2) + (f ? 'grandmother' : 'grandfather'))
    if (a === 0) return en(b === 1 ? (f ? 'daughter' : 'son') : g(b - 2) + (f ? 'granddaughter' : 'grandson'))
    if (m === 1) {
      if (d === 0) return en((ctx.half ? 'half-' : '') + (f ? 'sister' : 'brother'))
      return en(g(d - 1) + (a > b ? (f ? 'aunt' : 'uncle') : (f ? 'niece' : 'nephew')))
    }
    return en(`${EN_ORD[m] || m - 1 + 'th'} cousin${EN_REM[d] ?? ` ${d} times removed`}`)
  },
  es(a, b, f, ctx) {
    const m = Math.min(a, b), d = Math.abs(a - b), o = f ? 'a' : 'o', es = (s: string) => w(s, null, f)
    const UP = ['', f ? 'madre' : 'padre', 'abuel' + o, 'bisabuel' + o, 'tatarabuel' + o, 'trastatarabuel' + o]
    const DOWN = ['', 'hij' + o, 'niet' + o, 'bisniet' + o, 'tataraniet' + o, 'trastataraniet' + o]
    if (b === 0) return es(UP[a] || `${a - 1}.º abuel${o}`)
    if (a === 0) return es(DOWN[b] || `descendiente de ${b}.ª generación`)
    if (m === 1) {
      if (d === 0) return es(ctx.half ? (f ? 'media hermana' : 'medio hermano') : 'herman' + o)
      const t = a > b ? ['', 'tí' + o, f ? 'tía abuela' : 'tío abuelo', f ? 'tía bisabuela' : 'tío bisabuelo']
        : ['', 'sobrin' + o, f ? 'sobrina nieta' : 'sobrino nieto', f ? 'sobrina bisnieta' : 'sobrino bisnieto']
      return t[d] ? es(t[d]) : null
    }
    // primo segundo — троюродный (m = 3), а tío segundo — двоюродный дядя (m = 2): у кузенов порядковое на единицу меньше
    const ordOf = (k: number) => ES_ORD[k] ? ' ' + ES_ORD[k].replace(/o$/, o) : null
    if (d === 0) { const ord = ordOf(m - 1); return m === 2 ? es('prim' + o) : ord ? es('prim' + o + ord) : null }
    const ord = ordOf(m)
    if (d === 1 && ord) return es((a > b ? 'tí' : 'sobrin') + o + ord)
    return null
  },
  pl(a, b, f, ctx) {
    const m = Math.min(a, b), d = Math.abs(a - b), pl = (s: string) => word('pl', s, f)
    if (b === 0) return pl(a === 1 ? (f ? 'matka' : 'ojciec') : rep('pra', a - 2) + (f ? 'babcia' : 'dziadek'))
    if (a === 0) return pl(b === 1 ? (f ? 'córka' : 'syn') : rep('pra', b - 2) + (f ? 'wnuczka' : 'wnuk'))
    if (m === 1 && d === 0) return pl((f ? 'siostra' : 'brat') + (ctx.half ? (f ? ' przyrodnia' : ' przyrodni') : ''))
    // дядя по отцу — stryj, по матери — wuj
    if (m === 1 && d === 1 && a > b) return pl(f ? 'ciotka' : ctx.side === 'M' ? 'stryj' : ctx.side === 'F' ? 'wuj' : 'wujek')
    if (m === 1 && d === 1) return pl(ctx.sib === 'F' ? (f ? 'siostrzenica' : 'siostrzeniec') : (f ? 'bratanica' : 'bratanek'))
    if (d === 0 && m === 2) return pl(f ? 'kuzynka' : 'kuzyn')
    if (d === 0 && PL_ORD[m]) return w(`${f ? 'kuzynka' : 'kuzyn'} ${PL_ORD[m]} stopnia`, `${f ? 'kuzynki' : 'kuzyna'} ${PL_ORD[m]} stopnia`, f)
    return null
  },
}

/** «X моего R»: брат дедушки, father's cousin, primo del abuelo */
export const OF: Record<Lang, (x: Word, r: Word) => Word> = {
  ru: (x, r) => w(`${x.nom} ${r.gen}`, `${x.gen} ${r.gen}`, x.f),
  pl: (x, r) => w(`${x.nom} ${r.gen}`, `${x.gen} ${r.gen}`, x.f),
  en: (x, r) => w(`${r.nom}'s ${x.nom}`, null, x.f),
  es: (x, r) => w(`${x.nom} ${r.f ? 'de la' : 'del'} ${r.nom}`, null, x.f),
}

const SPOUSE: Record<Lang, [string, string, string, string]> = {ru: ['муж', 'жена', 'бывший ', 'бывшая '],
  en: ['husband', 'wife', 'ex-', 'ex-'], es: ['esposo', 'esposa', 'ex ', 'ex '], pl: ['mąż', 'żona', 'były ', 'była ']}
export const spouseWord = (L: Lang, f: boolean, divorced: boolean): Word => {
  const s = SPOUSE[L]
  return word(L, (divorced ? s[f ? 3 : 2] : '') + s[f ? 1 : 0], f)
}

const is = (r: Steps, a: number, b: number) => r.a === a && r.b === b
/** X — супруг моего кровного родственника R (r — родство R со мной): отчим, зять, невестка */
export const IN_END: Record<Lang, (r: Steps, f: boolean) => string | null> = {
  ru: (r, f) => is(r, 1, 0) ? (f ? 'мачеха' : 'отчим') : is(r, 0, 1) || is(r, 1, 1) ? (f ? 'невестка' : 'зять') : null,
  en: (r, f) => is(r, 1, 0) ? (f ? 'stepmother' : 'stepfather') : is(r, 0, 1) ? (f ? 'daughter-in-law' : 'son-in-law')
    : is(r, 1, 1) ? (f ? 'sister-in-law' : 'brother-in-law') : null,
  es: (r, f) => is(r, 1, 0) ? (f ? 'madrastra' : 'padrastro') : is(r, 0, 1) ? (f ? 'nuera' : 'yerno') : is(r, 1, 1) ? (f ? 'cuñada' : 'cuñado') : null,
  pl: (r, f) => is(r, 1, 0) ? (f ? 'macocha' : 'ojczym') : is(r, 0, 1) ? (f ? 'synowa' : 'zięć') : is(r, 1, 1) ? (f ? 'bratowa' : 'szwagier') : null,
}
/** X — кровный родственник моего супруга (r — родство X с супругом; spF — супруг женщина): тёща, шурин, пасынок */
export const IN_START: Record<Lang, (r: Steps, f: boolean, spF: boolean) => string | null> = {
  ru: (r, f, spF) => is(r, 1, 0) ? (spF ? (f ? 'тёща' : 'тесть') : (f ? 'свекровь' : 'свёкор'))
    : is(r, 1, 1) ? (spF ? (f ? 'свояченица' : 'шурин') : (f ? 'золовка' : 'деверь')) : is(r, 0, 1) ? (f ? 'падчерица' : 'пасынок') : null,
  en: (r, f) => is(r, 1, 0) ? (f ? 'mother-in-law' : 'father-in-law') : is(r, 1, 1) ? (f ? 'sister-in-law' : 'brother-in-law')
    : is(r, 0, 1) ? (f ? 'stepdaughter' : 'stepson') : null,
  es: (r, f) => is(r, 1, 0) ? (f ? 'suegra' : 'suegro') : is(r, 1, 1) ? (f ? 'cuñada' : 'cuñado') : is(r, 0, 1) ? (f ? 'hijastra' : 'hijastro') : null,
  pl: (r, f) => is(r, 1, 0) ? (f ? 'teściowa' : 'teść') : is(r, 1, 1) ? (f ? 'szwagierka' : 'szwagier') : is(r, 0, 1) ? (f ? 'pasierbica' : 'pasierb') : null,
}
/** родитель супруга моего ребёнка; в английском отдельного слова нет — будет «son-in-law's father» */
export const CO_PARENT: Record<Lang, (f: boolean) => string | null> = {
  ru: f => f ? 'сватья' : 'сват', es: f => f ? 'consuegra' : 'consuegro', pl: f => f ? 'swatowa' : 'swat', en: () => null}
/** муж сестры жены — только в русском */
export const SVOYAK: Partial<Record<Lang, string>> = {ru: 'свояк'}
export const RELATIVE: Record<Lang, [string, string]> = {ru: ['родственник', 'родственница'], en: ['relative', 'relative'],
  es: ['pariente', 'pariente'], pl: ['krewny', 'krewna']}
export const IN_LAW: Record<Lang, [string, string]> = {ru: ['свойственник', 'свойственница'],
  en: ['relative by marriage', 'relative by marriage'], es: ['pariente político', 'pariente política'], pl: ['powinowaty', 'powinowata']}
