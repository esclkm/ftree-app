// Фото места: снятые по точному адресу (дом, вуз — пометка addr в галерее) и альбом места. Для страницы места и карты.
import {Link} from 'react-router'
import type {GalleryFile} from '../data/schema.gen'
import {Icon} from '../components/Icon'
import {useGalleryQuery} from './api'
import {trIn, useLang, useT} from './i18n'
import {useLightbox} from './Lightbox'
import {shotOf} from './pages/Gallery'
import {eraSlices, PhotoTimeline} from './PhotoTimeline'
import {useIndex, useLinks} from './useIndex'

type Photo = GalleryFile['albums'][number]['photos'][number]

export function usePlacePhotos(placeId?: string) {
  const {ix} = useIndex()
  const q = useGalleryQuery(ix ? ix.index.built : '', {skip: !ix || !placeId})
  const album = q.data?.albums.find(a => a.place === placeId)
  const addr: Photo[] = q.data?.albums.flatMap(a => a.photos.filter(p => p.addr === placeId)) ?? []
  // «≈ не наше»: снимков нашей деревни нет — самые похожие рядом (снимок лежит в альбоме «Похожие деревни»)
  const like: Photo[] = q.data?.albums.flatMap(a => a.photos.filter(p => p.like?.ours_place === placeId)) ?? []
  return {album, addr, like}
}

const PER_SLICE = 4  // на странице места — по 4 снимка на срез, остальные — в альбоме

/** Страница места: снимки этого адреса и альбом места с похожими деревнями рядом — лентой по срезам лет */
export function PlacePhotos({placeId}: {placeId: string}) {
  const href = useLinks()
  const t = useT(), lang = useLang(), {album, addr, like} = usePlacePhotos(placeId)
  const photos = [...(album?.photos ?? []), ...like]
  const more = eraSlices(photos, lang, '', String).some(s => s.photos.length > PER_SLICE)
  return <>
    {addr.length > 0 && <section className="card flat"><h2><Icon name="pics" />{t('gal_place_photos')} <span className="count">{addr.length}</span></h2>
      <PhotoTimeline photos={addr} where={t('nw_addr_photos')} /></section>}
    {photos.length > 0 && <section className="card flat"><h2><Icon name="pics" />{t('gal_place_photos')} <span className="count">{photos.length}</span></h2>
      <PhotoTimeline photos={photos} where={album ? t('nw_place_album', album.names.ru) : t('nw_photo')} perSlice={PER_SLICE} />
      {album && more && <p><Link className="btn tonal" to={href.album(album.slug)}><Icon name="pics" />{t('gal_all')}</Link></p>}
    </section>}
  </>
}

/** Полоска превью для панели на карте */
export function PhotoStrip({placeId, limit = 8}: {placeId: string; limit?: number}) {
  const href = useLinks()
  const t = useT(), lang = useLang(), open = useLightbox(), {album, addr} = usePlacePhotos(placeId)
  const photos = [...addr, ...(album?.photos ?? [])]
  if (!photos.length) return null
  const shots = photos.map(p => shotOf(trIn(p, lang)))
  return <>
    <div className="strip-head">{t('gal_place_photos')} <span className="count">{photos.length}</span>
      {album && <> · <Link to={href.album(album.slug)}>{t('gal_all')}</Link></>}</div>
    <div className="strip">{photos.slice(0, limit).map((p, i) =>
      <a key={p.url} href={p.url} onClick={e => { e.preventDefault(); open(shots, i) }}><img loading="lazy" src={p.thumb} alt="" /></a>)}</div>
  </>
}
