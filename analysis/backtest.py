"""
策略回测 —— 用历史数据验证「某个买卖策略能不能赚钱」，并和「买入持有」对比。

提供三个经典策略，都很好理解：
  1. 双均线交叉：短均线上穿长均线买入，下穿卖出（趋势跟随）
  2. MACD 金叉死叉：DIF 上穿 DEA 买入，下穿卖出
  3. RSI 超卖超买：RSI 跌破 30 买入，涨破 70 卖出（高抛低吸）

核心是一个通用引擎 backtest()：给定每天的「持仓信号」（1=持有，0=空仓），
算出策略的资金曲线、总收益、最大回撤、交易次数、胜率，并和买入持有对比。

防作弊（避免「未来函数」）：信号当天产生，第二天才按收盘价成交（position.shift(1)）。
"""

import numpy as np
import pandas as pd


# ---------- 三个策略：输入行情，输出每日持仓信号 Series(0/1) ----------

def signal_ma_cross(df: pd.DataFrame, short: int = 5, long: int = 20) -> pd.Series:
    """双均线交叉：短均线在长均线上方时持有（1），否则空仓（0）。"""
    ma_s = df["close"].rolling(short).mean()
    ma_l = df["close"].rolling(long).mean()
    return (ma_s > ma_l).astype(int)


def signal_macd(df: pd.DataFrame) -> pd.Series:
    """MACD：DIF 在 DEA 上方时持有。需要 df already 含 dif/dea 列。"""
    return (df["dif"] > df["dea"]).astype(int)


def signal_rsi(df: pd.DataFrame, low: int = 30, high: int = 70) -> pd.Series:
    """
    RSI 超卖超买（有状态）：RSI 跌破 low 买入并持有，直到涨破 high 卖出。
    需要 df 含 rsi14 列。
    """
    rsi = df["rsi14"]
    pos = []
    holding = 0
    for v in rsi:
        if np.isnan(v):
            pos.append(0)
            continue
        if holding == 0 and v < low:
            holding = 1
        elif holding == 1 and v > high:
            holding = 0
        pos.append(holding)
    return pd.Series(pos, index=df.index)


# ---------- 通用回测引擎 ----------

def backtest(df: pd.DataFrame, position: pd.Series) -> dict:
    """
    根据持仓信号回测。

    参数:
        df:       含 date, close 的行情
        position: 每日持仓信号 Series(0/1)，与 df 对齐

    返回 dict:
        equity_df: 含 date, 策略净值, 买入持有净值
        trades:    每笔交易明细列表
        stats:     汇总指标（策略总收益/买入持有收益/最大回撤/交易次数/胜率/超额）
    """
    data = df[["date", "close"]].copy()
    data["ret"] = data["close"].pct_change().fillna(0)
    # 信号当天生成、次日成交，避免用到「未来」的信息
    data["pos"] = position.shift(1).fillna(0).values
    data["strat_ret"] = data["ret"] * data["pos"]

    data["策略净值"] = (1 + data["strat_ret"]).cumprod()
    data["买入持有净值"] = (1 + data["ret"]).cumprod()

    # 最大回撤（策略）
    roll_max = data["策略净值"].cummax()
    drawdown = data["策略净值"] / roll_max - 1
    max_dd = float(drawdown.min())

    # 拆出每一笔交易（持仓从 0→1 进场，1→0 出场）
    trades = []
    entry_idx = None
    pos_arr = data["pos"].values
    for i in range(len(data)):
        if pos_arr[i] == 1 and (i == 0 or pos_arr[i - 1] == 0):
            entry_idx = i
        elif pos_arr[i] == 0 and i > 0 and pos_arr[i - 1] == 1 and entry_idx is not None:
            ep, xp = data["close"].iloc[entry_idx], data["close"].iloc[i]
            trades.append({
                "买入日": data["date"].iloc[entry_idx].date(),
                "买入价": round(float(ep), 2),
                "卖出日": data["date"].iloc[i].date(),
                "卖出价": round(float(xp), 2),
                "收益率": round((xp / ep - 1) * 100, 2),
            })
            entry_idx = None
    # 还没平仓的最后一笔，按最新价浮动结算
    if entry_idx is not None:
        ep, xp = data["close"].iloc[entry_idx], data["close"].iloc[-1]
        trades.append({
            "买入日": data["date"].iloc[entry_idx].date(),
            "买入价": round(float(ep), 2),
            "卖出日": data["date"].iloc[-1].date(),
            "卖出价": round(float(xp), 2),
            "收益率": round((xp / ep - 1) * 100, 2),
        })

    wins = [t for t in trades if t["收益率"] > 0]
    strat_total = float(data["策略净值"].iloc[-1] - 1)
    bh_total = float(data["买入持有净值"].iloc[-1] - 1)

    stats = {
        "策略总收益": strat_total * 100,
        "买入持有收益": bh_total * 100,
        "超额收益": (strat_total - bh_total) * 100,
        "最大回撤": max_dd * 100,
        "交易次数": len(trades),
        "胜率": (len(wins) / len(trades) * 100) if trades else 0.0,
    }

    return {
        "equity_df": data[["date", "策略净值", "买入持有净值"]],
        "trades": trades,
        "stats": stats,
    }


# ---------- 策略注册表（给界面用，键是中文显示名）----------
STRATEGIES = {
    "双均线交叉": "ma",
    "平滑异同均线金叉死叉": "macd",
    "相对强弱超买超卖": "rsi",
}


def run(df: pd.DataFrame, strategy: str, **params) -> dict:
    """按策略名分发，生成信号并回测。"""
    if strategy == "ma":
        pos = signal_ma_cross(df, params.get("short", 5), params.get("long", 20))
    elif strategy == "macd":
        pos = signal_macd(df)
    elif strategy == "rsi":
        pos = signal_rsi(df, params.get("low", 30), params.get("high", 70))
    else:
        raise ValueError(f"未知策略: {strategy}")
    return backtest(df, pos)
