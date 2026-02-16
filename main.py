"""
AutoTrade Bot - 메인 진입점
업비트 + KIS(국내/해외) 자동매매봇 + FastAPI 대시보드 동시 실행
"""
import asyncio
import logging
import signal
import sys
from datetime import datetime
from pathlib import Path

import uvicorn

from bot.config import Config
from bot.exchange.upbit import UpbitClient
from bot.exchange.kis import KISClient
from bot.strategy.trend_following import TrendFollowingStrategy
from bot.strategy.rsi_reversal import RSIReversalStrategy
from bot.strategy.bollinger_breakout import BollingerBreakoutStrategy
from bot.strategy.smc import SMCStrategy
from bot.strategy.turtle import TurtleStrategy
from bot.strategy.base import Signal
from bot.risk import RiskManager
from bot.portfolio import Portfolio, Position
from bot.storage import Storage
from bot.notification import TelegramNotifier
from bot.scheduler import BotScheduler
from dashboard.app import app as dashboard_app, set_bot_context

# ── 로깅 설정 ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Path("logs") / f"bot_{datetime.now():%Y%m%d}.log"),
    ],
)
logger = logging.getLogger(__name__)

STRATEGY_MAP = {
    "trend_following": TrendFollowingStrategy,
    "rsi_reversal": RSIReversalStrategy,
    "bollinger_breakout": BollingerBreakoutStrategy,
    "smc": SMCStrategy,
    "turtle": TurtleStrategy,
}


class AutoTradeBot:
    def __init__(self, config: Config):
        self.cfg = config
        self._running = True
        self._stop_event = asyncio.Event()

        # 클라이언트
        self.upbit = UpbitClient(
            config.upbit["access_key"],
            config.upbit["secret_key"],
        )
        self.kis = KISClient(
            app_key=config.kis["app_key"],
            app_secret=config.kis["app_secret"],
            account_no=config.kis["account_no"],
            account_product_code=config.kis.get("account_product_code", "01"),
            hts_id=config.kis.get("hts_id", ""),
            is_paper_trading=config.kis.get("is_paper_trading", True),
        )

        # 전략 인스턴스 (전체 config 전달)
        self._strategies: dict[str, object] = {
            name: cls(config._data) for name, cls in STRATEGY_MAP.items()
        }

        self.risk = RiskManager(config._data)
        self.portfolio = Portfolio(max_positions=self.risk.max_concurrent_positions)
        self.storage = Storage()
        self.notifier = TelegramNotifier(
            bot_token=config.telegram.get("bot_token", ""),
            chat_id=config.telegram.get("chat_id", ""),
            on_stop=self._stop,
            on_resume=self._resume,
        )
        self.scheduler = BotScheduler()
        self._total_asset: float = 0.0

    def _stop(self):
        logger.info("봇 중지 명령 수신")
        self._running = False
        self._stop_event.set()

    def _resume(self):
        logger.info("봇 재개 명령 수신")
        self._running = True
        self._stop_event.clear()

    def _get_strategies(self, names: list[str]) -> list:
        return [self._strategies[n] for n in names if n in self._strategies]

    # ── 업비트 전략 실행 ──────────────────────────────────────────
    async def run_upbit_strategies(self):
        if not self._running:
            return
        cfg_upbit = self.cfg.strategy.get("upbit", {})
        if not cfg_upbit.get("enabled", False):
            return

        symbols = cfg_upbit.get("symbols", [])
        strategy_names = cfg_upbit.get("active_strategies", [])
        interval = cfg_upbit.get("candle_interval", "15")
        strategies = self._get_strategies(strategy_names)

        for symbol in symbols:
            if not self._running:
                break
            try:
                df = self.upbit.get_candles(symbol, interval, count=300)
                if df is None or len(df) < 50:
                    continue

                current_price = float(df["close"].iloc[-1])
                self.portfolio.update_price("upbit", symbol, current_price)

                # 보유 포지션 손절/익절 체크
                pos = self.portfolio.get_position("upbit", symbol)
                if pos:
                    if self.risk.check_stop_loss(pos.entry_price, current_price, pos.side):
                        await self._execute_sell("upbit", symbol, current_price, pos, "손절")
                        continue
                    if self.risk.check_take_profit(pos.entry_price, current_price, pos.side):
                        await self._execute_sell("upbit", symbol, current_price, pos, "익절")
                        continue

                # 전략 분석
                for strategy in strategies:
                    signal = strategy.analyze(df, symbol)
                    reason = strategy.get_reason()

                    if signal == Signal.BUY and not self.portfolio.has_position("upbit", symbol):
                        if self.portfolio.can_open_position():
                            await self._execute_buy("upbit", symbol, current_price, strategy.name, reason)
                    elif signal == Signal.SELL and self.portfolio.has_position("upbit", symbol):
                        pos = self.portfolio.get_position("upbit", symbol)
                        await self._execute_sell("upbit", symbol, current_price, pos, reason)

            except Exception as e:
                logger.error(f"업비트 {symbol} 전략 오류: {e}")

    # ── KIS 국내 전략 실행 ────────────────────────────────────────
    async def run_kis_domestic_strategies(self):
        if not self._running:
            return
        cfg_dom = self.cfg.strategy.get("kis_domestic", {})
        if not cfg_dom.get("enabled", False):
            return

        symbols = cfg_dom.get("symbols", [])
        strategy_names = cfg_dom.get("active_strategies", [])
        strategies = self._get_strategies(strategy_names)

        for symbol in symbols:
            if not self._running:
                break
            try:
                raw = self.kis.get_domestic_daily_chart(symbol, count=300)
                if not raw:
                    continue
                import pandas as pd
                df = pd.DataFrame(raw)
                df = df.rename(columns={"stck_bsop_date": "datetime", "stck_oprc": "open",
                                         "stck_hgpr": "high", "stck_lwpr": "low",
                                         "stck_clpr": "close", "acml_vol": "volume"})
                for col in ["open", "high", "low", "close", "volume"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                df = df.dropna(subset=["close"]).sort_values("datetime").reset_index(drop=True)

                current_price = float(df["close"].iloc[-1])
                self.portfolio.update_price("kis_domestic", symbol, current_price)

                pos = self.portfolio.get_position("kis_domestic", symbol)
                if pos:
                    if self.risk.check_stop_loss(pos.entry_price, current_price, pos.side):
                        await self._execute_sell("kis_domestic", symbol, current_price, pos, "손절")
                        continue
                    if self.risk.check_take_profit(pos.entry_price, current_price, pos.side):
                        await self._execute_sell("kis_domestic", symbol, current_price, pos, "익절")
                        continue

                for strategy in strategies:
                    signal = strategy.analyze(df, symbol)
                    reason = strategy.get_reason()

                    if signal == Signal.BUY and not self.portfolio.has_position("kis_domestic", symbol):
                        if self.portfolio.can_open_position():
                            await self._execute_buy("kis_domestic", symbol, current_price, strategy.name, reason)
                    elif signal == Signal.SELL and self.portfolio.has_position("kis_domestic", symbol):
                        pos = self.portfolio.get_position("kis_domestic", symbol)
                        await self._execute_sell("kis_domestic", symbol, current_price, pos, reason)

            except Exception as e:
                logger.error(f"KIS 국내 {symbol} 전략 오류: {e}")

    # ── KIS 해외 전략 실행 ────────────────────────────────────────
    async def run_kis_overseas_strategies(self):
        if not self._running:
            return
        cfg_ovs = self.cfg.strategy.get("kis_overseas", {})
        if not cfg_ovs.get("enabled", False):
            return

        market = cfg_ovs.get("market", "NAS")
        symbols = cfg_ovs.get("symbols", [])
        strategy_names = cfg_ovs.get("active_strategies", [])
        strategies = self._get_strategies(strategy_names)

        for symbol in symbols:
            if not self._running:
                break
            try:
                raw = self.kis.get_overseas_daily_chart(symbol, market=market, count=300)
                if not raw:
                    continue
                import pandas as pd
                df = pd.DataFrame(raw)
                df = df.rename(columns={"xymd": "datetime", "open": "open",
                                         "high": "high", "low": "low",
                                         "clos": "close", "tvol": "volume"})
                for col in ["open", "high", "low", "close", "volume"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                df = df.dropna(subset=["close"]).sort_values("datetime").reset_index(drop=True)

                current_price = float(df["close"].iloc[-1])
                self.portfolio.update_price("kis_overseas", symbol, current_price)

                pos = self.portfolio.get_position("kis_overseas", symbol)
                if pos:
                    if self.risk.check_stop_loss(pos.entry_price, current_price, pos.side):
                        await self._execute_sell("kis_overseas", symbol, current_price, pos, "손절", market=market)
                        continue
                    if self.risk.check_take_profit(pos.entry_price, current_price, pos.side):
                        await self._execute_sell("kis_overseas", symbol, current_price, pos, "익절", market=market)
                        continue

                for strategy in strategies:
                    signal = strategy.analyze(df, symbol)
                    reason = strategy.get_reason()

                    if signal == Signal.BUY and not self.portfolio.has_position("kis_overseas", symbol):
                        if self.portfolio.can_open_position():
                            await self._execute_buy("kis_overseas", symbol, current_price, strategy.name, reason, market=market)
                    elif signal == Signal.SELL and self.portfolio.has_position("kis_overseas", symbol):
                        pos = self.portfolio.get_position("kis_overseas", symbol)
                        await self._execute_sell("kis_overseas", symbol, current_price, pos, reason, market=market)

            except Exception as e:
                logger.error(f"KIS 해외 {symbol} 전략 오류: {e}")

    # ── 매수 실행 ─────────────────────────────────────────────────
    async def _execute_buy(self, exchange: str, symbol: str, price: float,
                           strategy: str, reason: str, market: str = ""):
        # 일일 손실 한도 체크
        if self.risk.check_daily_loss_limit(self.portfolio.daily_pnl, self._total_asset):
            logger.warning(f"일일 손실 한도 도달 - {symbol} 매수 스킵")
            return

        # Kelly Criterion 포지션 사이징 (기본 파라미터)
        amount = self.risk.kelly_position_size(
            win_rate=0.55,
            reward_risk_ratio=self.risk.take_profit_ratio / self.risk.stop_loss_ratio,
            capital=self._total_asset or 1_000_000,
        )
        quantity = amount / price if price > 0 else 0
        if quantity <= 0:
            return

        stop_price = self.risk.calculate_stop_price(price, "buy")
        take_profit = self.risk.calculate_take_profit_price(price, "buy")

        try:
            # 실제 주문
            if exchange == "upbit":
                self.upbit.place_market_buy(symbol, amount)
            elif exchange == "kis_domestic":
                self.kis.place_domestic_order(symbol, "buy", int(quantity), int(price))
            elif exchange == "kis_overseas":
                self.kis.place_overseas_order(symbol, market, "buy", int(quantity), round(price, 2))

            # 포지션 기록
            pos = Position(
                exchange=exchange, symbol=symbol, strategy=strategy,
                side="buy", entry_price=price, quantity=quantity,
                stop_price=stop_price, take_profit_price=take_profit, market=market,
            )
            self.portfolio.open_position(pos)
            self.storage.save_trade(
                exchange, symbol, "buy", strategy, price, quantity, amount, reason=reason
            )

            ratio = amount / (self._total_asset or 1)
            self.notifier.notify_buy(exchange, symbol, strategy, price, stop_price, take_profit, ratio)
            logger.info(f"매수 완료: {exchange} {symbol} @ {price:.2f} x {quantity:.4f}")

        except Exception as e:
            logger.error(f"매수 실패 {exchange} {symbol}: {e}")
            self.notifier.notify_error(f"매수 {symbol}", str(e))

    # ── 매도 실행 ─────────────────────────────────────────────────
    async def _execute_sell(self, exchange: str, symbol: str, price: float,
                            pos: Position, reason: str, market: str = ""):
        try:
            if exchange == "upbit":
                self.upbit.place_market_sell(symbol, pos.quantity)
            elif exchange == "kis_domestic":
                self.kis.place_domestic_order(symbol, "sell", int(pos.quantity), int(price))
            elif exchange == "kis_overseas":
                self.kis.place_overseas_order(symbol, market or pos.market, "sell",
                                              int(pos.quantity), round(price, 2))

            pnl = self.portfolio.close_position(exchange, symbol, price)
            amount = price * pos.quantity
            self.storage.save_trade(
                exchange, symbol, "sell", pos.strategy, price, pos.quantity, amount, pnl=pnl, reason=reason
            )
            self.notifier.notify_sell(exchange, symbol, pos.strategy, price, pnl or 0, reason)
            logger.info(f"매도 완료: {exchange} {symbol} @ {price:.2f}, PnL={pnl:.2f}")

        except Exception as e:
            logger.error(f"매도 실패 {exchange} {symbol}: {e}")
            self.notifier.notify_error(f"매도 {symbol}", str(e))

    # ── 일일 리포트 ───────────────────────────────────────────────
    async def send_daily_report(self):
        today = datetime.now().strftime("%Y-%m-%d")
        daily = self.storage.get_daily_summary()
        self.notifier.notify_daily_report(today, {
            "upbit_pnl": 0,
            "kis_domestic_pnl": 0,
            "kis_overseas_pnl": 0,
            "trade_count": daily["trade_count"],
            "win_count": daily["win_count"],
        })
        self.portfolio.reset_daily_pnl()

    # ── 메인 실행 ─────────────────────────────────────────────────
    async def start(self):
        logger.info("AutoTrade Bot 시작")

        # 대시보드 컨텍스트 설정
        set_bot_context({
            "portfolio": self.portfolio,
            "storage": self.storage,
            "total_asset": self._total_asset,
            "stop_event": self._stop_event,
        })

        # 스케줄러 등록
        self.scheduler.add_upbit_job(self.run_upbit_strategies, interval_seconds=60)
        self.scheduler.add_kis_domestic_job(self.run_kis_domestic_strategies, interval_seconds=60)
        self.scheduler.add_kis_overseas_job(self.run_kis_overseas_strategies, interval_seconds=60)
        self.scheduler.add_daily_report_job(self.send_daily_report)
        self.scheduler.add_daily_reset_job(self.portfolio.reset_daily_pnl)
        self.scheduler.start()

        # 텔레그램 리스너
        try:
            asyncio.ensure_future(self.notifier.start_command_listener())
        except Exception as e:
            logger.warning(f"텔레그램 리스너 시작 실패: {e}")

        logger.info("봇 실행 중. Ctrl+C로 종료.")
        try:
            await self._stop_event.wait()
        except asyncio.CancelledError:
            pass
        finally:
            self.scheduler.stop()
            logger.info("AutoTrade Bot 종료")


async def run_dashboard():
    config = uvicorn.Config(dashboard_app, host="0.0.0.0", port=8080, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    cfg = Config()
    bot = AutoTradeBot(cfg)
    await asyncio.gather(
        bot.start(),
        run_dashboard(),
    )


if __name__ == "__main__":
    Path("logs").mkdir(exist_ok=True)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("사용자 종료 요청")
