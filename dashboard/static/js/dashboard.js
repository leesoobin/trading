// AutoTrade Bot Dashboard JS

const API = {
  summary: '/api/summary',
  positions: '/api/positions',
  trades: '/api/trades',
  pnlChart: '/api/pnl-chart',
  strategyStats: '/api/strategy-stats',
  stop: '/api/bot/stop',
  resume: '/api/bot/resume',
};

let pnlChart = null;
let botRunning = true;

function fmt(num) {
  if (num === null || num === undefined) return '-';
  const abs = Math.abs(num);
  if (abs >= 1_000_000) return (num / 1_000_000).toFixed(2) + 'M';
  if (abs >= 1_000) return (num / 1_000).toFixed(1) + 'k';
  return num.toFixed(0);
}

function fmtMoney(num) {
  if (num === null || num === undefined) return '-';
  const sign = num >= 0 ? '+' : '';
  return sign + '₩' + fmt(num);
}

function fmtPct(num) {
  if (num === null || num === undefined) return '-';
  const sign = num >= 0 ? '+' : '';
  return sign + (num * 100).toFixed(2) + '%';
}

function colorClass(num) {
  if (num > 0) return 'positive';
  if (num < 0) return 'negative';
  return '';
}

// ── Summary ──────────────────────────────────────────────────────
async function loadSummary() {
  try {
    const data = await fetch(API.summary).then(r => r.json());

    document.getElementById('total-asset').textContent = '₩' + fmt(data.total_asset);
    const dpEl = document.getElementById('daily-pnl');
    dpEl.textContent = fmtMoney(data.daily_pnl);
    dpEl.className = 'card-value ' + colorClass(data.daily_pnl);
    document.getElementById('daily-pnl-ratio').textContent = fmtPct(data.daily_pnl_ratio);
    document.getElementById('win-rate').textContent = Math.round((data.win_rate || 0) * 100) + '%';
    document.getElementById('win-count').textContent = `${data.win_count || 0}/${data.trade_count || 0}`;
    document.getElementById('active-positions').textContent = (data.active_positions || 0) + '종목';

    botRunning = data.bot_running !== false;
    updateBotStatus();
  } catch (e) { console.error('summary error', e); }
}

// ── PnL Chart ─────────────────────────────────────────────────────
async function loadPnlChart() {
  try {
    const data = await fetch(API.pnlChart).then(r => r.json());
    const labels = data.map(d => d.date);
    const values = data.map(d => d.cumulative_pnl);

    if (pnlChart) {
      pnlChart.data.labels = labels;
      pnlChart.data.datasets[0].data = values;
      pnlChart.update();
      return;
    }

    const ctx = document.getElementById('pnl-chart').getContext('2d');
    pnlChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label: '누적 손익',
          data: values,
          borderColor: '#3b82f6',
          backgroundColor: 'rgba(59,130,246,.1)',
          fill: true,
          tension: 0.3,
          pointRadius: 3,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: '#8892a4' }, grid: { color: '#2d3147' } },
          y: {
            ticks: {
              color: '#8892a4',
              callback: v => '₩' + fmt(v),
            },
            grid: { color: '#2d3147' },
          },
        },
      },
    });
  } catch (e) { console.error('pnl chart error', e); }
}

// ── Positions ─────────────────────────────────────────────────────
async function loadPositions() {
  try {
    const data = await fetch(API.positions).then(r => r.json());
    const tbody = document.getElementById('positions-body');
    if (!data || data.length === 0) {
      tbody.innerHTML = '<tr><td colspan="8" class="empty">포지션 없음</td></tr>';
      return;
    }
    tbody.innerHTML = data.map(p => `
      <tr>
        <td><b>${p.symbol}</b></td>
        <td>${p.exchange}</td>
        <td>${p.strategy}</td>
        <td>₩${fmt(p.entry_price)}</td>
        <td>₩${fmt(p.current_price)}</td>
        <td class="${colorClass(p.pnl_ratio)}">${fmtPct(p.pnl_ratio)}<br><small>${fmtMoney(p.pnl)}</small></td>
        <td class="negative">₩${fmt(p.stop_price)}</td>
        <td class="positive">₩${fmt(p.take_profit_price)}</td>
      </tr>
    `).join('');
  } catch (e) { console.error('positions error', e); }
}

// ── Trades ────────────────────────────────────────────────────────
async function loadTrades() {
  try {
    const data = await fetch(API.trades + '?limit=20').then(r => r.json());
    const tbody = document.getElementById('trades-body');
    if (!data || data.length === 0) {
      tbody.innerHTML = '<tr><td colspan="8" class="empty">거래 내역 없음</td></tr>';
      return;
    }
    tbody.innerHTML = data.map(t => {
      const ts = t.timestamp ? t.timestamp.substring(11, 16) : '-';
      const pnlStr = t.pnl != null ? fmtMoney(t.pnl) : '-';
      return `
        <tr>
          <td>${ts}</td>
          <td>${t.exchange}</td>
          <td>${t.symbol}</td>
          <td>${t.strategy}</td>
          <td><span class="badge badge-${t.side}">${t.side === 'buy' ? '매수' : '매도'}</span></td>
          <td>₩${fmt(t.price)}</td>
          <td>${t.quantity ? t.quantity.toFixed(4) : '-'}</td>
          <td class="${t.pnl >= 0 ? 'positive' : 'negative'}">${pnlStr}</td>
        </tr>
      `;
    }).join('');
  } catch (e) { console.error('trades error', e); }
}

// ── Strategy Stats ────────────────────────────────────────────────
async function loadStrategyStats() {
  try {
    const data = await fetch(API.strategyStats).then(r => r.json());
    const tbody = document.getElementById('strategy-body');
    if (!data || data.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" class="empty">데이터 없음</td></tr>';
      return;
    }
    tbody.innerHTML = data.map(s => `
      <tr>
        <td>${s.strategy}</td>
        <td>${s.trade_count}</td>
        <td>${Math.round((s.win_rate || 0) * 100)}%</td>
        <td class="${colorClass(s.avg_return)}">${fmtPct(s.avg_return)}</td>
        <td class="${colorClass(s.total_pnl)}">${fmtMoney(s.total_pnl)}</td>
      </tr>
    `).join('');
  } catch (e) { console.error('strategy stats error', e); }
}

// ── Bot Control ───────────────────────────────────────────────────
function updateBotStatus() {
  const badge = document.getElementById('bot-status');
  const btn = document.getElementById('btn-stop');
  if (botRunning) {
    badge.textContent = '● RUNNING';
    badge.className = 'status-badge status-running';
    btn.textContent = 'STOP';
    btn.className = 'btn btn-danger';
  } else {
    badge.textContent = '● STOPPED';
    badge.className = 'status-badge status-stopped';
    btn.textContent = 'RESUME';
    btn.className = 'btn btn-primary';
  }
}

async function toggleBot() {
  const url = botRunning ? API.stop : API.resume;
  const res = await fetch(url, { method: 'POST' }).then(r => r.json());
  botRunning = res.status === 'running';
  updateBotStatus();
}

// ── WebSocket ─────────────────────────────────────────────────────
function connectWS() {
  const ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      if (data.type === 'portfolio_update') {
        botRunning = data.bot_running !== false;
        updateBotStatus();
      }
      if (data.type === 'bot_status') {
        botRunning = data.running;
        updateBotStatus();
      }
    } catch (_) {}
  };
  ws.onclose = () => setTimeout(connectWS, 5000);
}

// ── Init ──────────────────────────────────────────────────────────
async function refresh() {
  await Promise.all([loadSummary(), loadPositions(), loadTrades(), loadStrategyStats()]);
}

async function init() {
  await loadPnlChart();
  await refresh();
  setInterval(refresh, 10_000);
  setInterval(loadPnlChart, 60_000);
  connectWS();
}

document.addEventListener('DOMContentLoaded', init);
