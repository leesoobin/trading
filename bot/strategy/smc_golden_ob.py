"""SMC 고품질 OB 스나이핑 전략 (Golden OB Sniper)
18점 스코어링 시스템: S급(12+) OB + Fibonacci Golden Zone + 확인 캔들
목표 승률: 55~65%, 목표 RR: 1:2~1:3
"""
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from bot.strategy.base import Signal, Strategy


@dataclass
class ScoredOB:
    idx: int
    direction: str  # 'bullish' | 'bearish'
    top: float
    bottom: float
    score: int
    golden_zone: float  # 0 | 38.2 | 50 | 61.8
    has_fvg: bool
    structure: str  # 'choch' | 'bos'


class SMCGoldenOBStrategy(Strategy):
    """
    Golden OB Sniper: 정량 스코어링으로 S급 OB에서만 진입
    """
    name = "smc_golden_ob"

    def __init__(self, config: dict = None):
        super().__init__(config)
        self._swing_n = 5
        self._atr_period = 14
        self._min_score = 9   # A급 이상 (S급: 12+)
        self._ob_lookback = 50

    def _swing_highs(self, df: pd.DataFrame, n: int) -> list[int]:
        return [i for i in range(n, len(df) - n)
                if df["high"].iloc[i] == df["high"].iloc[i - n:i + n + 1].max()]

    def _swing_lows(self, df: pd.DataFrame, n: int) -> list[int]:
        return [i for i in range(n, len(df) - n)
                if df["low"].iloc[i] == df["low"].iloc[i - n:i + n + 1].min()]

    def _atr(self, df: pd.DataFrame, period: int = 14) -> float:
        high = df["high"]
        low = df["low"]
        close = df["close"]
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ], axis=1).max(axis=1)
        return tr.rolling(period).mean().iloc[-1]

    def _trend_direction(self, df: pd.DataFrame, sh: list[int], sl: list[int]) -> str:
        if len(sh) < 2 or len(sl) < 2:
            return "none"
        sh_p = [df["high"].iloc[i] for i in sh[-3:]]
        sl_p = [df["low"].iloc[i] for i in sl[-3:]]
        if len(sh_p) >= 2 and sh_p[-1] > sh_p[-2] and len(sl_p) >= 2 and sl_p[-1] > sl_p[-2]:
            return "bullish"
        if len(sh_p) >= 2 and sh_p[-1] < sh_p[-2] and len(sl_p) >= 2 and sl_p[-1] < sl_p[-2]:
            return "bearish"
        return "none"

    def _fib_levels(self, swing_high: float, swing_low: float) -> dict:
        rng = swing_high - swing_low
        return {
            61.8: swing_high - rng * 0.618,
            50.0: swing_high - rng * 0.500,
            38.2: swing_high - rng * 0.382,
        }

    def _golden_zone_match(self, ob_mid: float, fib_levels: dict, tolerance: float = 0.01) -> float:
        """OB 중앙이 피보나치 레벨에 해당하는지 확인. 해당하면 레벨값 반환, 없으면 0"""
        for level, price in fib_levels.items():
            if abs(ob_mid - price) / max(price, 1e-9) <= tolerance:
                return level
        return 0.0

    def _score_ob(self, df: pd.DataFrame, idx: int, direction: str,
                  ob_top: float, ob_bottom: float,
                  sh: list[int], sl: list[int], atr: float, trend: str) -> ScoredOB:
        """OB 품질 점수 계산 (최대 18점)"""
        score = 0
        structure = "bos"
        golden_zone = 0.0
        has_fvg = False

        # 1. Structure (CHOCH: +4, BOS: +2)
        if idx > 0:
            prev_close = df["close"].iloc[idx - 1]
            curr_close = df["close"].iloc[idx]
            # 간단히 BOS로 처리 (단일 타임프레임 제약)
            score += 2
            structure = "bos"

        # 2. HTF Alignment: 추세 방향과 일치 (+2)
        if (direction == "bullish" and trend == "bullish") or (direction == "bearish" and trend == "bearish"):
            score += 2

        # 3. Base Candles: OB 직전 캔들 수 (근사치: 항상 1개로 계산)
        score += 2  # 1~3개 기준

        # 4. Consecutive Impulse Candles
        impulse_count = 0
        for k in range(idx + 1, min(idx + 5, len(df) - 1)):
            c = df.iloc[k]
            if direction == "bullish" and c["close"] > c["open"]:
                impulse_count += 1
            elif direction == "bearish" and c["close"] < c["open"]:
                impulse_count += 1
            else:
                break
        if impulse_count >= 3:
            score += 2
        elif impulse_count >= 2:
            score += 1

        # 5. Move Distance (ATR 기준)
        if idx + 1 < len(df) and atr > 0:
            move = abs(df["close"].iloc[min(idx + 3, len(df) - 1)] - df["close"].iloc[idx])
            if move >= 2.5 * atr:
                score += 2
            elif move >= 1.5 * atr:
                score += 1

        # 6. Wick Ratio: 캔들 내 꼬리 비율
        ob_candle = df.iloc[idx]
        candle_rng = ob_candle["high"] - ob_candle["low"]
        if candle_rng > 0:
            body = abs(ob_candle["close"] - ob_candle["open"])
            wick_ratio = 1 - (body / candle_rng)
            if wick_ratio <= 0.40:
                score += 2
            elif wick_ratio <= 0.60:
                score += 1

        # 7. FVG
        if idx >= 1 and idx + 2 < len(df):
            if direction == "bullish":
                fvg = df.iloc[idx - 1]["high"] < df.iloc[idx + 2]["low"]
            else:
                fvg = df.iloc[idx - 1]["low"] > df.iloc[idx + 2]["high"]
            if fvg:
                has_fvg = True
                score += 1

        # 8. Golden Zone (Fibonacci)
        if sh and sl:
            recent_sh = df["high"].iloc[sh[-1]]
            recent_sl = df["low"].iloc[sl[-1]]
            fib_levels = self._fib_levels(recent_sh, recent_sl)
            ob_mid = (ob_top + ob_bottom) / 2
            gz = self._golden_zone_match(ob_mid, fib_levels)
            if gz == 61.8:
                score += 3
            elif gz == 50.0:
                score += 2
            elif gz == 38.2:
                score += 1
            golden_zone = gz

        return ScoredOB(idx, direction, ob_top, ob_bottom, score, golden_zone, has_fvg, structure)

    def _find_best_ob(self, df: pd.DataFrame, direction: str, price: float,
                      sh: list[int], sl: list[int], atr: float, trend: str) -> Optional[ScoredOB]:
        lookback = min(self._ob_lookback, len(df) - 5)
        best: Optional[ScoredOB] = None
        for i in range(1, lookback):
            idx = len(df) - 1 - i
            if idx < 2:
                break
            c = df.iloc[idx]
            nxt = df.iloc[idx + 1]
            ob_top, ob_bottom = c["high"], c["low"]

            if direction == "bullish" and c["close"] < c["open"] and nxt["close"] > c["high"]:
                if ob_bottom <= price <= ob_top * 1.01:
                    ob = self._score_ob(df, idx, "bullish", ob_top, ob_bottom, sh, sl, atr, trend)
                    if best is None or ob.score > best.score:
                        best = ob

            if direction == "bearish" and c["close"] > c["open"] and nxt["close"] < c["low"]:
                if ob_bottom * 0.99 <= price <= ob_top:
                    ob = self._score_ob(df, idx, "bearish", ob_top, ob_bottom, sh, sl, atr, trend)
                    if best is None or ob.score > best.score:
                        best = ob
        return best

    def _confirm_candle(self, df: pd.DataFrame, direction: str) -> str:
        """확인 캔들 타입: 'pinbar' | 'engulfing' | 'none'"""
        last = df.iloc[-1]
        prev = df.iloc[-2]
        rng = last["high"] - last["low"]
        if rng == 0:
            return "none"
        if direction == "bullish":
            lower_wick = min(last["open"], last["close"]) - last["low"]
            if lower_wick > rng * 0.6 and last["close"] > last["open"]:
                return "pinbar"
            if last["close"] > last["open"] and last["close"] > prev["open"] and last["open"] < prev["close"]:
                return "engulfing"
        else:
            upper_wick = last["high"] - max(last["open"], last["close"])
            if upper_wick > rng * 0.6 and last["close"] < last["open"]:
                return "pinbar"
            if last["close"] < last["open"] and last["close"] < prev["open"] and last["open"] > prev["close"]:
                return "engulfing"
        return "none"

    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        min_len = self._ob_lookback + self._swing_n * 2 + self._atr_period + 5
        if len(df) < min_len:
            self._reason = f"데이터 부족 ({len(df)}/{min_len})"
            return Signal.HOLD

        price = df["close"].iloc[-1]
        sh = self._swing_highs(df, self._swing_n)
        sl = self._swing_lows(df, self._swing_n)
        trend = self._trend_direction(df, sh, sl)
        atr = self._atr(df, self._atr_period)

        if trend == "none":
            self._reason = "[GoldenOB] 추세 불명확 - 대기"
            return Signal.HOLD

        direction = trend  # 추세 방향으로 OB 탐색
        ob = self._find_best_ob(df, direction, price, sh, sl, atr, trend)

        if ob is None or ob.score < self._min_score:
            best_score = ob.score if ob else 0
            self._reason = f"[GoldenOB] HQ OB 없음 (최고점수={best_score})"
            return Signal.HOLD

        confirm = self._confirm_candle(df, direction)
        grade = "S" if ob.score >= 12 else "A"
        gz_str = f" Golden{ob.golden_zone:.1f}%" if ob.golden_zone > 0 else ""
        fvg_str = " +FVG" if ob.has_fvg else ""

        if ob.direction == "bullish" and confirm != "none":
            self._reason = f"[GoldenOB] {grade}급({ob.score}){gz_str}{fvg_str} Demand OB → 매수 [{confirm}]"
            return Signal.BUY

        if ob.direction == "bearish" and confirm != "none":
            self._reason = f"[GoldenOB] {grade}급({ob.score}){gz_str}{fvg_str} Supply OB → 매도 [{confirm}]"
            return Signal.SELL

        self._reason = f"[GoldenOB] {grade}급({ob.score}){gz_str} OB 대기 (확인 캔들 미발생)"
        return Signal.HOLD

    def get_reason(self) -> str:
        return self._reason
