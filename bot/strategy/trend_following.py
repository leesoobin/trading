import pandas as pd

from bot.strategy.base import Signal, Strategy
from bot.indicators import calc_ma, is_new_high, avg_volume


class TrendFollowingStrategy(Strategy):
    """MA 크로스오버 + 52주 신고가 추세추종 전략"""

    def __init__(self, config: dict = None):
        super().__init__(config)
        ind = self._config.get("indicators", {})
        self._ma_short = ind.get("ma_short", 20)
        self._ma_long = ind.get("ma_long", 200)
        self._volume_mult = 1.5
        self._min_gain = 0.01  # 전일비 최소 +1%

    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        if len(df) < self._ma_long + 1:
            self._reason = f"데이터 부족 ({len(df)}/{self._ma_long + 1})"
            return Signal.HOLD

        ma_short = calc_ma(df, self._ma_short)
        ma_long = calc_ma(df, self._ma_long)

        if ma_short.isna().iloc[-1] or ma_long.isna().iloc[-1]:
            self._reason = "MA 계산 불가"
            return Signal.HOLD

        curr_short = ma_short.iloc[-1]
        curr_long = ma_long.iloc[-1]
        prev_short = ma_short.iloc[-2]
        prev_long = ma_long.iloc[-2]

        current_close = df["close"].iloc[-1]
        prev_close = df["close"].iloc[-2]
        daily_gain = (current_close - prev_close) / prev_close

        vol_avg = avg_volume(df)
        curr_vol = df["volume"].iloc[-1]
        vol_surge = curr_vol > vol_avg * self._volume_mult

        # 골든크로스 (단기 MA가 장기 MA 상향 돌파)
        golden_cross = (prev_short <= prev_long) and (curr_short > curr_long)
        # 정배열 + 조건 확인
        bullish_alignment = curr_short > curr_long and daily_gain >= self._min_gain and vol_surge
        # 52주 신고가
        new_high_signal = is_new_high(df)

        # 데드크로스 (단기 MA가 장기 MA 하향 돌파)
        dead_cross = (prev_short >= prev_long) and (curr_short < curr_long)

        if dead_cross:
            self._reason = f"데드크로스 (MA{self._ma_short}={curr_short:.2f} < MA{self._ma_long}={curr_long:.2f})"
            return Signal.SELL

        if golden_cross:
            self._reason = f"골든크로스 (MA{self._ma_short}={curr_short:.2f} > MA{self._ma_long}={curr_long:.2f})"
            return Signal.BUY

        if new_high_signal and bullish_alignment:
            self._reason = f"52주 신고가 돌파 + 정배열 (거래량 {curr_vol/vol_avg:.1f}x)"
            return Signal.BUY

        self._reason = f"조건 미충족 (MA{self._ma_short}={curr_short:.2f}, MA{self._ma_long}={curr_long:.2f})"
        return Signal.HOLD

    def get_reason(self) -> str:
        return self._reason
