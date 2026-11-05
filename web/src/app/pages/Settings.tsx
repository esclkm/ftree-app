// «Настройки» (шестерёнка рядом с языком): кто я, сколько поколений показывать в дереве, язык. Всё хранится только в
// этом браузере — «я» в me.ts, поколения — те же ключи, что читает дерево (tree/TreeApp.tsx).
import {useEffect} from 'react'
import {Link, useLocation, useNavigate} from 'react-router'
import type {Lang} from '../../data/schema.gen'
import {Icon} from '../../components/Icon'
import {PersonSearch} from '../../components/PersonSearch'
import {tree} from '../../data'
import {useStoredNumber} from '../../hooks'
import {kin, personName} from '../../kin'
import {setMe, useMe} from '../../me'
import {GENERATIONS, TREE_ANC, TREE_DESC} from '../../tree/TreeApp'
import {useLang, useT} from '../i18n'
import {THEMES, useTheme, useTreeLight} from '../theme'
import {LANGS} from '../ui'
import {useLinks} from '../useIndex'

export function Settings() {
  const t = useT(), lang = useLang(), href = useLinks(), loc = useLocation(), navigate = useNavigate()
  const me = useMe(), people = tree()
  const [ancestry, setAncestry] = useStoredNumber(TREE_ANC)
  const [progeny, setProgeny] = useStoredNumber(TREE_DESC)
  const [theme, setTheme] = useTheme()
  const [treeLight, setTreeLight] = useTreeLight()
  useEffect(() => { document.title = `${t('set_title')} — ${t('site')}` }, [t])
  const switchTo = (l: Lang) => navigate(loc.pathname.replace(/^\/\w\w(?=\/|$)/, `/${l}`) + loc.search)
  const generations = (value: number, onChange: (v: number) => void) =>
    <select value={value} onChange={e => onChange(+e.target.value)}>
      {GENERATIONS.map(n => <option key={n} value={n}>{n || t('set_all')}</option>)}
    </select>

  return <div className="settings" key={lang}>
    <h1 className="page-title">{t('set_title')}</h1>
    <section className="card">
      <h2><Icon name="person" />{t('set_me')}</h2>
      <p className="life">{t('set_me_hint')}</p>
      {me && kin.P[me] && <p className="set-me">
        <Link to={href.person(kin.P[me].x.slug)}><b>{personName(me)}</b></Link>{' '}
        <button className="linkbtn" onClick={() => setMe(null)}>{t('kin_not_me')}</button>
      </p>}
      {people && <PersonSearch people={people} placeholder={t(me ? 'set_me_change' : 'set_me_find')} onPick={setMe} />}
    </section>
    <section className="card">
      <h2><Icon name="tree" />{t('nav_tree')}</h2>
      <label className="set-row">{t('set_anc')} {generations(ancestry, setAncestry)}</label>
      <label className="set-row">{t('set_desc')} {generations(progeny, setProgeny)}</label>
    </section>
    <section className="card">
      <h2>{t('set_lang')}</h2>
      <select aria-label="Language" value={lang} onChange={e => switchTo(e.target.value as Lang)}>
        {LANGS.map(c => <option key={c} value={c}>{c.toUpperCase()}</option>)}
      </select>
    </section>
    <section className="card">
      <h2>{t('set_theme')}</h2>
      <select aria-label={t('set_theme')} value={theme} onChange={e => setTheme(e.target.value as typeof theme)}>
        {THEMES.map(v => <option key={v} value={v}>{t(`set_theme_${v}`)}</option>)}
      </select>
      <label className="set-check"><input type="checkbox" checked={treeLight} onChange={e => setTreeLight(e.target.checked)} /> {t('set_tree_light')}</label>
    </section>
    <p className="life">{t('set_saved')}</p>
  </div>
}
