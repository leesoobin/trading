"""MACD 전략 — 이동평균 수렴/확산

스윙 | 60분봉, 일봉

계산:
  MACD Line   = EMA(12) - EMA(26)
  Signal Line = EMA(9) of MACD
  Histogram   = MACD - Signal

BUY : MACD가 Signal선을 상향 돌파 (골든크로스) + Histogram 양수 전환
SELL: MACD가 Signal선을 하향 이탈 (데드크로스) + Histogram 음수 전환

보조 조건 (과매도/과매수 필터):
  - BUY 신호는 MACD < 0 영역에서 더 유효 (저점 반등)
  - SELL 신호는 MACD > 0 영역에서 더 유효 (고점 꺾임)
"""
import pandas as pd

from bot.strategy.base import Signal, Strategy


class MACDStrategy(Strategy):
    """MACD 골든/데드크로스 전략"""

    def __init__(self, config: dict = None):
        super().__init__(config)
        self._fast   = int(self._config.get("macd_fast",   12))
        self._slow   = int(self._config.get("macd_slow",   26))
        self._signal = int(self._config.get("macd_signal",  9))

    def _compute(self, close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
        ema_fast = close.ewm(span=self._fast, adjust=False).mean()
        ema_slow = close.ewm(span=self._slow, adjust=False).mean()
        macd     = ema_fast - ema_slow
        signal   = macd.ewm(span=self._signal, adjust=False).mean()
        hist     = macd - signal
        return macd, signal, hist

    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        min_bars = self._slow + self._signal + 5
        if len(df) < min_bars:
            self._reason = f"MACD 데이터 부족 ({len(df)}/{min_bars})"
            return Signal.HOLD

        close = df["close"].astype(float)
        macd, sig, hist = self._compute(close)

        macd_now  = float(macd.iloc[-1])
        macd_prev = float(macd.iloc[-2])
        sig_now   = float(sig.iloc[-1])
        sig_prev  = float(sig.iloc[-2])
        hist_now  = float(hist.iloc[-1])
        hist_prev = float(hist.iloc[-2])

        # 골든크로스: MACD가 Signal 위로 (이전엔 아래)
        golden = macd_prev < sig_prev and macd_now >= sig_now
        # 데드크로스: MACD가 Signal 아래로
        dead   = macd_prev > sig_prev and macd_now <= sig_now

        if golden:
            strength = "강" if macd_now < 0 else "일반"
            self._reason = (
                f"MACD BUY — 골든크로스 ({strength}) "
                f"(MACD={macd_now:.4g}, Sig={sig_now:.4g}, Hist={hist_now:.4g})"
            )
            return Signal.BUY

        if dead:
            strength = "강" if macd_now > 0 else "일반"
            self._reason = (
                f"MACD SELL — 데드크로스 ({strength}) "
                f"(MACD={macd_now:.4g}, Sig={sig_now:.4g}, Hist={hist_now:.4g})"
            )
            return Signal.SELL

        cross = "위" if macd_now > sig_now else "아래"
        self._reason = (
            f"MACD HOLD — Signal선 {cross} "
            f"(MACD={macd_now:.4g}, Hist={hist_now:.4g})"
        )
        return Signal.HOLD

    def get_reason(self) -> str:
        return self._reason
