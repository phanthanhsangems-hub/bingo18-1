/* ═══════════════════════════════════════════════════════════════
   BINGO18 Dashboard JS — "Sạp Số" (P154)
   Data: REST endpoints + SSE live refresh
   ═══════════════════════════════════════════════════════════════ */
'use strict';

const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const SZ_VI = { LON: 'LỚN', HOA: 'HÒA', NHO: 'NHỎ' };

async function J(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} -> ${r.status}`);
  return r.json();
}

function sizeOf(nums) {
  const s = (nums || []).reduce((a, b) => a + b, 0);
  return s >= 12 ? 'LON' : (s >= 10 ? 'HOA' : 'NHO');
}

function miniDice(nums) {
  return `<span class="mini-dice">${(nums || []).map(v =>
    `<span class="mini-die" data-v="${v}">${v}</span>`).join('')}</span>`;
}

function szPill(sz, cls = 'tk-sz') {
  if (!sz) return '';
  return `<span class="${cls} ${sz}">${SZ_VI[sz] || sz}</span>`;
}

// ── toast ─────────────────────────────────────────────────────
let toastTimer = null;
function toast(msg) {
  const t = $('live-toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 5000);
}

// ── theme ─────────────────────────────────────────────────────
$('theme-btn').addEventListener('click', () => {
  const r = document.documentElement;
  const next = r.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
  r.setAttribute('data-theme', next);
  localStorage.setItem('bingo18-theme', next);
});

// ── clock + countdown (chu kỳ 6 phút, giờ VN) ────────────────
function tick() {
  const now = new Date();
  $('clock').textContent = now.toLocaleTimeString('vi-VN',
    { hour12: false, timeZone: 'Asia/Ho_Chi_Minh' });
  const s = 360 - ((now.getMinutes() % 6) * 60 + now.getSeconds());
  $('cd').textContent =
    String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0');
  $('cd-bar').style.width = ((360 - s) / 360 * 100) + '%';
}
tick();
setInterval(tick, 1000);

// ── HERO: prediction ──────────────────────────────────────────
async function loadHero() {
  const p = await J('/api/next_prediction');
  if (!p || !p.predicted_numbers) return;

  const nums = p.predicted_numbers;
  $('pred-draw').textContent = '#' + p.draw_number;
  $('pred-model').textContent = p.model_name || '--';
  if (p.display_time_vietnam) $('pred-time').textContent = 'xổ lúc ' + p.display_time_vietnam;

  const row = $('dice-row');
  row.classList.remove('rolled');
  void row.offsetWidth; // restart CSS animation
  [...row.children].forEach((die, i) => die.setAttribute('data-v', nums[i] ?? 0));
  row.classList.add('rolled');
  row.setAttribute('aria-label', 'Bộ số dự đoán: ' + nums.join(', '));

  const sz = sizeOf(nums);
  const sum = nums.reduce((a, b) => a + b, 0);
  const pill = $('pred-size');
  pill.className = 'size-pill ' + sz;
  pill.textContent = `${SZ_VI[sz]} · tổng ${sum}`;

  const conf = (p.confidence || 0) * 100;
  $('conf-val').innerHTML = `${conf.toFixed(1)}<small> %</small>`;
  $('conf-fill').style.width = Math.min(conf, 100) + '%';
  const delta = conf - 35;
  $('conf-delta').textContent = (delta >= 0 ? '+' : '') + delta.toFixed(1) + ' điểm';
  $('conf-delta').style.color = delta >= 0 ? 'var(--win)' : 'var(--loss)';

  // vote share nếu có
  const vb = p.vote_breakdown || {};
  if (vb.vote_share != null) {
    $('pred-probs').hidden = false;
    $('pred-probs').innerHTML = `Đồng thuận <b>${Math.round(vb.vote_share * 100)}%</b>`;
  }
}

// ── Forecast N+2/N+3 (Markov projection) ─────────────────────
async function loadForecast() {
  const d = await J('/api/next-prediction');
  if (!d || !d.n2) return;
  const strip = $('forecast-strip');
  const item = (n, label) => {
    if (!n) return '';
    const probs = n.size_probs || {};
    const pct = probs[n.predicted_size] != null
      ? ` ${Math.round(probs[n.predicted_size] * 100)}%` : '';
    return `<span class="fc-item"><span class="mono">#${n.draw_number}</span>` +
      `<span class="fc-sz ${esc(n.predicted_size)}">${SZ_VI[n.predicted_size] || ''}${pct}</span>` +
      `<span>${label}</span></span>`;
  };
  strip.innerHTML =
    `<span style="letter-spacing:.1em;text-transform:uppercase;font-size:10.5px">Dự báo</span>` +
    item(d.n2, 'Markov¹') + item(d.n3, 'Markov²');
  strip.hidden = false;
}

// ── Ticker + Log (recent outcomes) ────────────────────────────
async function loadRecent() {
  const d = await J('/api/recent-outcomes');
  const rows = d.draws || [];
  if (!rows.length) return;

  // topbar: kỳ mới nhất + sync lag
  const latest = rows[0];
  $('last-draw').textContent = '#' + latest.draw_number;
  if (latest.draw_time) {
    const drawMs = new Date(latest.draw_time.replace(' ', 'T')).getTime();
    const nowVN = new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Ho_Chi_Minh' })).getTime();
    const lagMin = Math.max(0, Math.round((nowVN - drawMs) / 60000));
    $('sync-lag').textContent = lagMin <= 1 ? 'live' : lagMin + 'p';
    const dot = $('sys-dot');
    dot.className = 'dot' + (lagMin > 20 ? ' down' : lagMin > 10 ? ' stale' : '');
    $('sys-status').textContent = lagMin > 20 ? 'TRỄ' : 'LIVE';
  }

  // ticker
  $('ticker').innerHTML = '<span class="tk-label">Vừa xổ</span>' + rows.map(r => {
    const wl = r.is_win == null ? '' :
      `<span class="tk-wl ${r.is_win ? 'w' : 'l'}">${r.is_win ? '✓' : '✕'}</span>`;
    return `<div class="tk-item"><span class="tk-no mono">#${r.draw_number}</span>` +
      miniDice(r.numbers) + szPill(r.size) + wl + `</div>`;
  }).join('');

  // last result chip in hero
  const lr = rows.find(r => r.is_win != null);
  if (lr) {
    $('last-result').hidden = false;
    $('last-result').innerHTML =
      `Kỳ trước: <b>${(lr.numbers || []).join('·')} — ${SZ_VI[lr.size] || ''} ${lr.is_win ? '✓' : '✕'}</b>`;
  }

  // log table
  $('log-body').innerHTML = rows.map(r => {
    const wl = r.is_win == null
      ? '<span class="wl p">CHỜ</span>'
      : (r.is_win ? '<span class="wl w">WIN</span>' : '<span class="wl l">LOSS</span>');
    const time = r.draw_time ? esc(String(r.draw_time).slice(11, 16)) : '--';
    return `<tr>
      <td class="mono">#${r.draw_number}</td>
      <td class="mono">${time}</td>
      <td>${r.pred_numbers && r.pred_numbers.length ? miniDice(r.pred_numbers) : '<span class="skeleton">--</span>'}</td>
      <td>${szPill(r.pred_size)}</td>
      <td>${miniDice(r.numbers)}</td>
      <td>${szPill(r.size)}</td>
      <td class="num">${r.match_count ?? '--'}</td>
      <td>${wl}</td>
    </tr>`;
  }).join('');
}

// ── Stat tiles ────────────────────────────────────────────────
async function loadTiles() {
  const [tw, ls, wl] = await Promise.allSettled([
    J('/api/today-wr'), J('/api/learning-status'), J('/api/wl-streak'),
  ]);

  if (tw.status === 'fulfilled' && tw.value.wr != null) {
    const w = tw.value;
    $('wr-today').textContent = w.wr.toFixed(1) + '%';
    const d = w.wr - 35;
    $('wr-today-sub').innerHTML =
      `<span class="${d >= 0 ? 't-up' : 't-down'}">${d >= 0 ? '▲' : '▼'} ${Math.abs(d).toFixed(1)}</span>` +
      ` vs baseline · ${w.evaluated} kỳ`;
  }

  if (ls.status === 'fulfilled') {
    const l = ls.value;
    if (l.win_rate_last_50 != null) {
      $('wr-50').textContent = (l.win_rate_last_50 * 100).toFixed(1) + '%';
      $('wr-50-sub').textContent = `${l.wins_last_50}/${l.total_last_50} thắng`;
    }
    if (l.learned_last_24h != null) {
      $('learned-24h').textContent = l.learned_last_24h + ' kỳ';
      $('learned-sub').textContent = l.last_retrain_at
        ? 'Retrain: ' + String(l.last_retrain_at).slice(11, 16)
        : 'Retrain: tự động mỗi ' + (l.auto_retrain_interval || 20) + ' kỳ';
    }
  }

  if (wl.status === 'fulfilled' && wl.value.result) {
    const s = wl.value;
    const win = s.result === 'WIN';
    $('streak-val').textContent = `${s.streak_len} ${win ? 'thắng' : 'thua'}`;
    $('streak-val').style.color = win ? 'var(--win)' : 'var(--loss)';
    $('streak-sub').textContent = win ? 'Giữ vững phong độ 🔥' : 'Chờ đảo chiều';
  }
}

// ── WR 7-day chart (SVG + crosshair tooltip) ─────────────────
async function loadTrend() {
  const d = await J('/api/daily-trend?days=7');
  const trend = (d.trend || []).slice(-7);
  if (!trend.length) { $('wr-chart').innerHTML = '<span class="skeleton">Chưa có dữ liệu</span>'; return; }

  const data = trend.map(t => ({
    d: t.date.slice(5).replace('-', '/'),
    v: +(t.win_rate * 100).toFixed(1),
    n: t.total,
  }));
  const W = 560, H = 210, P = { t: 14, r: 16, b: 26, l: 38 };
  const vals = data.map(p => p.v);
  const lo = Math.max(0, Math.floor((Math.min(...vals, 35) - 4) / 5) * 5);
  const hi = Math.min(100, Math.ceil((Math.max(...vals, 35) + 4) / 5) * 5);
  const x = i => data.length === 1 ? W / 2 : P.l + (W - P.l - P.r) * i / (data.length - 1);
  const y = v => P.t + (H - P.t - P.b) * (1 - (v - lo) / (hi - lo));
  const pts = data.map((p, i) => [x(i), y(p.v)]);
  const line = pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ');
  const area = line + ` L${pts[pts.length - 1][0]},${y(lo)} L${pts[0][0]},${y(lo)} Z`;

  const gridVals = [];
  for (let v = lo; v <= hi; v += 5) gridVals.push(v);
  const grid = gridVals.map(v => `
    <line x1="${P.l}" x2="${W - P.r}" y1="${y(v)}" y2="${y(v)}" stroke="var(--chart-grid)"/>
    <text x="${P.l - 8}" y="${y(v) + 4}" text-anchor="end" font-size="10.5" fill="var(--muted)" class="num">${v}%</text>`).join('');
  const base = `<line x1="${P.l}" x2="${W - P.r}" y1="${y(35)}" y2="${y(35)}" stroke="var(--muted)" stroke-dasharray="4 4" opacity=".7"/>`;
  const xl = data.map((p, i) =>
    `<text x="${x(i)}" y="${H - 8}" text-anchor="middle" font-size="10.5" fill="var(--muted)">${esc(p.d)}</text>`).join('');
  const end = pts[pts.length - 1];

  $('wr-chart').innerHTML = `
  <svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;display:block" id="wr-svg" role="img"
       aria-label="Win rate 7 ngày gần nhất">
    ${grid}${base}
    <path d="${area}" fill="var(--jade)" opacity=".12"/>
    <path d="${line}" fill="none" stroke="var(--jade)" stroke-width="2" stroke-linecap="round"/>
    <circle cx="${end[0]}" cy="${end[1]}" r="4.5" fill="var(--jade)" stroke="var(--card)" stroke-width="2"/>
    <text x="${end[0] - 6}" y="${end[1] - 10}" text-anchor="end" font-size="11.5" font-weight="700"
          fill="var(--ink)" class="num">${data[data.length - 1].v}%</text>
    <line id="wr-xh" y1="${P.t}" y2="${H - P.b}" stroke="var(--muted)" opacity="0"/>
    ${xl}
  </svg>`;

  const svg = $('wr-svg'), xh = $('wr-xh'), tt = $('tooltip');
  svg.addEventListener('mousemove', e => {
    const r = svg.getBoundingClientRect(), sx = (e.clientX - r.left) / r.width * W;
    let bi = 0, bd = 1e9;
    pts.forEach((p, i) => { const dd = Math.abs(p[0] - sx); if (dd < bd) { bd = dd; bi = i; } });
    xh.setAttribute('x1', pts[bi][0]); xh.setAttribute('x2', pts[bi][0]); xh.setAttribute('opacity', '.5');
    tt.innerHTML = `${esc(data[bi].d)} · WR <b>${data[bi].v}%</b> · ${data[bi].n} kỳ`;
    tt.style.left = (r.left + scrollX + pts[bi][0] / W * r.width) + 'px';
    tt.style.top = (r.top + scrollY + pts[bi][1] / H * r.height) + 'px';
    tt.style.opacity = 1;
  });
  svg.addEventListener('mouseleave', () => { xh.setAttribute('opacity', '0'); tt.style.opacity = 0; });
}

// ── SIZE distribution today ───────────────────────────────────
async function loadSizeDist() {
  const d = await J('/api/today-draws');
  const draws = d.draws || [];
  if (!draws.length) { $('size-bars').innerHTML = '<span class="skeleton">Chưa có kỳ nào hôm nay</span>'; return; }
  const cnt = { NHO: 0, HOA: 0, LON: 0 };
  draws.forEach(r => { if (cnt[r.size] != null) cnt[r.size]++; });
  const total = draws.length;
  $('size-dist-sub').textContent = `${total} kỳ hôm nay (giờ VN)`;
  const CLR = { NHO: 'var(--jade)', HOA: 'var(--amber)', LON: 'var(--plum)' };
  const max = Math.max(cnt.NHO, cnt.HOA, cnt.LON, 1);
  $('size-bars').innerHTML = ['NHO', 'HOA', 'LON'].map(sz => {
    const pct = total ? (cnt[sz] / total * 100) : 0;
    return `<div class="szbar">
      <div class="bar-val num">${cnt[sz]}</div>
      <div class="bar" style="height:${Math.max(4, cnt[sz] / max * 78)}%;background:${CLR[sz]}"
           data-tip="${SZ_VI[sz]} · ${cnt[sz]} kỳ · ${pct.toFixed(1)}%"></div>
      <div class="bar-lbl" style="color:${CLR[sz]}">${SZ_VI[sz]}</div>
      <div class="bar-pct num">${pct.toFixed(1)}%</div>
    </div>`;
  }).join('');
  bindTips();
}

// ── Hot / cold numbers ────────────────────────────────────────
let _numGaps = {};   // {"1": kỳ chưa ra, ...} — từ /api/cold-streaks
async function loadHotCold() {
  const freq = await J('/api/number_frequency?window=100');
  const items = Object.entries(freq)
    .map(([n, c]) => ({ n: +n, c: +c }))
    .filter(o => o.n >= 1 && o.n <= 6)
    .sort((a, b) => b.c - a.c);
  if (!items.length) return;
  const maxC = items[0].c;
  $('hc-grid').innerHTML = items.map((f, i) => {
    const badge = i === 0
      ? '<span class="hc-badge hot">🔥 NÓNG</span>'
      : i === items.length - 1
        ? '<span class="hc-badge cold">❄️ LẠNH</span>'
        : '<span class="hc-badge mid">·</span>';
    const gap = _numGaps[f.n];
    const gapHtml = gap == null ? ''
      : gap === 0
        ? '<div class="hc-gap just">● vừa ra kỳ này</div>'
        : `<div class="hc-gap${gap >= 5 ? ' long' : ''}">chưa ra <b class="num">${gap}</b> kỳ</div>`;
    return `<div class="hc-cell">
      <div class="hc-num" style="background:var(--n${f.n})">${f.n}</div>
      ${badge}
      <div class="hc-track"><i style="width:${Math.round(f.c / maxC * 100)}%;background:var(--n${f.n})"></i></div>
      <div class="hc-cnt num"><b>${f.c}</b> lần</div>
      ${gapHtml}
    </div>`;
  }).join('');
}

// ── Cold combos (đồng thời cấp gap từng số cho card nóng/lạnh) ─
async function loadColdCombos() {
  const d = await J('/api/cold-streaks');
  _numGaps = d.numbers || {};
  loadHotCold().catch(() => {});   // vẽ lại card số nóng/lạnh kèm gap
  const combos = (d.combos || []).slice(0, 6);
  if (!combos.length) return;
  const maxGap = combos[0].streak || 1;
  $('cold-list').innerHTML = combos.map(r => {
    const nums = String(r.combo).split('').map(Number);
    return `<div class="cold-row">
      ${miniDice(nums)}
      <div class="cold-track"><i style="width:${Math.max(4, r.streak / maxGap * 100)}%"></i></div>
      <span class="cold-n num">${r.streak.toLocaleString('vi-VN')} <small>kỳ</small></span>
    </div>`;
  }).join('');
}

// ── Alerts ────────────────────────────────────────────────────
const ALERT_META = [
  { match: /cluster/i, icon: '🔥', cls: '' },
  { match: /triple/i, icon: '⚡', cls: 'watch' },
  { match: /pair|double/i, icon: '🎯', cls: 'watch' },
  { match: /bocpd|regime/i, icon: '📡', cls: 'info' },
  { match: /drift|voter/i, icon: '🩺', cls: 'info' },
];
function alertMeta(key) {
  for (const m of ALERT_META) if (m.match.test(key || '')) return m;
  return { icon: 'ℹ️', cls: 'info' };
}
function agoVN(iso) {
  try {
    const t = new Date(iso.includes('T') ? iso : iso.replace(' ', 'T') + 'Z').getTime();
    const mins = Math.max(0, Math.round((Date.now() - t) / 60000));
    if (mins < 60) return mins + ' phút';
    if (mins < 1440) return Math.round(mins / 60) + ' giờ';
    return Math.round(mins / 1440) + ' ngày';
  } catch { return ''; }
}
async function loadAlerts() {
  const d = await J('/api/alert-log?n=8');
  const alerts = d.alerts || [];
  if (!alerts.length) {
    $('alerts').innerHTML = '<span class="skeleton">Chưa có cảnh báo nào</span>';
    return;
  }
  $('alerts').innerHTML = alerts.map(a => {
    const meta = alertMeta(a.key);
    const text = esc(String(a.message || '').replace(/<[^>]*>/g, ''));
    const lines = text.split('\n').filter(Boolean);
    const title = lines[0] || a.key;
    const body = lines.slice(1, 3).join('\n');
    return `<div class="alert ${meta.cls}">
      <div class="a-ic">${meta.icon}</div>
      <div><div class="a-t">${title}</div>${body ? `<div class="a-d">${body}</div>` : ''}</div>
      <div class="a-time">${agoVN(a.fired_at)}</div>
    </div>`;
  }).join('');
}

// ── bar tooltips ──────────────────────────────────────────────
function bindTips() {
  const tt = $('tooltip');
  document.querySelectorAll('[data-tip]').forEach(el => {
    if (el._tipBound) return;
    el._tipBound = true;
    el.addEventListener('mousemove', e => {
      tt.textContent = el.dataset.tip;
      tt.style.left = e.pageX + 'px';
      tt.style.top = (e.pageY - 8) + 'px';
      tt.style.opacity = 1;
    });
    el.addEventListener('mouseleave', () => tt.style.opacity = 0);
  });
}

// ── SSE live updates ──────────────────────────────────────────
let sse = null;
function connectSSE() {
  try {
    if (sse) sse.close();
    sse = new EventSource('/api/sse/draws');
    sse.onmessage = e => {
      try {
        const d = JSON.parse(e.data);
        if (d.type === 'new_draw') {
          toast(`🎲 Kỳ #${d.draw_number}: ${(d.numbers || []).join('·')} — ${SZ_VI[d.size_category] || ''}`);
          refreshAll();
        }
      } catch { /* heartbeat */ }
    };
    sse.onerror = () => {          // server closes after ~4 min — reconnect
      sse.close();
      setTimeout(connectSSE, 5000);
    };
  } catch { /* SSE unsupported */ }
}

// ── refresh orchestration ─────────────────────────────────────
function safe(fn) { return fn().catch(err => console.warn(fn.name, err)); }
function refreshAll() {
  safe(loadHero);
  safe(loadForecast);
  safe(loadRecent);
  safe(loadTiles);
  safe(loadSizeDist);
  safe(loadHotCold);
  safe(loadColdCombos);
  safe(loadAlerts);
}
refreshAll();
safe(loadTrend);                       // trend đổi chậm — tải 1 lần + mỗi 10 phút
setInterval(refreshAll, 60000);
setInterval(() => safe(loadTrend), 600000);
connectSSE();
