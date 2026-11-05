// Дерево и «кем приходится» — тот же код, что у нынешних страниц (src/tree, src/map, src/kin); данные — из
// data/index.json (main.tsx передаёт их через provide).
// Язык они берут при отрисовке: сменили язык — рисуем заново (key={lang}).
import 'family-chart/styles/family-chart.css'
import {useEffect} from 'react'
import {KinLine} from '../../components/KinLine'
import {tree} from '../../data'
import {kin} from '../../kin'
import {TreeApp} from '../../tree/TreeApp'
import {useLang, useT} from '../i18n'
import {useLinks} from '../useIndex'

export function TreePage() {
  const lang = useLang(), t = useT(), people = tree()
  useEffect(() => { document.title = `${t('nav_tree')} — ${t('site')}` }, [t])
  return <div id="tree-app" key={lang}>{people && <TreeApp people={people} />}</div>
}

/** «Кем вам приходится» на странице человека; ссылки — на страницы приложения */
export function Kin({id}: {id: string}) {
  const href = useLinks()
  const lang = useLang()
  if (!kin.P[id]) return null
  return <div id="kin" key={lang}><KinLine personId={id} linkTo={pid => href.person(kin.P[pid].x.slug)} /></div>
}
