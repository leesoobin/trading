"""
새벽 배치 스크리닝 엔진
장 마감 후 실행 → 기술적 필터 → 장중 모니터링 후보 선별

타임라인:
  00:30 KST → screen_upbit()          업비트 코인
  06:00 KST → screen_kis_overseas()   미국장 마감 후
  15:00 KST → screen_kis_domestic()   한국장 (pykrx 거래량 상위, 장외에도 동작)
"""
import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytz
import requests

# 국내 후보 종목 캐시 경로 (주말/야간 스크리닝 시 재사용)
_DOMESTIC_CACHE = Path(__file__).parent.parent / "data" / "domestic_candidates.json"

_KST = pytz.timezone("Asia/Seoul")

logger = logging.getLogger(__name__)

# 미국 스크리닝 유니버스 (NASDAQ 중심 100종목)
US_UNIVERSE = [
    # ── 반도체/하드웨어 ──────────────────────────────────────────
    "NVDA", "AMD", "INTC", "AVGO", "QCOM", "AMAT", "KLAC", "LRCX", "MU", "NXPI",
    "MRVL", "ON", "MPWR", "SMCI", "ARM", "SWKS", "QRVO", "TXN", "SNPS", "CDNS",
    "KEYS", "WOLF", "COHU", "ACLS", "MCHP",
    # ── 빅테크/소프트웨어 ────────────────────────────────────────
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "ORCL", "ADBE", "CRM", "NOW", "INTU",
    "WDAY", "TEAM", "SNOW", "DDOG", "ZS", "CRWD", "PANW", "FTNT", "S", "NET",
    "OKTA", "PLTR", "MSTR", "GTLB", "MDB",
    # ── AI/데이터 ────────────────────────────────────────────────
    "SOUN", "BBAI", "AI", "IONQ", "QUBT", "RGTI", "ARQQ", "SMCI", "DELL", "HPE",
    # ── 이커머스/소비 플랫폼 ────────────────────────────────────
    "TSLA", "NFLX", "SPOT", "SHOP", "UBER", "LYFT", "ABNB", "DASH", "PINS", "SNAP",
    "ROKU", "TTD", "RBLX", "U", "MELI",
    # ── 핀테크/금융 (NASDAQ 중심) ───────────────────────────────
    "PYPL", "AFRM", "SOFI", "UPST", "COIN", "HOOD", "NU", "IBKR", "SCHW", "V",
    # ── 바이오/헬스케어 (NASDAQ 중심) ───────────────────────────
    "MRNA", "BNTX", "GILD", "VRTX", "BIIB", "REGN", "AMGN", "ALNY", "RXRX", "NVAX",
    # ── 클린에너지/EV ───────────────────────────────────────────
    "RIVN", "LCID", "NIO", "XPEV", "LI", "ENPH", "SEDG", "PLUG", "FSLR", "BLNK",
]


@dataclass
class ScreenResult:
    symbol: str
    exchange: str      # "upbit" | "kis_domestic" | "kis_overseas"
    score: float
    trend: str
    market_type: str = ""          # KOSPI / KOSDAQ / NAS 구분 (main.py 타임프레임 결정용)
    reasons: list[str] = field(default_factory=list)
    name: str = ""                 # 종목명 (텔레그램 알림용)


class Screener:
    """새벽 배치 스크리닝 엔진"""

    def __init__(self, upbit_client, kis_client,
                 top_n_upbit: int = 30,
                 top_n_domestic: int = 30,
                 top_n_overseas: int = 100,
                 storage=None):
        self.upbit = upbit_client
        self.kis = kis_client
        self.top_n_upbit = top_n_upbit
        self.top_n_domestic = top_n_domestic
        self.top_n_overseas = top_n_overseas
        self._storage = storage

    # ── 기술적 점수 계산 ──────────────────────────────────────────
    @staticmethod
    def _tech_score(df: pd.DataFrame) -> tuple[float, str, list[str]]:
        """
        일봉 OHLCV DataFrame → 기술적 점수(0~10점), 추세, 사유 반환

        채점 기준:
          EMA 정배열/역배열  +3점
          거래량 급증 2배↑   +2점 (1.5배↑ +1점)
          52주 신고가 93%↑   +2점 (85%↑ +1점)
          볼린저밴드 수축    +2점 (소폭 수축 +1점)
          20EMA 눌림목       +1점
        """
        if len(df) < 20:
            return 0.0, "neutral", []

        score = 0.0
        reasons = []

        close = df["close"].astype(float)
        volume = df["volume"].astype(float)
        high = df["high"].astype(float)

        # 1. EMA 정배열/역배열 (+3점)
        ema5 = close.ewm(span=5, adjust=False).mean()
        ema20 = close.ewm(span=20, adjust=False).mean()
        ema60 = close.ewm(span=min(60, len(df)), adjust=False).mean()

        e5, e20, e60 = float(ema5.iloc[-1]), float(ema20.iloc[-1]), float(ema60.iloc[-1])
        if e5 > e20 > e60:
            trend = "bullish"
            score += 3
            reasons.append("EMA정배열(5>20>60)")
        elif e5 < e20 < e60:
            trend = "bearish"
            score += 3
            reasons.append("EMA역배열(5<20<60)")
        else:
            trend = "neutral"

        # 2. 거래량 급증 (+2점)
        if len(volume) >= 22:
            avg_vol = float(volume.iloc[-21:-1].mean())
            recent_vol = float(volume.iloc[-1])
            if avg_vol > 0:
                surge = recent_vol / avg_vol
                if surge >= 2.0:
                    score += 2
                    reasons.append(f"거래량급증({surge:.1f}배)")
                elif surge >= 1.5:
                    score += 1
                    reasons.append(f"거래량증가({surge:.1f}배)")

        # 3. 52주 신고가 근처 (+2점)
        lookback = min(len(df), 252)
        high_52w = float(high.iloc[-lookback:].max())
        current = float(close.iloc[-1])
        if high_52w > 0:
            ratio = current / high_52w
            if ratio >= 0.93:
                score += 2
                reasons.append(f"52주고가{ratio*100:.0f}%")
            elif ratio >= 0.85:
                score += 1
                reasons.append(f"52주고가{ratio*100:.0f}%")

        # 4. 볼린저밴드 수축 (+2점)
        if len(df) >= 40:
            std20 = close.rolling(20).std()
            last_std = float(std20.iloc[-1])
            avg_std = float(std20.iloc[-40:].mean())
            last_close = float(close.iloc[-1])
            avg_close = float(close.iloc[-20:].mean())
            if last_close > 0 and avg_close > 0 and avg_std > 0:
                bw_now = last_std / last_close
                bw_avg = avg_std / avg_close
                if bw_now < bw_avg * 0.65:
                    score += 2
                    reasons.append("볼린저수축(강)")
                elif bw_now < bw_avg * 0.80:
                    score += 1
                    reasons.append("볼린저수축")

        # 5. 20EMA 눌림목 (+1점)
        if e20 > 0:
            dist = abs(current - e20) / e20
            if dist <= 0.015:
                score += 1
                reasons.append("20EMA눌림목(1.5%이내)")

        return score, trend, reasons

    # ── 업비트 스크리닝 ───────────────────────────────────────────
    async def screen_upbit(self) -> list[ScreenResult]:
        """
        업비트 KRW 코인 스크리닝
        1순위: 24시간 거래대금 상위 40개 (실시간 Upbit API)
        2순위: DB 일봉 → 기술적 점수 3점 이상 → top_n_upbit 반환
               DB 미보유 시 pyupbit API 폴백
        """
        logger.info("[스크리너] 업비트 스크리닝 시작")
        try:
            import pyupbit

            tickers = pyupbit.get_tickers(fiat="KRW")
            if not tickers:
                logger.warning("[스크리너] 업비트 티커 조회 실패")
                return []

            # 24시간 거래대금 조회 (100개씩 배치)
            candidates = []
            for i in range(0, len(tickers), 100):
                chunk = tickers[i:i + 100]
                try:
                    resp = requests.get(
                        "https://api.upbit.com/v1/ticker",
                        params={"markets": ",".join(chunk)},
                        timeout=10,
                    )
                    if resp.ok:
                        for item in resp.json():
                            candidates.append({
                                "symbol": item["market"],
                                "vol24h": item.get("acc_trade_price_24h", 0),
                            })
                except Exception as e:
                    logger.warning(f"업비트 티커 배치 조회 오류: {e}")
                await asyncio.sleep(0.3)

            # 거래대금 상위 40개 선별
            candidates.sort(key=lambda x: x["vol24h"], reverse=True)
            top40 = [c["symbol"] for c in candidates[:40]]

            # 기술적 필터: DB 일봉 우선, 없으면 API 폴백
            results = []
            for symbol in top40:
                try:
                    df = None
                    # 1) DB에서 일봉 로드
                    if self._storage:
                        df = await asyncio.to_thread(
                            self._storage.get_ohlcv, symbol, "upbit", "1d", 300
                        )
                    # 2) DB 미보유 시 pyupbit API 폴백
                    if df is None or len(df) < 20:
                        df = await asyncio.to_thread(
                            pyupbit.get_ohlcv, symbol, "day", 300
                        )
                        if df is not None:
                            df.columns = [c.lower() for c in df.columns]
                    if df is None or len(df) < 20:
                        continue

                    score, trend, reasons = self._tech_score(df)
                    if score >= 3:
                        results.append(ScreenResult(
                            symbol=symbol, exchange="upbit",
                            score=score, trend=trend,
                            market_type="upbit",
                            reasons=reasons,
                        ))
                    await asyncio.sleep(0.05)
                except Exception as e:
                    logger.warning(f"업비트 {symbol} 분석 오류: {e}")

            results.sort(key=lambda x: x.score, reverse=True)
            selected = results[:self.top_n_upbit]
            logger.info(f"[스크리너] 업비트 완료: {len(selected)}개 선별 → {[r.symbol for r in selected]}")
            return selected

        except Exception as e:
            logger.error(f"[스크리너] 업비트 스크리닝 실패: {e}")
            return []

    # ── KIS 국내 스크리닝 ─────────────────────────────────────────
    async def screen_kis_domestic(self) -> list[ScreenResult]:
        """
        KIS 국내 주식 스크리닝

        [DB 보유 시] DataSync가 미리 수집한 전체 유니버스 사용:
          1단계: symbol_info DB에서 전체 KOSPI+KOSDAQ 목록 로드
          2단계: 각 종목 OHLCV DB에서 로드 (API 재호출 없음)
          3단계: 기술적 점수 3점 이상 → top_n_domestic 반환

        [DB 미보유 시 폴백] 네이버 거래량 순위 크롤링 + fchart API:
          기존 방식: 거래량 상위 100+100개 → fchart 일봉 → 점수 산출

        ScreenResult.market_type: "KOSPI" or "KOSDAQ" (main.py 분봉 타임프레임 결정용)
        """
        logger.info("[스크리너] KIS 국내 스크리닝 시작")
        try:
            # ── DB 우선: 전체 유니버스 (DataSync가 미리 수집) ─────────
            if self._storage:
                kospi_list = await asyncio.to_thread(self._storage.get_all_symbols, "KOSPI")
                kosdaq_list = await asyncio.to_thread(self._storage.get_all_symbols, "KOSDAQ")
                all_universe = (
                    [(c, "KOSPI", n) for c, _, n in kospi_list] +
                    [(c, "KOSDAQ", n) for c, _, n in kosdaq_list]
                )
                if all_universe:
                    logger.info(f"[스크리너] 국내 DB 유니버스: {len(all_universe)}개 (KOSPI+KOSDAQ)")
                    results = []
                    ok, skip = 0, 0
                    for code, market_type, name in all_universe:
                        try:
                            df = await asyncio.to_thread(
                                self._storage.get_ohlcv, code, market_type, "1d", 300
                            )
                            if df is None or len(df) < 20:
                                skip += 1
                                continue
                            score, trend, reasons = self._tech_score(df)
                            if score >= 3:
                                results.append(ScreenResult(
                                    symbol=code, exchange="kis_domestic",
                                    score=score, trend=trend,
                                    market_type=market_type,
                                    reasons=reasons,
                                    name=name,
                                ))
                            ok += 1
                        except Exception as e:
                            logger.debug(f"[스크리너] 국내 DB {code} 오류: {e}")
                    logger.info(
                        f"[스크리너] 국내 DB 완료: 처리={ok} 데이터부족={skip} 통과={len(results)}"
                    )
                    results.sort(key=lambda x: x.score, reverse=True)
                    selected = results[:self.top_n_domestic]
                    logger.info(f"[스크리너] KIS 국내 완료: {len(selected)}개 선별")
                    return selected

            # ── 폴백: 네이버 거래량 순위 + fchart API ───────────────
            logger.info("[스크리너] 국내 DB 없음 → 네이버 거래량 순위 폴백")

            def _fetch_volume_top():
                """네이버 금융 거래량 순위 크롤링. 실패 시 캐시 재사용."""
                from bs4 import BeautifulSoup
                headers = {"User-Agent": "Mozilla/5.0"}
                result = []
                for market_name, sosok in [("KOSPI", 0), ("KOSDAQ", 1)]:
                    page = 1
                    while len([r for r in result if r[1] == market_name]) < 100:
                        url = f"https://finance.naver.com/sise/sise_quant.nhn?sosok={sosok}&page={page}"
                        resp = requests.get(url, headers=headers, timeout=10)
                        resp.encoding = "euc-kr"
                        soup = BeautifulSoup(resp.text, "lxml")
                        rows = soup.select("table.type_2 tr")
                        found = 0
                        for tr in rows:
                            a = tr.select_one("td a[href*=code]")
                            if not a:
                                continue
                            code = a["href"].split("code=")[-1]
                            name = a.text.strip()
                            result.append((code, market_name, name))
                            found += 1
                        if found == 0:
                            break
                        page += 1
                if result:
                    _DOMESTIC_CACHE.parent.mkdir(parents=True, exist_ok=True)
                    _DOMESTIC_CACHE.write_text(json.dumps(result, ensure_ascii=False))
                    logger.info(f"[스크리너] 네이버 거래량 크롤링 성공 ({len(result)}개)")
                    return result
                if _DOMESTIC_CACHE.exists():
                    cached = json.loads(_DOMESTIC_CACHE.read_text())
                    logger.info(f"[스크리너] 크롤링 실패 → 캐시 재사용 ({len(cached)}개)")
                    return cached
                raise RuntimeError("거래량 후보 조회 실패 (캐시도 없음)")

            candidates = await asyncio.to_thread(_fetch_volume_top)
            logger.info(f"[스크리너] 국내 폴백 후보: {len(candidates)}개")

            if self._storage and candidates:
                try:
                    items = [(code, "domestic", name) for code, _, name in candidates]
                    await asyncio.to_thread(self._storage.bulk_upsert_symbol_info, items)
                except Exception as e:
                    logger.warning(f"[스크리너] symbol_info 저장 실패: {e}")

            import xml.etree.ElementTree as ET

            def _fchart_daily(code: str) -> pd.DataFrame:
                resp = requests.get(
                    "https://fchart.stock.naver.com/sise.nhn",
                    params={"symbol": code, "timeframe": "day", "count": 100, "requestType": "0"},
                    headers={"User-Agent": "Mozilla/5.0"},
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
                        rows.append({
                            "open": float(parts[1]), "high": float(parts[2]),
                            "low": float(parts[3]), "close": float(parts[4]),
                            "volume": float(parts[5]),
                        })
                    except ValueError:
                        continue
                if not rows:
                    return pd.DataFrame()
                return pd.DataFrame(rows)

            results = []
            err_count = 0
            skip_count = 0
            for symbol, market_type, name in candidates:
                try:
                    df = await asyncio.to_thread(_fchart_daily, symbol)
                    if df is None or len(df) < 20:
                        skip_count += 1
                        continue
                    score, trend, reasons = self._tech_score(df)
                    if score >= 3:
                        results.append(ScreenResult(
                            symbol=symbol, exchange="kis_domestic",
                            score=score, trend=trend,
                            market_type=market_type,
                            reasons=reasons,
                            name=name,
                        ))
                    await asyncio.sleep(0.05)
                except Exception as e:
                    err_count += 1
                    logger.warning(f"fchart {symbol} 분석 오류: {e}")

            logger.info(
                f"[스크리너] 국내 폴백 완료: "
                f"성공={len(candidates)-err_count-skip_count} "
                f"데이터부족={skip_count} 오류={err_count} 통과={len(results)}"
            )
            results.sort(key=lambda x: x.score, reverse=True)
            selected = results[:self.top_n_domestic]
            logger.info(f"[스크리너] KIS 국내 완료: {len(selected)}개 선별")
            return selected

        except Exception as e:
            logger.error(f"[스크리너] KIS 국내 스크리닝 실패: {e}")
            return []

    # ── KIS 해외 스크리닝 ─────────────────────────────────────────
    async def screen_kis_overseas(self, market: str = "NAS") -> list[ScreenResult]:
        """
        미국 주식 스크리닝

        [DB 보유 시] DataSync가 수집한 NASDAQ 전체 유니버스 (~4,000개) 스크리닝
        [DB 미보유 시] US_UNIVERSE 고정 100종목 → yfinance 폴백
        """
        logger.info(f"[스크리너] 해외({market}) 스크리닝 시작")
        try:
            # ── DB 우선: 전체 NASDAQ 유니버스 ─────────────────────
            if self._storage:
                overseas_list = await asyncio.to_thread(
                    self._storage.get_all_symbols, "overseas"
                )
                if overseas_list:
                    logger.info(f"[스크리너] 해외 DB 유니버스: {len(overseas_list)}개 종목 처리")
                    results = []
                    ok, skip = 0, 0
                    for sym, _, name in overseas_list:
                        try:
                            df = await asyncio.to_thread(
                                self._storage.get_ohlcv, sym, "overseas", "1d", 300
                            )
                            if df is None or len(df) < 20:
                                skip += 1
                                continue
                            score, trend, reasons = self._tech_score(df)
                            if score >= 3:
                                results.append(ScreenResult(
                                    symbol=sym, exchange="kis_overseas",
                                    score=score, trend=trend,
                                    market_type=market,
                                    reasons=reasons,
                                    name=name,
                                ))
                            ok += 1
                        except Exception as e:
                            logger.debug(f"[스크리너] 해외 DB {sym} 오류: {e}")
                    logger.info(
                        f"[스크리너] 해외 DB 완료: 처리={ok} 데이터부족={skip} 통과={len(results)}"
                    )
                    results.sort(key=lambda x: x.score, reverse=True)
                    selected = results[:self.top_n_overseas]
                    logger.info(f"[스크리너] 해외 완료: {len(selected)}개 선별")
                    return selected

            # ── 폴백: US_UNIVERSE 100종목 + yfinance 개별 다운로드 ──
            logger.info("[스크리너] 해외 DB 없음 → US_UNIVERSE 폴백")
            results = []
            for symbol in US_UNIVERSE:
                try:
                    def _single_dl(sym=symbol):
                        import yfinance as _yf
                        t = _yf.Ticker(sym)
                        raw = t.history(period="1y", interval="1d", auto_adjust=True)
                        if raw is None or len(raw) < 20:
                            return None
                        raw = raw.rename(columns={
                            "Open": "open", "High": "high",
                            "Low": "low", "Close": "close", "Volume": "volume",
                        })
                        return raw[["open", "high", "low", "close", "volume"]]

                    df = await asyncio.to_thread(_single_dl)
                    await asyncio.sleep(0.05)
                    if df is None or len(df) < 20:
                        continue
                    score, trend, reasons = self._tech_score(df)
                    if score >= 3:
                        results.append(ScreenResult(
                            symbol=symbol, exchange="kis_overseas",
                            score=score, trend=trend,
                            market_type=market,
                            reasons=reasons,
                        ))
                except Exception as e:
                    logger.warning(f"[스크리너] 해외 {symbol} 분석 오류: {e}")

            results.sort(key=lambda x: x.score, reverse=True)
            selected = results[:self.top_n_overseas]
            logger.info(f"[스크리너] 해외 완료: {len(selected)}개 선별")
            return selected

        except Exception as e:
            logger.error(f"[스크리너] 해외 스크리닝 실패: {e}")
            return []
