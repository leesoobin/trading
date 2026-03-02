"""Trend Template — 미너비니(Minervini) 8가지 상승 추세 조건

스윙/포지션 전략 | 일봉 권장

조건:
  1. 가격 > 150일 SMA AND 가격 > 200일 SMA
  2. 150일 SMA > 200일 SMA
  3. 200일 SMA가 최소 1개월(20봉) 동안 우상향
  4. 50일 SMA > 150일 SMA AND 50일 SMA > 200일 SMA
  5. 가격 > 50일 SMA
  6. 가격이 52주 최저가 대비 +30% 이상
  7. 가격이 52주 최고가 대비 -25% 이내

BUY : 7개 조건 모두 충족 (진입 타이밍은 52주 고가 부근 돌파)
SELL: 가격이 50일 SMA 아래로 이탈 (추세 붕괴)
"""
import pandas as pd

from bot.strategy.base import Signal, Strategy


class TrendTemplateStrategy(Strategy):
    """Minervini Trend Template — 7가지 추세 조건 필터"""

    MIN_BARS = 210  # 200일 SMA 계산에 필요한 최소 봉수

    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        if len(df) < self.MIN_BARS:
            self._reason = f"데이터 부족 ({len(df)}/{self.MIN_BARS})"
            return Signal.HOLD

        close = df["close"].astype(float)
        high  = df["high"].astype(float)
        low   = df["low"].astype(float)

        sma50  = close.rolling(50).mean()
        sma150 = close.rolling(150).mean()
        sma200 = close.rolling(200).mean()

        curr       = close.iloc[-1]
        s50        = sma50.iloc[-1]
        s150       = sma150.iloc[-1]
        s200       = sma200.iloc[-1]
        s200_month = sma200.iloc[-21]  # 1개월(21거래일) 전 200일SMA

        high_52w = high.iloc[-252:].max()
        low_52w  = low.iloc[-252:].min()

        # 조건 평가
        c1 = curr > s150 and curr > s200
        c2 = s150 > s200
        c3 = s200 > s200_month              # 200일SMA 우상향
        c4 = s50 > s150 and s50 > s200
        c5 = curr > s50
        c6 = curr >= low_52w * 1.30         # 52주 저가 +30% 이상
        c7 = curr >= high_52w * 0.75        # 52주 고가 -25% 이내

        conditions = [c1, c2, c3, c4, c5, c6, c7]
        passed = sum(conditions)

        # SELL: 50일SMA 이탈 (추세 붕괴)
        if not c5:
            self._reason = f"TrendTemplate SELL — 50일SMA({s50:.2f}) 이탈 (통과:{passed}/7)"
            return Signal.SELL

        # BUY: 7개 모두 통과
        if passed == 7:
            pct_from_high = (curr / high_52w - 1) * 100
            self._reason = (
                f"TrendTemplate BUY — 7/7 조건 충족 "
                f"(52주고가 {pct_from_high:+.1f}%, SMA50={s50:.2f})"
            )
            return Signal.BUY

        # 6/7: 조건 거의 충족, HOLD
        labels = ["가격>SMA150/200", "SMA150>200", "SMA200우상향",
                  "SMA50>SMA150/200", "가격>SMA50", "52주저가+30%", "52주고가-25%이내"]
        failed = [labels[i] for i, c in enumerate(conditions) if not c]
        self._reason = f"TrendTemplate HOLD — {passed}/7 충족 (미달: {', '.join(failed)})"
        return Signal.HOLD

    def get_reason(self) -> str:
        return self._reason
