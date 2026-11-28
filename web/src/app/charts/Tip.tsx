// Подсказка у мыши над графиком: обёртка position:relative, подсказка — внутри неё, у курсора.
import {type ReactNode, type MouseEvent, useCallback, useRef, useState} from 'react'

export interface TipState { x: number; y: number; body: ReactNode }

export function useTip() {
  const box = useRef<HTMLDivElement>(null)
  const [tip, setTip] = useState<TipState | null>(null)
  const show = useCallback((e: MouseEvent, body: ReactNode) => {
    const r = box.current?.getBoundingClientRect()
    if (r) setTip({x: e.clientX - r.left, y: e.clientY - r.top, body})
  }, [])
  const hide = useCallback(() => setTip(null), [])
  return {box, tip, show, hide}
}

/** Подсказка; у правого края переворачивается влево, чтобы не уйти за карточку */
export function Tip({tip, width}: {tip: TipState | null; width?: number}) {
  if (!tip) return null
  const right = width !== undefined && tip.x > width * 0.6
  return <div className="chart-tip" role="tooltip"
    style={{top: tip.y + 14, ...(right ? {right: (width ?? 0) - tip.x + 10} : {left: tip.x + 14})}}>{tip.body}</div>
}
