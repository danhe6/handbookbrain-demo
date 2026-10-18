/* Read-only demo: answers the UI's /api/* fetches from a saved snapshot (static/snap/). Built by scripts/build_static_demo.py. */
(() => {
  const realFetch = window.fetch.bind(window);
  const BASE = new URL('.', document.currentScript.src).href; // .../static/
  const REPO = 'https://github.com/danhe6/handbookbrain#quickstart';
  const RO = 'This is a read-only snapshot. Asking new questions, sync and approvals need the full app (README → Quickstart).';
  let idxP = null;
  const index = () => idxP || (idxP = realFetch(BASE + 'snap/index.json').then((r) => r.json()));
  const json = (d, status = 200) => new Response(JSON.stringify(d), { status, headers: { 'Content-Type': 'application/json' } });
  const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
  function keyOf(u) {
    const url = new URL(u, location.origin);
    const q = [...url.searchParams].sort((a, b) => cmp(a[0], b[0]) || cmp(a[1], b[1]));
    return decodeURIComponent(url.pathname) + (q.length ? '?' + q.map(([k, v]) => k + '=' + v).join('&') : '');
  }
  async function snap(key) {
    const f = (await index())[key];
    if (!f) return null;
    return realFetch(BASE + 'snap/' + f).then((r) => r.json());
  }
  const normQ = (s) => String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
  async function ask(question) {
    const a = await snap('/api/answers?limit=40');
    const q = normQ(question);
    const hit = (a?.answers || []).find((x) => normQ(x.question) === q)
      || (q.length > 15 && (a?.answers || []).find((x) => normQ(x.question).includes(q) || q.includes(normQ(x.question))));
    if (!hit) return json({ detail: 'Free-form questions need the live agent. In this snapshot, pick one of the answered questions on the Ask page. ' + RO }, 403);
    const st = await snap('/api/story/' + hit.id);
    const cites = (st?.graph?.nodes || []).filter((n) => n.type === 'Section' && n.cite)
      .map((n) => ({ cite: n.cite, path: n.path, page: n.page || n.title, heading: n.heading || n.label }));
    return json({ id: hit.id, question: hit.question, answer: st?.answer?.text || '', citations: cites });
  }
  window.fetch = async (input, opts = {}) => {
    const url = typeof input === 'string' ? input : input.url;
    if (!/^\/api\//.test(url)) return realFetch(input, opts);
    const method = (opts.method || 'GET').toUpperCase();
    if (method === 'POST' && url.startsWith('/api/ask')) {
      let q = ''; try { q = JSON.parse(opts.body || '{}').question; } catch (e) { /* */ }
      return ask(q);
    }
    if (method !== 'GET') return json({ detail: RO }, 403);
    const d = await snap(keyOf(url));
    return d == null ? json({ detail: 'Not in this snapshot. ' + RO }, 404) : json(d);
  };
  document.addEventListener('DOMContentLoaded', () => {
    const st = document.createElement('style');
    st.textContent = `.askbtn,#syncbtn,#refresh,[data-draft]{display:none!important}
      .ro-banner{background:#2a2140;color:#e9e3ff;font:13px/1.45 'Inter Tight',system-ui,sans-serif;padding:8px 16px;text-align:center}
      .ro-banner a{color:#c8b8ff}`;
    document.head.append(st);
    const b = document.createElement('div');
    b.className = 'ro-banner';
    b.innerHTML = `Read-only demo: every view is real API output from the GitLab graph, saved as a snapshot. To ask new questions, run it locally: <a href="${REPO}" target="_blank" rel="noopener">Quickstart ↗</a>`;
    document.body.prepend(b);
  });
})();
