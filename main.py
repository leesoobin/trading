"""
AutoTrade Bot - 메인 진입점
업비트 + KIS(국내/해외) 자동매매봇 + FastAPI 대시보드 동시 실행
"""
import asyncio
import dataclasses
import json
import logging
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

_SCREEN_CACHE = {
    "kis_domestic": Path("screened_domestic.json"),
    "kis_overseas": Path("screened_overseas.json"),
}

import uvicorn

from bot.config import Config
from bot.exchange.upbit import UpbitClient
from bot.exchange.kis import KISClient
from bot.strategy.trend_following import TrendFollowingStrategy
from bot.strategy.bollinger_breakout import BollingerBreakoutStrategy
from bot.strategy.turtle import TurtleStrategy
from bot.strategy.ma_pullback import MAPullbackStrategy
from bot.strategy.mtf_structure import MTFStructureStrategy
from bot.strategy.smc import SMCStrategy
from bot.strategy.base import Signal
from bot.risk import RiskManager
from bot.portfolio import Portfolio, Position
from bot.storage import Storage
from bot.notification import TelegramNotifier
from bot.scheduler import BotScheduler
from bot.screener import Screener, ScreenResult
from bot.data_sync import DataSync
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

# 전략 맵 (활성/비활성 config에서 제어)
STRATEGY_MAP = {
    "turtle":            TurtleStrategy,
    "trend_following":   TrendFollowingStrategy,
    "bollinger_breakout": BollingerBreakoutStrategy,
    "ma_pullback":       MAPullbackStrategy,
    "mtf_structure":     MTFStructureStrategy,
    "smc":               SMCStrategy,
}

# 전략별 최대 보유일 (초과 시 강제 청산)
# TurtleStrategy: 제한 없음 (추세가 이어지는 한 유지)
MAX_HOLD_DAYS: dict[str, int] = {
    "BollingerBreakoutStrategy": 3,
    "MTFStructureStrategy":      3,
    "TrendFollowingStrategy":    14,
    "MAPullbackStrategy":        14,
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

        # 전략 인스턴스
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
        self.screener = Screener(self.upbit, self.kis, storage=self.storage)
        self.data_sync = DataSync(self.storage)
        self._total_asset: float = 0.0

        # 스크리닝 결과: list[ScreenResult] (비어 있으면 config.yaml symbols 폴백)
        self._screened_symbols: dict[str, list] = {
            "upbit": [],
            "kis_domestic": [],
            "kis_overseas": [],
        }

        # 손절 후 재진입 쿨다운: {(exchange, symbol): 손절 시각}
        self._stop_loss_cooldown: dict[tuple, datetime] = {}
        self._cooldown_hours: int = 24

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

        # 스크리닝 결과 우선 (ScreenResult 리스트), 없으면 config.yaml symbols 폴백
        screened: list[ScreenResult] = self._screened_symbols["upbit"]
        if screened:
            symbols = [r.symbol for r in screened]
        else:
            symbols = [ScreenResult(s, "upbit", 0, "neutral", "upbit")
                       for s in cfg_upbit.get("symbols", [])]
            screened = symbols
            symbols = [r.symbol for r in screened]

        strategy_names = cfg_upbit.get("active_strategies", [])
        strategies = self._get_strategies(strategy_names)

        for symbol in symbols:
            if not self._running:
                break
            try:
                # 멀티 타임프레임 데이터 수집
                df_htf   = self.upbit.get_candles(symbol, "240", count=100)  # 4H - MTF HTF
                df_ltf   = self.upbit.get_candles(symbol, "15",  count=200)  # 15분 - MTF/BB LTF
                df_daily = self.upbit.get_daily_candles(symbol, count=400)   # 일봉 - turtle/trend

                # 현재가: LTF 기준
                if df_ltf is None or len(df_ltf) < 50:
                    continue
                current_price = float(df_ltf["close"].iloc[-1])
                self.portfolio.update_price("upbit", symbol, current_price)

                # 보유 포지션 손절/익절/기간초과 체크
                pos = self.portfolio.get_position("upbit", symbol)
                if pos:
                    if self.risk.check_stop_loss(pos.entry_price, current_price, pos.side):
                        await self._execute_sell("upbit", symbol, current_price, pos, "손절")
                        continue
                    # MTF만 고정 익절가 체크 (나머지는 전략 신호로 청산)
                    if pos.take_profit_price > 0 and current_price >= pos.take_profit_price:
                        await self._execute_sell("upbit", symbol, current_price, pos, "익절")
                        continue
                    # 최대 보유 기간 초과 체크
                    max_days = MAX_HOLD_DAYS.get(pos.strategy)
                    if max_days:
                        days_held = (datetime.now() - pos.entry_time.replace(tzinfo=None)).days
                        if days_held >= max_days:
                            await self._execute_sell("upbit", symbol, current_price, pos, f"보유기간 초과 ({days_held}일)")
                            continue

                # 전략별 라우팅
                for strategy in strategies:
                    sname = strategy.name
                    if sname in ("TurtleStrategy", "TrendFollowingStrategy", "MAPullbackStrategy"):
                        if df_daily is None or len(df_daily) < 50:
                            continue
                        signal = strategy.analyze(df_daily, symbol)
                    elif sname == "MTFStructureStrategy":
                        if df_htf is None or df_ltf is None:
                            continue
                        signal = strategy.analyze_mtf(df_ltf, df_htf, symbol)
                    else:  # BollingerBreakoutStrategy
                        signal = strategy.analyze(df_ltf, symbol)

                    reason = strategy.get_reason()

                    if signal == Signal.BUY and not self.portfolio.has_position("upbit", symbol):
                        if self.portfolio.can_open_position():
                            await self._execute_buy("upbit", symbol, current_price, strategy.name, reason)
                    elif signal == Signal.SELL and self.portfolio.has_position("upbit", symbol):
                        pos = self.portfolio.get_position("upbit", symbol)
                        # 포지션을 연 전략만 청산 가능
                        if pos and pos.strategy == strategy.name:
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

        screened: list[ScreenResult] = self._screened_symbols["kis_domestic"]
        if not screened:
            screened = [ScreenResult(s, "kis_domestic", 0, "neutral", "KOSPI")
                        for s in cfg_dom.get("symbols", [])]

        strategy_names = cfg_dom.get("active_strategies", [])
        strategies = self._get_strategies(strategy_names)

        import pandas as pd

        for screen_result in screened:
            symbol = screen_result.symbol
            market_type = screen_result.market_type  # "KOSPI" or "KOSDAQ"
            if not self._running:
                break
            try:
                # 일봉 데이터 (HTF & 일봉 전략용)
                raw_daily = self.kis.get_domestic_daily_chart(symbol, count=300)
                if not raw_daily:
                    continue
                df_daily = pd.DataFrame(raw_daily)
                df_daily = df_daily.rename(columns={
                    "stck_bsop_date": "datetime", "stck_oprc": "open",
                    "stck_hgpr": "high", "stck_lwpr": "low",
                    "stck_clpr": "close", "acml_vol": "volume",
                })
                for col in ["open", "high", "low", "close", "volume"]:
                    if col in df_daily.columns:
                        df_daily[col] = pd.to_numeric(df_daily[col], errors="coerce")
                df_daily = df_daily.dropna(subset=["close"]).sort_values("datetime").reset_index(drop=True)

                # LTF 분봉 데이터 (MTF용)
                period = 60 if market_type == "KOSPI" else 30
                df_ltf = self.kis.get_domestic_minute_chart(symbol, period=period, count=120)

                current_price = float(df_daily["close"].iloc[-1])
                self.portfolio.update_price("kis_domestic", symbol, current_price)

                pos = self.portfolio.get_position("kis_domestic", symbol)
                if pos:
                    if self.risk.check_stop_loss(pos.entry_price, current_price, pos.side):
                        await self._execute_sell("kis_domestic", symbol, current_price, pos, "손절")
                        continue
                    if pos.take_profit_price > 0 and current_price >= pos.take_profit_price:
                        await self._execute_sell("kis_domestic", symbol, current_price, pos, "익절")
                        continue
                    # 최대 보유 기간 초과 체크
                    max_days = MAX_HOLD_DAYS.get(pos.strategy)
                    if max_days:
                        days_held = (datetime.now() - pos.entry_time.replace(tzinfo=None)).days
                        if days_held >= max_days:
                            await self._execute_sell("kis_domestic", symbol, current_price, pos, f"보유기간 초과 ({days_held}일)")
                            continue

                for strategy in strategies:
                    sname = strategy.name
                    if sname in ("TurtleStrategy", "TrendFollowingStrategy", "MAPullbackStrategy"):
                        if len(df_daily) < 50:
                            continue
                        signal = strategy.analyze(df_daily, symbol)
                    elif sname == "MTFStructureStrategy":
                        if df_ltf is None or len(df_daily) < 30:
                            continue
                        signal = strategy.analyze_mtf(df_ltf, df_daily, symbol)
                    else:
                        df_target = df_ltf if df_ltf is not None else df_daily
                        signal = strategy.analyze(df_target, symbol)

                    reason = strategy.get_reason()

                    if signal == Signal.BUY and not self.portfolio.has_position("kis_domestic", symbol):
                        if self.portfolio.can_open_position():
                            await self._execute_buy("kis_domestic", symbol, current_price, strategy.name, reason)
                    elif signal == Signal.SELL and self.portfolio.has_position("kis_domestic", symbol):
                        pos = self.portfolio.get_position("kis_domestic", symbol)
                        if pos and pos.strategy == strategy.name:
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
        screened: list[ScreenResult] = self._screened_symbols["kis_overseas"]
        if not screened:
            screened = [ScreenResult(s, "kis_overseas", 0, "neutral", market)
                        for s in cfg_ovs.get("symbols", [])]

        strategy_names = cfg_ovs.get("active_strategies", [])
        strategies = self._get_strategies(strategy_names)

        import pandas as pd

        for screen_result in screened:
            symbol = screen_result.symbol
            ovs_market = screen_result.market_type or market
            if not self._running:
                break
            try:
                # 일봉 (HTF & 일봉 전략)
                raw_daily = self.kis.get_overseas_daily_chart(symbol, market=ovs_market, count=300)
                if not raw_daily:
                    continue
                df_daily = pd.DataFrame(raw_daily)
                df_daily = df_daily.rename(columns={
                    "xymd": "datetime", "open": "open",
                    "high": "high", "low": "low",
                    "clos": "close", "tvol": "volume",
                })
                for col in ["open", "high", "low", "close", "volume"]:
                    if col in df_daily.columns:
                        df_daily[col] = pd.to_numeric(df_daily[col], errors="coerce")
                df_daily = df_daily.dropna(subset=["close"]).sort_values("datetime").reset_index(drop=True)

                # LTF 분봉 (MTF용, NASDAQ 15분봉)
                df_ltf = self.kis.get_overseas_minute_chart(symbol, market=ovs_market, nmin=15, count=100)

                current_price = float(df_daily["close"].iloc[-1])
                self.portfolio.update_price("kis_overseas", symbol, current_price)

                pos = self.portfolio.get_position("kis_overseas", symbol)
                if pos:
                    if self.risk.check_stop_loss(pos.entry_price, current_price, pos.side):
                        await self._execute_sell("kis_overseas", symbol, current_price, pos, "손절", market=ovs_market)
                        continue
                    if pos.take_profit_price > 0 and current_price >= pos.take_profit_price:
                        await self._execute_sell("kis_overseas", symbol, current_price, pos, "익절", market=ovs_market)
                        continue
                    # 최대 보유 기간 초과 체크
                    max_days = MAX_HOLD_DAYS.get(pos.strategy)
                    if max_days:
                        days_held = (datetime.now() - pos.entry_time.replace(tzinfo=None)).days
                        if days_held >= max_days:
                            await self._execute_sell("kis_overseas", symbol, current_price, pos, f"보유기간 초과 ({days_held}일)", market=ovs_market)
                            continue

                for strategy in strategies:
                    sname = strategy.name
                    if sname in ("TurtleStrategy", "TrendFollowingStrategy", "MAPullbackStrategy"):
                        if len(df_daily) < 50:
                            continue
                        signal = strategy.analyze(df_daily, symbol)
                    elif sname == "MTFStructureStrategy":
                        if df_ltf is None or len(df_daily) < 30:
                            continue
                        signal = strategy.analyze_mtf(df_ltf, df_daily, symbol)
                    else:
                        df_target = df_ltf if df_ltf is not None else df_daily
                        signal = strategy.analyze(df_target, symbol)

                    reason = strategy.get_reason()

                    if signal == Signal.BUY and not self.portfolio.has_position("kis_overseas", symbol):
                        if self.portfolio.can_open_position():
                            await self._execute_buy("kis_overseas", symbol, current_price, strategy.name, reason, market=ovs_market)
                    elif signal == Signal.SELL and self.portfolio.has_position("kis_overseas", symbol):
                        pos = self.portfolio.get_position("kis_overseas", symbol)
                        if pos and pos.strategy == strategy.name:
                            await self._execute_sell("kis_overseas", symbol, current_price, pos, reason, market=ovs_market)

            except Exception as e:
                logger.error(f"KIS 해외 {symbol} 전략 오류: {e}")

    # ── 미청산 포지션 복원 ────────────────────────────────────────
    def _restore_open_positions(self):
        """봇 재시작 시 DB에서 미청산 포지션을 복구 (같은 종목 병합)"""
        open_trades = self.storage.get_open_positions()
        if not open_trades:
            logger.info("복원할 미청산 포지션 없음")
            return

        # 같은 exchange:symbol 묶어서 병합 (평균가, 합산수량)
        merged: dict[str, dict] = {}
        for trade in open_trades:
            key = f"{trade['exchange']}:{trade['symbol']}"
            if key not in merged:
                merged[key] = {
                    "exchange": trade["exchange"],
                    "symbol": trade["symbol"],
                    "strategy": trade["strategy"],
                    "total_qty": 0.0,
                    "total_amt": 0.0,
                    "entry_time": trade["timestamp"],
                }
            merged[key]["total_qty"] += trade["quantity"]
            merged[key]["total_amt"] += trade["price"] * trade["quantity"]

        for key, m in merged.items():
            try:
                avg_price = m["total_amt"] / m["total_qty"] if m["total_qty"] > 0 else 0
                stop_price = self.risk.calculate_stop_price(avg_price, "buy")
                take_profit = self.risk.calculate_take_profit_price(avg_price, "buy")
                pos = Position(
                    exchange=m["exchange"],
                    symbol=m["symbol"],
                    strategy=m["strategy"],
                    side="buy",
                    entry_price=avg_price,
                    quantity=m["total_qty"],
                    stop_price=stop_price,
                    take_profit_price=take_profit,
                    entry_time=datetime.fromisoformat(m["entry_time"]),
                )
                self.portfolio.open_position(pos)
                logger.info(f"포지션 복원: {m['exchange']} {m['symbol']} 평균가={avg_price:.4f} 수량={m['total_qty']:.4f}")
            except Exception as e:
                logger.error(f"포지션 복원 실패 {m.get('symbol')}: {e}")
        logger.info(f"포지션 복원 완료: {len(merged)}개")

    def _restore_screened_symbols(self):
        """봇 재시작 시 스크리닝 캐시 파일에서 결과 복원"""
        for key, path in _SCREEN_CACHE.items():
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text())
                self._screened_symbols[key] = [ScreenResult(**d) for d in data]
                logger.info(f"스크리닝 캐시 복원: {key} {len(self._screened_symbols[key])}개 ← {path}")
            except Exception as e:
                logger.warning(f"스크리닝 캐시 로드 실패 ({path}): {e}")

    def _save_screened_symbols(self, key: str):
        """스크리닝 결과를 파일에 저장"""
        path = _SCREEN_CACHE.get(key)
        if not path:
            return
        try:
            data = [dataclasses.asdict(r) for r in self._screened_symbols[key]]
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        except Exception as e:
            logger.warning(f"스크리닝 캐시 저장 실패 ({path}): {e}")

    # ── 매수 실행 ─────────────────────────────────────────────────
    async def _execute_buy(self, exchange: str, symbol: str, price: float,
                           strategy: str, reason: str, market: str = ""):
        # 손절 쿨다운 체크
        cooldown_key = (exchange, symbol)
        if cooldown_key in self._stop_loss_cooldown:
            elapsed = (datetime.now() - self._stop_loss_cooldown[cooldown_key]).total_seconds() / 3600
            if elapsed < self._cooldown_hours:
                logger.info(f"쿨다운 중 매수 스킵: {exchange} {symbol} (손절 후 {elapsed:.1f}h / {self._cooldown_hours}h)")
                return
            else:
                del self._stop_loss_cooldown[cooldown_key]

        today_pnl = self.storage.get_today_pnl()
        if self.risk.check_daily_loss_limit(today_pnl, self._total_asset):
            logger.warning(f"일일 손실 한도 도달 (오늘 PnL={today_pnl:,.0f}원) - {symbol} 매수 스킵")
            return

        amount = self.risk.kelly_position_size(
            win_rate=0.55,
            reward_risk_ratio=self.risk.take_profit_ratio / self.risk.stop_loss_ratio,
            capital=self._total_asset or 1_000_000,
        )
        quantity = amount / price if price > 0 else 0
        if quantity <= 0:
            return

        # 손절가: 모든 전략 공통 -3% 안전망
        stop_price = self.risk.calculate_stop_price(price, "buy")

        # 익절가 설정
        if strategy == "MTFStructureStrategy":
            # MTF: 전략이 직접 SL/TP 계산
            strat_obj = self._strategies.get(strategy)
            strat_sl, strat_tp = strat_obj.get_last_sl_tp() if strat_obj and hasattr(strat_obj, "get_last_sl_tp") else (None, None)
            if strat_sl and strat_sl < price:
                stop_price = strat_sl
            take_profit = strat_tp if (strat_tp and strat_tp > price) else self.risk.calculate_take_profit_price(price, "buy")
        elif strategy == "BollingerBreakoutStrategy":
            # 볼린저: risk.py TP +6% 사용 (전략 SELL = 브레이크아웃 실패 청산, risk TP = 수익 실현)
            take_profit = self.risk.calculate_take_profit_price(price, "buy")
        else:
            take_profit = 0.0  # 터틀/추세추종: 전략 신호로만 청산 (터틀 저점, 데드크로스 등)

        try:
            if exchange == "upbit":
                self.upbit.place_market_buy(symbol, amount)
            elif exchange == "kis_domestic":
                self.kis.place_domestic_order(symbol, "buy", int(quantity), int(price))
            elif exchange == "kis_overseas":
                self.kis.place_overseas_order(symbol, market, "buy", int(quantity), round(price, 2))

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
                # 실제 보유 수량 조회 (수수료로 인해 DB 수량과 차이 발생 가능)
                currency = symbol.replace("KRW-", "")
                actual_qty = self.upbit.get_balance(currency)
                sell_qty = actual_qty if actual_qty > 0 else pos.quantity
                self.upbit.place_market_sell(symbol, sell_qty)
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

            # 모든 청산 후 재진입 쿨다운 등록 (손절/익절/전략 청산 모두)
            self._stop_loss_cooldown[(exchange, symbol)] = datetime.now()
            logger.info(f"쿨다운 등록: {exchange} {symbol} → {self._cooldown_hours}시간 재진입 금지 [{reason}]")

        except Exception as e:
            logger.error(f"매도 실패 {exchange} {symbol}: {e}")
            self.notifier.notify_error(f"매도 {symbol}", str(e))

    # ── 데이터 업데이트 + 스크리닝 통합 (12:30 KST) ─────────────
    async def run_data_and_screen(self):
        """12:30 KST: 전체 데이터 업데이트 후 스크리닝 실행"""
        try:
            summary = await self.data_sync.sync_all()
            logger.info(
                f"데이터 업데이트 완료 — 국내={summary['domestic']} "
                f"해외={summary['overseas']} 코인={summary['upbit']} "
                f"({summary['elapsed_sec']}초)"
            )
        except Exception as e:
            logger.error(f"데이터 업데이트 실패: {e}")

        # 스크리닝 (데이터 업데이트 직후 실행)
        await asyncio.gather(
            self.run_screen_upbit(),
            self.run_screen_kis_domestic(),
            self.run_screen_kis_overseas(),
        )

    # ── 스크리닝 실행 ─────────────────────────────────────────────
    async def run_screen_upbit(self):
        """00:30 KST: 업비트 코인 스크리닝"""
        results = await self.screener.screen_upbit()
        if results:
            self._screened_symbols["upbit"] = results
            logger.info(f"업비트 스크리닝 결과 반영: {[r.symbol for r in results]}")
        self.notifier.notify_screening("upbit", results)

    async def run_screen_kis_domestic(self):
        """15:00 KST: KIS 국내 스크리닝"""
        results = await self.screener.screen_kis_domestic()
        if results:
            self._screened_symbols["kis_domestic"] = results
            self._save_screened_symbols("kis_domestic")
            logger.info(f"KIS 국내 스크리닝 결과 반영: {[r.symbol for r in results]}")
        self.notifier.notify_screening("kis_domestic", results)

    async def run_screen_kis_overseas(self):
        """06:00 KST: KIS 해외 스크리닝"""
        cfg_ovs = self.cfg.strategy.get("kis_overseas", {})
        market = cfg_ovs.get("market", "NAS")
        results = await self.screener.screen_kis_overseas(market=market)
        fallback = not results  # 0개면 config fallback 사용
        if results:
            self._screened_symbols["kis_overseas"] = results
            logger.info(f"KIS 해외 스크리닝 결과 반영: {[r.symbol for r in results]}")
        self.notifier.notify_screening("kis_overseas", results, fallback=fallback)

    # ── 일일 리포트 ───────────────────────────────────────────────
    async def send_daily_report(self):
        today = datetime.now().strftime("%Y-%m-%d")
        daily = self.storage.get_daily_summary()

        total_asset = self._total_asset or 1_000_000
        self.notifier.notify_daily_report(today, {
            "upbit_pnl": daily["upbit_pnl"],
            "kis_domestic_pnl": daily["kis_domestic_pnl"],
            "kis_overseas_pnl": daily["kis_overseas_pnl"],
            "total_pnl": daily["total_pnl"],
            "trade_count": daily["trade_count"],
            "win_count": daily["win_count"],
            "total_asset": total_asset,
        })
        self.portfolio.reset_daily_pnl()

    # ── 메인 실행 ─────────────────────────────────────────────────
    async def start(self):
        logger.info("AutoTrade Bot 시작")

        # 총자산 초기화: 업비트 (KRW + 코인평가액) + KIS 자본
        try:
            upbit_balance = self.upbit.get_total_balance_krw()
            kis_capital = 1_000_000  # KIS 입금액
            self._total_asset = upbit_balance["total"] + kis_capital
            logger.info(
                f"총자산 초기화: 업비트 KRW={upbit_balance['krw']:,.0f}원 "
                f"+ 코인={upbit_balance['coin_value']:,.0f}원 "
                f"+ KIS={kis_capital:,.0f}원 = {self._total_asset:,.0f}원"
            )
        except Exception as e:
            self._total_asset = 2_000_000
            logger.warning(f"잔고 조회 실패, 기본값 200만원 사용: {e}")

        # 미청산 포지션 복원 (재시작 후 DB에서 복구)
        self._restore_open_positions()

        # 스크리닝 결과 캐시 복원 (재시작 후 파일에서 복구)
        self._restore_screened_symbols()

        set_bot_context({
            "portfolio": self.portfolio,
            "storage": self.storage,
            "total_asset": self._total_asset,
            "stop_event": self._stop_event,
        })

        self.scheduler.add_upbit_job(self.run_upbit_strategies, interval_seconds=60)
        self.scheduler.add_kis_domestic_job(self.run_kis_domestic_strategies, interval_seconds=60)
        self.scheduler.add_kis_overseas_job(self.run_kis_overseas_strategies, interval_seconds=60)
        self.scheduler.add_daily_report_job(self.send_daily_report)
        self.scheduler.add_daily_reset_job(self.portfolio.reset_daily_pnl)
        # 12:30 KST: 데이터 업데이트 + 스크리닝 통합 잡
        self.scheduler.add_data_sync_job(self.run_data_and_screen)
        self.scheduler.start()

        cfg_upbit = self.cfg.strategy.get("upbit", {})
        if not cfg_upbit.get("symbols"):
            logger.info("초기 데이터 업데이트+스크리닝 실행 중... (백그라운드)")
            asyncio.ensure_future(self.run_data_and_screen())

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
    import fcntl
    Path("logs").mkdir(exist_ok=True)
    lock_file = Path("bot.lock")
    _lock_fd = open(lock_file, "w")
    try:
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        logger.error("이미 봇이 실행 중입니다. 중복 실행 방지로 종료합니다.")
        _lock_fd.close()
        sys.exit(1)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("사용자 종료 요청")
    finally:
        fcntl.flock(_lock_fd, fcntl.LOCK_UN)
        _lock_fd.close()
        lock_file.unlink(missing_ok=True)
