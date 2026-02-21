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
| `bot/screener.py` | 새벽 배치 스크리닝 엔진 (ScreenResult 반환) |
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

## 전략 파일 → STRATEGY_MAP

```python
# main.py STRATEGY_MAP (불량 전략 제거 완료)
"turtle"              → bot/strategy/turtle.py           ✅ 우수
"trend_following"     → bot/strategy/trend_following.py  ✅ 우수
"bollinger_breakout"  → bot/strategy/bollinger_breakout.py ✅ 양호
"ma_pullback"         → bot/strategy/ma_pullback.py      ⚠️ 보류
"mtf_structure"       → bot/strategy/mtf_structure.py    🆕 신규 실거래 검증 중

# 제거됨 (성과 불량)
# smc, smc_ob_pullback, smc_liquidity_sweep, smc_range, smc_golden_ob, rsi_reversal
```

### 전략별 손절/익절/최대보유기간

| 전략 | 손절 | 익절/청산 | 최대 보유 |
|------|------|----------|----------|
| **MTFStructureStrategy** | LTF 스윙 저점 | HTF 스윙 고점 (전략 계산) | **3일** |
| **BollingerBreakoutStrategy** | -3% 안전망 | 볼린저 중심선(MA20) 도달 | **3일** |
| **TrendFollowingStrategy** | -3% 안전망 | MA20 < MA200 데드크로스 | **14일** |
| **MAPullbackStrategy** | -3% 안전망 | EMA 역배열 | **14일** |
| **TurtleStrategy** | -3% 안전망 | 10일/20일 최저가 이탈 | **제한 없음** |

→ `main.py`의 `MAX_HOLD_DAYS` 딕셔너리에서 관리
→ `pos.take_profit_price > 0`이면 MTF (고정 TP), `== 0`이면 전략 신호로만 청산

---

## 시장별 MTF 타임프레임 매핑

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
| turtle | 일봉 | 55.3% | +348,965원 | ✅ 우수 |
| trend_following | 일봉 | 56.2% | +330,841원 | ✅ 우수 |
| bollinger_breakout | 1H | 55.8% | +187,542원 | ✅ 양호 |
| ma_pullback | 일봉 | 33.3% | -519원 | ⚠️ 보류 |
| mtf_structure | 15분 LTF | 40.0% | -6,946원 | ⚠️ 거래수 부족 |
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

### 스크리닝 구조
```
00:30 KST → 업비트 (거래대금 상위 40 → 4H HTF → 최대 30개)
06:00 KST → 미국 (NASDAQ 100종목, 월~토)
16:30 KST → 국내 (KOSPI+KOSDAQ 상위 200, 월~금)
```
- `ScreenResult.market_type`: KOSPI/KOSDAQ/NAS 구분

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
- [ ] mtf_structure 거래수 확대 검증
- [x] 최대 보유 기간 강제 청산 (볼린저/MTF 3일, 추세추종 14일)
