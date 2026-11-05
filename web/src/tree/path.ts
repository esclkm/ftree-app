// Путь родства на дереве: какие линии подсветить. Чистые функции — их проверяет test/path.test.ts.

/** Пары соседей на пути «я → отец → дед → дядя»: каждая пара — одна линия дерева (родитель–ребёнок или супруги) */
export function pathEdges(path: string[]): Set<string> {
  const edges = new Set<string>()
  for (let i = 1; i < path.length; i++) edges.add([path[i - 1], path[i]].sort().join('|'))
  return edges
}

/** Линия идёт от одних людей к другим: к ребёнку — от пары родителей сразу, поэтому с каждой стороны список.
 *  Она на пути, если хоть одна пара «отсюда — туда» — соседи на пути. */
export function onPath(edges: Set<string>, a: string[], b: string[]): boolean {
  return a.some(x => b.some(y => edges.has([x, y].sort().join('|'))))
}
