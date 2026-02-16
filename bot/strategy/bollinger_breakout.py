import pandas as pd

from bot.strategy.base import Signal, Strategy
from bot.indicators import calc_bollinger, avg_volume


class BollingerBreakoutStrategy(Strategy):
    """볼린저밴드 상단 브레이크아웃 + 하단 평균회귀 전략"""

    def __init__(self, config: dict = None):
        super().__init__(config)
        ind = self._config.get("indicators", {})
        self._period = ind.get("bollinger_period", 20)
        self._std = ind.get("bollinger_std", 2.0)
        self._volume_mult = 1.5

    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        if len(df) < self._period + 2:
            self._reason = f"데이터 부족 ({len(df)})"
            return Signal.HOLD

        upper, mid, lower = calc_bollinger(df, self._period, self._std)

        if upper.isna().iloc[-1] or mid.isna().iloc[-1] or lower.isna().iloc[-1]:
            self._reason = "볼린저밴드 계산 불가"
            return Signal.HOLD

        curr_close = df["close"].iloc[-1]
        prev_close = df["close"].iloc[-2]
        curr_upper = upper.iloc[-1]
        curr_mid = mid.iloc[-1]
        curr_lower = lower.iloc[-1]
        prev_lower = lower.iloc[-2]

        vol_avg = avg_volume(df)
        curr_vol = df["volume"].iloc[-1]
        vol_surge = curr_vol > vol_avg * self._volume_mult

        # 상단 브레이크아웃: 가격이 상단 돌파 + 거래량 급증
        if prev_close <= upper.iloc[-2] and curr_close > curr_upper and vol_surge:
            self._reason = f"볼린저 상단 브레이크아웃 (가격={curr_close:.2f} > 상단={curr_upper:.2f}, 거래량 {curr_vol/vol_avg:.1f}x)"
            return Signal.BUY

        # 하단 평균회귀: 가격이 하단 이탈 후 반등
        if prev_close < prev_lower and curr_close >= curr_lower:
            self._reason = f"볼린저 하단 반등 ({prev_close:.2f} → {curr_close:.2f}, 하단={curr_lower:.2f})"
            return Signal.BUY

        # 매도: 중심선 도달
        if prev_close < curr_mid and curr_close >= curr_mid:
            self._reason = f"볼린저 중심선 도달 ({curr_close:.2f} ≥ 중심={curr_mid:.2f})"
            return Signal.SELL

        # 매도: 상단 과열 후 하락
        if prev_close > curr_upper and curr_close <= curr_upper:
            self._reason = f"볼린저 상단 이탈 ({curr_close:.2f} ≤ 상단={curr_upper:.2f})"
            return Signal.SELL

        self._reason = f"볼린저 대기 (상단={curr_upper:.2f}, 중심={curr_mid:.2f}, 하단={curr_lower:.2f})"
        return Signal.HOLD

    def get_reason(self) -> str:
        return self._reason
