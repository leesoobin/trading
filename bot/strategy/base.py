from abc import ABC, abstractmethod
from enum import Enum

import pandas as pd


class Signal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class Strategy(ABC):
    def __init__(self, config: dict = None):
        self._config = config or {}
        self._reason: str = ""

    @abstractmethod
    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        """주어진 OHLCV 데이터프레임을 분석하여 매매 신호 반환"""
        ...

    @abstractmethod
    def get_reason(self) -> str:
        """마지막 analyze() 호출의 매매 사유 반환 (텔레그램 메시지용)"""
        ...

    @property
    def name(self) -> str:
        return self.__class__.__name__
