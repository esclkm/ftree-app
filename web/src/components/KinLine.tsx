// Строка «Кем приходится»: на странице человека и над деревом.
// from — от кого считаем: «я» или человек, выбранный в дереве («кем приходится другому»). Не выбран никто — строки нет.
// «Кто я» выбирают на странице «Настройки» (app/pages/Settings.tsx), не здесь: кнопки в каждом профиле отвлекали.
import {Fragment, useState} from 'react'
import {t} from '../i18n'
import {kin, personName, relation} from '../kin'
import {useMe} from '../me'
import {Icon} from './Icon'
import {KinDiagram} from './KinDiagram'

export function KinLine({personId, from, linkTo, onClearFrom, extra}: {
  personId: string
  /** от кого считать; не задан — от «меня» */
  from?: string | null
  /** адрес для человека в цепочке: страница или место в дереве */
  linkTo: (id: string) => string
  onClearFrom?: () => void
  /** кнопки, которые добавляет дерево («кем приходится другому») */
  extra?: React.ReactNode
}) {
  const me = useMe()
  const [chart, setChart] = useState(false)
  const start = from || me

  if (!start) return extra ? <div className="kin">{extra}</div> : null
  if (start === personId && !from) return <div className="kin"><span className="kin-term">{t('kin_self')}</span> {extra}</div>

  const r = relation(start, personId)
  // от меня — без подписи, просто «Прапрадед»; от другого человека — «Кем приходится для X ✕:»
  const label = from && <><span className="life">{t('kin_for')} <button className="chip-btn" onClick={onClearFrom} title={t('kin_back')}>{personName(from)} ✕</button>:</span>{' '}</>
  const term = r?.self ? t('kin_origin') : r?.term?.nom
  // цепочка — только те, кто между: «отец Александр → бабушка Мария → прабабушка Вера»; «Вы» и сам человек — лишние
  const via = r ? r.path.slice(from ? 0 : 1, -1) : []
  return (
    <div className="kin">
      <div>
        {label}
        {term ? <span className="kin-term">{from ? term : term[0].toUpperCase() + term.slice(1)}</span> : <span className="life">{t('kin_none')}</span>}
      </div>
      {via.length > 0 && (
        <div className="kin-chain">
          {via.map((id, i) => (
            <Fragment key={id}>
              {i > 0 && <span className="kin-arrow"> → </span>}
              <a href={linkTo(id)}>{id === from ? '' : relation(start, id)?.term?.nom + ' '}{personName(id)}</a>
            </Fragment>
          ))}
        </div>
      )}
      {r && r.path.length > 1 && <button className="chip-btn kd-open" onClick={() => setChart(true)}><Icon name="tree" />{t('kin_chart')}</button>}
      {chart && r && <KinDiagram path={r.path} title={term ?? ''} linkTo={linkTo} onClose={() => setChart(false)} />}
      {' '}{extra}
    </div>
  )
}

/** Адрес страницы человека от корня сайта; код лежит в assets/, корень — на уровень выше */
const ROOT = new URL(/* @vite-ignore */ '..', import.meta.url).href
export const personPage = (id: string) => ROOT + kin.P[id].x.url + location.search
