import uuid
import hashlib
import urllib.parse
import asyncio
import json
import logging
from typing import Optional
import time

import jwt
import requests
import websockets
import pandas as pd

logger = logging.getLogger(__name__)

UPBIT_REST = "https://api.upbit.com/v1"
UPBIT_WS = "wss://api.upbit.com/websocket/v1"


class UpbitClient:
    def __init__(self, access_key: str, secret_key: str):
        self.access_key = access_key
        self.secret_key = secret_key
        self._last_req_time = 0.0

    def _auth_header(self, query_params: dict = None) -> dict:
        payload = {"access_key": self.access_key, "nonce": str(uuid.uuid4())}
        if query_params:
            query_string = urllib.parse.urlencode(query_params, doseq=True).encode()
            m = hashlib.sha512()
            m.update(query_string)
            query_hash = m.hexdigest()
            payload["query_hash"] = query_hash
            payload["query_hash_alg"] = "SHA512"
        token = jwt.encode(payload, self.secret_key, algorithm="HS256")
        return {"Authorization": f"Bearer {token}"}

    def _throttle(self, gap: float = 0.125):
        now = time.time()
        diff = now - self._last_req_time
        if diff < gap:
            time.sleep(gap - diff)
        self._last_req_time = time.time()

    # ── 시장 데이터 ──────────────────────────────────────────────
    def get_candles(self, symbol: str, interval: str = "15", count: int = 200) -> pd.DataFrame:
        self._throttle()
        url = f"{UPBIT_REST}/candles/minutes/{interval}"
        params = {"market": symbol, "count": count}
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        df = pd.DataFrame(data)
        df = df.rename(columns={
            "candle_date_time_utc": "datetime",
            "opening_price": "open",
            "high_price": "high",
            "low_price": "low",
            "trade_price": "close",
            "candle_acc_trade_volume": "volume",
        })
        df = df[["datetime", "open", "high", "low", "close", "volume"]].copy()
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        return df

    def get_ticker(self, symbols: list[str]) -> list[dict]:
        self._throttle()
        url = f"{UPBIT_REST}/ticker"
        params = {"markets": ",".join(symbols)}
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    # ── 계좌 ──────────────────────────────────────────────────────
    def get_accounts(self) -> list[dict]:
        self._throttle()
        headers = self._auth_header()
        resp = requests.get(f"{UPBIT_REST}/accounts", headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def get_balance(self, currency: str = "KRW") -> float:
        accounts = self.get_accounts()
        for acc in accounts:
            if acc["currency"] == currency:
                return float(acc["balance"])
        return 0.0

    # ── 주문 ──────────────────────────────────────────────────────
    def place_market_buy(self, symbol: str, price: float) -> dict:
        self._throttle(0.2)
        body = {
            "market": symbol,
            "side": "bid",
            "price": str(price),
            "ord_type": "price",
        }
        headers = self._auth_header(body)
        resp = requests.post(f"{UPBIT_REST}/orders", headers=headers, json=body, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def place_market_sell(self, symbol: str, volume: float) -> dict:
        self._throttle(0.2)
        body = {
            "market": symbol,
            "side": "ask",
            "volume": str(volume),
            "ord_type": "market",
        }
        headers = self._auth_header(body)
        resp = requests.post(f"{UPBIT_REST}/orders", headers=headers, json=body, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def place_limit_order(self, symbol: str, side: str, price: float, volume: float) -> dict:
        """side: 'bid' (매수) or 'ask' (매도)"""
        self._throttle(0.2)
        body = {
            "market": symbol,
            "side": side,
            "price": str(price),
            "volume": str(volume),
            "ord_type": "limit",
        }
        headers = self._auth_header(body)
        resp = requests.post(f"{UPBIT_REST}/orders", headers=headers, json=body, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def cancel_order(self, order_uuid: str) -> dict:
        self._throttle(0.2)
        params = {"uuid": order_uuid}
        headers = self._auth_header(params)
        resp = requests.delete(f"{UPBIT_REST}/order", headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    # ── WebSocket ─────────────────────────────────────────────────
    async def subscribe_ticker(self, symbols: list[str], callback):
        subscribe_msg = [
            {"ticket": str(uuid.uuid4())},
            {"type": "ticker", "codes": symbols},
        ]
        async with websockets.connect(UPBIT_WS) as ws:
            await ws.send(json.dumps(subscribe_msg))
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=30)
                    data = json.loads(raw)
                    await callback(data)
                except asyncio.TimeoutError:
                    logger.warning("Upbit WebSocket timeout, reconnecting...")
                    break
                except Exception as e:
                    logger.error(f"Upbit WebSocket error: {e}")
                    break
