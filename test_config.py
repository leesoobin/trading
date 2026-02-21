"""
config.yaml API 연결 테스트 스크립트
- Upbit: 잔고 조회 + BTC 캔들 조회
- KIS: OAuth 토큰 발급 + 삼성전자 현재가 조회
- Telegram: 테스트 메시지 발송
"""
import sys
import yaml
import requests
import json
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.yaml"


def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def test_upbit(cfg):
    print("\n" + "="*50)
    print("📊 [1] Upbit API 테스트")
    print("="*50)
    try:
        import uuid, hashlib, urllib.parse, jwt
        access_key = cfg["upbit"]["access_key"]
        secret_key = cfg["upbit"]["secret_key"]

        # 1-1. 공개 API: BTC 캔들 (인증 불필요)
        resp = requests.get(
            "https://api.upbit.com/v1/candles/minutes/15",
            params={"market": "KRW-BTC", "count": 3},
            timeout=10
        )
        resp.raise_for_status()
        candles = resp.json()
        print(f"  ✅ 캔들 조회 OK  → BTC 현재가: ₩{candles[0]['trade_price']:,.0f}")

        # 1-2. 인증 API: 잔고 조회
        payload = {"access_key": access_key, "nonce": str(uuid.uuid4())}
        token = jwt.encode(payload, secret_key, algorithm="HS256")
        headers = {"Authorization": f"Bearer {token}"}
        resp2 = requests.get("https://api.upbit.com/v1/accounts", headers=headers, timeout=10)
        resp2.raise_for_status()
        accounts = resp2.json()
        krw = next((a for a in accounts if a["currency"] == "KRW"), None)
        if krw:
            print(f"  ✅ 잔고 조회 OK  → KRW 잔고: ₩{float(krw['balance']):,.0f}")
        else:
            print(f"  ✅ 잔고 조회 OK  → 보유 자산 {len(accounts)}개")

    except Exception as e:
        print(f"  ❌ Upbit 오류: {e}")


def test_kis(cfg):
    print("\n" + "="*50)
    print("📈 [2] KIS (한국투자증권) API 테스트")
    print("="*50)
    try:
        app_key = cfg["kis"]["app_key"]
        app_secret = cfg["kis"]["app_secret"]
        is_paper = cfg["kis"].get("is_paper_trading", True)
        base_url = "https://openapivts.koreainvestment.com:29443" if is_paper else "https://openapi.koreainvestment.com:9443"
        mode = "모의투자" if is_paper else "실전투자"

        # 2-1. OAuth 토큰 발급
        resp = requests.post(
            f"{base_url}/oauth2/tokenP",
            json={"grant_type": "client_credentials", "appkey": app_key, "appsecret": app_secret},
            timeout=15
        )
        resp.raise_for_status()
        token_data = resp.json()
        access_token = token_data.get("access_token", "")
        if access_token:
            print(f"  ✅ OAuth 토큰 발급 OK  ({mode} 모드)")
            print(f"     만료: {token_data.get('access_token_token_expired', 'N/A')}")
        else:
            print(f"  ⚠️  토큰 응답 이상: {token_data}")
            return

        # 2-2. 삼성전자 현재가 조회
        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {access_token}",
            "appkey": app_key,
            "appsecret": app_secret,
            "tr_id": "FHKST01010100",
            "custtype": "P",
        }
        resp2 = requests.get(
            f"{base_url}/uapi/domestic-stock/v1/quotations/inquire-price",
            headers=headers,
            params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": "005930"},
            timeout=10
        )
        resp2.raise_for_status()
        price_data = resp2.json().get("output", {})
        if price_data:
            print(f"  ✅ 삼성전자 현재가: ₩{int(price_data.get('stck_prpr', 0)):,.0f}")
        else:
            print(f"  ⚠️  현재가 조회 결과 없음 (응답: {resp2.json().get('msg1', '')})")

    except requests.exceptions.HTTPError as e:
        print(f"  ❌ KIS HTTP 오류: {e.response.status_code} - {e.response.text[:200]}")
    except Exception as e:
        print(f"  ❌ KIS 오류: {e}")


def test_telegram(cfg):
    print("\n" + "="*50)
    print("📱 [3] Telegram Bot 테스트")
    print("="*50)
    try:
        bot_token = cfg["telegram"]["bot_token"]
        chat_id = cfg["telegram"]["chat_id"]

        # 3-1. 봇 정보 확인
        resp = requests.get(
            f"https://api.telegram.org/bot{bot_token}/getMe",
            timeout=10
        )
        resp.raise_for_status()
        bot_info = resp.json().get("result", {})
        print(f"  ✅ 봇 연결 OK  → @{bot_info.get('username', 'N/A')}")

        # 3-2. 테스트 메시지 발송
        msg = "🤖 AutoTrade Bot config 테스트 메시지\n✅ 연결 성공!"
        resp2 = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": msg},
            timeout=10
        )
        resp2.raise_for_status()
        result = resp2.json()
        if result.get("ok"):
            print(f"  ✅ 메시지 발송 OK  → chat_id: {chat_id}")
        else:
            print(f"  ⚠️  발송 실패: {result}")

    except Exception as e:
        print(f"  ❌ Telegram 오류: {e}")


def main():
    print("🔧 config.yaml API 연결 테스트 시작")
    cfg = load_config()

    test_upbit(cfg)
    test_kis(cfg)
    test_telegram(cfg)

    print("\n" + "="*50)
    print("✅ 테스트 완료")
    print("="*50)


if __name__ == "__main__":
    main()
