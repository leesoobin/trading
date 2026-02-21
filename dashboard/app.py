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
        return _MOCK_PNL_CHART[-days:]
    storage = _bot_context.get("storage")
    if storage is None:
        return _MOCK_PNL_CHART[-days:]
    return storage.get_pnl_chart_data(days)


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
