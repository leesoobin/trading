"""
백테스팅 엔진 - 전략 성능 검증
Usage:
    python -m backtest.backtester                          # 전체 배치 (기본)
    python -m backtest.backtester --symbol KRW-BTC --strategy smc_ob_pullback
"""
import argparse
import logging
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

ALL_STRATEGIES = [
    "turtle", "trend_following", "bollinger_breakout", "ma_pullback", "mtf_structure",
]

UPBIT_SYMBOLS = ["KRW-BTC", "KRW-ETH", "KRW-SOL"]
KIS_SYMBOLS   = []

# ── 전략별 최적 시간봉 + 수집 기간 ───────────────────────────────────────
# interval : pyupbit 인터벌 문자열
# candles  : 수집할 캔들 수 (워밍업 200개 + 실거래 목표)
STRATEGY_TIMEFRAME = {
    #  전략                  interval        candles   이유
    "turtle":             ("day",            1_095),  # 일봉 × 3년 : 20/55일 채널 전용
    "trend_following":    ("day",            1_095),  # 일봉 × 3년 : MA20/200 크로스
    "bollinger_breakout": ("minute60",       3_000),  # 1H × ~125일 : BB 브레이크아웃
    "ma_pullback":        ("day",            1_095),  # 일봉 × 3년 : EMA 5/20/60은 일봉 기준
    "mtf_structure":      ("minute15",       8_000),  # 15분봉 LTF ~83일 (HTF는 4H로 자동 리샘플)
}

INTERVAL_LABEL = {
    "day": "일봉", "minute240": "4시간봉", "minute60": "1시간봉", "minute15": "15분봉(LTF)",
}


class BacktestResult:
    def __init__(self):
        self.trades: list[dict] = []
        self.equity_curve: list[dict] = []

    def add_trade(self, entry_time, exit_time, symbol: str, side: str,
                  entry_price: float, exit_price: float, quantity: float,
                  strategy: str, reason: str):
        pnl = (exit_price - entry_price) * quantity
        pnl_ratio = (exit_price - entry_price) / entry_price if entry_price > 0 else 0
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
        wins   = [t for t in self.trades if t["pnl"] > 0]
        losses = [t for t in self.trades if t["pnl"] <= 0]
        win_rate = len(wins) / len(self.trades) if self.trades else 0
        avg_win  = np.mean([t["pnl_ratio"] for t in wins])   if wins   else 0
        avg_loss = np.mean([abs(t["pnl_ratio"]) for t in losses]) if losses else 0
        gross_win  = sum(t["pnl"] for t in wins)
        gross_loss = abs(sum(t["pnl"] for t in losses))
        profit_factor = gross_win / gross_loss if gross_loss > 0 else float("inf")
        return {
            "total_trades":   len(self.trades),
            "win_count":      len(wins),
            "loss_count":     len(losses),
            "win_rate":       win_rate,
            "total_pnl":      total_pnl,
            "avg_win_pct":    avg_win,
            "avg_loss_pct":   avg_loss,
            "profit_factor":  profit_factor,
            "max_drawdown":   self._max_drawdown(),
        }

    def _max_drawdown(self) -> float:
        if not self.equity_curve:
            return 0.0
        equity = [e["equity"] for e in self.equity_curve]
        peak, max_dd = equity[0], 0.0
        for e in equity:
            if e > peak:
                peak = e
            dd = (peak - e) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)
        return max_dd

    def print_summary(self):
        s = self.summary()
        print("\n" + "=" * 52)
        print("📊 백테스트 결과")
        print("=" * 52)
        if "message" in s:
            print(f"  {s['message']}")
        else:
            print(f"  총 거래:      {s['total_trades']}건  (승 {s['win_count']} / 패 {s['loss_count']})")
            print(f"  승률:         {s['win_rate']:.1%}")
            print(f"  총 손익:      {s['total_pnl']:+,.0f}원")
            print(f"  평균 수익:    {s['avg_win_pct']:+.2%}  /  평균 손실: -{s['avg_loss_pct']:.2%}")
            print(f"  Profit Factor:{s['profit_factor']:.2f}")
            print(f"  최대 낙폭:    {s['max_drawdown']:.2%}")
        print("=" * 52)


class Backtester:
    def __init__(self, initial_capital: float = 10_000_000,
                 stop_loss_ratio: float = 0.03,
                 take_profit_ratio: float = 0.06,
                 position_ratio: float = 0.05,
                 commission_rate: float = 0.0005):
        self.initial_capital   = initial_capital
        self.stop_loss_ratio   = stop_loss_ratio
        self.take_profit_ratio = take_profit_ratio
        self.position_ratio    = position_ratio
        self.commission        = commission_rate

    def run(self, df: pd.DataFrame, strategy, symbol: str = "SYMBOL",
            lookback: int = 300) -> BacktestResult:
        """
        고정 룩백 윈도우 백테스트 - O(n) 성능
        매 캔들마다 최근 lookback개만 전달 → 전략 분석 속도 일정 유지
        lookback은 지표 계산에 필요한 최소 캔들 수 (default: 300 ≥ MA200+여유)
        """
        result   = BacktestResult()
        capital  = self.initial_capital
        position = None

        from bot.strategy.base import Signal

        warmup = lookback   # 처음 lookback개는 워밍업

        for i in range(warmup, len(df)):
            # 고정 크기 윈도우: 매번 lookback개 캔들만 잘라서 전달
            window        = df.iloc[i - lookback + 1 : i + 1].copy().reset_index(drop=True)
            current_price = float(df.iloc[i]["close"])
            ts            = df.iloc[i]["datetime"] if "datetime" in df.columns else i

            # ── 보유 중: 손절/익절/매도 신호 ─────────────────────────
            if position:
                entry = position["entry_price"]
                sl    = entry * (1 - self.stop_loss_ratio)
                tp    = entry * (1 + self.take_profit_ratio)
                exit_reason = None
                exit_price  = current_price

                if current_price <= sl:
                    exit_reason, exit_price = "손절", sl
                elif current_price >= tp:
                    exit_reason, exit_price = "익절", tp
                else:
                    try:
                        sig = strategy.analyze(window, symbol)
                        if sig == Signal.SELL:
                            exit_reason = strategy.get_reason() or "매도신호"
                    except Exception:
                        pass

                if exit_reason:
                    qty = position["quantity"]
                    capital += exit_price * qty * (1 - self.commission)
                    result.add_trade(
                        entry_time=position["entry_time"], exit_time=ts,
                        symbol=symbol, side="buy",
                        entry_price=entry, exit_price=exit_price,
                        quantity=qty, strategy=strategy.name, reason=exit_reason,
                    )
                    result.equity_curve.append({"time": ts, "equity": capital})
                    position = None
                else:
                    result.equity_curve.append({"time": ts, "equity": capital})
                continue

            # ── 미보유: 매수 신호 체크 ────────────────────────────────
            try:
                sig = strategy.analyze(window, symbol)
            except Exception:
                result.equity_curve.append({"time": ts, "equity": capital})
                continue

            if sig == Signal.BUY:
                amount = capital * self.position_ratio
                if amount * (1 + self.commission) > capital:
                    result.equity_curve.append({"time": ts, "equity": capital})
                    continue
                qty      = amount / current_price
                capital -= amount * (1 + self.commission)
                position = {"entry_price": current_price, "quantity": qty, "entry_time": ts}

            result.equity_curve.append({"time": ts, "equity": capital})

        # 마지막 포지션 시장가 청산
        if position:
            last_price = float(df["close"].iloc[-1])
            last_ts    = df["datetime"].iloc[-1] if "datetime" in df.columns else len(df) - 1
            capital   += last_price * position["quantity"] * (1 - self.commission)
            result.add_trade(
                entry_time=position["entry_time"], exit_time=last_ts,
                symbol=symbol, side="buy",
                entry_price=position["entry_price"], exit_price=last_price,
                quantity=position["quantity"], strategy=strategy.name, reason="기간종료",
            )

        return result

    def run_mtf(self, df_ltf: pd.DataFrame, strategy,
                htf_resample: str = "240min",
                symbol: str = "SYMBOL", lookback_ltf: int = 200,
                lookback_htf: int = 100) -> "BacktestResult":
        """
        MTF 전략 백테스트.
        df_ltf(15분봉)를 HTF(4H봉)로 리샘플하여 analyze_mtf() 호출.
        """
        result   = BacktestResult()
        capital  = self.initial_capital
        position = None

        from bot.strategy.base import Signal

        # HTF 사전 계산 (확정된 캔들만 사용)
        df_ltf_idx = df_ltf.set_index("datetime") if "datetime" in df_ltf.columns else df_ltf
        df_htf_full = df_ltf_idx.resample(htf_resample).agg(
            open=("open", "first"), high=("high", "max"),
            low=("low", "min"), close=("close", "last"), volume=("volume", "sum"),
        ).dropna(subset=["close"]).reset_index()
        df_htf_full = df_htf_full.rename(columns={"index": "datetime"})

        # HTF 캔들 주기 — 미확정 캔들 제외에 사용 (예: "240min" → Timedelta)
        import pandas as _pd
        _htf_timedelta = _pd.Timedelta(htf_resample)

        warmup = max(lookback_ltf, lookback_htf * 16)  # 16 × 15분 = 4H

        for i in range(warmup, len(df_ltf)):
            window_ltf    = df_ltf.iloc[i - lookback_ltf + 1 : i + 1].copy().reset_index(drop=True)
            current_price = float(df_ltf.iloc[i]["close"])
            ts            = df_ltf.iloc[i]["datetime"] if "datetime" in df_ltf.columns else i

            # HTF 윈도우: 현재 캔들 시각보다 한 주기 이상 이전에 시작한 확정 캔들만 포함
            if "datetime" in df_htf_full.columns:
                htf_slice = df_htf_full[df_htf_full["datetime"] + _htf_timedelta <= ts]
            else:
                htf_slice = df_htf_full
            window_htf = htf_slice.tail(lookback_htf).reset_index(drop=True)

            if position:
                entry = position["entry_price"]
                sl    = position["sl"]
                tp    = position["tp"]
                exit_reason = None
                exit_price  = current_price

                if current_price <= sl:
                    exit_reason, exit_price = "손절", sl
                elif current_price >= tp:
                    exit_reason, exit_price = "익절", tp
                else:
                    try:
                        sig = strategy.analyze_mtf(window_ltf, window_htf, symbol)
                        if sig == Signal.SELL:
                            exit_reason = strategy.get_reason() or "매도신호"
                    except Exception:
                        pass

                if exit_reason:
                    qty = position["quantity"]
                    capital += exit_price * qty * (1 - self.commission)
                    result.add_trade(
                        entry_time=position["entry_time"], exit_time=ts,
                        symbol=symbol, side="buy",
                        entry_price=entry, exit_price=exit_price,
                        quantity=qty, strategy=strategy.name, reason=exit_reason,
                    )
                    result.equity_curve.append({"time": ts, "equity": capital})
                    position = None
                else:
                    result.equity_curve.append({"time": ts, "equity": capital})
                continue

            try:
                sig = strategy.analyze_mtf(window_ltf, window_htf, symbol)
            except Exception:
                result.equity_curve.append({"time": ts, "equity": capital})
                continue

            if sig == Signal.BUY:
                amount = capital * self.position_ratio
                if amount * (1 + self.commission) > capital:
                    result.equity_curve.append({"time": ts, "equity": capital})
                    continue
                qty = amount / current_price
                capital -= amount * (1 + self.commission)
                # 전략이 계산한 SL/TP 사용 (없으면 고정 비율 fallback)
                strat_sl, strat_tp = strategy.get_last_sl_tp() if hasattr(strategy, "get_last_sl_tp") else (None, None)
                pos_sl = strat_sl if strat_sl and strat_sl < current_price else current_price * (1 - self.stop_loss_ratio)
                pos_tp = strat_tp if strat_tp and strat_tp > current_price else current_price * (1 + self.take_profit_ratio)
                position = {"entry_price": current_price, "quantity": qty, "entry_time": ts,
                            "sl": pos_sl, "tp": pos_tp}

            result.equity_curve.append({"time": ts, "equity": capital})

        if position:
            last_price = float(df_ltf["close"].iloc[-1])
            last_ts    = df_ltf["datetime"].iloc[-1] if "datetime" in df_ltf.columns else len(df_ltf) - 1
            capital   += last_price * position["quantity"] * (1 - self.commission)
            result.add_trade(
                entry_time=position["entry_time"], exit_time=last_ts,
                symbol=symbol, side="buy",
                entry_price=position["entry_price"], exit_price=last_price,
                quantity=position["quantity"], strategy=strategy.name, reason="기간종료",
            )

        return result


# ── 데이터 로드 ────────────────────────────────────────────────────────
def fetch_upbit_ohlcv(symbol: str = "KRW-BTC", days: int = 365,
                      interval: str = "day", candles: int = None) -> pd.DataFrame:
    """
    업비트 OHLCV 로드 (pyupbit)
    200개 제한을 to 파라미터 반복 호출로 우회 → 원하는 캔들 수만큼 수집
    interval: day / minute240 / minute60 / minute15 등
    candles : 수집할 총 캔들 수 (None이면 days 기준으로 자동 계산)
    """
    try:
        import pyupbit
        import time as _time

        # 수집 목표 캔들 수 계산
        if candles is None:
            candles_per_day = {"day": 1, "minute240": 6, "minute60": 24, "minute15": 96}
            cpd = candles_per_day.get(interval, 1)
            candles = days * cpd

        chunks = []
        to = None
        remaining = candles

        while remaining > 0:
            count = min(200, remaining)
            if to is None:
                chunk = pyupbit.get_ohlcv(symbol, interval=interval, count=count)
            else:
                chunk = pyupbit.get_ohlcv(symbol, interval=interval, count=count, to=to)

            if chunk is None or len(chunk) == 0:
                break

            chunks.append(chunk)
            remaining -= len(chunk)
            to = chunk.index[0].strftime("%Y-%m-%d %H:%M:%S")
            _time.sleep(0.25)

        if not chunks:
            raise ValueError("데이터 없음")

        df = pd.concat(chunks[::-1])
        df = df[~df.index.duplicated(keep="last")]
        df = df.sort_index()
        df = df.reset_index().rename(columns={"index": "datetime"})
        df.columns = [c.lower() for c in df.columns]
        df = df.sort_values("datetime").reset_index(drop=True)
        return df

    except Exception as e:
        logger.warning(f"업비트 데이터 로드 실패 ({e}) → 샘플 데이터 사용")
        return _generate_sample_data(days)


def _generate_sample_data(days: int = 365) -> pd.DataFrame:
    """테스트용 샘플 OHLCV 생성"""
    np.random.seed(42)
    dates  = pd.date_range(end=datetime.now(), periods=days, freq="D")
    close  = 50_000_000.0
    rows   = []
    for d in dates:
        change = np.random.normal(0.0005, 0.022)
        close  = close * (1 + change)
        o = close * (1 + np.random.uniform(-0.005, 0.005))
        h = max(o, close) * (1 + abs(np.random.normal(0, 0.005)))
        l = min(o, close) * (1 - abs(np.random.normal(0, 0.005)))
        v = np.random.uniform(500, 5000)
        rows.append({"datetime": d, "open": o, "high": h, "low": l, "close": close, "volume": v})
    return pd.DataFrame(rows)


# ── 전략 로드 헬퍼 ─────────────────────────────────────────────────────
def get_strategy_map():
    from bot.strategy.ma_pullback        import MAPullbackStrategy
    from bot.strategy.trend_following    import TrendFollowingStrategy
    from bot.strategy.bollinger_breakout import BollingerBreakoutStrategy
    from bot.strategy.turtle             import TurtleStrategy
    from bot.strategy.mtf_structure      import MTFStructureStrategy
    return {
        "turtle":             TurtleStrategy,
        "trend_following":    TrendFollowingStrategy,
        "bollinger_breakout": BollingerBreakoutStrategy,
        "ma_pullback":        MAPullbackStrategy,
        "mtf_structure":      MTFStructureStrategy,
    }


# ── 배치 실행 ─────────────────────────────────────────────────────────
def run_batch(symbols: list[str], strategy_names: list[str], capital: float = 10_000_000):
    """
    전략별 최적 시간봉으로 배치 백테스트
    STRATEGY_TIMEFRAME 맵에서 각 전략에 맞는 봉/기간 자동 선택
    """
    strategy_map = get_strategy_map()
    backtester   = Backtester(initial_capital=capital)

    print(f"\n{'='*72}")
    print(f"  📊 멀티 타임프레임 배치 백테스트  |  초기자본: {capital/1e6:.0f}M원")
    print(f"  종목: {symbols}")
    print(f"{'='*72}")
    print(f"\n  {'전략':<22} {'봉':<8} {'종목':<12} {'거래':>5} {'승률':>6} {'총손익':>13} {'PF':>6} {'MDD':>7}")
    print(f"  {'-'*72}")

    batch_rows = []
    # 심볼별로 이미 가져온 데이터 캐시 (interval → df)
    cache: dict[str, dict[str, pd.DataFrame]] = {}  # symbol → {interval: df}

    for sname in strategy_names:
        if sname not in strategy_map:
            continue

        interval, candles = STRATEGY_TIMEFRAME.get(sname, ("day", 1095))
        label = INTERVAL_LABEL.get(interval, interval)

        for symbol in symbols:
            # 캐시 확인
            if symbol not in cache:
                cache[symbol] = {}
            if interval not in cache[symbol]:
                print(f"\n  ▼ {symbol} {label} 데이터 로드 중...", end=" ", flush=True)
                df = fetch_upbit_ohlcv(symbol, interval=interval, candles=candles)
                cache[symbol][interval] = df
                print(f"{len(df):,}캔들 완료")

            df = cache[symbol][interval]

            try:
                strategy = strategy_map[sname]()
                if sname == "mtf_structure":
                    result = backtester.run_mtf(df, strategy, symbol=symbol)
                else:
                    result = backtester.run(df, strategy, symbol=symbol)
                s        = result.summary()

                if "message" in s or s.get("total_trades", 0) == 0:
                    print(f"  {sname:<22} {label:<8} {symbol:<12} {'0':>5}  (신호없음)")
                    continue

                pf_str  = f"{s['profit_factor']:.2f}" if s['profit_factor'] != float("inf") else "  ∞"
                pnl_str = f"{s['total_pnl']:+,.0f}"
                print(f"  {sname:<22} {label:<8} {symbol:<12} {s['total_trades']:>5} "
                      f"{s['win_rate']:>5.1%} {pnl_str:>13} {pf_str:>6} "
                      f"{s['max_drawdown']:>6.1%}")

                batch_rows.append({"strategy": sname, "symbol": symbol,
                                   "interval": label, **s})
            except Exception as e:
                print(f"  {sname:<22} {label:<8} {symbol:<12}  ERROR: {e}")

    # ── 전략별 종합 요약 ────────────────────────────────────────────
    if batch_rows:
        print(f"\n{'='*72}")
        print("  📈 전략별 종합 (전 종목 합산, 최적 시간봉 기준)")
        print(f"{'='*72}")
        print(f"  {'전략':<22} {'봉':<8} {'총거래':>6} {'승률':>6} {'총손익':>14} {'평균PF':>8}")
        print(f"  {'-'*65}")

        by_strategy: dict[str, list] = {}
        for r in batch_rows:
            by_strategy.setdefault(r["strategy"], []).append(r)

        ranked = []
        for sname, rows in by_strategy.items():
            total_trades = sum(r["total_trades"] for r in rows)
            if total_trades == 0:
                continue
            total_wins = sum(r["win_count"] for r in rows)
            total_pnl  = sum(r["total_pnl"] for r in rows)
            pfs = [r["profit_factor"] for r in rows if r["profit_factor"] != float("inf")]
            avg_pf = np.mean(pfs) if pfs else 0
            wr = total_wins / total_trades
            ivl = rows[0]["interval"]
            ranked.append((total_pnl, sname, ivl, total_trades, wr, total_pnl, avg_pf))

        for row in sorted(ranked, reverse=True):
            _, sname, ivl, tc, wr, pnl, pf = row
            print(f"  {sname:<22} {ivl:<8} {tc:>6} {wr:>5.1%} {pnl:>+14,.0f}원  {pf:>7.2f}")

        best = max(batch_rows, key=lambda r: r["total_pnl"])
        print(f"\n  🏆 최고: {best['strategy']} ({best['interval']}) × {best['symbol']}"
              f"  →  {best['total_pnl']:+,.0f}원  (승률 {best['win_rate']:.1%})")
        worst = min(batch_rows, key=lambda r: r["total_pnl"])
        print(f"  💀 최저: {worst['strategy']} ({worst['interval']}) × {worst['symbol']}"
              f"  →  {worst['total_pnl']:+,.0f}원  (승률 {worst['win_rate']:.1%})")

    print(f"\n{'='*72}\n")


def main():
    parser = argparse.ArgumentParser(description="AutoTrade Bot 백테스터")
    parser.add_argument("--symbol",   default=None,   help="단일 종목 (없으면 배치)")
    parser.add_argument("--strategy", default=None,   choices=ALL_STRATEGIES, help="단일 전략 (없으면 배치)")
    parser.add_argument("--days",     type=int, default=365, help="백테스트 기간(일)")
    parser.add_argument("--capital",  type=float, default=10_000_000, help="초기 자본")
    parser.add_argument("--sample",   action="store_true", help="샘플 데이터 사용")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)

    # 단일 실행
    if args.symbol and args.strategy:
        strategy_map = get_strategy_map()
        strategy     = strategy_map[args.strategy]()
        df = _generate_sample_data(args.days) if args.sample else fetch_upbit_ohlcv(args.symbol, args.days)
        print(f"\n▶ {args.symbol} / {args.strategy} / {len(df)}일치")
        result = Backtester(initial_capital=args.capital).run(df, strategy, symbol=args.symbol)
        result.print_summary()
        if result.trades:
            print("\n최근 거래 (최대 10건):")
            for t in result.trades[-10:]:
                print(f"  {t['strategy']} | {t['entry_time']} → {t['exit_time']} "
                      f"| {t['entry_price']:,.0f} → {t['exit_price']:,.0f} "
                      f"| PnL: {t['pnl']:+,.0f}원 ({t['pnl_ratio']:+.2%}) | {t['reason']}")
        return

    # 배치 실행 (기본) - 전략별 최적 시간봉 자동 선택
    symbols    = [args.symbol]   if args.symbol   else UPBIT_SYMBOLS
    strategies = [args.strategy] if args.strategy else ALL_STRATEGIES
    run_batch(symbols, strategies, capital=args.capital)


if __name__ == "__main__":
    main()
