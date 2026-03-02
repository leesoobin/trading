"""Mansfield Relative Strength (RS) — 장기 시장강도

스윙/포지션 | 주봉, 일봉

Mansfield RS 공식:
  RS_line = Close / Index_Close
  RS = (RS_line / SMA52_of_RS_line - 1) * 100

  RS > 0: 시장 대비 강세 (0선 위)
  RS < 0: 시장 대비 약세 (0선 아래)

BUY : RS가 0선을 상향 돌파 (장기 우상향 시작)
SELL: RS가 0선을 하향 이탈 (상대 강세 종료)

인덱스 데이터:
  - overseas  : SPY (S&P 500 ETF) via yfinance
  - upbit     : 비트코인(KRW-BTC) via pyupbit
  - KOSPI     : KODEX200(069500) via 네이버 fchart
  - KOSDAQ    : KODEX코스닥150(229200) via 네이버 fchart
  실패 시 내부 52주 SMA 대비로 fallback (Simplified RS)
"""
import logging
import time
from typing import Optional

import pandas as pd

from bot.strategy.base import Signal, Strategy

logger = logging.getLogger(__name__)

# 인덱스 캐시: {market_key: (fetch_ts, df)}
_INDEX_CACHE: dict[str, tuple[float, pd.Series]] = {}
_CACHE_TTL = 3600.0  # 1시간


def _fetch_index_close(market: str) -> Optional[pd.Series]:
    """시장별 인덱스 종가 시리즈 반환 (캐시 적용)"""
    now = time.time()
    if market in _INDEX_CACHE:
        ts, series = _INDEX_CACHE[market]
        if now - ts < _CACHE_TTL:
            return series

    try:
        if market in ("overseas", "NAS", "NYSE"):
            import yfinance as yf
            df = yf.download("SPY", period="2y", interval="1d",
                             progress=False, auto_adjust=True)
            if df is None or df.empty:
                return None
            if hasattr(df.columns, "droplevel"):
                try:
                    df.columns = df.columns.droplevel(1)
                except Exception:
                    pass
            series = df["Close"].dropna()

        elif market in ("KOSPI",):
            import requests, xml.etree.ElementTree as ET
            resp = requests.get(
                "https://fchart.stock.naver.com/sise.nhn",
                params={"symbol": "069500", "timeframe": "day",
                        "count": 300, "requestType": "0"},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=15,
            )
            root = ET.fromstring(resp.content.decode("euc-kr", errors="replace"))
            rows = []
            for item in root.iter("item"):
                parts = item.attrib.get("data", "").split("|")
                if len(parts) >= 5:
                    try:
                        d = parts[0]
                        ts_str = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
                        rows.append((pd.Timestamp(ts_str), float(parts[4])))
                    except Exception:
                        continue
            if not rows:
                return None
            series = pd.Series({t: v for t, v in rows}).sort_index()

        elif market in ("KOSDAQ",):
            import requests, xml.etree.ElementTree as ET
            resp = requests.get(
                "https://fchart.stock.naver.com/sise.nhn",
                params={"symbol": "229200", "timeframe": "day",
                        "count": 300, "requestType": "0"},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=15,
            )
            root = ET.fromstring(resp.content.decode("euc-kr", errors="replace"))
            rows = []
            for item in root.iter("item"):
                parts = item.attrib.get("data", "").split("|")
                if len(parts) >= 5:
                    try:
                        d = parts[0]
                        ts_str = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
                        rows.append((pd.Timestamp(ts_str), float(parts[4])))
                    except Exception:
                        continue
            if not rows:
                return None
            series = pd.Series({t: v for t, v in rows}).sort_index()

        elif market in ("upbit", "coin"):
            import pyupbit
            df = pyupbit.get_ohlcv("KRW-BTC", interval="day", count=300)
            if df is None or df.empty:
                return None
            series = df["close"].dropna()

        else:
            return None

        _INDEX_CACHE[market] = (time.time(), series)
        return series

    except Exception as e:
        logger.debug(f"[MansFieldRS] 인덱스 수집 실패 ({market}): {e}")
        return None


class MansFieldRSStrategy(Strategy):
    """Mansfield RS — 0선 기준 시장 상대강도"""

    def __init__(self, config: dict = None):
        super().__init__(config)
        self._sma_period = int(self._config.get("mansfield_sma", 52))  # 52주 = 약 260 거래일

    def _calc_rs(self, df: pd.DataFrame, index_series: Optional[pd.Series]) -> Optional[pd.Series]:
        """Mansfield RS 시리즈 계산. 인덱스 없으면 None"""
        if index_series is None or len(index_series) < self._sma_period:
            return None

        close = df["close"].astype(float)

        # 날짜 기준 정렬 후 공통 날짜만 사용
        try:
            if not isinstance(df.index, pd.DatetimeIndex):
                return None
            common = close.index.intersection(index_series.index)
            if len(common) < self._sma_period:
                return None
            stock_c = close.loc[common]
            idx_c   = index_series.loc[common]
            rs_line = stock_c / idx_c
            sma52   = rs_line.rolling(self._sma_period).mean()
            rs      = (rs_line / sma52 - 1) * 100
            return rs
        except Exception:
            return None

    def _simplified_rs(self, df: pd.DataFrame) -> pd.Series:
        """인덱스 없을 때 fallback: 종목 자체 52주 SMA 대비"""
        close = df["close"].astype(float)
        sma52 = close.rolling(self._sma_period).mean()
        return (close / sma52 - 1) * 100

    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        if len(df) < self._sma_period + 5:
            self._reason = f"MansFieldRS 데이터 부족 ({len(df)}/{self._sma_period + 5})"
            return Signal.HOLD

        # 시장 종류 추론 (symbol 길이로 간단 판별)
        if symbol.startswith("KRW-"):
            market = "upbit"
        elif len(symbol) == 6 and symbol.isdigit():
            market = "KOSPI"   # 기본값, KOSDAQ도 있지만 동일 계산
        else:
            market = "overseas"

        index_s = _fetch_index_close(market)
        rs = self._calc_rs(df, index_s)
        if rs is None:
            rs = self._simplified_rs(df)
            mode = "simplified"
        else:
            mode = "vs index"

        rs_now  = float(rs.iloc[-1]) if not pd.isna(rs.iloc[-1]) else 0.0
        rs_prev = float(rs.iloc[-2]) if not pd.isna(rs.iloc[-2]) else 0.0

        # 0선 상향 돌파 → BUY
        if rs_prev < 0 and rs_now >= 0:
            self._reason = (
                f"MansFieldRS BUY — 0선 상향 돌파 "
                f"(RS={rs_now:.2f}, mode={mode})"
            )
            return Signal.BUY

        # 0선 하향 이탈 → SELL
        if rs_prev >= 0 and rs_now < 0:
            self._reason = (
                f"MansFieldRS SELL — 0선 하향 이탈 "
                f"(RS={rs_now:.2f}, mode={mode})"
            )
            return Signal.SELL

        state = "강세(0선 위)" if rs_now >= 0 else "약세(0선 아래)"
        self._reason = (
            f"MansFieldRS HOLD — {state} "
            f"(RS={rs_now:.2f}, mode={mode})"
        )
        return Signal.HOLD

    def get_reason(self) -> str:
        return self._reason
