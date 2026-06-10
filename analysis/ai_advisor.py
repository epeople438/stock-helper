"""
AI 深度解读 —— 调用 Claude（你自己的 Anthropic API Key）对持仓做更自然的解读。

定位：这是「给你自己用」的增强版解读，需要你配置 API Key 才会启用；
分享给朋友的版本若没配 Key，就只显示 advisor.py 的机械化解读，互不影响。

重要区别：
- claude.ai 的「订阅」(Pro/Max) 不能被程序调用；
- 程序调用需要 console.anthropic.com 的 **API Key**（单独按量计费，很便宜）。

技术要点：
- 用官方 anthropic SDK（httpx 后端）。
- api.anthropic.com 在国外，需要走代理；这里复用 net_setup 保存的原始代理地址，
  和「国内数据源必须直连」并行不悖。
- 配置（API Key / 模型 / 代理）存在本地 .ai_config.json，**不要分享这个文件**。
"""

import json
from pathlib import Path

import net_setup  # noqa: F401  复用其保存的 ORIGINAL_PROXY

_CONFIG_PATH = Path(__file__).resolve().parent.parent / ".ai_config.json"

# 可选模型：默认 Opus（解读最深），Sonnet 更快更省
MODELS = {
    "Claude Opus 4.8（最聪明）": "claude-opus-4-8",
    "Claude Sonnet 4.6（更快更省）": "claude-sonnet-4-6",
}

_SYSTEM_PROMPT = (
    "你是一位接地气的资深投资助理，面向不太懂术语的普通股民。"
    "你会把技术指标、估值、盈亏这些数据，翻译成大白话，帮他看懂自己持仓的处境。"
    "要求：1) 说人话，少用术语，必要时顺带解释；"
    "2) 有理有据，结论要落到给出的数据上，不要编造数据里没有的信息；"
    "3) 给出可操作的思考框架（比如关注哪个价位、什么情况该警惕），"
    "但不要下达『立刻买入/卖出』这种绝对指令；"
    "4) 语气稳重、不夸大、不画大饼，主动提示风险；"
    "5) 用中文，控制在 300 字以内，可用简短分段或要点。"
    "结尾不需要免责声明（程序会另外显示）。"
)


def load_config() -> dict:
    """读取本地 AI 配置；不存在返回默认值。"""
    cfg = {"api_key": "", "model": "claude-opus-4-8",
           "proxy": net_setup.ORIGINAL_PROXY}
    if _CONFIG_PATH.exists():
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def save_config(cfg: dict) -> None:
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def is_configured() -> bool:
    """是否已配置 API Key（决定要不要显示 AI 解读功能）。"""
    return bool(load_config().get("api_key", "").strip())


def _build_user_prompt(facts: dict, adv: dict) -> str:
    """把结构化数据拼成给 Claude 的输入。"""
    lines = [
        f"股票：{facts['name']}（{facts['market']} {facts['code']}）",
        f"我的持仓：买入价 {facts['buy_price']}，买入 {facts['hold_days']} 天，"
        f"股数 {facts['shares']}，现价 {facts['current_price']:.2f}，"
        f"浮动盈亏 {adv['pnl_pct']:+.1f}%（约 {adv['pnl_amount']:+.0f} 元）。",
        "",
        "技术面快照：",
        f"- 均线：MA5={facts.get('ma5')}, MA20={facts.get('ma20')}, MA60={facts.get('ma60')}",
        f"- RSI14={facts.get('rsi14')}（>70 超买 / <30 超卖）",
        f"- MACD：DIF={facts.get('dif')}, DEA={facts.get('dea')}",
        f"- 估值：当前 PE-TTM={facts.get('pe_ttm')}，历史分位 {facts.get('pe_percentile')}",
        "",
        "程序已算出的机械化提示（供你参考，可整合或纠正）：",
    ]
    for ins in adv["insights"]:
        lines.append(f"- [{ins['dim']}] {ins['text']}")
    lines.append("")
    lines.append("请基于以上数据，用大白话帮我解读这只股票现在的处境，并给出我该关注什么。")
    return "\n".join(lines)


def _round(x):
    """安全地把数值四舍五入，None/NaN 原样返回。"""
    try:
        if x is None or x != x:  # NaN
            return None
        return round(float(x), 2)
    except (TypeError, ValueError):
        return x


def _collect_facts(df, valuation_df, entry: dict, adv: dict) -> dict:
    """从行情/估值/持仓里抽出给 Claude 的关键事实。"""
    last = df.iloc[-1]
    pe_now = pe_pct = None
    if valuation_df is not None and not valuation_df.empty and "pe_ttm" in valuation_df:
        pe_series = valuation_df["pe_ttm"].dropna()
        if not pe_series.empty:
            pe_now = _round(pe_series.iloc[-1])
            if pe_now and pe_now > 0:
                pe_pct = f"{(pe_series <= pe_series.iloc[-1]).mean()*100:.0f}%"

    return {
        "name": entry.get("name") or entry["code"],
        "market": entry["market"], "code": entry["code"],
        "buy_price": entry["buy_price"], "shares": entry["shares"],
        "hold_days": adv["hold_days"], "current_price": adv["current_price"],
        "ma5": _round(last.get("ma5")), "ma20": _round(last.get("ma20")),
        "ma60": _round(last.get("ma60")), "rsi14": _round(last.get("rsi14")),
        "dif": _round(last.get("dif")), "dea": _round(last.get("dea")),
        "pe_ttm": pe_now, "pe_percentile": pe_pct,
    }


def build_chat_prompt(df, valuation_df, entry: dict) -> str:
    """
    生成一段「可直接复制粘贴到 claude.ai 网页聊天」的完整提示词（含角色说明+数据）。
    不需要 API Key——用户用自己的订阅手动发给 Claude 即可，免费。
    """
    from analysis.advisor import build_advice
    adv = build_advice(df, valuation_df, entry["buy_price"],
                       entry["buy_date"], entry["shares"])
    facts = _collect_facts(df, valuation_df, entry, adv)
    user_part = _build_user_prompt(facts, adv)
    return f"{_SYSTEM_PROMPT}\n\n———— 以下是我的持仓数据 ————\n\n{user_part}"


def ai_interpret(df, valuation_df, entry: dict, model: str,
                 api_key: str, proxy: str = "") -> str:
    """
    调用 Claude 生成深度解读，返回 Markdown 文本。

    参数:
        df:           含指标的行情（来自 load_kline）
        valuation_df: 估值历史（可为 None）
        entry:        自选股记录（market/code/name/buy_price/buy_date/shares）
        model:        模型 ID
        api_key:      Anthropic API Key
        proxy:        给 Anthropic 客户端用的代理（国外站点，通常需要）
    """
    import anthropic
    from analysis.advisor import build_advice

    # 先拿到机械化解读（数字 + 信号），作为给 Claude 的事实依据
    adv = build_advice(df, valuation_df, entry["buy_price"],
                       entry["buy_date"], entry["shares"])
    facts = _collect_facts(df, valuation_df, entry, adv)
    prompt = _build_user_prompt(facts, adv)

    # api.anthropic.com 在国外，通常要走代理；有代理就用，没有则直连
    if proxy:
        client = anthropic.Anthropic(
            api_key=api_key,
            http_client=anthropic.DefaultHttpxClient(proxy=proxy),
        )
    else:
        client = anthropic.Anthropic(api_key=api_key)

    msg = client.messages.create(
        model=model,
        max_tokens=1500,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in msg.content if b.type == "text")
