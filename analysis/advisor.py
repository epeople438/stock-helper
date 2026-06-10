"""
助手建议引擎 —— 把行情/指标/估值数据，翻译成普通股民看得懂的大白话建议。

设计原则：规则化、确定性（同样的数据每次结论一致）、可解释、不依赖 AI。
入口函数 build_advice() 返回一个 dict，包含持仓盈亏数字 + 四个维度的建议条目 +
一句话综合结论。每个建议条目带一个「级别」用于前端上色：
    好  → 偏正面    中 → 中性    差 → 偏负面    提醒 → 风险/操作提示

免责声明（DISCLAIMER）由前端固定展示：机械化解读，仅供参考，不构成投资建议。
"""

from datetime import date

import pandas as pd

DISCLAIMER = "以上为程序根据公开数据的机械化解读，仅供参考，不构成投资建议。"


def _safe_last(series: pd.Series):
    """取一列里最后一个非空值，没有则返回 None。"""
    s = series.dropna()
    return float(s.iloc[-1]) if not s.empty else None


def _fmt_money(x: float) -> str:
    """金额按「万/元」自适应显示，带正负号。"""
    if abs(x) >= 1e4:
        return f"{x/1e4:+.2f} 万元"
    return f"{x:+.0f} 元"


# ---------- 维度一：持仓盈亏与止盈止损 ----------
def _position_insights(df, df_since, buy_price, shares, hold_days, rsi_now):
    cur = float(df["close"].iloc[-1])
    pnl_pct = (cur - buy_price) / buy_price * 100
    pnl_amount = (cur - buy_price) * shares

    out = []
    verb = "浮盈" if pnl_pct >= 0 else "浮亏"
    level = "好" if pnl_pct >= 0 else "差"
    out.append({
        "dim": "持仓盈亏", "level": level,
        "text": (f"你 {hold_days} 天前以 {buy_price:.2f} 买入，现价 {cur:.2f}，"
                 f"{verb} {abs(pnl_pct):.1f}%（约 {_fmt_money(pnl_amount)}）。"),
    })

    # 买入后的最大回撤：只看买入日之后这段，价格从阶段最高点最多回落了多少
    after = df_since["close"]
    if len(after) > 1:
        running_max = after.cummax()
        drawdown = (after - running_max) / running_max
        max_dd = float(drawdown.min()) * 100
        if max_dd <= -10:
            out.append({
                "dim": "持仓盈亏", "level": "提醒",
                "text": f"持有以来一度从阶段高点回落约 {abs(max_dd):.0f}%，波动不小，留意自己的承受力。",
            })

    # 止损 / 止盈参考
    if pnl_pct <= -8:
        out.append({
            "dim": "持仓盈亏", "level": "提醒",
            "text": "目前浮亏已超 8%，建议想清楚自己的止损纪律，别让小亏拖成大亏。",
        })
    if pnl_pct >= 20 and rsi_now is not None and rsi_now >= 70:
        out.append({
            "dim": "持仓盈亏", "level": "提醒",
            "text": "浮盈可观且短期超买，可考虑分批止盈、落袋为安，别让利润坐过山车。",
        })

    return out, dict(current_price=cur, pnl_pct=pnl_pct, pnl_amount=pnl_amount)


# ---------- 维度二：技术信号解读 ----------
def _technical_insights(df):
    out = []
    cur = float(df["close"].iloc[-1])
    ma5, ma20, ma60 = (_safe_last(df[c]) for c in ("ma5", "ma20", "ma60"))

    # 均线多空排列
    if None not in (ma5, ma20, ma60):
        if ma5 > ma20 > ma60:
            out.append({"dim": "技术信号", "level": "好",
                        "text": "均线多头排列（5日>20日>60日），中短期趋势向上，做多氛围较好。"})
        elif ma5 < ma20 < ma60:
            out.append({"dim": "技术信号", "level": "差",
                        "text": "均线空头排列（5日<20日<60日），趋势偏弱，反弹更像是减仓机会而非加仓。"})
        else:
            out.append({"dim": "技术信号", "level": "中",
                        "text": "均线相互交织，多空不明朗，方向还在选择中，不必急于操作。"})
    # 相对 20 日线位置
    if ma20 is not None:
        if cur >= ma20:
            out.append({"dim": "技术信号", "level": "中",
                        "text": f"股价站在 20 日均线（{ma20:.2f}）上方，短期重心偏稳。"})
        else:
            out.append({"dim": "技术信号", "level": "中",
                        "text": f"股价跌破 20 日均线（{ma20:.2f}），短期承压，这条线常被当作多空分界。"})

    # MACD 金叉 / 死叉（看最近一根有没有刚发生交叉）
    dif, dea = df["dif"].dropna(), df["dea"].dropna()
    if len(dif) >= 2 and len(dea) >= 2:
        d_prev, d_now = dif.iloc[-2], dif.iloc[-1]
        e_prev, e_now = dea.iloc[-2], dea.iloc[-1]
        if d_prev <= e_prev and d_now > e_now:
            out.append({"dim": "技术信号", "level": "好",
                        "text": "MACD 刚形成金叉，短期动能由弱转强，常被视为偏积极的信号。"})
        elif d_prev >= e_prev and d_now < e_now:
            out.append({"dim": "技术信号", "level": "差",
                        "text": "MACD 刚形成死叉，短期动能转弱，注意上方抛压。"})

    # RSI 超买 / 超卖
    rsi_now = _safe_last(df["rsi14"])
    if rsi_now is not None:
        if rsi_now >= 70:
            out.append({"dim": "技术信号", "level": "提醒",
                        "text": f"RSI 已到 {rsi_now:.0f}，短期超买，情绪偏热，追高容易吃面。"})
        elif rsi_now <= 30:
            out.append({"dim": "技术信号", "level": "好",
                        "text": f"RSI 仅 {rsi_now:.0f}，短期超卖，可能酝酿反弹，但别贸然接飞刀。"})

    # 布林带位置
    bu, bl = _safe_last(df["boll_upper"]), _safe_last(df["boll_lower"])
    if bu is not None and cur >= bu:
        out.append({"dim": "技术信号", "level": "提醒",
                    "text": "股价触及布林带上轨，短期偏强但有回落压力，别在高位重仓追。"})
    elif bl is not None and cur <= bl:
        out.append({"dim": "技术信号", "level": "中",
                    "text": "股价触及布林带下轨，处于阶段低位，超跌后或有修复。"})

    return out, rsi_now, (ma5, ma20, ma60)


# ---------- 维度三：估值贵不贵 ----------
def _valuation_insights(valuation_df):
    """返回 (insights, 估值倾向)；倾向 ∈ {'便宜','适中','贵',None}。"""
    if valuation_df is None or valuation_df.empty or "pe_ttm" not in valuation_df:
        return [], None

    pe = valuation_df["pe_ttm"].dropna()
    cur_pe = _safe_last(valuation_df["pe_ttm"])
    if cur_pe is None or cur_pe <= 0 or len(pe) < 20:
        return ([{"dim": "估值", "level": "中",
                  "text": "当前市盈率不适用（可能亏损或数据不足），估值高低参考性有限。"}], None)

    # 当前 PE 在历史里的分位：越低越便宜
    pct = (pe <= cur_pe).mean() * 100
    if pct <= 30:
        tag, level, word = "便宜", "好", "偏低"
    elif pct >= 70:
        tag, level, word = "贵", "提醒", "偏高"
    else:
        tag, level, word = "适中", "中", "适中"
    return ([{"dim": "估值", "level": level,
              "text": (f"当前市盈率 {cur_pe:.1f}，处于自身历史约 {pct:.0f}% 分位，"
                       f"估值{word}（和它过去比{'更便宜' if tag=='便宜' else '更贵' if tag=='贵' else '差不多'}）。")}],
            tag)


# ---------- 一句话综合结论 ----------
def _summary(pnl_pct, ma_tuple, val_tag, buy_price):
    ma5, ma20, ma60 = ma_tuple
    if None not in (ma5, ma20, ma60):
        if ma5 > ma20 > ma60:
            trend = "趋势向上"
        elif ma5 < ma20 < ma60:
            trend = "趋势偏弱"
        else:
            trend = "趋势震荡"
    else:
        trend = "趋势数据不足"

    val_part = {"便宜": "估值不贵", "贵": "估值偏高", "适中": "估值适中"}.get(val_tag, "估值看不清")

    # 根据组合给一句带倾向的话
    if trend == "趋势向上" and val_tag in ("便宜", "适中"):
        action = "趋势与估值都不差，可继续持有、不必慌"
    elif trend == "趋势偏弱" and val_tag == "便宜":
        action = "短期弱但便宜，可耐心持有，跌破成本较多再考虑止损"
    elif trend == "趋势偏弱" and val_tag == "贵":
        action = "又弱又贵，性价比一般，反弹时注意控制仓位"
    elif trend == "趋势向上" and val_tag == "贵":
        action = "趋势好但已不便宜，可持有但别追高、设好止盈"
    else:
        action = "走势不明朗，少动多看，守住自己的成本线"

    return f"{trend}、{val_part}：{action}。"


# ---------- 对外入口 ----------
def build_advice(df: pd.DataFrame, valuation_df, buy_price: float,
                 buy_date: str, shares: int) -> dict:
    """
    生成完整建议。

    参数:
        df:           含指标的行情（ma/dif/dea/macd/rsi14/boll_*），来自 load_kline
        valuation_df: 估值历史（date, pe_ttm, pb），可为 None
        buy_price:    买入价
        buy_date:     "YYYY-MM-DD"
        shares:       股数

    返回 dict: current_price, pnl_pct, pnl_amount, hold_days, insights(list), summary, disclaimer
    """
    if df is None or df.empty:
        raise ValueError("没有行情数据，无法生成建议")

    try:
        bd = date.fromisoformat(buy_date)
        hold_days = max((date.today() - bd).days, 0)
    except ValueError:
        bd = None
        hold_days = 0

    # 买入日之后的那段行情，用于算「持有以来」的回撤
    if bd is not None and "date" in df:
        df_since = df[df["date"] >= pd.Timestamp(bd)]
        if df_since.empty:
            df_since = df
    else:
        df_since = df

    tech, rsi_now, ma_tuple = _technical_insights(df)
    pos, pos_metrics = _position_insights(df, df_since, buy_price, shares, hold_days, rsi_now)
    val, val_tag = _valuation_insights(valuation_df)
    summary = _summary(pos_metrics["pnl_pct"], ma_tuple, val_tag, buy_price)

    return {
        **pos_metrics,
        "hold_days": hold_days,
        "insights": pos + tech + val,
        "summary": summary,
        "disclaimer": DISCLAIMER,
    }
