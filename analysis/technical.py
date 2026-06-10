"""
技术指标计算。MVP 先实现均线（MA），后续阶段在这里继续加 MACD / RSI / 布林带。
所有函数都接收 get_kline() 返回的标准 DataFrame，返回新增指标列的 DataFrame。
"""

import pandas as pd


def add_moving_averages(df: pd.DataFrame, windows=(5, 20, 60)) -> pd.DataFrame:
    """
    给行情 DataFrame 增加若干条移动平均线列，如 ma5, ma20, ma60。

    参数:
        df: 含 close 列的行情数据
        windows: 要计算的均线周期，默认 5/20/60 日
    """
    df = df.copy()
    for w in windows:
        df[f"ma{w}"] = df["close"].rolling(window=w).mean()
    return df


def add_macd(df: pd.DataFrame, fast=12, slow=26, signal=9) -> pd.DataFrame:
    """
    增加 MACD 指标，新增三列：
        dif   = 快线EMA - 慢线EMA（短期与长期的差）
        dea   = dif 的 signal 日 EMA（信号线）
        macd  = (dif - dea) * 2（柱状图，俗称红绿柱）

    用法直觉：dif 上穿 dea（金叉）偏多，下穿（死叉）偏空；柱由绿转红是动能转强。
    """
    df = df.copy()
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    df["dif"] = ema_fast - ema_slow
    df["dea"] = df["dif"].ewm(span=signal, adjust=False).mean()
    df["macd"] = (df["dif"] - df["dea"]) * 2
    return df


def add_rsi(df: pd.DataFrame, period=14) -> pd.DataFrame:
    """
    增加 RSI 相对强弱指标，新增一列 rsi{period}（默认 rsi14）。
    取值 0~100：常以 >70 视为超买、<30 视为超卖。
    用 Wilder 平滑（指数加权）计算，与多数行情软件一致。
    """
    df = df.copy()
    delta = df["close"].diff()
    gain = delta.clip(lower=0)        # 上涨幅度，下跌记 0
    loss = -delta.clip(upper=0)       # 下跌幅度（取正），上涨记 0
    # Wilder 平滑：等价于 alpha = 1/period 的指数移动平均
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    df[f"rsi{period}"] = 100 - 100 / (1 + rs)
    return df


def add_bollinger(df: pd.DataFrame, window=20, num_std=2) -> pd.DataFrame:
    """
    增加布林带，新增三列：
        boll_mid   = 中轨（window 日均线）
        boll_upper = 上轨（中轨 + num_std 倍标准差）
        boll_lower = 下轨（中轨 - num_std 倍标准差）

    直觉：价格多在上下轨之间波动，触上轨偏强/触下轨偏弱，带宽收窄常预示变盘。
    """
    df = df.copy()
    mid = df["close"].rolling(window=window).mean()
    std = df["close"].rolling(window=window).std()
    df["boll_mid"] = mid
    df["boll_upper"] = mid + num_std * std
    df["boll_lower"] = mid - num_std * std
    return df
