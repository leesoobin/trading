"""
터틀 트레이딩 (Richard Dennis & William Eckhardt, 1983)
- System 1: 20일 도니안채널 브레이크아웃
- System 2: 55일 도니안채널 브레이크아웃
- ATR 기반 Unit 포지션 사이징
- 0.5 ATR 피라미딩 (최대 4 Units)
- 2 ATR 손절
"""
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
import numpy as np

from bot.strategy.base import Signal, Strategy
from bot.indicators import calc_atr, calc_donchian


@dataclass
class TurtleState:
    last_signal_profitable: bool = False  # System 1 필터: 직전 신호 수익 여부
    entry_price: Optional[float] = None
    atr_at_entry: Optional[float] = None
    units: int = 0
    last_add_price: Optional[float] = None


class TurtleStrategy(Strategy):
    """터틀 트레이딩: 도니안채널 브레이크아웃 + ATR Unit 사이징"""

    def __init__(self, config: dict = None, system: int = 2):
        super().__init__(config)
        self.system = system  # 1 or 2
        if system == 1:
            self._entry_period = 20
            self._exit_period = 10
            self._use_filter = True
        else:
            self._entry_period = 55
            self._exit_period = 20
            self._use_filter = False
        self._atr_period = 14
        self._max_units = 4
        self._pyramid_atr = 0.5  # 피라미딩 간격
        self._stop_atr = 2.0     # 손절 ATR 배수
        self._state: dict[str, TurtleState] = {}

    def _get_state(self, symbol: str) -> TurtleState:
        if symbol not in self._state:
            self._state[symbol] = TurtleState()
        return self._state[symbol]

    def update_exit(self, symbol: str, exit_price: float):
        """포지션 청산 후 직전 신호 수익 여부 업데이트"""
        state = self._get_state(symbol)
        if state.entry_price is not None:
            state.last_signal_profitable = exit_price > state.entry_price
        state.entry_price = None
        state.atr_at_entry = None
        state.units = 0
        state.last_add_price = None

    def calc_unit_size(self, atr: float, price: float, capital: float) -> float:
        """Unit 수량 = (자본 × 1%) / (ATR × 가격)"""
        if atr <= 0 or price <= 0:
            return 0.0
        dollar_volatility = atr * price
        return (capital * 0.01) / dollar_volatility if dollar_volatility > 0 else 0.0

    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        min_len = self._entry_period + self._atr_period + 5
        if len(df) < min_len:
            self._reason = f"터틀 데이터 부족 ({len(df)}/{min_len})"
            return Signal.HOLD

        atr_series = calc_atr(df, self._atr_period)
        entry_upper, _ = calc_donchian(df, self._entry_period)
        _, exit_lower = calc_donchian(df, self._exit_period)

        if atr_series.isna().iloc[-1]:
            self._reason = "ATR 계산 불가"
            return Signal.HOLD

        curr_close = df["close"].iloc[-1]
        prev_close = df["close"].iloc[-2]
        curr_atr = atr_series.iloc[-1]
        curr_entry_upper = entry_upper.iloc[-2]  # 전일 기준 (현재봉 제외)
        curr_exit_lower = exit_lower.iloc[-2]

        state = self._get_state(symbol)

        # 청산 체크: 보유 중이면 청산 조건 우선 체크
        if state.entry_price is not None:
            # ATR 손절
            atr_stop = state.entry_price - (self._stop_atr * (state.atr_at_entry or curr_atr))
            if curr_close < atr_stop:
                self._reason = f"터틀 2ATR 손절 ({curr_close:.2f} < {atr_stop:.2f})"
                self.update_exit(symbol, curr_close)
                return Signal.SELL

            # 도니안 청산
            if curr_close < curr_exit_lower:
                self._reason = f"터틀 {self._exit_period}일 저점 이탈 ({curr_close:.2f} < {curr_exit_lower:.2f})"
                self.update_exit(symbol, curr_close)
                return Signal.SELL

            # 피라미딩: 0.5 ATR 상승마다 추가 (최대 4 Units)
            if state.units < self._max_units:
                add_price = (state.last_add_price or state.entry_price) + self._pyramid_atr * curr_atr
                if curr_close >= add_price:
                    state.units += 1
                    state.last_add_price = curr_close
                    self._reason = f"터틀 피라미딩 Unit{state.units} (현재가={curr_close:.2f})"
                    return Signal.BUY

            self._reason = f"터틀 보유 중 (진입가={state.entry_price:.2f}, Units={state.units})"
            return Signal.HOLD

        # 진입: 도니안 상단 돌파
        if prev_close <= curr_entry_upper < curr_close:
            # System 1 필터: 직전 신호가 수익이었으면 이번 신호 스킵
            if self._use_filter and state.last_signal_profitable:
                self._reason = f"System1 필터: 직전 신호 수익 → 스킵 (상단={curr_entry_upper:.2f})"
                return Signal.HOLD

            state.entry_price = curr_close
            state.atr_at_entry = curr_atr
            state.units = 1
            state.last_add_price = curr_close
            self._reason = f"터틀 System{self.system} 진입 ({self._entry_period}일 고가 {curr_entry_upper:.2f} 돌파)"
            return Signal.BUY

        self._reason = f"터틀 대기 (상단={curr_entry_upper:.2f}, 현재가={curr_close:.2f}, ATR={curr_atr:.2f})"
        return Signal.HOLD

    def get_reason(self) -> str:
        return self._reason
