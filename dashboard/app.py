"""FastAPI 대시보드 서버 - http://localhost:8080"""
import asyncio
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent

app = FastAPI(title="AutoTrade Bot Dashboard")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# 전역 봇 컨텍스트 (main.py에서 주입)
_bot_context: Optional[dict] = None
_ws_clients: list[WebSocket] = []
_bot_running: bool = True


# ── 목업 데이터 (봇 미실행 시 사용) ─────────────────────────────────
def _mock_pnl_chart() -> list[dict]:
    daily_pnls = [
        45000, -28000, 62000, -15000, 83000, 24000, -45000, 96000, 28000, -18000,
        74000, -32000, 58000, 18000, -22000, 85000, -8000, 112000, 15000, -28000,
        67000, 38000, -19000, 95000, 24000, -42000, 78000, 45000, -12000, 150000,
    ]
    base_date = date(2026, 1, 23)
    cumulative = 0
    result = []
    for i, daily in enumerate(daily_pnls):
        cumulative += daily
        result.append({
            "date": (base_date + timedelta(days=i)).isoformat(),
            "daily_pnl": daily,
            "cumulative_pnl": cumulative,
        })
    return result


_MOCK_SUMMARY = {
    "total_asset": 50_000_000,
    "daily_pnl": 150_000,
    "daily_pnl_ratio": 0.003,
    "win_rate": 0.65,
    "win_count": 13,
    "trade_count": 20,
    "active_positions": 3,
    "bot_running": True,
}

_MOCK_POSITIONS = [
    {
        "symbol": "KRW-BTC", "exchange": "upbit", "strategy": "smc",
        "entry_price": 142_500_000, "current_price": 145_200_000,
        "quantity": 0.0105, "pnl": 28_350, "pnl_ratio": 0.0189,
        "stop_price": 138_225_000, "take_profit_price": 151_050_000,
    },
    {
        "symbol": "KRW-ETH", "exchange": "upbit", "strategy": "trend_following",
        "entry_price": 4_200_000, "current_price": 4_350_000,
        "quantity": 0.35, "pnl": 52_500, "pnl_ratio": 0.0357,
        "stop_price": 4_074_000, "take_profit_price": 4_452_000,
    },
    {
        "symbol": "NVDA", "exchange": "kis_overseas", "strategy": "trend_following",
        "entry_price": 890.50, "current_price": 912.30,
        "quantity": 5, "pnl": 109_000, "pnl_ratio": 0.0245,
        "stop_price": 863.79, "take_profit_price": 943.93,
    },
]

_MOCK_TRADES = [
    {"timestamp": "2026-02-21T14:30:00", "exchange": "upbit", "symbol": "KRW-BTC",
     "strategy": "smc", "side": "buy", "price": 142_500_000, "quantity": 0.0105, "pnl": None},
    {"timestamp": "2026-02-21T13:15:00", "exchange": "upbit", "symbol": "KRW-SOL",
     "strategy": "rsi_reversal", "side": "sell", "price": 285_000, "quantity": 2.1, "pnl": 12_600},
    {"timestamp": "2026-02-21T11:50:00", "exchange": "upbit", "symbol": "KRW-ETH",
     "strategy": "trend_following", "side": "buy", "price": 4_200_000, "quantity": 0.35, "pnl": None},
    {"timestamp": "2026-02-21T10:20:00", "exchange": "kis_overseas", "symbol": "NVDA",
     "strategy": "trend_following", "side": "buy", "price": 890.50, "quantity": 5, "pnl": None},
    {"timestamp": "2026-02-21T09:45:00", "exchange": "kis_overseas", "symbol": "AAPL",
     "strategy": "trend_following", "side": "sell", "price": 228.30, "quantity": 10, "pnl": 45_000},
    {"timestamp": "2026-02-21T09:10:00", "exchange": "kis_domestic", "symbol": "005930",
     "strategy": "rsi_reversal", "side": "sell", "price": 63_800, "quantity": 50, "pnl": -28_000},
    {"timestamp": "2026-02-20T15:20:00", "exchange": "upbit", "symbol": "KRW-BTC",
     "strategy": "bollinger_breakout", "side": "sell", "price": 141_800_000, "quantity": 0.008, "pnl": 85_600},
    {"timestamp": "2026-02-20T13:40:00", "exchange": "upbit", "symbol": "KRW-SOL",
     "strategy": "smc", "side": "buy", "price": 278_000, "quantity": 2.1, "pnl": None},
    {"timestamp": "2026-02-20T11:20:00", "exchange": "kis_domestic", "symbol": "000660",
     "strategy": "trend_following", "side": "sell", "price": 198_500, "quantity": 15, "pnl": 42_000},
    {"timestamp": "2026-02-19T14:30:00", "exchange": "kis_overseas", "symbol": "TSLA",
     "strategy": "turtle", "side": "sell", "price": 312.50, "quantity": 8, "pnl": -62_000},
]

_MOCK_STRATEGY_STATS = [
    {"strategy": "smc", "trade_count": 8, "win_count": 5,
     "win_rate": 0.625, "avg_return": 0.0215, "total_pnl": 126_000},
    {"strategy": "trend_following", "trade_count": 7, "win_count": 5,
     "win_rate": 0.714, "avg_return": 0.0185, "total_pnl": 98_500},
    {"strategy": "rsi_reversal", "trade_count": 3, "win_count": 2,
     "win_rate": 0.667, "avg_return": 0.0120, "total_pnl": 24_600},
    {"strategy": "bollinger_breakout", "trade_count": 1, "win_count": 1,
     "win_rate": 1.0, "avg_return": 0.0302, "total_pnl": 85_600},
    {"strategy": "turtle", "trade_count": 1, "win_count": 0,
     "win_rate": 0.0, "avg_return": -0.0218, "total_pnl": -62_000},
]

_MOCK_PNL_CHART = _mock_pnl_chart()


def set_bot_context(ctx: dict):
    global _bot_context
    _bot_context = ctx


def is_running() -> bool:
    return _bot_running


# ── HTML ────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ── REST API ─────────────────────────────────────────────────────
@app.get("/api/summary")
async def get_summary():
    if _bot_context is None:
        return _MOCK_SUMMARY
    portfolio = _bot_context.get("portfolio")
    storage = _bot_context.get("storage")
    if portfolio is None:
        return _MOCK_SUMMARY
    summary = portfolio.summary()
    daily = storage.get_daily_summary() if storage else {"total_pnl": 0, "trade_count": 0, "win_count": 0}
    total_asset = _bot_context.get("total_asset", 0)
    return {
        "total_asset": total_asset,
        "daily_pnl": daily["total_pnl"],
        "daily_pnl_ratio": daily["total_pnl"] / total_asset if total_asset > 0 else 0,
        "win_rate": summary["win_rate"],
        "win_count": summary["win_count"],
        "trade_count": summary["trade_count"],
        "active_positions": summary["active_positions"],
        "bot_running": _bot_running,
    }


@app.get("/api/positions")
async def get_positions():
    if _bot_context is None:
        return _MOCK_POSITIONS
    portfolio = _bot_context.get("portfolio")
    if portfolio is None:
        return _MOCK_POSITIONS
    return portfolio.summary().get("positions", [])


@app.get("/api/trades")
async def get_trades(limit: int = 20):
    if _bot_context is None:
        return _MOCK_TRADES[:limit]
    storage = _bot_context.get("storage")
    if storage is None:
        return _MOCK_TRADES[:limit]
    return storage.get_recent_trades(limit)


@app.get("/api/pnl-chart")
async def get_pnl_chart(days: int = 30):
    if _bot_context is None:
        return {"pnl": _MOCK_PNL_CHART[-days:], "buy_dates": [], "sell_dates": []}
    storage = _bot_context.get("storage")
    if storage is None:
        return {"pnl": _MOCK_PNL_CHART[-days:], "buy_dates": [], "sell_dates": []}
    pnl = storage.get_pnl_chart_data(days)
    events = storage.get_trade_events(days)
    return {"pnl": pnl, **events}


@app.get("/api/strategy-stats")
async def get_strategy_stats():
    if _bot_context is None:
        return _MOCK_STRATEGY_STATS
    storage = _bot_context.get("storage")
    if storage is None:
        return _MOCK_STRATEGY_STATS
    return storage.get_strategy_stats()


@app.post("/api/bot/stop")
async def stop_bot():
    global _bot_running
    _bot_running = False
    ctx = _bot_context or {}
    if "stop_event" in ctx:
        ctx["stop_event"].set()
    await _broadcast({"type": "bot_status", "running": False})
    return {"status": "stopped"}


@app.post("/api/bot/resume")
async def resume_bot():
    global _bot_running
    _bot_running = True
    ctx = _bot_context or {}
    if "stop_event" in ctx:
        ctx["stop_event"].clear()
    await _broadcast({"type": "bot_status", "running": True})
    return {"status": "running"}


# ── WebSocket ────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.append(websocket)
    try:
        while True:
            await asyncio.sleep(3)
            if _bot_context:
                portfolio = _bot_context.get("portfolio")
                if portfolio:
                    data = {
                        "type": "portfolio_update",
                        "positions": portfolio.summary().get("positions", []),
                        "unrealized_pnl": portfolio.unrealized_pnl,
                        "bot_running": _bot_running,
                        "timestamp": datetime.now().isoformat(),
                    }
                    await websocket.send_json(data)
    except WebSocketDisconnect:
        _ws_clients.remove(websocket)
    except Exception as e:
        logger.debug(f"WebSocket 연결 종료: {e}")
        if websocket in _ws_clients:
            _ws_clients.remove(websocket)


async def _broadcast(data: dict):
    dead = []
    for ws in _ws_clients:
        try:
            await ws.send_json(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.remove(ws)


# ── 종목 분석 헬퍼 ────────────────────────────────────────────────
def _calc_signal_markers(df) -> list[dict]:
    """과거 OHLCV에서 터틀·추세추종 전략 시그널 발생 날짜 반환 (최근 120봉 기준)"""
    import pandas as pd
    markers = []
    df = df.copy()

    # ── 터틀 전략 시그널 ──────────────────────────────────────────
    if len(df) >= 56:
        high55 = df["high"].shift(1).rolling(55).max()
        low20 = df["low"].rolling(20).min()
        for i in range(55, len(df)):
            ts = str(df.index[i])[:10]
            c = float(df["close"].iloc[i])
            prev_c = float(df["close"].iloc[i - 1])
            h55 = float(high55.iloc[i]) if not pd.isna(high55.iloc[i]) else None
            l20 = float(low20.iloc[i]) if not pd.isna(low20.iloc[i]) else None
            if h55 and prev_c <= h55 < c:
                markers.append({"time": ts, "type": "turtle_buy",  "text": "터틀매수"})
            elif l20 and c < l20:
                markers.append({"time": ts, "type": "turtle_sell", "text": "터틀청산"})

    # ── 추세추종 전략 시그널 ─────────────────────────────────────
    if len(df) >= 201:
        ma20  = df["close"].rolling(20).mean()
        ma200 = df["close"].rolling(200).mean()
        for i in range(200, len(df)):
            ts = str(df.index[i])[:10]
            if pd.isna(ma20.iloc[i - 1]) or pd.isna(ma200.iloc[i - 1]):
                continue
            if float(ma20.iloc[i - 1]) <= float(ma200.iloc[i - 1]) and float(ma20.iloc[i]) > float(ma200.iloc[i]):
                markers.append({"time": ts, "type": "trend_buy",  "text": "추세매수"})
            elif float(ma20.iloc[i - 1]) >= float(ma200.iloc[i - 1]) and float(ma20.iloc[i]) < float(ma200.iloc[i]):
                markers.append({"time": ts, "type": "trend_sell", "text": "추세청산"})

    # 최근 120봉 범위로 자르기
    cutoff = str(df.index[-120])[:10] if len(df) >= 120 else str(df.index[0])[:10]
    markers = [m for m in markers if m["time"] >= cutoff]
    # 같은 날짜에 중복 마커 제거 (type 기준 최초 1개)
    seen: set[str] = set()
    deduped = []
    for m in markers:
        key = m["time"] + m["type"]
        if key not in seen:
            seen.add(key)
            deduped.append(m)
    return deduped


def _calc_turtle(df) -> tuple[str, str]:
    """터틀 전략 시그널: 55일 신고가 돌파 / 20일 최저가 이탈"""
    if len(df) < 56:
        return "HOLD", "데이터 부족 (55봉 미만)"
    high55 = float(df["high"].rolling(55).max().iloc[-2])
    low20 = float(df["low"].rolling(20).min().iloc[-1])
    curr = float(df["close"].iloc[-1])
    prev = float(df["close"].iloc[-2])
    if prev <= high55 < curr:
        return "BUY", "55일 신고가 돌파"
    if curr < low20:
        return "SELL", "20일 최저가 이탈"
    return "HOLD", "신호 없음"


def _calc_trend(df) -> tuple[str, str]:
    """추세추종 전략 시그널: MA20/MA200 골든크로스·데드크로스"""
    if len(df) < 201:
        if len(df) < 21:
            return "HOLD", "데이터 부족 (20봉 미만)"
        ma20 = df["close"].rolling(20).mean()
        direction = "상승" if float(ma20.iloc[-1]) > float(ma20.iloc[-10]) else "하락"
        return "HOLD", f"MA200 데이터 부족 — {direction} 중"
    ma20 = df["close"].rolling(20).mean()
    ma200 = df["close"].rolling(200).mean()
    if float(ma20.iloc[-2]) <= float(ma200.iloc[-2]) and float(ma20.iloc[-1]) > float(ma200.iloc[-1]):
        return "BUY", "MA20/MA200 골든크로스"
    if float(ma20.iloc[-2]) >= float(ma200.iloc[-2]) and float(ma20.iloc[-1]) < float(ma200.iloc[-1]):
        return "SELL", "MA20/MA200 데드크로스"
    trend = "상승 추세" if float(ma20.iloc[-1]) > float(ma200.iloc[-1]) else "하락 추세"
    return "HOLD", f"{trend} 유지 중"


def _fetch_naver_fchart(code: str, timeframe: str = "day", count: int = 300) -> "pd.DataFrame":
    """네이버 fchart XML → OHLCV DataFrame (24시간 동작)
    일봉: timeframe=day, count=300
    분봉: timeframe=minute (count 무시, 최근 ~6거래일치 반환)
    """
    import xml.etree.ElementTree as ET
    import pandas as pd
    import requests as _req

    resp = _req.get(
        "https://fchart.stock.naver.com/sise.nhn",
        params={"symbol": code, "timeframe": timeframe, "count": count, "requestType": "0"},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=15,
    )
    resp.raise_for_status()
    root = ET.fromstring(resp.content.decode("euc-kr", errors="replace"))
    rows = []
    for item in root.iter("item"):
        parts = item.attrib.get("data", "").split("|")
        if len(parts) < 6:
            continue
        try:
            c = float(parts[4]) if parts[4] != "null" else None
            if c is None:
                continue
            o = float(parts[1]) if parts[1] != "null" else c
            h = float(parts[2]) if parts[2] != "null" else c
            l = float(parts[3]) if parts[3] != "null" else c
            v = float(parts[5]) if parts[5] != "null" else 0.0
            rows.append({"date": parts[0].strip(), "open": o, "high": h, "low": l, "close": c, "volume": v})
        except (ValueError, IndexError):
            continue
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    fmt = "%Y%m%d" if timeframe == "day" else "%Y%m%d%H%M"
    df["date"] = pd.to_datetime(df["date"], format=fmt)
    df = df.set_index("date").sort_index()
    return df[["open", "high", "low", "close", "volume"]]


async def _fetch_ohlcv(symbol: str, market: str, interval: str):
    """종목별 OHLCV 수집 (코인/국내/해외)"""
    import pandas as pd

    if market == "coin":
        import pyupbit
        iv_map = {"1m": "minute1", "5m": "minute5", "15m": "minute15", "1h": "minute60", "1d": "day"}
        count_map = {"1d": 300, "1h": 200, "15m": 200, "5m": 200, "1m": 200}
        pv_iv = iv_map.get(interval, "day")
        count = count_map.get(interval, 300)
        df = await asyncio.to_thread(pyupbit.get_ohlcv, symbol, pv_iv, count)
        if df is None or df.empty:
            return None
        df.columns = [c.lower() for c in df.columns]
        return df[["open", "high", "low", "close", "volume"]]

    elif market == "domestic":
        def _fchart_domestic():
            if interval == "1d":
                return _fetch_naver_fchart(symbol, "day", 300)
            # 분봉: fchart minute → 리샘플
            df_min = _fetch_naver_fchart(symbol, "minute")
            if df_min.empty:
                return df_min
            resample_map = {"1h": "1h", "15m": "15min", "5m": "5min", "1m": "1min"}
            rule = resample_map.get(interval, "1min")
            return (
                df_min.resample(rule)
                .agg(open=("open", "first"), high=("high", "max"),
                     low=("low", "min"), close=("close", "last"), volume=("volume", "sum"))
                .dropna(subset=["close"])
            )
        df = await asyncio.to_thread(_fchart_domestic)
        if df is None or df.empty:
            return None
        return df[["open", "high", "low", "close", "volume"]]

    elif market == "overseas":
        import yfinance as yf
        period_map = {"1d": "1y", "1h": "60d", "15m": "5d", "5m": "5d", "1m": "5d"}
        iv_map = {"1d": "1d", "1h": "1h", "15m": "15m", "5m": "5m", "1m": "1m"}
        yf_period = period_map.get(interval, "1y")
        yf_iv = iv_map.get(interval, "1d")
        df = await asyncio.to_thread(
            yf.download, symbol, period=yf_period, interval=yf_iv,
            progress=False, auto_adjust=True,
        )
        if df is None or df.empty:
            return None
        import pandas as pd
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
        df = df[["open", "high", "low", "close", "volume"]]
        df = df.dropna(subset=["open", "high", "low", "close"])
        df["volume"] = df["volume"].fillna(0)
        return df

    return None


def _resolve_domestic_symbol(query: str) -> str:
    """국내 주식 종목명 → 코드 변환 (숫자면 그대로 반환)
    스크리너 캐시(domestic_candidates.json) 우선 사용 → 네이버 API 폴백
    """
    if query.isdigit():
        return query
    # 1순위: 스크리너 캐시 (주말/야간에도 동작)
    try:
        import json
        from pathlib import Path
        cache_path = Path(__file__).parent.parent / "data" / "domestic_candidates.json"
        if cache_path.exists():
            for code, market, name in json.loads(cache_path.read_text()):
                if name == query:
                    return code
    except Exception:
        pass
    # 2순위: 네이버 금융 자동완성 API
    try:
        import requests as _req
        resp = _req.get(
            "https://ac.finance.naver.com/ac",
            params={"q": query, "target": "stock"},
            timeout=5,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        data = resp.json()
        raw = data.get("items", [])
        candidates = raw[0] if raw and isinstance(raw[0], list) and raw[0] and isinstance(raw[0][0], list) else raw
        for item in candidates:
            if len(item) >= 2 and item[1] == query:
                return item[0]
        if candidates:
            return candidates[0][0]
    except Exception:
        pass
    return query  # 변환 실패 시 원본 반환


@app.get("/api/analyze")
async def analyze_symbol(symbol: str, market: str = "overseas", interval: str = "1d"):
    """종목 분석: 전략 시그널 + 기술점수 + 매매 추천"""
    try:
        from bot.screener import Screener

        if market == "domestic":
            resolved = await asyncio.to_thread(_resolve_domestic_symbol, symbol)
            if not resolved.isdigit():
                return {"symbol": symbol, "error": f"종목명 '{symbol}'을 찾을 수 없습니다. 코드(예: 005930)로 직접 입력해주세요."}
            symbol = resolved

        df = await _fetch_ohlcv(symbol, market, interval)
        if df is None or len(df) < 20:
            return {"symbol": symbol, "error": f"데이터 부족 (20봉 미만) — 종목코드가 맞는지 확인해주세요."}

        current_price = float(df["close"].iloc[-1])
        tech_score, trend, reasons = Screener._tech_score(df)

        turtle_signal, turtle_reason = _calc_turtle(df)
        trend_signal, trend_reason = _calc_trend(df)

        signals = [
            {"strategy": "turtle", "signal": turtle_signal, "reason": turtle_reason},
            {"strategy": "trend_following", "signal": trend_signal, "reason": trend_reason},
        ]

        action = "BUY" if any(s["signal"] == "BUY" for s in signals) else (
            "SELL" if any(s["signal"] == "SELL" for s in signals) else "HOLD"
        )
        rec = {
            "action": action,
            "buy_price": current_price,
            "stop_loss": round(current_price * 0.97, 4),
            "stop_loss_pct": -3.0,
            "target": round(current_price * 1.06, 4),
            "target_pct": 6.0,
        }

        import math
        ohlcv = []
        for idx, row in df.tail(120).iterrows():
            o, h, l, c, v = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"]), float(row["volume"])
            if any(math.isnan(x) or math.isinf(x) for x in [o, h, l, c]):
                continue
            ohlcv.append({
                "time": str(idx)[:10],
                "open": o, "high": h, "low": l, "close": c,
                "volume": 0.0 if math.isnan(v) else v,
            })

        # 거래 이력 (해당 종목)
        trades = []
        if _bot_context:
            storage = _bot_context.get("storage")
            if storage:
                try:
                    raw = storage.get_trades_by_symbol(symbol)
                    trades = [
                        {
                            "date": t["timestamp"][:10],
                            "side": t["side"],
                            "strategy": t["strategy"],
                            "price": t["price"],
                            "reason": t.get("reason", ""),
                        }
                        for t in raw
                    ]
                except Exception:
                    pass

        signal_markers = _calc_signal_markers(df)

        return {
            "symbol": symbol,
            "current_price": current_price,
            "tech_score": tech_score,
            "trend": trend,
            "reasons": reasons,
            "ohlcv": ohlcv,
            "signals": signals,
            "recommendation": rec,
            "trades": trades,
            "signal_markers": signal_markers,
            "error": None,
        }
    except Exception as e:
        logger.error(f"[분석] {symbol} 오류: {e}")
        return {"symbol": symbol, "error": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
