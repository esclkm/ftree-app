// Данные сайта. На прежних страницах их писал Python в отдельные файлы (tree_data.js, kin_data.js, map_data.js,
// i18n_data.js) — обычные скрипты с `const …`, подключаются до кода; такие const не свойства window: проверяем через typeof.
// Приложение (src/app) передаёт те же данные из data/index.json и data/ui.json через provide() — до загрузки остального кода.

export type Lang = 'ru' | 'pl' | 'es' | 'en'
export type Sex = 'M' | 'F'

/** Имя по языкам: кириллица по-русски, латиница остальным */
export interface Names { ru: string; en: string; pl: string; es?: string }

/** Сколько материала о человеке — значки на карточке */
export interface Stats { bio: boolean; texts: number; facts: number; fam: number; web: number; tree: number; pics: number; langs: string[] }

export interface TreePersonData extends Names {
  gender: Sex; slug: string; life: string; avatar: string; url: string; st: Stats
  /** номер брака родителей, от которого ребёнок; 0 — один брак */
  mar: number
  /** круг без фото: инициалы по языкам (у неизвестного — null, рисуем значок) и номер цвета 0–7 — от номера человека */
  ini: Names | null; c: number
  /** насколько связь с деревом доказана (kinship карточки); нет — не оценивали */
  kin?: 'proven' | 'likely' | 'possible' | 'unlikely' | 'no'
  /** откуда уровень: card — поставлен в карточке, facts — оценка по фактам */
  kinBy?: 'card' | 'facts'
}
export interface TreePerson { id: string; data: TreePersonData; rels: { parents: string[]; spouses: string[]; children: string[] } }
/** Строка kin_data.js: id, пол, родители, супруги, slug, имена ru/en/pl/es, адрес страницы */
export type KinRow = [string, Sex, string[], string[], string, string, string, string, string, string]
export interface Place extends Names { id: string; lat: number; lng: number; url: string; n: number }
export type Dict = Record<string, string>

declare const TREE: TreePerson[]
declare const START: string
declare const ICONS: Record<string, string>
declare const DIVORCES: Record<string, string>
declare const KIN: KinRow[]
declare const PLACES: Place[]
declare const I18N: Record<Lang, Dict>

interface Provided { tree: TreePerson[]; start: string; icons: Record<string, string>; divorces: Record<string, string>
  places: Place[]; dict: Record<Lang, Dict> }
let provided: Partial<Provided> = {}
/** Приложение: данные из data/*.json вместо файлов нынешних страниц */
export function provide(p: Partial<Provided>): void { provided = {...provided, ...p} }

export const tree = (): TreePerson[] | null => provided.tree ?? (typeof TREE === 'undefined' ? null : TREE)
export const start = (): string => provided.start ?? START
export const icons = (): Record<string, string> => provided.icons ?? (typeof ICONS === 'undefined' ? {} : ICONS)
export const divorces = (): Record<string, string> => provided.divorces ?? (typeof DIVORCES === 'undefined' ? {} : DIVORCES)
export const kinRows = (): KinRow[] | null => typeof KIN === 'undefined' ? null : KIN
export const places = (): Place[] => provided.places ?? PLACES
export const dict = (): Record<Lang, Dict> => provided.dict ?? (typeof I18N === 'undefined' ? {ru: {}, pl: {}, es: {}, en: {}} : I18N)
