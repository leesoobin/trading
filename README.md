# AutoTrade Bot

> 업비트(코인) + 한국투자증권(국내/해외 주식) 자동매매봇

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)

---

## 개요

| 항목 | 내용 |
|------|------|
| **거래소** | 업비트 (암호화폐) · 한국투자증권 (국내/해외 주식) |
| **활성 전략** | 터틀 트레이딩(스윙) · 추세추종 MA크로스(스윙) |
| **유니버스** | 코인 ~242개 · 국내 KOSPI+KOSDAQ ~2,600개 · 해외 NASDAQ 100종목 |
| **데이터 업데이트** | 매일 12:30 KST (DataSync — 주말/야간 모두 동작) |
| **리스크** | Kelly Criterion 포지션 사이징 · 일일 손실 서킷브레이커 |
| **알림** | 텔레그램 봇 (매수/매도/일일 리포트/명령 수신) |
| **대시보드** | FastAPI + Chart.js 웹 UI (`http://localhost:8080`) |
| **운용 자본** | 업비트 ~100만원 + KIS ~100만원 = 총 ~200만원 |

---

## 빠른 시작

```bash
# 1. 가상환경 + 의존성
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. 설정
cp config.example.yaml config.yaml
# config.yaml에 API 키 입력 (절대 커밋 금지)

# 3. 봇 실행 (백그라운드)
bash start.sh
# → http://localhost:8080 대시보드 확인

# 로그 확인
tail -f logs/bot_$(date +%Y%m%d)*.log
```

> **start.sh**: 기존 프로세스 자동 종료 → `bot.lock` 정리 → 백그라운드 재시작

---

## 전체 시스템 흐름

```
[12:30 KST 매일]
  DataSync.sync_all()          ← OHLCV DB 증분 업데이트
      ├─ 국내: fchart 일봉 (~2,600종목)
      ├─ 해외: yfinance 배치 (100종목)
      └─ 코인: pyupbit 일봉 (~242종목)
      ↓
  Screener 3개 동시 실행      ← DB에서 OHLCV 로드 → 기술점수 계산

[60초마다, 장 운영시간]
  전략 실행 루프
      ├─ KIS/pyupbit API로 최신 봉 데이터 실시간 수집
      ├─ 손절/익절/보유기간 초과 체크
      └─ 전략 신호 계산 → 매수/매도 실행
```

---

## 데이터 수집 상세

### A. OHLCV DB 업데이트 (DataSync — 매일 12:30 KST)

| 시장 | 종목 수 | 소스 | 타임프레임 | DB 저장량 | market 키 |
|------|--------|------|-----------|----------|----------|
| KOSPI | ~840개 | 네이버 fchart XML | 일봉 (1d) | 최초 300봉 (~14개월) / 이후 5봉 증분 | `KOSPI` |
| KOSDAQ | ~1,817개 | 네이버 fchart XML | 일봉 (1d) | 최초 300봉 (~14개월) / 이후 5봉 증분 | `KOSDAQ` |
| 해외 NASDAQ | 100종목 | yfinance 배치 | 일봉 (1d) | 2년치 (~500봉) | `overseas` |
| 업비트 코인 | ~242개 | pyupbit | 일봉 (1d) | 최초 300봉 (~10개월) / 이후 5봉 증분 | `upbit` |

- **증분 업데이트 로직**: DB에 데이터가 있으면 최신 5봉만 fetch, 최초엔 300봉 전체 수집
- **주말/야간 동작**: 네이버 fchart·yfinance·pyupbit 모두 24h/주말 정상 동작
- **종목 목록**: 네이버 sise_market_sum 크롤링으로 KOSPI+KOSDAQ 전체 종목 자동 갱신

### B. 스크리닝 데이터 (DataSync 완료 후 즉시 실행)

#### 업비트 코인 스크리닝

| 단계 | 소스 | 내용 |
|------|------|------|
| 1단계 (유니버스) | Upbit API 실시간 | 24h 거래대금 상위 40개 선별 |
| 2단계 (기술분석) | DB 일봉 300봉 | 기술점수 계산 |
| 2단계 폴백 | pyupbit API | DB 없으면 일봉 300개 직접 수집 |
| 선별 기준 | — | 기술점수 ≥ 3점 → 상위 30개 |

#### 국내 주식 스크리닝 (KOSPI + KOSDAQ)

| 단계 | 소스 | 내용 |
|------|------|------|
| 1단계 (유니버스) | DB symbol_info | KOSPI/KOSDAQ 전체 ~2,600종목 목록 |
| 2단계 (기술분석) | DB 일봉 300봉 | 각 종목 기술점수 계산 |
| 폴백 (DB 없을 때) | 네이버 거래량 순위 + fchart API | 거래량 상위 100+100개 → fchart 일봉 100봉 |
| 선별 기준 | — | 기술점수 ≥ 3점 → 상위 30개 |

> DB 보유 시: 2,600개 전체 유니버스 처리 (기술점수 필터만 적용)
> DB 미보유 시: 거래량 상위 200개만 처리 (구버전 폴백)

#### 해외 NASDAQ 스크리닝

| 단계 | 소스 | 내용 |
|------|------|------|
| 1단계 (유니버스) | US_UNIVERSE 고정 목록 | 100종목 |
| 2단계 (기술분석) | DB 일봉 300봉 | 각 종목 기술점수 계산 |
| 폴백 (DB 없을 때) | yfinance 개별 | 1y 일봉 직접 수집 |
| 선별 기준 | — | 기술점수 ≥ 3점 → 상위 100개 |

#### 기술점수 (_tech_score) 기준

| 항목 | 배점 | 조건 |
|------|------|------|
| EMA 정배열 (5>20>60) | +3점 | 상승 추세 |
| EMA 역배열 (5<20<60) | +3점 | 하락 추세 |
| 거래량 급증 | +2점 / +1점 | 20일 평균 대비 2배↑ / 1.5배↑ |
| 52주 신고가 근접 | +2점 / +1점 | 52주 고가의 93%↑ / 85%↑ |
| 볼린저밴드 수축 | +2점 / +1점 | 40일 평균 표준편차의 65%↓ / 80%↓ |
| 20EMA 눌림목 | +1점 | 현재가 ↔ 20EMA 거리 1.5% 이내 |
| **통과 기준** | **≥ 3점** | |

### C. 장중 실시간 데이터 (전략 실행, 매 60초)

전략 실행 시에는 항상 **외부 API로 최신 데이터 실시간 수집** (DB 미사용):

#### 업비트

```
df_htf   = upbit.get_candles(symbol, "240", count=100)   # 4H봉 100개 (~16일)  [MTF용, 현재 미사용]
df_ltf   = upbit.get_candles(symbol, "15",  count=200)   # 15분봉 200개 (~50h) [Bollinger용, 현재 미사용]
df_daily = upbit.get_daily_candles(symbol, count=400)    # 일봉 400개 (~1.6년)  [turtle/trend 사용]
```

소스: `Upbit REST API (api.upbit.com)`

#### 국내 주식 (KIS)

```
df_daily = kis.get_domestic_daily_chart(symbol, count=300)             # 일봉 300개 (~14개월)   [turtle/trend 사용]
df_ltf   = kis.get_domestic_minute_chart(symbol, period=60, count=120) # 60분봉 120개 (KOSPI)  [MTF용, 현재 미사용]
         = kis.get_domestic_minute_chart(symbol, period=30, count=120) # 30분봉 120개 (KOSDAQ) [MTF용, 현재 미사용]
```

소스: `KIS OpenAPI (FHKST03010100 일봉 / FHKST03010200 분봉)`

> KIS 분봉 API: 1회 30개씩 반환 → 배치 반복 호출로 count 달성

#### 해외 주식 (KIS)

```
df_daily = kis.get_overseas_daily_chart(symbol, market="NAS", count=300) # 일봉 300개 (~14개월)  [turtle/trend 사용]
df_ltf   = kis.get_overseas_minute_chart(symbol, nmin=15, count=100)     # 15분봉 100개 (~25h) [MTF용, 현재 미사용]
```

소스: `KIS OpenAPI (HHDFS76240000 일봉 / HHDFS76200200 분봉)`

> 해외 분봉 API: nmin=1/5/10/15만 지원

---

## SQLite DB 구조 (trades.db)

### ohlcv 테이블 (OHLCV 캐시)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| symbol | TEXT | 종목 코드 (예: `005930`, `NVDA`, `KRW-BTC`) |
| market | TEXT | 시장 구분 (`KOSPI` / `KOSDAQ` / `overseas` / `upbit`) |
| timeframe | TEXT | 봉 단위 (현재 `1d` 만 사용) |
| ts | TEXT | 타임스탬프 (`YYYY-MM-DD`) |
| open/high/low/close/volume | REAL | 가격 데이터 |

저장 데이터량:

| market | 종목 수 | 봉 수 | 기간 |
|--------|--------|------|------|
| KOSPI | ~840 | 최대 300봉 | ~14개월 |
| KOSDAQ | ~1,817 | 최대 300봉 | ~14개월 |
| overseas | ~100 | ~500봉 | ~2년 |
| upbit | ~242 | 최대 300봉 | ~10개월 |

### symbol_info 테이블 (종목 코드 ↔ 이름)

| 컬럼 | 타입 | 예시 |
|------|------|------|
| symbol | TEXT | `005930` |
| market | TEXT | `KOSPI` / `KOSDAQ` / `overseas` / `upbit` |
| name | TEXT | `삼성전자` |

> DataSync 실행 시 자동 갱신. 대시보드 종목 검색, 텔레그램 알림에 사용.

### trades 테이블 (거래 이력)

매수/매도 실행 시마다 기록. 포지션 복원, 손익 집계, 대시보드에 사용.

### analysis_cache 테이블 (분석 캐시)

대시보드 종목 분석 탭 캐시 (1시간 TTL).

---

## 전략 상세

### 스타일 구분

| 스타일 | 설명 | 활성 전략 |
|--------|------|----------|
| **스윙 (Swing)** | 일봉 기준, 수일~수주 보유 | TurtleStrategy ✅, TrendFollowingStrategy ✅ |
| **데이트레이딩** | 15분/60분봉, 당일 청산 목표 | BollingerBreakout ⏸, MTFStructure ⏸ |

> **현재는 스윙 전략만 활성.** 데이트레이딩 전략은 코드는 존재하나 config에서 비활성화.

---

### TurtleStrategy (스윙) ✅ 활성

**Richard Dennis & William Eckhardt의 1983년 터틀 트레이딩 — System 2**

| 항목 | 값 |
|------|-----|
| **사용 봉** | 일봉 (업비트 400개 / 국내·해외 300개) |
| **진입** | 55일 도니안채널 상단 돌파 (전일 종가 ≤ 55일 고가 < 당일 종가) |
| **청산** | 20일 최저가 이탈 (전략 신호) |
| **손절** | 진입가 - 2×ATR(14일) 또는 -3% 안전망 중 높은 쪽 |
| **피라미딩** | 0.5 ATR 상승마다 +1 Unit (최대 4 Units) |
| **최대 보유** | 제한 없음 (추세가 이어지는 한 유지) |
| **TP(익절가)** | 없음 — 전략 신호로만 청산 |
| **데이터 소스** | 장중: KIS API / Upbit API (실시간) |

```
진입: prev_close ≤ high_55d < curr_close
청산: curr_close < low_20d  OR  curr_close < entry - 2×ATR
```

---

### TrendFollowingStrategy (스윙) ✅ 활성

**MA 크로스오버 + 52주 신고가 돌파 복합 신호**

| 항목 | 값 |
|------|-----|
| **사용 봉** | 일봉 (업비트 400개 / 국내·해외 300개) |
| **진입 조건 A** | MA20 > MA200 골든크로스 (전일 MA20 ≤ MA200, 당일 MA20 > MA200) |
| **진입 조건 B** | MA20 > MA200 + 전일비 +1%↑ + 거래량 20일 평균 150%↑ + 52주 신고가 |
| **청산** | MA20 < MA200 데드크로스 (전략 신호) |
| **손절** | -3% 안전망 |
| **최대 보유** | 14일 (초과 시 강제 청산) |
| **TP(익절가)** | 없음 — 전략 신호로만 청산 |
| **데이터 소스** | 장중: KIS API / Upbit API (실시간) |

```
진입A: prev_ma20 <= prev_ma200 AND curr_ma20 > curr_ma200
진입B: curr_ma20 > curr_ma200 AND pct_change >= 1% AND volume_ratio >= 1.5 AND curr >= high_52w
청산:  prev_ma20 >= prev_ma200 AND curr_ma20 < curr_ma200
```

---

### BollingerBreakoutStrategy (데이트레이딩) ⏸ 비활성

| 항목 | 값 |
|------|-----|
| **사용 봉** | 15분봉 200개 (~50시간) |
| **진입** | 볼린저밴드 상단 브레이크아웃 |
| **청산** | 밴드 복귀 또는 TP +6% |
| **최대 보유** | 3일 |
| **비활성 이유** | 코인 실거래 손실 → 추가 검증 필요 |

---

### MTFStructureStrategy (데이트레이딩) ⏸ 비활성

**다중 타임프레임 구조 매핑 (HTF 추세 + LTF 진입)**

| 시장 | HTF (추세 파악) | LTF (진입 타점) |
|------|----------------|----------------|
| 코인 | 4H봉 100개 (~16일) | 15분봉 200개 (~50h) |
| KOSPI | 일봉 300개 | 60분봉 120개 |
| KOSDAQ | 일봉 300개 | 30분봉 120개 |
| NASDAQ | 일봉 300개 | 15분봉 100개 |

| 항목 | 값 |
|------|-----|
| **진입** | HTF 상승추세 + LTF 해머캔들 + 거래량 급증 |
| **청산** | HTF 추세 전환 또는 TP |
| **최대 보유** | 3일 |
| **비활성 이유** | 거래 수 부족, 검증 미완 |

---

## 리스크 관리

### 포지션 사이징 (Kelly Criterion)

```
f* = (b × p - q) / b
  b = 수익비 (익절6% ÷ 손절3% = 2.0)
  p = 승률 (0.55 가정)
  q = 1 - p = 0.45

Half-Kelly 적용 후 종목당 최대 6% 캡
매수금액 = 총자산(200만원) × 6% ≈ 12만원/종목
```

### 손절/청산 규칙

| 전략 | 손절 | 청산 신호 | 최대 보유 |
|------|------|----------|----------|
| TurtleStrategy | 2ATR 또는 -3% 안전망 | 20일 최저가 이탈 | **없음** |
| TrendFollowingStrategy | -3% | MA20 < MA200 데드크로스 | **14일** |
| BollingerBreakout | -3% | 밴드 복귀 | 3일 |
| MTFStructure | 전략 자체 SL | HTF 추세 전환 | 3일 |

### 청산 후 쿨다운

- **모든 청산(손절/익절/전략신호) 후 24시간** 동일 종목 재진입 금지
- 과매매 방지 및 연속 손실 차단

### 서킷브레이커

- 일일 손실이 총자산의 **-2%** 도달 시 당일 신규 매수 전면 중단
- `/resume` 텔레그램 명령으로 재개

---

## 스케줄

| 시각 (KST) | 작업 | 대상 |
|-----------|------|------|
| **12:30** (매일) | DataSync + 스크리닝 통합 | 국내+해외+코인 동시 실행 |
| **16:00** (매일) | 일일 리포트 | 텔레그램 전송 |
| **00:00** (매일) | 일일 손익 리셋 | 포트폴리오 초기화 |
| **매 60초** (장중) | 전략 실행 | 코인(24/7) · 국내(09:00-15:20) · 해외(22:30-05:00) |

> `misfire_grace_time=300`: 이벤트 루프 지연 5분 이내면 실행 보장

---

## 프로젝트 구조

```
money/
├── config.yaml              # API 키 + 전략 설정 (gitignore — 절대 커밋 금지)
├── main.py                  # 봇 진입점 (봇 + 대시보드 동시 실행)
├── trades.db                # 거래 이력 + OHLCV 캐시 SQLite
├── start.sh                 # 봇 시작 스크립트 (백그라운드 실행)
│
├── bot/
│   ├── data_sync.py         # DataSync — 전체 유니버스 OHLCV 증분 업데이트 엔진
│   ├── screener.py          # 배치 스크리닝 엔진 (DB 우선 → API 폴백)
│   ├── scheduler.py         # APScheduler + 12:30 통합 스케줄
│   ├── storage.py           # SQLite CRUD (거래이력/OHLCV/종목정보/분석캐시)
│   ├── risk.py              # Kelly Criterion + 손절/익절 계산
│   ├── portfolio.py         # 포지션 상태 추적 (메모리)
│   ├── notification.py      # 텔레그램 알림 + 명령어 수신
│   ├── config.py            # pyyaml 설정 로더
│   ├── indicators.py        # 보조지표 (ATR, 도니안채널 등)
│   ├── exchange/
│   │   ├── upbit.py         # Upbit REST 클라이언트
│   │   └── kis.py           # KIS OAuth2 + REST 클라이언트
│   └── strategy/
│       ├── base.py          # Strategy ABC + Signal Enum
│       ├── turtle.py        # 터틀 트레이딩 ✅ 활성
│       ├── trend_following.py # 추세추종 MA크로스 ✅ 활성
│       ├── bollinger_breakout.py # 볼린저밴드 ⏸ 비활성
│       ├── mtf_structure.py # MTF 구조 매핑 ⏸ 비활성
│       └── ma_pullback.py   # 이평선 눌림목 ⏸ 비활성
│
├── dashboard/
│   ├── app.py               # FastAPI 서버 + WebSocket
│   ├── static/js/dashboard.js # Chart.js 실시간 UI (소수점 완전 표시)
│   └── templates/index.html
│
├── backtest/
│   └── backtester.py        # 백테스팅 엔진 + CLI
└── logs/                    # 일별 로그
```

---

## 재시작 시 자동 복원

| 항목 | 복원 소스 | 동작 |
|------|----------|------|
| 미청산 포지션 | `trades.db` | 매수 후 매도 없는 건 → 평균가+합산수량 병합 |
| 스크리닝 결과 | `screened_*.json` | 이전 스크리닝 결과 파일에서 복원 |

---

## 백테스트 결과 (2026-02-21)

> 초기자본 1,000만원 / 포지션 5% / 손절 3% / 익절 6%

| 전략 | 봉 | 승률 | 총손익 | 상태 |
|------|-----|------|--------|------|
| turtle | 일봉 | 55.3% | +348,965원 | ✅ 활성 |
| trend_following | 일봉 | 56.2% | +330,841원 | ✅ 활성 |
| bollinger_breakout | 15분봉 | 55.8% | +187,542원 | ⏸ 비활성 |
| ma_pullback | 일봉 | 33.3% | -519원 | ⏸ 비활성 |
| mtf_structure | 15분 LTF | 40.0% | -6,946원 | ⏸ 비활성 |

```bash
# 백테스트 실행
.venv/bin/python -m backtest.backtester
```

---

## config.yaml 주요 설정

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

## 텔레그램 명령어

| 명령어 | 설명 |
|--------|------|
| `/status` | 봇 상태 확인 |
| `/positions` | 현재 포지션 |
| `/pnl` | 손익 현황 |
| `/stop` | 봇 중지 |
| `/resume` | 봇 재개 |

---

## KIS API 주의사항

| 항목 | 내용 |
|------|------|
| OAuth2 토큰 | 1분당 1회 발급 제한 (EGW00133 오류 시 1분 대기) |
| 국내 분봉 | `FHKST03010200` TR, 1회 30개씩 반환 |
| 해외 분봉 | `HHDFS76200200` TR, nmin=1/5/10/15만 지원 |
| 해외 일봉 | `HHDFS76240000` — 계좌 권한 문제로 404 반환 → yfinance로 대체 |
| Rate limit | 해외 스크리닝 0.6초 대기, 장중 0.05초 대기 |

---

## 주의사항

- `config.yaml`은 `.gitignore` — **절대 커밋 금지**
- KIS는 최초 `is_paper_trading: true`로 검증 후 실전 전환
- 봇은 **단일 인스턴스**만 실행 (`bot.lock`, fcntl.flock)
- 포지션은 메모리 저장 → 재시작 시 DB 자동 복원
- 미국 서머타임(3월~11월) 22:30 / 겨울(11월~3월) 23:30 시작
- 투자에는 항상 원금 손실 위험이 있습니다

---

## 미구현 / 개선 예정

- [ ] 스크리닝 결과 대시보드 표시
- [ ] KIS 잔고 API 연동 (현재 100만원 하드코딩)
- [ ] 총자산 주기적 갱신 (현재 봇 시작 시 1회)
- [ ] bollinger_breakout / mtf_structure 재검증 후 재활성화 검토
- [x] DataSync 전체 유니버스 OHLCV 증분 업데이트 엔진
- [x] 스크리닝 DB 우선 로드 (API 재호출 최소화)
- [x] 12:30 KST 통합 스케줄 (데이터+스크리닝)
- [x] 최대 보유 기간 강제 청산
- [x] 청산 후 24h 쿨다운 (재진입 방지)

---

## 라이선스

MIT License
