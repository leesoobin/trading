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
  if (abs >= 1_000) return num.toLocaleString('ko-KR', { maximumFractionDigits: 0 });
  if (abs >= 1) return num.toFixed(2);
  if (abs >= 0.0001) return num.toFixed(6);
  if (abs === 0) return '0';
  return num.toFixed(8);
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
    const resp = await fetch(API.pnlChart).then(r => r.json());
    const pnlData = resp.pnl ?? resp;  // 구버전 호환
    const buyDates  = new Set(resp.buy_dates  || []);
    const sellDates = new Set(resp.sell_dates || []);

    const labels = pnlData.map(d => d.date);
    const values = pnlData.map(d => d.cumulative_pnl);
    const ptColors = labels.map(d =>
      buyDates.has(d)  ? '#22c55e' :
      sellDates.has(d) ? '#ef4444' :
      'rgba(59,130,246,0.5)'
    );
    const ptSizes = labels.map(d => (buyDates.has(d) || sellDates.has(d)) ? 8 : 3);
    const ptStyles = labels.map(d =>
      buyDates.has(d)  ? 'triangle' :
      sellDates.has(d) ? 'rectRot' :
      'circle'
    );

    if (pnlChart) {
      pnlChart.data.labels = labels;
      pnlChart.data.datasets[0].data = values;
      pnlChart.data.datasets[0].pointBackgroundColor = ptColors;
      pnlChart.data.datasets[0].pointRadius = ptSizes;
      pnlChart.data.datasets[0].pointStyle = ptStyles;
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
          pointRadius: ptSizes,
          pointBackgroundColor: ptColors,
          pointStyle: ptStyles,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              afterLabel: (ctx) => {
                const d = labels[ctx.dataIndex];
                if (buyDates.has(d))  return '▲ 매수 발생';
                if (sellDates.has(d)) return '▼ 매도 발생';
                return '';
              },
            },
          },
        },
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
        <td class="positive">${p.take_profit_price > 0 ? '₩' + fmt(p.take_profit_price) : '전략 신호'}</td>
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
      tbody.innerHTML = '<tr><td colspan="9" class="empty">거래 내역 없음</td></tr>';
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
          <td><button class="btn-chart" onclick="openTVModal('${t.symbol}','${t.exchange}','${t.strategy}')">📈</button></td>
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

// ── Tab ───────────────────────────────────────────────────────────
function switchTab(name) {
  document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');
  document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
  document.getElementById('tab-' + name).style.display = '';
  document.querySelector(`.tab-btn[data-tab="${name}"]`).classList.add('active');
}

function updateAnalyzePlaceholder() {
  const market = document.getElementById('analyze-market').value;
  const placeholders = { coin: 'KRW-BTC', domestic: '005930', overseas: 'AAPL' };
  document.getElementById('analyze-symbol').placeholder = placeholders[market] || 'AAPL';
}

// ── Analyze ───────────────────────────────────────────────────────
let _candleChart = null;

async function analyzeSymbol() {
  const rawInput = document.getElementById('analyze-symbol').value.trim();
  const market = document.getElementById('analyze-market').value;
  const interval = document.getElementById('analyze-interval').value;

  if (!rawInput) { alert('종목 심볼을 입력하세요.'); return; }

  // 국내 종목명 입력 시 대소문자 변환 없이, 나머지는 대문자로
  const symbol = market === 'domestic' ? rawInput : rawInput.toUpperCase();

  document.getElementById('analyze-result').style.display = 'none';
  document.getElementById('analyze-error').style.display = 'none';
  document.getElementById('analyze-loading').style.display = '';
  document.getElementById('analyze-btn').disabled = true;

  try {
    const url = `/api/analyze?symbol=${encodeURIComponent(symbol)}&market=${market}&interval=${interval}`;
    const resp = await fetch(url);
    if (!resp.ok) {
      const errText = await resp.text().catch(() => resp.statusText);
      document.getElementById('analyze-error-msg').textContent = `서버 오류 (${resp.status}): ${errText.slice(0, 200)}`;
      document.getElementById('analyze-error').style.display = '';
      return;
    }
    const data = await resp.json();

    if (data.error) {
      document.getElementById('analyze-error-msg').textContent = `오류: ${data.error}`;
      document.getElementById('analyze-error').style.display = '';
      return;
    }

    document.getElementById('analyze-result').style.display = '';
    renderAnalyzeInfo(data);
    renderSignals(data.signals || []);
    renderRecommendation(data.recommendation);
    renderCandleChart(data.ohlcv, data.trades || [], data.signal_markers || []);
  } catch (e) {
    document.getElementById('analyze-error-msg').textContent = `오류: ${e.message}`;
    document.getElementById('analyze-error').style.display = '';
  } finally {
    document.getElementById('analyze-loading').style.display = 'none';
    document.getElementById('analyze-btn').disabled = false;
  }
}

// ── 공통 캔들 차트 렌더링 ──────────────────────────────────────────
function renderChartInContainer(containerId, ohlcv, trades, signalMarkers, height) {
  if (!ohlcv || ohlcv.length === 0) return null;

  const container = document.getElementById(containerId);
  const chart = LightweightCharts.createChart(container, {
    width: container.clientWidth || container.offsetWidth || 800,
    height: height || 340,
    layout: { background: { color: '#1a1d27' }, textColor: '#8892a4' },
    grid: { vertLines: { color: '#2d3147' }, horzLines: { color: '#2d3147' } },
    timeScale: { borderColor: '#2d3147', timeVisible: true },
    rightPriceScale: { borderColor: '#2d3147' },
  });

  const series = chart.addCandlestickSeries({
    upColor: '#22c55e', downColor: '#ef4444',
    borderUpColor: '#22c55e', borderDownColor: '#ef4444',
    wickUpColor: '#22c55e', wickDownColor: '#ef4444',
  });
  series.setData(ohlcv.map(d => ({ time: d.time, open: d.open, high: d.high, low: d.low, close: d.close })));

  const allMarkers = [];

  // 1) 전략 시그널 마커
  const sigCfg = {
    turtle_buy:   { pos: 'belowBar', color: '#22c55e', shape: 'arrowUp',   size: 1 },
    turtle_sell:  { pos: 'aboveBar', color: '#f59e0b', shape: 'arrowDown', size: 1 },
    trend_buy:    { pos: 'belowBar', color: '#3b82f6', shape: 'arrowUp',   size: 1 },
    trend_sell:   { pos: 'aboveBar', color: '#a855f7', shape: 'arrowDown', size: 1 },
  };
  for (const m of (signalMarkers || [])) {
    const cfg = sigCfg[m.type];
    if (!cfg) continue;
    allMarkers.push({ time: m.time, position: cfg.pos, color: cfg.color, shape: cfg.shape, text: m.text, size: cfg.size });
  }

  // 2) 실제 DB 거래 이력 마커 (더 크게)
  const strategyLabel = { turtle: '터틀', trend_following: '추세추종' };
  for (const t of (trades || [])) {
    allMarkers.push({
      time: t.date,
      position: t.side === 'buy' ? 'belowBar' : 'aboveBar',
      color: t.side === 'buy' ? '#00ff88' : '#ff4466',
      shape: t.side === 'buy' ? 'arrowUp' : 'arrowDown',
      text: `${strategyLabel[t.strategy] || t.strategy} ${t.side === 'buy' ? '실제매수' : '실제매도'} ${fmt(t.price)}`,
      size: 2,
    });
  }

  if (allMarkers.length > 0) {
    allMarkers.sort((a, b) => a.time.localeCompare(b.time));
    series.setMarkers(allMarkers);
  }

  chart.timeScale().fitContent();
  return chart;
}

function renderCandleChart(ohlcv, trades, signalMarkers) {
  const container = document.getElementById('candle-chart-container');
  container.innerHTML = '';
  if (_candleChart) { try { _candleChart.remove(); } catch (_) {} _candleChart = null; }
  _candleChart = renderChartInContainer('candle-chart-container', ohlcv, trades, signalMarkers, 340);
}

function renderAnalyzeInfo(data) {
  const score = data.tech_score || 0;
  const trendMap = { bullish: '🟢 상승', bearish: '🔴 하락', neutral: '🟡 중립' };

  // 차트 헤더
  document.getElementById('analyze-chart-title').textContent =
    `${data.symbol}  |  현재가 ₩${fmt(data.current_price)}  |  기술점수 ${score.toFixed(1)}/10  |  ${trendMap[data.trend] || data.trend}`;

  const hasTrades = data.trades && data.trades.length > 0;
  document.getElementById('analyze-chart-legend').innerHTML = `
    <span style="color:#22c55e">▲ 터틀매수</span>
    <span style="color:#f59e0b">▼ 터틀청산</span>
    <span style="color:#3b82f6">▲ 추세매수</span>
    <span style="color:#a855f7">▼ 추세청산</span>
    ${hasTrades ? '<span style="color:#00ff88;font-weight:700">▲ 실제매수</span><span style="color:#ff4466;font-weight:700">▼ 실제매도</span>' : ''}
  `;

  // 기존 요약 영역
  document.getElementById('res-price').textContent = '₩' + fmt(data.current_price);
  const stars = '★'.repeat(Math.round(score)) + '☆'.repeat(10 - Math.round(score));
  document.getElementById('res-score').textContent = `${stars} (${score.toFixed(1)}/10)`;
  document.getElementById('res-trend').textContent = trendMap[data.trend] || data.trend;
}

function renderSignals(signals) {
  if (!signals || signals.length === 0) return;
  const tbody = document.getElementById('signal-body');
  const nameMap = { turtle: '터틀 (55일)', trend_following: '추세추종 (MA200)' };
  const signalClass = { BUY: 'signal-buy', SELL: 'signal-sell', HOLD: 'signal-hold' };
  const signalLabel = { BUY: '🟢 매수', SELL: '🔴 매도', HOLD: '🟡 대기' };
  tbody.innerHTML = signals.map(s => `
    <tr>
      <td>${nameMap[s.strategy] || s.strategy}</td>
      <td class="${signalClass[s.signal] || ''}">${signalLabel[s.signal] || s.signal}</td>
      <td>${s.reason}</td>
    </tr>
  `).join('');
}

function renderRecommendation(rec) {
  if (!rec) return;
  const actionColor = rec.action === 'BUY' ? 'positive' : rec.action === 'SELL' ? 'negative' : '';
  document.getElementById('rec-box').innerHTML = `
    <div class="rec-card">
      <div class="rec-label">추천 액션</div>
      <div class="rec-value ${actionColor}">${rec.action === 'BUY' ? '🟢 매수' : rec.action === 'SELL' ? '🔴 매도' : '🟡 대기'}</div>
      <div class="rec-pct" style="color:var(--text-sub)">매수가 ₩${fmt(rec.buy_price)}</div>
    </div>
    <div class="rec-card">
      <div class="rec-label">손절가</div>
      <div class="rec-value negative">₩${fmt(rec.stop_loss)}</div>
      <div class="rec-pct negative">${rec.stop_loss_pct.toFixed(1)}%</div>
    </div>
    <div class="rec-card">
      <div class="rec-label">목표가</div>
      <div class="rec-value positive">₩${fmt(rec.target)}</div>
      <div class="rec-pct positive">+${rec.target_pct.toFixed(1)}%</div>
    </div>
  `;
}

// ── 거래 차트 모달 ────────────────────────────────────────────────
let _modalChart = null;

// 전략별 차트 타임프레임: 스윙은 일봉, 데이트레이딩/MTF는 1시봉
const SWING_STRATEGIES = new Set(['turtle', 'trend_following', 'smc', 'ma_pullback']);
function _chartInterval(strategy) {
  return SWING_STRATEGIES.has(strategy) ? '1d' : '1h';
}
function _chartLabel(strategy) {
  return SWING_STRATEGIES.has(strategy) ? '일봉' : '1시봉';
}

async function openTVModal(symbol, exchange, strategy) {
  const market = exchange === 'upbit' ? 'coin'
               : exchange === 'kis_domestic' ? 'domestic'
               : 'overseas';
  const interval = _chartInterval(strategy || 'turtle');
  const ivLabel = _chartLabel(strategy || 'turtle');

  document.getElementById('tv-modal').style.display = 'flex';
  document.getElementById('modal-chart-title').textContent = `${symbol} 로딩 중... (${ivLabel})`;
  document.getElementById('modal-chart-legend').innerHTML = '';
  document.getElementById('modal-candle-container').innerHTML = '';
  if (_modalChart) { try { _modalChart.remove(); } catch (_) {} _modalChart = null; }

  try {
    const data = await fetch(`/api/analyze?symbol=${encodeURIComponent(symbol)}&market=${market}&interval=${interval}`).then(r => r.json());
    if (data.error) {
      document.getElementById('modal-chart-title').textContent = `${symbol} — 오류: ${data.error}`;
      return;
    }

    document.getElementById('modal-chart-title').textContent =
      `${symbol}  [${ivLabel}]  |  현재가 ${fmt(data.current_price)}  |  기술점수 ${(data.tech_score || 0).toFixed(1)}/10`;

    document.getElementById('modal-chart-legend').innerHTML = `
      <span style="color:#22c55e">▲ 터틀매수</span>
      <span style="color:#f59e0b">▼ 터틀청산</span>
      <span style="color:#3b82f6">▲ 추세매수</span>
      <span style="color:#a855f7">▼ 추세청산</span>
      <span style="color:#00ff88;font-weight:700">▲ 실제매수</span>
      <span style="color:#ff4466;font-weight:700">▼ 실제매도</span>
    `;

    _modalChart = renderChartInContainer('modal-candle-container', data.ohlcv, data.trades || [], data.signal_markers || [], 460);
  } catch (e) {
    document.getElementById('modal-chart-title').textContent = `${symbol} — 로드 실패: ${e.message}`;
  }
}

function closeTVModal() {
  document.getElementById('tv-modal').style.display = 'none';
  if (_modalChart) { try { _modalChart.remove(); } catch (_) {} _modalChart = null; }
}
