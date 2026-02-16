# 🤖 AutoTrade Bot

> 업비트(코인) + 한국투자증권(국내/해외 주식) 자동매매봇

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/License-MIT-blue)](LICENSE)

---

## 📌 개요

한국 트레이딩봇 커뮤니티(TigerBot, DeepDive_KR 등) 사례를 참고하여 구현한
**텔레그램 알림 + 5가지 전략 + Kelly Criterion 리스크 관리**를 갖춘 자동매매봇.

| 항목 | 내용 |
|------|------|
| **거래소** | 업비트 (암호화폐) · 한국투자증권 (국내/해외 주식) |
| **전략** | 추세추종 · RSI 역추세 · 볼린저밴드 · SMC · 터틀 |
| **리스크** | Kelly Criterion 포지션 사이징 · 서킷브레이커 |
| **알림** | 텔레그램 봇 (매수/매도/일일 리포트) |
| **대시보드** | FastAPI + Chart.js 웹 UI (`http://localhost:8080`) |
| **언어** | Python 3.11+ |

---

## 🗂️ 프로젝트 구조

```
money/
├── config.yaml                  # API 키 + 전략 설정 (gitignore)
├── config.example.yaml          # 설정 템플릿 (커밋용)
├── requirements.txt
├── main.py                      # 봇 진입점 (봇 + 대시보드 동시 실행)
├── bot/
│   ├── config.py                # pyyaml 기반 설정 로더
│   ├── exchange/
│   │   ├── upbit.py             # Upbit REST + WebSocket 클라이언트
│   │   └── kis.py               # KIS OAuth2 + REST 클라이언트
│   ├── strategy/
│   │   ├── base.py              # Strategy ABC + Signal Enum
│   │   ├── trend_following.py   # 추세추종: MA 크로스오버 + 신고가 돌파
│   │   ├── rsi_reversal.py      # RSI 역추세: RSI(14) 과매수/과매도
│   │   ├── bollinger_breakout.py# 볼린저밴드: 브레이크아웃 + 평균회귀
│   │   ├── smc.py               # SMC: 오더블록 + FVG + 유동성 스윕
│   │   └── turtle.py            # 터틀: 도니안채널 + ATR 사이징 + 피라미딩
│   ├── indicators.py            # 기술적 지표 (pandas-ta)
│   ├── risk.py                  # Kelly Criterion + ATR 손절/익절
│   ├── portfolio.py             # 포지션 상태 추적 + 손익 계산
│   ├── notification.py          # 텔레그램 봇 알림 + 명령어
│   ├── scheduler.py             # APScheduler + 장 운영시간 관리
│   └── storage.py               # SQLite 거래 이력
├── dashboard/
│   ├── app.py                   # FastAPI 서버 + WebSocket
│   ├── static/
│   │   ├── css/style.css        # 다크 테마 스타일
│   │   └── js/dashboard.js      # Chart.js 실시간 업데이트
│   └── templates/
│       └── index.html           # 메인 대시보드 HTML
├── backtest/
│   └── backtester.py            # 백테스팅 엔진 + CLI
└── logs/
```

---

## ⚡ 빠른 시작

### 1. 의존성 설치

```bash
pip install -r requirements.txt
```

### 2. 설정 파일 작성

```bash
cp config.example.yaml config.yaml
```

`config.yaml`을 편집하여 API 키를 입력합니다:

```yaml
upbit:
  access_key: "YOUR_UPBIT_ACCESS_KEY"
  secret_key: "YOUR_UPBIT_SECRET_KEY"

kis:
  app_key: "YOUR_KIS_APP_KEY"
  app_secret: "YOUR_KIS_APP_SECRET"
  account_no: "12345678"
  is_paper_trading: true   # ← 반드시 true로 시작 (모의투자)

telegram:
  bot_token: "YOUR_BOT_TOKEN"
  chat_id: "YOUR_CHAT_ID"
```

### 3. 봇 실행

```bash
python main.py
```

봇과 대시보드가 동시에 실행됩니다.
대시보드: **http://localhost:8080**

### 4. 백테스트

```bash
# 샘플 데이터로 전략 검증
python -m backtest.backtester --strategy trend_following --sample --days 500

# 전략 선택: trend_following / rsi_reversal / bollinger_breakout / smc / turtle
python -m backtest.backtester --strategy turtle --sample --days 365 --capital 10000000
```

---

## ⚙️ 설정 (config.yaml)

```yaml
strategy:
  upbit:
    enabled: true
    symbols: ["KRW-BTC", "KRW-ETH", "KRW-SOL"]
    active_strategies: ["trend_following", "rsi_reversal", "bollinger_breakout"]
    candle_interval: "15"       # 분봉 (1/3/5/15/60/240)

  kis_domestic:
    enabled: true
    symbols: ["005930", "000660"]   # 삼성전자, SK하이닉스
    active_strategies: ["trend_following", "rsi_reversal"]

  kis_overseas:
    enabled: true
    market: "NAS"                   # NAS=나스닥, NYS=뉴욕, AMS=아멕스
    symbols: ["AAPL", "NVDA", "TSLA"]
    active_strategies: ["trend_following"]

risk:
  max_position_ratio: 0.06     # 종목당 최대 6% (Kelly Criterion)
  max_daily_loss_ratio: 0.02   # 일일 최대 손실 2% (서킷브레이커)
  stop_loss_ratio: 0.03        # 손절 3%
  take_profit_ratio: 0.06      # 익절 6%
  max_concurrent_positions: 5  # 동시 보유 최대 5종목

indicators:
  rsi_period: 14
  rsi_oversold: 30
  rsi_overbought: 70
  ma_short: 20
  ma_long: 200
  bollinger_period: 20
  bollinger_std: 2.0
```

---

## 📈 전략 상세

### 1. 추세추종 (Trend Following)

MA 크로스오버와 52주 신고가를 결합한 전략.

| 신호 | 조건 |
|------|------|
| **매수** | MA20 > MA200 (골든크로스) + 전일비 +1% 이상 + 거래량 평균 150%↑ |
| **매수** | 52주 신고가 돌파 (DeepDive_KR 방식) |
| **매도** | MA20 < MA200 (데드크로스) |

### 2. RSI 역추세 (RSI Reversal)

RSI(14) 과매수/과매도 구간을 이용한 역추세 전략.

| 신호 | 조건 |
|------|------|
| **매수** | RSI < 30 탈출 (과매도 → 반등) + MA200 위 |
| **매도** | RSI > 70 (과매수 진입) |

### 3. 볼린저밴드 (Bollinger Breakout)

상단 브레이크아웃과 하단 평균회귀를 모두 지원.

| 신호 | 조건 |
|------|------|
| **매수 (브레이크아웃)** | 볼린저 상단 돌파 + 거래량 급증 |
| **매수 (평균회귀)** | 볼린저 하단 이탈 후 반등 |
| **매도** | 볼린저 중심선(MA20) 도달 |

### 4. SMC (Smart Money Concepts)

기관 투자자(스마트머니)의 발자국을 추적.

```
Order Block (OB)
  └─ 불리시 OB: 하락 후 강한 상승 전환점의 마지막 하락 캔들
  └─ 베어리시 OB: 상승 후 강한 하락 전환점의 마지막 상승 캔들

Fair Value Gap (FVG)
  └─ 3개 캔들 기준 갭 구간 → 가격이 채우러 돌아올 때 진입

Break of Structure (BoS) / CHoCH
  └─ BoS: 추세 지속 확인 / CHoCH: 추세 전환 신호

Liquidity Sweep
  └─ 이전 고점/저점 일시 돌파 후 반전 (스톱헌팅 후 실방향)
```

| 신호 | 조건 |
|------|------|
| **매수** | 불리시 OB 터치 + BoS 확인 OR FVG 채움 + CHoCH 상승 |
| **매수** | 저점 유동성 스윕 후 반전 |
| **매도** | 베어리시 OB 터치 OR 고점 유동성 스윕 후 반전 |

### 5. 터틀 트레이딩 (Turtle Trading)

Richard Dennis & William Eckhardt의 클래식 추세추종 시스템 (1983).

| 항목 | System 1 (단기) | System 2 (장기) |
|------|----------------|----------------|
| **진입** | 20일 최고가 돌파 | 55일 최고가 돌파 |
| **청산** | 10일 최저가 이탈 | 20일 최저가 이탈 |
| **필터** | 직전 신호 수익 시 스킵 | 없음 |

**Unit 시스템 (ATR 기반 포지션 사이징)**
```
Unit 수량 = (자본 × 1%) / (ATR × 가격)
피라미딩: 진입 후 0.5 ATR 상승마다 1 Unit 추가 (최대 4 Units)
손절: 진입가 대비 2 ATR 이탈 시 전체 청산
```

---

## 🛡️ 리스크 관리

### Kelly Criterion (켈리 공식)

```
f* = (b × p - q) / b
  b = 수익비 (익절/손절)
  p = 승률
  q = 1 - p

Half-Kelly 적용 (보수적 운용) + 종목당 최대 6% 캡
```

### 서킷브레이커

- 일일 손실이 전체 자산의 **2%** 도달 시 당일 거래 자동 중단
- 텔레그램으로 즉시 알림 발송
- `/resume` 명령으로 재개 가능

---

## 📊 대시보드

`http://localhost:8080`에서 실시간 모니터링.

```
┌─────────────────────────────────────────────────────────────┐
│  AutoTrade Bot Dashboard              [RUNNING] 🟢  [STOP]  │
├──────────────┬──────────────┬──────────────┬────────────────┤
│ 총 자산      │ 오늘 손익    │ 승률         │ 활성 포지션    │
│ ₩15,234,500  │ +₩67,000     │ 75% (3/4)    │ 3종목          │
├──────────────┴──────────────┴──────────────┴────────────────┤
│                     누적 손익 차트 (Chart.js)                │
├─────────────────────────────────────────────────────────────┤
│ 현재 포지션  종목 | 거래소 | 전략 | 진입가 | 손익 | 비중    │
├─────────────────────────────────────────────────────────────┤
│ 최근 거래 이력 (최근 20건)                                   │
├─────────────────────────────────────────────────────────────┤
│ 전략별 성과  전략 | 거래수 | 승률 | 평균수익 | 누적손익     │
└─────────────────────────────────────────────────────────────┘
```

**WebSocket 실시간 업데이트** (10초 주기)

---

## 📱 텔레그램 알림

### 매수 신호 예시
```
📈 [매수 신호] KRW-BTC
거래소: upbit
전략: 추세추종 (MA골든크로스)
현재가: ₩142.5M
목표가: ₩150.8M (+5.8%)
손절가: ₩138.2M (-3.0%)
포지션: 잔고의 5.2%
```

### 일일 리포트 예시
```
📊 [일일 리포트] 2026-02-17
업비트: +2.3% | 손익: +₩46,000
KIS 국내: +1.1% | 손익: +₩33,000
KIS 해외: -0.5% | 손익: -₩12,000
총 손익: +₩67,000 | 승률: 3/4 (75%)
```

### 지원 명령어

| 명령어 | 설명 |
|--------|------|
| `/status` | 봇 상태 확인 |
| `/positions` | 현재 포지션 조회 |
| `/pnl` | 손익 현황 |
| `/stop` | 봇 즉시 중지 |
| `/resume` | 봇 재개 |

---

## 🕐 스케줄 운영시간

| 거래소 | 운영 시간 | 비고 |
|--------|-----------|------|
| **업비트** | 24/7 (매 1분) | 암호화폐 상시 운영 |
| **KIS 국내** | 평일 09:00~15:20 KST | 장 마감 10분 전 종료 |
| **KIS 해외** | 평일 22:30~05:00 KST | 미국 정규장 (서머타임 기준) |
| **일일 리포트** | 매일 16:00 KST | 텔레그램 자동 발송 |

---

## 🔌 API 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| `GET` | `/` | 대시보드 메인 |
| `GET` | `/api/summary` | 총 자산 / 오늘 손익 / 승률 |
| `GET` | `/api/positions` | 현재 포지션 목록 |
| `GET` | `/api/trades` | 최근 거래 이력 |
| `GET` | `/api/pnl-chart` | 누적 손익 차트 데이터 |
| `GET` | `/api/strategy-stats` | 전략별 성과 통계 |
| `POST` | `/api/bot/stop` | 봇 중지 |
| `POST` | `/api/bot/resume` | 봇 재개 |
| `WS` | `/ws` | 실시간 포지션/가격 업데이트 |

---

## 📦 의존성

```
pyupbit              # 업비트 공식 Python 래퍼
requests             # HTTP REST API
websockets           # WebSocket 클라이언트
pandas               # 데이터프레임 처리
numpy                # 수치 계산
pandas-ta            # 기술적 지표 (RSI, MA, BB, MACD, ATR, 도니안채널)
python-telegram-bot  # 텔레그램 봇
apscheduler          # 스케줄러
pyyaml               # config.yaml 로딩
PyJWT                # JWT 토큰 생성 (업비트 인증)
cryptography         # 해시키 생성 (KIS 인증)
fastapi              # 대시보드 웹 서버
uvicorn              # FastAPI ASGI 서버
jinja2               # HTML 템플릿 엔진
```

---

## ✅ 검증 순서

1. **KIS 모의투자 테스트** — `is_paper_trading: true`로 실제 자금 위험 없이 테스트
2. **업비트 잔고 조회** — API 연결 및 인증 확인
3. **텔레그램 알림** — `/status` 명령 응답 확인
4. **백테스트** — 전략별 과거 데이터 성능 검증
5. **대시보드** — `http://localhost:8080` 브라우저 확인
6. **소액 실투자** — 모든 검증 후 `is_paper_trading: false` 전환

---

## ⚠️ 주의사항

- `config.yaml`은 `.gitignore`에 포함 — **절대 커밋 금지**
- KIS는 반드시 `is_paper_trading: true`로 시작
- 텔레그램 `/stop` 명령으로 언제든지 봇 중지 가능
- 투자에는 항상 원금 손실 위험이 있습니다

---

## 📄 라이선스

MIT License
