"""데이터 수집 엔진 — 전체 유니버스 OHLCV 증분 업데이트

매일 12:30 KST 실행 (주말 포함)

지원 시장:
  국내: KOSPI + KOSDAQ (네이버 fchart XML + sise_market_sum, 24h 동작)
  해외: NASDAQ (yfinance, 주말/야간 동작)
  코인: 업비트 KRW (pyupbit, 24h 동작)

증분 업데이트 로직:
  최초 실행: count=300 (전체 히스토리)
  이후 실행: count=5  (최근 5봉만 업데이트)
"""
import asyncio
import logging
import time
import xml.etree.ElementTree as ET
from typing import Optional

import pandas as pd
import requests

from bot.storage import Storage

logger = logging.getLogger(__name__)

_NAVER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}


class DataSync:
    """전체 유니버스 OHLCV 데이터 증분 업데이트 엔진"""

    def __init__(self, storage: Storage):
        self.storage = storage

    # ── 국내 종목 목록 ──────────────────────────────────────────────

    def fetch_domestic_universe(self) -> list[tuple[str, str, str]]:
        """네이버 sise_market_sum으로 전체 KOSPI + KOSDAQ 종목 목록 수집

        Returns: [(code, market_type, name), ...]
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            logger.error("[DataSync] BeautifulSoup4 미설치: pip install beautifulsoup4 lxml")
            return []

        result = []
        for market_name, sosok in [("KOSPI", 0), ("KOSDAQ", 1)]:
            page = 1
            while True:
                try:
                    url = (
                        f"https://finance.naver.com/sise/sise_market_sum.nhn"
                        f"?sosok={sosok}&page={page}"
                    )
                    resp = requests.get(url, headers=_NAVER_HEADERS, timeout=15)
                    resp.encoding = "euc-kr"
                    soup = BeautifulSoup(resp.text, "lxml")
                    rows = soup.select("table.type_2 tr")
                    found = 0
                    for tr in rows:
                        a = tr.select_one("td a[href*=code]")
                        if not a:
                            continue
                        code = a["href"].split("code=")[-1].strip()
                        name = a.text.strip()
                        if code and name:
                            result.append((code, market_name, name))
                            found += 1
                    if found == 0:
                        break
                    page += 1
                    time.sleep(0.1)
                except Exception as e:
                    logger.warning(f"[DataSync] 국내 종목 크롤링 오류 (page={page}): {e}")
                    break

        logger.info(f"[DataSync] 국내 종목 목록 수집: {len(result)}개 (KOSPI+KOSDAQ)")
        return result

    # ── 네이버 fchart 일봉 ─────────────────────────────────────────

    def fetch_fchart_daily(self, code: str, count: int = 300) -> Optional[pd.DataFrame]:
        """네이버 fchart XML 일봉 (24h/주말 동작)

        반환: DatetimeIndex DataFrame, columns=[open, high, low, close, volume]
        """
        try:
            resp = requests.get(
                "https://fchart.stock.naver.com/sise.nhn",
                params={
                    "symbol": code,
                    "timeframe": "day",
                    "count": count,
                    "requestType": "0",
                },
                headers=_NAVER_HEADERS,
                timeout=15,
            )
            resp.raise_for_status()
            root = ET.fromstring(resp.content.decode("euc-kr", errors="replace"))
            rows = []
            for item in root.iter("item"):
                parts = item.attrib.get("data", "").split("|")
                if len(parts) < 6:
                    continue
                try:
                    date_str = parts[0]  # YYYYMMDD
                    ts = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
                    rows.append({
                        "ts": ts,
                        "open": float(parts[1]),
                        "high": float(parts[2]),
                        "low": float(parts[3]),
                        "close": float(parts[4]),
                        "volume": float(parts[5]),
                    })
                except (ValueError, IndexError):
                    continue
            if not rows:
                return None
            df = pd.DataFrame(rows)
            df["ts"] = pd.to_datetime(df["ts"])
            df = df.set_index("ts").sort_index()
            return df[["open", "high", "low", "close", "volume"]]
        except Exception as e:
            logger.debug(f"[DataSync] fchart 일봉 오류 {code}: {e}")
            return None

    # ── NASDAQ 전체 종목 목록 ──────────────────────────────────────

    def fetch_nasdaq_universe(self) -> list[tuple[str, str, str]]:
        """NASDAQ API로 전체 상장 종목 목록 수집

        Returns: [(symbol, "overseas", name), ...]
        ~4,000개 반환
        """
        try:
            resp = requests.get(
                "https://api.nasdaq.com/api/screener/stocks",
                params={"tableonly": "true", "exchange": "NASDAQ", "download": "true"},
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                    "Accept": "application/json",
                },
                timeout=20,
            )
            resp.raise_for_status()
            rows = resp.json().get("data", {}).get("rows", [])
            result = [
                (r["symbol"], "overseas", r.get("name", r["symbol"]))
                for r in rows
                if r.get("symbol") and r["symbol"].isalpha()  # 특수문자 심볼 제외 (워런트/유닛 등)
            ]
            logger.info(f"[DataSync] NASDAQ 전체 유니버스: {len(result)}개 수집")
            return result
        except Exception as e:
            logger.error(f"[DataSync] NASDAQ 유니버스 수집 실패: {e}")
            return []

    # ── yfinance 해외 배치 ─────────────────────────────────────────

    def fetch_yfinance_batch(
        self, symbols: list[str], period: str = "2y"
    ) -> dict[str, pd.DataFrame]:
        """yfinance 단일 배치 다운로드 (symbols는 500개 이하 권장)

        Returns: {symbol: DataFrame(open/high/low/close/volume)}
        """
        import yfinance as yf

        try:
            hist = yf.download(
                symbols,
                period=period,
                interval="1d",
                group_by="ticker",
                progress=False,
                auto_adjust=True,
                threads=True,
            )
            result = {}
            for sym in symbols:
                try:
                    df_raw = hist[sym] if isinstance(hist.columns, pd.MultiIndex) else hist
                    df_raw = df_raw.dropna(subset=["Close"])
                    if df_raw is None or len(df_raw) < 5:
                        continue
                    df = df_raw[["Open", "High", "Low", "Close", "Volume"]].copy()
                    df.columns = ["open", "high", "low", "close", "volume"]
                    result[sym] = df
                except Exception:
                    continue
            return result
        except Exception as e:
            logger.error(f"[DataSync] yfinance 배치 오류: {e}")
            return {}

    # ── pyupbit 코인 일봉 ──────────────────────────────────────────

    def fetch_pyupbit_daily(self, symbol: str, count: int = 300) -> Optional[pd.DataFrame]:
        """pyupbit 코인 일봉 (24h 동작)"""
        import pyupbit

        try:
            df = pyupbit.get_ohlcv(symbol, interval="day", count=count)
            if df is None or len(df) < 5:
                return None
            df.columns = [c.lower() for c in df.columns]
            return df[["open", "high", "low", "close", "volume"]]
        except Exception as e:
            logger.debug(f"[DataSync] pyupbit 일봉 오류 {symbol}: {e}")
            return None

    # ── 국내 동기화 ────────────────────────────────────────────────

    async def sync_domestic(self) -> int:
        """KOSPI + KOSDAQ 전체 일봉 증분 업데이트

        1. 네이버 sise_market_sum으로 전체 종목 목록 크롤링
        2. symbol_info DB 저장
        3. 각 종목 fchart 일봉 증분 업데이트 (최초 300개, 이후 5개)
        """
        logger.info("[DataSync] 국내 일봉 업데이트 시작")

        universe = await asyncio.to_thread(self.fetch_domestic_universe)
        if not universe:
            logger.warning("[DataSync] 국내 종목 목록 크롤링 실패 — 업데이트 건너뜀")
            return 0

        await asyncio.to_thread(self.storage.bulk_upsert_symbol_info, universe)
        logger.info(f"[DataSync] 국내 종목 {len(universe)}개 symbol_info 저장 완료")

        ok, err = 0, 0
        for code, market_type, name in universe:
            # market_type = "KOSPI" or "KOSDAQ" — ohlcv/symbol_info 일관성 유지
            try:
                latest = self.storage.get_ohlcv_latest_ts(code, market_type, "1d")
                fetch_count = 5 if latest else 300
                df = await asyncio.to_thread(self.fetch_fchart_daily, code, fetch_count)
                if df is not None and len(df) > 0:
                    await asyncio.to_thread(
                        self.storage.upsert_ohlcv, code, market_type, "1d", df
                    )
                    ok += 1
                await asyncio.sleep(0.05)
            except Exception as e:
                err += 1
                logger.debug(f"[DataSync] 국내 {code} 오류: {e}")

        logger.info(f"[DataSync] 국내 완료: {ok}개 업데이트, {err}개 실패 (전체 {len(universe)}개)")
        return ok

    # ── 해외 동기화 ────────────────────────────────────────────────

    async def sync_overseas(self) -> int:
        """NASDAQ 전체 종목 일봉 업데이트

        1. NASDAQ API로 전체 유니버스 수집 (~4,000개)
        2. symbol_info DB 저장
        3. 스마트 period 감지:
           - DB에 데이터 없음(최초): period="2y" (~500봉)
           - DB에 데이터 있음(증분): period="5d" (최근 5봉만)
        4. 500개씩 배치로 yfinance 다운로드
        """
        # 1. NASDAQ 전체 유니버스
        universe = await asyncio.to_thread(self.fetch_nasdaq_universe)
        if not universe:
            logger.warning("[DataSync] NASDAQ 유니버스 수집 실패 — 업데이트 건너뜀")
            return 0

        symbols = [sym for sym, _, _ in universe]

        # symbol_info 저장 (종목명 포함)
        await asyncio.to_thread(self.storage.bulk_upsert_symbol_info, universe)
        logger.info(f"[DataSync] 해외 symbol_info {len(universe)}개 저장 완료")

        # 2. 스마트 period: NVDA 데이터가 200봉 이상이면 증분, 아니면 전체
        nvda_df = self.storage.get_ohlcv("NVDA", "overseas", "1d", 1000)
        has_sufficient_data = nvda_df is not None and len(nvda_df) >= 200
        period = "5d" if has_sufficient_data else "2y"
        logger.info(
            f"[DataSync] 해외 일봉 업데이트 시작: {len(symbols)}개, "
            f"period={period} ({'증분' if has_sufficient_data else '최초 전체'})"
        )

        # 3. 500개씩 배치
        batch_size = 500
        batches = [symbols[i:i + batch_size] for i in range(0, len(symbols), batch_size)]
        ok = 0
        for idx, batch in enumerate(batches, 1):
            logger.info(f"[DataSync] 해외 배치 {idx}/{len(batches)} ({len(batch)}개)")
            result = await asyncio.to_thread(self.fetch_yfinance_batch, batch, period)
            for sym, df in result.items():
                try:
                    if df is not None and len(df) > 0:
                        await asyncio.to_thread(
                            self.storage.upsert_ohlcv, sym, "overseas", "1d", df
                        )
                        ok += 1
                except Exception as e:
                    logger.debug(f"[DataSync] 해외 {sym} 저장 오류: {e}")
            # 배치 간 짧은 대기 (yfinance rate limit 방지)
            if idx < len(batches):
                await asyncio.sleep(2)

        logger.info(f"[DataSync] 해외 완료: {ok}/{len(symbols)}개 업데이트")
        return ok

    # ── 코인 동기화 ────────────────────────────────────────────────

    async def sync_upbit(self) -> int:
        """업비트 KRW 코인 전체 일봉 증분 업데이트"""
        import pyupbit

        logger.info("[DataSync] 코인 일봉 업데이트 시작")

        try:
            tickers = await asyncio.to_thread(pyupbit.get_tickers, fiat="KRW")
        except Exception as e:
            logger.error(f"[DataSync] 코인 티커 조회 실패: {e}")
            return 0

        ok = 0
        for symbol in tickers:
            try:
                latest = self.storage.get_ohlcv_latest_ts(symbol, "upbit", "1d")
                fetch_count = 5 if latest else 300
                df = await asyncio.to_thread(self.fetch_pyupbit_daily, symbol, fetch_count)
                if df is not None and len(df) > 0:
                    await asyncio.to_thread(
                        self.storage.upsert_ohlcv, symbol, "upbit", "1d", df
                    )
                    await asyncio.to_thread(
                        self.storage.upsert_symbol_info,
                        symbol, "upbit", symbol.replace("KRW-", ""),
                    )
                    ok += 1
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.debug(f"[DataSync] 코인 {symbol} 오류: {e}")

        logger.info(f"[DataSync] 코인 완료: {ok}/{len(tickers)}개 업데이트")
        return ok

    # ── 전체 동기화 ────────────────────────────────────────────────

    async def sync_all(self) -> dict:
        """전체 데이터 업데이트 (국내 + 해외 + 코인 동시 실행)

        Returns: {domestic: int, overseas: int, upbit: int, elapsed_sec: float}
        """
        logger.info("[DataSync] 전체 데이터 업데이트 시작")
        t0 = asyncio.get_event_loop().time()

        results = await asyncio.gather(
            self.sync_domestic(),
            self.sync_overseas(),
            self.sync_upbit(),
            return_exceptions=True,
        )

        elapsed = round(asyncio.get_event_loop().time() - t0, 1)
        summary = {
            "domestic": results[0] if isinstance(results[0], int) else 0,
            "overseas": results[1] if isinstance(results[1], int) else 0,
            "upbit": results[2] if isinstance(results[2], int) else 0,
            "elapsed_sec": elapsed,
        }
        logger.info(
            f"[DataSync] 전체 완료 — 국내={summary['domestic']} "
            f"해외={summary['overseas']} 코인={summary['upbit']} ({elapsed}초)"
        )
        return summary
