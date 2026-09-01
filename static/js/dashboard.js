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

// ── clock (giờ VN) ────────────────────────────────────────────
function tick() {
  $('clock').textContent = new Date().toLocaleTimeString('vi-VN',
    { hour12: false, timeZone: 'Asia/Ho_Chi_Minh' });
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

// ── Dự báo cầu: cầu đang hoạt động + bảng điểm forward-test ──
let _lastDraw = null;          // {draw_number, combo} — set bởi loadRecent
async function loadWatchPairs() {
  const d = await J('/api/watch-scoreboard');
  const pairs = d.pairs || [];
  if (!pairs.length) return;
  const dash = c => String(c).split('').join('-');

  // Cầu đang hoạt động: kỳ vừa xổ có phải bộ dẫn trước không?
  const act = $('wp-active');
  if (_lastDraw) {
    const hits = pairs.filter(p => p.trigger === _lastDraw.combo);
    if (hits.length) {
      const list = hits.sort((a, b) => b.historical_count - a.historical_count)
        .map(p => `<b>${dash(p.target)}</b> (${p.historical_count} lần)`).join(' · ');
      act.className = 'wp-active';
      act.innerHTML =
        `<span class="wp-ic">👀</span><div>` +
        `<div class="wp-t">Kỳ #${_lastDraw.draw_number} vừa ra ${dash(_lastDraw.combo)} — ` +
        `theo dõi kỳ #${_lastDraw.draw_number + 1}</div>` +
        `<div class="wp-d">Cầu chờ về: ${list}</div></div>`;
    } else {
      act.className = 'wp-idle';
      act.innerHTML = `Kỳ #${_lastDraw.draw_number} ra ${dash(_lastDraw.combo)} — ` +
        `không phải bộ dẫn trước nào. Chưa có cầu nào đang chờ.`;
    }
  }

  // Bảng điểm — cầu có lượt theo dõi lên đầu, còn lại theo lịch sử
  const sorted = [...pairs].sort((a, b) =>
    (b.watches - a.watches) || (b.historical_count - a.historical_count));
  $('wp-body').innerHTML = sorted.map(p => {
    const active = _lastDraw && p.trigger === _lastDraw.combo;
    let vs = '<span class="wp-vs none">—</span>';
    if (p.watches > 0) {
      const over = p.hits > p.expected_hits;
      vs = `<span class="wp-vs ${over ? 'over' : 'under'}">` +
           `${over ? '▲' : '='} ${p.hits} / ${p.expected_hits.toFixed(2)}</span>`;
    }
    return `<tr${active ? ' style="background:var(--accent-soft)"' : ''}>
      <td class="wp-pair mono">${dash(p.trigger)} → ${dash(p.target)}</td>
      <td class="num">${p.historical_count}</td>
      <td class="num">${p.watches}</td>
      <td class="num">${p.hits}</td>
      <td class="num">${p.expected_hits.toFixed(2)}</td>
      <td>${vs}</td>
    </tr>`;
  }).join('');

  $('wp-sub').textContent =
    `${pairs.length} cầu [bộ dẫn trước → trip] · forward-test từ khi bật alert`;
  const rate = d.total_watches ? (d.total_hits / d.total_watches * 100).toFixed(2) : null;
  $('wp-foot').innerHTML =
    `Tổng: <b>${d.total_watches}</b> lượt theo dõi · <b>${d.total_hits}</b> trúng · ` +
    `kỳ vọng ngẫu nhiên <b>${d.total_expected}</b>` +
    (rate !== null ? ` · tỷ lệ trúng <b>${rate}%</b> vs base rate ${(d.base_rate * 100).toFixed(2)}%` : '') +
    `<br>Cần vài trăm lượt mới đủ ý nghĩa thống kê — 1 vài lần trúng sớm là bình thường.`;
}

// ── Ticker + Log (recent outcomes) ────────────────────────────
async function loadRecent() {
  const [dRes, npRes] = await Promise.allSettled([
    J('/api/recent-outcomes'), J('/api/next_prediction'),
  ]);
  if (dRes.status !== 'fulfilled') throw dRes.reason;
  const d = dRes.value;
  const np = npRes.status === 'fulfilled' ? npRes.value : null;
  const rows = d.draws || [];
  if (!rows.length) return;

  // topbar: kỳ mới nhất + sync lag
  const latest = rows[0];
  _lastDraw = {
    draw_number: latest.draw_number,
    combo: [...(latest.numbers || [])].sort().join(''),
  };
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

  // log table — dòng đầu: dự đoán kỳ SẮP TỚI (chưa xổ)
  let pendingRow = '';
  if (np && np.predicted_numbers && np.draw_number > rows[0].draw_number) {
    const psz = sizeOf(np.predicted_numbers);
    const ptime = np.display_time_vietnam ? esc(String(np.display_time_vietnam).slice(0, 5)) : '--';
    pendingRow = `<tr class="pending-row">
      <td class="mono">#${np.draw_number}</td>
      <td class="mono">${ptime}</td>
      <td>${miniDice(np.predicted_numbers)}</td>
      <td>${szPill(psz)}</td>
      <td colspan="3" class="pending-note">chờ xổ · win prob ${((np.confidence || 0) * 100).toFixed(1)}%</td>
      <td><span class="wl pd">DỰ ĐOÁN</span></td>
    </tr>`;
  }
  $('log-body').innerHTML = pendingRow + rows.map(r => {
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
// P188: chỉ đếm trong NGÀY HÔM NAY (giờ VN) theo yêu cầu, thay cho cửa sổ
// 1000 kỳ trước đây. Lưu ý cỡ mẫu: một ngày đủ (~160 kỳ = 480 lượt) cho
// kỳ vọng 80 ± 8.2 mỗi số — sai số tương đối 10.2% (so với 4.1% ở 1000 kỳ),
// nên nhãn NÓNG/LẠNH trong ngày nhiễu hơn nhiều. Nhãn bên dưới in thẳng
// kỳ vọng ± sai số chuẩn tính từ dữ liệu thật để không bị hiểu nhầm.
async function loadHotCold() {
  const d     = await J('/api/number_frequency?today=1');
  const freq  = (d && d.freq) ? d.freq : {};
  const items = Object.entries(freq)
    .map(([n, c]) => ({ n: +n, c: +c }))
    .filter(o => o.n >= 1 && o.n <= 6)
    .sort((a, b) => b.c - a.c);
  const slots = items.reduce((s, o) => s + o.c, 0);
  const draws = d && d.draws != null ? +d.draws : Math.round(slots / 3);
  const sub   = $('hc-sub');

  if (!items.length || slots === 0) {
    if (sub) sub.textContent = 'Hôm nay chưa có kỳ nào — chờ kỳ đầu tiên';
    $('hc-grid').innerHTML = '<span class="skeleton">Chưa có dữ liệu hôm nay</span>';
    return;
  }
  const maxC = items[0].c;

  // Nhãn tính từ dữ liệu thật, không hardcode — luôn khớp số kỳ đã có
  if (sub) {
    const exp = slots / 6;
    const sd  = Math.sqrt(slots * (1 / 6) * (5 / 6));
    sub.textContent =
      `Tần suất từng số trong ngày hôm nay · ${draws} kỳ (${slots} lượt số) · `
      + `kỳ vọng ${exp.toFixed(0)} ± ${sd.toFixed(0)} mỗi số · mỗi số một màu riêng`;
  }
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

// ── Bộ số hôm nay, GOM THEO TỔNG ────────────────────────────
// Trước đây chỉ có hai đống "đã ra" và "chưa ra", muốn biết tổng 7 còn thiếu
// bộ nào thì phải tự dò trong 56 chip. Gom theo tổng thì nhìn một cái là thấy.
async function loadTodayCombos() {
  const d = await J('/api/today-combos');
  const ap = d.appeared || [], ny = d.not_appeared || [];
  if (!ap.length && !ny.length) {
    $('tc-by-sum').innerHTML = '<span class="skeleton">Chưa có kỳ nào hôm nay</span>';
    $('tc-note').textContent = '';
    return;
  }
  $('tc-sub').textContent =
    `${ap.length}/56 bộ đã xuất hiện hôm nay (giờ VN) · ${ny.length} bộ chưa ra`;

  // gom vào 16 rổ theo tổng 3..18
  const theoTong = {};
  for (let t = 3; t <= 18; t++) theoTong[t] = { ra: [], chua: [] };
  ap.forEach(c => theoTong[c.sum].ra.push(c));
  ny.forEach(c => theoTong[c.sum].chua.push(c));

  // trong mỗi tổng: bộ ra nhiều xếp trước, rồi tới bộ chưa ra
  const sx = (a, b) => (b.count || 0) - (a.count || 0) || a.label.localeCompare(b.label);

  const chip = (c, daRa) => daRa
    ? `<span class="combo-chip" title="${esc(c.label)} · ra ${c.count} lần hôm nay">`
      + miniDice(c.combo) + `<span class="cc-count num">×${c.count}</span></span>`
    : `<span class="combo-chip not-yet" title="${esc(c.label)} · chưa ra hôm nay">`
      + miniDice(c.combo) + `</span>`;

  let html = '';
  for (let t = 3; t <= 18; t++) {
    const g = theoTong[t];
    const tong = g.ra.length + g.chua.length;      // số bộ tạo ra được tổng này
    const sz = t <= 9 ? 'NHO' : (t <= 11 ? 'HOA' : 'LON');
    const het = g.chua.length === 0;
    html += `<div class="tc-row${het ? ' du' : ''}">
      <div class="tc-key">
        <span class="ss-sum ${sz}">${t}</span>
        <span class="tc-tally num">${g.ra.length}/${tong}</span>
      </div>
      <div class="combo-chips">
        ${g.ra.sort(sx).map(c => chip(c, true)).join('')}
        ${g.chua.sort(sx).map(c => chip(c, false)).join('')}
      </div>
    </div>`;
  }
  $('tc-by-sum').innerHTML = html;

  const duTong = [];
  for (let t = 3; t <= 18; t++) if (theoTong[t].chua.length === 0) duTong.push(t);
  $('tc-note').innerHTML =
    'Mỗi hàng là một tổng · chip mờ = bộ chưa ra hôm nay · <b>x/y</b> = đã ra / tổng số bộ tạo được tổng đó. '
    + (duTong.length
        ? `Đã đủ mọi bộ ở tổng <b>${duTong.join(', ')}</b>.`
        : 'Chưa tổng nào ra đủ mọi bộ.');
}

// ── P186: nạp số kỳ vắng mặt của từng số 1-6 cho card nóng/lạnh.
// Thẻ "Bộ 3 lạnh nhất" đã bỏ, nhưng cùng endpoint này vẫn cấp _numGaps
// nên giữ lại phần nạp, chỉ bỏ phần vẽ.
async function loadNumberGaps() {
  const d = await J('/api/cold-streaks');
  _numGaps = d.numbers || {};
  loadHotCold().catch(() => {});   // vẽ lại card số nóng/lạnh kèm gap
}

// ── Alerts ────────────────────────────────────────────────────
const ALERT_META = [
  { match: /^watch_.*_hit$/i, icon: '🎯', cls: '' },
  { match: /^watch_/i, icon: '👀', cls: 'info' },
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
let sseBackoff = 5000;             // P173: lùi dần khi server từ chối
const SSE_BACKOFF_MAX = 120000;
function connectSSE() {
  try {
    if (sse) sse.close();
    sse = new EventSource('/api/sse/draws');
    sse.onopen = () => { sseBackoff = 5000; };   // nối được thì reset
    sse.onmessage = e => {
      try {
        const d = JSON.parse(e.data);
        if (d.type === 'new_draw') {
          toast(`🎲 Kỳ #${d.draw_number}: ${(d.numbers || []).join('·')} — ${SZ_VI[d.size_category] || ''}`);
          refreshAll();
        }
      } catch { /* heartbeat */ }
    };
    // Server đóng sau ~4 phút (bình thường) HOẶC trả 503 khi đủ 5 client.
    // Trường hợp 503 mà cứ thử lại mỗi 5s thì thành tự DDoS chính mình,
    // nên nhân đôi thời gian chờ tới tối đa 2 phút. Dashboard vẫn cập nhật
    // nhờ vòng refresh 60s, chỉ mất tin đẩy tức thì.
    sse.onerror = () => {
      sse.close();
      setTimeout(connectSSE, sseBackoff);
      sseBackoff = Math.min(sseBackoff * 2, SSE_BACKOFF_MAX);
    };
  } catch { /* SSE unsupported */ }
}

// ── Bet signal + Kelly stake ──────────────────────────────────
async function loadBetSignal() {
  const d = await J('/api/bet-signal');
  const badge = $('bet-badge');
  badge.textContent = d.label || '--';
  badge.className = 'bet-badge ' + (d.color || 'gold');
  const k = d.kelly || {};
  if (k.stake_pct > 0) {
    $('bet-stake').textContent = k.stake_pct.toFixed(1) + '% vốn';
    $('bet-stake').style.color = 'var(--jade)';
    $('bet-advice').textContent = k.advice || '';
  } else {
    $('bet-stake').textContent = 'BỎ QUA';
    $('bet-stake').style.color = 'var(--muted)';
    $('bet-advice').textContent = k.advice ||
      'Không có edge — chờ tín hiệu tốt hơn';
  }
  if (k.breakeven_payout != null) {
    $('bet-note').textContent =
      `WR50 ${(k.p_win * 100).toFixed(0)}% · cần trả thưởng ≥ ${k.breakeven_payout}× mới có lời ` +
      `(giả định ${k.payout_assumed}×)`;
  }
}

// ── refresh orchestration ─────────────────────────────────────
function safe(fn) { return fn().catch(err => console.warn(fn.name, err)); }
// ── P187: Lưới chi tiết — hàng = kỳ, cột = số 1..6 ───────────
async function loadDrawGrid() {
  // Người dùng muốn xem 160 kỳ. Bảng cuộn trong khung riêng (.dg-wrap,
  // max-height + thead sticky) nên số hàng lớn không kéo dài cả trang.
  const d = await J('/api/draw-grid?n=160');
  const rows = d.draws || [];
  if (!rows.length) return;

  $('dg-body').innerHTML = rows.map(r => {
    const cells = r.counts.map((c, i) => {
      if (!c) return '<td></td>';
      const dots = '<i></i>'.repeat(c);
      return `<td><span class="dg-c" style="background:var(--n${i + 1})">${dots}</span></td>`;
    }).join('');
    return `<tr>
      <td class="dg-ky mono">#${r.draw_number}</td>
      ${cells}
      <td class="dg-t num ${r.size}">${r.sum}</td>
    </tr>`;
  }).join('');

  // Tần suất từng số trong đúng cửa sổ đang hiển thị + ngưỡng nhiễu
  const tot = rows.length * 3;
  const cnt = [0, 0, 0, 0, 0, 0];
  rows.forEach(r => r.counts.forEach((c, i) => { cnt[i] += c; }));
  const exp = tot / 6;
  const sd  = Math.sqrt(tot * (1 / 6) * (5 / 6));
  const freq = cnt.map((c, i) => `<b style="color:var(--n${i + 1})">${i + 1}</b>:${c}`).join(' · ');
  // P196: trước đây ghi "chênh lệch dưới 2·SD là bình thường". SAI — 2·SD là
  // ngưỡng cho MỘT số lệch khỏi kỳ vọng, không phải cho khoảng cách giữa số
  // cao nhất và thấp nhất. Mô phỏng 400k cửa sổ: với 24 kỳ, chênh lệch trung
  // bình đã là 8,7 và vượt 2·SD tới 76,8% số lần — tức nhãn gọi trường hợp
  // thông thường là bất thường.
  // Bách phân vị 95 của (max − min) ổn định ở ~4,4·SD với mọi cỡ cửa sổ
  // (24 kỳ: 14,0 ≈ 4,43·SD; 50 kỳ: 20,0 ≈ 4,39·SD; 100 kỳ: 28,0 ≈ 4,34·SD).
  const spread    = Math.max(...cnt) - Math.min(...cnt);
  const nguong    = 4.4 * sd;
  const batThuong = spread > nguong;
  $('dg-foot').innerHTML =
    `${rows.length} kỳ gần nhất · ${freq} — kỳ vọng ${exp.toFixed(1)} ± ${sd.toFixed(1)} mỗi số. `
    + `Chênh lệch nhiều nhất − ít nhất hiện là <b>${spread}</b>; `
    + (batThuong
        ? `vượt ngưỡng ${nguong.toFixed(0)} (95% cửa sổ nằm dưới mức này).`
        : `dưới ngưỡng ${nguong.toFixed(0)} nên là dao động bình thường.`);
}

// ── P185: Thống kê bộ 3 số trùng nhau ────────────────────────
async function loadTripleStats(d) {
  d = d || await J('/api/triple-stats');
  const rows = d.triples || [];
  if (!rows.length) return;
  const fmt = v => v == null ? '—' : v.toLocaleString('vi-VN');

  // Ô "chưa về" tô đậm dần theo mức vượt trung bình
  const cell = r => {
    if (r.current_gap == null || !r.avg_gap) return '<td class="num ta-r">—</td>';
    const ratio = r.current_gap / r.avg_gap;
    const cls = ratio >= 1.5 ? ' overdue-hi' : ratio >= 1 ? ' overdue' : '';
    return `<td class="num ta-r${cls}">${fmt(r.current_gap)}</td>`;
  };

  const line = (r, isAny) => `<tr${isAny ? ' class="tr-any"' : ''}>
      <td>${isAny ? '<span class="tr-any-lbl">Bất kỳ trip nào</span>'
                  : miniDice(r.combo.split('').map(Number))}</td>
      <td class="num ta-r">${fmt(r.count)}</td>
      <td class="num ta-r ss-prev">${fmt(r.avg_gap)}</td>
      <td class="num ta-r">${fmt(r.median_gap)}</td>
      <td class="num ta-r ss-prev">${fmt(r.prev_gap)}</td>
      ${cell(r)}
    </tr>`;

  // P215: 8 LẦN TRIP GẦN NHẤT, thay cho dòng "Trip gần nhất" chỉ nói được
  // một lần. Một mốc đơn lẻ không cho thấy nhịp: 4 trip dồn trong 50 kỳ khác
  // hẳn 4 trip rải đều 800 kỳ, mà cả hai đều hiện y như nhau.
  const lastLine = () => {
    const a = d.any;
    const ds = (a && a.recent) || [];
    if (!ds.length) return '';
    const o = ds.map(x => {
      const khi = x.gap === 0 ? 'kỳ này' : `${fmt(x.gap)} kỳ trước`;
      return `<span class="tr-rec">${miniDice(x.combo.split('').map(Number))}`
           + `<span class="tr-rec-ky num">#${fmt(x.draw)}</span>`
           + `<span class="tr-rec-khi">${khi}</span></span>`;
    }).join('');
    return `<tr class="tr-last">
      <td colspan="6" class="tr-last-txt">
        <div class="tr-rec-lbl">${ds.length} lần trip gần nhất</div>
        <div class="tr-rec-wrap">${o}</div>
      </td>
    </tr>`;
  };

  $('tr-body').innerHTML = rows.map(r => line(r, false)).join('')
                         + (d.any ? line(d.any, true) : '')
                         + lastLine();
  $('tr-sub').textContent = `${fmt(d.total_draws)} kỳ`;
  // P212: TB và TRUNG VỊ nói hai chuyện khác nhau, phải giải thích rõ nếu
  // không người đọc sẽ tưởng một trong hai bị tính sai.
  $('tr-note').textContent =
    'Lý thuyết: mỗi trip cụ thể 1 lần/216 kỳ, bất kỳ trip nào 1 lần/36 kỳ. '
    + 'TB = tổng số kỳ ÷ số lần về, bị vài đợt hạn cực dài kéo lệch lên. '
    + 'TRUNG VỊ = một nửa số lần về sớm hơn con số này — sát thực tế hơn. '
    + 'Ô "chưa về" đậm khi đã vượt mức TB.';
}

// ── P185: Thống kê theo tổng ─────────────────────────────────
async function loadSumStats(d) {
  d = d || await J('/api/sum-stats');
  const by = {};
  (d.sums || []).forEach(s => { by[s.sum] = s; });
  if (!Object.keys(by).length) return;
  const fmt = v => v == null ? '—' : v.toLocaleString('vi-VN');

  const half = s => {
    if (!s) return '<td></td><td></td><td></td><td></td><td></td>';
    const ratio = (s.current_gap != null && s.avg_gap) ? s.current_gap / s.avg_gap : 0;
    const cls = ratio >= 1.5 ? ' overdue-hi' : ratio >= 1 ? ' overdue' : '';
    // P203: "Đợt trước" = chu kỳ vừa xong dài bao nhiêu kỳ. Để so trực tiếp
    // với "Chưa về" hiện tại. Rỗng khi tổng đó mới về đúng 1 lần.
    return `<td><span class="ss-sum ${s.size}">${s.sum}</span></td>`
         + `<td class="num ta-r ss-prev">${fmt(s.avg_gap)}</td>`
         + `<td class="num ta-r">${fmt(s.median_gap)}</td>`
         + `<td class="num ta-r ss-prev">${fmt(s.prev_gap)}</td>`
         + `<td class="num ta-r${cls}">${fmt(s.current_gap)}</td>`;
  };

  // 3↔18, 4↔17, … — mỗi hàng là một cặp có xác suất lý thuyết bằng nhau
  let html = '';
  for (let lo = 3; lo <= 10; lo++) {
    html += `<tr>${half(by[lo])}<td class="ss-gap"></td>${half(by[21 - lo])}</tr>`;
  }
  $('ss-body').innerHTML = html;
}

function refreshAll() {
  safe(loadHero);
  safe(loadRecent).then(() => safe(loadWatchPairs));
  safe(loadDrawGrid);
  safe(loadTiles);
  safe(loadSizeDist);
  safe(loadTodayCombos);
  safe(loadHotCold);
  safe(loadNumberGaps);
  safe(loadAlerts);
  safe(loadBetSignal);
}
// P204: bảng lịch sử — gọi qua hàm riêng để vừa dùng cho setInterval vừa
// dùng khi mở lại tab, và có ghi lại mốc thời gian cập nhật.
let _lanCuoiTaiBangTong = 0;
function loadBangLichSu() {
  _lanCuoiTaiBangTong = Date.now();
  // P207: MỘT lần gọi cho cả hai bảng. Gọi riêng thì hai request có thể rơi
  // vào hai instance Cloud Run có ảnh chụp lệch nhau, và "chưa về" của tổng 3
  // lại khác của trip 111 — đúng lỗi người dùng chụp được ở kỳ #182599.
  // Hỏng thì lùi về hai endpoint cũ để bảng vẫn hiện.
  safe(async () => {
    let d = null;
    try { d = await J('/api/board-stats'); } catch (e) { d = null; }
    if (d && d.sums && d.triples) { await loadTripleStats(d); await loadSumStats(d); }
    else { await loadTripleStats(); await loadSumStats(); }
  });
}

// P204: hiện mốc cập nhật để người dùng THẤY dữ liệu cũ hay mới, thay vì
// phải đoán. Trước đây bảng cũ 18 phút mà trông y hệt bảng vừa tải.
function ghiMocCapNhat() {
  const el = $('last-refresh');
  if (!el) return;
  el.textContent = 'cập nhật ' + new Date().toLocaleTimeString('vi-VN',
    { hour12: false, timeZone: 'Asia/Ho_Chi_Minh' }).slice(0, 5);
}

function refreshAllVaGhiMoc() {
  refreshAll();
  ghiMocCapNhat();
}

refreshAll();
ghiMocCapNhat();
safe(loadTrend);                       // trend đổi chậm — tải 1 lần + mỗi 10 phút
// P185: thống kê toàn lịch sử, đổi rất chậm — 5 phút một lần là thừa đủ
// (server cũng cache 300s nên gọi dày hơn cũng không có dữ liệu mới)
loadBangLichSu();
setInterval(refreshAllVaGhiMoc, 60000);
setInterval(() => safe(loadTrend), 600000);
setInterval(loadBangLichSu, 300000);

// P204: trình duyệt điện thoại ĐÓNG BĂNG setInterval khi tab chạy nền hoặc
// khoá máy. Mở lại app là thấy dữ liệu của lúc rời đi — có thể cũ hàng chục
// phút — cho tới lần tick kế tiếp. Người dùng thấy "tổng 14 chưa về 3" ngay
// sau khi kỳ tổng 14 vừa ra, tưởng hệ thống cập nhật sai, trong khi dữ liệu
// trong DB vẫn đúng.
// Nạp lại ngay khi tab hiện trở lại.
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState !== 'visible') return;
  refreshAllVaGhiMoc();
  // Bảng lịch sử nặng hơn và server cache 300s — chỉ nạp lại khi đã quá cũ
  if (Date.now() - _lanCuoiTaiBangTong > 120000) loadBangLichSu();
  if (typeof connectSSE === 'function') connectSSE();   // SSE cũng bị ngắt khi nền
});

connectSSE();
