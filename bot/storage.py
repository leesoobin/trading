import sqlite3
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "trades.db"


class Storage:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(DB_PATH)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._conn() as conn:
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
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_exchange_symbol ON trades(exchange, symbol)
            """)
            conn.commit()

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
        if row:
            return {
                "trade_count": row["count"] or 0,
                "win_count": row["wins"] or 0,
                "total_pnl": row["total_pnl"] or 0.0,
            }
        return {"trade_count": 0, "win_count": 0, "total_pnl": 0.0}
