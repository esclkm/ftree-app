// Дерево «по шагам» — для телефона: схема в ширину на узком экране не помещается, и связи теряются за краем. Здесь
// строки сверху вниз — бабушки и дедушки, родители, человек в центре с супругами, братья и сёстры, дети; каждая строка
// листается вбок сама. Нажали на карточку — человек встаёт в центр; ещё раз — его страница (как в схеме).
// Карточки — те же, что в схеме (card.ts).
import type {TreeDatum} from 'family-chart'
import {useEffect, useMemo, useRef} from 'react'
import type {TreePerson} from '../data'
import {t} from '../i18n'
import {cardHtml} from './card'

interface Props {
  people: TreePerson[]; mainId: string
  from: string | null; fromIsMe: boolean; path: string[]
  onCardClick: (id: string) => void
}

const uniq = (ids: string[]) => [...new Set(ids)]

export function TreeSteps({people, mainId, from, fromIsMe, path, onCardClick}: Props) {
  const by = useMemo(() => new Map(people.map(p => [p.id, p])), [people])
  const me = by.get(mainId)
  const rowsRef = useRef<HTMLDivElement>(null)
  // человек в центре — посередине своей строки, а вся полоса строк — к началу
  useEffect(() => {
    rowsRef.current?.querySelector('.steps-card.center')?.scrollIntoView({block: 'nearest', inline: 'center'})
  }, [mainId])
  if (!me) return null
  const kids = (id: string) => by.get(id)?.rels.children ?? []
  const parents = me.rels.parents
  const rows: [string, string[]][] = [
    ['tree_grand', uniq(parents.flatMap(p => by.get(p)?.rels.parents ?? []))],
    ['tree_parents', parents],
    ['tree_center', [mainId, ...me.rels.spouses]],
    ['siblings', uniq(parents.flatMap(kids)).filter(id => id !== mainId)],
    ['children', me.rels.children],
  ]
  const opts = {mainId, from, fromIsMe, onPath: new Set(path)}
  return <div className="steps" ref={rowsRef}>
    {rows.filter(([, ids]) => ids.length).map(([key, ids]) => <section key={key} className={`steps-row ${key}`}>
      <h3>{t(key)} <span className="count">{ids.length}</span></h3>
      <div className="steps-cards">{ids.flatMap(id => {
        const p = by.get(id)
        return p ? [<div key={id} className={`steps-card${id === mainId ? ' center' : ''}`} onClick={() => onCardClick(id)}
          // та же карточка, что в схеме: строка HTML из card.ts (имена и подписи в ней уже экранированы)
          dangerouslySetInnerHTML={{__html: cardHtml({data: p} as unknown as TreeDatum, opts)}} />] : []
      })}</div>
    </section>)}
    <p className="life steps-hint">{t('tree_steps_hint')}</p>
  </div>
}
