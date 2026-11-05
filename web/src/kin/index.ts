// Граф родства из данных страницы: на странице дерева — TREE (tree_data.js), на страницах людей — KIN (kin_data.js)
import {divorces, kinRows, tree} from '../data'
import {LANG, nameOf} from '../i18n'
import {Kinship, type Person, type Relation} from './graph'

function load(): Person[] {
  const tr = tree()
  if (tr) return tr.map(d => ({id: d.id, g: d.data.gender, p: d.rels.parents, s: d.rels.spouses || [], x: d.data}))
  return (kinRows() || []).map(([id, g, p, s, slug, ru, en, pl, es, url]) => ({id, g, p, s, x: {slug, ru, en, pl, es, url}}))
}
export const kin = new Kinship(load(), divorces())

/** Кем X приходится человеку from — на языке сайта */
export const relation = (from: string, X: string): Relation | null => kin.relation(from, X, LANG)
export const personName = (id: string): string => nameOf(kin.P[id].x)
