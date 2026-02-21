---
생성일: 2026-02-09
tags:
  - type/strategy
  - status/developing
  - topic/trading/smc
aliases:
  - SMC OB Pullback
  - SMC 눌림목 전략
---
연결문서 - [[이평선 쌍바닥과 눌림목]], [[SMC 전략 비교 매트릭스]]
참조문서 - [[SMC 기본 개념 정리]], [[Order Block]], [[Order Flow — 오더 플로우(주문 흐름)]], [[BOS & CHOCH (SMC 핵심 개념)]]

------

# 전략 개요 (Strategy Overview)

> **핵심 철학**
> 확립된 추세 방향으로 BOS가 발생한 후, 가격이 Fresh OB(Order Block) 또는 Demand/Supply Zone으로 되돌림(Pullback)할 때 진입한다. Order Flow의 Continuation 단계를 활용하여 **추세의 다음 파동에 탑승**하는 전략이다.

## 전략 성격
| 항목 | 값 |
|------|-----|
| 유형 | 추세추종 (Trend Following) |
| 목표 승률 | 50~60% |
| 목표 RR | 1:2 ~ 1:3 |
| 매매 빈도 | 중간 |
| 난이도 | 중간 |
| 적합 장세 | **추세장** (정배열/역배열 확립 후) |

## 전략의 전제 조건
- HTF에서 **추세가 확립**되어야 함 (BOS로 확인)
- OB는 **Fresh(미터치) 상태**에서만 유효 (첫 터치 우선)
- 진입은 반드시 **추세 방향으로만** (상승 추세 → 롱만, 하락 추세 → 숏만)
- OB에 도달 시 **PA(Price Action) 확인**이 필수 — 무조건 진입 금지

---

# 1. 핵심 개념 정의

## 1-1. Market Structure (시장 구조)

### 상승 구조 (Bullish Structure)
- Higher High(HH)와 Higher Low(HL)가 반복
- BOS: 직전 고점을 **캔들 몸통으로** 상방 돌파
- 매매 방향: **롱만 탐색**

### 하락 구조 (Bearish Structure)
- Lower Low(LL)와 Lower High(LH)가 반복
- BOS: 직전 저점을 **캔들 몸통으로** 하방 돌파
- 매매 방향: **숏만 탐색**

### BOS 유효성 판단
- **유효한 BOS**: 캔들 몸통이 이전 고점/저점을 완전히 돌파하여 마감
- **무효한 BOS**: 꼬리(wick)로만 찔렀을 경우 → BOS로 인정하지 않음
- **Failed BOS**: Minor 구조에서 돌파했으나 되돌림 발생 → 주의 필요

## 1-2. Order Block (OB) 식별

### Demand OB (매수 OB) — 롱 진입용
- **정의**: 강한 상승 임펄스 직전의 마지막 하락(Bearish) 캔들
- **범위**: 해당 캔들의 시가~저가 (꼬리 포함)
- **조건**: 이 OB에서 출발한 임펄스가 BOS를 만들어야 유효

### Supply OB (매도 OB) — 숏 진입용
- **정의**: 강한 하락 임펄스 직전의 마지막 상승(Bullish) 캔들
- **범위**: 해당 캔들의 시가~고가 (꼬리 포함)
- **조건**: 이 OB에서 출발한 임펄스가 BOS를 만들어야 유효

### OB 4가지 필수 조건
1. **Imbalance(불균형)**: OB에서 출발한 캔들이 장대양봉/장대음봉
2. **Break of Structure**: OB 출발 임펄스가 구조를 돌파(BOS)
3. **Inefficiency(비효율)**: FVG(Fair Value Gap)가 동반될수록 강함
4. **Unmitigated(미터치)**: 아직 가격 반응이 나오지 않은 Fresh 상태

### OB 등급 판정
| 등급 | 조건 | 신뢰도 |
|------|------|--------|
| S급 | CHOCH 기반 + FVG 동반 + HTF 정렬 + Fresh | 최고 |
| A급 | BOS 기반 + FVG 동반 + Fresh | 상 |
| B급 | BOS 기반 + Fresh (FVG 없음) | 중 |
| C급 | 2회 이상 터치(Mitigated) 또는 조건 미충족 | 매매 불가 |

## 1-3. Order Flow 4단계

이 전략은 **Continuation(4단계)** 에서 진입한다:

```
[1] Range (축적) → Bigboy 주문 축적
[2] Initiation (돌파) → CHOCH/BOS로 구조 돌파
[3] Mitigation (흡수) → OB/FVG로 되돌림 ← 여기서 진입!
[4] Continuation (지속) → 추세 재개 → 수익 구간
```

## 1-4. FVG (Fair Value Gap) 활용

- **상승 FVG**: 1번째 캔들 고가 ~ 3번째 캔들 저가 사이 갭
- **하락 FVG**: 1번째 캔들 저가 ~ 3번째 캔들 고가 사이 갭
- FVG와 OB가 겹치는 구간 = **컨플루언스 존** → 신뢰도 최상
- FVG는 가격을 끌어당기는 자석 역할 → 되돌림 목표 구간으로 활용

---

# 2. 멀티타임프레임 (MTF) 분석 체계

## 2-1. 타임프레임 역할 분담

| 타임프레임 | 역할 | 확인 사항 |
|-----------|------|----------|
| **주봉/일봉 (HTF)** | 대추세 방향 판단 | 시장 구조(HH/HL or LL/LH), Supply/Demand 대구간 |
| **4시간봉 (HTF)** | 추세 방향 + OB 식별 | BOS 확인, OB 위치 마킹, Order Flow 단계 판단 |
| **1시간봉 (MTF)** | 되돌림 구간 감시 | OB 접근 여부, 되돌림 깊이 확인 |
| **15분/5분봉 (LTF)** | 정밀 진입 타이밍 | PA 확인(핀바/잉걸핑/인사이드바), LTF 구조 전환 |

## 2-2. Top-Down 분석 플로우

```
[Step 1] HTF(4H) 추세 확인
    │
    ├── BOS로 상승 구조 확인 → 롱만 탐색
    ├── BOS로 하락 구조 확인 → 숏만 탐색
    └── 구조 불명확 / CHOCH 직후 → 매매 보류
    │
[Step 2] HTF(4H) OB 식별 및 마킹
    │
    ├── 가장 최근 BOS를 만든 OB 식별
    ├── OB가 Fresh(미터치)인지 확인
    ├── FVG 동반 여부 확인
    └── OB 등급 판정 (S/A/B/C)
    │
[Step 3] 가격의 OB 접근 대기
    │
    ├── 가격이 OB 구간에 진입하는지 관찰
    ├── 너무 깊은 되돌림(OB 이탈)이면 구조 훼손 의심
    └── OB 구간에 도달 시 LTF로 전환
    │
[Step 4] LTF(5m/15m) 진입 트리거 탐색
    │
    ├── OB 구간 내 PA 확인 (핀바/잉걸핑/인사이드바 돌파)
    ├── LTF에서 CHOCH → BOS 전환 확인 (선택적, 더 보수적)
    └── 진입 실행
```

---

# 3. 진입/손절/익절 규칙

## 3-1. 롱 진입

### 진입 조건 체크리스트
- [ ] HTF(4H): 상승 구조 확립 (HH + HL 반복, BOS 확인)
- [ ] HTF(4H): Demand OB 식별 완료 (BOS를 만든 마지막 Bearish 캔들)
- [ ] HTF(4H): OB가 Fresh(첫 터치) 상태
- [ ] HTF(4H): OB에 FVG가 동반되면 가산점
- [ ] HTF 대추세(일봉+): 상방 확인 (정렬)
- [ ] 가격이 Demand OB 구간에 도달
- [ ] LTF(5m/15m): OB 구간 내 Bullish PA 출현
  - 핀바(Hammer): 긴 아래꼬리 + 짧은 몸통
  - Bullish 잉걸핑: 이전 음봉을 완전히 감싸는 양봉
  - 인사이드바 상단 돌파
- [ ] (선택) LTF에서 Bullish CHOCH → BOS 전환 확인

### 진입 시점
- **기본**: OB 구간 내 Bullish PA 캔들 **종가 확정 시** 진입
- **보수적**: LTF에서 Bullish CHOCH 발생 후, 되돌림 → BOS 확정 시 진입
- **공격적**: OB 구간 하단에 지정가(Limit) 주문 배치

### 손절
- **기본**: OB 하단(저가) 하방 + 약간의 buffer
- OB 이탈 = 해당 OB 무효화 = 구조 훼손 가능성
- ⚠️ OB 바로 아래는 유동성 사냥 대상이 될 수 있으므로, OB 범위 전체를 넘어선 가격에 손절
- 손절폭이 넓으면 → 포지션 사이즈를 줄여 리스크 금액 고정 (계좌 1~2%)

### 익절
- **1차 익절 (50%)**: 직전 고점(HH) 부근 — RR 1:1~1:2
- **2차 익절 (30%)**: 다음 Supply Zone 하단 — RR 1:2~1:3
- **잔여 (20%) 트레일링**: 새로운 BOS 발생 시 손절을 새로운 HL로 올림, LTF CHOCH 발생 시 전량 청산

## 3-2. 숏 진입

### 진입 조건 체크리스트
- [ ] HTF(4H): 하락 구조 확립 (LL + LH 반복, BOS 확인)
- [ ] HTF(4H): Supply OB 식별 완료 (BOS를 만든 마지막 Bullish 캔들)
- [ ] HTF(4H): OB가 Fresh(첫 터치) 상태
- [ ] HTF(4H): OB에 FVG가 동반되면 가산점
- [ ] HTF 대추세(일봉+): 하방 확인 (정렬)
- [ ] 가격이 Supply OB 구간에 도달
- [ ] LTF(5m/15m): OB 구간 내 Bearish PA 출현
  - 핀바(Shooting Star): 긴 위꼬리 + 짧은 몸통
  - Bearish 잉걸핑: 이전 양봉을 완전히 감싸는 음봉
  - 인사이드바 하단 돌파
- [ ] (선택) LTF에서 Bearish CHOCH → BOS 전환 확인

### 진입 시점
- **기본**: OB 구간 내 Bearish PA 캔들 **종가 확정 시** 진입
- **보수적**: LTF에서 Bearish CHOCH 발생 후, 되돌림 → BOS 확정 시 진입
- **공격적**: OB 구간 상단에 지정가(Limit) 주문 배치

### 손절
- **기본**: OB 상단(고가) 상방 + 약간의 buffer
- ⚠️ 직전 고점(LH) 위는 유동성 사냥 대상 → OB 전체 범위를 넘어선 가격에 손절

### 익절
- **1차 익절 (50%)**: 직전 저점(LL) 부근 — RR 1:1~1:2
- **2차 익절 (30%)**: 다음 Demand Zone 상단 — RR 1:2~1:3
- **잔여 (20%) 트레일링**: 새로운 BOS 발생 시 손절을 새로운 LH로 내림, LTF CHOCH 발생 시 전량 청산

---

# 4. 매매 보류 조건 (No Trade Zone)

다음 조건 중 하나라도 해당하면 **매매하지 않음**:

1. **HTF 구조 불명확** — CHOCH 직후 BOS가 아직 미확정, 방향성 없음
2. **OB가 이미 Mitigated** — 2회 이상 터치된 OB는 무효
3. **OB 등급 C급 이하** — 조건 미충족 OB에서는 진입 금지
4. **HTF/LTF 방향 불일치** — HTF 상승인데 LTF 하락 구조면 대기
5. **LTF PA 미확인** — OB에 도달했으나 반전 캔들이 나오지 않음
6. **주요 경제 이벤트 직전** — FOMC, CPI, 고용지표 등
7. **RR 1:2 미만** — 손절 대비 기대 수익이 부족
8. **추세 과진행** — 같은 방향으로 3회 이상 BOS 후 눌림목은 실패 확률 증가

---

# 5. 시나리오 상세 (실전 플로우)

## 5-1. 롱 시나리오

### 시나리오 A: 정석 — 정배열 확립 후 OB 눌림목
```
[상황] 4H에서 HH + HL 반복, BOS 발생으로 상승 구조 확립
[마킹] 가장 최근 BOS를 만든 Demand OB 식별 + FVG 확인
[대기] 가격이 Demand OB 구간까지 되돌림
[확인] LTF(15m/5m)에서 Hammer, Bullish Engulfing 등 PA 출현
[진입] PA 캔들 종가 확정 시 롱 진입
[손절] OB 하단 하방
[익절] 1차 직전 HH, 2차 다음 Supply Zone, 잔여 트레일링
```

### 시나리오 B: 보수적 — LTF 구조 전환 확인 후 진입
```
[상황] 4H Demand OB에 가격 도달
[확인] LTF(5m)에서 하락 구조 → CHOCH 발생 → BOS 확정 (상승 구조 전환)
[진입] LTF BOS 확정 후 되돌림에서 LTF OB 진입
[손절] LTF CHOCH 저점 하방
[장점] 더 타이트한 손절 가능 → RR 개선
[단점] 진입 가격이 높아져 이상적 진입가를 놓칠 수 있음
```

## 5-2. 숏 시나리오

### 시나리오 A: 정석 — 역배열 확립 후 OB 눌림목
```
[상황] 4H에서 LL + LH 반복, BOS 발생으로 하락 구조 확립
[마킹] 가장 최근 BOS를 만든 Supply OB 식별 + FVG 확인
[대기] 가격이 Supply OB 구간까지 반등
[확인] LTF(15m/5m)에서 Shooting Star, Bearish Engulfing 등 PA 출현
[진입] PA 캔들 종가 확정 시 숏 진입
[손절] OB 상단 상방
[익절] 1차 직전 LL, 2차 다음 Demand Zone, 잔여 트레일링
```

### 시나리오 B: 보수적 — LTF 구조 전환 확인 후 진입
```
[상황] 4H Supply OB에 가격 도달
[확인] LTF(5m)에서 상승 구조 → CHOCH 발생 → BOS 확정 (하락 구조 전환)
[진입] LTF BOS 확정 후 되돌림에서 LTF OB 진입
[손절] LTF CHOCH 고점 상방
[장점] 더 타이트한 손절 → RR 개선
[단점] 진입 가격이 낮아져 이상적 진입가를 놓칠 수 있음
```

---

# 6. SMC 고유 필터링 (이평선 전략과의 차이점)

| 항목 | 이평선 눌림목 | SMC OB 눌림목 |
|------|-------------|-------------|
| 추세 판단 | 이평선 배열 (정배열/역배열) | BOS/CHOCH + 시장 구조 |
| 진입 구간 | 이평선 터치 (5 EMA / 20 EMA) | OB + FVG 구간 |
| 진입 확인 | 5 EMA 돌파 캔들 | PA 캔들 (핀바/잉걸핑/인사이드바) |
| 손절 기준 | 쌍바닥/쌍봉 극단점 | OB 범위 이탈 |
| 추세 지속 판단 | 이평선 배열 유지 여부 | Order Flow Mitigated/Unmitigated |
| 유동성 고려 | IDM 개념 참고 | Liquidity, IDM, Sweep 통합 |

---

# 7. AI 전문가 에이전트 디렉션

## 에이전트 역할 정의
> 이 에이전트는 "SMC OB 눌림목 전문가"로서, 주어진 차트 데이터에서 Market Structure → OB 식별 → Order Flow 분석 → PA 확인의 순서로 분석하고 매매 판단을 제공한다.

## 분석 파이프라인 (순서대로 실행)

### Phase 1: 시장 구조 분석 (HTF)
1. 4H 차트에서 스윙 포인트(HH/HL 또는 LL/LH) 식별
2. BOS 발생 여부 및 유효성 판단 (캔들 몸통 돌파 확인)
3. 현재 추세 방향 확정 (Bullish / Bearish / 불명확)
4. → **추세 불명확 시 "보류" 판정하고 중단**

### Phase 2: OB 식별 및 마킹 (HTF)
5. 가장 최근 BOS를 발생시킨 OB 식별
6. OB 4가지 조건 검증 (Imbalance, BOS, Inefficiency, Unmitigated)
7. FVG 동반 여부 확인
8. OB 등급 판정 (S/A/B/C)
9. → **C급 이하면 "매매 불가" 판정**

### Phase 3: Order Flow 분석 (HTF → MTF)
10. 현재 Order Flow 단계 판단 (Range/Initiation/Mitigation/Continuation)
11. Unmitigated OB가 남아있는지 확인
12. 가격이 OB에 접근 중인지 확인

### Phase 4: 진입 트리거 탐색 (LTF)
13. OB 구간 내 PA 캔들 탐색 (핀바/잉걸핑/인사이드바 돌파)
14. (선택) LTF 구조 전환(CHOCH → BOS) 확인
15. 진입 가격, 손절 가격, 익절 목표가 산출
16. RR 계산 → 1:2 미만이면 패스

### Phase 5: 리스크 관리
17. 계좌 대비 리스크 비율 계산 (권장: 계좌의 1~2%)
18. 포지션 사이즈 산출
19. 분할 익절 계획 수립 (50% / 30% / 20%)

### Phase 6: 최종 판단 출력
```
[판정] 롱/숏/보류
[신뢰도] 상/중/하
[시장 구조] Bullish/Bearish/불명확
[OB 등급] S/A/B/C
[Order Flow] Mitigation 단계 / Continuation 단계
[PA 확인] 핀바/잉걸핑/인사이드바/미확인
[진입가] xxxx
[손절가] xxxx (OB 하단/상단 기준)
[익절 1차] xxxx (R:R 1:x)
[익절 2차] xxxx (R:R 1:x)
[포지션 사이즈] 계좌의 x%
[주의사항] (해당 시)
```

---

# 8. 전략 한계 및 주의사항

1. **횡보장 취약**: 구조가 명확하지 않으면 OB가 반복적으로 무효화됨
2. **OB 범위 애매함**: HTF OB는 범위가 넓어 LTF에서 Refined OB를 찾아야 할 수 있음
3. **BOS 판단 주관성**: 어떤 스윙을 Major/Minor로 볼지에 따라 결과가 달라짐
4. **유동성 사냥**: OB 하단/상단이 스윕된 후 원래 방향으로 갈 수 있음 → 손절 buffer 필수
5. **뉴스/이벤트 리스크**: 기술적 분석만으로는 대응 불가한 외부 변수 존재

---

# 부록: 용어 정리

| 용어 | 설명 |
|------|------|
| OB | Order Block — 기관의 대량 주문이 집행된 가격대 |
| BOS | Break of Structure — 추세 지속을 확인하는 구조 돌파 |
| CHOCH | Change of Character — 추세 전환 초기 신호 |
| FVG | Fair Value Gap — 급격한 가격 이동으로 생긴 캔들 간 갭 |
| PA | Price Action — 캔들 패턴 기반 가격 행동 분석 |
| Demand OB | 매수 OB — 상승 임펄스 직전 마지막 하락 캔들 |
| Supply OB | 매도 OB — 하락 임펄스 직전 마지막 상승 캔들 |
| Fresh/Unmitigated | 아직 가격 반응이 나오지 않은 미터치 상태 |
| Mitigated | 이미 가격이 반응한(터치된) 상태 |
| HH/HL | Higher High / Higher Low (상승 구조) |
| LL/LH | Lower Low / Lower High (하락 구조) |
| Order Flow | 기관의 주문 흐름 — Range→Initiation→Mitigation→Continuation |
| IDM | Inducement — 유동성 사냥을 위한 미끼 구간 |
| R:R | Risk to Reward Ratio (손익비) |
