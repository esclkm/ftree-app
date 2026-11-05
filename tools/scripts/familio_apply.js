// Выполнить сжатый план (familio_sync.py plan → plan_c.json) в странице familio.org под входом Павла.
// Ключ входа берётся из самой страницы и никуда не уходит. Вставить: window.__planText = '…' (частями — +=),
// затем: await familioApply(window.__planText, '<sha256 плана>', {dry: true}) — пробный проход, потом без dry.
// Люди Familio в плане — номера в списке /api/v3/persons?owner (под входом), отсортированном по uuid;
// список строится здесь же и сверяется по контрольной сумме («uh»). Порядок: создать → имена → рождение → смерть →
// браки. Ничего не удаляет. Повторный запуск продолжает с места остановки (window.__fa).
async function sha256(s) {
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s))))
    .map(b => b.toString(16).padStart(2, '0')).join('');
}

async function familioApply(text, sha, opt = {}) {
  if (sha && await sha256(text) !== sha) return {error: 'план повреждён при передаче'};
  const plan = JSON.parse(text);
  // С 24.10.2026 открытый вид показывает не всех (293 из 604) — список берём под входом Павла, без скрытых им самим
  // («invisible»): их нет и в снимке familio_sync.py.
  const tk = document.getElementById('__NEXT_DATA__').textContent.match(/"token":"(eyJ[^"]+)"/)[1];
  const H = {'Authorization': 'Bearer ' + tk, 'Accept': 'application/ld+json', 'Content-Type': 'application/ld+json'};
  let U = [];
  for (let page = 1; ; page++) {
    const j = await (await fetch(`/api/v3/persons?page=${page}&owner=${plan.o}&itemsPerPage=100&orderBy=full_name&orderDirection=asc&mentions=false`, {headers: H})).json();
    U.push(...j.data.filter(x => x.privacyType !== 'invisible').map(x => x.uuid));
    if (j.data.length < 100) break;   // с 30.10.2026 Familio отдаёт не больше 100 за раз (300 → 400 «Invalid parameter»)
  }
  const mine = new Set(Object.values((window.__fa || {map: {}}).map));   // созданные этим планом — не в сверке
  U = U.filter(u => !mine.has(u));
  U.sort();
  if ((await sha256(U.join(','))).slice(0, 16) !== plan.uh) return {error: 'список людей на Familio изменился — план устарел'};
  window.__fa = window.__fa || {map: {}, done: {}, log: []};
  const S = window.__fa;
  const id = r => typeof r === 'number' ? U[r] : S.map[r];
  const empty = {calendar: 'gregorian', type: 'equal', first: null, second: null};
  const date = s => {
    if (!s) return empty;
    const [type, c, a, b] = s.split('|'), cal = c === 'j' ? 'julian' : 'gregorian';
    const part = x => { if (!x) return null; const [y, m, d] = x.split('.').map(v => v ? +v : null); return {year: y, month: m, day: d, type: cal}; };
    return {calendar: cal, type, first: part(a), second: part(b)};
  };
  const place = i => i >= 0 ? {uuid: plan.S[i]} : null;
  const basic = a => ({firstName: a[0], lastName: a[1], middleName: a[2], birthFirstName: a[3], birthLastName: a[4],
                       gender: a[5] === 'm' ? 'male' : 'female', privacy: 'visible_for_all'});
  const call = async (method, url, body, extra = {}) => {
    if (opt.dry) return {basic: {uuid: 'dry'}, updatedAt: 'dry'};
    const r = await fetch(url, {method, headers: {...H, ...extra}, body: body && JSON.stringify(body)});
    const t = await r.text();
    if (!r.ok) throw new Error(r.status + ' ' + t.slice(0, 200));
    return t ? JSON.parse(t) : {};
  };
  // Рождение и смерть: есть у человека такое событие — правим его (PUT), нет — создаём (POST); иначе выйдет второе
  // (31.10.2026). Пусто в плане — оставляем дату и место Familio; родители — добавляем к тем, что есть, никого не снимаем.
  // PUT по событию, которое только что поменялось через другого участника, — 400: перечитать и повторить.
  const bare = d => d && {calendar: d.calendar, type: d.type, first: d.first && {year: d.first.year, month: d.first.month, day: d.first.day, type: d.first.type},
                          second: d.second && {year: d.second.year, month: d.second.month, day: d.second.day, type: d.second.type}};
  const upsert = async (u, type, role, d, s, parents) => {
    for (let k = 0; ; k++) {
      const evs = opt.dry ? [] : await call('GET', `/api/v2/persons/${u}/events`);
      const ev = evs.find(e => e.type === type && e.participants.some(p => p.personUuid === u && p.role === role));
      if (!ev) return call('POST', `/api/v2/persons/${u}/events`, {uuid: null, type, date: date(d), settlement: place(s), comment: '',
        participants: [{personUuid: u, role}, ...parents.map(p => ({personUuid: p, role: 'parent'}))]});
      const parts = ev.participants.map(p => ({personUuid: p.personUuid, role: p.role}));
      for (const p of parents) if (!parts.some(x => x.personUuid === p)) parts.push({personUuid: p, role: 'parent'});
      const body = {uuid: ev.uuid, type, date: d ? date(d) : bare(ev.date), comment: ev.comment || '', participants: parts,
                    settlement: s >= 0 ? place(s) : ev.settlement && {uuid: ev.settlement.uuid}};
      try { return await call('PUT', `/api/v2/persons/${u}/events/${ev.uuid}`, body, {'X-Base-Version': ev.updatedAt}); }
      catch (e) { if (k < 1 && e.message.startsWith('400')) continue; throw e; }
    }
  };
  const limit = opt.limit || Infinity;
  let n = 0;
  for (let i = 0; i < plan.ops.length && n < limit; i++) {
    const o = plan.ops[i];
    if (S.done[i]) continue;
    try {
      if (o[0] === 'c') {
        const r = await call('POST', `/api/v2/persons?owner=${plan.o}`, {basic: basic(o.slice(2)), photo: null, biography: null,
          events: [{uuid: null, type: 'birth', date: empty, participants: [{personUuid: 'self', role: 'child'}], settlement: null, comment: ''}]});
        S.map[o[1]] = opt.dry ? 'dry-' + o[1] : r.basic.uuid;
      } else if (o[0] === 'b') {
        const u = id(o[1]);
        const cur = await call('GET', `/api/v2/persons/${u}/basic`);
        await call('PUT', `/api/v2/persons/${u}/basic`, basic(o.slice(2)), {'X-Base-Version': cur.updatedAt});
      } else if (o[0] === 'r') {
        await upsert(id(o[1]), 'birth', 'child', o[2], o[3], o[4].map(id));
      } else if (o[0] === 'd') {
        await upsert(id(o[1]), 'death', 'owner', o[2], o[3], []);
      } else if (o[0] === 'w') {
        const a = id(o[1]), b = id(o[2]);
        await call('POST', `/api/v2/persons/${a}/events`, {uuid: null, type: 'wedding', date: empty, settlement: null, comment: '',
          participants: [{personUuid: a, role: 'spouse'}, {personUuid: b, role: 'spouse'}]});
      }
      if (!opt.dry) S.done[i] = true;
      n++;
    } catch (e) {
      S.log.push(`${i} ${o[0]}: ${e.message}`);
      n++;
    }
    if (!opt.dry) await new Promise(r => setTimeout(r, 700));
  }
  return {done: Object.keys(S.done).length, of: plan.ops.length, errors: S.log.length, lastErrors: S.log.slice(-5)};
}
