# 데이터 소스 재계획 (2026-03-01)

## 1. 현황 — 시장별 데이터 소스 & 24시간 가용성

### 업비트 (코인)
| 용도 | 소스 | 24시간? | 비고 |
|------|------|---------|------|
| 스크리닝 후보 | pyupbit (거래대금 상위 40) | ✅ | 문제없음 |
| 기술점수 OHLCV (4H 100개) | pyupbit | ✅ | |
| 일봉 (turtle/trend용) | pyupbit | ✅ | |

### 국내 주식 (KIS)
| 용도 | 소스 | 24시간? | 비고 |
|------|------|---------|------|
| 스크리닝 거래량 순위 | ~~pykrx `get_market_ohlcv_by_ticker`~~ → **네이버 크롤링** (오늘 교체) | ✅(교체 후) | pykrx는 주말 KRX API 차단으로 실패 |
| 기술점수 OHLCV (일봉 60개) | pykrx `get_market_ohlcv_by_date` | ✅ | 다른 엔드포인트라 주말도 동작 |
| 일봉 (turtle/trend 거래용) | KIS `inquire-daily-itemchartprice` | ✅ | 24시간 동작 확인됨 |
| 분봉 (MTF용, 비활성) | KIS `FHKST03010200` | ❌ 장중만 | 장중(09:00~15:30)만 의미있는 데이터 |
| 종목명→코드 변환 | 네이버 크롤링 캐시(상위200개) → 네이버 자동완성 폴백 | ⚠️ | 캐시에 없는 종목(카카오뱅크 등)은 자동완성 API 의존 |
| 종목분석 OHLCV | pykrx `get_market_ohlcv_by_date` | ✅ | 일봉만, 분봉 미지원 |

### 해외 주식 (yfinance + KIS)
| 용도 | 소스 | 24시간? | 비고 |
|------|------|---------|------|
| 스크리닝 후보 + OHLCV | yfinance (US_UNIVERSE 고정) | ✅ | |
| 일봉 (turtle/trend 거래용) | yfinance | ✅ | |
| 분봉 (MTF용, 비활성) | KIS `HHDFS76200200` | ❌ 장중만 | NMIN=1/5/10/15만 지원 |
| 종목분석 OHLCV | yfinance | ✅ | |

---

## 2. 현재 문제점

### A. 국내 스크리닝 속도 느림
- **원인**: 네이버 크롤링 (HTML 파싱) 자체가 무거움 + 이후 pykrx `get_market_ohlcv_by_date` 200개 개별 호출
- **측정**: 약 20~30초 소요 (APScheduler misfire 경고 반복 발생 중)

### B. 국내 스크리닝 스케줄이 여전히 15:00 장중 고정
- **원인**: 기존에 KIS 거래량 순위 API가 장중 전용이라 15:00으로 박아뒀음
- **현황**: 네이버 크롤링으로 교체했으니 이제 시간 제약 없음 → 스케줄 변경 필요

### C. 종목분석 종목명→코드 변환 불안정
- **원인**: 캐시는 거래량 상위 200개만 포함 → 카카오뱅크(323410) 같이 순위 밖 종목은 없음
- **폴백**: 네이버 자동완성 API (`ac.finance.naver.com`) → 실서버에서 동작 여부 미확인 (개발환경 DNS 차단)

### D. 종목분석 국내 분봉 미지원
- **현황**: 분봉/시봉 선택해도 "일봉(1d)만 지원" 에러 반환
- **원인**: pykrx는 분봉 미지원, KIS 분봉은 장중만 유효

### E. KIS volume-rank API 미활용
- **현황**: `get_domestic_volume_ranking()` 이미 구현됨
- **특징**: 00시~08시 → 전일 최종 순위 제공, 장중 → 실시간 순위
- **장점**: 네이버 크롤링보다 빠름, 공식 데이터
- **미확인**: 주말(토/일)에도 동작하는지 테스트 필요

---

## 3. 검토된 대안

### 네이버 fchart XML
```
https://fchart.stock.naver.com/sise.nhn?symbol=005930&timeframe=day&count=300&requestType=0
```
- ✅ 토요일 테스트 완료, 24시간 동작
- ✅ 일봉/분봉 모두 지원 (timeframe=day/minute)
- ✅ API 키 불필요
- ✅ 개별 종목 OHLCV 조회에 매우 적합
- ❌ 전체 종목 거래량 순위 조회 불가 (코드를 알아야만 조회 가능)

### KIS volume-rank API (`/uapi/domestic-stock/v1/ranking/volume`)
- ✅ 이미 구현됨 (`get_domestic_volume_ranking`)
- ✅ 00시~08시 전일 순위 제공 (공식 문서 기준)
- ✅ 속도 빠름 (단일 API 호출)
- ⚠️ **주말 동작 여부 미확인** — 월요일에 테스트 필요
- ✅ 코드 + 이름 함께 반환

### 네이버 거래량 크롤링 (현재 적용)
- ✅ 주말 토요일 동작 확인됨
- ❌ 느림 (HTML 파싱 + 페이지당 약 2~3초)
- ❌ 네이버 구조 변경 시 깨질 수 있음

---

## 4. 변경 계획 (우선순위 순)

### [P1] 국내 스크리닝 거래량 순위 소스 결정
**월요일에 KIS volume-rank API 주말 동작 여부 확인 후 결정:**
- **KIS 동작 O** → KIS volume-rank로 교체 (빠름 + 공식 데이터)
  - `_fetch_volume_top` → KIS `get_domestic_volume_ranking` (KOSPI/KOSDAQ 각각 호출)
  - 주말 실패 시 네이버 크롤링 폴백
- **KIS 동작 X** → 네이버 크롤링 유지 (속도 개선 방안 검토)

### [P1] 국내 스크리닝 스케줄 변경
- 현재: 15:00 KST (장중 고정)
- 변경: **06:30 KST** (미국장 스크리닝 후, 매일) — 네이버 크롤링 24시간 가능하므로 제약 없음

### [P2] 종목분석 국내 OHLCV — 네이버 fchart XML 교체
```python
# 현재
pykrx_stock.get_market_ohlcv_by_date(start, end, symbol)

# 변경
https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count=300
```
- 일봉: `timeframe=day`
- 분봉: `timeframe=minute&count=6000` (~10거래일치)
- **효과**: 분봉/시봉 지원 추가, pykrx 의존성 제거, 24시간 안정적 동작

### [P2] 종목명→코드 변환 — KIS 종목 검색 API 활용
```
/uapi/domestic-stock/v1/quotations/search-stock-info
```
- 종목명으로 코드 검색 가능 (24시간 동작 여부 확인 필요)
- 확인 후 네이버 자동완성 대신 적용

### [P3] APScheduler misfire 근본 해결
- **현황**: 매 1분 interval 잡이 20초씩 밀려 misfire 경고 반복
- **원인**: 단일 스레드에서 네이버 크롤링 + 200개 OHLCV 조회가 60초를 초과
- **방안**: 스크리닝을 별도 프로세스/스레드로 분리 or 간격 5분으로 늘리기

---

## 5. 전략별 데이터 요구사항 정리 (목표 상태)

| 전략 | 봉 | 소스 (목표) | 24시간? |
|------|-----|------------|---------|
| TurtleStrategy | 일봉 300개 | 국내: fchart XML / 해외: yfinance / 코인: pyupbit | ✅ |
| TrendFollowingStrategy | 일봉 300개 | 동일 | ✅ |
| MTF (재활성화 검토) | HTF 일봉 + LTF 분봉 | LTF는 장중에만 의미있음 → 진입 시그널만 장중 확인 | 부분 |

---

## 6. 미확인 사항 (월요일 확인 필요)

- [ ] KIS volume-rank API — 주말(토/일) 00시~08시 동작 여부
- [ ] KIS 종목 검색 API — 종목명→코드 변환 지원 여부
- [ ] 네이버 자동완성 API — 실서버(맥미니)에서 실제 동작 여부
- [ ] 네이버 fchart XML 분봉 — count 최대치 및 응답 속도
