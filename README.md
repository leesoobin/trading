# 🤖 AutoTrade Bot

> 업비트(코인) + 한국투자증권(국내/해외 주식) 자동매매봇

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/License-MIT-blue)](LICENSE)

---

## 📌 개요

| 항목 | 내용 |
|------|------|
| **거래소** | 업비트 (암호화폐) · 한국투자증권 (국내/해외 주식) |
| **활성 전략** | 터틀 트레이딩 · 추세추종 MA크로스 (코인/국내/해외 공통) |
| **종목 발굴** | 배치 스크리닝 (일봉 기술점수) → 60초마다 신호 체크 |
| **리스크** | Kelly Criterion 포지션 사이징 · 서킷브레이커 |
| **알림** | 텔레그램 봇 (매수/매도/일일 리포트/명령 수신) |
| **대시보드** | FastAPI + Chart.js 웹 UI (`http://localhost:8080`) |
| **운용 자본** | 업비트 100만원 + KIS 100만원 = 총 200만원 |
| **언어** | Python 3.11+ |

---

## 🗂️ 프로젝트 구조

```
money/
├── config.yaml                  # API 키 + 전략 설정 (gitignore — 절대 커밋 금지)
├── main.py                      # 봇 진입점 (봇 + 대시보드 동시 실행)
├── bot.lock                     # 중복 실행 방지 락 파일 (자동 생성/삭제)
├── trades.db                    # 거래 이력 SQLite
│
├── bot/
│   ├── config.py                # pyyaml 기반 설정 로더
│   ├── exchange/
│   │   ├── upbit.py             # Upbit REST 클라이언트 (분봉/일봉/잔고/주문)
│   │   └── kis.py               # KIS OAuth2 + REST 클라이언트
│   ├── strategy/
│   │   ├── base.py              # Strategy ABC + Signal Enum
│   │   ├── turtle.py            # 터틀: 도니안채널 + ATR 사이징 + 피라미딩 ✅ 활성
│   │   ├── trend_following.py   # 추세추종: MA 크로스오버 + 신고가 돌파 ✅ 활성
│   │   ├── bollinger_breakout.py# 볼린저밴드: 상단 브레이크아웃 ⏸ 비활성
│   │   ├── mtf_structure.py     # MTF 구조 매핑 (HTF 추세 + LTF BOS/ChoCh) ⏸ 비활성
│   │   └── ma_pullback.py       # 이평선 눌림목 ⏸ 비활성
│   ├── screener.py              # 배치 스크리닝 엔진 (일봉 기술점수)
│   ├── risk.py                  # Kelly Criterion + 손절/익절 계산
│   ├── portfolio.py             # 포지션 상태 추적 (메모리)
│   ├── notification.py          # 텔레그램 알림 + 명령어 수신
│   ├── scheduler.py             # APScheduler + 장 운영시간 관리
│   └── storage.py               # SQLite 거래 이력 저장/조회
│
├── dashboard/
│   ├── app.py                   # FastAPI 서버 + WebSocket
│   ├── static/js/dashboard.js   # Chart.js 실시간 업데이트 (소수점 가격 처리)
│   └── templates/index.html     # 대시보드 HTML
│
├── backtest/
│   └── backtester.py            # 백테스팅 엔진 + CLI
└── logs/                        # 일별 로그 파일
```

---

## ⚡ 빠른 시작

```bash
# 1. 가상환경 + 의존성
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. 설정
cp config.example.yaml config.yaml
# config.yaml에 API 키 입력

# 3. 봇 실행 (백그라운드)
bash start.sh
# → http://localhost:8080 대시보드 확인

# 로그 확인
tail -f logs/bot_$(date +%Y%m%d)*.log
```

> **start.sh**: 기존 프로세스 자동 종료 → `bot.lock` 정리 → 백그라운드 재시작
> **중복 실행 방지**: `bot.lock` (fcntl.flock)으로 단일 인스턴스 보장

---

## 🔄 동작 흐름

### 1단계 — 배치 스크리닝 (하루 3회)

| 시각 (KST) | 대상 | 유니버스 | 필터 데이터 | 결과 |
|-----------|------|---------|-----------|------|
| **00:30** (매일) | 업비트 코인 | 24h 거래대금 상위 40개 | 4H봉 100개 (~16일치) | 최대 30개 |
| **06:00** (월~토) | 미국 NASDAQ | 고정 유니버스 100종목 | 일봉 200개 (~10개월치) | 상위 N개 |
| **15:00** (월~금) | KOSPI + KOSDAQ | 거래량 순위 각 100개 (장중만 동작) | 일봉 60개 (~3개월치) | 상위 N개 |

- 스크리닝 결과 없으면 `config.yaml`의 `symbols` 폴백 사용
- `_tech_score >= 3` 통과 기준: EMA 정배열(+3) · 거래량 급증(+2) · 52주 고가 근접(+2) · 볼린저 수축(+2) · 눌림목(+1)

### 2단계 — 장중 신호 체크 (60초마다)

선별된 종목 대상으로 매 60초:

```
① 데이터 수집 (종목당 봉 데이터)

   [업비트]
     4H봉  100개 (~16일치)   ← 사용 안 함 (MTF 비활성)
     15분봉 200개 (~50시간치) ← 사용 안 함 (Bollinger 비활성)
     일봉   400개 (~1.6년치)  ← turtle / trend_following 사용

   [국내 주식]
     일봉   300개 (~1.2년치)  ← turtle / trend_following 사용
     60분봉(KOSPI) / 30분봉(KOSDAQ) 120개 ← MTF 비활성 시 미사용

   [해외 주식]
     일봉   300개 (~1.2년치)  ← turtle / trend_following 사용
     15분봉 100개 (~25시간치) ← MTF 비활성 시 미사용

② 현재가 업데이트

③ 보유 포지션 → 손절(-3%) / 최대 보유 기간 초과 체크 → 조건 충족 시 즉시 매도

④ 미보유 포지션 → 전략 신호 계산 → BUY 신호 + 포지션 여유 있으면 매수
```

### 장 운영 시간

| 시장 | 운영 시간 | 요일 |
|------|----------|------|
| 업비트 (코인) | 24/7 | 매일 |
| KIS 국내 | 09:00 ~ 15:20 KST | 평일 |
| KIS 해외 (미국) | 22:30 ~ 05:00 KST (서머타임) / 23:30 ~ 06:00 (겨울) | 평일 |

---

## 📈 전략 상세

### 활성 전략 요약

| 전략 | 사용 봉 | 진입 | 청산 | 스타일 | 최대 보유 |
|------|---------|------|------|--------|----------|
| **TurtleStrategy** ✅ | **일봉** | 55일 도니안 상단 돌파 | 20일 최저가 이탈 / 2ATR 손절 | 장기 추세추종 | 없음 |
| **TrendFollowingStrategy** ✅ | **일봉** | MA20/MA200 골든크로스 또는 52주 신고가+정배열 | MA20/MA200 데드크로스 | 중기 스윙 | 14일 |

> 비활성: BollingerBreakout ⏸ · MTFStructure ⏸ · MAPullback ⏸

### 터틀 (`turtle`) — System 2

| 항목 | 값 |
|------|-----|
| 진입 | 55일 최고가 돌파 (전일 기준) |
| 청산 | 20일 최저가 이탈 |
| ATR 손절 | 진입가 - 2ATR |
| 피라미딩 | 0.5 ATR 상승마다 +1 Unit (최대 4 Unit) |
| 필터 | System 1만 적용 (System 2는 필터 없음) |

```
진입 조건: prev_close ≤ 55일고가 < curr_close
청산 조건: curr_close < 20일저가 OR curr_close < entry - 2×ATR
```

### 추세추종 (`trend_following`)

| 신호 | 조건 |
|------|------|
| 매수 | MA20 > MA200 골든크로스 |
| 매수 | MA20 > MA200 + 전일비 +1%↑ + 거래량 평균 150%↑ + 52주 신고가 |
| 매도 | MA20 < MA200 데드크로스 |

---

## 🛡️ 리스크 관리

### 포지션 사이징 (Kelly Criterion)

```
f* = (b × p - q) / b
  b = 수익비 (익절6% ÷ 손절3% = 2.0)
  p = 승률 (0.55 가정)

Half-Kelly 적용 후 종목당 최대 6% 캡
∴ 매수금액 = 총자산(200만원) × 6% ≈ 120,000원/종목
```

### 손절/청산/최대 보유 기간

| 전략 | 손절 | 청산 조건 | 최대 보유 |
|------|------|----------|----------|
| 터틀 | 2ATR 또는 -3% 안전망 | 20일 최저가 이탈 | **없음** |
| 추세추종 | -3% | MA20 < MA200 데드크로스 | **14일** |

최대 보유 기간 초과 시 → 자동 강제 청산 + 텔레그램 알림

### 서킷브레이커

- 일일 손실이 총자산의 **-2%** 도달 시 당일 신규 매수 중단
- 텔레그램 즉시 알림
- `/resume` 명령으로 재개

### 포지션 수 제한

- 동시 최대 보유 종목: **5** (`max_concurrent_positions`)
- 동일 종목 중복 매수 없음 (포지션 연 전략만 청산 가능)

---

## 🔄 재시작 시 포지션 복원

포트폴리오는 **메모리**에만 저장되므로, 봇 재시작 시 `trades.db`에서 미청산 포지션을 자동 복원합니다:

- DB에서 매수 후 매도 기록이 없는 종목 조회
- 동일 종목 여러 건은 **평균가 + 합산 수량**으로 병합
- 복원된 포지션의 손절가는 진입 평균가 기준으로 재계산

---

## 📊 대시보드 (`http://localhost:8080`)

| 섹션 | 내용 |
|------|------|
| 총 자산 | 업비트 KRW + 코인 평가액 + KIS 자본 합산 |
| 오늘 손익 | 당일 청산 거래 기준 실현 손익 |
| 현재 포지션 | 종목/거래소/전략/진입가/현재가/손절가/목표가/손익 |
| 최근 거래 이력 | 최근 20건 |
| 전략별 성과 | 전략별 거래수/승률/누적손익 |

모든 가격은 소수점 완전 표시 (K/M 약자 없음 — 소액 코인 대응).

---

## 📱 텔레그램 명령어

| 명령어 | 설명 |
|--------|------|
| `/status` | 봇 상태 |
| `/positions` | 현재 포지션 |
| `/pnl` | 손익 현황 |
| `/stop` | 봇 중지 |
| `/resume` | 봇 재개 |

---

## 📊 백테스트 결과 (2026-02-21)

> 초기자본 1,000만원 / 포지션 5% / 손절 3% / 익절 6%

| 전략 | 봉 | 승률 | 총손익 | 상태 |
|------|-----|------|--------|------|
| turtle | 일봉 | 55.3% | +348,965원 | ✅ 활성 |
| trend_following | 일봉 | 56.2% | +330,841원 | ✅ 활성 |
| bollinger_breakout | 15분봉 | 55.8% | +187,542원 | ⏸ 비활성 (코인 손실) |
| ma_pullback | 일봉 | 33.3% | -519원 | ⏸ 비활성 (성과 불량) |
| mtf_structure | 15분 LTF | 40.0% | -6,946원 | ⏸ 비활성 (검증 부족) |
| ~~smc 계열 5종~~ | — | — | — | ❌ 제거 |

```bash
# 백테스트 실행
.venv/bin/python -m backtest.backtester
```

---

## ⚙️ config.yaml 주요 설정

```yaml
risk:
  max_position_ratio: 0.06       # 종목당 최대 6%
  max_daily_loss_ratio: 0.02     # 일일 최대 손실 2%
  stop_loss_ratio: 0.03          # 손절 3%
  take_profit_ratio: 0.06        # 익절 6%
  max_concurrent_positions: 5    # 동시 보유 최대 5종목

strategy:
  upbit:
    active_strategies: ["turtle", "trend_following"]
  kis_domestic:
    active_strategies: ["turtle", "trend_following"]
  kis_overseas:
    market: "NAS"
    active_strategies: ["turtle", "trend_following"]
```

---

## ⚠️ 주의사항

- `config.yaml`은 `.gitignore` 포함 — **절대 커밋 금지**
- KIS는 최초 `is_paper_trading: true`로 검증 후 실전 전환
- KIS OAuth2 토큰: **1분당 1회** 발급 제한 (EGW00133 오류 시 1분 대기)
- KIS 국내 거래량 순위 API: **장중(09:00~15:20)에만 동작** → 스크리닝 15:00에 실행
- 장외 시간에 봇 시작 시 국내 스크리닝은 자동 스킵 (15:00 정기 스케줄로 실행됨)
- 미국 서머타임(3월~11월) 22:30 / 겨울(11월~3월) 23:30 시작
- 봇은 **단일 인스턴스**로만 실행 (`bot.lock` 중복 방지)
- 포지션은 메모리 저장 → 재시작 시 DB에서 자동 복원
- 투자에는 항상 원금 손실 위험이 있습니다

---

## 🚧 미구현 / 개선 예정

- [ ] 스크리닝 결과 대시보드 표시
- [ ] KIS 잔고 API 연동 (현재 100만원 하드코딩)
- [ ] 총자산 주기적 갱신 (현재 봇 시작 시 1회만 계산)
- [ ] bollinger_breakout / mtf_structure 재검증 후 재활성화 검토
- [x] 최대 보유 기간 강제 청산 (추세추종 14일, 터틀 제외)
- [x] misfire_grace_time 설정 (스크리닝 cron 잡 누락 방지)
- [x] 국내 스크리닝 장외 시간 자동 스킵

---

## 📄 라이선스

MIT License
