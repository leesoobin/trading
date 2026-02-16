from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class Position:
    exchange: str          # upbit | kis_domestic | kis_overseas
    symbol: str
    strategy: str
    side: str              # buy | sell
    entry_price: float
    quantity: float
    stop_price: float
    take_profit_price: float
    entry_time: datetime = field(default_factory=datetime.now)
    current_price: float = 0.0
    market: str = ""       # KIS 해외 거래소 코드

    @property
    def amount(self) -> float:
        return self.entry_price * self.quantity

    @property
    def pnl(self) -> float:
        if self.current_price <= 0:
            return 0.0
        if self.side == "buy":
            return (self.current_price - self.entry_price) * self.quantity
        else:
            return (self.entry_price - self.current_price) * self.quantity

    @property
    def pnl_ratio(self) -> float:
        if self.entry_price <= 0:
            return 0.0
        if self.side == "buy":
            return (self.current_price - self.entry_price) / self.entry_price
        else:
            return (self.entry_price - self.current_price) / self.entry_price


class Portfolio:
    def __init__(self, max_positions: int = 5):
        self._positions: dict[str, Position] = {}  # key: f"{exchange}:{symbol}"
        self._max_positions = max_positions
        self._daily_pnl: float = 0.0
        self._total_pnl: float = 0.0
        self._trade_count: int = 0
        self._win_count: int = 0

    def _key(self, exchange: str, symbol: str) -> str:
        return f"{exchange}:{symbol}"

    def has_position(self, exchange: str, symbol: str) -> bool:
        return self._key(exchange, symbol) in self._positions

    def get_position(self, exchange: str, symbol: str) -> Optional[Position]:
        return self._positions.get(self._key(exchange, symbol))

    def can_open_position(self) -> bool:
        return len(self._positions) < self._max_positions

    def open_position(self, position: Position):
        key = self._key(position.exchange, position.symbol)
        if key in self._positions:
            logger.warning(f"포지션 이미 존재: {key}")
            return
        self._positions[key] = position
        logger.info(f"포지션 오픈: {key} @ {position.entry_price:.2f} x {position.quantity:.4f}")

    def close_position(self, exchange: str, symbol: str, exit_price: float) -> Optional[float]:
        """포지션 청산. 손익(pnl) 반환"""
        key = self._key(exchange, symbol)
        pos = self._positions.pop(key, None)
        if pos is None:
            logger.warning(f"청산할 포지션 없음: {key}")
            return None
        pos.current_price = exit_price
        pnl = pos.pnl
        self._daily_pnl += pnl
        self._total_pnl += pnl
        self._trade_count += 1
        if pnl > 0:
            self._win_count += 1
        logger.info(f"포지션 청산: {key} @ {exit_price:.2f}, PnL={pnl:.2f}")
        return pnl

    def update_price(self, exchange: str, symbol: str, current_price: float):
        key = self._key(exchange, symbol)
        if key in self._positions:
            self._positions[key].current_price = current_price

    def get_all_positions(self) -> list[Position]:
        return list(self._positions.values())

    def reset_daily_pnl(self):
        self._daily_pnl = 0.0

    @property
    def daily_pnl(self) -> float:
        return self._daily_pnl

    @property
    def total_pnl(self) -> float:
        return self._total_pnl

    @property
    def unrealized_pnl(self) -> float:
        return sum(p.pnl for p in self._positions.values())

    @property
    def win_rate(self) -> float:
        if self._trade_count == 0:
            return 0.0
        return self._win_count / self._trade_count

    @property
    def trade_count(self) -> int:
        return self._trade_count

    @property
    def win_count(self) -> int:
        return self._win_count

    def summary(self) -> dict:
        positions = self.get_all_positions()
        return {
            "active_positions": len(positions),
            "daily_pnl": self._daily_pnl,
            "total_pnl": self._total_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "trade_count": self._trade_count,
            "win_count": self._win_count,
            "win_rate": self.win_rate,
            "positions": [
                {
                    "exchange": p.exchange,
                    "symbol": p.symbol,
                    "strategy": p.strategy,
                    "side": p.side,
                    "entry_price": p.entry_price,
                    "current_price": p.current_price,
                    "quantity": p.quantity,
                    "pnl": p.pnl,
                    "pnl_ratio": p.pnl_ratio,
                    "stop_price": p.stop_price,
                    "take_profit_price": p.take_profit_price,
                    "entry_time": p.entry_time.isoformat(),
                }
                for p in positions
            ],
        }
