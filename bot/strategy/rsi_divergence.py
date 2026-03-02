"""RSI Divergence — 가격-모멘텀 간의 괴리 감지

데트/스윙 공용 | 모든 타임프레임

종류:
  ■ 강세 다이버전스 (Bullish): 가격은 저저점, RSI는 고저점 → BUY
    → 하락 추세 약화, 반전 임박
  ■ 약세 다이버전스 (Bearish): 가격은 고고점, RSI는 저고점 → SELL
    → 상승 추세 약화, 고점 임박

탐지 방식:
  1. 최근 N봉에서 스윙 고점/저점 탐지
  2. 가장 최근 2개의 스윙 고/저점에서 가격·RSI 방향 비교
  3. 방향이 반대이면 다이버전스 확정
"""
import numpy as np
import pandas as pd

from bot.strategy.base import Signal, Strategy


class RSIDivergenceStrategy(Strategy):
    """RSI 다이버전스 — 추세 끝물 반전 포착"""

    def __init__(self, config: dict = None):
        super().__init__(config)
        self._rsi_period = int(self._config.get("rsi_period",   14))
        self._pivot_n    = int(self._config.get("div_pivot_n",   5))
        self._lookback   = int(self._config.get("div_lookback",  60))

    def _rsi(self, close: pd.Series) -> pd.Series:
        delta = close.diff()
        gain  = delta.clip(lower=0)
        loss  = (-delta).clip(lower=0)
        avg_gain = gain.ewm(alpha=1 / self._rsi_period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / self._rsi_period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.inf)
        return 100 - 100 / (1 + rs)

    def _find_swings(self, series: pd.Series, mode: str) -> list[int]:
        """mode='high' or 'low' — 스윙 인덱스 목록 반환 (정수 위치)"""
        n = self._pivot_n
        arr = series.values
        out = []
        for i in range(n, len(arr) - n):
            window = arr[max(0, i - n): i + n + 1]
            if mode == "high" and arr[i] == window.max():
                out.append(i)
            elif mode == "low" and arr[i] == window.min():
                out.append(i)
        return out

    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        min_bars = self._rsi_period + self._lookback + self._pivot_n * 2 + 5
        if len(df) < min_bars:
            self._reason = f"RSIDivergence 데이터 부족 ({len(df)}/{min_bars})"
            return Signal.HOLD

        recent = df.iloc[-(self._lookback + self._pivot_n * 2):].copy()
        recent = recent.reset_index(drop=True)

        close = recent["close"].astype(float)
        rsi   = self._rsi(close)

        # 끝 5봉은 피봇 탐지에서 제외 (미확정 피봇)
        search_end = len(recent) - self._pivot_n

        close_search = close.iloc[:search_end]
        rsi_search   = rsi.iloc[:search_end]

        sw_lows  = self._find_swings(close_search, "low")
        sw_highs = self._find_swings(close_search, "high")

        # ── 강세 다이버전스: 가격 저저점 + RSI 고저점 ──
        if len(sw_lows) >= 2:
            i1, i2 = sw_lows[-2], sw_lows[-1]
            price_lower = float(close.iloc[i2]) < float(close.iloc[i1])
            rsi_higher  = float(rsi.iloc[i2])   > float(rsi.iloc[i1])
            if price_lower and rsi_higher:
                p1, p2 = float(close.iloc[i1]), float(close.iloc[i2])
                r1, r2 = float(rsi.iloc[i1]),   float(rsi.iloc[i2])
                self._reason = (
                    f"RSIDivergence BUY — 강세 다이버전스 "
                    f"(가격: {p1:.4g}→{p2:.4g}↓, RSI: {r1:.1f}→{r2:.1f}↑)"
                )
                return Signal.BUY

        # ── 약세 다이버전스: 가격 고고점 + RSI 저고점 ──
        if len(sw_highs) >= 2:
            i1, i2 = sw_highs[-2], sw_highs[-1]
            price_higher = float(close.iloc[i2]) > float(close.iloc[i1])
            rsi_lower    = float(rsi.iloc[i2])   < float(rsi.iloc[i1])
            if price_higher and rsi_lower:
                p1, p2 = float(close.iloc[i1]), float(close.iloc[i2])
                r1, r2 = float(rsi.iloc[i1]),   float(rsi.iloc[i2])
                self._reason = (
                    f"RSIDivergence SELL — 약세 다이버전스 "
                    f"(가격: {p1:.4g}→{p2:.4g}↑, RSI: {r1:.1f}→{r2:.1f}↓)"
                )
                return Signal.SELL

        curr_rsi = float(rsi.iloc[-1])
        self._reason = (
            f"RSIDivergence HOLD — 다이버전스 없음 "
            f"(RSI={curr_rsi:.1f}, 저점수={len(sw_lows)}, 고점수={len(sw_highs)})"
        )
        return Signal.HOLD

    def get_reason(self) -> str:
        return self._reason
