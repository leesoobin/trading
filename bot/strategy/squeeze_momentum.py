"""Squeeze Momentum — BB × Keltner 채널 변동성 수축/확산

데이트레이딩 | 5분봉, 15분봉

LazyBear 방식:
  - Squeeze ON : BB(20,2)가 KC(20,1.5) 내부에 완전히 들어올 때
  - Squeeze OFF: BB가 KC 밖으로 나올 때 → 에너지 방출
  - Momentum : Linreg(Close - midpoint, length)
      midpoint = mean(HH[length], LL[length], SMA[length])

BUY : Squeeze가 켜졌다가 꺼지는 시점(OFF) + Momentum 양수(상승)
SELL: Squeeze OFF + Momentum 음수(하락)

HOLD: Squeeze ON(수축 중) 또는 momentum 신호 불명확
"""
import numpy as np
import pandas as pd

from bot.strategy.base import Signal, Strategy


def _linreg_slope(series: pd.Series, length: int) -> float:
    """단순 선형회귀 기울기 (마지막 length개 값)"""
    y = series.iloc[-length:].values
    if len(y) < length or np.isnan(y).any():
        return 0.0
    x = np.arange(length, dtype=float)
    m = np.polyfit(x, y, 1)[0]
    return float(m)


def _linreg_val(series: pd.Series, length: int) -> pd.Series:
    """Rolling linear regression value (마지막 점의 fitted value)"""
    out = pd.Series(np.nan, index=series.index)
    arr = series.values.astype(float)
    for i in range(length - 1, len(arr)):
        y = arr[i - length + 1: i + 1]
        if np.isnan(y).any():
            continue
        x = np.arange(length, dtype=float)
        p = np.polyfit(x, y, 1)
        out.iloc[i] = np.polyval(p, length - 1)
    return out


class SqueezeMomentumStrategy(Strategy):
    """BB × Keltner 스퀴즈 모멘텀"""

    def __init__(self, config: dict = None):
        super().__init__(config)
        self._bb_len   = int(self._config.get("squeeze_bb_len",   20))
        self._bb_mult  = float(self._config.get("squeeze_bb_mult",  2.0))
        self._kc_len   = int(self._config.get("squeeze_kc_len",   20))
        self._kc_mult  = float(self._config.get("squeeze_kc_mult",  1.5))
        self._mom_len  = int(self._config.get("squeeze_mom_len",  12))

    def _compute(self, df: pd.DataFrame):
        close = df["close"].astype(float)
        high  = df["high"].astype(float)
        low   = df["low"].astype(float)
        n = self._bb_len

        # Bollinger Bands
        bb_mid   = close.rolling(n).mean()
        bb_std   = close.rolling(n).std()
        bb_upper = bb_mid + self._bb_mult * bb_std
        bb_lower = bb_mid - self._bb_mult * bb_std

        # True Range for ATR (Keltner)
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low  - prev_close).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(self._kc_len).mean()
        kc_upper = bb_mid + self._kc_mult * atr
        kc_lower = bb_mid - self._kc_mult * atr

        # Squeeze: BB inside KC
        squeeze = (bb_upper < kc_upper) & (bb_lower > kc_lower)

        # Momentum value (LazyBear)
        hh   = high.rolling(self._mom_len).max()
        ll   = low.rolling(self._mom_len).min()
        mid  = (hh + ll) / 2
        delta = close - (mid + bb_mid) / 2
        mom = _linreg_val(delta, self._mom_len)

        return squeeze, mom

    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        min_bars = self._bb_len + self._mom_len + 10
        if len(df) < min_bars:
            self._reason = f"Squeeze 데이터 부족 ({len(df)}/{min_bars})"
            return Signal.HOLD

        squeeze, mom = self._compute(df)

        sq_now  = bool(squeeze.iloc[-1])
        sq_prev = bool(squeeze.iloc[-2])
        mom_now = float(mom.iloc[-1]) if not np.isnan(mom.iloc[-1]) else 0.0
        mom_prev = float(mom.iloc[-2]) if not np.isnan(mom.iloc[-2]) else 0.0

        # Squeeze가 켜졌다가 꺼지는 순간 = "불꽃 점화"
        squeeze_fire = sq_prev and not sq_now  # OFF 전환

        if squeeze_fire:
            if mom_now > 0:
                self._reason = (
                    f"Squeeze BUY — 스퀴즈 점화 + 모멘텀 양수 "
                    f"(mom={mom_now:.4g}, 전={mom_prev:.4g})"
                )
                return Signal.BUY
            elif mom_now < 0:
                self._reason = (
                    f"Squeeze SELL — 스퀴즈 점화 + 모멘텀 음수 "
                    f"(mom={mom_now:.4g})"
                )
                return Signal.SELL

        sq_state = "수축중" if sq_now else "확산중"
        self._reason = (
            f"Squeeze HOLD — {sq_state} "
            f"(mom={mom_now:.4g}, fire={squeeze_fire})"
        )
        return Signal.HOLD

    def get_reason(self) -> str:
        return self._reason
