// Кружки людей, связанных с местом: до трёх лиц (портрет или инициалы цвета дерева), дальше «+N»; при наведении — кто это.
import {nameIn, useLang, useT} from './i18n'
import type {Lookup} from './useIndex'

const TIP_MAX = 12

export function Faces({ids, ix, max = 3}: {ids: string[]; ix: Lookup; max?: number}) {
  const t = useT(), lang = useLang()
  const folk = ids.flatMap(id => (ix.people.has(id) ? [ix.people.get(id)!] : []))
  if (!folk.length) return null
  const names = folk.map(p => `${nameIn(p.names, lang)}${p.life ? ` ${p.life}` : ''}`)
  const rest = folk.length - max
  return <span className="faces" tabIndex={0} title={names.join("\n")} aria-label={t('gal_folk', folk.length)}>
    {folk.slice(0, max).map(p => p.avatar
      ? <img key={p.id} className="face" src={p.avatar} alt="" loading="lazy" />
      : <span key={p.id} className={`face ph c${p.color ?? 0}`}>{p.initials ? nameIn(p.initials, lang) : '?'}</span>)}
    {rest > 0 && <span className="face more">+{rest}</span>}
    <span className="faces-tip" role="tooltip"><b>{t('gal_folk', folk.length)}</b>
      {names.slice(0, TIP_MAX).map(n => <span key={n}>{n}</span>)}
      {names.length > TIP_MAX && <span>{t('gal_folk_more', names.length - TIP_MAX)}</span>}</span>
  </span>
}
