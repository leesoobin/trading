"""SuperTrend — ATR 기반 추세 추종 신호

데이트/스윙 공용 | 15분봉, 60분봉 (데이트) / 일봉 (스윙)

계산:
  ATR    = Average True Range (period)
  Basic Upper = (H+L)/2 + mult * ATR
  Basic Lower = (H+L)/2 - mult * ATR
  SuperTrend 방향:
    - 가격이 ST 위: 상승 추세 (ST = Lower Band 추적)
    - 가격이 ST 아래: 하락 추세 (ST = Upper Band 추적)

BUY : ST 방향이 하락→상승 전환 (가격이 ST 돌파)
SELL: ST 방향이 상승→하락 전환 (가격이 ST 하향 이탈)
"""
import numpy as np
import pandas as pd

from bot.strategy.base import Signal, Strategy


class SuperTrendStrategy(Strategy):
    """ATR 기반 SuperTrend 추세 추종"""

    def __init__(self, config: dict = None):
        super().__init__(config)
        self._period = int(self._config.get("supertrend_period", 7))
        self._mult   = float(self._config.get("supertrend_mult", 3.0))

    def _compute(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        """SuperTrend 시리즈와 방향(1=상승, -1=하락) 반환"""
        high  = df["high"].astype(float)
        low   = df["low"].astype(float)
        close = df["close"].astype(float)

        # True Range
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low  - prev_close).abs(),
        ], axis=1).max(axis=1)
        atr = tr.ewm(span=self._period, adjust=False).mean()

        hl2  = (high + low) / 2
        upper = hl2 + self._mult * atr
        lower = hl2 - self._mult * atr

        st      = pd.Series(np.nan, index=df.index)
        trend   = pd.Series(1,     index=df.index)

        for i in range(1, len(df)):
            prev_upper = upper.iloc[i - 1]
            prev_lower = lower.iloc[i - 1]

            # Final upper/lower (prevent band narrowing)
            final_upper = upper.iloc[i] if upper.iloc[i] < prev_upper or close.iloc[i - 1] > prev_upper else prev_upper
            final_lower = lower.iloc[i] if lower.iloc[i] > prev_lower or close.iloc[i - 1] < prev_lower else prev_lower

            upper.iloc[i] = final_upper
            lower.iloc[i] = final_lower

            prev_trend = trend.iloc[i - 1]
            if prev_trend == 1:
                if close.iloc[i] < final_lower:
                    trend.iloc[i] = -1
                    st.iloc[i]    = final_upper
                else:
                    trend.iloc[i] = 1
                    st.iloc[i]    = final_lower
            else:
                if close.iloc[i] > final_upper:
                    trend.iloc[i] = 1
                    st.iloc[i]    = final_lower
                else:
                    trend.iloc[i] = -1
                    st.iloc[i]    = final_upper

        return st, trend

    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        min_bars = self._period * 3 + 5
        if len(df) < min_bars:
            self._reason = f"SuperTrend 데이터 부족 ({len(df)}/{min_bars})"
            return Signal.HOLD

        st, trend = self._compute(df)

        curr_trend = trend.iloc[-1]
        prev_trend = trend.iloc[-2]
        curr_st    = st.iloc[-1]
        curr_close = float(df["close"].iloc[-1])

        # 추세 전환 감지
        if prev_trend == -1 and curr_trend == 1:
            self._reason = (
                f"SuperTrend BUY — 상승 전환 "
                f"(가격={curr_close:.4g}, ST={curr_st:.4g})"
            )
            return Signal.BUY

        if prev_trend == 1 and curr_trend == -1:
            self._reason = (
                f"SuperTrend SELL — 하락 전환 "
                f"(가격={curr_close:.4g}, ST={curr_st:.4g})"
            )
            return Signal.SELL

        direction = "상승" if curr_trend == 1 else "하락"
        self._reason = (
            f"SuperTrend HOLD — {direction} 추세 유지 "
            f"(ST={curr_st:.4g})"
        )
        return Signal.HOLD

    def get_reason(self) -> str:
        return self._reason
