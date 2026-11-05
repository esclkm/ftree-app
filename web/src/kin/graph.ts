// Кем человек приходится «мне» и через кого. Чистый расчёт, без страницы: его проверяют тесты (test/kin.test.ts).
// Как считаем: общий предок → шаги вверх от меня (a) и вниз к человеку (b) → название по языку (terms.ts).
// Нет общего предка — идём через браки: тёща, жена брата, брат жены, сват, «жена деда жены».
import type {Lang, Names, Sex} from '../data'
import {BLOOD, CO_PARENT, IN_END, IN_LAW, IN_START, OF, RELATIVE, SVOYAK, spouseWord, word, type Word} from './terms'

export interface Person { id: string; g: Sex; p: string[]; s: string[]; x: Names & {slug: string; url: string} }
interface Node extends Person { c: string[] }

/** Кровное родство: a шагов вверх до общего предка lca, b вниз; path — цепочка id от первого человека ко второму */
export interface Blood { a: number; b: number; lca: string; path: string[]; half?: Sex }
export interface Relation { term?: Word; path: string[]; self?: boolean; blood?: boolean; far?: boolean }
interface Step { cost: number; seg: number; from?: string; kind?: 'spouse' | 'blood'; r?: Blood }

export class Kinship {
  readonly P: Record<string, Node> = {}
  readonly bySlug: Record<string, string> = {}
  private ancMemo: Record<string, Map<string, {d: number; via: string | null}>> = {}
  private bestMemo: Record<string, Record<string, Step>> = {}
  private relMemo: Record<string, Relation | null> = {}

  constructor(people: Person[], private divorces: Record<string, string> = {}) {
    for (const d of people) { this.P[d.id] = {...d, c: []}; this.bySlug[d.x.slug] = d.id }
    for (const d of people) for (const pid of d.p) this.P[pid]?.c.push(d.id)
  }

  private F = (id: string) => this.P[id].g === 'F'
  private divorced = (a: string, b: string) => [a, b].sort().join('|') in this.divorces

  /** предки: id → {d: сколько шагов вверх, via: через кого из детей шли вниз к исходному человеку} */
  private anc(id: string) {
    if (this.ancMemo[id]) return this.ancMemo[id]
    const m = new Map<string, {d: number; via: string | null}>([[id, {d: 0, via: null}]]), queue = [id]
    while (queue.length) {
      const c = queue.shift()!
      for (const pid of this.P[c].p) if (this.P[pid] && !m.has(pid)) { m.set(pid, {d: m.get(c)!.d + 1, via: c}); queue.push(pid) }
    }
    return (this.ancMemo[id] = m)
  }
  /** цепочка от id вверх до предка top */
  private upPath(id: string, top: string): string[] {
    const r: string[] = [], a = this.anc(id)
    for (let c: string | null = top; c; c = a.get(c)!.via) r.push(c)
    return r.reverse()
  }

  /** кровное родство через ближайшего общего предка; null — общих предков нет */
  blood(A: string, X: string): Blood | null {
    const ma = this.anc(A), mx = this.anc(X)
    let best: {a: number; b: number; lca: string} | null = null
    for (const [c, ia] of ma) {
      const ix = mx.get(c)
      if (ix && (!best || ia.d + ix.d < best.a + best.b)) best = {a: ia.d, b: ix.d, lca: c}
    }
    if (!best) return null
    const r: Blood = {...best, path: this.upPath(A, best.lca).concat(this.upPath(X, best.lca).reverse().slice(1))}
    if (r.a === 1 && r.b === 1) {  // брат или сестра по одному родителю — только если у обоих записаны оба родителя
      const common = this.P[A].p.filter(p => this.P[X].p.includes(p))
      if (common.length === 1 && this.P[A].p.length === 2 && this.P[X].p.length === 2) r.half = this.P[common[0]].g
    }
    return r
  }

  /** название кровного родства; нет слова в языке — через звено на пути: «кузен отца», «сын двоюродного брата» */
  private bloodTerm(L: Lang, r: Blood, X: string): Word {
    const f = this.F(X), path = r.path
    const t = BLOOD[L](r.a, r.b, f, {half: r.half, side: path[1] ? this.P[path[1]].g : undefined,
      sib: r.a === 1 && path[2] ? this.P[path[2]].g : null})
    if (t) return t
    const me = path[0]
    // прямая линия и одно поколение названы во всех языках — сюда не доходит, но без этого описание зациклится
    if (!r.a || !r.b || r.a === r.b) return word(L, RELATIVE[L][f ? 1 : 0], f)
    // человек старше: мой предок Y на его поколении, он — брат или кузен Y; младше — его предок Z на моём поколении
    const Y = r.a > r.b ? path[r.a - r.b] : path[r.a * 2]
    return OF[L](this.bloodTerm(L, this.blood(Y, X)!, X), this.bloodTerm(L, this.blood(me, Y)!, Y))
  }

  // Самое короткое объяснение для всех сразу: шаг по крови (от меня или от того, кто вошёл в семью браком) стоит столько,
  // сколько поколений вверх и вниз; шаг «супруг» — 1. При равной длине — меньше звеньев.
  // Так «жена деда жены» находится сама, а у кровных родных всегда прямое название, без «брат отца» вместо «дядя».
  private explain(me: string): Record<string, Step> {
    if (this.bestMemo[me]) return this.bestMemo[me]
    const best: Record<string, Step> = {[me]: {cost: 0, seg: 0}}, done = new Set<string>()
    const worse = (x: Step, y: Step) => x.cost - y.cost || x.seg - y.seg
    for (;;) {
      let u: string | null = null
      for (const k in best) if (!done.has(k) && (u === null || worse(best[k], best[u]) < 0)) u = k
      if (u === null) break
      done.add(u)
      const bu = best[u], from = u
      const relax = (v: string, cost: number, e: Partial<Step>) => {
        const c: Step = {cost, seg: bu.seg + 1, from, ...e}
        if (!best[v] || worse(c, best[v]) < 0) best[v] = c
      }
      for (const v of this.P[u].s) if (!done.has(v) && this.P[v]) relax(v, bu.cost + 1, {kind: 'spouse'})
      if (u === me || bu.kind === 'spouse')
        for (const v in this.P) if (!done.has(v)) { const r = this.blood(u, v); if (r) relax(v, bu.cost + r.a + r.b, {kind: 'blood', r}) }
    }
    return (this.bestMemo[me] = best)
  }

  /** Кем X приходится me на языке L; null — связи нет или кого-то нет в данных (пустая карточка дерева) */
  relation(me: string, X: string, L: Lang): Relation | null {
    if (!this.P[me] || !this.P[X]) return null
    const key = me + '>' + X + '>' + L
    if (!(key in this.relMemo)) this.relMemo[key] = this.compute(me, X, L)
    return this.relMemo[key]
  }

  private compute(me: string, X: string, L: Lang): Relation | null {
    const f = this.F(X), best = this.explain(me), e = best[X]
    if (me === X) return {self: true, path: [me]}
    if (!e) return this.farChain(me, X, L)
    const Q = e.from!, eq = best[Q], up = Q === me ? null : this.relation(me, Q, L)!
    const path = (up ? up.path : [me]).concat(e.kind === 'blood' ? e.r!.path.slice(1) : [X])
    let term: Word
    if (e.kind === 'spouse') {
      const sp = spouseWord(L, f, this.divorced(Q, X))
      if (Q === me) term = sp
      else {  // X — супруг того, кто мне Q: мачеха, зять, невестка — или «жена двоюродного брата»
        const R = eq.from!, er = best[R]
        const svoyak = !f && this.F(Q) && eq.kind === 'blood' && R !== me && er.kind === 'spouse' && er.from === me
          && this.F(R) && eq.r!.a === 1 && eq.r!.b === 1 && SVOYAK[L]  // муж сестры жены
        const special = svoyak || (eq.kind === 'blood' && R === me && IN_END[L](eq.r!, f))
        term = special ? word(L, special, f) : OF[L](sp, up!.term!)
      }
    } else if (Q === me) term = this.bloodTerm(L, e.r!, X)
    else {  // X — кровный родственник Q, а Q вошёл в семью браком с R
      const R = eq.from!, er = best[R]
      const start = R === me && IN_START[L](e.r!, f, this.F(Q))
      const co = er?.kind === 'blood' && er.from === me && er.r!.a === 0 && er.r!.b === 1 && e.r!.a === 1 && e.r!.b === 0 && CO_PARENT[L](f)
      term = start ? word(L, start, f) : co ? word(L, co, f) : OF[L](this.bloodTerm(L, e.r!, X), up!.term!)
    }
    return {term, path, blood: e.kind === 'blood' && Q === me}
  }

  /** ни кровью, ни браками по шагам не дойти (например, общий ребёнок без записи о браке) — кратчайшая цепочка */
  private farChain(me: string, X: string, L: Lang): Relation | null {
    const prev: Record<string, string | null> = {[me]: null}, queue = [me]
    while (queue.length && !(X in prev)) {
      const c = queue.shift()!, n = this.P[c]
      for (const v of n.p.concat(n.c, n.s)) if (this.P[v] && !(v in prev)) { prev[v] = c; queue.push(v) }
    }
    if (!(X in prev)) return null
    const path: string[] = []
    for (let c: string | null = X; c; c = prev[c]) path.unshift(c)
    return {term: word(L, IN_LAW[L][this.F(X) ? 1 : 0], this.F(X)), path, far: true}
  }
}
