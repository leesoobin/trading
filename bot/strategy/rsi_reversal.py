import pandas as pd

from bot.strategy.base import Signal, Strategy
from bot.indicators import calc_rsi, calc_ma


class RSIReversalStrategy(Strategy):
    """RSI(14) 과매수/과매도 역추세 전략"""

    def __init__(self, config: dict = None):
        super().__init__(config)
        ind = self._config.get("indicators", {})
        self._rsi_period = ind.get("rsi_period", 14)
        self._oversold = ind.get("rsi_oversold", 30)
        self._overbought = ind.get("rsi_overbought", 70)
        self._ma_long = ind.get("ma_long", 200)

    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        if len(df) < self._rsi_period + 2:
            self._reason = f"데이터 부족 ({len(df)})"
            return Signal.HOLD

        rsi = calc_rsi(df, self._rsi_period)
        ma_long = calc_ma(df, self._ma_long)

        if rsi.isna().iloc[-1]:
            self._reason = "RSI 계산 불가"
            return Signal.HOLD

        curr_rsi = rsi.iloc[-1]
        prev_rsi = rsi.iloc[-2]
        current_close = df["close"].iloc[-1]
        ma200 = ma_long.iloc[-1] if not ma_long.isna().iloc[-1] else None

        # 매수: RSI 과매도 탈출 + MA200 위
        if prev_rsi < self._oversold and curr_rsi >= self._oversold:
            above_ma200 = (ma200 is None or current_close > ma200)
            if above_ma200:
                self._reason = f"RSI 과매도 탈출 ({prev_rsi:.1f} → {curr_rsi:.1f}) / MA200 위"
                return Signal.BUY
            else:
                self._reason = f"RSI 과매도 탈출 ({curr_rsi:.1f}) / MA200 아래 → 스킵"
                return Signal.HOLD

        # 매도: RSI 과매수 진입
        if curr_rsi > self._overbought:
            self._reason = f"RSI 과매수 ({curr_rsi:.1f} > {self._overbought})"
            return Signal.SELL

        self._reason = f"RSI={curr_rsi:.1f} (과매도={self._oversold}, 과매수={self._overbought})"
        return Signal.HOLD

    def get_reason(self) -> str:
        return self._reason
