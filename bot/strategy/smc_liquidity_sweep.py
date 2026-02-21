"""SMC 유동성 스윕 헌팅 전략 (Liquidity Sweep)
EQH/EQL 유동성 풀 스윕 → CHOCH → BOS 전환 확인 후 역추세 진입
목표 승률: 30~40%, 목표 RR: 1:3~1:5+
"""
import pandas as pd

from bot.strategy.base import Signal, Strategy


class SMCLiquiditySweepStrategy(Strategy):
    """
    유동성 스윕 헌팅:
    - EQH/EQL 식별 → 스윕 감지 → CHOCH+BOS 확인 → 진입
    """
    name = "smc_liquidity_sweep"

    def __init__(self, config: dict = None):
        super().__init__(config)
        self._swing_n = 5
        self._eq_tolerance = 0.003   # EQH/EQL 동일 수준 판단 허용 오차 (0.3%)
        self._sweep_lookback = 30

    def _swing_highs(self, df: pd.DataFrame, n: int) -> list[int]:
        return [i for i in range(n, len(df) - n)
                if df["high"].iloc[i] == df["high"].iloc[i - n:i + n + 1].max()]

    def _swing_lows(self, df: pd.DataFrame, n: int) -> list[int]:
        return [i for i in range(n, len(df) - n)
                if df["low"].iloc[i] == df["low"].iloc[i - n:i + n + 1].min()]

    def _find_eqh(self, df: pd.DataFrame, sh: list[int]) -> list[float]:
        """Equal Highs: 비슷한 수준의 고점 2개 이상"""
        eqhs = []
        prices = [df["high"].iloc[i] for i in sh[-10:]]
        for i in range(len(prices)):
            for j in range(i + 1, len(prices)):
                if abs(prices[i] - prices[j]) / prices[i] <= self._eq_tolerance:
                    eqhs.append(max(prices[i], prices[j]))
        return list(set(round(p, 2) for p in eqhs))

    def _find_eql(self, df: pd.DataFrame, sl: list[int]) -> list[float]:
        """Equal Lows: 비슷한 수준의 저점 2개 이상"""
        eqls = []
        prices = [df["low"].iloc[i] for i in sl[-10:]]
        for i in range(len(prices)):
            for j in range(i + 1, len(prices)):
                if abs(prices[i] - prices[j]) / max(prices[i], 1e-9) <= self._eq_tolerance:
                    eqls.append(min(prices[i], prices[j]))
        return list(set(round(p, 2) for p in eqls))

    def _detect_sweep(self, df: pd.DataFrame, sh: list[int], sl: list[int]) -> str:
        """
        유동성 스윕 감지: 꼬리로 EQH/EQL 돌파 후 캔들 몸통이 안쪽으로 복귀
        Returns: 'sweep_high' | 'sweep_low' | 'none'
        """
        if len(df) < 3:
            return "none"

        eqhs = self._find_eqh(df, sh)
        eqls = self._find_eql(df, sl)

        prev = df.iloc[-2]
        curr = df.iloc[-1]

        # 고점 스윕: 이전 봉 꼬리가 EQH 돌파 → 현재 봉 종가가 EQH 아래
        for eqh in eqhs:
            if prev["high"] > eqh and curr["close"] < eqh:
                return "sweep_high"

        # 저점 스윕: 이전 봉 꼬리가 EQL 돌파 → 현재 봉 종가가 EQL 위
        for eql in eqls:
            if prev["low"] < eql and curr["close"] > eql:
                return "sweep_low"

        return "none"

    def _detect_choch(self, df: pd.DataFrame, sh: list[int], sl: list[int]) -> str:
        """CHoCH: 직전 구조 스윙 포인트 이탈"""
        if len(sh) < 1 or len(sl) < 1:
            return "none"
        curr = df["close"].iloc[-1]
        prev = df["close"].iloc[-2]
        last_sh = df["high"].iloc[sh[-1]]
        last_sl = df["low"].iloc[sl[-1]]
        if prev <= last_sh < curr:
            return "choch_up"
        if prev >= last_sl > curr:
            return "choch_down"
        return "none"

    def _recent_sweep(self, df: pd.DataFrame, sh: list[int], sl: list[int], lookback: int = 10) -> str:
        """최근 N봉 내에 스윕이 있었는지 확인"""
        sub = df.iloc[-lookback:].copy().reset_index(drop=True)
        sub_sh = [i for i in range(self._swing_n, len(sub) - self._swing_n)
                  if sub["high"].iloc[i] == sub["high"].iloc[max(0, i - self._swing_n):i + self._swing_n + 1].max()]
        sub_sl = [i for i in range(self._swing_n, len(sub) - self._swing_n)
                  if sub["low"].iloc[i] == sub["low"].iloc[max(0, i - self._swing_n):i + self._swing_n + 1].min()]
        return self._detect_sweep(sub, sub_sh, sub_sl)

    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        min_len = self._sweep_lookback + self._swing_n * 2 + 5
        if len(df) < min_len:
            self._reason = f"데이터 부족 ({len(df)}/{min_len})"
            return Signal.HOLD

        sh = self._swing_highs(df, self._swing_n)
        sl = self._swing_lows(df, self._swing_n)

        sweep = self._detect_sweep(df, sh, sl)
        choch = self._detect_choch(df, sh, sl)

        # 저점 스윕 → 상승 전환 신호
        if sweep == "sweep_low":
            self._reason = "[Sweep] 저점 유동성 스윕 감지 → 매수 준비"
            return Signal.BUY

        # CHOCH 상승 전환 (최근 스윕 후 발생)
        if choch == "choch_up":
            recent_sweep = self._recent_sweep(df, sh, sl, lookback=15)
            if recent_sweep == "sweep_low":
                self._reason = "[Sweep] 저점 스윕 → CHoCH 상승 전환 확인 → 매수"
                return Signal.BUY

        # 고점 스윕 → 하락 전환 신호
        if sweep == "sweep_high":
            self._reason = "[Sweep] 고점 유동성 스윕 감지 → 매도 준비"
            return Signal.SELL

        # CHOCH 하락 전환
        if choch == "choch_down":
            recent_sweep = self._recent_sweep(df, sh, sl, lookback=15)
            if recent_sweep == "sweep_high":
                self._reason = "[Sweep] 고점 스윕 → CHoCH 하락 전환 확인 → 매도"
                return Signal.SELL

        self._reason = f"[Sweep] 대기 (sweep={sweep}, choch={choch})"
        return Signal.HOLD

    def get_reason(self) -> str:
        return self._reason
