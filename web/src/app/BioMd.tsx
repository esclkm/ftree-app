// Текст биографии (Markdown: заголовки, списки, таблицы) → React. Ссылки по номеру — как в тексте фактов (Md.tsx);
// картинки — с адресом на сайте. HTML из текста не вставляется: react-markdown строит элементы сам.
import Markdown, {defaultUrlTransform} from 'react-markdown'
import {Link} from 'react-router'
import remarkGfm from 'remark-gfm'
import {shownLabel, target} from './Md'
import {useLang} from './i18n'
import {useIndex} from './useIndex'
import {BlockPin} from './notes/Pin'

const OWN = /^(person|place|source|doc):(.+)$/

export function BioMd({text}: {text: string}) {
  const {ix} = useIndex(), lang = useLang()
  return <Markdown
    remarkPlugins={[remarkGfm]}
    // свои ссылки (person:<id> …) react-markdown иначе выбросил бы как непонятные
    urlTransform={url => (OWN.test(url) ? url : defaultUrlTransform(url))}
    components={{
      a: ({href, children}) => {
        const m = href?.match(OWN)
        if (m) {
          const to = target(m[1], m[2], ix, lang)
          const shown = typeof children === 'string' ? shownLabel(m[1], m[2], children, ix, lang) : children
          return to ? <Link to={to}>{shown}</Link> : <>{shown}</>
        }
        return <a href={href} target="_blank" rel="noreferrer noopener">{children}</a>
      },
      // «＋» на полях абзаца и пункта — только в режиме заметок (иначе BlockPin ничего не рисует)
      p: ({children}) => <p className="nblock">{children}<BlockPin /></p>,
      li: ({children, className}) => <li className={['nblock', className].filter(Boolean).join(' ')}>{children}<BlockPin /></li>,
      img: ({src, alt}) => <a href={typeof src === 'string' ? src : undefined}><img className="inl" loading="lazy" src={typeof src === 'string' ? src : undefined} alt={alt ?? ''} /></a>,
    }}
  >{fieldLines(text)}</Markdown>
}

/** Биографии набраны с переносом строк внутри абзаца (~120 знаков) — такой перенос остаётся пробелом, как в Markdown и
 *  на нынешних страницах. Новая строка — только у строк шапки «**Родился:** …», «**Кто:** …»: подпись жирным с двоеточием. */
export const fieldLines = (md: string): string => md.replace(/([^\n])\n(?=\*\*[^*\n]{1,40}:\*\*)/g, '$1  \n')
