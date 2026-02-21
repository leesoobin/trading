---
생성일: 2026-02-09
tags:
  - type/strategy
  - status/developing
  - topic/trading/smc
aliases:
  - SMC Golden OB Sniper
  - OB 스나이핑 전략
---
연결문서 - [[SMC 추세추종 눌림목 (OB Pullback)]], [[SMC 전략 비교 매트릭스]]
참조문서 - [[SMC_Golden_OB_v5_Guide]], [[Order Block]], [[BOS & CHOCH (SMC 핵심 개념)]]

------

# 전략 개요 (Strategy Overview)

> **핵심 철학**
> SMC Golden OB v5 인디케이터의 **18점 스코어링 시스템과 Golden Zone 필터**를 활용하여, 정량적으로 검증된 고품질 OB에서만 진입한다. 주관적 판단을 최소화하고, **인디케이터의 객관적 점수 + 확인 캔들 시스템**에 의존하여 높은 승률을 추구하는 전략이다.

## 전략 성격
| 항목 | 값 |
|------|-----|
| 유형 | 인디케이터 기반 정밀 진입 |
| 목표 승률 | 55~65% |
| 목표 RR | 1:2 ~ 1:3 |
| 매매 빈도 | 낮음 (엄격한 필터링) |
| 난이도 | 낮음 (인디케이터가 판단 보조) |
| 적합 장세 | **추세장** (HTF/LTF 트렌드 정렬 시) |

## 전략의 전제 조건
- **SMC Golden OB v5 인디케이터** 사용 필수
- **S-Grade(12+) 또는 Golden Zone OB**에서만 진입 (C/B급 무시)
- **HTF + LTF 트렌드 정렬** 필수 (Info Table에서 확인)
- **확인 캔들(Confirmation Candle)** 발생 후에만 진입 (Smart 모드)
- 인디케이터 신호에 의존하되, **맹목적 추종은 금지** — 시장 맥락 확인 필수

---

# 1. 인디케이터 핵심 시스템 이해

## 1-1. 18점 스코어링 시스템

### 점수 산정 기준

| 요소 | 조건 | 점수 | 이 전략에서의 의미 |
|------|------|------|-----------------|
| **Structure** | CHOCH | +4 | 추세 전환 OB → 높은 가치 |
| | BOS | +2 | 추세 지속 OB → 기본 가치 |
| **HTF Alignment** | HTF 트렌드 일치 | +2 | MTF 정렬 → 높은 신뢰도 |
| **Base Candles** | 1~3개 | +2 | 타이트한 OB → 정밀 진입 가능 |
| | 4~5개 | +1 | 넓은 OB → 허용 |
| **Consecutive** | 3개 이상 연속 임펄스 | +2 | 강한 모멘텀 → 높은 신뢰 |
| | 2개 연속 | +1 | 보통 모멘텀 |
| **Move Distance** | ≥ 2.5 ATR | +2 | 매우 강한 이탈 |
| | ≥ 1.5 ATR | +1 | 보통 이탈 |
| **Wick Ratio** | ≤ 40% | +2 | 깔끔한 캔들 (확신있는 이동) |
| | ≤ 60% | +1 | 허용 범위 |
| **Gap** | FVG 존재 | +1 | 비효율 구간 동반 |
| **Golden Zone** | 61.8% Fib | +3 | 최강 컨플루언스 |
| | 50.0% Fib | +2 | 강한 컨플루언스 |
| | 38.2% Fib | +1 | 기본 컨플루언스 |

### 등급 분류
| 등급 | 점수 | 이 전략에서 | 판단 |
|------|------|-----------|------|
| **S-Grade** | 12+ | **필수 진입 대상** | 최고 품질, 놓치면 안 되는 기회 |
| **A-Grade** | 9~11 | **Golden Zone 겹침 시 진입** | 우수 품질, 추가 확인 필요 |
| **B-Grade** | 6~8 | **진입 금지** (이 전략에서) | 보통 품질 — 전략 1로 판단 |
| **C-Grade** | 1~5 | **무시** | 낮은 품질 |

## 1-2. Golden Zone (피보나치 컨플루언스)

### 정의
- 직전 스윙의 **피보나치 되돌림 핵심 레벨**과 **OB가 겹치는 구간**
- OB + Fib = **이중 근거** → 승률 상승

### Golden Zone 레벨
| Fib 레벨 | 강도 | 가산점 | 해석 |
|----------|------|--------|------|
| **61.8%** | 최강 | +3 | 가장 강력한 되돌림, 최고 진입점 |
| **50.0%** | 강 | +2 | Equilibrium, 균형 되돌림 |
| **38.2%** | 보통 | +1 | 얕은 되돌림 (추세가 강할 때) |

### Golden OB
- **Golden OB = OB + Golden Zone 겹침**
- 인디케이터에서 ◆(61.8%), ◇(50%), ·(38.2%)로 표시
- 이 전략의 **핵심 진입 대상**

## 1-3. 확인 캔들 (Confirmation Candle)

### 3가지 확인 패턴

| 패턴 | 코드 | 롱 조건 | 숏 조건 |
|------|------|---------|---------|
| **Pinbar** | PIN | Hammer (긴 아래꼬리, wick ratio ≥ 0.6) | Shooting Star (긴 위꼬리) |
| **Engulfing** | ENG | Bullish Engulfing (이전 음봉 완전 감싸는 양봉) | Bearish Engulfing (이전 양봉 완전 감싸는 음봉) |
| **Inside Bar** | IB | Inside Bar 상단 돌파 | Inside Bar 하단 돌파 |

### Smart 시그널 발생 조건
```
HQ OB(S-Grade 또는 Golden) 진입
    + 확인 캔들(PIN/ENG/IB) 발생
    + 쿨다운 Ready 상태
    = 🔥 SMART SIGNAL 발생 → 진입!
```

## 1-4. Info Table 읽는 법

```
┌───────────────────┐
│ SMC v5            │
├───────────────────┤
│ Trend: ▲/▲ ✓     │ ← LTF/HTF 둘 다 Bullish + 정렬됨
│ Mode: Smart       │
├───────────────────┤
│ OBs: 4 (S:1 G:2) │ ← 활성 OB 4개 (S등급 1개, Golden 2개)
├───────────────────┤
│ Demand: 🔥 HQ     │ ← 현재 HQ Demand 존 안에 있음
│ Supply: —         │
├───────────────────┤
│ L-CD: ✓           │ ← Long 쿨다운 Ready
│ S-CD: 3           │ ← Short 3캔들 후 Ready
├───────────────────┤
│ Signal: 🟢 LONG   │ ← Long 시그널 발생!
└───────────────────┘
```

### 진입 가능 조건 (Info Table 기준)
- Trend: **✓ (정렬됨)** 필수
- Demand/Supply: **🔥 HQ** 필수
- CD(쿨다운): **✓ (Ready)** 필수
- Signal: **🟢/🔴** 표시 시 진입

---

# 2. 멀티타임프레임 (MTF) 설정

## 2-1. 타임프레임별 인디케이터 설정

### 스캘핑 (1분 ~ 15분)
| 설정 | 값 |
|------|-----|
| Clean Mode | ON |
| Show Grade | S |
| Signal Mode | Smart |
| Cooldown | 3 bars |
| Swing Detection | 3 |
| HTF | 60분 또는 240분 |

### 데이트레이딩 (30분 ~ 1시간)
| 설정 | 값 |
|------|-----|
| Clean Mode | ON |
| Show Grade | A |
| Signal Mode | Smart |
| Cooldown | 5 bars |
| Swing Detection | 5 |
| HTF | 240분 |

### 스윙 트레이딩 (4시간 ~ 일봉)
| 설정 | 값 |
|------|-----|
| Clean Mode | OFF |
| Signal Mode | Golden/S Only |
| Cooldown | 3 bars |
| Swing Detection | 8 |
| HTF Swing Detection | 15 |
| HTF | Daily 또는 Weekly |

## 2-2. 분석 플로우

```
[Step 1] Info Table 확인
    │
    ├── Trend 정렬 여부 (✓ 필수)
    ├── 활성 OB 현황 (S등급, Golden 개수)
    └── 쿨다운 상태
    │
[Step 2] 차트에서 HQ OB 위치 확인
    │
    ├── S-Grade OB 위치 (🌟 표시)
    ├── Golden OB 위치 (◆◇· 표시)
    └── HTF OB와 LTF OB 겹침 여부
    │
[Step 3] 가격의 HQ OB 접근 대기
    │
    ├── Demand HQ OB → 롱 준비
    ├── Supply HQ OB → 숏 준비
    └── 균형가(50% Fib) 부근 → 가장 이상적
    │
[Step 4] 시그널 발생 확인
    │
    ├── 🔥 HQ 표시 + 확인 캔들 발생
    ├── Info Table에 🟢/🔴 시그널 표시
    └── 진입 실행
```

---

# 3. 진입/손절/익절 규칙

## 3-1. 롱 진입

### 진입 조건 체크리스트
- [ ] **Trend 정렬**: LTF + HTF 둘 다 Bullish (▲/▲ ✓)
- [ ] **HQ Demand OB**: S-Grade(12+) 또는 Golden Zone Demand OB
- [ ] **Fresh 상태**: 해당 OB가 아직 Mitigated 되지 않음
- [ ] **가격 진입**: 가격이 HQ Demand OB 구간에 진입
- [ ] **확인 캔들**: PIN(Hammer) / ENG(Bullish Engulfing) / IB(상단 돌파) 중 하나 발생
- [ ] **쿨다운**: L-CD ✓ (Ready 상태)
- [ ] **시그널**: Info Table에 🟢 LONG 표시
- [ ] (가산) HTF OB와 LTF OB가 겹치는 구간

### 진입 시점
- **Smart 모드**: 🔥LONG 시그널 발생 시 즉시 진입
- 시그널 라벨 예시: `🔥LONG(12)[PIN]` = S-Grade(12점) Demand + Pinbar 확인

### 손절
- **기본**: OB 하단 아래 (인디케이터에 표시된 OB 박스 하단)
- 또는 **2 ATR** 거리
- 둘 중 더 보수적인(넓은) 값 선택

### 익절
- **1차 익절 (50%)**: 직전 고점 (최근 Swing High) — RR 1:1~1:2
- **2차 익절 (30%)**: HTF 저항대 또는 Supply OB 하단 — RR 1:2~1:3
- **잔여 (20%) 트레일링**: BOS 발생 시 손절 올림, CHOCH 발생 시 전량 청산

## 3-2. 숏 진입

### 진입 조건 체크리스트
- [ ] **Trend 정렬**: LTF + HTF 둘 다 Bearish (▼/▼ ✓)
- [ ] **HQ Supply OB**: S-Grade(12+) 또는 Golden Zone Supply OB
- [ ] **Fresh 상태**: 해당 OB가 아직 Mitigated 되지 않음
- [ ] **가격 진입**: 가격이 HQ Supply OB 구간에 진입
- [ ] **확인 캔들**: PIN(Shooting Star) / ENG(Bearish Engulfing) / IB(하단 돌파) 중 하나 발생
- [ ] **쿨다운**: S-CD ✓ (Ready 상태)
- [ ] **시그널**: Info Table에 🔴 SHORT 표시
- [ ] (가산) HTF OB와 LTF OB가 겹치는 구간

### 진입 시점
- **Smart 모드**: 🔥SHORT 시그널 발생 시 즉시 진입
- 시그널 라벨 예시: `🔥SHORT(10)[ENG]` = A-Grade(10점) Golden Supply + Engulfing 확인

### 손절
- **기본**: OB 상단 위 (인디케이터에 표시된 OB 박스 상단)
- 또는 **2 ATR** 거리

### 익절
- **1차 익절 (50%)**: 직전 저점 (최근 Swing Low) — RR 1:1~1:2
- **2차 익절 (30%)**: HTF 지지대 또는 Demand OB 상단 — RR 1:2~1:3
- **잔여 (20%) 트레일링**: BOS 발생 시 손절 내림, CHOCH 발생 시 전량 청산

---

# 4. 매매 보류 조건 (No Trade Zone)

다음 조건 중 하나라도 해당하면 **매매하지 않음**:

1. **Trend 비정렬** — LTF와 HTF 방향 불일치 (Info Table에 ✓ 없음)
2. **C-Grade 또는 B-Grade OB** — 이 전략에서는 S/A(Golden) 이상만 진입
3. **Mitigated OB** — 이미 가격 반응이 나온 OB (인디케이터가 자동 제거)
4. **확인 캔들 미발생** — Smart 모드 조건 미충족
5. **쿨다운 중** — 이전 시그널 발생 후 쿨다운 기간 내
6. **활성 OB 부재** — Info Table에서 OBs: 0 (S:0 G:0)
7. **주요 경제 이벤트 직전** — 기술적 시그널이 무효화될 수 있음
8. **RR 1:2 미만** — OB 범위가 넓어 적절한 RR 확보 불가

---

# 5. 시나리오 상세 (실전 플로우)

## 5-1. 롱 시나리오

### 시나리오 A: S-Grade Demand + Smart Signal
```
[전제] Info Table: Trend ▲/▲ ✓ | Mode: Smart | L-CD: ✓
[감지] S-Grade(14점) Demand OB 표시 (🌟D14◆)
[대기] 가격이 해당 OB 구간으로 하락
[확인] OB 구간 내 Hammer 발생 → 🔥LONG(14)[PIN] 시그널
[진입] 시그널 발생 시 즉시 롱 진입
[손절] OB 하단 아래
[익절] 1차 직전 고점, 2차 HTF 저항, 잔여 트레일링
```

### 시나리오 B: A-Grade Golden Demand
```
[전제] Info Table: Trend ▲/▲ ✓ | Mode: Smart | L-CD: ✓
[감지] A-Grade(10점) Golden(61.8%) Demand OB 표시 (⭐D10◆)
[대기] 가격이 해당 OB 구간(= 61.8% Fib 구간)으로 하락
[확인] OB 구간 내 Bullish Engulfing 발생 → 🔥LONG(10)[ENG]
[진입] 시그널 발생 시 롱 진입
[손절] OB 하단 아래
[익절] 1차 직전 고점, 2차 HTF 저항
```

## 5-2. 숏 시나리오

### 시나리오 A: S-Grade Supply + Smart Signal
```
[전제] Info Table: Trend ▼/▼ ✓ | Mode: Smart | S-CD: ✓
[감지] S-Grade(13점) Supply OB 표시 (🌟S13◇)
[대기] 가격이 해당 OB 구간으로 상승
[확인] OB 구간 내 Shooting Star 발생 → 🔥SHORT(13)[PIN] 시그널
[진입] 시그널 발생 시 즉시 숏 진입
[손절] OB 상단 위
[익절] 1차 직전 저점, 2차 HTF 지지, 잔여 트레일링
```

### 시나리오 B: A-Grade Golden Supply
```
[전제] Info Table: Trend ▼/▼ ✓ | Mode: Smart | S-CD: ✓
[감지] A-Grade(9점) Golden(50%) Supply OB 표시 (⭐S9◇)
[대기] 가격이 해당 OB 구간(= 50% Fib 구간)으로 상승
[확인] OB 구간 내 Bearish Engulfing → 🔥SHORT(9)[ENG]
[진입] 시그널 발생 시 숏 진입
[손절] OB 상단 위
```

---

# 6. 인디케이터 의존 시 주의사항

인디케이터는 강력한 도구이지만, **맹목적 추종은 위험**하다:

### 인디케이터가 잘 작동하는 조건
- 추세가 명확한 시장 (정렬 상태)
- 변동성이 적당한 시장
- 유동성이 충분한 자산 (BTC, 나스닥, 주요 종목)

### 인디케이터 한계
- **횡보장에서 오신호**: 추세가 없으면 OB가 반복적으로 무효화
- **뉴스 이벤트**: 기술적 시그널과 무관한 급변동 발생
- **과최적화**: 인디케이터 설정을 과도하게 튜닝하면 과적합 위험
- **Lag**: 확인 캔들을 기다리므로 최적 진입가를 놓칠 수 있음

### 인디케이터 + 시장 맥락 결합 체크
| 인디케이터 신호 | 시장 맥락 확인 | 판단 |
|----------------|-------------|------|
| 🔥LONG 발생 | HTF 상승 구조 + Demand Zone 확인 | **진입** |
| 🔥LONG 발생 | HTF 하락 중 + 구조 불명확 | **보류** (비정렬 가능성) |
| 🔥SHORT 발생 | 주요 지지대 바로 위 | **보류** (반등 가능성) |
| S-Grade OB | 이미 추세가 과진행 (3+파동) | **주의** (사이즈 축소) |

---

# 7. AI 전문가 에이전트 디렉션

## 에이전트 역할 정의
> 이 에이전트는 "Golden OB 스나이퍼"로서, 인디케이터의 정량적 점수와 시장 맥락을 결합하여 **고승률 진입 기회만 선별**한다. 인디케이터 데이터를 1차 필터로, 시장 구조를 2차 필터로 사용한다.

## 분석 파이프라인 (순서대로 실행)

### Phase 1: 인디케이터 상태 확인
1. Info Table 읽기: Trend 정렬, 활성 OB 수, 쿨다운 상태
2. S-Grade / Golden OB 존재 여부 확인
3. → **비정렬 또는 HQ OB 부재 시 "대기" 판정**

### Phase 2: OB 품질 검증
4. HQ OB의 스코어 세부 구성 확인 (어떤 항목에서 점수를 받았는지)
5. CHOCH 기반 OB인지 BOS 기반 OB인지 확인 (CHOCH 기반 = 더 높은 가치)
6. FVG 동반 여부 확인
7. → **핵심 항목(Structure, HTF Alignment)에서 점수를 못 받은 OB는 경고**

### Phase 3: 시장 맥락 검증 (인디케이터 외부)
8. HTF에서 시장 구조가 실제로 해당 방향을 지지하는지 확인
9. 주요 S/D Zone, 유동성 풀과의 관계 확인
10. 추세 과진행 여부 확인 (3파 이상 진행 시 주의)

### Phase 4: 진입 트리거 대기
11. 가격이 HQ OB 구간에 진입하는지 감시
12. 확인 캔들(PIN/ENG/IB) 발생 대기
13. 시그널 발생 확인

### Phase 5: 리스크 관리
14. 진입가, 손절가(OB 하/상단), 익절 목표가 산출
15. RR 계산 → 1:2 미만이면 패스
16. 포지션 사이즈 산출 (계좌 1~2%)
17. 분할 익절 계획 (50% / 30% / 20%)

### Phase 6: 최종 판단 출력
```
[판정] 롱/숏/보류
[신뢰도] 상/중/하
[Trend 정렬] ✓ / ✗
[OB 등급] S-Grade(xx점) / A-Grade(xx점) Golden
[OB 상세] Structure: CHOCH(+4) / HTF: 정렬(+2) / FVG: 있음(+1) / ...
[Golden Zone] 61.8% / 50% / 38.2% / 해당없음
[확인 캔들] PIN / ENG / IB / 미확인
[시그널] 🔥LONG / 🔥SHORT / 대기
[진입가] xxxx
[손절가] xxxx (OB 하단/상단)
[익절 1차] xxxx (R:R 1:x)
[익절 2차] xxxx (R:R 1:x)
[포지션 사이즈] 계좌의 x%
[시장 맥락 주의] (해당 시)
```

---

# 8. 전략 한계 및 주의사항

1. **인디케이터 의존성**: 인디케이터 자체의 버그나 오작동 가능성
2. **낮은 매매 빈도**: S-Grade + Golden + Smart 시그널 조합은 드물게 발생
3. **확인 캔들 지연**: PA를 기다리느라 최적 진입가를 놓칠 수 있음
4. **횡보장 오신호**: 추세가 없으면 OB가 반복 무효화 → 정렬 확인 필수
5. **설정 민감도**: Swing Detection Length, ATR Period 등 설정에 따라 결과 변동
6. **과신 경계**: "인디케이터가 말했으니까"는 위험 — 항상 시장 맥락과 교차 검증

---

# 부록: 인디케이터 라벨 빠른 참조

### OB 라벨 해석
```
D12◆  = Demand, 12점, Golden 61.8%
S9◇   = Supply, 9점, Golden 50%
HD10·  = HTF Demand, 10점, Golden 38.2%
D7     = Demand, 7점 (Golden 아님)
```

### 시그널 라벨 해석
```
🔥LONG(12)[PIN]  = HQ Demand, 12점, Pinbar 확인
🔥SHORT(10)[ENG] = HQ Supply, 10점, Engulfing 확인
🔥LONG(14)[IB]   = HQ Demand, 14점, Inside Bar 돌파 확인
```

### 등급 아이콘
| 아이콘 | 등급 | 점수 |
|--------|------|------|
| 🌟 | S-Grade | 12+ |
| ⭐ | A-Grade | 9~11 |
| ● | B-Grade | 6~8 |
| (숨김) | C-Grade | 1~5 |
