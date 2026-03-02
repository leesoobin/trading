"""Trendlines with Breaks — 피봇 기반 동적 추세선 돌파

데이트/스윙 공용 | 15분봉, 30분봉

로직:
  1. 최근 N봉에서 스윙 고점/저점 탐지 (pivot 기반)
  2. 최근 스윙 고점 2개를 연결해 하향 저항선(resistance) 계산
  3. 최근 스윙 저점 2개를 연결해 상향 지지선(support) 계산
  4. 현재 가격이 추세선을 돌파/이탈하면 신호

BUY : 현재가 > 저항 추세선 (상방 돌파) + 거래량 확인
SELL: 현재가 < 지지 추세선 (하방 이탈)
"""
import numpy as np
import pandas as pd

from bot.strategy.base import Signal, Strategy


class TrendlinesBreakStrategy(Strategy):
    """피봇 기반 추세선 돌파 전략"""

    def __init__(self, config: dict = None):
        super().__init__(config)
        self._pivot_n  = int(self._config.get("trendline_pivot_n",   5))   # 피봇 탐색 범위
        self._lookback = int(self._config.get("trendline_lookback", 60))   # 최근 N봉 내에서 피봇 탐색

    def _find_pivot_highs(self, high: pd.Series) -> list[int]:
        """스윙 고점 인덱스 목록 (정수 위치 기준)"""
        n = self._pivot_n
        highs = []
        arr = high.values
        for i in range(n, len(arr) - n):
            if arr[i] == arr[max(0, i - n):i + n + 1].max():
                highs.append(i)
        return highs

    def _find_pivot_lows(self, low: pd.Series) -> list[int]:
        """스윙 저점 인덱스 목록"""
        n = self._pivot_n
        lows = []
        arr = low.values
        for i in range(n, len(arr) - n):
            if arr[i] == arr[max(0, i - n):i + n + 1].min():
                lows.append(i)
        return lows

    def _trendline_at_now(self, indices: list[int], prices: np.ndarray, now_idx: int) -> float | None:
        """두 피봇을 잇는 추세선의 현재(now_idx) 값을 선형 보간으로 계산"""
        if len(indices) < 2:
            return None
        i1, i2 = indices[-2], indices[-1]
        p1, p2 = prices[i1], prices[i2]
        if i2 == i1:
            return None
        slope = (p2 - p1) / (i2 - i1)
        return p2 + slope * (now_idx - i2)

    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        min_bars = self._lookback + self._pivot_n * 2 + 5
        if len(df) < min_bars:
            self._reason = f"TrendlineBreak 데이터 부족 ({len(df)}/{min_bars})"
            return Signal.HOLD

        # 최근 lookback봉만 사용
        recent = df.iloc[-self._lookback:].copy()
        recent = recent.reset_index(drop=True)

        high  = recent["high"].astype(float)
        low   = recent["low"].astype(float)
        close = recent["close"].astype(float)

        ph = self._find_pivot_highs(high)
        pl = self._find_pivot_lows(low)

        now_idx   = len(recent) - 1
        curr_close = float(close.iloc[-1])
        prev_close = float(close.iloc[-2])

        # 저항 추세선 (하향 저항선 → 이것을 상방 돌파하면 BUY)
        res_val = self._trendline_at_now(ph, high.values, now_idx)
        # 지지 추세선 (상향 지지선 → 이것을 하방 이탈하면 SELL)
        sup_val = self._trendline_at_now(pl, low.values, now_idx)

        if res_val is not None and prev_close <= res_val < curr_close:
            self._reason = (
                f"TrendlineBreak BUY — 저항 추세선 상방 돌파 "
                f"(저항={res_val:.4g}, 현재가={curr_close:.4g})"
            )
            return Signal.BUY

        if sup_val is not None and prev_close >= sup_val > curr_close:
            self._reason = (
                f"TrendlineBreak SELL — 지지 추세선 하방 이탈 "
                f"(지지={sup_val:.4g}, 현재가={curr_close:.4g})"
            )
            return Signal.SELL

        res_str = f"{res_val:.4g}" if res_val else "없음"
        sup_str = f"{sup_val:.4g}" if sup_val else "없음"
        self._reason = (
            f"TrendlineBreak HOLD — 추세선 대기 "
            f"(저항={res_str}, 지지={sup_str}, 현재가={curr_close:.4g})"
        )
        return Signal.HOLD

    def get_reason(self) -> str:
        return self._reason
