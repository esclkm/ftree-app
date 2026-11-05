// Значки «сколько материала» у человека: биография, тексты, факты, семейные источники, найденное, чужие деревья, фото.
import type {Stats} from '../data'
import {Icon} from '../components/Icon'
import {useT} from './i18n'

const KEYS = ['bio', 'texts', 'facts', 'fam', 'web', 'tree', 'pics'] as const

export function Badges({st, words = false}: {st?: Stats; words?: boolean}) {
  const t = useT()
  const on = st ? KEYS.filter(k => st[k]) : []
  if (!on.length) return words ? <span className="chip none">{t('nothing_yet')}</span> : null
  return <span className="chips">{on.map(k =>
    <span key={k} className="chip" title={t(`b_${k}`)}><Icon name={k} />{k !== 'bio' && <b>{st![k] as number}</b>}{words && ' ' + t(`b_${k}`)}</span>)}
  </span>
}
