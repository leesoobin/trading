"""
MTF 구조 매핑 전략 (Multi-Timeframe Structure)

HTF(고위 타임프레임)로 추세를 파악하고,
LTF(저위 타임프레임)에서 BOS/ChoCh 진입 시점을 탐지합니다.

타임프레임 매핑:
  코인:   HTF=4H(minute240), LTF=15분(minute15)
  KOSPI:  HTF=일봉(day),     LTF=60분(minute60)
  KOSDAQ: HTF=일봉(day),     LTF=30분(minute30)
  NASDAQ: HTF=일봉(day),     LTF=15분(minute15)
"""
import logging

import pandas as pd
import numpy as np

from .base import Strategy, Signal

logger = logging.getLogger(__name__)

# 클래스 레벨 플래그: 이 전략은 HTF 데이터도 필요함
NEEDS_HTF = True

# 최소 데이터 요건
MIN_HTF_CANDLES = 30
MIN_LTF_CANDLES = 50


class MTFStructureStrategy(Strategy):
    """
    Multi-Timeframe 구조 매핑 전략.

    analyze()       : 기존 인터페이스 호환 (df=LTF, 항상 HOLD)
    analyze_mtf()   : 핵심 메서드 (df_ltf + df_htf → Signal)
    """

    needs_htf = True  # main.py에서 HTF 데이터 추가 수집 여부 판단용

    def __init__(self, config: dict = None):
        super().__init__(config)
        self._reason = ""
        self._last_sl: float | None = None
        self._last_tp: float | None = None

    def get_last_sl_tp(self) -> tuple[float | None, float | None]:
        """마지막 신호의 SL/TP 반환 (백테스터용)"""
        return self._last_sl, self._last_tp

    # ── 기존 인터페이스 호환 ──────────────────────────────────────
    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        """단일 타임프레임으로는 분석 불가 → HOLD 반환 (MTF 미적용)"""
        self._reason = "MTF 전략: analyze_mtf()를 사용하세요"
        return Signal.HOLD

    def get_reason(self) -> str:
        return self._reason

    # ── MTF 핵심 분석 ─────────────────────────────────────────────
    def analyze_mtf(self, df_ltf: pd.DataFrame, df_htf: pd.DataFrame,
                    symbol: str) -> Signal:
        """
        HTF + LTF 데이터를 받아 매매 신호를 반환합니다.

        Args:
            df_ltf: LTF OHLCV DataFrame (datetime, open, high, low, close, volume)
            df_htf: HTF OHLCV DataFrame (동일 컬럼 구조)
            symbol: 종목 코드 (로깅용)

        Returns:
            Signal.BUY / Signal.SELL / Signal.HOLD
        """
        if df_htf is None or len(df_htf) < MIN_HTF_CANDLES:
            self._reason = f"HTF 데이터 부족 ({len(df_htf) if df_htf is not None else 0}개)"
            return Signal.HOLD
        if df_ltf is None or len(df_ltf) < MIN_LTF_CANDLES:
            self._reason = f"LTF 데이터 부족 ({len(df_ltf) if df_ltf is not None else 0}개)"
            return Signal.HOLD

        # HTF 추세 파악
        htf_trend, htf_high, htf_low = self._htf_trend(df_htf)

        if htf_trend == "neutral":
            self._reason = "HTF neutral: HOLD"
            return Signal.HOLD

        # LTF 진입 시점 탐지
        signal, reason = self._ltf_entry(df_ltf, htf_trend, htf_high, htf_low)

        self._reason = f"HTF:{htf_trend} | {reason}"
        logger.debug(f"[MTF] {symbol} → {signal.value} | {self._reason}")
        return signal

    # ── HTF 추세 분석 ─────────────────────────────────────────────
    @staticmethod
    def _find_swing_points(df: pd.DataFrame, n: int = 5) -> tuple[list, list]:
        """
        스윙 고점/저점 탐색.

        Args:
            df: OHLCV DataFrame
            n:  좌우 n개 캔들 기준

        Returns:
            (swing_highs, swing_lows): 각각 (index, price) 튜플 리스트
        """
        highs = df["high"].values
        lows = df["low"].values
        swing_highs = []
        swing_lows = []

        for i in range(n, len(df) - n):
            if all(highs[i] >= highs[i - j] for j in range(1, n + 1)) and \
               all(highs[i] >= highs[i + j] for j in range(1, n + 1)):
                swing_highs.append((i, float(highs[i])))
            if all(lows[i] <= lows[i - j] for j in range(1, n + 1)) and \
               all(lows[i] <= lows[i + j] for j in range(1, n + 1)):
                swing_lows.append((i, float(lows[i])))

        return swing_highs, swing_lows

    def _htf_trend(self, df_htf: pd.DataFrame,
               n: int = 5) -> tuple[str, float, float]:
        """
        HTF 데이터에서 추세를 판단합니다.

        추세 판단 기준:
          - HH(Higher High) + HL(Higher Low) 2회 이상 확인 → "bullish"
          - LH(Lower High)  + LL(Lower Low)  2회 이상 확인 → "bearish"
          - 그 외 → "neutral"
        스윙 탐색 n=5, 최소 스윙 3개

        Returns:
            (trend, last_swing_high_price, last_swing_low_price)
        """
        swing_highs, swing_lows = self._find_swing_points(df_htf, n=n)

        last_htf_high = float(df_htf["high"].max())
        last_htf_low = float(df_htf["low"].min())

        if len(swing_highs) >= 1:
            last_htf_high = swing_highs[-1][1]
        if len(swing_lows) >= 1:
            last_htf_low = swing_lows[-1][1]

        # 최소 스윙 3개 필요
        if len(swing_highs) < 3 or len(swing_lows) < 3:
            return "neutral", last_htf_high, last_htf_low

        # HH/HL 카운트
        hh_count = sum(1 for i in range(1, len(swing_highs)) if swing_highs[i][1] > swing_highs[i-1][1])
        lh_count = len(swing_highs) - 1 - hh_count
        hl_count = sum(1 for i in range(1, len(swing_lows)) if swing_lows[i][1] > swing_lows[i-1][1])
        ll_count = len(swing_lows) - 1 - hl_count

        # 2회 이상 확인 (신호 품질 유지)
        if hh_count >= 2 and hl_count >= 2:
            return "bullish", last_htf_high, last_htf_low
        if lh_count >= 2 and ll_count >= 2:
            return "bearish", last_htf_high, last_htf_low

        return "neutral", last_htf_high, last_htf_low

    # ── LTF 진입 시점 탐지 ────────────────────────────────────────
    def _ltf_entry(self, df_ltf: pd.DataFrame, htf_trend: str,
               htf_high: float, htf_low: float) -> tuple[Signal, str]:
        """
        HTF 추세 방향으로 LTF에서 BOS/ChoCh 진입 시점을 탐지합니다.
        LTF 스윙 탐색 n=3 (노이즈 방지)
        """
        swing_highs, swing_lows = self._find_swing_points(df_ltf, n=3)

        if htf_trend == "bullish":
            return self._detect_bullish_entry(df_ltf, swing_highs, swing_lows, htf_high)
        else:  # bearish
            return self._detect_bearish_entry(df_ltf, swing_highs, swing_lows, htf_low)

    def _detect_bullish_entry(self, df_ltf: pd.DataFrame,
                           swing_highs: list, swing_lows: list,
                           htf_high: float) -> tuple[Signal, str]:
        """
        HTF Bullish: 조정 후 LTF ChoCh/BOS 상향 돌파 → BUY

        조정 감지 (스윙 기반): 최근 swing_low가 이전보다 낮음
        TP 최소 거리: 1%
        """
        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return Signal.HOLD, "LTF 스윙 포인트 부족"

        close = df_ltf["close"].values
        current_close = float(close[-1])

        recent_lows = swing_lows[-3:] if len(swing_lows) >= 3 else swing_lows
        recent_highs = swing_highs[-3:] if len(swing_highs) >= 3 else swing_highs

        # 조정 감지: 스윙 기반 (최근 저점이 이전보다 낮음)
        correction_detected = (len(recent_lows) >= 2 and
                               recent_lows[-1][1] < recent_lows[-2][1])

        if not correction_detected:
            return Signal.HOLD, "조정 구간 미감지"

        if not recent_highs:
            return Signal.HOLD, "LTF 고점 없음"

        last_swing_high = recent_highs[-1][1]

        # ChoCh: 조정 중 직전 LTF 고점을 상향 돌파
        if current_close > last_swing_high:
            sl_price = recent_lows[-1][1] if recent_lows else current_close * 0.97
            tp_price = htf_high
            if tp_price > current_close * 1.01 and sl_price < current_close:
                rr = (tp_price - current_close) / (current_close - sl_price)
                self._last_sl, self._last_tp = sl_price, tp_price
                return Signal.BUY, f"LTF ChoCh BUY @ {current_close:.2f} SL={sl_price:.2f} TP={tp_price:.2f} RR={rr:.1f}"

        # BOS: 새로운 LTF 고점 형성 (이전 고점 경신)
        if len(swing_highs) >= 2 and swing_highs[-1][1] > swing_highs[-2][1]:
            sl_price = swing_lows[-1][1] if swing_lows else current_close * 0.97
            tp_price = htf_high
            if tp_price > current_close * 1.01 and sl_price < current_close:
                rr = (tp_price - current_close) / (current_close - sl_price)
                self._last_sl, self._last_tp = sl_price, tp_price
                return Signal.BUY, f"LTF BOS BUY @ {current_close:.2f} SL={sl_price:.2f} TP={tp_price:.2f} RR={rr:.1f}"

        return Signal.HOLD, "LTF 진입 조건 미충족(bullish)"

    def _detect_bearish_entry(self, df_ltf: pd.DataFrame,
                           swing_highs: list, swing_lows: list,
                           htf_low: float) -> tuple[Signal, str]:
        """
        HTF Bearish: 반등 후 LTF ChoCh/BOS 하향 돌파 → SELL

        반등 감지 (스윙 기반): 최근 swing_high가 이전보다 높음
        TP 최소 거리: 1%
        """
        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return Signal.HOLD, "LTF 스윙 포인트 부족"

        close = df_ltf["close"].values
        current_close = float(close[-1])

        recent_highs = swing_highs[-3:] if len(swing_highs) >= 3 else swing_highs
        recent_lows = swing_lows[-3:] if len(swing_lows) >= 3 else swing_lows

        # 반등 감지: 스윙 기반 (최근 고점이 이전보다 높음)
        bounce_detected = (len(recent_highs) >= 2 and
                           recent_highs[-1][1] > recent_highs[-2][1])

        if not bounce_detected:
            return Signal.HOLD, "반등 구간 미감지"

        if not recent_lows:
            return Signal.HOLD, "LTF 저점 없음"

        last_swing_low = recent_lows[-1][1]

        # ChoCh: 반등 중 직전 LTF 저점을 하향 돌파
        if current_close < last_swing_low:
            sl_price = recent_highs[-1][1] if recent_highs else current_close * 1.03
            tp_price = htf_low
            if tp_price < current_close * 0.99 and sl_price > current_close:
                rr = (current_close - tp_price) / (sl_price - current_close)
                self._last_sl, self._last_tp = sl_price, tp_price
                return Signal.SELL, f"LTF ChoCh SELL @ {current_close:.2f} SL={sl_price:.2f} TP={tp_price:.2f} RR={rr:.1f}"

        # BOS: 새로운 LTF 저점 형성
        if len(swing_lows) >= 2 and swing_lows[-1][1] < swing_lows[-2][1]:
            sl_price = swing_highs[-1][1] if swing_highs else current_close * 1.03
            tp_price = htf_low
            if tp_price < current_close * 0.99 and sl_price > current_close:
                rr = (current_close - tp_price) / (sl_price - current_close)
                self._last_sl, self._last_tp = sl_price, tp_price
                return Signal.SELL, f"LTF BOS SELL @ {current_close:.2f} SL={sl_price:.2f} TP={tp_price:.2f} RR={rr:.1f}"

        return Signal.HOLD, "LTF 진입 조건 미충족(bearish)"
