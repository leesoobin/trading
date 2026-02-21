"""SMC 횡보 박스권 매매 전략 (Range Trading)
횡보 구간 확정 → False Breakout(박스 경계 스윕) → 반대 방향 진입
목표 승률: 50~55%, 목표 RR: 1:1~1:2
"""
import pandas as pd

from bot.strategy.base import Signal, Strategy


class SMCRangeTradingStrategy(Strategy):
    """
    박스권 매매:
    - 이평선 수렴 + 스윙 포인트 3개+ = 횡보 확정
    - 박스 상/하단 False Breakout 감지 → 반전 진입
    """
    name = "smc_range"

    def __init__(self, config: dict = None):
        super().__init__(config)
        self._swing_n = 5
        self._ma_short = 20
        self._ma_long = 60
        self._range_threshold = 0.04   # 박스 범위 최대 4%
        self._breakout_tolerance = 0.005  # False Breakout 허용 오차 0.5%

    def _swing_highs(self, df: pd.DataFrame, n: int) -> list[int]:
        return [i for i in range(n, len(df) - n)
                if df["high"].iloc[i] == df["high"].iloc[i - n:i + n + 1].max()]

    def _swing_lows(self, df: pd.DataFrame, n: int) -> list[int]:
        return [i for i in range(n, len(df) - n)
                if df["low"].iloc[i] == df["low"].iloc[i - n:i + n + 1].min()]

    def _is_ranging(self, df: pd.DataFrame, sh: list[int], sl: list[int]) -> tuple[bool, float, float]:
        """
        횡보 판단: 스윙 포인트 3개+, MA 수렴, BOS 없음
        Returns: (is_ranging, box_top, box_bottom)
        """
        if len(sh) < 2 or len(sl) < 2:
            return False, 0, 0

        # 최근 스윙 고/저점으로 박스 범위 계산
        recent_sh = [df["high"].iloc[i] for i in sh[-4:]]
        recent_sl = [df["low"].iloc[i] for i in sl[-4:]]

        box_top = max(recent_sh)
        box_bottom = min(recent_sl)
        box_range = (box_top - box_bottom) / box_bottom if box_bottom > 0 else 0

        if box_range > self._range_threshold:
            return False, box_top, box_bottom

        # MA 수렴 확인
        ma_s = df["close"].rolling(self._ma_short).mean()
        ma_l = df["close"].rolling(self._ma_long).mean()
        if ma_s.isna().iloc[-1] or ma_l.isna().iloc[-1]:
            return False, box_top, box_bottom

        ma_diff_ratio = abs(ma_s.iloc[-1] - ma_l.iloc[-1]) / ma_l.iloc[-1]
        ma_converging = ma_diff_ratio < 0.02  # MA 2% 이내 수렴

        # 스윙 포인트 3개+ (총 sh + sl >= 3)
        enough_swings = len(sh) >= 2 and len(sl) >= 2

        is_ranging = ma_converging and enough_swings
        return is_ranging, box_top, box_bottom

    def _detect_false_breakout(self, df: pd.DataFrame, box_top: float, box_bottom: float) -> str:
        """
        False Breakout 감지:
        - 꼬리가 박스 경계 돌파 후 몸통이 박스 안쪽으로 복귀
        Returns: 'false_up'(상방 페이크 → 숏) | 'false_down'(하방 페이크 → 롱) | 'none'
        """
        prev = df.iloc[-2]
        curr = df.iloc[-1]

        tol = box_bottom * self._breakout_tolerance

        # 상방 False Breakout: 꼬리가 박스 상단 돌파, 현재 종가가 박스 안으로 복귀
        if prev["high"] > box_top + tol and curr["close"] < box_top:
            return "false_up"

        # 하방 False Breakout: 꼬리가 박스 하단 돌파, 현재 종가가 박스 안으로 복귀
        if prev["low"] < box_bottom - tol and curr["close"] > box_bottom:
            return "false_down"

        # 당일 캔들에서 False Breakout
        if curr["high"] > box_top + tol and curr["close"] < box_top:
            return "false_up"
        if curr["low"] < box_bottom - tol and curr["close"] > box_bottom:
            return "false_down"

        return "none"

    def _confirm_reversal(self, df: pd.DataFrame, direction: str) -> bool:
        """반전 확인 캔들: Hammer, Engulfing, 방향성 캔들"""
        last = df.iloc[-1]
        prev = df.iloc[-2]
        rng = last["high"] - last["low"]
        if rng == 0:
            return False

        if direction == "bullish":
            # Hammer
            lower_wick = min(last["open"], last["close"]) - last["low"]
            if lower_wick > rng * 0.5 and last["close"] > last["open"]:
                return True
            # Bullish Engulfing
            if last["close"] > last["open"] and last["close"] > prev["high"] and last["open"] < prev["low"]:
                return True
            # 양봉
            if last["close"] > last["open"] and (last["close"] - last["open"]) > rng * 0.5:
                return True
        else:
            # Shooting Star
            upper_wick = last["high"] - max(last["open"], last["close"])
            if upper_wick > rng * 0.5 and last["close"] < last["open"]:
                return True
            # Bearish Engulfing
            if last["close"] < last["open"] and last["close"] < prev["low"] and last["open"] > prev["high"]:
                return True
            # 음봉
            if last["close"] < last["open"] and (last["open"] - last["close"]) > rng * 0.5:
                return True
        return False

    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        min_len = self._swing_n * 2 + self._ma_long + 10
        if len(df) < min_len:
            self._reason = f"데이터 부족 ({len(df)}/{min_len})"
            return Signal.HOLD

        price = df["close"].iloc[-1]
        sh = self._swing_highs(df, self._swing_n)
        sl = self._swing_lows(df, self._swing_n)

        is_ranging, box_top, box_bottom = self._is_ranging(df, sh, sl)
        if not is_ranging or box_top == 0 or box_bottom == 0:
            self._reason = f"[Range] 횡보 미확정 - 대기"
            return Signal.HOLD

        midpoint = (box_top + box_bottom) / 2
        fb = self._detect_false_breakout(df, box_top, box_bottom)

        if fb == "false_down":
            if self._confirm_reversal(df, "bullish"):
                self._reason = f"[Range] 박스 하단 False Breakout → 롱 (박스: {box_bottom:.0f}~{box_top:.0f})"
                return Signal.BUY

        if fb == "false_up":
            if self._confirm_reversal(df, "bearish"):
                self._reason = f"[Range] 박스 상단 False Breakout → 숏 (박스: {box_bottom:.0f}~{box_top:.0f})"
                return Signal.SELL

        # 박스 하단 구간 진입 (False Breakout 없어도 반전 캔들이면)
        zone = (box_top - box_bottom) * 0.2
        if price < box_bottom + zone and self._confirm_reversal(df, "bullish"):
            self._reason = f"[Range] 박스 하단 Zone 롱 진입"
            return Signal.BUY

        if price > box_top - zone and self._confirm_reversal(df, "bearish"):
            self._reason = f"[Range] 박스 상단 Zone 숏 진입"
            return Signal.SELL

        self._reason = f"[Range] 박스권 대기 (상단={box_top:.0f}, 중앙={midpoint:.0f}, 하단={box_bottom:.0f})"
        return Signal.HOLD

    def get_reason(self) -> str:
        return self._reason
