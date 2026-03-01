import pandas as pd

from bot.strategy.base import Signal, Strategy
from bot.indicators import calc_bollinger, avg_volume


class BollingerBreakoutStrategy(Strategy):
    """볼린저 스퀴즈 브레이크아웃 전략

    진입 조건:
      - 상단 밴드 돌파 (prev_close <= upper → curr_close > upper)
      - 거래량 급증 (1.5× 20봉 평균)
      - 스퀴즈 직후 (밴드폭이 40봉 평균의 80% 이하 상태에서 돌파)

    청산 조건:
      1. 전략 SELL: 상단 밴드 아래로 되돌림 → 브레이크아웃 실패
      2. 익절 +6% (main.py에서 risk.py TP 사용)
      3. 손절 -3% (main.py에서 risk.py SL 사용)

    ※ 하단 반등 평균회귀 진입은 제거 (RR < 1 구조 문제)
    """

    def __init__(self, config: dict = None):
        super().__init__(config)
        ind = self._config.get("indicators", {})
        self._period = ind.get("bollinger_period", 20)
        self._std = ind.get("bollinger_std", 2.0)
        self._volume_mult = 1.5

    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        if len(df) < max(self._period + 2, 42):
            self._reason = f"데이터 부족 ({len(df)})"
            return Signal.HOLD

        upper, mid, lower = calc_bollinger(df, self._period, self._std)

        if upper.isna().iloc[-1] or mid.isna().iloc[-1]:
            self._reason = "볼린저밴드 계산 불가"
            return Signal.HOLD

        curr_close = float(df["close"].iloc[-1])
        prev_close = float(df["close"].iloc[-2])
        curr_upper = float(upper.iloc[-1])
        prev_upper = float(upper.iloc[-2])
        curr_lower = float(lower.iloc[-1])
        curr_mid = float(mid.iloc[-1])

        vol_avg = avg_volume(df)
        curr_vol = float(df["volume"].iloc[-1])
        vol_surge = curr_vol > vol_avg * self._volume_mult

        # ── 스퀴즈 체크 (밴드폭 수축 확인) ─────────────────────────
        bw = (upper - lower) / mid.replace(0, float("nan"))
        bw_now = float(bw.iloc[-1]) if not bw.isna().iloc[-1] else 999
        bw_avg = float(bw.iloc[-40:].mean()) if len(df) >= 40 else bw_now
        in_squeeze = bw_now < bw_avg * 0.80  # 현재 밴드폭이 40봉 평균의 80% 이하

        # ── BUY: 상단 돌파 + 거래량 + 스퀴즈 직후 ───────────────
        if prev_close <= prev_upper and curr_close > curr_upper and vol_surge and in_squeeze:
            bw_pct = bw_now / bw_avg * 100
            self._reason = (
                f"볼린저 브레이크아웃 (상단={curr_upper:.2f}, 거래량 {curr_vol/vol_avg:.1f}x, "
                f"밴드폭 {bw_pct:.0f}%)"
            )
            return Signal.BUY

        # ── SELL: 상단 밴드 아래로 되돌림 (브레이크아웃 실패) ──────
        if prev_close > curr_upper and curr_close <= curr_upper:
            self._reason = (
                f"브레이크아웃 실패 — 상단 재이탈 ({curr_close:.2f} ≤ 상단={curr_upper:.2f})"
            )
            return Signal.SELL

        self._reason = (
            f"대기 (상단={curr_upper:.2f}, 중심={curr_mid:.2f}, "
            f"밴드폭={bw_now/bw_avg*100:.0f}%)"
        )
        return Signal.HOLD

    def get_reason(self) -> str:
        return self._reason
