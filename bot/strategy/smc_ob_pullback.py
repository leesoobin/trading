"""SMC 추세추종 눌림목 전략 (OB Pullback)
BOS로 추세를 확인한 후, Fresh OB로 가격이 되돌아올 때 진입
목표 승률: 50~60%, 목표 RR: 1:2~1:3
"""
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from bot.strategy.base import Signal, Strategy


@dataclass
class OrderBlock:
    idx: int
    direction: str  # 'bullish' | 'bearish'
    top: float
    bottom: float
    has_fvg: bool = False


class SMCOBPullbackStrategy(Strategy):
    """
    SMC 추세추종 눌림목: BOS 확인 후 Fresh OB 되돌림 진입
    """
    name = "smc_ob_pullback"

    def __init__(self, config: dict = None):
        super().__init__(config)
        self._swing_n = 5
        self._ob_lookback = 40

    def _swing_highs(self, df: pd.DataFrame, n: int) -> list[int]:
        highs = []
        for i in range(n, len(df) - n):
            if df["high"].iloc[i] == df["high"].iloc[i - n:i + n + 1].max():
                highs.append(i)
        return highs

    def _swing_lows(self, df: pd.DataFrame, n: int) -> list[int]:
        lows = []
        for i in range(n, len(df) - n):
            if df["low"].iloc[i] == df["low"].iloc[i - n:i + n + 1].min():
                lows.append(i)
        return lows

    def _trend(self, df: pd.DataFrame, sh: list[int], sl: list[int]) -> str:
        if len(sh) < 2 or len(sl) < 2:
            return "none"
        sh_p = [df["high"].iloc[i] for i in sh[-3:]]
        sl_p = [df["low"].iloc[i] for i in sl[-3:]]
        bullish = len(sh_p) >= 2 and sh_p[-1] > sh_p[-2] and len(sl_p) >= 2 and sl_p[-1] > sl_p[-2]
        bearish = len(sh_p) >= 2 and sh_p[-1] < sh_p[-2] and len(sl_p) >= 2 and sl_p[-1] < sl_p[-2]
        if bullish:
            return "bullish"
        if bearish:
            return "bearish"
        return "none"

    def _bos(self, df: pd.DataFrame, sh: list[int], sl: list[int]) -> str:
        if len(sh) < 2 or len(sl) < 2:
            return "none"
        curr = df["close"].iloc[-1]
        prev = df["close"].iloc[-2]
        prev_sh = df["high"].iloc[sh[-2]]
        prev_sl = df["low"].iloc[sl[-2]]
        if prev <= prev_sh < curr:
            return "bullish_bos"
        if prev >= prev_sl > curr:
            return "bearish_bos"
        return "none"

    def _find_ob(self, df: pd.DataFrame, direction: str, price: float) -> Optional[OrderBlock]:
        lookback = min(self._ob_lookback, len(df) - 5)
        for i in range(1, lookback):
            idx = len(df) - 1 - i
            if idx < 2:
                break
            c = df.iloc[idx]
            nxt = df.iloc[idx + 1]
            if direction == "bullish" and c["close"] < c["open"] and nxt["close"] > c["high"]:
                if price >= c["low"]:
                    fvg = idx >= 1 and idx + 2 < len(df) and df.iloc[idx - 1]["high"] < df.iloc[idx + 2]["low"]
                    return OrderBlock(idx, "bullish", c["high"], c["low"], bool(fvg))
            if direction == "bearish" and c["close"] > c["open"] and nxt["close"] < c["low"]:
                if price <= c["high"]:
                    fvg = idx >= 1 and idx + 2 < len(df) and df.iloc[idx - 1]["low"] > df.iloc[idx + 2]["high"]
                    return OrderBlock(idx, "bearish", c["high"], c["low"], bool(fvg))
        return None

    def _confirm(self, df: pd.DataFrame, direction: str) -> bool:
        last = df.iloc[-1]
        prev = df.iloc[-2]
        rng = last["high"] - last["low"]
        if rng == 0:
            return False
        if direction == "bullish":
            lower_wick = min(last["open"], last["close"]) - last["low"]
            if lower_wick > rng * 0.6 and last["close"] > last["open"]:
                return True
            if last["close"] > last["open"] and last["close"] > prev["open"] and last["open"] < prev["close"]:
                return True
        else:
            upper_wick = last["high"] - max(last["open"], last["close"])
            if upper_wick > rng * 0.6 and last["close"] < last["open"]:
                return True
            if last["close"] < last["open"] and last["close"] < prev["open"] and last["open"] > prev["close"]:
                return True
        return False

    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        min_len = self._ob_lookback + self._swing_n * 2 + 5
        if len(df) < min_len:
            self._reason = f"데이터 부족 ({len(df)}/{min_len})"
            return Signal.HOLD

        price = df["close"].iloc[-1]
        sh = self._swing_highs(df, self._swing_n)
        sl = self._swing_lows(df, self._swing_n)
        trend = self._trend(df, sh, sl)

        if trend == "none":
            self._reason = "[OB Pullback] 추세 불명확 - 대기"
            return Signal.HOLD

        bos = self._bos(df, sh, sl)

        if trend == "bullish":
            ob = self._find_ob(df, "bullish", price)
            if ob and ob.bottom <= price <= ob.top:
                if self._confirm(df, "bullish") or bos == "bullish_bos":
                    grade = "A" if ob.has_fvg else "B"
                    self._reason = f"[OB Pullback] 상승추세 Demand OB({grade}) 터치{'+ FVG' if ob.has_fvg else ''}"
                    return Signal.BUY

        if trend == "bearish":
            ob = self._find_ob(df, "bearish", price)
            if ob and ob.bottom <= price <= ob.top:
                if self._confirm(df, "bearish") or bos == "bearish_bos":
                    grade = "A" if ob.has_fvg else "B"
                    self._reason = f"[OB Pullback] 하락추세 Supply OB({grade}) 터치{'+ FVG' if ob.has_fvg else ''}"
                    return Signal.SELL

        self._reason = f"[OB Pullback] 대기 (추세={trend})"
        return Signal.HOLD

    def get_reason(self) -> str:
        return self._reason
