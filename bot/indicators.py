import pandas as pd
import numpy as np

try:
    import pandas_ta as ta
    _HAS_TA = True
except ImportError:
    _HAS_TA = False


def calc_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    if _HAS_TA:
        return ta.rsi(df["close"], length=period)
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_ma(df: pd.DataFrame, period: int) -> pd.Series:
    if _HAS_TA:
        return ta.sma(df["close"], length=period)
    return df["close"].rolling(period).mean()


def calc_ema(df: pd.DataFrame, period: int) -> pd.Series:
    if _HAS_TA:
        return ta.ema(df["close"], length=period)
    return df["close"].ewm(span=period, adjust=False).mean()


def calc_bollinger(df: pd.DataFrame, period: int = 20, std: float = 2.0):
    """Returns (upper, mid, lower) as pd.Series tuple"""
    if _HAS_TA:
        bb = ta.bbands(df["close"], length=period, std=std)
        if bb is not None:
            upper = bb[f"BBU_{period}_{std}"]
            mid = bb[f"BBM_{period}_{std}"]
            lower = bb[f"BBL_{period}_{std}"]
            return upper, mid, lower
    mid = df["close"].rolling(period).mean()
    sd = df["close"].rolling(period).std()
    return mid + std * sd, mid, mid - std * sd


def calc_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9):
    """Returns (macd_line, signal_line, histogram) as pd.Series tuple"""
    if _HAS_TA:
        macd = ta.macd(df["close"], fast=fast, slow=slow, signal=signal)
        if macd is not None:
            return macd[f"MACD_{fast}_{slow}_{signal}"], macd[f"MACDs_{fast}_{slow}_{signal}"], macd[f"MACDh_{fast}_{slow}_{signal}"]
    ema_fast = calc_ema(df, fast)
    ema_slow = calc_ema(df, slow)
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    if _HAS_TA:
        return ta.atr(df["high"], df["low"], df["close"], length=period)
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def calc_donchian(df: pd.DataFrame, period: int = 20):
    """Returns (upper, lower) as pd.Series tuple"""
    if _HAS_TA:
        dc = ta.donchian(df["high"], df["low"], lower_length=period, upper_length=period)
        if dc is not None:
            upper = dc.get(f"DCU_{period}_{period}", df["high"].rolling(period).max())
            lower = dc.get(f"DCL_{period}_{period}", df["low"].rolling(period).min())
            return upper, lower
    return df["high"].rolling(period).max(), df["low"].rolling(period).min()


def is_new_high(df: pd.DataFrame, lookback: int = 260) -> bool:
    """52주 신고가 여부 (일봉 기준 약 260개 캔들)"""
    if len(df) < 2:
        return False
    current_close = df["close"].iloc[-1]
    past_high = df["close"].iloc[-(lookback + 1):-1].max() if len(df) > lookback else df["close"].iloc[:-1].max()
    return current_close > past_high


def avg_volume(df: pd.DataFrame, period: int = 20) -> float:
    return df["volume"].rolling(period).mean().iloc[-1]
