"""
基本面数据获取。第 3 阶段：估值（PE/PB 历史）+ 营收利润趋势。

现实情况：akshare 对 A股 的基本面数据最完整、最稳定，港股/美股的财报接口
字段杂乱且经常变动。所以本模块先把 A股 做扎实，港股/美股暂时抛出友好提示，
留待后续单独适配。所有函数返回规整后的 DataFrame，列名为英文/中文混合但固定。
"""

import net_setup  # noqa: F401  导入即关闭代理，必须在 akshare 之前

import akshare as ak
import pandas as pd


class NotSupportedYet(Exception):
    """该市场的基本面暂未支持，UI 捕获后给用户友好提示。"""


# 百度股市通的估值接口，三个市场各一个，参数完全一致
_VALUATION_FUNC = {
    "A股": "stock_zh_valuation_baidu",
    "港股": "stock_hk_valuation_baidu",
    "美股": "stock_us_valuation_baidu",
}


def _baidu_valuation(market: str, code: str, indicator: str, period: str) -> pd.DataFrame:
    """调一次百度估值接口，统一成两列：date + 指标值。"""
    fn = getattr(ak, _VALUATION_FUNC[market])
    raw = fn(symbol=code, indicator=indicator, period=period)
    # 返回通常是两列：日期 + 数值。这里不假设列名，按位置取，稳妥。
    raw = raw.iloc[:, :2].copy()
    raw.columns = ["date", "value"]
    raw["date"] = pd.to_datetime(raw["date"])
    raw["value"] = pd.to_numeric(raw["value"], errors="coerce")
    return raw


def get_valuation(market: str, code: str, period: str = "全部") -> pd.DataFrame:
    """
    估值历史。返回 DataFrame: date, pe_ttm, pb。
    数据来自百度股市通，A股 / 港股 / 美股都支持。
    分别取「市盈率(TTM)」和「市净率」两条曲线再按日期对齐。
    """
    if market not in _VALUATION_FUNC:
        raise NotSupportedYet(f"{market} 的估值历史暂未支持")

    pe = _baidu_valuation(market, code, "市盈率(TTM)", period).rename(
        columns={"value": "pe_ttm"})
    pb = _baidu_valuation(market, code, "市净率", period).rename(
        columns={"value": "pb"})

    df = pd.merge(pe, pb, on="date", how="outer")
    df = df.sort_values("date").reset_index(drop=True)
    return df


def get_revenue_profit(market: str, code: str) -> pd.DataFrame:
    """
    营收 / 净利润趋势。返回 DataFrame: period(报告期), 营业总收入_亿, 归母净利润_亿。
    目前仅 A股（数据来自同花顺财务摘要）。金额统一换算成「亿元」便于阅读。
    """
    if market != "A股":
        raise NotSupportedYet(f"{market} 的财报趋势暂未支持，目前仅 A股")

    raw = ak.stock_financial_abstract(symbol=code)
    # raw 形如：列 = ['选项','指标', '20240331', '20231231', ...]
    # 行按「指标」给出各财务科目；日期列是各报告期的值（单位：元）。
    date_cols = [c for c in raw.columns if c not in ("选项", "指标")]

    def pick(*keywords):
        """按指标名取一行，优先精确匹配，退而求其次用包含匹配。"""
        for kw in keywords:
            row = raw[raw["指标"] == kw]
            if not row.empty:
                return row.iloc[0]
        for kw in keywords:
            row = raw[raw["指标"].astype(str).str.contains(kw, na=False)]
            if not row.empty:
                return row.iloc[0]
        return None

    rev_row = pick("营业总收入", "营业收入")
    prof_row = pick("归母净利润", "净利润")
    if rev_row is None and prof_row is None:
        raise ValueError("没解析到营收/利润字段，数据源结构可能变了")

    records = []
    for c in date_cols:
        rev = pd.to_numeric(rev_row[c], errors="coerce") if rev_row is not None else None
        prof = pd.to_numeric(prof_row[c], errors="coerce") if prof_row is not None else None
        records.append({
            "period": pd.to_datetime(c, format="%Y%m%d", errors="coerce"),
            "营业总收入_亿": rev / 1e8 if rev is not None else None,
            "归母净利润_亿": prof / 1e8 if prof is not None else None,
        })

    df = pd.DataFrame(records).dropna(subset=["period"])
    df = df.sort_values("period").reset_index(drop=True)
    return df
