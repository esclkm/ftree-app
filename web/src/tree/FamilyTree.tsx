// Схема дерева. Рисует библиотека family-chart (на d3); этот компонент создаёт её один раз и передаёт ей изменения:
// кто в центре, сколько поколений, от кого считать родство и какой путь подсветить.
import {select, zoomIdentity, zoomTransform, type ZoomBehavior} from 'd3'
import {createChart, type Chart, type TreeDatum} from 'family-chart'
import {useEffect, useRef} from 'react'
import type {TreePerson} from '../data'
import {cardHtml} from './card'
import {colorLinks, highlightPath, roundLinks} from './links'
import {birthOrder} from './order'
import {pathEdges} from './path'

const ALL = 99  // «все поколения»
// карточки переезжают коротко и плавно (раньше 0,7 с — тянулось); линии на это время прячутся и проявляются, когда
// карточки уже на месте: иначе новые линии видны раньше карточек, к которым они ведут
const ANIM = 350, LINKS_IN = 180
type Zoomable = Element & {__zoomObj: ZoomBehavior<Element, unknown>}  // масштаб висит на svg или его родителе

export interface TreeView {
  mainId: string; ancestry: number; progeny: number
  /** от кого считаем родство и путь к человеку в центре (пусто — не подсвечиваем) */
  from: string | null; fromIsMe: boolean; path: string[]
}

export function FamilyTree({people, view, onCardClick}: {people: TreePerson[]; view: TreeView; onCardClick: (id: string) => void}) {
  const box = useRef<HTMLDivElement>(null)
  const chart = useRef<Chart | null>(null)
  const card = useRef<HtmlCard | null>(null)
  const mobNow = useRef(false)  // в каком размере схема построена сейчас: телефон или компьютер
  const prev = useRef<TreeView | null>(null)
  const moving = useRef(false)  // эта перестройка двигает карточки (другой человек в центре, другие поколения, размер)
  // библиотека вызывает наши функции позже, сама — берём из ref самые свежие значения, а не те, что были при создании
  const live = useRef({view, onCardClick})
  live.current = {view, onCardClick}

  useEffect(() => {
    const c = chart.current ?? (chart.current = create())
    const p = prev.current
    prev.current = view
    c.setAncestryDepth(view.ancestry || ALL).setProgenyDepth(view.progeny || ALL)
    if (!p) {  // первая отрисовка: сразу всё, без «вырастания» по поколениям, и приблизить к человеку в центре
      c.setTransitionTime(0); c.updateMainId(view.mainId); c.updateTree({initial: true}); c.setTransitionTime(ANIM)
      focusMain(0)
      return
    }
    const move = p.mainId !== view.mainId || p.ancestry !== view.ancestry || p.progeny !== view.progeny
    if (p.mainId !== view.mainId) c.updateMainId(view.mainId)
    moving.current = move
    c.updateTree({tree_position: 'inherit'})
    if (move) focusMain()
  }, [view.mainId, view.ancestry, view.progeny, view.from, view.path.join('|')])

  // окно сузили или расширили через границу «телефон» — шаг между карточками пересчитать, иначе крупные карточки
  // компьютера стоят с телефонным шагом и наезжают друг на друга (и наоборот). Сверяем при каждом изменении размера
  // схемы, в том числе сразу после запуска: окно могло поменяться, пока схема строилась
  useEffect(() => {
    const check = () => {
      const c = chart.current, mob = matchMedia(MOB_Q).matches
      if (!c || !card.current || mob === mobNow.current) return
      sizeFor(c, card.current, mob); mobNow.current = mob
      moving.current = true
      c.updateTree({tree_position: 'inherit'})
    }
    const ro = new ResizeObserver(check)  // следим за самой схемой: срабатывает и при первом показе
    ro.observe(box.current!)
    return () => ro.disconnect()
  }, [])

  function create(): Chart {
    const c = createChart(box.current!, people).setTransitionTime(ANIM).setShowSiblingsOfMain(true)
      .setSortChildrenFunction(birthOrder(people))
    card.current = c.setCardHtml()
    mobNow.current = matchMedia(MOB_Q).matches
    sizeFor(c, card.current, mobNow.current)
    card.current
      .setCardInnerHtmlCreator((d: TreeDatum) => {
        const v = live.current.view
        return cardHtml(d, {mainId: v.mainId, from: v.from, fromIsMe: v.fromIsMe, onPath: new Set(v.path)})
      })
      .setOnCardClick((_e: MouseEvent, d: TreeDatum) => live.current.onCardClick(d.data.id))
    c.setAfterUpdate(after)
    // отдалили — остаются только имя и фамилия, крупно: мелкие подробности всё равно не читаются
    const z = zoomEl(c)
    const lod = (k: number) => { box.current!.classList.toggle('far', k < .62); box.current!.classList.toggle('very-far', k < .38) }
    z.__zoomObj.on('zoom.lod', e => lod(e.transform.k))
    lod(zoomTransform(z).k)
    return c
  }
  function after() {
    const c = chart.current!
    roundLinks(c.svg, 0)  // скруглённые углы вместо размытых кривых библиотеки — сразу на новых местах, пока спрятаны
    colorLinks(c.svg)
    highlightPath(c.svg, pathEdges(live.current.view.path))
    const links = select(c.svg).select<SVGGElement>('.links_view').interrupt('show')
    if (moving.current) links.style('opacity', 0).transition('show').delay(ANIM).duration(LINKS_IN).style('opacity', 1)
    else links.style('opacity', 1)
    moving.current = false
  }
  // человек в центре — не строго посередине, а по высоте пропорционально предкам и потомкам:
  // у кого много предков и мало потомков — ниже, чтобы предкам хватило места сверху
  function focusMain(ms = ANIM) {
    const c = chart.current!, data = c.store.getTree()!.data, d = c.store.getTreeMainDatum()
    const ys = data.map(x => x.y), minY = Math.min(...ys), maxY = Math.max(...ys)
    const frac = maxY > minY ? (d.y - minY) / (maxY - minY) : .5
    const z = zoomEl(c), rect = c.svg.getBoundingClientRect(), k = .9
    const tr = zoomIdentity.translate(rect.width / 2 - d.x * k, rect.height * (.12 + .76 * frac) - d.y * k).scale(k)
    select<Element, unknown>(z).transition().duration(ms).call(z.__zoomObj.transform, tr)
  }

  return <div id="FamilyChart" className="f3" ref={box} />
}

// телефон: карточки теснее (размеры — те же, что в стилях для телефона, _tree.scss); шаг 94 при ширине 84 — между
// карточками 10 px (2 px слипаются); по вертикали — место под линии
const MOB_Q = '(max-width:700px)'
type HtmlCard = ReturnType<Chart['setCardHtml']>
function sizeFor(c: Chart, card: HtmlCard, mob: boolean) {
  c.setCardXSpacing(mob ? 94 : 158).setCardYSpacing(mob ? 124 : 196)
  card.setCardDim({w: mob ? 84 : 132, h: mob ? 106 : 168, text_x: 0, text_y: 0, img_w: 0, img_h: 0, img_x: 0, img_y: 0})
}

const zoomEl = (c: Chart) => ((c.svg as unknown as Zoomable).__zoomObj ? c.svg : c.svg.parentNode) as unknown as Zoomable
