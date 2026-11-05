// Даты по образцу GEDCOM — на языке страницы. Запись та же, что в карточке (tools/scripts/dates.py): «1971-03-05»,
// «ABT 1935», «BEF 1944-05», «BET 1941 AND 1945», «FROM 1941 TO 1945»; после даты — слова в скобках: «1945 (после
// войны)»; даты нет — только слова: «(без даты)». Слова переводим, только если это одно из частых пояснений
// (PHRASES: «примерно», «детство», «после войны»…); остальные — из источника, как сказано.
import type {Lang} from './data'

const LOCALE: Record<Lang, string> = {ru: 'ru-RU', pl: 'pl-PL', es: 'es-AR', en: 'en-GB'}
const RU_GEN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
const RU_NOM = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']
const RU_INS = ['январём', 'февралём', 'мартом', 'апрелем', 'маем', 'июнем', 'июлем', 'августом', 'сентябрём', 'октябрём', 'ноябрём', 'декабрём']

const ROMAN = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X', 'XI', 'XII']

// частые пояснения в скобках → [pl, es, en]; части через «, » переводятся по отдельности: «детство, примерно»
const PHRASES: Record<string, [string, string, string]> = {
  'примерно': ['w przybliżeniu', 'aproximadamente', 'approximately'],
  'годы неизвестны': ['lata nieznane', 'años desconocidos', 'years unknown'],
  'без даты': ['bez daty', 'sin fecha', 'undated'],
  'детство': ['dzieciństwo', 'infancia', 'childhood'],
  'школьные годы': ['lata szkolne', 'años escolares', 'school years'],
  'подростком': ['jako nastolatek', 'de adolescente', 'as a teenager'],
  'до войны': ['przed wojną', 'antes de la guerra', 'before the war'],
  'перед войной': ['tuż przed wojną', 'poco antes de la guerra', 'just before the war'],
  'после войны': ['po wojnie', 'después de la guerra', 'after the war'],
  'сразу после войны': ['zaraz po wojnie', 'justo después de la guerra', 'right after the war'],
  'весна': ['wiosna', 'primavera', 'spring'], 'лето': ['lato', 'verano', 'summer'],
  'осень': ['jesień', 'otoño', 'autumn'], 'зима': ['zima', 'invierno', 'winter'],
  'конец года': ['koniec roku', 'fin de año', 'end of the year'],
  'конец месяца': ['koniec miesiąca', 'fin de mes', 'end of the month'],
  'вывод проекта': ['wniosek projektu', 'deducción del proyecto', 'project inference'],
  'сейчас': ['obecnie', 'ahora', 'now'],
}
const phrase = (p: string, lang: Lang): string => lang === 'ru' ? p
  : p.split(', ').map(x => PHRASES[x]?.[{pl: 0, es: 1, en: 2}[lang]] ?? x).join(', ')

type Words = {ABT: string, CAL: string, EST: string, BEF: string, AFT: string, FROM: string, TO: string, BET: [string, string]}
const WORDS: Record<Lang, Words> = {
  ru: {ABT: 'ок.', CAL: 'расч.', EST: 'оцен.', BEF: 'до', AFT: 'после', FROM: 'с', TO: 'по', BET: ['между', 'и']},
  pl: {ABT: 'ok.', CAL: 'wylicz.', EST: 'szac.', BEF: 'przed', AFT: 'po', FROM: 'od', TO: 'do', BET: ['między', 'a']},
  es: {ABT: 'hacia', CAL: 'calc.', EST: 'est.', BEF: 'antes de', AFT: 'después de', FROM: 'desde', TO: 'hasta', BET: ['entre', 'y']},
  en: {ABT: 'c.', CAL: 'calc.', EST: 'est.', BEF: 'before', AFT: 'after', FROM: 'from', TO: 'until', BET: ['between', 'and']},
}

/** «1971-03-05» → «5 марта 1971», «1986-02» → «февраль 1986», «1986» → «1986». Считаем в UTC,
 *  иначе в Аргентине (UTC−3) 30 декабря превратилось бы в 29-е. ruCase — падеж месяца по-русски («до мая», «между
 *  маем»); prefixed — перед датой «ok.», «przed»…: по-польски месяц тогда римской цифрой («ok. II 1986»), падеж не нужен. */
export function fmtIso(iso: string, lang: Lang, ruCase: string[] = RU_NOM, prefixed = false): string {
  const m = /^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$/.exec(iso)
  if (!m) return iso
  if (!m[2]) return m[1]
  if (lang === 'ru' && !m[3]) return `${ruCase[+m[2] - 1]} ${m[1]}`
  if (lang === 'pl' && !m[3] && prefixed) return `${ROMAN[+m[2] - 1]} ${m[1]}`
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +(m[3] || 1)))
  const opt: Intl.DateTimeFormatOptions = m[3] ? {day: 'numeric', month: 'long', year: 'numeric'} : {month: 'long', year: 'numeric'}
  return new Intl.DateTimeFormat(LOCALE[lang], {...opt, timeZone: 'UTC'}).format(d).replace(/\s?г\.$/, '')
}

const ISO = String.raw`\d{4}(?:-\d{2}(?:-\d{2})?)?`
const CARD = new RegExp(String.raw`^(?:(?:(ABT|CAL|EST|BEF|AFT|FROM|TO) )?(${ISO})|BET (${ISO}) AND (${ISO})|FROM (${ISO}) TO (${ISO}))?(?: ?\(([^()]+)\))?$`)

/** Дата GEDCOM-записью карточки → текст на языке страницы. Не разобралась — как есть. */
export function fmtGed(ged: string, lang: Lang): string {
  const m = CARD.exec(ged.trim())
  if (!m || !(m[2] || m[3] || m[5] || m[7])) return ged
  if (!(m[2] || m[3] || m[5])) return `(${phrase(m[7], lang)})`  // даты нет — одни слова
  const w = WORDS[lang]
  const tail = m[7] ? ` (${phrase(m[7], lang)})` : ''
  let s = ''
  if (m[2]) {
    const q = m[1] as keyof Words | undefined
    const ruCase = q === 'CAL' || q === 'EST' || q === 'TO' || !q ? RU_NOM : RU_GEN
    s = (q ? `${w[q]} ` : '') + fmtIso(m[2], lang, ruCase, !!q)
  } else if (m[3]) {
    const [a, b] = [m[3], m[4]]
    const decade = /^\d{3}0$/.test(a) && +b === +a + 9
    s = decade && lang === 'ru' ? `${a}-е` : decade && lang === 'en' ? `${a}s` : decade && lang === 'es' ? `década de ${a}`
      : `${w.BET[0]} ${fmtIso(a, lang, RU_INS, true)} ${w.BET[1]} ${fmtIso(b, lang, RU_INS, true)}`
  } else if (m[5]) {
    const [a, b] = [fmtIso(m[5], lang), fmtIso(m[6], lang)]
    const years = /^\d{4}$/.test(m[5]) && /^\d{4}$/.test(m[6])
    // несколько десятилетий: FROM 1960 TO 1979 — «1960-е–1970-е» (как dates.py)
    const last = +m[6] - 9, decades = years && /0$/.test(m[5]) && /9$/.test(m[6]) && last > +m[5]
    s = decades && lang === 'ru' ? `${m[5]}-е–${last}-е` : decades && lang === 'en' ? `${m[5]}s–${last}s`
      : decades && lang === 'es' ? `décadas de ${m[5]} a ${last}` : years ? `${a}–${b}` : `${a} – ${b}`
  }
  return (s + tail).trim()
}
