// Фото во всплывающем окне — те же стили, что были у прежних страниц: стрелки и свайп — листать,
// Esc и клик мимо — закрыть, внизу — миниатюры. Открывает его любая сетка фото: const open = useLightbox(); open(list, i)
// На общем фото — кто где (faces): навёл на человека или на имя под снимком — он подсвечен целиком, имя под лицом;
// на телефоне — тап по снимку показывает все лица с именами.
import {createContext, type ReactNode, useCallback, useContext, useEffect, useRef, useState} from 'react'

/** Человек на снимке: имя, рамка лица и фигуры целиком в долях ширины и высоты [x0, y0, x1, y1] */
export interface ShotFace { name: string; box: number[]; body?: number[] }
const pct = (v: number) => `${v * 100}%`
// меньшие фигуры — поверх больших: ребёнок на руках ловит мышь раньше взрослого
const area = (f: ShotFace) => { const b = f.body ?? f.box; return (b[2] - b[0]) * (b[3] - b[1]) }
export interface Shot { src: string; thumb?: string; caption?: string; info?: ReactNode; faces?: ShotFace[] }
type Open = (shots: Shot[], i: number) => void
const Ctx = createContext<Open>(() => {})
export const useLightbox = (): Open => useContext(Ctx)

export function LightboxProvider({children}: {children: ReactNode}) {
  const [state, setState] = useState<{shots: Shot[]; i: number} | null>(null)
  const open = useCallback<Open>((shots, i) => setState({shots, i}), [])
  return <Ctx.Provider value={open}>{children}{state && <Box {...state} go={i => setState({...state, i})} close={() => setState(null)} />}</Ctx.Provider>
}

function Box({shots, i, go, close}: {shots: Shot[]; i: number; go: (i: number) => void; close: () => void}) {
  const n = shots.length, at = (k: number) => (k + n) % n
  const touch = useRef<number | null>(null), strip = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
      if (e.key === 'ArrowLeft') go(at(i - 1))
      if (e.key === 'ArrowRight') go(at(i + 1))
    }
    addEventListener('keydown', key)
    return () => removeEventListener('keydown', key)
  })
  useEffect(() => { strip.current?.children[i]?.scrollIntoView({block: 'nearest', inline: 'center'}) }, [i])
  const s = shots[i], faces = s.faces ?? []
  const [hl, setHl] = useState<number | null>(null), [all, setAll] = useState(false)
  useEffect(() => { setHl(null); setAll(false) }, [i])
  return <div className={`lb on${n < 2 ? ' single' : ''}${s.info ? ' info' : ''}`} onClick={e => { if (e.target === e.currentTarget) close() }}
    onTouchStart={e => { touch.current = e.touches[0].clientX }}
    onTouchEnd={e => { const x = touch.current; touch.current = null; if (x === null) return
      const d = e.changedTouches[0].clientX - x; if (Math.abs(d) > 40) go(at(d > 0 ? i - 1 : i + 1)) }}>
    <span className={`lb-ph${all ? ' all' : ''}${hl !== null ? ' hl' : ''}`} onClick={() => faces.length && setAll(!all)}>
      <img src={s.src} alt="" />
      {faces.map((f, k) => [f, k] as const).sort((a, b) => area(b[0]) - area(a[0])).map(([f, k]) => {
        const b = f.body ?? f.box, w = b[2] - b[0], h = b[3] - b[1]
        return <span key={k} className={`lb-f${hl === k ? ' on' : ''}`} onMouseEnter={() => setHl(k)} onMouseLeave={() => setHl(null)}
          style={{left: pct(b[0]), top: pct(b[1]), width: pct(w), height: pct(h)}}>
          <span className="lb-fc" style={{left: pct((f.box[0] - b[0]) / w), top: pct((f.box[1] - b[1]) / h),
            width: pct((f.box[2] - f.box[0]) / w), height: pct((f.box[3] - f.box[1]) / h)}}><span className="lb-fn">{f.name}</span></span>
        </span>
      })}
    </span>
    <button className="lb-x" aria-label="×" onClick={close}>×</button>
    <button className="lb-p" aria-label="‹" onClick={() => go(at(i - 1))}>‹</button>
    <button className="lb-n" aria-label="›" onClick={() => go(at(i + 1))}>›</button>
    <div className="lb-cap" onClick={e => { if ((e.target as HTMLElement).closest('a')) close() }}>{s.caption}
      {faces.length > 0 && <div className="lb-who">{faces.map((f, k) =>
        <span key={k} className={hl === k ? 'on' : undefined} onMouseEnter={() => setHl(k)} onMouseLeave={() => setHl(null)}>{f.name}</span>)}</div>}
      {s.info && <div className="lb-info">{s.info}</div>}</div>
    <div className="lb-c">{n > 1 ? `${i + 1} / ${n}` : ''}</div>
    {n > 1 && <div className="lb-t" ref={strip}>{shots.map((x, k) =>
      <img key={x.src} src={x.thumb ?? x.src} loading="lazy" className={k === i ? 'cur' : undefined} onClick={() => go(k)} alt="" />)}</div>}
  </div>
}
