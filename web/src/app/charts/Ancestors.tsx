// Карточка «Предки»: две вкладки — веер предков и глубина линий. Число поколений веера помнит браузер.
import {useState} from 'react'
import {Icon} from '../../components/Icon'
import {useT} from '../i18n'
import type {Lookup} from '../useIndex'
import {AncestorFan} from './AncestorFan'
import {ancestorSlots} from './ancestry'
import {LineDepthChart} from './LineDepth'
import './charts.scss'

const KEY = 'ftree.fanGens'
// на телефоне по умолчанию 4 поколения: при 6 имена на узком экране не прочитать
const DEFAULT = typeof matchMedia !== 'undefined' && matchMedia('(max-width: 700px)').matches ? 4 : 6
const read = () => { try { const n = Number(localStorage.getItem(KEY)); return n >= 3 && n <= 8 ? n : DEFAULT } catch { return DEFAULT } }

export function Ancestors({id, ix, title}: {id: string; ix: Lookup; title?: string}) {
  const t = useT()
  const [gens, setGens] = useState(read)
  const [tab, setTab] = useState<'fan' | 'depth'>('fan')
  const slots = ancestorSlots(ix, id, 3)
  if (!slots[2] && !slots[3]) return null          // родители неизвестны — показывать нечего
  const depthOk = slots.slice(8, 16).filter(Boolean).length >= 2
  const pick = (n: number) => { setGens(n); try { localStorage.setItem(KEY, String(n)) } catch { /* без хранилища — на этот раз */ } }
  return <section className="card anc-card" data-note-where={t('fan_title')}>
    <h2><Icon name="tree" />{title ?? t('fan_title')}</h2>
    <div className="anc-bar">
      {depthOk && <div className="bio-tabs anc-tabs" role="tablist">
        <button role="tab" aria-selected={tab === 'fan'} className={tab === 'fan' ? 'on' : ''} onClick={() => setTab('fan')}>{t('fan_tab')}</button>
        <button role="tab" aria-selected={tab === 'depth'} className={tab === 'depth' ? 'on' : ''} onClick={() => setTab('depth')}>{t('depth_title')}</button>
      </div>}
      {tab === 'fan' && <label className="life">{t('fan_gens')}{' '}
        <select value={gens} onChange={e => pick(Number(e.target.value))}>
          {[3, 4, 5, 6, 7, 8].map(n => <option key={n} value={n}>{n}</option>)}
        </select></label>}
    </div>
    {tab === 'fan' ? <AncestorFan id={id} ix={ix} gens={gens} /> : <LineDepthChart id={id} ix={ix} />}
  </section>
}
