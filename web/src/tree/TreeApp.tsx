// Страница дерева: панель сверху (поиск, родство, вид, «?») и схема. Сколько поколений показывать — на странице
// «Настройки» (app/pages/Settings.tsx), ключи браузера — TREE_ANC и TREE_DESC.
// Кто в центре — в адресе (tree.html#ivan-yasenev-1878): такую ссылку можно отправить. Без адреса — «я» из
// «Настроек», а если «я» не выбран — корень дерева.
import {useEffect, useState} from 'react'
import {Icon} from '../components/Icon'
import {KinLine} from '../components/KinLine'
import {PersonSearch} from '../components/PersonSearch'
import {Popover} from '../components/Popover'
import {start, type TreePerson} from '../data'
import {t} from '../i18n'
import {kin, relation} from '../kin'
import {useStoredNumber} from '../hooks'
import {getMe, useMe} from '../me'
import {FamilyTree} from './FamilyTree'
import {TreeSteps} from './TreeSteps'

export const GENERATIONS = [0, 1, 2, 3, 4, 5, 6, 7, 8]  // 0 — все
export const TREE_ANC = 'tree_anc', TREE_DESC = 'tree_desc'
const SCHEME = 1, STEPS = 2  // вид дерева (tree_mode в браузере); 0 — не выбирали
const KIN = ['likely', 'possible', 'unlikely', 'no'] as const
const BADGES = ['bio', 'texts', 'facts', 'fam', 'web', 'tree', 'pics']

const fromHash = () => { const h = decodeURIComponent(location.hash.slice(1)); return kin.bySlug[h] || (kin.P[h] ? h : null) }

export function TreeApp({people}: {people: TreePerson[]}) {
  // в центр — только человек из графа родства: неизвестный номер (устаревшая ссылка, заглушка библиотеки) не принимаем
  const [mainId, setMainIdRaw] = useState(() => fromHash() || getMe() || (kin.P[start()] ? start() : Object.keys(kin.P)[0]))
  const setMainId = (id: string) => { if (kin.P[id]) setMainIdRaw(id) }
  const [ancestry] = useStoredNumber(TREE_ANC)
  const [progeny] = useStoredNumber(TREE_DESC)
  // вид: схема (по умолчанию, и на телефоне) или «по шагам» — выбор запоминается в браузере
  const [mode, setMode] = useStoredNumber('tree_mode')
  const steps = mode === STEPS
  const me = useMe()
  // «кем приходится другому»: от кого считать, если не от меня; живёт до перезагрузки страницы
  const [other, setOther] = useState<string | null>(null)
  const [picking, setPicking] = useState(false)

  // человек в центре ↔ адрес страницы
  useEffect(() => { const x = kin.P[mainId]; if (x) history.replaceState(null, '', location.search + '#' + x.x.slug) }, [mainId])
  useEffect(() => {
    const onHash = () => { const id = fromHash(); if (id) setMainId(id) }
    addEventListener('hashchange', onHash)
    return () => removeEventListener('hashchange', onHash)
  }, [])

  const from = other || me
  const path = from && from !== mainId ? relation(from, mainId)?.path || [] : []
  // первое нажатие — повернуть дерево к человеку, второе (он уже в центре) — открыть его страницу
  const onCardClick = (id: string) => { if (id === mainId && kin.P[id]) location.href = kin.P[id].x.url + location.search; else setMainId(id) }
  const pickOther = picking
    ? <span className="kin-pick"><PersonSearch people={people} placeholder={t('kin_other_ph')} autoFocus
        onPick={id => { setOther(id); setPicking(false) }} /><button className="linkbtn" onClick={() => setPicking(false)}>✕</button></span>
    : <button className="linkbtn kin-other" onClick={() => setPicking(true)}>{t('kin_other')}</button>

  return (
    <>
      <div className="treebar">
        <PersonSearch people={people} placeholder={t('search_ph')} onPick={setMainId} />
        <KinLine personId={mainId} from={other} onClearFrom={() => setOther(null)} linkTo={id => '#' + kin.P[id].x.slug} extra={pickOther} />
        <span className="tree-mode" role="group">
          <button className={steps ? '' : 'on'} onClick={() => setMode(SCHEME)}>{t('tree_scheme')}</button>
          <button className={steps ? 'on' : ''} onClick={() => setMode(STEPS)}>{t('tree_steps')}</button>
        </span>
        <Popover icon="help" title={t('help')} className="help">
          <p>{t('tree_hint')}</p>
          <div className="legend">
            {BADGES.map(k => <span key={k} className="chip"><Icon name={k} />{t('b_' + k)}</span>)}
            <span className="chip"><span className="empty-sample" />{t('empty_legend')}</span>
            <span className="chip">{KIN.map(k => <span key={k} className={`kin-sample k-${k}`} />)}{t('kin_legend')}</span>
            <span className="chip"><span className="mar-sample" style={{background: '#1c8fa6'}} /><span className="mar-sample" style={{background: '#e09100'}} />{t('mar_legend')}</span>
            <span className="chip"><span className="div-sample" />{t('div_legend')}</span>
            <span className="chip"><span className="path-sample" />{t('path_legend')}</span>
          </div>
        </Popover>
      </div>
      {steps
        ? <TreeSteps people={people} mainId={mainId} from={from} fromIsMe={!other} path={path} onCardClick={onCardClick} />
        : <FamilyTree people={people} onCardClick={onCardClick} view={{mainId, ancestry, progeny, from, fromIsMe: !other, path}} />}
    </>
  )
}
