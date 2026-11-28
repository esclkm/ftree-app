// Страница человека на широком экране: на половине окна — схема дерева (та же, что на странице «Дерево»), в центре —
// человек, чья страница открыта. Нажатие на карточку открывает страницу того человека, дерево поворачивается к нему —
// так быстро ходят по родне. Поколения — из «Настроек»; путь родства от «я» подсвечен. «Свёрнуто» помнит браузер.
import 'family-chart/styles/family-chart.css'
import {useState} from 'react'
import {useNavigate} from 'react-router'
import {Icon} from '../../components/Icon'
import {tree} from '../../data'
import {useStoredNumber} from '../../hooks'
import {kin, relation} from '../../kin'
import {useMe} from '../../me'
import {FamilyTree} from '../../tree/FamilyTree'
import {TREE_ANC, TREE_DESC} from '../../tree/TreeApp'
import {useT} from '../i18n'
import {useLinks} from '../useIndex'
import './charts.scss'

const OPEN = 'ftree.sideOpen'
const wide = () => typeof matchMedia !== 'undefined' && matchMedia('(min-width: 1400px)').matches

export function SideTree({id}: {id: string}) {
  const t = useT(), href = useLinks(), navigate = useNavigate(), me = useMe(), people = tree()
  const [open, setOpen] = useState(() => { try { return localStorage.getItem(OPEN) !== '0' } catch { return true } })
  const [ancestry] = useStoredNumber(TREE_ANC)
  const [progeny] = useStoredNumber(TREE_DESC)
  const toggle = () => { setOpen(!open); try { localStorage.setItem(OPEN, open ? '0' : '1') } catch { /* без хранилища */ } }
  // узкое окно — схемы нет вовсе: библиотека дерева тяжёлая, а показать её негде
  if (!people || !kin.P[id] || !wide()) return null
  if (!open) return <aside className="side-tree closed">
    <button className="btn tonal" onClick={toggle} title={t('st_show')}><Icon name="tree" /></button></aside>
  const path = me && me !== id ? relation(me, id)?.path ?? [] : []
  return <aside className="side-tree card">
    <div className="st-head">
      <b><Icon name="tree" />{t('st_title')}</b>
      <span className="life">{t('st_hint')}</span>
      <button className="linkbtn" onClick={toggle}>{t('st_hide')}</button>
    </div>
    <FamilyTree people={people} view={{mainId: id, ancestry, progeny, from: me, fromIsMe: true, path}}
      onCardClick={pid => { const x = kin.P[pid]; if (x && pid !== id) navigate(href.person(x.x.slug)) }} />
  </aside>
}
