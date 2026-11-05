// Порядок братьев и сестёр на схеме дерева
import type {TreePerson} from '../data'

/** Братья и сёстры — по рождению. Список детей у родителя уже по датам (cards.tree.order_family), но братьев человека
 *  в центре библиотека берёт из общего списка людей и его самого ставит первым — поэтому сравниваем сами: кто раньше
 *  в списке детей общего родителя. */
type Rel = {id: string; rels: {parents: string[]}}
export function birthOrder(people: TreePerson[]): (a: Rel, b: Rel) => number {
  const rank = new Map<string, number>()  // «родитель|ребёнок» → место среди детей
  for (const p of people) p.rels.children.forEach((c, i) => rank.set(p.id + '|' + c, i))
  return (a, b) => {
    const p = a.rels.parents.find(x => b.rels.parents.includes(x))
    return p ? (rank.get(p + '|' + a.id) ?? 0) - (rank.get(p + '|' + b.id) ?? 0) : 0
  }
}
