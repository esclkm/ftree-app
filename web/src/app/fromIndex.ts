// data/index.json → данные в том виде, в каком их ждут нынешние дерево, карта и «кем приходится» (src/data.ts).
import type {Place, Stats, TreePerson} from '../data'
import type {SiteIndex} from '../data/schema.gen'

const NO_STATS: Stats = {bio: false, texts: 0, facts: 0, fam: 0, web: 0, tree: 0, pics: 0, langs: []}

export function treeFromIndex(ix: SiteIndex): TreePerson[] {
  return ix.people.map(p => ({
    id: p.id,
    data: {
      gender: p.sex, ru: p.names.ru, en: p.names.en ?? p.names.ru, pl: p.names.pl ?? p.names.en ?? p.names.ru, es: p.names.es,
      slug: p.slug, life: p.life, avatar: p.avatar ?? '', url: `/people/${p.slug}`,
      st: (p.stats as Stats | undefined) ?? NO_STATS, mar: p.marriage ?? 0,
      ini: p.initials ? {ru: p.initials.ru, en: p.initials.en ?? p.initials.ru, pl: p.initials.pl ?? p.initials.ru, es: p.initials.es} : null,
      c: p.color ?? 0, kin: p.kinship, kinBy: p.kinship_by,
    },
    // копии: библиотека дерева дописывает в эти списки свои пометки, а данные хранилища заморожены
    rels: {parents: [...p.parents], spouses: [...p.spouses], children: [...p.children]},
  }))
}

export function placesFromIndex(ix: SiteIndex): Place[] {
  return ix.places.flatMap(p => (p.lat === undefined || p.lng === undefined ? [] : [{
    id: p.id, ru: p.names.ru, en: p.names.en ?? p.names.ru, pl: p.names.pl ?? p.names.ru, es: p.names.es,
    lat: p.lat, lng: p.lng, url: `/places/${p.slug}`, n: p.people,
  }]))
}
