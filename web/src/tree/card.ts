// Карточка человека в дереве: фото, имя в две строки, годы, значки материала; ярлычок «кем приходится» над ней.
// Это строка HTML, а не компонент React: карточки рисует библиотека дерева, она принимает готовый HTML.
import type {TreeDatum} from 'family-chart'
import {icons, tree, type TreePersonData} from '../data'
import {esc, nameOf, t} from '../i18n'
import {relation} from '../kin'

const BADGES = ['bio', 'texts', 'facts', 'fam', 'web', 'tree', 'pics'] as const
const ic = (k: string) => `<svg class="ic" viewBox="0 0 24 24"><path d="${icons()[k]}"/></svg>`

// уровень родства по номеру — для пустого места (второго родителя, которого нет в дереве): у него своих данных нет,
// берём уровень ребёнка — родитель точно был, вопрос лишь в том, наш ли ребёнок
let kinById: Map<string, TreePersonData['kin']> | null = null
// дети — по всему дереву, а не по развёрнутому на экране: так видно, сколько детей спрятано в свёрнутой ветке
let kidsById: Map<string, number> | null = null
const kidsOf = (id: string) => {
  if (!kidsById?.size) kidsById = new Map((tree() ?? []).map(p => [p.id, p.rels.children.length]))
  return kidsById.get(id) ?? 0
}
const kinOf = (id: string) => {
  if (!kinById?.size) kinById = new Map((tree() ?? []).map(p => [p.id, p.data.kin]))  // пустой не храним: данных ещё нет
  return kinById.get(id)
}

/** from — от кого считаем родство (я или выбранный человек); onPath — люди на подсвеченном пути */
export function cardHtml(d: TreeDatum, o: {mainId: string; from: string | null; fromIsMe: boolean; onPath: Set<string>}): string {
  const x = d.data.data as TreePersonData, st = x.st, id = d.data.id
  // без фото — инициалы на цветном круге, как в телефонной книге; значок — только у неизвестного и у пустого места
  // (пустое место — второй родитель, которого нет в дереве: у него нет ни имени, ни цвета)
  const img = x.avatar ? `<img src="${esc(x.avatar)}" alt="">`
    : `<span class="ph${x.c === undefined ? '' : ' c' + x.c}">${x.ini ? esc(nameOf(x.ini)) : ic('person')}</span>`
  // значки: сколько материала о человеке; светлая карточка с пунктиром — о нём пока ничего нет
  const b = st ? BADGES.filter(k => st[k]).map(k => `<span title="${esc(t('b_' + k))}">${ic(k)}${k === 'bio' ? '' : st[k]}</span>`).join('') : ''
  const nk = kidsOf(id)
  const kids = nk ? `<span class="kids" title="${esc(t('b_kids'))}">${ic('kids')}${nk}</span>` : ''
  const empty = st && !st.bio && !st.facts && !st.texts && !st.fam && !st.web ? ' empty' : ''
  // имя — первой строкой, фамилия — второй: карточка уже, дерево помещается шире
  const full = x.ru ? nameOf(x) : t('unknown')
  const m = full.match(/^(.*\S)\s+(\S+)$/)
  const [first, last] = m && !/^\(/.test(m[2]) ? [m[1], m[2]] : [full, '']
  const kin = x.kin ?? d.data.rels.children?.map(kinOf).find(Boolean) ?? (d.parent?.data.data as TreePersonData | undefined)?.kin
  const cls = [x.gender, empty, kin ? 'k-' + kin : '', id === o.mainId ? 'main' : '', o.onPath.has(id) ? 'on-path' : ''].join(' ')
  // ярлычок: у того, от кого считаем, — «Вы» (или «отсюда»); кем приходится — только у человека в центре,
  // то есть у того, на кого нажали: на всех карточках сразу ярлычки загромождают дерево
  const r = o.from && o.from !== id && id === o.mainId ? relation(o.from, id) : null
  const tag = o.from === id ? `<span class="kin-tag me">${esc(t(o.fromIsMe ? 'kin_you' : 'kin_origin'))}</span>`
    : r?.term ? `<span class="kin-tag" title="${esc(r.term.nom)}">${esc(r.term.nom)}</span>` : ''
  // очень длинное слово (Ольховская-Клёнова, Wierzbowska-Brzozowska) — мельче шрифтом, чтобы на узкой карточке телефона не обрезалось
  const long = (w: string) => ([...w].length > 11 ? ' nlong' : '')
  // точка уровня родства с подсказкой — только при сомнении: у «доказано» точки нет, иначе она шумит на каждой карточке
  const dot = kin && kin !== 'proven' ? `<span class="kin-dot" title="${esc(`${t('kl_title')}: ${t('kl_' + kin)} — ${t(x.kinBy === 'card' ? 'kl_by_card' : 'kl_by_facts')}`)}"></span>` : ''
  return `<div class="fc-card ${cls}">${tag}${dot}${img}<div class="tx"><div class="n${long(first)}" title="${esc(full)}">${esc(first)}</div>`
    + `${last ? `<div class="n2${long(last)}">${esc(last)}</div>` : ''}<div class="l">${esc(x.life || '')}</div><div class="b">${b}${kids}</div></div></div>`
}
