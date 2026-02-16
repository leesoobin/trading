import logging
from typing import Optional

logger = logging.getLogger(__name__)


class RiskManager:
    def __init__(self, config: dict):
        risk = config.get("risk", {})
        self.max_position_ratio = risk.get("max_position_ratio", 0.06)
        self.max_daily_loss_ratio = risk.get("max_daily_loss_ratio", 0.02)
        self.stop_loss_ratio = risk.get("stop_loss_ratio", 0.03)
        self.take_profit_ratio = risk.get("take_profit_ratio", 0.06)
        self.max_concurrent_positions = risk.get("max_concurrent_positions", 5)

    def kelly_position_size(self, win_rate: float, reward_risk_ratio: float, capital: float) -> float:
        """
        Kelly Criterion: f* = (b*p - q) / b
        - b = reward_risk_ratio (수익비, e.g. 2.0 = 익절/손절)
        - p = win_rate (승률, 0~1)
        - q = 1 - p
        返回: 포지션 금액 (원)
        """
        if win_rate <= 0 or reward_risk_ratio <= 0 or capital <= 0:
            return 0.0
        p = win_rate
        q = 1.0 - p
        b = reward_risk_ratio
        kelly_fraction = (b * p - q) / b
        # 음수(기대값 음수) → 포지션 없음
        if kelly_fraction <= 0:
            return 0.0
        # Half-Kelly (보수적 운용)
        half_kelly = kelly_fraction * 0.5
        # 최대 max_position_ratio 캡 적용
        capped = min(half_kelly, self.max_position_ratio)
        position_amount = capital * capped
        logger.debug(f"Kelly: f*={kelly_fraction:.4f}, half={half_kelly:.4f}, capped={capped:.4f}, amount={position_amount:.0f}")
        return position_amount

    def turtle_unit_size(self, atr: float, price: float, capital: float) -> float:
        """
        터틀 Unit 사이징: Unit = (capital × 1%) / (ATR × price)
        """
        if atr <= 0 or price <= 0 or capital <= 0:
            return 0.0
        dollar_volatility = atr * price
        units = (capital * 0.01) / dollar_volatility
        # 최대 max_position_ratio 캡
        max_amount = capital * self.max_position_ratio
        max_units_by_cap = max_amount / (price if price > 0 else 1)
        return min(units, max_units_by_cap)

    def check_daily_loss_limit(self, daily_pnl: float, capital: float) -> bool:
        """일일 손실 한도 초과 여부 확인. True = 거래 중지 필요"""
        if capital <= 0:
            return False
        loss_ratio = abs(daily_pnl) / capital if daily_pnl < 0 else 0.0
        if loss_ratio >= self.max_daily_loss_ratio:
            logger.warning(f"일일 손실 한도 도달: {loss_ratio:.2%} >= {self.max_daily_loss_ratio:.2%}")
            return True
        return False

    def calculate_stop_price(self, entry_price: float, side: str) -> float:
        """손절가 계산. side: 'buy' | 'sell'"""
        if side == "buy":
            return entry_price * (1 - self.stop_loss_ratio)
        else:
            return entry_price * (1 + self.stop_loss_ratio)

    def calculate_take_profit_price(self, entry_price: float, side: str) -> float:
        """익절가 계산. side: 'buy' | 'sell'"""
        if side == "buy":
            return entry_price * (1 + self.take_profit_ratio)
        else:
            return entry_price * (1 - self.take_profit_ratio)

    def calculate_atr_stop(self, entry_price: float, atr: float, multiplier: float = 2.0) -> float:
        """ATR 기반 손절가 (터틀 전용)"""
        return entry_price - (atr * multiplier)

    def check_stop_loss(self, entry_price: float, current_price: float, side: str) -> bool:
        """손절 트리거 여부"""
        stop = self.calculate_stop_price(entry_price, side)
        if side == "buy":
            return current_price <= stop
        return current_price >= stop

    def check_take_profit(self, entry_price: float, current_price: float, side: str) -> bool:
        """익절 트리거 여부"""
        tp = self.calculate_take_profit_price(entry_price, side)
        if side == "buy":
            return current_price >= tp
        return current_price <= tp
