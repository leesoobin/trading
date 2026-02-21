"""이평선 쌍바닥/눌림목 전략 (MA Pullback)
5/20/60 EMA 정배열/역배열 확인 → 쌍바닥/쌍봉 패턴 탐지 → 눌림목 진입
목표 승률: 50~60%, 목표 RR: 1:2~1:3
"""
import pandas as pd

from bot.strategy.base import Signal, Strategy


class MAPullbackStrategy(Strategy):
    """
    이평선 쌍바닥/눌림목 전략:
    - 5/20/60 EMA 정배열(상승) / 역배열(하락) 확인
    - 쌍바닥(롱) / 쌍봉(숏) 패턴 탐지
    - 이평선 눌림목에서 5EMA 돌파 시 진입
    """
    name = "ma_pullback"

    def __init__(self, config: dict = None):
        super().__init__(config)
        self._ema_fast = 5
        self._ema_mid = 20
        self._ema_slow = 60
        self._double_tolerance = 0.015  # 쌍바닥/쌍봉 동일 수준 허용 오차 1.5%
        self._pullback_lookback = 30

    def _ema(self, series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()

    def _alignment(self, df: pd.DataFrame) -> str:
        """
        정배열: ema5 > ema20 > ema60 → 'bullish'
        역배열: ema5 < ema20 < ema60 → 'bearish'
        수렴: 'none'
        """
        ema5 = self._ema(df["close"], self._ema_fast).iloc[-1]
        ema20 = self._ema(df["close"], self._ema_mid).iloc[-1]
        ema60 = self._ema(df["close"], self._ema_slow).iloc[-1]

        if ema5 > ema20 > ema60:
            return "bullish"
        if ema5 < ema20 < ema60:
            return "bearish"
        return "none"

    def _detect_double_bottom(self, df: pd.DataFrame, lookback: int = 30) -> bool:
        """
        쌍바닥: 최근 N봉 내에서 비슷한 수준의 저점이 2개 형성
        조건: 두 저점 간격 5봉 이상, 허용 오차 1.5% 이내
        """
        lows = []
        window = df["low"].iloc[-lookback:]
        for i in range(5, len(window) - 5):
            local_min = window.iloc[i - 5:i + 5].min()
            if window.iloc[i] == local_min:
                lows.append((i, window.iloc[i]))

        if len(lows) < 2:
            return False

        # 가장 최근 두 저점 비교
        for i in range(len(lows) - 1, 0, -1):
            p1_idx, p1_val = lows[i]
            p2_idx, p2_val = lows[i - 1]
            if abs(p1_val - p2_val) / max(p2_val, 1e-9) <= self._double_tolerance:
                if abs(p1_idx - p2_idx) >= 5:  # 간격 5봉 이상
                    return True
        return False

    def _detect_double_top(self, df: pd.DataFrame, lookback: int = 30) -> bool:
        """쌍봉: 최근 N봉 내에서 비슷한 수준의 고점 2개 형성"""
        highs = []
        window = df["high"].iloc[-lookback:]
        for i in range(5, len(window) - 5):
            local_max = window.iloc[i - 5:i + 5].max()
            if window.iloc[i] == local_max:
                highs.append((i, window.iloc[i]))

        if len(highs) < 2:
            return False

        for i in range(len(highs) - 1, 0, -1):
            p1_idx, p1_val = highs[i]
            p2_idx, p2_val = highs[i - 1]
            if abs(p1_val - p2_val) / max(p2_val, 1e-9) <= self._double_tolerance:
                if abs(p1_idx - p2_idx) >= 5:
                    return True
        return False

    def _is_ema_pullback(self, df: pd.DataFrame, alignment: str) -> tuple[bool, str]:
        """
        이평선 눌림목 확인:
        - 정배열에서 가격이 5EMA 또는 20EMA에 접근/터치
        - 역배열에서 가격이 5EMA 또는 20EMA로 반등
        Returns: (is_pullback, grade)  grade: 'A'(5EMA) | 'B'(20EMA) | 'none'
        """
        price = df["close"].iloc[-1]
        ema5_s = self._ema(df["close"], self._ema_fast)
        ema20_s = self._ema(df["close"], self._ema_mid)
        ema5 = ema5_s.iloc[-1]
        ema20 = ema20_s.iloc[-1]
        tol = price * 0.005  # 0.5% 허용 오차

        if alignment == "bullish":
            if abs(price - ema5) <= tol or price < ema5:
                return True, "A"
            if abs(price - ema20) <= tol or (ema5 > ema20 and price < ema20 * 1.01):
                return True, "B"
        elif alignment == "bearish":
            if abs(price - ema5) <= tol or price > ema5:
                return True, "A"
            if abs(price - ema20) <= tol or (ema5 < ema20 and price > ema20 * 0.99):
                return True, "B"
        return False, "none"

    def _ema5_breakout(self, df: pd.DataFrame, direction: str) -> bool:
        """5EMA 돌파 확인 (진입 트리거)"""
        ema5 = self._ema(df["close"], self._ema_fast)
        curr_close = df["close"].iloc[-1]
        prev_close = df["close"].iloc[-2]
        curr_ema5 = ema5.iloc[-1]
        prev_ema5 = ema5.iloc[-2]

        if direction == "bullish":
            # 이전 봉: EMA5 아래, 현재 봉: EMA5 위 (상방 돌파)
            return prev_close <= prev_ema5 and curr_close > curr_ema5
        else:
            # 이전 봉: EMA5 위, 현재 봉: EMA5 아래 (하방 이탈)
            return prev_close >= prev_ema5 and curr_close < curr_ema5

    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        min_len = self._ema_slow + self._pullback_lookback + 10
        if len(df) < min_len:
            self._reason = f"데이터 부족 ({len(df)}/{min_len})"
            return Signal.HOLD

        alignment = self._alignment(df)
        if alignment == "none":
            self._reason = "[MA Pullback] 이평선 수렴 - No Trade Zone"
            return Signal.HOLD

        is_pullback, pb_grade = self._is_ema_pullback(df, alignment)

        if alignment == "bullish":
            double_bottom = self._detect_double_bottom(df, self._pullback_lookback)
            breakout = self._ema5_breakout(df, "bullish")

            if is_pullback and (breakout or double_bottom):
                db_str = " + 쌍바닥" if double_bottom else ""
                bo_str = " + 5EMA 돌파" if breakout else ""
                self._reason = f"[MA Pullback] 정배열 {pb_grade}급 눌림목{db_str}{bo_str} → 매수"
                return Signal.BUY

        elif alignment == "bearish":
            double_top = self._detect_double_top(df, self._pullback_lookback)
            breakout = self._ema5_breakout(df, "bearish")

            if is_pullback and (breakout or double_top):
                dt_str = " + 쌍봉" if double_top else ""
                bo_str = " + 5EMA 이탈" if breakout else ""
                self._reason = f"[MA Pullback] 역배열 {pb_grade}급 눌림목{dt_str}{bo_str} → 매도"
                return Signal.SELL

        self._reason = f"[MA Pullback] 대기 (배열={alignment}, 눌림목={'O' if is_pullback else 'X'})"
        return Signal.HOLD

    def get_reason(self) -> str:
        return self._reason
