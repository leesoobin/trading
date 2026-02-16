"""FastAPI 대시보드 서버 - http://localhost:8080"""
import asyncio
import json
import logging
from datetime import datetime
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
        return {"total_asset": 0, "daily_pnl": 0, "daily_pnl_ratio": 0,
                "win_rate": 0, "win_count": 0, "trade_count": 0, "active_positions": 0}
    portfolio = _bot_context.get("portfolio")
    storage = _bot_context.get("storage")
    if portfolio is None:
        return {}
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
        return []
    portfolio = _bot_context.get("portfolio")
    if portfolio is None:
        return []
    return portfolio.summary().get("positions", [])


@app.get("/api/trades")
async def get_trades(limit: int = 20):
    if _bot_context is None:
        return []
    storage = _bot_context.get("storage")
    if storage is None:
        return []
    return storage.get_recent_trades(limit)


@app.get("/api/pnl-chart")
async def get_pnl_chart(days: int = 30):
    if _bot_context is None:
        return []
    storage = _bot_context.get("storage")
    if storage is None:
        return []
    return storage.get_pnl_chart_data(days)


@app.get("/api/strategy-stats")
async def get_strategy_stats():
    if _bot_context is None:
        return []
    storage = _bot_context.get("storage")
    if storage is None:
        return []
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
