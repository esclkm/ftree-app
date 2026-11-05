// Разбор найденных фото (/<язык>/review): все снимки галереи — иллюстрации мест и времени, найденные в сети, — по одному,
// крупно, с подписью и тем, откуда взят. Клавиши 1–6 — приговор (VERDICTS), он сразу ложится в заметки и открывается
// следующий снимок; ← → — листать; Enter — дописать словами (курсор в заметку в панели). Только в режиме заметок.
import {type ChangeEvent, useCallback, useEffect, useMemo, useState} from 'react'
import {Link} from 'react-router'
import type {GalleryFile, Lang} from '../../data/schema.gen'
import {Icon} from '../../components/Icon'
import {useGalleryQuery} from '../api'
import {nameIn, translate, trIn, useLang, useT} from '../i18n'
import {Status} from '../Layout'
import {Md} from '../Md'
import {useAppSelector} from '../store'
import {type Lookup, useIndex, useLinks} from '../useIndex'
import {type NewNote, type Note, photoName, type Subject, type Verdict, VERDICTS} from './model'
import {plainMd, VERDICT_ICON} from './Pin'
import {useNotesAvailable} from './scope'
import {useNotes} from './useNotes'

type Photo = GalleryFile['albums'][number]['photos'][number]
interface Shot { photo: Photo; subject: Subject }
const AT = 'review-at'  // на каком снимке остановились — адрес снимка в localStorage

/** Все снимки галереи по разу; «чей» снимок — его альбом */
function shotsOf(lang: Lang, gallery?: GalleryFile): Shot[] {
  const seen = new Set<string>(), out: Shot[] = []
  for (const a of gallery?.albums ?? []) for (const photo of a.photos) {
    if (seen.has(photo.url)) continue
    seen.add(photo.url)
    out.push({photo, subject: {type: 'album', id: a.slug, name: translate(lang, 'nw_album', a.names.ru), path: `/gallery/${a.slug}`}})
  }
  return out
}

const verdictIn = (items: Note[], s: Shot): Verdict | undefined =>
  items.find(n => n.photo?.url === s.photo.url && n.subject.id === s.subject.id)?.verdict

const noteOf = (s: Shot, verdict: Verdict | undefined, quiet: boolean, lang: Lang): NewNote => ({
  subject: s.subject, kind: 'photo', where: translate(lang, 'nr_short'), verdict, quiet, lang,
  photo: {url: s.photo.url, thumb: s.photo.thumb, caption: plainMd([s.photo.year_txt, s.photo.desc].filter(Boolean).join(' · ')),
    source: s.photo.source ? plainMd(s.photo.source) : undefined, link: s.photo.link},
})

/** Очередь снимков: текущий, листание, приговор с переходом к следующему, «дописать словами» */
function useQueue(all: Shot[], items: Note[], onlyNew: boolean) {
  const notes = useNotes(), lang = useLang()
  const [at, setAt] = useState(() => localStorage.getItem(AT) ?? '')
  const list = useMemo(() => onlyNew ? all.filter(s => !verdictIn(items, s) || s.photo.url === at) : all, [all, items, onlyNew, at])
  const i = Math.max(0, list.findIndex(s => s.photo.url === at))
  const cur = list[i] as Shot | undefined
  const goTo = useCallback((s?: Shot) => { if (s) { setAt(s.photo.url); localStorage.setItem(AT, s.photo.url) } }, [])
  const prev = useCallback(() => goTo(list[i - 1]), [goTo, list, i])
  const next = useCallback(() => goTo(list[i + 1]), [goTo, list, i])
  const judge = useCallback((v: Verdict) => {
    if (!cur) return
    notes.add(noteOf(cur, v, true, lang))
    goTo(list[i + 1] ?? list[i - 1])  // «только без оценки»: оценённый уходит из списка — идём к соседу
  }, [cur, notes, goTo, list, i, lang])
  const write = useCallback(() => { if (cur) notes.add(noteOf(cur, verdictIn(items, cur), false, lang)) }, [cur, notes, items, lang])
  return {list, i, cur, prev, next, judge, write}
}

/** 1–6 — приговор, ← → — листать, Enter — дописать; в полях ввода клавиши — просто буквы */
function useKeys(q: ReturnType<typeof useQueue>) {
  const {judge, prev, next, write} = q
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.target as Element).closest('input, textarea, select') || e.metaKey || e.ctrlKey || e.altKey) return
      const n = Number(e.key)
      const act = n >= 1 && n <= VERDICTS.length ? () => judge(VERDICTS[n - 1])
        : e.key === 'ArrowRight' ? next : e.key === 'ArrowLeft' ? prev : e.key === 'Enter' ? write : null
      if (act) { e.preventDefault(); act() }
    }
    addEventListener('keydown', key)
    return () => removeEventListener('keydown', key)
  }, [judge, prev, next, write])
}

export function Review() {
  const available = useNotesAvailable(), t = useT(), lang = useLang()
  const {ix} = useIndex()
  const q = useGalleryQuery(ix ? ix.index.built : '', {skip: !ix})
  const items = useAppSelector(s => s.notes.items)
  const [onlyNew, setOnlyNew] = useState(true)
  const all = useMemo(() => shotsOf(lang, q.data), [lang, q.data])
  const queue = useQueue(all, items, onlyNew)
  useKeys(queue)
  const toggleNew = useCallback((e: ChangeEvent<HTMLInputElement>) => setOnlyNew(e.target.checked), [])
  useEffect(() => { document.title = t('nr_short') }, [t])

  if (!available) return <Status state="not_found" />
  if (q.isError) return <Status state="error" />
  if (!q.data || !ix) return <Status state="loading" />
  const done = all.filter(s => verdictIn(items, s)).length
  return <section className="card review">
    <header className="review-head">
      <h1><Icon name="review" />{t('nr_title')}</h1>
      <span className="review-count">{t('nr_count', done, all.length)}</span>
      <label><input type="checkbox" checked={onlyNew} onChange={toggleNew} /> {t('nr_only_new')}</label>
    </header>
    {queue.cur
      ? <ShotView shot={queue.cur} given={verdictIn(items, queue.cur)} queue={queue} ix={ix} />
      : <p className="note">{t('nr_all_done')}</p>}
  </section>
}

function ShotView({shot, given, queue, ix}: {shot: Shot; given?: Verdict; queue: ReturnType<typeof useQueue>; ix: Lookup}) {
  const lang = useLang(), href = useLinks(), t = useT()
  const p = trIn(shot.photo, lang), {list, i} = queue  // подписи — переводом, если есть (как в галерее)
  const place = p.addr ? ix.places.get(p.addr) : undefined
  return <div className="review-body">
    <div className="review-img">
      <button type="button" className="icon-btn" aria-label={t('nr_prev')} onClick={queue.prev} disabled={i === 0}><Icon name="prev" /></button>
      <img src={p.url} alt="" />
      <button type="button" className="icon-btn" aria-label={t('nr_next')} onClick={queue.next} disabled={i >= list.length - 1}><Icon name="next" /></button>
    </div>
    <div className="review-info">
      <div className="review-pos">{i + 1} / {list.length}</div>
      <div className="chips">{p.year_txt && <span className="chip">{p.year_txt}</span>}{p.era && <span className="chip era">{nameIn(p.era, lang)}</span>}</div>
      {p.desc && <p className="cap"><Md text={p.desc} /></p>}
      <table className="kv"><tbody>
        <tr><th>{t('nr_album')}</th><td><Link to={href.at(shot.subject.path)}>{shot.subject.name}</Link></td></tr>
        {place && <tr><th>{t('nr_address')}</th><td><Link to={href.place(place.slug)}>{nameIn(place.names, lang)}</Link></td></tr>}
        {p.whose && <tr><th>{t('nr_whose')}</th><td><Md text={p.whose} /></td></tr>}
        {p.exact && <tr><th>{t('nr_exact')}</th><td><Md text={p.exact} /></td></tr>}
        {p.note && <tr><th>{t('nr_question')}</th><td><Md text={p.note} /></td></tr>}
        {(p.source || p.link) && <tr><th>{t('nr_from')}</th><td>{p.link
          ? <a href={p.link} target="_blank" rel="noreferrer noopener">{plainMd(p.source) || p.link}</a> : <Md text={p.source ?? ''} />}</td></tr>}
        <tr><th>{t('nr_file')}</th><td><code>{photoName(p.url)}</code></td></tr>
      </tbody></table>
      <div className="review-verdicts">
        {VERDICTS.map((v, k) => <JudgeButton key={v} v={v} n={k + 1} on={given === v} judge={queue.judge} />)}
        <button type="button" onClick={queue.write}><kbd>Enter</kbd><Icon name="note" />{t('nr_write')}</button>
      </div>
      <p className="note">{t('nr_keys')}</p>
    </div>
  </div>
}

function JudgeButton({v, n, on, judge}: {v: Verdict; n: number; on: boolean; judge: (v: Verdict) => void}) {
  const t = useT()
  const click = useCallback(() => judge(v), [judge, v])
  return <button type="button" className={`v-${v}${on ? ' on' : ''}`} onClick={click}>
    <kbd>{n}</kbd><Icon name={VERDICT_ICON[v]} />{t(`nv_${v}`)}</button>
}
