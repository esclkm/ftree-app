// Части страницы человека, которые приходят не из карточки, а из биографии и событий: биография по языкам,
// линия жизни, фото, «Места и эпохи».
import {useState} from 'react'
import {Link} from 'react-router'
import type {Lang, PersonFile} from '../../data/schema.gen'
import {Icon} from '../../components/Icon'
import {BioMd} from '../BioMd'
import {useLightbox} from '../Lightbox'
import {dateIn, nameIn, titleIn, useLang, useT} from '../i18n'
import {Md} from '../Md'
import {PersonMap} from '../PersonMap'
import {PhotoTimeline} from '../PhotoTimeline'
import {type Lookup, useLinks} from '../useIndex'
import {PhotoPin, Pin} from '../notes/Pin'

type Bio = NonNullable<PersonFile['biography']>

export function Biography({bio}: {bio: Bio}) {
  const t = useT(), lang = useLang()
  const langs = Object.keys(bio.texts) as Lang[]
  const [chosen, setChosen] = useState<Lang | null>(null)
  const shown: Lang = chosen ?? (bio.texts[lang] ? lang : 'ru')
  const text = bio.texts[shown]!
  return <section className="card prose bio" id="bio" data-note-where={shown !== 'ru' ? t('nw_bio_tr', shown.toUpperCase()) : t('nw_bio')}>
    <h2><Icon name="bio" />{t('biography')}
      {langs.length > 1 && <span className="bio-tabs">{langs.map(l =>
        <button key={l} className={l === shown ? 'on' : undefined} onClick={() => setChosen(l)}>{l.toUpperCase()}</button>)}</span>}
    </h2>
    {!chosen && lang !== 'ru' && !bio.texts[lang] && <p className="tr-note missing">{t('tr_missing')}</p>}
    {shown !== 'ru' && text.ai && <p className="tr-note">{t('tr_ai')}</p>}
    {shown !== 'ru' && text.stale && <p className="tr-note warn">{t('tr_stale')}</p>}
    <BioMd text={text.md} />
  </section>
}

type Row = Bio['lifeline'][number]

/** Строки линии жизни на языке страницы: из перевода, если в нём своя линия жизни, иначе русские. Дата — разобранная
 *  из русской строки: перевод повторяет таблицу строка в строку, а в нём дата словами. */
export function lifelineRows(bio: Bio, lang: Lang, part: 'lifeline' | 'memory' = 'lifeline'): {row: Row; date: Row['date']}[] {
  const ru = bio[part] ?? []
  const own = lang !== 'ru' ? bio.texts[lang]?.[part] : undefined
  const rows = own?.length ? own : ru
  return rows.map((row, i) => {
    const date = own?.length === ru.length ? ru[i].date : row.date
    // слова при дате («расч.», «осень») — из переведённой строки: «1918 (calc.)» → calc.
    const words = own?.length && date?.words ? row.when.match(/\(([^)]*)\)\s*$/)?.[1] : undefined
    return {row, date: words && date ? {...date, words} : date}
  })
}

/** «Линия жизни», а за ней — продолжением, после черты смерти — «Память»: что было после смерти (музей, книга,
 *  статьи), тем же списком, но тише. Только «Память» без линии жизни — тоже показываем. */
export function Lifeline({bio}: {bio: Bio}) {
  const t = useT(), lang = useLang()
  const life = lifelineRows(bio, lang, 'lifeline'), mem = lifelineRows(bio, lang, 'memory')
  if (!life.length && !mem.length) return null
  const items = (lines: typeof life, title: string) => lines.map(({row: r, date: d}, i) =>
    <li key={i}>
      <span className="date">{d && lang !== 'ru' ? dateIn(d, lang) : <Md text={r.when} />}
        {d?.os && <small className="os" title={t('os_style', d.os)}>({d.os})</small>}</span>
      <span><Md text={r.text} />
        {r.extra && <span className="tl-extra">{r.extra.map((x, j) => <span key={j}>{x.col && `${x.col}: `}<Md text={x.value} /></span>)}</span>}
        <Pin kind="lifeline" where={t('nw_row', title, i + 1)} text={[`${r.when} — ${r.text}`, ...(r.extra ?? []).map(x => `${x.col ? x.col + ': ' : ''}${x.value}`)].join('\n')} />
      </span>
    </li>)
  return <section className="card" data-note-where={t('nw_lifeline')}>
    <h2><Icon name="event" />{t('lifeline')}</h2>
    {life.length > 0 && <ul className="timeline">{items(life, t('nw_lifeline'))}</ul>}
    {mem.length > 0 && <div className="tl-after" data-note-where={t('nw_memory')}>
      <h3>{t('memory')}</h3>
      <ul className="timeline">{items(mem, t('nw_memory'))}</ul>
    </div>}
  </section>
}

/** «Открытые вопросы» — что ещё не знаем о человеке; свёрнуто, открывается по нажатию. Из перевода, если он есть. */
export function Questions({bio}: {bio: Bio}) {
  const t = useT(), lang = useLang()
  const md = (lang !== 'ru' ? bio.texts[lang]?.questions : undefined) ?? bio.questions
  if (!md) return null
  const count = md.split('\n').filter(l => /^\s*[-*]\s/.test(l) && !/✅|~~/.test(l)).length
  return <details className="card fold questions" data-note-where={t('nw_questions')}>
    <summary><h2><Icon name="source" />{t('open_questions')}{count > 0 && <span className="count">{count}</span>}</h2></summary>
    <div className="prose"><BioMd text={md} /></div>
  </details>
}

/** «Воспоминания» — сценки, которые кто-то помнит о человеке: название, кто вспоминает и откуда, рассказ. Из перевода —
 *  если там столько же сценок, иначе русские. */
export function Recollections({bio}: {bio: Bio}) {
  const t = useT(), lang = useLang()
  const ru = bio.recollections ?? []
  const own = lang !== 'ru' ? bio.texts[lang]?.recollections : undefined
  const items = own?.length === ru.length ? own : ru
  if (!items.length) return null
  return <section className="card recollections" data-note-where={t('nw_recollections')}>
    <h2><Icon name="bio" />{t('recollections')}</h2>
    {items.map((r, i) => <article key={i} className="recollection">
      <h3>{r.title}<Pin kind="about" where={`${t('nw_recollections')} › ${ru[i]?.title ?? r.title}`}
        text={[r.title, r.by ?? '', r.text].filter(Boolean).join('\n')} /></h3>
      {r.by && <div className="rec-by"><Md text={r.by} /></div>}
      <BioMd text={r.text} />
    </article>)}
  </section>
}

export function Photos({p}: {p: PersonFile}) {
  const t = useT(), lb = useLightbox()
  const shown = (p.media ?? []).filter(m => !m.private)
  if (shown.length < 2) return null  // одно фото — уже в шапке
  const shots = shown.map(m => ({src: m.url}))
  return <section className="card">
    <h2><Icon name="pics" />{t('photos')}</h2>
    <div className="gallery">{shown.map((m, i) =>
      <a key={m.url} href={m.url} className="pin-host" onClick={e => { e.preventDefault(); lb(shots, i) }}><img loading="lazy" src={m.url} alt="" />
        <PhotoPin photo={{url: m.url, family: true}} where={t('nw_media')} /></a>)}</div>
  </section>
}

/** «Документы» — паспорт, трудовая, метрики (2_transcripts/documents): плитка с первой страницей, нажатие — PDF,
 *  «Текст» — страница с описанием и расшифровкой. Закрытых здесь нет (их не выгружает сборка); документ живого — по паролю. */
export function Documents({p}: {p: PersonFile}) {
  const t = useT(), lang = useLang(), href = useLinks()
  const docs = p.documents ?? []
  if (!docs.length) return null
  return <section className="card" data-note-where={t('nw_docs')}>
    <h2><Icon name="texts" />{t('documents')} <span className="count">{docs.length}</span></h2>
    <div className="albums docs">{docs.map(d => {
      const cover = d.cover && !d.private ? <img loading="lazy" src={d.cover} alt="" /> : <span className="doc-blank"><Icon name="texts" /></span>
      return <div key={d.doc} className="album">
        {d.pdf ? <a href={d.pdf} target="_blank" rel="noopener">{cover}</a> : <Link to={href.doc(d.doc)}>{cover}</Link>}
        <div>
          <b>{t(`doc_kind_${d.kind}`)} · {d.years}</b>
          <span className="album-about">{titleIn(d, lang)}</span>
          <span>{d.pages ? t('doc_pages', d.pages) : ''}{d.private ? ` · ${t('doc_private')}` : ''}</span>
          <span className="doc-links">
            {d.pdf && <a href={d.pdf} target="_blank" rel="noopener"><Icon name="download" />{t('doc_pdf')}</a>}
            <Link to={href.doc(d.doc)}><Icon name="source" />{t('doc_text')}</Link>
          </span>
        </div>
      </div>
    })}</div>
  </section>
}

/** Портрет; нет фото — круг с инициалами того же цвета, что в дереве (у неизвестного — значок) */
export function Avatar({p, ix}: {p: PersonFile; ix: Lookup}) {
  const lang = useLang(), lb = useLightbox(), t = useT()
  const a = p.avatar && !p.avatar.private ? p.avatar : undefined
  if (a) return <a className="avatar pin-host" href={a.url} onClick={e => { e.preventDefault(); lb([{src: a.url}], 0) }}><img src={a.url} alt="" />
    <PhotoPin photo={{url: a.url, family: true}} where={t('nw_portrait')} /></a>
  const x = ix.people.get(p.id)
  return <span className={`avatar ph c${x?.color ?? 0}`}>{x?.initials ? nameIn(x.initials, lang) : <Icon name="person" />}</span>
}

export function Stays({p, ix}: {p: PersonFile; ix: Lookup}) {
  const href = useLinks()
  const t = useT(), lang = useLang()
  const ids = [p.born?.place, ...(p.stays ?? []).map(s => s.place), p.died?.place].filter((x): x is string => !!x)
  if (!p.stays?.length && !ids.length) return null
  return <section className="card" data-note-where={t('nw_stays')}>
    <h2><Icon name="place" />{t('places_eras')}</h2>
    <PersonMap placeIds={ids} ix={ix} />
    <ul className="timeline">{(p.stays ?? []).map((s, i) => {
      const pl = ix.places.get(s.place)
      return <li key={i}>
        <span className="date">{s.from}{s.to > s.from ? `–${s.to}` : ''}</span>
        <span>{t(s.event)} · {pl ? <Link to={href.place(pl.slug)}>{nameIn(pl.names, lang)}</Link> : null}
          {s.state && <> — {t('then')}: <b className="era">{nameIn(s.state, lang)}</b></>}
          <Pin kind="stay" where={t('nw_stays_calc')}
            text={`${s.from}${s.to > s.from ? `–${s.to}` : ''} · ${pl ? nameIn(pl.names, 'ru') : s.place}${s.state ? ` — тогда ${s.state.ru}` : ''}`} /></span>
      </li>
    })}</ul>
  </section>
}

/** Фото мест из жизни: снимки мест и адресов, где он был, — из тех лет, когда он там был (отбирает site_export.life_photos).
 *  Одной лентой по срезам лет; у каждого снимка — метка, где снято («наше · Вербичи») или «≈ не наше». */
export function LifePhotos({p, ix}: {p: PersonFile; ix: Lookup}) {
  const href = useLinks()
  const t = useT(), lang = useLang()
  const groups = p.life_photos ?? [], other = p.life_photos_other ?? []
  if (!groups.length && !other.length) return null
  const whereOf = new Map(groups.flatMap(g => g.photos.map(ph => [ph.url, nameIn(g.names, lang)] as const)))
  const photos = [...new Map(groups.flatMap(g => g.photos.map(ph => [ph.url, ph] as const))).values()]
  const links = groups.flatMap(g => {
    const pl = g.place ? ix.places.get(g.place) : undefined
    const to = pl ? href.place(pl.slug) : g.album ? href.album(g.album) : undefined
    return to ? [{to, name: nameIn(g.names, lang), n: g.photos.length}] : []
  })
  return <section className="card flat">
    <h2><Icon name="pics" />{t('gal_life_photos')} <span className="count">{photos.length}</span></h2>
    {photos.length > 0 && <PhotoTimeline photos={photos} where={t('nw_life_photos')} ours={ph => whereOf.get(ph.url)} />}
    {links.length > 0 && <p className="life">{links.map((l, i) => <span key={l.to}>{i > 0 && ' · '}<Link to={l.to}>{l.name}</Link> {l.n}</span>)}</p>}
    {other.length > 0 && <p className="life">{t('addr_other_years')}: {other.map((id, i) => { const pl = ix.places.get(id)
      return pl ? <span key={id}>{i > 0 && ', '}<Link to={href.place(pl.slug)}>{nameIn(pl.names, lang)}</Link></span> : null })}</p>}
  </section>
}
