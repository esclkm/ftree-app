// Дома — места, где жила семья (карточка места с type: house, cards/houses.py). Кто жил и когда — по событиям
// «место жительства»: на странице дома — полосы по годам на одной шкале, у человека — его дома по порядку, в разделе
// «Хроника» — вкладка «Дома» со списком по городам.
import {Link} from 'react-router'
import type {GDate, PersonFile, PlaceFile} from '../data/schema.gen'
import {Icon} from '../components/Icon'
import {matchesName} from '../nameSearch'
import {dateIn, nameIn, useLang, useT} from './i18n'
import {PersonLink} from './pages/PersonPage'
import {Pin} from './notes/Pin'
import {type IndexPlace, type Lookup, useLinks} from './useIndex'

/** Годы даты: «FROM 1956 TO 2000» → [1956, 2000], «ABT 1985» → [1985, 1985]; без года — null */
export function yearsOf(d?: GDate): [number, number] | null {
  const ys = (d?.value.match(/\d{4}/g) ?? []).map(Number)
  return ys.length ? [Math.min(...ys), Math.max(...ys)] : null
}

/** Как рисовать годы на шкале: «с 1957» (FROM без TO) — от начала и растворяется вправо, конец неизвестен; «до 1943»
 * (BEF) — растворяется влево; «между 1960 и 1979» (BET) — бледно: когда-то в эти годы, а не все годы подряд */
function shape(d: GDate, lo: number, hi: number): {a: number; b: number; cls?: string} | null {
  const ys = yearsOf(d)
  if (!ys) return null
  const v = d.value
  if (/^FROM \d{4}(-\d\d)*$/.test(v) || v.startsWith('AFT')) return {a: ys[0], b: hi - 1, cls: 'open'}
  if (v.startsWith('BEF') || v.startsWith('TO')) return {a: lo, b: ys[1], cls: 'before'}
  if (v.startsWith('BET')) return {a: ys[0], b: ys[1], cls: 'window'}
  return {a: ys[0], b: ys[1], cls: ys[0] === ys[1] ? 'dot' : undefined}
}

/** «1956–2010», «1985», «с 1956», «до 1943» (t — надписи: yr_since, yr_until) */
export function span(a: number | undefined, b: number | undefined, t: (k: string) => string) {
  if (a === undefined) return b === undefined ? '' : `${t('yr_until')} ${b}`
  return b === undefined ? `${t('yr_since')} ${a}` : b === a ? `${a}` : `${a}–${b}`
}

/** Название дома без города впереди: под заголовком «Гродно» — «Луговая», а не «Гродно — Луговая» */
export function houseName(h: IndexPlace, ix: Lookup, lang: ReturnType<typeof useLang>) {
  const name = nameIn(h.names, lang), seen = new Set<string>()
  // «Минск — Садовая» внутри «Минск — Заречье»: город впереди может быть у любого места выше
  for (let x = h.parent ? ix.places.get(h.parent) : undefined; x && !seen.has(x.id); x = x.parent ? ix.places.get(x.parent) : undefined) {
    seen.add(x.id)
    const pre = `${nameIn(x.names, lang).split(' — ')[0]} — `
    if (name.startsWith(pre)) return name.slice(pre.length)
  }
  return name
}

/** Места выше дома по цепочке parent: район, город, область */
function placesAbove(h: IndexPlace, ix: Lookup): IndexPlace[] {
  const out: IndexPlace[] = [], seen = new Set<string>()
  for (let x = h.parent ? ix.places.get(h.parent) : undefined; x && !seen.has(x.id); x = x.parent ? ix.places.get(x.parent) : undefined) { seen.add(x.id); out.push(x) }
  return out
}

const SETTLEMENT = new Set(['city', 'town', 'village', 'locality'])

/** Город или деревня дома: ближайшее место выше, которое населённый пункт (не район города, не другой дом) */
export function cityOf(h: IndexPlace, ix: Lookup): IndexPlace | undefined {
  const seen = new Set<string>()
  let first: IndexPlace | undefined
  for (let x = h.parent ? ix.places.get(h.parent) : undefined; x && !seen.has(x.id); x = x.parent ? ix.places.get(x.parent) : undefined) {
    seen.add(x.id); first ??= x
    if (SETTLEMENT.has(x.type ?? '')) return x
  }
  return first
}

/** Значки под названием дома: что за жильё, когда построен, когда его не стало */
export function HouseChips({pl}: {pl: PlaceFile}) {
  const t = useT(), lang = useLang(), h = pl.house
  if (!h) return null
  return <div className="chips house-chips">
    <span className="chip"><Icon name="home" /><b>{t(h.kind ? `house_kind_${h.kind}` : 'map_tab_houses')}</b></span>
    {h.built && <span className="chip">{t('house_built')} <b>{dateIn(h.built, lang)}</b></span>}
    {(h.from ?? h.to) !== undefined && <span className="chip">{t('house_residents')} <b>{span(h.from, h.to, t)}</b></span>}
    {h.gone && <span className="chip">{t('house_gone')} <b>{dateIn(h.gone, lang)}</b></span>}
  </div>
}

/** «Кто жил в доме»: строка на человека, полосы его лет на общей шкале — от первого года до последнего (и стройки/сноса) */
export function HouseResidents({pl, ix}: {pl: PlaceFile; ix: Lookup}) {
  const t = useT(), lang = useLang()
  const rows = new Map<string, NonNullable<PlaceFile['residents']>>()
  for (const r of pl.residents ?? []) rows.set(r.person, [...(rows.get(r.person) ?? []), r])
  if (!rows.size) return null
  const all = (pl.residents ?? []).flatMap(r => yearsOf(r.date) ?? [])
  for (const d of [pl.house?.built, pl.house?.gone]) all.push(...(yearsOf(d) ?? []))
  const lo = all.length ? Math.floor(Math.min(...all) / 10) * 10 : 0
  const hi = all.length ? Math.max(Math.ceil((Math.max(...all) + 1) / 10) * 10, lo + 10) : 0
  const x = (y: number) => `${((y - lo) / (hi - lo)) * 100}%`
  const w = (a: number, b: number) => `${Math.max(((b + 1 - a) / (hi - lo)) * 100, 1.2)}%`
  const ticks = all.length ? Array.from({length: Math.floor((hi - lo) / 10) + 1}, (_, i) => lo + i * 10)
    .filter((_, i, a) => a.length <= 9 || i % 2 === 0) : []
  return <section className="card house-people" data-note-where={t('nw_house')}>
    <h2><Icon name="fam" />{t('house_people')} <span className="count">{rows.size}</span></h2>
    {ticks.length > 0 && <div className="hp-axis">{ticks.map(y => <span key={y} style={{left: x(y)}}>{y}</span>)}</div>}
    <ul className="plain hp-rows">{[...rows].map(([pid, rs]) => {
      const text = rs.map(r => r.date ? dateIn(r.date, lang) : t('house_no_date')).join('; ')
      return <li key={pid}>
        <div className="hp-who"><PersonLink id={pid} ix={ix} /> <span className="life">— {text}{rs.some(r => r.what === 'pp_born') ? ` · ${t('pp_born')}` : ''}</span>
          <Pin kind="stay" where={t('nw_house_calc')} text={`${ix.people.get(pid)?.names.ru ?? pid} — ${text}`} /></div>
        {all.length > 0 && <div className="hp-track">{rs.flatMap((r, i) => {
          const sh = r.date && shape(r.date, lo, hi)
          return sh ? [<i key={i} className={sh.cls} style={{left: x(sh.a), width: w(sh.a, sh.b)}} title={text} />] : []
        })}</div>}
      </li>
    })}</ul>
  </section>
}

/** У человека: дома, где он жил, по порядку */
export function Homes({p, ix}: {p: PersonFile; ix: Lookup}) {
  const href = useLinks()
  const t = useT(), lang = useLang()
  const homes = p.homes ?? []
  if (!homes.length) return null
  return <section className="card" data-note-where={t('nw_homes')}>
    <h2><Icon name="home" />{t('person_homes')}</h2>
    <ul className="timeline">{homes.map((h, i) => {
      const pl = ix.places.get(h.place), city = pl && cityOf(pl, ix)
      return <li key={i}>
        <span className="date">{h.date ? dateIn(h.date, lang) : '—'}</span>
        <span>{pl ? <Link to={href.place(pl.slug)}>{houseName(pl, ix, lang)}</Link> : h.place}
          {city && <span className="life"> · {nameIn(city.names, lang)}</span>}
          {pl?.house?.kind && <span className="life"> · {t(`house_kind_${pl.house.kind}`)}</span>}
          {h.what === 'pp_born' && <span className="life"> · {t(p.sex === 'M' ? 'born_m' : 'born_f')}</span>}</span>
      </li>
    })}</ul>
  </section>
}

/** Вкладка «Дома»: дома по городам, каждый — ссылка на страницу дома */
export function HousesList({ix, words = []}: {ix: Lookup; words?: string[]}) {
  const href = useLinks()
  const t = useT(), lang = useLang()
  const all = ix.index.places.filter(p => p.type === 'house')
  // поиск: по названию дома и всех мест выше (улица, район, город)
  const houses = words.length ? all.filter(h => matchesName([...Object.values(h.names), ...placesAbove(h, ix).flatMap(x => Object.values(x.names))], words)) : all
  const groups = new Map<string, IndexPlace[]>()
  for (const h of houses) { const c = cityOf(h, ix)?.id ?? ''; groups.set(c, [...(groups.get(c) ?? []), h]) }
  const order = [...groups].sort(([a], [b]) => (a ? nameIn(ix.places.get(a)!.names, lang) : '~').localeCompare(b ? nameIn(ix.places.get(b)!.names, lang) : '~'))
  return <div className="houses-list">
    <p className="note">{t('houses_intro')}</p>
    {!houses.length && <p className="life">{t(all.length ? 'search_none' : 'houses_none')}</p>}
    {order.map(([cid, hs]) => {
      const city = ix.places.get(cid)
      hs.sort((a, b) => (a.house?.from ?? a.house?.to ?? 9999) - (b.house?.from ?? b.house?.to ?? 9999) || houseName(a, ix, lang).localeCompare(houseName(b, ix, lang)))
      return <div key={cid} className="houses-city">
        <h3>{city ? <Link to={href.place(city.slug)}>{nameIn(city.names, lang)}</Link> : '—'}</h3>
        <ul className="plain">{hs.map(h => {
          return <li key={h.id}>
            <Link className="house-row" to={href.place(h.slug)}>
              <Icon name="home" />
              <span className="house-name">{houseName(h, ix, lang)}</span>
              <span className="life">{[h.house?.kind ? t(`house_kind_${h.house.kind}`) : '', span(h.house?.from, h.house?.to, t),
                h.house?.residents ? `${t('house_residents')}: ${h.house.residents}` : ''].filter(Boolean).join(' · ')}</span>
            </Link>
          </li>
        })}</ul>
      </div>
    })}
  </div>
}
