// Поиск человека: имя в любой записи («Василий» и «Vasiliy», «Ясенев» и «Jasieniew»), в списке — фото и годы.
// Стрелки — выбрать, Enter — открыть, Esc — закрыть.
import {useMemo, useState} from 'react'
import type {TreePerson} from '../data'
import {altName, nameOf} from '../i18n'
import {Icon} from './Icon'
import {matchesName, nameRank, queryWords} from '../nameSearch'

const MAX = 8

export function PersonSearch({people, placeholder, onPick, autoFocus}: {
  people: TreePerson[]; placeholder: string; onPick: (id: string) => void; autoFocus?: boolean
}) {
  const [text, setText] = useState('')
  const [cur, setCur] = useState(0)
  // одна строка для поиска на человека: все записи имени и годы
  // слова запроса — в любом порядке («Ясенев Иван» = «Иван Ясенев»), см. nameSearch.ts
  const index = useMemo(() => people.map(p => ({p, names: [p.data.ru, p.data.en, p.data.pl, p.data.es].filter(Boolean) as string[]})), [people])
  const words = queryWords(text)
  const found = index.filter(x => matchesName([...x.names, x.p.data.life], words))
    .map(x => ({p: x.p, r: nameRank(x.names, words)})).sort((a, b) => a.r - b.r)  // начало имени или фамилии — выше
    .slice(0, MAX).map(x => x.p)
  const pick = (p: TreePerson) => { setText(''); setCur(0); onPick(p.id) }

  return (
    <div className="psearch">
      <Icon name="person" />
      <input value={text} placeholder={placeholder} autoFocus={autoFocus} autoComplete="off"
        onChange={e => { setText(e.target.value); setCur(0) }}
        onKeyDown={e => {
          if (e.key === 'ArrowDown') { setCur(Math.min(cur + 1, found.length - 1)); e.preventDefault() }
          if (e.key === 'ArrowUp') { setCur(Math.max(cur - 1, 0)); e.preventDefault() }
          if (e.key === 'Enter' && found[cur]) pick(found[cur])
          if (e.key === 'Escape') setText('')
        }} />
      {found.length > 0 && (
        <ul className="psearch-list">
          {found.map((p, i) => (
            <li key={p.id} className={i === cur ? 'cur' : ''} onMouseDown={e => { e.preventDefault(); pick(p) }} onMouseEnter={() => setCur(i)}>
              {p.data.avatar ? <img src={p.data.avatar} alt="" /> : <span className={'ph c' + p.data.c}>{p.data.ini ? nameOf(p.data.ini) : <Icon name="person" />}</span>}
              <span className="who">
                <b>{nameOf(p.data)}</b>
                <small>{[p.data.life, altName(p.data) !== nameOf(p.data) ? altName(p.data) : ''].filter(Boolean).join(' · ')}</small>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
