import json
import sqlite3
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "trades.db"


class Storage:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(DB_PATH)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")   # 다중 연결 안전
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self):
        with self._conn() as conn:
            # ── 거래 이력 ──────────────────────────────────────────
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT    NOT NULL,
                    exchange  TEXT    NOT NULL,
                    symbol    TEXT    NOT NULL,
                    side      TEXT    NOT NULL,
                    strategy  TEXT    NOT NULL,
                    price     REAL    NOT NULL,
                    quantity  REAL    NOT NULL,
                    amount    REAL    NOT NULL,
                    pnl       REAL,
                    reason    TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_exchange_symbol ON trades(exchange, symbol)")

            # ── OHLCV 캐시 ────────────────────────────────────────
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ohlcv (
                    symbol    TEXT NOT NULL,
                    market    TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    ts        TEXT NOT NULL,
                    open      REAL NOT NULL,
                    high      REAL NOT NULL,
                    low       REAL NOT NULL,
                    close     REAL NOT NULL,
                    volume    REAL NOT NULL,
                    PRIMARY KEY (symbol, market, timeframe, ts)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ohlcv_lookup
                ON ohlcv(symbol, market, timeframe, ts)
            """)

            # ── 종목 정보 (코드 ↔ 이름) ───────────────────────────
            conn.execute("""
                CREATE TABLE IF NOT EXISTS symbol_info (
                    symbol     TEXT NOT NULL,
                    market     TEXT NOT NULL,
                    name       TEXT,
                    updated_at TEXT,
                    PRIMARY KEY (symbol, market)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_symbol_name ON symbol_info(name, market)")

            # ── 종목 분석 결과 캐시 ───────────────────────────────
            conn.execute("""
                CREATE TABLE IF NOT EXISTS analysis_cache (
                    symbol     TEXT NOT NULL,
                    market     TEXT NOT NULL,
                    interval   TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    data       TEXT NOT NULL,
                    PRIMARY KEY (symbol, market, interval)
                )
            """)
            conn.commit()

    # ── 거래 이력 ──────────────────────────────────────────────────
    def save_trade(self, exchange: str, symbol: str, side: str, strategy: str,
                   price: float, quantity: float, amount: float,
                   pnl: Optional[float] = None, reason: str = "") -> int:
        ts = datetime.now().isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO trades (timestamp, exchange, symbol, side, strategy,
                   price, quantity, amount, pnl, reason)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (ts, exchange, symbol, side, strategy, price, quantity, amount, pnl, reason),
            )
            conn.commit()
            return cur.lastrowid

    def get_recent_trades(self, limit: int = 20) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_today_trades(self) -> list[dict]:
        today = date.today().isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM trades WHERE timestamp >= ? ORDER BY timestamp DESC",
                (today,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_pnl_chart_data(self, days: int = 30) -> list[dict]:
        """누적 손익 차트 데이터 (일별)"""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT date(timestamp) as trade_date, SUM(pnl) as daily_pnl
                   FROM trades
                   WHERE pnl IS NOT NULL AND side = 'sell'
                   GROUP BY date(timestamp)
                   ORDER BY trade_date ASC
                   LIMIT ?""",
                (days,),
            ).fetchall()
        result = []
        cumulative = 0.0
        for row in rows:
            daily = row["daily_pnl"] or 0.0
            cumulative += daily
            result.append({"date": row["trade_date"], "daily_pnl": daily, "cumulative_pnl": cumulative})
        return result

    def get_strategy_stats(self) -> list[dict]:
        """전략별 성과 통계"""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT strategy,
                          COUNT(*) as total_trades,
                          SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                          AVG(CASE WHEN pnl IS NOT NULL THEN pnl / amount ELSE NULL END) as avg_return,
                          SUM(COALESCE(pnl, 0)) as total_pnl
                   FROM trades
                   WHERE side = 'sell'
                   GROUP BY strategy""",
            ).fetchall()
        stats = []
        for row in rows:
            total = row["total_trades"] or 1
            stats.append({
                "strategy": row["strategy"],
                "trade_count": row["total_trades"],
                "win_count": row["wins"] or 0,
                "win_rate": (row["wins"] or 0) / total,
                "avg_return": row["avg_return"] or 0.0,
                "total_pnl": row["total_pnl"] or 0.0,
            })
        return stats

    def get_open_positions(self) -> list[dict]:
        """재시작 후 복원용: 매수 후 매도 없는 미청산 포지션"""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT t.*
                   FROM trades t
                   WHERE t.side = 'buy'
                   AND NOT EXISTS (
                       SELECT 1 FROM trades t2
                       WHERE t2.exchange = t.exchange
                       AND t2.symbol = t.symbol
                       AND t2.side = 'sell'
                       AND t2.timestamp > t.timestamp
                   )
                   ORDER BY t.timestamp ASC"""
            ).fetchall()
        return [dict(r) for r in rows]

    def get_daily_summary(self) -> dict:
        today = date.today().isoformat()
        with self._conn() as conn:
            row = conn.execute(
                """SELECT COUNT(*) as count,
                          SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                          SUM(COALESCE(pnl, 0)) as total_pnl
                   FROM trades
                   WHERE timestamp >= ? AND side = 'sell'""",
                (today,),
            ).fetchone()
            rows_by_exchange = conn.execute(
                """SELECT exchange, SUM(COALESCE(pnl, 0)) as pnl
                   FROM trades WHERE timestamp >= ? AND side = 'sell'
                   GROUP BY exchange""",
                (today,),
            ).fetchall()

        pnl_by_exchange: dict[str, float] = {}
        for r in rows_by_exchange:
            pnl_by_exchange[r["exchange"]] = r["pnl"] or 0.0

        return {
            "trade_count": row["count"] or 0 if row else 0,
            "win_count": row["wins"] or 0 if row else 0,
            "total_pnl": row["total_pnl"] or 0.0 if row else 0.0,
            "upbit_pnl": pnl_by_exchange.get("upbit", 0.0),
            "kis_domestic_pnl": pnl_by_exchange.get("kis_domestic", 0.0),
            "kis_overseas_pnl": pnl_by_exchange.get("kis_overseas", 0.0),
        }

    def get_today_pnl(self) -> float:
        return self.get_daily_summary().get("total_pnl", 0.0)

    def get_trades_by_symbol(self, symbol: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM trades WHERE symbol = ? ORDER BY timestamp ASC",
                (symbol,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_trade_events(self, days: int = 60) -> dict:
        since = (date.today() - timedelta(days=days)).isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT date(timestamp) as d, side FROM trades WHERE timestamp >= ? ORDER BY timestamp ASC",
                (since,),
            ).fetchall()
        buy_dates, sell_dates = set(), set()
        for r in rows:
            if r["side"] == "buy":
                buy_dates.add(r["d"])
            else:
                sell_dates.add(r["d"])
        return {"buy_dates": sorted(buy_dates), "sell_dates": sorted(sell_dates)}

    # ── OHLCV 캐시 ────────────────────────────────────────────────
    def upsert_ohlcv(self, symbol: str, market: str, timeframe: str, df) -> None:
        """DataFrame → DB 저장 (INSERT OR REPLACE)"""
        import pandas as pd
        if df is None or len(df) == 0:
            return
        rows = []
        for idx, row in df.iterrows():
            try:
                ts = str(idx)[:19]  # "2026-02-27" or "2026-02-27T09:30:00"
                rows.append((
                    symbol, market, timeframe, ts,
                    float(row["open"]), float(row["high"]),
                    float(row["low"]), float(row["close"]),
                    float(row["volume"]),
                ))
            except (ValueError, KeyError):
                continue
        if not rows:
            return
        with self._conn() as conn:
            conn.executemany("""
                INSERT OR REPLACE INTO ohlcv
                (symbol, market, timeframe, ts, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)
            conn.commit()

    def get_ohlcv(self, symbol: str, market: str, timeframe: str,
                  limit: int = 300) -> Optional["pd.DataFrame"]:
        """DB에서 OHLCV 조회. 없으면 None."""
        import pandas as pd
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT ts, open, high, low, close, volume
                   FROM ohlcv WHERE symbol=? AND market=? AND timeframe=?
                   ORDER BY ts DESC LIMIT ?""",
                (symbol, market, timeframe, limit),
            ).fetchall()
        if not rows:
            return None
        df = pd.DataFrame([dict(r) for r in rows])
        df["ts"] = pd.to_datetime(df["ts"])
        df = df.set_index("ts").sort_index()
        return df[["open", "high", "low", "close", "volume"]]

    def get_ohlcv_latest_ts(self, symbol: str, market: str, timeframe: str) -> Optional[str]:
        """DB의 가장 최근 OHLCV 타임스탬프"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT MAX(ts) as latest FROM ohlcv WHERE symbol=? AND market=? AND timeframe=?",
                (symbol, market, timeframe),
            ).fetchone()
        return row["latest"] if row and row["latest"] else None

    # ── 종목 정보 ─────────────────────────────────────────────────
    def upsert_symbol_info(self, symbol: str, market: str, name: str) -> None:
        with self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO symbol_info (symbol, market, name, updated_at)
                VALUES (?, ?, ?, ?)
            """, (symbol, market, name, datetime.now().isoformat()))
            conn.commit()

    def bulk_upsert_symbol_info(self, items: list[tuple[str, str, str]]) -> None:
        """[(symbol, market, name), ...] 일괄 저장"""
        ts = datetime.now().isoformat()
        with self._conn() as conn:
            conn.executemany("""
                INSERT OR REPLACE INTO symbol_info (symbol, market, name, updated_at)
                VALUES (?, ?, ?, ?)
            """, [(s, m, n, ts) for s, m, n in items])
            conn.commit()

    def get_symbol_by_name(self, name: str, market: str = None) -> Optional[str]:
        """종목명 → 코드"""
        with self._conn() as conn:
            if market:
                row = conn.execute(
                    "SELECT symbol FROM symbol_info WHERE name=? AND market=?",
                    (name, market),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT symbol FROM symbol_info WHERE name=?", (name,)
                ).fetchone()
        return row["symbol"] if row else None

    def get_symbol_name(self, symbol: str, market: str = None) -> Optional[str]:
        """코드 → 종목명"""
        with self._conn() as conn:
            if market:
                row = conn.execute(
                    "SELECT name FROM symbol_info WHERE symbol=? AND market=?",
                    (symbol, market),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT name FROM symbol_info WHERE symbol=?", (symbol,)
                ).fetchone()
        return row["name"] if row else None

    def get_all_symbols(self, market: str = None) -> list[tuple[str, str, str]]:
        """symbol_info 전체 목록 반환: [(symbol, market, name), ...]"""
        with self._conn() as conn:
            if market:
                rows = conn.execute(
                    "SELECT symbol, market, name FROM symbol_info WHERE market=? ORDER BY symbol",
                    (market,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT symbol, market, name FROM symbol_info ORDER BY symbol"
                ).fetchall()
        return [(r["symbol"], r["market"], r["name"] or "") for r in rows]

    def search_symbols(self, query: str, market: str = None, limit: int = 10) -> list[dict]:
        """종목명 부분 검색 (자동완성용)"""
        with self._conn() as conn:
            if market:
                rows = conn.execute(
                    "SELECT symbol, market, name FROM symbol_info WHERE name LIKE ? AND market=? LIMIT ?",
                    (f"%{query}%", market, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT symbol, market, name FROM symbol_info WHERE name LIKE ? LIMIT ?",
                    (f"%{query}%", limit),
                ).fetchall()
        return [dict(r) for r in rows]

    # ── 분석 캐시 ─────────────────────────────────────────────────
    def set_analysis_cache(self, symbol: str, market: str, interval: str, data: dict) -> None:
        with self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO analysis_cache (symbol, market, interval, updated_at, data)
                VALUES (?, ?, ?, ?, ?)
            """, (symbol, market, interval,
                  datetime.now().isoformat(),
                  json.dumps(data, ensure_ascii=False)))
            conn.commit()

    def get_analysis_cache(self, symbol: str, market: str, interval: str,
                           max_age_hours: float = 1.0) -> Optional[dict]:
        """캐시 조회. max_age_hours 초과 시 None 반환."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT updated_at, data FROM analysis_cache WHERE symbol=? AND market=? AND interval=?",
                (symbol, market, interval),
            ).fetchone()
        if not row:
            return None
        age_hours = (datetime.now() - datetime.fromisoformat(row["updated_at"])).total_seconds() / 3600
        if age_hours > max_age_hours:
            return None
        try:
            return json.loads(row["data"])
        except Exception:
            return None
