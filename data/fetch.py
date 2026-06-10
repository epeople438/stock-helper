"""
数据获取层 —— 封装 akshare，统一三个市场（A股 / 港股 / 美股）的行情接口。

对外只暴露一个函数 get_kline()，调用方不用关心底层用的哪个 akshare 接口。
返回的 DataFrame 列名统一为英文：date, open, close, high, low, volume。

健壮性设计：
- 每个数据源调用都带「自动重试」（应对东方财富等接口的偶发性掐断 RemoteDisconnected）。
- 每个市场都准备「主源 + 备用源」，主源连续失败就自动切换到备用源。
  A股：东方财富 → 腾讯；港股 / 美股：东方财富 → 新浪。
"""

import time

import net_setup  # noqa: F401  导入即关闭代理，必须在 akshare 之前

import akshare as ak
import pandas as pd
import requests


# akshare 各接口返回的列名是中文/英文不一，这里统一映射成英文
_COLUMN_MAP = {
    "日期": "date", "开盘": "open", "收盘": "close",
    "最高": "high", "最低": "low", "成交量": "volume",
}

# 这些是「连接类」异常，遇到才重试；数据为空之类的逻辑错误不重试
_RETRYABLE = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


def _retry(func, *args, attempts=4, base_delay=0.8, **kwargs):
    """对单个数据源调用做自动重试：连接类报错时等待递增后重试，最多 attempts 次。"""
    last_err = None
    for i in range(attempts):
        try:
            return func(*args, **kwargs)
        except _RETRYABLE as e:
            last_err = e
            time.sleep(base_delay * (i + 1))  # 0.8s, 1.6s, 2.4s …
    raise last_err


def _normalize(df: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    """
    把各数据源返回的 DataFrame 统一成英文列、按日期排序、并裁到指定区间。
    兼容中文列名和英文列名；没有成交量的源用成交额或 0 兜底（不影响 K 线）。
    """
    df = df.rename(columns=_COLUMN_MAP)
    if "volume" not in df.columns:
        for alt in ("成交额", "amount", "turnover"):
            if alt in df.columns:
                df = df.rename(columns={alt: "volume"})
                break
    if "volume" not in df.columns:
        df["volume"] = 0

    required = ["date", "open", "close", "high", "low"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"数据源返回的列不认识，缺少 {missing}；实际列={list(df.columns)}")

    df = df[["date", "open", "close", "high", "low", "volume"]].copy()
    df["date"] = pd.to_datetime(df["date"])
    # 裁剪到用户选的时间区间（新浪等源不支持按区间查，统一在这里裁）
    s = pd.to_datetime(start_date, format="%Y%m%d")
    e = pd.to_datetime(end_date, format="%Y%m%d")
    df = df[(df["date"] >= s) & (df["date"] <= e)]
    df = df.sort_values("date").reset_index(drop=True)
    return df


def _resolve_us_symbol(ticker: str) -> str:
    """美股东方财富接口需要 105.AAPL 这种格式，用户只输 AAPL，这里查全市场列表补全。"""
    ticker = ticker.strip().upper()
    spot = _retry(ak.stock_us_spot_em)
    matched = spot[spot["代码"].str.split(".").str[-1] == ticker]
    if matched.empty:
        raise ValueError(f"没找到美股代码 {ticker}，请确认拼写（例：AAPL、TSLA、NVDA）")
    return matched.iloc[0]["代码"]


def _a_share_prefixed(code: str) -> str:
    """A股 6 位代码加交易所前缀，供腾讯/新浪源使用：sh / sz / bj。"""
    if code[0] in "69":
        return "sh" + code
    if code[0] in "48":
        return "bj" + code
    return "sz" + code


# ---------- 各市场的「主源 / 备用源」获取函数 ----------
# 每个函数返回「未规整」的原始 DataFrame，规整交给 _normalize 统一处理。

def _a_primary(code, s, e, adjust):       # 东方财富
    return _retry(ak.stock_zh_a_hist, symbol=code, period="daily",
                  start_date=s, end_date=e, adjust=adjust, timeout=15)

def _a_backup(code, s, e, adjust):        # 腾讯
    return _retry(ak.stock_zh_a_hist_tx, symbol=_a_share_prefixed(code),
                  start_date=s, end_date=e, adjust=adjust)

def _hk_primary(code, s, e, adjust):      # 东方财富
    return _retry(ak.stock_hk_hist, symbol=code, period="daily",
                  start_date=s, end_date=e, adjust=adjust)

def _hk_backup(code, s, e, adjust):       # 新浪（返回全历史，区间由 _normalize 裁）
    return _retry(ak.stock_hk_daily, symbol=code, adjust=adjust)

def _us_primary(code, s, e, adjust):      # 东方财富
    return _retry(ak.stock_us_hist, symbol=_resolve_us_symbol(code), period="daily",
                  start_date=s, end_date=e, adjust=adjust)

def _us_backup(code, s, e, adjust):       # 新浪（用纯代码，返回全历史）
    return _retry(ak.stock_us_daily, symbol=code.strip().upper(), adjust=adjust)


_SOURCES = {
    "A股": (_a_primary, _a_backup),
    "港股": (_hk_primary, _hk_backup),
    "美股": (_us_primary, _us_backup),
}


def get_kline(market: str, code: str, start_date: str, end_date: str,
              adjust: str = "qfq") -> pd.DataFrame:
    """
    获取日 K 线数据。先试主源（带重试），失败再试备用源。

    参数:
        market: "A股" | "港股" | "美股"
        code:   A股6位(如 600519) / 港股5位(如 00700) / 美股代码(如 AAPL)
        start_date, end_date: "YYYYMMDD"
        adjust: "qfq"前复权 / "hfq"后复权 / ""不复权

    返回: DataFrame，列为 date, open, close, high, low, volume
    """
    code = code.strip()
    if market not in _SOURCES:
        raise ValueError(f"未知市场: {market}")

    primary, backup = _SOURCES[market]
    errors = []
    for name, src in (("主源", primary), ("备用源", backup)):
        try:
            df = src(code, start_date, end_date, adjust)
            if df is None or df.empty:
                raise ValueError("返回空数据")
            return _normalize(df, start_date, end_date)
        except Exception as e:  # 主源失败就接着试备用源
            errors.append(f"{name}: {type(e).__name__} {e}")

    raise ValueError(
        f"{market} {code} 两个数据源都没取到数据，请检查代码/日期，或稍后再试。\n"
        + "\n".join(errors)
    )
