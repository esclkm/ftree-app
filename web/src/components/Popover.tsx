import {useEffect, useRef, useState, type ReactNode} from 'react'
import {Icon} from './Icon'

/** Кнопка-значок и окошко под ней. Закрывается кнопкой, клавишей Esc или нажатием мимо */
export function Popover({icon, title, className, children}: {icon: string; title: string; className?: string; children: ReactNode}) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const outside = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('click', outside); document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('click', outside); document.removeEventListener('keydown', esc) }
  }, [open])
  return (
    <div className="popover" ref={box}>
      <button className={'icon-btn' + (open ? ' on' : '')} title={title} aria-label={title} onClick={() => setOpen(!open)}>
        <Icon name={icon} />
      </button>
      {open && <div className={'card popover-body ' + (className || '')}>{children}</div>}
    </div>
  )
}
