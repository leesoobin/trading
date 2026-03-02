"""Tether Line — Donchian 채널 중심선 눌림목 전략

단기 스윙 | 60분봉, 일봉

로직:
  Donchian 채널:
    Upper = N봉 최고가
    Lower = N봉 최저가
    Mid (Tether Line) = (Upper + Lower) / 2

  Tether Line = 추세의 '생명선' — 상승 추세에서 지지, 하락 추세에서 저항

BUY  : 상승 추세 (가격 > SMA50) + 가격이 Tether Line까지 눌림 후 반등
        (이전봉이 Tether Line 아래에 터치, 현재봉이 Tether Line 위로 복귀)
SELL : 가격이 Tether Line 아래로 이탈 (추세 포기)
       또는 하락 추세 (가격 < SMA50) 중 Tether Line 저항 확인
"""
import pandas as pd

from bot.strategy.base import Signal, Strategy


class TetherLineStrategy(Strategy):
    """Donchian 중심선(Tether Line) 눌림목 전략"""

    def __init__(self, config: dict = None):
        super().__init__(config)
        self._donchian_n = int(self._config.get("tether_donchian_n", 20))
        self._trend_sma  = int(self._config.get("tether_trend_sma",  50))

    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        min_bars = max(self._donchian_n, self._trend_sma) + 10
        if len(df) < min_bars:
            self._reason = f"TetherLine 데이터 부족 ({len(df)}/{min_bars})"
            return Signal.HOLD

        close = df["close"].astype(float)
        high  = df["high"].astype(float)
        low   = df["low"].astype(float)

        don_upper = high.rolling(self._donchian_n).max()
        don_lower = low.rolling(self._donchian_n).min()
        tether    = (don_upper + don_lower) / 2  # Tether Line

        sma50 = close.rolling(self._trend_sma).mean()

        curr_close  = float(close.iloc[-1])
        prev_close  = float(close.iloc[-2])
        curr_tether = float(tether.iloc[-1])
        prev_tether = float(tether.iloc[-2])
        curr_sma50  = float(sma50.iloc[-1])

        uptrend   = curr_close > curr_sma50

        # 눌림 반등 탐지: 이전봉이 Tether 아래 → 현재봉이 Tether 위
        pullback_bounce = prev_close <= prev_tether and curr_close > curr_tether

        # BUY: 상승 추세 + Tether Line 눌림 반등
        if uptrend and pullback_bounce:
            self._reason = (
                f"TetherLine BUY — 상승 추세 중 Tether Line 눌림 반등 "
                f"(Tether={curr_tether:.4g}, 가격={curr_close:.4g}, SMA50={curr_sma50:.4g})"
            )
            return Signal.BUY

        # SELL: Tether Line 하방 이탈 (상승 추세 붕괴)
        if prev_close >= prev_tether and curr_close < curr_tether:
            self._reason = (
                f"TetherLine SELL — Tether Line 하방 이탈 "
                f"(Tether={curr_tether:.4g}, 가격={curr_close:.4g})"
            )
            return Signal.SELL

        pos = "위" if curr_close > curr_tether else "아래"
        trend = "상승" if uptrend else "하락"
        self._reason = (
            f"TetherLine HOLD — Tether {pos}, {trend} 추세 "
            f"(Tether={curr_tether:.4g})"
        )
        return Signal.HOLD

    def get_reason(self) -> str:
        return self._reason
