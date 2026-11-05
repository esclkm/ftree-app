import {icons} from '../data'

/** Значок Material Icons; контуры — из data/ui.json (ICONS в site_export.py) */
export function Icon({name}: {name: string}) {
  return <svg className="ic" viewBox="0 0 24 24" aria-hidden="true"><path d={icons()[name]} /></svg>
}
