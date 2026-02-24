import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

import requests

logger = logging.getLogger(__name__)

KIS_REAL_BASE = "https://openapi.koreainvestment.com:9443"
KIS_PAPER_BASE = "https://openapivts.koreainvestment.com:29443"
KIS_WS_REAL = "ws://ops.koreainvestment.com:21000"
KIS_WS_PAPER = "ws://ops.koreainvestment.com:31000"


class KISClient:
    def __init__(self, app_key: str, app_secret: str, account_no: str,
                 account_product_code: str = "01", hts_id: str = "",
                 is_paper_trading: bool = True):
        self.app_key = app_key
        self.app_secret = app_secret
        self.account_no = account_no
        self.account_product_code = account_product_code
        self.hts_id = hts_id
        self.is_paper = is_paper_trading
        self.base_url = KIS_PAPER_BASE if is_paper_trading else KIS_REAL_BASE
        self._access_token: Optional[str] = None
        self._token_expires: Optional[datetime] = None

    # ── OAuth2 인증 ──────────────────────────────────────────────
    def _ensure_token(self):
        if self._access_token and self._token_expires and datetime.now() < self._token_expires:
            return
        url = f"{self.base_url}/oauth2/tokenP"
        body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }
        resp = requests.post(url, json=body, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        self._token_expires = datetime.now() + timedelta(hours=23)
        logger.info("KIS OAuth2 token refreshed")

    def _get_hashkey(self, body: dict) -> str:
        url = f"{self.base_url}/uapi/hashkey"
        headers = {"appkey": self.app_key, "appsecret": self.app_secret, "Content-Type": "application/json"}
        resp = requests.post(url, headers=headers, json=body, timeout=10)
        resp.raise_for_status()
        return resp.json()["HASH"]

    def _headers(self, tr_id: str, hashkey: str = None) -> dict:
        self._ensure_token()
        h = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {self._access_token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }
        if hashkey:
            h["hashkey"] = hashkey
        return h

    # ── 국내 주식 ────────────────────────────────────────────────
    def get_domestic_price(self, symbol: str) -> dict:
        """국내 현재가 조회"""
        self._ensure_token()
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol}
        resp = requests.get(url, headers=self._headers("FHKST01010100"), params=params, timeout=10)
        resp.raise_for_status()
        return resp.json().get("output", {})

    def get_domestic_daily_chart(self, symbol: str, count: int = 200) -> list[dict]:
        """국내 일봉 조회"""
        self._ensure_token()
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
        today = datetime.now().strftime("%Y%m%d")
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": symbol,
            "FID_INPUT_DATE_1": "19800101",
            "FID_INPUT_DATE_2": today,
            "FID_PERIOD_DIV_CODE": "D",
            "FID_ORG_ADJ_PRC": "0",
        }
        resp = requests.get(url, headers=self._headers("FHKST03010100"), params=params, timeout=10)
        resp.raise_for_status()
        return resp.json().get("output2", [])

    def place_domestic_order(self, symbol: str, side: str, qty: int,
                              price: int = 0, order_type: str = "01") -> dict:
        """
        국내 주식 주문
        side: 'buy' | 'sell'
        order_type: '01'=시장가, '00'=지정가
        """
        if side == "buy":
            tr_id = "TTTC0802U" if not self.is_paper else "VTTC0802U"
        else:
            tr_id = "TTTC0801U" if not self.is_paper else "VTTC0801U"
        body = {
            "CANO": self.account_no,
            "ACNT_PRDT_CD": self.account_product_code,
            "PDNO": symbol,
            "ORD_DVSN": order_type,
            "ORD_QTY": str(qty),
            "ORD_UNPR": str(price),
        }
        hashkey = self._get_hashkey(body)
        resp = requests.post(
            f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash",
            headers=self._headers(tr_id, hashkey),
            json=body,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def get_domestic_balance(self) -> dict:
        """국내 계좌 잔고 조회"""
        self._ensure_token()
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        tr_id = "TTTC8434R" if not self.is_paper else "VTTC8434R"
        params = {
            "CANO": self.account_no,
            "ACNT_PRDT_CD": self.account_product_code,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "01",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        resp = requests.get(url, headers=self._headers(tr_id), params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    # ── 해외 주식 ────────────────────────────────────────────────
    def get_overseas_price(self, symbol: str, market: str = "NAS") -> dict:
        """해외 현재가 조회"""
        self._ensure_token()
        url = f"{self.base_url}/uapi/overseas-price/v1/quotations/price"
        params = {"AUTH": "", "EXCD": market, "SYMB": symbol}
        resp = requests.get(url, headers=self._headers("HHDFS00000300"), params=params, timeout=10)
        resp.raise_for_status()
        return resp.json().get("output", {})

    def get_overseas_daily_chart(self, symbol: str, market: str = "NAS", count: int = 200) -> list[dict]:
        """해외 일봉 조회
        
        BYMD: KST 기준이 아닌 미국 동부 시간 기준 날짜 사용
        KST는 미국 동부보다 14시간 앞서므로, datetime.now() - 14h 로 미국 날짜 계산
        (예: 02:05 KST Feb 25 → 12:05 Feb 24 US → BYMD=20260224)
        """
        self._ensure_token()
        url = f"{self.base_url}/uapi/overseas-price/v1/quotations/dailychartprice"
        from datetime import timedelta
        us_date = (datetime.now() - timedelta(hours=14)).strftime("%Y%m%d")
        params = {
            "AUTH": "",
            "EXCD": market,
            "SYMB": symbol,
            "GUBN": "0",
            "BYMD": us_date,
            "MODP": "1",
        }
        resp = requests.get(url, headers=self._headers("HHDFS76240000"), params=params, timeout=10)
        resp.raise_for_status()
        return resp.json().get("output2", [])

    def place_overseas_order(self, symbol: str, market: str, side: str,
                              qty: int, price: float = 0) -> dict:
        """
        해외 주식 주문
        side: 'buy' | 'sell'
        market: 'NAS'/'NASD'(NASDAQ), 'NYS'/'NYSE', 'AMS'/'AMEX' 등
                조회용(NAS) → 주문용(NASD) 자동 변환
        price: 0이면 시장가, > 0이면 지정가 (소수점 2자리 자동 반올림)
        """
        self._ensure_token()
        # 조회용 코드 → 주문용 코드 매핑
        _ORDER_MARKET_MAP = {"NAS": "NASD", "NYS": "NYSE", "AMS": "AMEX", "HKS": "SEHK"}
        order_market = _ORDER_MARKET_MAP.get(market, market)
        if side == "buy":
            tr_id = "TTTT1002U" if not self.is_paper else "VTTT1002U"
        else:
            tr_id = "TTTT1006U" if not self.is_paper else "VTTT1001U"
        # KIS 해외주식: 1$ 이상은 소수점 2자리까지만 허용
        formatted_price = f"{round(price, 2):.2f}" if price > 0 else "0"
        body = {
            "CANO": self.account_no,
            "ACNT_PRDT_CD": self.account_product_code,
            "OVRS_EXCG_CD": order_market,
            "PDNO": symbol,
            "ORD_DVSN": "00" if price > 0 else "01",
            "ORD_QTY": str(qty),
            "OVRS_ORD_UNPR": formatted_price,
            "ORD_SVR_DVSN_CD": "0",
        }
        hashkey = self._get_hashkey(body)
        resp = requests.post(
            f"{self.base_url}/uapi/overseas-stock/v1/trading/order",
            headers=self._headers(tr_id, hashkey),
            json=body,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def get_overseas_balance(self) -> dict:
        """해외 계좌 잔고 조회"""
        self._ensure_token()
        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-balance"
        tr_id = "TTTS3012R" if not self.is_paper else "VTTS3012R"
        params = {
            "CANO": self.account_no,
            "ACNT_PRDT_CD": self.account_product_code,
            "OVRS_EXCG_CD": "NAS",
            "TR_CRCY_CD": "USD",
            "CTX_AREA_FK200": "",
            "CTX_AREA_NK200": "",
        }
        resp = requests.get(url, headers=self._headers(tr_id), params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def get_domestic_volume_ranking(self, market: str = "J", top_n: int = 100) -> list[dict]:
        """
        국내 거래량 순위 조회
        market: J=KOSPI, Q=KOSDAQ
        Returns: [{"mksc_shrn_iscd": "005930", "hts_kor_isnm": "삼성전자",
                   "stck_prpr": "75000", "acml_vol": "15000000", "prdy_vol": "8000000", ...}]
        """
        self._ensure_token()
        url = f"{self.base_url}/uapi/domestic-stock/v1/ranking/volume"
        params = {
            "FID_COND_MKT_DIV_CODE": market,
            "FID_COND_SCR_DIV_CODE": "20171",
            "FID_INPUT_ISCD": "0000",
            "FID_DIV_CLS_CODE": "0",
            "FID_BLNG_CLS_CODE": "0",
            "FID_TRGT_CLS_CODE": "111111111",
            "FID_TRGT_EXLS_CLS_CODE": "0000000000",
            "FID_INPUT_PRICE_1": "",
            "FID_INPUT_PRICE_2": "",
            "FID_VOL_CNT": "",
            "FID_INPUT_DATE_1": "",
        }
        resp = requests.get(
            url,
            headers=self._headers("FHPST01710000"),
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("output", [])[:top_n]

    def get_domestic_minute_chart(self, symbol: str, period: int = 60,
                                   count: int = 120) -> "pd.DataFrame | None":
        """
        국내 주식 분봉 차트 조회.

        KIS API는 1분봉 30개씩 반환 → resample로 period분봉 집계.
        Args:
            symbol: 종목코드 (예: "005930")
            period: 집계 단위 분 (30 or 60)
            count:  최종 반환할 분봉 개수 (30개씩 배치 수집)
        """
        import pandas as pd
        self._ensure_token()
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
        # FID_COND_MRKT_DIV_CODE: 시장구분 (J=KOSPI, Q=KOSDAQ) → 공통 J 사용
        # 30개씩 역방향 수집
        frames = []
        ref_time = datetime.now()
        collected = 0
        max_batches = (count // 30) + 2  # 여유분 포함

        for _ in range(max_batches):
            if collected >= count * 2:  # 1분봉 기준 충분히 수집
                break
            time_str = ref_time.strftime("%H%M%S")
            params = {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": symbol,
                "FID_INPUT_HOUR_1": time_str,
                "FID_PW_DATA_INCU_YN": "Y",
                "FID_ETC_CLS_CODE": "",
            }
            try:
                resp = requests.get(url, headers=self._headers("FHKST03010200"),
                                    params=params, timeout=10)
                resp.raise_for_status()
                output = resp.json().get("output2", [])
                if not output:
                    break
                frames.extend(output)
                collected += len(output)
                # 마지막 캔들 시간 → 다음 배치 기준
                last_time = output[-1].get("stck_cntg_hour", time_str)
                try:
                    ref_time = datetime.strptime(
                        ref_time.strftime("%Y%m%d") + last_time, "%Y%m%d%H%M%S"
                    ) - timedelta(minutes=1)
                except ValueError:
                    break
                time.sleep(0.05)
            except Exception as e:
                logger.debug(f"KIS 국내 분봉 배치 오류 {symbol}: {e}")
                break

        if not frames:
            return None

        try:
            df = pd.DataFrame(frames)
            # 컬럼 매핑 (KIS 국내 분봉 output2)
            col_map = {
                "stck_bsop_date": "date",
                "stck_cntg_hour": "time",
                "stck_oprc": "open",
                "stck_hgpr": "high",
                "stck_lwpr": "low",
                "stck_prpr": "close",
                "cntg_vol": "volume",
            }
            df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
            if "date" not in df.columns or "time" not in df.columns:
                return None
            df["datetime"] = pd.to_datetime(df["date"] + df["time"], format="%Y%m%d%H%M%S", errors="coerce")
            for col in ["open", "high", "low", "close", "volume"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna(subset=["datetime", "close"]).sort_values("datetime").reset_index(drop=True)

            if period > 1:
                df = df.set_index("datetime")
                rule = f"{period}min"
                df = df.resample(rule).agg(
                    open=("open", "first"),
                    high=("high", "max"),
                    low=("low", "min"),
                    close=("close", "last"),
                    volume=("volume", "sum"),
                ).dropna(subset=["close"]).reset_index()

            return df[["datetime", "open", "high", "low", "close", "volume"]].tail(count).reset_index(drop=True)
        except Exception as e:
            logger.error(f"KIS 국내 분봉 파싱 오류 {symbol}: {e}")
            return None

    def get_overseas_minute_chart(self, symbol: str, market: str = "NAS",
                                   nmin: int = 15, count: int = 100) -> "pd.DataFrame | None":
        """
        해외 주식 분봉 차트 조회.

        KIS API: HHDFS76200200
        Args:
            symbol: 종목코드 (예: "AAPL")
            market: 거래소 코드 (NAS, NYS 등)
            nmin:   분봉 단위 (1/5/10/15 지원)
            count:  반환할 캔들 수
        """
        import pandas as pd
        self._ensure_token()
        url = f"{self.base_url}/uapi/overseas-price/v1/quotations/inquire-time-itemchartprice"
        params = {
            "AUTH": "",
            "EXCD": market,
            "SYMB": symbol,
            "NMIN": str(nmin),
            "PINC": "1",
            "NEXT": "",
            "NREC": str(min(count, 120)),
            "FILL": "",
            "KEYB": "",
        }
        try:
            time.sleep(0.05)  # 20 TPS 준수
            resp = requests.get(url, headers=self._headers("HHDFS76200200"),
                                params=params, timeout=10)
            resp.raise_for_status()
            output = resp.json().get("output2", [])
            if not output:
                return None

            df = pd.DataFrame(output)
            # KIS 해외 분봉 컬럼 매핑
            col_map = {
                "kymd": "date",
                "khms": "time",
                "open": "open",
                "high": "high",
                "low": "low",
                "last": "close",
                "evol": "volume",
            }
            df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
            # 대안 컬럼명
            if "date" not in df.columns and "stck_bsop_date" in df.columns:
                df = df.rename(columns={"stck_bsop_date": "date", "stck_cntg_hour": "time"})

            if "date" in df.columns and "time" in df.columns:
                df["datetime"] = pd.to_datetime(df["date"] + df["time"], format="%Y%m%d%H%M%S", errors="coerce")
            elif "kymd" in df.columns:
                df["datetime"] = pd.to_datetime(df["kymd"], format="%Y%m%d", errors="coerce")
            else:
                return None

            for col in ["open", "high", "low", "close", "volume"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna(subset=["datetime", "close"]).sort_values("datetime").reset_index(drop=True)
            return df[["datetime", "open", "high", "low", "close", "volume"]].tail(count).reset_index(drop=True)
        except Exception as e:
            logger.error(f"KIS 해외 분봉 조회 실패 {symbol}: {e}")
            return None
