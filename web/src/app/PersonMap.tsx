// Карта мест человека: где родился, жил, работал, умер (те же места, что в «Местах и эпохах»). Нажатие — страница места.
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import {useEffect, useRef} from 'react'
import {useNavigate} from 'react-router'
import {nameIn, useLang} from './i18n'
import {type Lookup, useLinks} from './useIndex'

export function PersonMap({placeIds, ix}: {placeIds: string[]; ix: Lookup}) {
  const href = useLinks()
  const box = useRef<HTMLDivElement>(null), lang = useLang(), navigate = useNavigate()
  const pts = [...new Set(placeIds)].flatMap(id => {
    const p = ix.places.get(id)
    return p && p.lat !== undefined && p.lng !== undefined ? [{...p, lat: p.lat, lng: p.lng}] : []
  })
  const key = pts.map(p => p.id).join()
  useEffect(() => {
    if (!box.current || !pts.length) return
    const map = L.map(box.current, {scrollWheelZoom: false})
    // адрес сайта картинкам карты — как на прежней карте: без него OpenStreetMap отвечает «Access blocked»
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 18, attribution: '&copy; OpenStreetMap', referrerPolicy: 'strict-origin'}).addTo(map)
    for (const p of pts) {
      L.circleMarker([p.lat, p.lng], {radius: 8, color: '#fff', weight: 2, fillColor: '#8c4f2b', fillOpacity: .9})
        .bindTooltip(nameIn(p.names, lang)).on('click', () => navigate(href.place(p.slug))).addTo(map)
    }
    if (pts.length === 1) map.setView([pts[0].lat, pts[0].lng], 9)
    else map.fitBounds(L.latLngBounds(pts.map(p => [p.lat, p.lng] as L.LatLngTuple)), {padding: [30, 30], maxZoom: 10})
    return () => { map.remove() }
  }, [key, lang])  // eslint-disable-line react-hooks/exhaustive-deps
  return pts.length ? <div className="person-map" ref={box} /> : null
}
