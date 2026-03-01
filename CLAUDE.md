# AutoTrade Bot — CLAUDE.md
> 세션 시작 시 이 파일을 참고하세요. 프로젝트 구조·규칙·전략 성과 요약.

---

## 프로젝트 개요

업비트(코인) + 한국투자증권(국내/해외 주식) 자동매매봇.
- **언어**: Python 3.11+, `.venv` 가상환경
- **실행**: `bash start.sh` (백그라운드 실행, 기존 프로세스 자동 종료)
- **API 키 위치**: `config.yaml` (gitignore — 절대 커밋 금지)
- **실전 운용 중**: KIS `is_paper_trading: false`, 업비트 실계좌
- **운용 자본**: 업비트 ~100만원 + KIS ~100만원 = 총 ~200만원

---

## 핵심 파일 경로

| 파일 | 역할 |
|------|------|
| `main.py` | 봇 진입점, STRATEGY_MAP, 전략 라우팅, 포지션 복원 |
| `config.yaml` | API 키 + 전략 설정 (gitignore) |
| `bot/screener.py` | 배치 스크리닝 엔진 (일봉 기술점수, ScreenResult 반환) |
| `bot/exchange/upbit.py` | Upbit REST + `get_total_balance_krw()` |
| `bot/exchange/kis.py` | KIS OAuth2 + REST 클라이언트 (분봉 포함) |
| `bot/scheduler.py` | APScheduler, 장 운영시간, 스크리닝 잡 |
| `bot/risk.py` | Kelly Criterion + 손절/익절 계산 |
| `bot/portfolio.py` | 포지션 상태 추적 (메모리) |
| `bot/storage.py` | SQLite 거래 이력 + `get_open_positions()` |
| `bot/notification.py` | 텔레그램 알림 (전략별 청산 조건 표시) |
| `dashboard/app.py` | FastAPI + WebSocket |
| `dashboard/static/js/dashboard.js` | 가격 포맷 (소수점 완전 표시, K/M 없음) |
| `backtest/backtester.py` | 백테스팅 엔진 + CLI (MTF 지원) |

---

## 활성 전략 (config.yaml 기준, 코인/국내/해외 공통)

```python
# 현재 활성 (3개 시장 모두 동일)
"turtle"          → bot/strategy/turtle.py          ✅ 활성
"trend_following" → bot/strategy/trend_following.py ✅ 활성

# 비활성 (config에서 제거됨)
"bollinger_breakout" ⏸ 코인 실거래 손실로 비활성
"mtf_structure"      ⏸ 거래수 부족, 검증 미완
"ma_pullback"        ⏸ 승률 33.3% 불량

# 제거됨 (영구)
# smc, smc_ob_pullback, smc_liquidity_sweep, smc_range, smc_golden_ob, rsi_reversal
```

### 활성 전략 진입/청산 조건

| 전략 | 사용 봉 | 진입 | 청산 | 최대 보유 |
|------|---------|------|------|----------|
| **TurtleStrategy** (System2) | **일봉** | 55일 도니안 상단 돌파 | 20일 최저가 이탈 / 2ATR 손절 | **없음** |
| **TrendFollowingStrategy** | **일봉** | MA20/MA200 골든크로스 또는 52주 신고가+정배열 | MA20 < MA200 데드크로스 | **14일** |

→ `main.py`의 `MAX_HOLD_DAYS` 딕셔너리에서 관리
→ `pos.take_profit_price == 0`이면 전략 신호로만 청산 (터틀/추세추종 모두 해당)

---

## 스크리닝 구조

### 실행 시간 및 데이터

| 시각 (KST) | 대상 | 유니버스 | 필터 데이터 | 결과 |
|-----------|------|---------|-----------|------|
| **00:30** (매일) | 업비트 코인 | 24h 거래대금 상위 40개 | **4H봉 100개** (~16일치) | 최대 30개 |
| **06:00** (월~토) | 미국 NASDAQ | 고정 100종목 (US_UNIVERSE) | **일봉 200개** (~10개월치) | 상위 N개 |
| **15:00** (월~금) | KOSPI+KOSDAQ | pykrx 거래량 상위 각 100개 | **일봉 60개** (~3개월치) | 상위 N개 |

- 공통 필터: `_tech_score >= 3` (EMA정배열 +3, 거래량급증 +2, 52주고가 +2, BB수축 +2, 눌림목 +1)
- 국내 스크리닝: KIS 거래량 순위 API(장중 전용) 대신 **pykrx**로 교체 → 장외 시간에도 안정 동작
- 모든 cron 잡 `misfire_grace_time=300` (이벤트 루프 지연 5분 이내 실행 보장)
- `ScreenResult.market_type`: KOSPI/KOSDAQ/NAS 구분 (main.py 분봉 결정용)

---

## 트레이딩 데이터 수집 (매 60초)

### 업비트

```python
df_htf   = upbit.get_candles(symbol, "240", count=100)   # 4H봉 100개 (~16일)  [MTF용, 현재 미사용]
df_ltf   = upbit.get_candles(symbol, "15",  count=200)   # 15분봉 200개 (~50h) [Bollinger용, 현재 미사용]
df_daily = upbit.get_daily_candles(symbol, count=400)    # 일봉 400개 (~1.6년)  [turtle/trend 사용]
```

### 국내 주식 (KIS)

```python
df_daily = kis.get_domestic_daily_chart(symbol, count=300)           # 일봉 300개 (~1.2년)  [turtle/trend 사용]
df_ltf   = kis.get_domestic_minute_chart(symbol, period=60, count=120) # 60분봉(KOSPI) 120개 [MTF용, 현재 미사용]
          # kis.get_domestic_minute_chart(symbol, period=30, count=120) # 30분봉(KOSDAQ)
```

### 해외 주식 (KIS)

```python
df_daily = kis.get_overseas_daily_chart(symbol, market="NAS", count=300) # 일봉 300개 (~1.2년) [turtle/trend 사용]
df_ltf   = kis.get_overseas_minute_chart(symbol, nmin=15, count=100)     # 15분봉 100개 (~25h) [MTF용, 현재 미사용]
```

---

## 시장별 MTF 타임프레임 매핑 (비활성이지만 코드 구조 유지)

| 시장 | HTF (추세 파악) | LTF (진입 시점) | 거래소 |
|------|----------------|----------------|--------|
| 코인 (KRW) | 4H (minute240) | 15분 (minute15) | 업비트 |
| KOSPI | 일봉 (day) | 60분 (minute60) | KIS |
| KOSDAQ | 일봉 (day) | 30분 (minute30) | KIS |
| NASDAQ | 일봉 (day) | 15분 (minute15) | KIS |

---

## 백테스트 결과 요약 (2026-02-21)

> 초기자본 1,000만원 / 포지션 5% / 손절 3% / 익절 6%

| 전략 | 봉 | 승률 | 총손익 | 상태 |
|------|-----|------|--------|------|
| turtle | 일봉 | 55.3% | +348,965원 | ✅ 활성 |
| trend_following | 일봉 | 56.2% | +330,841원 | ✅ 활성 |
| bollinger_breakout | 15분봉 | 55.8% | +187,542원 | ⏸ 비활성 (코인 손실) |
| ma_pullback | 일봉 | 33.3% | -519원 | ⏸ 비활성 |
| mtf_structure | 15분 LTF | 40.0% | -6,946원 | ⏸ 비활성 |
| smc 계열 5종 | — | — | 손실 | ❌ 제거 |

---

## 주요 구현 패턴 및 주의사항

### 봇 시작/재시작
- `bash start.sh`: 기존 포트 8080 프로세스 종료 + bot.lock 정리 + 백그라운드 실행
- `bot.lock` 파일로 단일 인스턴스 보장 (`fcntl.flock`)
- 이미 실행 중이면 즉시 종료

### 재시작 시 포지션 복원
- `storage.get_open_positions()`: 매수 후 매도 없는 미청산 포지션 조회
- 같은 종목 복수 매수는 **평균가 + 합산 수량**으로 병합
- 복원된 포지션 SL/TP: 진입 평균가 기준 재계산

### 업비트 매도 수량
- DB 수량이 아닌 **실제 잔고 조회** 후 매도 (수수료 차이 처리)
- `currency = symbol.replace("KRW-", "")` → `get_balance(currency)`

### 총자산 계산
- `upbit.get_total_balance_krw()`: KRW + 보유 코인 현재가 합산
- KIS 자본: 하드코딩 100만원 (API 잔고 조회 미구현)
- 봇 시작 시 1회 계산 (주기적 갱신 미구현)

### 가격 포맷
- 텔레그램: `_format_krw()` — 1,000원 이상 천단위 쉼표, 소수 최대 8자리
- 대시보드 JS: `fmt()` — K/M 없이 소수점 완전 표시

---

## KIS API 주의사항

- **거래량 순위 API**: 장중(09:00~15:20)에만 동작 → 주말/장마감 404 정상
- **OAuth2 토큰**: 1분당 1회 발급 제한 (EGW00133 → 1분 대기)
- **국내 분봉**: tr_id=`FHKST03010200`, 30개씩 반환
- **해외 분봉**: tr_id=`HHDFS76200200`, NMIN=1/5/10/15만 지원
- **Rate limiting**: 해외 스크리닝 `asyncio.sleep(0.6)`, 장중 `asyncio.sleep(0.05)`

---

## pyupbit 데이터 수집

```python
# 200개 초과: to 파라미터로 반복 호출
df = pyupbit.get_ohlcv(symbol, interval=interval, count=200, to=oldest_date)

# 업비트 일봉
df_daily = upbit.get_daily_candles(symbol, count=400)
```

---

## 백테스터 엔진 특성

- **고정 룩백 300개**: O(n) (슬라이딩 윈도우 O(n²) 사용 금지)
- **MTF**: `run_mtf()` — LTF를 4H로 자동 리샘플, 전략 SL/TP 사용
- **배치**: `python -m backtest.backtester`

---

## 현재 미구현 / 다음 작업

- [ ] KIS 잔고 API 연동 (현재 100만원 하드코딩)
- [ ] 총자산 주기적 갱신 (현재 봇 시작 시 1회)
- [ ] 스크리닝 결과 대시보드 표시
- [ ] bollinger_breakout / mtf_structure 재검증 후 재활성화 검토
- [x] 최대 보유 기간 강제 청산 (추세추종 14일, 터틀 제외)
- [x] misfire_grace_time=300 (스크리닝 cron 잡 누락 방지)
- [x] 국내 스크리닝 장외 시간 자동 스킵 + 15:00으로 변경
- [x] 해외 스크리닝 일봉 count=200 (EMA60 워밍업 개선)
