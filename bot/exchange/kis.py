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
        """해외 일봉 조회"""
        self._ensure_token()
        url = f"{self.base_url}/uapi/overseas-price/v1/quotations/dailychartprice"
        today = datetime.now().strftime("%Y%m%d")
        params = {
            "AUTH": "",
            "EXCD": market,
            "SYMB": symbol,
            "GUBN": "0",
            "BYMD": today,
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
        """
        if side == "buy":
            tr_id = "TTTT1002U" if not self.is_paper else "VTTT1002U"
        else:
            tr_id = "TTTT1006U" if not self.is_paper else "VTTT1001U"
        body = {
            "CANO": self.account_no,
            "ACNT_PRDT_CD": self.account_product_code,
            "OVRS_EXCG_CD": market,
            "PDNO": symbol,
            "ORD_DVSN": "00" if price > 0 else "01",
            "ORD_QTY": str(qty),
            "OVRS_ORD_UNPR": str(price),
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
