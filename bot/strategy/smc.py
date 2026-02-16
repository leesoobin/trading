"""
SMC (Smart Money Concepts) 전략
- Order Block (OB) 탐지
- Fair Value Gap (FVG) 탐지
- Break of Structure (BoS) / CHoCH
- Liquidity Sweep
"""
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
import numpy as np

from bot.strategy.base import Signal, Strategy


@dataclass
class OrderBlock:
    idx: int
    direction: str  # 'bullish' | 'bearish'
    top: float
    bottom: float


@dataclass
class FVG:
    idx: int
    direction: str  # 'bullish' | 'bearish'
    top: float
    bottom: float


class SMCStrategy(Strategy):
    """Smart Money Concepts: OB + FVG + BoS/CHoCH + Liquidity Sweep"""

    def __init__(self, config: dict = None):
        super().__init__(config)
        self._ob_lookback = 30
        self._fvg_lookback = 50
        self._swing_lookback = 5  # 스윙 고/저 탐지 범위

    def _find_swing_highs(self, df: pd.DataFrame, n: int = 5) -> list[int]:
        highs = []
        for i in range(n, len(df) - n):
            if df["high"].iloc[i] == df["high"].iloc[i - n:i + n + 1].max():
                highs.append(i)
        return highs

    def _find_swing_lows(self, df: pd.DataFrame, n: int = 5) -> list[int]:
        lows = []
        for i in range(n, len(df) - n):
            if df["low"].iloc[i] == df["low"].iloc[i - n:i + n + 1].min():
                lows.append(i)
        return lows

    def _detect_order_blocks(self, df: pd.DataFrame) -> list[OrderBlock]:
        obs = []
        lookback = min(self._ob_lookback, len(df) - 3)
        for i in range(1, lookback):
            idx = len(df) - 1 - i
            if idx < 2:
                break
            curr = df.iloc[idx]
            next_candle = df.iloc[idx + 1]
            # 불리시 OB: 하락 캔들 → 강한 상승 전환
            if curr["close"] < curr["open"]:  # 하락 캔들
                if next_candle["close"] > curr["high"]:  # 다음 캔들이 고점 돌파
                    obs.append(OrderBlock(
                        idx=idx,
                        direction="bullish",
                        top=curr["high"],
                        bottom=curr["low"],
                    ))
            # 베어리시 OB: 상승 캔들 → 강한 하락 전환
            elif curr["close"] > curr["open"]:  # 상승 캔들
                if next_candle["close"] < curr["low"]:  # 다음 캔들이 저점 돌파
                    obs.append(OrderBlock(
                        idx=idx,
                        direction="bearish",
                        top=curr["high"],
                        bottom=curr["low"],
                    ))
        return obs

    def _detect_fvg(self, df: pd.DataFrame) -> list[FVG]:
        fvgs = []
        lookback = min(self._fvg_lookback, len(df) - 2)
        for i in range(1, lookback):
            idx = len(df) - 1 - i
            if idx < 1:
                break
            prev = df.iloc[idx - 1]
            curr = df.iloc[idx]
            nxt = df.iloc[idx + 1]
            # 불리시 FVG: 첫 캔들 고점 ~ 세 번째 캔들 저점 사이 갭
            if prev["high"] < nxt["low"]:
                fvgs.append(FVG(
                    idx=idx,
                    direction="bullish",
                    top=nxt["low"],
                    bottom=prev["high"],
                ))
            # 베어리시 FVG
            elif prev["low"] > nxt["high"]:
                fvgs.append(FVG(
                    idx=idx,
                    direction="bearish",
                    top=prev["low"],
                    bottom=nxt["high"],
                ))
        return fvgs

    def _detect_bos(self, df: pd.DataFrame, swing_highs: list[int], swing_lows: list[int]) -> str:
        """
        BoS/CHoCH 감지
        Returns: 'bullish_bos' | 'bearish_bos' | 'choch_up' | 'choch_down' | 'none'
        """
        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return "none"

        curr_close = df["close"].iloc[-1]
        prev_close = df["close"].iloc[-2]

        # 최근 스윙 고점/저점
        last_sh = df["high"].iloc[swing_highs[-1]] if swing_highs else None
        last_sl = df["low"].iloc[swing_lows[-1]] if swing_lows else None
        prev_sh = df["high"].iloc[swing_highs[-2]] if len(swing_highs) >= 2 else None
        prev_sl = df["low"].iloc[swing_lows[-2]] if len(swing_lows) >= 2 else None

        # BoS 상승: 이전 스윙 고점 돌파 (추세 지속)
        if prev_sh and prev_close <= prev_sh < curr_close:
            return "bullish_bos"

        # BoS 하락: 이전 스윙 저점 이탈
        if prev_sl and prev_close >= prev_sl > curr_close:
            return "bearish_bos"

        # CHoCH (Change of Character): 하락 추세 중 스윙 고점 돌파 (반전)
        if last_sh and prev_close <= last_sh < curr_close:
            return "choch_up"

        # CHoCH: 상승 추세 중 스윙 저점 이탈 (반전)
        if last_sl and prev_close >= last_sl > curr_close:
            return "choch_down"

        return "none"

    def _detect_liquidity_sweep(self, df: pd.DataFrame, swing_highs: list[int], swing_lows: list[int]) -> str:
        """
        유동성 스윕: 이전 고점/저점 일시 돌파 후 반전
        Returns: 'sweep_high' (고점 스윕 → 하락 예상) | 'sweep_low' (저점 스윕 → 상승 예상) | 'none'
        """
        if len(df) < 3:
            return "none"

        prev_bar = df.iloc[-2]
        curr_bar = df.iloc[-1]

        if swing_highs:
            sh_price = df["high"].iloc[swing_highs[-1]]
            # 이전 봉이 고점 돌파 → 현재 봉이 되돌림
            if prev_bar["high"] > sh_price and curr_bar["close"] < sh_price:
                return "sweep_high"

        if swing_lows:
            sl_price = df["low"].iloc[swing_lows[-1]]
            # 이전 봉이 저점 돌파 → 현재 봉이 되돌림
            if prev_bar["low"] < sl_price and curr_bar["close"] > sl_price:
                return "sweep_low"

        return "none"

    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        min_len = self._ob_lookback + self._swing_lookback * 2 + 5
        if len(df) < min_len:
            self._reason = f"SMC 데이터 부족 ({len(df)}/{min_len})"
            return Signal.HOLD

        curr_close = df["close"].iloc[-1]

        swing_highs = self._find_swing_highs(df, self._swing_lookback)
        swing_lows = self._find_swing_lows(df, self._swing_lookback)
        obs = self._detect_order_blocks(df)
        fvgs = self._detect_fvg(df)
        bos = self._detect_bos(df, swing_highs, swing_lows)
        sweep = self._detect_liquidity_sweep(df, swing_highs, swing_lows)

        # 불리시 OB 터치 + BoS 확인 → 매수
        bullish_obs = [ob for ob in obs if ob.direction == "bullish"]
        for ob in bullish_obs:
            if ob.bottom <= curr_close <= ob.top:
                if bos in ("bullish_bos", "choch_up"):
                    self._reason = f"상승 OB 터치({ob.bottom:.2f}-{ob.top:.2f}) + {bos}"
                    return Signal.BUY

        # 불리시 FVG 채움 + CHoCH → 매수
        bullish_fvgs = [f for f in fvgs if f.direction == "bullish"]
        for fvg in bullish_fvgs:
            if fvg.bottom <= curr_close <= fvg.top:
                if bos == "choch_up":
                    self._reason = f"불리시 FVG 채움({fvg.bottom:.2f}-{fvg.top:.2f}) + CHoCH 상승"
                    return Signal.BUY

        # 저점 유동성 스윕 후 반전 → 매수
        if sweep == "sweep_low":
            self._reason = "저점 유동성 스윕 후 반전 (롱 진입)"
            return Signal.BUY

        # 베어리시 OB 터치 → 매도
        bearish_obs = [ob for ob in obs if ob.direction == "bearish"]
        for ob in bearish_obs:
            if ob.bottom <= curr_close <= ob.top:
                self._reason = f"하락 OB 터치({ob.bottom:.2f}-{ob.top:.2f}) + {bos}"
                return Signal.SELL

        # 고점 유동성 스윕 후 반전 → 매도
        if sweep == "sweep_high":
            self._reason = "고점 유동성 스윕 후 반전 (숏)"
            return Signal.SELL

        self._reason = f"SMC 대기 (BoS={bos}, OB수={len(obs)}, FVG수={len(fvgs)})"
        return Signal.HOLD

    def get_reason(self) -> str:
        return self._reason
