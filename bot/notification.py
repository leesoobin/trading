import asyncio
import logging
from datetime import datetime
from typing import Optional, Callable

logger = logging.getLogger(__name__)

try:
    from telegram import Update, Bot
    from telegram.ext import Application, CommandHandler, ContextTypes
    _HAS_TELEGRAM = True
except ImportError:
    _HAS_TELEGRAM = False
    logger.warning("python-telegram-bot not installed. Telegram notifications disabled.")


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str,
                 on_stop: Optional[Callable] = None,
                 on_resume: Optional[Callable] = None):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._on_stop = on_stop
        self._on_resume = on_resume
        self._app = None

    def _format_krw(self, amount: float) -> str:
        abs_val = abs(amount)
        if abs_val >= 1_000:
            return f"₩{amount:,.0f}"
        elif abs_val >= 1:
            return f"₩{amount:.2f}"
        elif abs_val >= 0.0001:
            return f"₩{amount:.6f}"
        elif abs_val == 0:
            return "₩0"
        return f"₩{amount:.8f}"

    async def send_message(self, text: str):
        if not _HAS_TELEGRAM:
            logger.info(f"[Telegram 비활성화] {text}")
            return
        try:
            bot = Bot(token=self.bot_token)
            async with bot:
                await bot.send_message(chat_id=self.chat_id, text=text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"텔레그램 전송 실패: {e}")

    def send(self, text: str):
        """동기 래퍼"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self.send_message(text))
            else:
                loop.run_until_complete(self.send_message(text))
        except Exception as e:
            logger.error(f"텔레그램 send 오류: {e}")

    # 전략별 청산 조건 설명
    _EXIT_CONDITIONS = {
        "BollingerBreakoutStrategy": "볼린저 중심선(MA20) 도달 시 매도",
        "TurtleStrategy": "10일/20일 최저가 이탈 시 매도",
        "TrendFollowingStrategy": "MA20 < MA200 데드크로스 시 매도",
        "MAPullbackStrategy": "EMA 역배열 시 매도",
    }

    def notify_buy(self, exchange: str, symbol: str, strategy: str,
                   price: float, stop_price: float, take_profit: float,
                   position_ratio: float):
        stop_pct = (stop_price - price) / price * 100
        if take_profit > 0:
            tp_pct = (take_profit - price) / price * 100
            exit_line = f"목표가: {self._format_krw(take_profit)} ({tp_pct:+.1f}%)\n"
        else:
            exit_cond = self._EXIT_CONDITIONS.get(strategy, "전략 신호 발생 시 매도")
            exit_line = f"청산조건: {exit_cond}\n"
        msg = (
            f"📈 <b>[매수 신호] {symbol}</b>\n"
            f"거래소: {exchange}\n"
            f"전략: {strategy}\n"
            f"현재가: {self._format_krw(price)}\n"
            f"{exit_line}"
            f"손절가: {self._format_krw(stop_price)} ({stop_pct:+.1f}%)\n"
            f"포지션: 잔고의 {position_ratio:.1%}"
        )
        self.send(msg)

    def notify_sell(self, exchange: str, symbol: str, strategy: str,
                    price: float, pnl: float, reason: str):
        pnl_emoji = "✅" if pnl >= 0 else "❌"
        msg = (
            f"{pnl_emoji} <b>[매도] {symbol}</b>\n"
            f"거래소: {exchange}\n"
            f"전략: {strategy}\n"
            f"매도가: {self._format_krw(price)}\n"
            f"손익: {self._format_krw(pnl)}\n"
            f"사유: {reason}"
        )
        self.send(msg)

    def notify_daily_report(self, date_str: str, summary: dict):
        upbit_pnl = summary.get("upbit_pnl", 0)
        kis_dom_pnl = summary.get("kis_domestic_pnl", 0)
        kis_ovs_pnl = summary.get("kis_overseas_pnl", 0)
        total_pnl = summary.get("total_pnl", upbit_pnl + kis_dom_pnl + kis_ovs_pnl)
        wins = summary.get("win_count", 0)
        total = summary.get("trade_count", 0)
        total_asset = summary.get("total_asset", 1_000_000)

        win_rate = f"{wins}/{total} ({wins/total*100:.0f}%)" if total > 0 else "0/0"
        total_pct = f"{total_pnl/total_asset*100:+.2f}%" if total_asset > 0 else "+0.00%"

        def _pnl_line(label: str, pnl: float) -> str:
            sign = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "⚪"
            return f"{sign} {label}: {self._format_krw(pnl)}"

        msg = (
            f"📊 <b>[일일 리포트] {date_str}</b>\n"
            f"{_pnl_line('업비트', upbit_pnl)}\n"
            f"{_pnl_line('KIS 국내', kis_dom_pnl)}\n"
            f"{_pnl_line('KIS 해외', kis_ovs_pnl)}\n"
            f"━━━━━━━━━━━━━━\n"
            f"총 손익: <b>{self._format_krw(total_pnl)}</b> ({total_pct})\n"
            f"승률: {win_rate} ({total}거래)"
        )
        self.send(msg)

    def notify_screening(self, exchange: str, results: list, fallback: bool = False):
        """스크리닝 완료 텔레그램 알람"""
        label_map = {
            "upbit": "업비트 코인",
            "kis_domestic": "KIS 국내",
            "kis_overseas": "KIS 해외",
        }
        label = label_map.get(exchange, exchange)

        def _escape(text: str) -> str:
            return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        if not results:
            msg = f"🔍 <b>[스크리닝] {label}</b>\n조건 충족 종목 없음"
            self.send(msg)
            return

        lines = []
        for r in results:
            reasons = _escape(", ".join(r.reasons)) if r.reasons else "-"
            trend_emoji = "🟢" if r.trend == "bullish" else "🔴" if r.trend == "bearish" else "⚪"
            display = f"{r.symbol} {r.name}" if getattr(r, "name", "") else r.symbol
            lines.append(f"{trend_emoji} {_escape(display)} ({r.score:.0f}점) {reasons}")

        suffix = f" (총 {len(results)}개" + (", fallback" if fallback else "") + ")"
        msg = (
            f"🔍 <b>[스크리닝] {label}</b>{suffix}\n"
            + "\n".join(lines)
        )
        self.send(msg)

    def notify_error(self, module: str, error: str):
        msg = f"⚠️ <b>[오류] {module}</b>\n{error}"
        self.send(msg)

    def notify_circuit_breaker(self, daily_loss: float, capital: float):
        ratio = abs(daily_loss / capital) * 100 if capital > 0 else 0
        msg = (
            f"🚨 <b>[서킷브레이커 발동]</b>\n"
            f"일일 손실: {self._format_krw(daily_loss)} ({ratio:.1f}%)\n"
            f"봇을 일시 중단합니다."
        )
        self.send(msg)

    async def start_command_listener(self):
        """텔레그램 명령어 수신 루프"""
        if not _HAS_TELEGRAM:
            return
        app = Application.builder().token(self.bot_token).build()

        async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
            await update.message.reply_text("🤖 봇 정상 동작 중입니다.")

        async def cmd_positions(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
            await update.message.reply_text("📋 /positions: 포트폴리오 모듈에서 조회하세요.")

        async def cmd_pnl(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
            await update.message.reply_text("💰 /pnl: 손익 정보를 불러오는 중입니다.")

        async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
            if self._on_stop:
                self._on_stop()
            await update.message.reply_text("🛑 봇 중지 명령을 수신했습니다.")

        async def cmd_resume(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
            if self._on_resume:
                self._on_resume()
            await update.message.reply_text("▶️ 봇 재개 명령을 수신했습니다.")

        app.add_handler(CommandHandler("status", cmd_status))
        app.add_handler(CommandHandler("positions", cmd_positions))
        app.add_handler(CommandHandler("pnl", cmd_pnl))
        app.add_handler(CommandHandler("stop", cmd_stop))
        app.add_handler(CommandHandler("resume", cmd_resume))

        self._app = app
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        logger.info("텔레그램 명령어 리스너 시작")
