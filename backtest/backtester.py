"""
백테스팅 엔진 - 전략 성능 검증
Usage:
    python -m backtest.backtester --symbol KRW-BTC --strategy trend_following --days 365
"""
import argparse
import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class BacktestResult:
    def __init__(self):
        self.trades: list[dict] = []
        self.equity_curve: list[dict] = []

    def add_trade(self, entry_time, exit_time, symbol: str, side: str,
                  entry_price: float, exit_price: float, quantity: float,
                  strategy: str, reason: str):
        pnl = (exit_price - entry_price) * quantity if side == "buy" else (entry_price - exit_price) * quantity
        pnl_ratio = (exit_price - entry_price) / entry_price if side == "buy" else (entry_price - exit_price) / entry_price
        self.trades.append({
            "entry_time": entry_time,
            "exit_time": exit_time,
            "symbol": symbol,
            "side": side,
            "strategy": strategy,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "quantity": quantity,
            "pnl": pnl,
            "pnl_ratio": pnl_ratio,
            "reason": reason,
        })

    def summary(self) -> dict:
        if not self.trades:
            return {"message": "거래 없음"}
        total_pnl = sum(t["pnl"] for t in self.trades)
        wins = [t for t in self.trades if t["pnl"] > 0]
        losses = [t for t in self.trades if t["pnl"] <= 0]
        win_rate = len(wins) / len(self.trades) if self.trades else 0
        avg_win = np.mean([t["pnl_ratio"] for t in wins]) if wins else 0
        avg_loss = np.mean([abs(t["pnl_ratio"]) for t in losses]) if losses else 0
        profit_factor = sum(t["pnl"] for t in wins) / abs(sum(t["pnl"] for t in losses)) if losses and sum(t["pnl"] for t in losses) != 0 else float("inf")
        return {
            "total_trades": len(self.trades),
            "win_count": len(wins),
            "loss_count": len(losses),
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "avg_win_pct": avg_win,
            "avg_loss_pct": avg_loss,
            "profit_factor": profit_factor,
            "max_drawdown": self._max_drawdown(),
        }

    def _max_drawdown(self) -> float:
        if not self.equity_curve:
            return 0.0
        equity = [e["equity"] for e in self.equity_curve]
        peak = equity[0]
        max_dd = 0.0
        for e in equity:
            if e > peak:
                peak = e
            dd = (peak - e) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)
        return max_dd

    def print_summary(self):
        s = self.summary()
        print("\n" + "=" * 50)
        print("📊 백테스트 결과")
        print("=" * 50)
        for k, v in s.items():
            if isinstance(v, float):
                print(f"  {k}: {v:.4f}")
            else:
                print(f"  {k}: {v}")
        print("=" * 50)


class Backtester:
    def __init__(self, initial_capital: float = 10_000_000,
                 stop_loss_ratio: float = 0.03,
                 take_profit_ratio: float = 0.06,
                 position_ratio: float = 0.05,
                 commission_rate: float = 0.0005):
        self.initial_capital = initial_capital
        self.stop_loss_ratio = stop_loss_ratio
        self.take_profit_ratio = take_profit_ratio
        self.position_ratio = position_ratio
        self.commission = commission_rate

    def run(self, df: pd.DataFrame, strategy, symbol: str = "SYMBOL") -> BacktestResult:
        """
        단순 단일 포지션 백테스트
        - 매수 신호 → 포지션 진입
        - 손절/익절 또는 매도 신호 → 청산
        """
        result = BacktestResult()
        capital = self.initial_capital
        position = None  # {entry_price, quantity, entry_time}

        # 매 캔들마다 전략 분석 (슬라이딩 윈도우)
        min_window = 210  # MA200 + 여유
        for i in range(min_window, len(df)):
            window = df.iloc[:i + 1].copy()
            current = df.iloc[i]
            current_price = float(current["close"])

            # 보유 중: 손절/익절 체크
            if position:
                entry = position["entry_price"]
                sl = entry * (1 - self.stop_loss_ratio)
                tp = entry * (1 + self.take_profit_ratio)

                exit_reason = None
                exit_price = current_price

                if current_price <= sl:
                    exit_reason = "손절"
                    exit_price = sl
                elif current_price >= tp:
                    exit_reason = "익절"
                    exit_price = tp
                else:
                    from bot.strategy.base import Signal
                    sig = strategy.analyze(window, symbol)
                    if sig == Signal.SELL:
                        exit_reason = strategy.get_reason()

                if exit_reason:
                    qty = position["quantity"]
                    pnl = (exit_price - entry) * qty
                    pnl -= exit_price * qty * self.commission  # 수수료
                    capital += exit_price * qty * (1 - self.commission)
                    result.add_trade(
                        entry_time=position["entry_time"],
                        exit_time=current.get("datetime", i),
                        symbol=symbol,
                        side="buy",
                        entry_price=entry,
                        exit_price=exit_price,
                        quantity=qty,
                        strategy=strategy.name,
                        reason=exit_reason,
                    )
                    result.equity_curve.append({"time": current.get("datetime", i), "equity": capital})
                    position = None
                continue

            # 미보유: 매수 신호 체크
            from bot.strategy.base import Signal
            sig = strategy.analyze(window, symbol)
            if sig == Signal.BUY:
                amount = capital * self.position_ratio
                cost = amount * (1 + self.commission)
                if cost > capital:
                    continue
                qty = amount / current_price
                capital -= cost
                position = {
                    "entry_price": current_price,
                    "quantity": qty,
                    "entry_time": current.get("datetime", i),
                }

            result.equity_curve.append({"time": current.get("datetime", i), "equity": capital})

        # 마지막에 포지션 있으면 시장가 청산
        if position:
            last_price = float(df["close"].iloc[-1])
            result.add_trade(
                entry_time=position["entry_time"],
                exit_time=df.get("datetime", len(df) - 1) if hasattr(df, "get") else len(df) - 1,
                symbol=symbol,
                side="buy",
                entry_price=position["entry_price"],
                exit_price=last_price,
                quantity=position["quantity"],
                strategy=strategy.name,
                reason="백테스트 종료",
            )

        return result


def load_sample_data(symbol: str = "KRW-BTC", days: int = 365) -> pd.DataFrame:
    """업비트에서 일봉 데이터 로드"""
    try:
        from bot.exchange.upbit import UpbitClient
        client = UpbitClient("", "")
        df = client.get_candles(symbol, interval="D" if False else "60", count=min(days * 24, 200))
        return df
    except Exception as e:
        logger.warning(f"실제 데이터 로드 실패 ({e}), 샘플 데이터 생성")
        return _generate_sample_data(days)


def _generate_sample_data(days: int = 365) -> pd.DataFrame:
    """테스트용 샘플 OHLCV 데이터 생성"""
    np.random.seed(42)
    n = days
    dates = pd.date_range(end=datetime.now(), periods=n, freq="D")
    close = 50000.0
    closes = []
    for _ in range(n):
        change = np.random.normal(0.0005, 0.02)
        close = close * (1 + change)
        closes.append(close)
    closes = np.array(closes)
    opens = closes * (1 + np.random.uniform(-0.005, 0.005, n))
    highs = np.maximum(opens, closes) * (1 + np.abs(np.random.normal(0, 0.005, n)))
    lows = np.minimum(opens, closes) * (1 - np.abs(np.random.normal(0, 0.005, n)))
    volumes = np.random.uniform(100, 1000, n)
    return pd.DataFrame({
        "datetime": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })


def main():
    parser = argparse.ArgumentParser(description="AutoTrade Bot 백테스터")
    parser.add_argument("--symbol", default="KRW-BTC", help="종목 코드")
    parser.add_argument("--strategy", default="trend_following",
                        choices=["trend_following", "rsi_reversal", "bollinger_breakout", "smc", "turtle"],
                        help="전략 이름")
    parser.add_argument("--days", type=int, default=365, help="백테스트 기간(일)")
    parser.add_argument("--capital", type=float, default=10_000_000, help="초기 자본")
    parser.add_argument("--sample", action="store_true", help="샘플 데이터 사용")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)

    from bot.strategy.trend_following import TrendFollowingStrategy
    from bot.strategy.rsi_reversal import RSIReversalStrategy
    from bot.strategy.bollinger_breakout import BollingerBreakoutStrategy
    from bot.strategy.smc import SMCStrategy
    from bot.strategy.turtle import TurtleStrategy

    strategy_map = {
        "trend_following": TrendFollowingStrategy,
        "rsi_reversal": RSIReversalStrategy,
        "bollinger_breakout": BollingerBreakoutStrategy,
        "smc": SMCStrategy,
        "turtle": TurtleStrategy,
    }

    strategy = strategy_map[args.strategy]()
    print(f"백테스트 시작: {args.symbol} / {args.strategy} / {args.days}일")

    if args.sample:
        df = _generate_sample_data(args.days)
    else:
        df = load_sample_data(args.symbol, args.days)

    print(f"데이터 로드 완료: {len(df)}개 캔들")

    backtester = Backtester(initial_capital=args.capital)
    result = backtester.run(df, strategy, symbol=args.symbol)
    result.print_summary()

    # 상위 5개 거래 출력
    if result.trades:
        print("\n최근 거래 (최대 5건):")
        for t in result.trades[-5:]:
            print(f"  {t['strategy']} {t['side']} @ {t['entry_price']:.2f} → {t['exit_price']:.2f} "
                  f"| PnL: {t['pnl']:+.2f} ({t['pnl_ratio']:+.2%}) | {t['reason']}")


if __name__ == "__main__":
    main()
