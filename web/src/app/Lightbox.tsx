// Фото во всплывающем окне — те же стили, что были у прежних страниц: стрелки и свайп — листать,
// Esc и клик мимо — закрыть, внизу — миниатюры. Открывает его любая сетка фото: const open = useLightbox(); open(list, i)
import {createContext, type ReactNode, useCallback, useContext, useEffect, useRef, useState} from 'react'

export interface Shot { src: string; thumb?: string; caption?: string; info?: ReactNode }
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
  const s = shots[i]
  return <div className={`lb on${n < 2 ? ' single' : ''}${s.info ? ' info' : ''}`} onClick={e => { if (e.target === e.currentTarget) close() }}
    onTouchStart={e => { touch.current = e.touches[0].clientX }}
    onTouchEnd={e => { const x = touch.current; touch.current = null; if (x === null) return
      const d = e.changedTouches[0].clientX - x; if (Math.abs(d) > 40) go(at(d > 0 ? i - 1 : i + 1)) }}>
    <img src={s.src} alt="" />
    <button className="lb-x" aria-label="×" onClick={close}>×</button>
    <button className="lb-p" aria-label="‹" onClick={() => go(at(i - 1))}>‹</button>
    <button className="lb-n" aria-label="›" onClick={() => go(at(i + 1))}>›</button>
    <div className="lb-cap" onClick={e => { if ((e.target as HTMLElement).closest('a')) close() }}>{s.caption}
      {s.info && <div className="lb-info">{s.info}</div>}</div>
    <div className="lb-c">{n > 1 ? `${i + 1} / ${n}` : ''}</div>
    {n > 1 && <div className="lb-t" ref={strip}>{shots.map((x, k) =>
      <img key={x.src} src={x.thumb ?? x.src} loading="lazy" className={k === i ? 'cur' : undefined} onClick={() => go(k)} alt="" />)}</div>}
  </div>
}
