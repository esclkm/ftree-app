// Карта мест: все места с координатами; размер точки — сколько людей связано с местом. Нажатие — панель с людьми и
// фото этого места. Адрес /map#<slug> открывает место сразу (как на нынешней карте). Дома — не здесь, а во вкладке
// «Дома» раздела «Хроника» (Gallery.tsx). Поле «Найти место» сверху — список мест по названию на любом языке; выбор открывает место.
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import 'leaflet.markercluster'
import 'leaflet.markercluster/dist/MarkerCluster.css'
import {useEffect, useMemo, useRef, useState} from 'react'
import {matchesName, nameRank, queryWords} from '../../nameSearch'
import {Link, useLocation, useNavigate} from 'react-router'
import {Icon} from '../../components/Icon'
import {usePlaceQuery} from '../api'
import {nameIn, useLang, useT} from '../i18n'
import {PhotoStrip} from '../PlacePhotos'
import {WhoWhat} from '../PlaceParts'
import {type IndexPlace, type Lookup, useIndex, useLinks} from '../useIndex'
import {PersonLink} from './PersonPage'

export function MapPage() {
  const t = useT(), lang = useLang(), {ix} = useIndex(), loc = useLocation(), navigate = useNavigate()
  const box = useRef<HTMLDivElement>(null), markers = useRef(new Map<string, L.CircleMarker>()), map = useRef<L.Map | null>(null)
  const cluster = useRef<L.MarkerClusterGroup | null>(null)
  const selected = ix?.placeBySlug.get(decodeURIComponent(loc.hash.slice(1)))
  useEffect(() => { document.title = `${t('nav_map')} — ${t('site')}` }, [t])
  useEffect(() => {
    if (!box.current || !ix) return
    const m = L.map(box.current)
    // мир (256 точек в высоту на первом приближении) не короче окна — без серых полос сверху и снизу на телефоне
    m.setMinZoom(Math.max(0, Math.ceil(Math.log2(box.current.clientHeight / 256))))
    // адрес сайта картинкам карты: без него OpenStreetMap отвечает «Access blocked»
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 18, attribution: '&copy; OpenStreetMap', referrerPolicy: 'strict-origin'}).addTo(m)
    // дома — только во вкладке «Дома» раздела «Хроника», на общей карте их нет
    const pts = ix.index.places.filter(p => p.type !== 'house' && p.lat !== undefined && p.lng !== undefined).map(p => ({p, lat: p.lat!, lng: p.lng!}))
    // близкие точки — одной группой с числом мест (деревни Брестчины в мелком масштабе сливались в пятно); ближе — распадаются
    const groups = L.markerClusterGroup({showCoverageOnHover: false, maxClusterRadius: 40, spiderfyOnMaxZoom: true,
      iconCreateFunction: c => { const n = c.getChildCount(), s = n < 10 ? 30 : n < 50 ? 38 : 46
        return L.divIcon({html: `<span>${n}</span>`, className: 'map-cluster', iconSize: [s, s]}) }})
    for (const {p, lat, lng} of pts) {
      const r = 6 + Math.min(p.people, 20) / 2
      const mk = L.circleMarker([lat, lng], {radius: r, color: '#fff', weight: 2, fillColor: '#8c4f2b', fillOpacity: .85})
        .bindTooltip(nameIn(p.names, lang)).on('click', () => navigate({hash: p.slug}, {replace: true}))
      markers.current.set(p.id, mk)
      groups.addLayer(mk)
    }
    if (pts.length) m.fitBounds(L.latLngBounds(pts.map(x => [x.lat, x.lng] as L.LatLngTuple)), {padding: [30, 30], maxZoom: 13})
    else m.setView([53.9, 27.56], 5)
    m.addLayer(groups)  // после масштаба: без него группы не считаются и точек не видно
    cluster.current = groups
    map.current = m
    return () => { m.remove(); markers.current.clear(); map.current = null; cluster.current = null }
  }, [ix, lang, navigate])
  useEffect(() => {  // выбранное место — другим цветом и в центре; спрятано в группе — группа раскрывается
    markers.current.forEach((mk, id) => mk.setStyle({fillColor: id === selected?.id ? '#d6336c' : '#8c4f2b'}))
    const mk = selected && markers.current.get(selected.id), m = map.current
    if (!mk || !m) return
    const center = () => m.setView(mk.getLatLng(), Math.max(m.getZoom(), 7))
    if (cluster.current) cluster.current.zoomToShowLayer(mk, center)
    else center()
  }, [selected])
  const panel = selected && ix && <PlacePanel id={selected.id} ix={ix} onClose={() => navigate({hash: ''}, {replace: true})} />
  return <div className="map-page"><div id="map" ref={box} />
    {ix && <MapSearch ix={ix} onPick={p => navigate({hash: p.slug}, {replace: true})} />}{panel}</div>
}

/** «Найти место»: точки карты (без домов), подходящие по названию; сверху — те, что начинаются со слова, потом — где больше людей */
function MapSearch({ix, onPick}: {ix: Lookup; onPick: (p: IndexPlace) => void}) {
  const t = useT(), lang = useLang()
  const [q, setQ] = useState(''), [cur, setCur] = useState(0)
  const found = useMemo(() => {
    const words = queryWords(q)
    if (!words.length) return []
    return ix.index.places.filter(p => p.type !== 'house' && p.lat != null && p.lng != null && matchesName(Object.values(p.names), words))
      .map(p => ({p, r: nameRank(Object.values(p.names), words)})).sort((x, y) => x.r - y.r || y.p.people - x.p.people).slice(0, 10).map(x => x.p)
  }, [ix, q])
  const pick = (p: IndexPlace) => { onPick(p); setQ(''); setCur(0) }
  return <div className="map-search">
    <div className="search"><Icon name="search" />
      <input type="search" placeholder={t('map_search')} value={q} autoComplete="off" enterKeyHint="search"
        role="combobox" aria-expanded={found.length > 0} aria-controls="map-found"
        onChange={e => { setQ(e.target.value); setCur(0) }}
        onKeyDown={e => {
          if (e.key === 'ArrowDown' && found.length) { setCur(Math.min(cur + 1, found.length - 1)); e.preventDefault() }
          else if (e.key === 'ArrowUp' && found.length) { setCur(Math.max(cur - 1, 0)); e.preventDefault() }
          else if (e.key === 'Enter' && found[cur]) { pick(found[cur]); e.currentTarget.blur(); e.preventDefault() }
          else if (e.key === 'Escape') setQ('')
        }} /></div>
    {q.trim() && <ul className="map-found" id="map-found" role="listbox">
      {!found.length && <li className="life">{t('search_none')}</li>}
      {found.map((p, i) => { const up = p.parent ? ix.places.get(p.parent) : undefined
        return <li key={p.id} role="option" aria-selected={i === cur} className={i === cur ? 'cur' : undefined} onMouseEnter={() => setCur(i)}>
          <button onMouseDown={e => e.preventDefault()} onClick={() => pick(p)}><Icon name="place" />{nameIn(p.names, lang)}
            {up && <span className="life"> · {nameIn(up.names, lang)}</span>}</button></li> })}
    </ul>}
  </div>
}

function PlacePanel({id, ix, onClose}: {id: string; ix: Lookup; onClose: () => void}) {
  const href = useLinks()
  const t = useT(), lang = useLang()
  const pl = ix.places.get(id)!
  const q = usePlaceQuery({id, v: ix.index.built})
  const who = q.data?.who ?? []
  return <aside className="card map-panel">
    <button className="icon-btn close" aria-label="×" onClick={onClose}>×</button>
    <h2><Icon name="place" /><Link to={href.place(pl.slug)}>{nameIn(pl.names, lang)}</Link></h2>
    {who.length > 0 && <ul className="plain">{who.slice(0, 12).map(w =>
      <li key={w.person}><PersonLink id={w.person} ix={ix} /><WhoWhat w={w} /></li>)}
      {who.length > 12 && <li className="life">… {t('map_people')}: {who.length}</li>}</ul>}
    <PhotoStrip placeId={id} />
    <p><Link className="btn tonal" to={href.place(pl.slug)}><Icon name="place" />{t('gal_place_page')}</Link></p>
  </aside>
}
