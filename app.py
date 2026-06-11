"""
股票分析程序 —— 主入口（Streamlit 网页应用）

运行方式（在项目目录下）:
    streamlit run app.py
或直接双击 运行.command

第 3 阶段：分「技术分析」「基本面」两个标签页。
- 技术分析：K线 + 均线 + 布林带 + MACD + RSI（侧边栏勾选）
- 基本面：估值（PE-TTM / PB 历史）+ 营收利润趋势（目前 A股）
"""

from datetime import date, timedelta
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from data.fetch import get_kline
from analysis.technical import (
    add_moving_averages, add_macd, add_rsi, add_bollinger,
)
from analysis.fundamental import (
    get_valuation, get_revenue_profit, NotSupportedYet,
)
from analysis.advisor import build_advice
import analysis.ai_advisor as ai_advisor
import analysis.backtest as backtest
import json
import uuid
from streamlit_local_storage import LocalStorage


# ---------- 页面基础设置 ----------
st.set_page_config(page_title="股票分析助手", page_icon="📈", layout="wide")

# 全局样式：仿 Claude 的温暖克制风 —— 奶白底、陶土点缀、衬线标题、留白充足
st.markdown("""
<style>
:root { --clay:#C96442; --cream:#FAF9F5; --sand:#F0EEE6; --line:#E8E2D4;
        --ink:#29261B; --muted:#7A7363; }

.block-container { padding: 1.6rem 2.8rem 3rem 2.8rem !important; max-width: 1180px; }

/* 顶部标题：克制的奶白卡片 + 衬线大字 + 一条陶土细线 */
.app-header {
    background: var(--cream); border: 1px solid var(--line);
    border-left: 4px solid var(--clay);
    border-radius: 14px; padding: 20px 26px; margin-bottom: 22px;
}
.app-header h1 {
    margin: 0; font-size: 1.75rem; font-weight: 600; color: var(--ink);
    font-family: 'Georgia', 'Songti SC', 'Times New Roman', serif;
}
.app-header p { margin: 8px 0 0; color: var(--muted); font-size: .95rem; }

/* 指标：浅米卡片、细边、几乎无阴影，安静 */
[data-testid="stMetric"] {
    background: #fff; border: 1px solid var(--line); border-radius: 12px;
    padding: 14px 16px;
}
[data-testid="stMetricLabel"] p { font-size: .82rem; color: var(--muted); }
[data-testid="stMetricValue"] { font-size: 1.35rem; font-weight: 600; color: var(--ink); }

/* 标签页：下划线式，选中陶土色 */
.stTabs [data-baseweb="tab-list"] { gap: 4px; border-bottom: 1px solid var(--line); }
.stTabs [data-baseweb="tab"] {
    height: 42px; padding: 0 16px; font-size: .98rem; font-weight: 600;
    color: var(--muted);
}
.stTabs [aria-selected="true"] { color: var(--clay); }
.stTabs [data-baseweb="tab-highlight"] { background: var(--clay); }

/* 按钮：圆润 */
.stButton > button { border-radius: 10px; font-weight: 600; }
.stButton > button[kind="primary"] { box-shadow: none; }

/* 输入框/下拉框：圆角 + 内部留白，文字不贴边 */
[data-baseweb="input"], [data-baseweb="select"] > div,
.stTextInput div[data-baseweb="base-input"],
.stNumberInput div[data-baseweb="base-input"],
.stDateInput div[data-baseweb="input"] {
    border-radius: 10px !important;
}
.stTextInput input, .stNumberInput input, .stDateInput input,
.stSelectbox div[data-baseweb="select"] div {
    padding-left: 0.7rem !important; padding-right: 0.7rem !important;
}
/* 输入框上方的小标题留点距离 */
.stTextInput label, .stNumberInput label, .stDateInput label,
.stSelectbox label, .stRadio label { margin-bottom: .15rem; }

/* 标题用衬线，呼应 Claude 编辑感 */
h2, h3 { font-family: 'Georgia','Songti SC',serif; font-weight: 600; color: var(--ink); }

/* 持仓卡片：柔和细边 */
[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 14px; border-color: var(--line) !important; background:#fff;
}
/* 侧栏：加宽 + 内容四周留足边距，别贴边 */
section[data-testid="stSidebar"] { border-right: 1px solid var(--line); min-width: 350px; }
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"],
section[data-testid="stSidebar"] [data-testid="stSidebarContent"],
section[data-testid="stSidebar"] > div:first-child {
    padding-left: 1.6rem !important; padding-right: 1.6rem !important;
}
[data-testid="stSidebar"] h2 { font-size: 1.05rem; }
[data-testid="stSidebar"] label p { font-size: .92rem; }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="app-header">
  <h1>📈 股票分析助手</h1>
  <p>港股 · 美股 · A股 &nbsp;|&nbsp; 看图 · 读财报 · 管自选 · 做回测，你的私人投资小助理</p>
</div>
""", unsafe_allow_html=True)


def _secret(key: str, default: str = "") -> str:
    """安全读取 secret：没有 secrets.toml 时直接返回默认值，避免本地报红。"""
    locs = [Path.home() / ".streamlit" / "secrets.toml",
            Path(__file__).resolve().parent / ".streamlit" / "secrets.toml"]
    if not any(p.exists() for p in locs):
        return default
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


def _gate() -> str:
    """
    访问暗号 + 用户名门禁。返回当前用户名（用于区分各自的自选股）。
    - 部署到云端：在 st.secrets 设 APP_PASSCODE 后启用门禁（输对暗号+填名字才进）。
    - 本地运行：没设 APP_PASSCODE 就不拦，用户名默认「本地」。
    """
    passcode = _secret("APP_PASSCODE", "")

    if not passcode:                       # 本地/未配置：直接放行
        return st.session_state.get("user", "本地")

    if st.session_state.get("authed"):
        return st.session_state["user"]

    st.markdown("#### 🔒 请输入访问暗号")
    with st.form("gate"):
        name = st.text_input("你的名字（可选）", placeholder="只用于打招呼，如 张三")
        pw = st.text_input("访问暗号", type="password")
        if st.form_submit_button("进入", type="primary"):
            if pw == passcode:
                st.session_state.authed = True
                st.session_state.user = name.strip() or "我"
                st.rerun()
            else:
                st.error("暗号不对")
    st.stop()


CURRENT_USER = _gate()


def copy_box(text: str, height: int = 300):
    """带醒目「复制全部」按钮的文本框，比 st.code 更好找、自动换行。"""
    safe = (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;"))
    components.html(f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
      <button id="cpbtn" onclick="
        var t=document.getElementById('cpta');
        t.focus(); t.select(); t.setSelectionRange(0,999999);
        var ok=false;
        try {{ ok=document.execCommand('copy'); }} catch(e) {{}}
        if (navigator.clipboard) {{ try {{ navigator.clipboard.writeText(t.value); ok=true; }} catch(e) {{}} }}
        var b=document.getElementById('cpbtn');
        b.innerText = ok ? '✅ 已复制，去 AI 对话框粘贴吧' : '⚠️ 请手动全选复制';
        setTimeout(function(){{b.innerText='📋 复制全部';}},1800);"
        style="background:#C96442;color:#fff;border:none;border-radius:10px;
               padding:10px 18px;font-size:.95rem;font-weight:700;cursor:pointer;
               margin-bottom:8px;box-shadow:0 2px 8px rgba(201,100,66,.22);">
        📋 复制全部
      </button>
      <textarea id="cpta" readonly
        style="width:100%;height:{height-60}px;box-sizing:border-box;padding:12px;
               border:1px solid #E8E2D4;border-radius:10px;background:#FAF9F5;
               font-size:.86rem;line-height:1.5;color:#29261B;resize:vertical;
               white-space:pre-wrap;">{safe}</textarea>
    </div>
    """, height=height)


# ---------- 数据获取（带缓存，避免重复请求） ----------
@st.cache_data(ttl=3600, show_spinner="正在拉取行情数据…")
def load_kline(market, code, start, end):
    df = get_kline(market, code, start, end)
    df = add_moving_averages(df, windows=(5, 20, 60))
    df = add_macd(df)
    df = add_rsi(df, period=14)
    df = add_bollinger(df, window=20, num_std=2)
    return df


@st.cache_data(ttl=3600, show_spinner="正在拉取估值数据…")
def load_valuation(market, code):
    return get_valuation(market, code)


@st.cache_data(ttl=3600, show_spinner="正在拉取财报数据…")
def load_revenue_profit(market, code):
    return get_revenue_profit(market, code)


# ---------- 侧边栏：输入区 ----------
with st.sidebar:
    st.header("查询条件")
    market = st.radio("市场", ["A股", "港股", "美股"], horizontal=True)

    placeholder = {"A股": "如 600519", "港股": "如 00700", "美股": "如 AAPL"}[market]
    code = st.text_input("股票代码", placeholder=placeholder)

    today = date.today()
    start = st.date_input("开始日期", today - timedelta(days=365))
    end = st.date_input("结束日期", today)

    st.divider()
    st.subheader("技术指标")
    show_ma = st.checkbox("均线（5/20/60日）", value=True)
    show_boll = st.checkbox("布林带", value=False)
    show_macd = st.checkbox("平滑异同均线", value=True)
    show_rsi = st.checkbox("相对强弱指标", value=False)

    go_btn = st.button("查询", type="primary", use_container_width=True)


# ---------- 子函数：画技术分析图 ----------
def render_technical(df):
    rows = [("price", 0.5), ("volume", 0.16)]
    if show_macd:
        rows.append(("macd", 0.17))
    if show_rsi:
        rows.append(("rsi", 0.17))

    row_index = {name: i + 1 for i, (name, _) in enumerate(rows)}
    fig = make_subplots(
        rows=len(rows), cols=1, shared_xaxes=True,
        row_heights=[h for _, h in rows], vertical_spacing=0.04,
    )

    pr = row_index["price"]
    fig.add_trace(
        go.Candlestick(
            x=df["date"], open=df["open"], high=df["high"],
            low=df["low"], close=df["close"], name="K线",
            increasing_line_color="red", decreasing_line_color="green",
        ),
        row=pr, col=1,
    )

    if show_ma:
        for w, color in [(5, "orange"), (20, "blue"), (60, "purple")]:
            fig.add_trace(
                go.Scatter(x=df["date"], y=df[f"ma{w}"], name=f"MA{w}",
                           line=dict(width=1, color=color)),
                row=pr, col=1,
            )

    if show_boll:
        fig.add_trace(
            go.Scatter(x=df["date"], y=df["boll_upper"], name="BOLL上轨",
                       line=dict(width=1, color="gray", dash="dot")),
            row=pr, col=1,
        )
        fig.add_trace(
            go.Scatter(x=df["date"], y=df["boll_lower"], name="BOLL下轨",
                       line=dict(width=1, color="gray", dash="dot"),
                       fill="tonexty", fillcolor="rgba(128,128,128,0.08)"),
            row=pr, col=1,
        )
        fig.add_trace(
            go.Scatter(x=df["date"], y=df["boll_mid"], name="BOLL中轨",
                       line=dict(width=1, color="brown")),
            row=pr, col=1,
        )

    fig.add_trace(
        go.Bar(x=df["date"], y=df["volume"], name="成交量",
               marker_color="lightgray"),
        row=row_index["volume"], col=1,
    )

    if show_macd:
        mr = row_index["macd"]
        colors = ["red" if v >= 0 else "green" for v in df["macd"]]
        fig.add_trace(
            go.Bar(x=df["date"], y=df["macd"], name="MACD柱",
                   marker_color=colors),
            row=mr, col=1,
        )
        fig.add_trace(
            go.Scatter(x=df["date"], y=df["dif"], name="DIF",
                       line=dict(width=1, color="black")),
            row=mr, col=1,
        )
        fig.add_trace(
            go.Scatter(x=df["date"], y=df["dea"], name="DEA",
                       line=dict(width=1, color="orange")),
            row=mr, col=1,
        )

    if show_rsi:
        rr = row_index["rsi"]
        fig.add_trace(
            go.Scatter(x=df["date"], y=df["rsi14"], name="RSI14",
                       line=dict(width=1, color="purple")),
            row=rr, col=1,
        )
        fig.add_hline(y=70, line=dict(color="red", width=1, dash="dash"),
                      row=rr, col=1)
        fig.add_hline(y=30, line=dict(color="green", width=1, dash="dash"),
                      row=rr, col=1)

    fig.update_layout(
        height=300 + 170 * (len(rows) - 1),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(t=30, b=20),
    )
    st.plotly_chart(fig, use_container_width=True)

    last = df.iloc[-1]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("最新收盘", f"{last['close']:.2f}")
    c2.metric("最高", f"{last['high']:.2f}")
    c3.metric("最低", f"{last['low']:.2f}")
    c4.metric("相对强弱指标", f"{last['rsi14']:.1f}" if last["rsi14"] == last["rsi14"] else "—")

    with st.expander("查看原始数据表"):
        st.dataframe(df, use_container_width=True)


# ---------- 子函数：画基本面 ----------
def render_fundamental():
    # 估值历史
    st.subheader("估值历史（PE-TTM / PB）")
    try:
        val = load_valuation(market, code)
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(
            go.Scatter(x=val["date"], y=val["pe_ttm"], name="PE-TTM",
                       line=dict(color="blue")),
            secondary_y=False,
        )
        fig.add_trace(
            go.Scatter(x=val["date"], y=val["pb"], name="PB",
                       line=dict(color="orange")),
            secondary_y=True,
        )
        fig.update_yaxes(title_text="PE-TTM", secondary_y=False)
        fig.update_yaxes(title_text="PB", secondary_y=True)
        fig.update_layout(height=350, margin=dict(t=20, b=20),
                          legend=dict(orientation="h", y=1.05))
        st.plotly_chart(fig, use_container_width=True)

        # 取最后一个「有效（非空）」值作为当前值，避免末行恰好缺值显示 —
        def last_valid(col):
            s = val[col].dropna()
            return s.iloc[-1] if not s.empty else None
        pe_now, pb_now = last_valid("pe_ttm"), last_valid("pb")
        c1, c2 = st.columns(2)
        c1.metric("当前 PE-TTM", f"{pe_now:.1f}" if pe_now is not None else "—")
        c2.metric("当前 PB", f"{pb_now:.2f}" if pb_now is not None else "—")
    except NotSupportedYet as e:
        st.info(f"ℹ️ {e}（后续迭代会补上港股/美股）")
    except Exception as e:
        st.error(f"估值数据获取失败：{e}")

    st.divider()

    # 营收利润趋势
    st.subheader("营收 / 净利润趋势（亿元）")
    try:
        rp = load_revenue_profit(market, code)
        fig = go.Figure()
        fig.add_trace(go.Bar(x=rp["period"], y=rp["营业总收入_亿"],
                             name="营业总收入", marker_color="steelblue"))
        fig.add_trace(go.Bar(x=rp["period"], y=rp["归母净利润_亿"],
                             name="归母净利润", marker_color="indianred"))
        fig.update_layout(height=350, barmode="group", margin=dict(t=20, b=20),
                          legend=dict(orientation="h", y=1.05))
        st.plotly_chart(fig, use_container_width=True)

        with st.expander("查看财报数据表"):
            st.dataframe(rp, use_container_width=True)
    except NotSupportedYet as e:
        st.info(f"ℹ️ {e}（后续迭代会补上港股/美股）")
    except Exception as e:
        st.error(f"财报数据获取失败：{e}")


# ---------- 子函数：自选股 + 助手建议 ----------
_LEVEL_ICON = {"好": "🟢", "中": "⚪", "差": "🔴", "提醒": "⚠️"}


def _fmt_cny(x: float) -> str:
    """金额紧凑显示：大于等于 1 万用「万元」，否则用「元」，都带正负号。"""
    if abs(x) >= 1e8:
        return f"{x/1e8:+.2f} 亿"
    if abs(x) >= 1e4:
        return f"{x/1e4:+.2f} 万"
    return f"{x:+,.0f} 元"


# ---------- 自选股存储：浏览器本地 Local Storage（各人各看各的，不需数据库）----------
_WL_KEY = "stock_watchlist_v1"


def _wl_load(ls):
    """
    读取自选股：只在「本次会话首次」从浏览器本地存储加载一次，之后一律以内存(session)为准。
    这样异步的 getItem 不会把刚加/刚删的结果覆盖掉，也避免反复读取。
    """
    if "wl_items" not in st.session_state:
        raw = ls.getItem(_WL_KEY)        # 组件首帧未挂载会是 None
        if raw is None:
            return []                    # 还没加载好，先返回空；组件挂载后会自动重跑再读
        try:
            v = json.loads(raw) if raw else []
        except Exception:
            v = []
        st.session_state["wl_items"] = v if isinstance(v, list) else []
    return st.session_state["wl_items"]


def _wl_save(ls, items):
    """写回内存(立即生效) + 浏览器本地存储(后台异步写入，本次渲染不能被 rerun 打断)。"""
    st.session_state["wl_items"] = items
    ls.setItem(_WL_KEY, json.dumps(items, ensure_ascii=False))


def _wl_add(ls, market, code, name, buy_date, buy_price, shares):
    items = list(_wl_load(ls))
    items.append({
        "id": uuid.uuid4().hex, "market": market, "code": code.strip(),
        "name": (name or "").strip(), "buy_date": buy_date,
        "buy_price": float(buy_price), "shares": int(shares),
    })
    _wl_save(ls, items)


def _wl_remove(ls, entry_id):
    _wl_save(ls, [e for e in _wl_load(ls) if e.get("id") != entry_id])


def render_watchlist():
    ls = LocalStorage(key="wl_store")
    # 先处理上一轮点的「删除」：放在渲染列表之前，删完不 rerun，让本地存储写入正常完成
    pending = st.session_state.pop("wl_pending_delete", None)
    if pending:
        _wl_remove(ls, pending)

    st.subheader("➕ 添加自选股")
    with st.form("add_watchlist", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        m = c1.selectbox("市场", ["A股", "港股", "美股"])
        code_in = c2.text_input("代码", placeholder="如 600519 / 00700 / AAPL")
        name_in = c3.text_input("名称（可选）", placeholder="如 贵州茅台")
        c4, c5, c6 = st.columns(3)
        buy_date_in = c4.date_input("买入日期", date.today() - timedelta(days=30))
        buy_price_in = c5.number_input("买入价", min_value=0.0, step=0.01, format="%.3f")
        shares_in = c6.number_input("股数", min_value=0, step=100, value=100)
        submitted = st.form_submit_button("加入自选", type="primary")
        if submitted:
            if not code_in.strip() or buy_price_in <= 0:
                st.warning("请至少填写「代码」和「买入价」")
            else:
                _wl_add(ls, m, code_in, name_in,
                        buy_date_in.isoformat(), buy_price_in, int(shares_in))
                st.success("已加入自选股")

    entries = _wl_load(ls)
    if not entries:
        st.info("还没有自选股，先在上面添加一只吧。数据存在你自己浏览器里，换设备/清缓存会清空。")
        return

    st.divider()
    st.subheader(f"📋 我的持仓（{CURRENT_USER}）")

    total_pnl = 0.0
    today_str = date.today().strftime("%Y%m%d")

    for e in entries:
        with st.container(border=True):
            # 第一行：标题（名称+代码）占满，右侧放删除按钮
            head_l, head_r = st.columns([8, 1])
            title = e.get("name") or e["code"]
            head_l.markdown(f"#### {title} &nbsp; `{e['market']} {e['code']}`")
            if head_r.button("删除", key=f"del_{e['id']}"):
                st.session_state["wl_pending_delete"] = e["id"]
                st.rerun()

            df = None
            try:
                # 取足够长的历史：从买入日和一年前里更早的那个开始，保证指标算得出
                buy_dt = date.fromisoformat(e["buy_date"])
                start_dt = min(buy_dt, date.today() - timedelta(days=365))
                df = load_kline(e["market"], e["code"],
                                start_dt.strftime("%Y%m%d"), today_str)
                cur = float(df["close"].iloc[-1])
                prev = float(df["close"].iloc[-2]) if len(df) > 1 else cur
                chg = (cur - prev) / prev * 100 if prev else 0.0
                pnl_pct = (cur - e["buy_price"]) / e["buy_price"] * 100
                pnl = (cur - e["buy_price"]) * e["shares"]
                total_pnl += pnl
                hold_days = max((date.today() - buy_dt).days, 0)

                # 第二行：四个数字各占满宽的 1/4，不再被截断
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("现价", f"{cur:,.2f}", f"{chg:+.2f}%")
                m2.metric("买入价", f"{e['buy_price']:,.2f}")
                m3.metric("浮动盈亏", _fmt_cny(pnl), f"{pnl_pct:+.1f}%")
                m4.metric("持有", f"{hold_days} 天")
            except Exception as ex:
                st.error(f"取数失败：{ex}")

            # 助手建议
            if df is not None and not df.empty:
                pk = f"prompt_{e['id']}"
                # 生成过提示词后，让 expander 保持展开（修复点按钮后缩回的问题）
                with st.expander("🧠 助手建议（大白话）", expanded=(pk in st.session_state)):
                    try:
                        val = None
                        try:
                            val = load_valuation(e["market"], e["code"])
                        except Exception:
                            val = None  # 估值拿不到不影响其它建议
                        adv = build_advice(df, val, e["buy_price"],
                                           e["buy_date"], e["shares"])
                        st.markdown(f"#### 📌 一句话：{adv['summary']}")
                        for ins in adv["insights"]:
                            icon = _LEVEL_ICON.get(ins["level"], "•")
                            st.markdown(f"{icon} **[{ins['dim']}]** {ins['text']}")
                        st.caption(adv["disclaimer"])

                        # 生成可粘贴到 AI 的提示词（免费，用自己的 AI 订阅）
                        st.divider()
                        if st.button("📋 生成给 AI 的分析提示词", key=f"pbtn_{e['id']}"):
                            st.session_state[pk] = ai_advisor.build_chat_prompt(df, val, e)
                        if pk in st.session_state:
                            st.caption("👇 点「复制全部」，粘贴到你常用的 AI（如 claude.ai、ChatGPT）发送即可，免费")
                            copy_box(st.session_state[pk])
                    except Exception as ex:
                        st.warning(f"建议生成失败：{ex}")

    # 组合总盈亏
    st.divider()
    color = "red" if total_pnl >= 0 else "green"
    st.markdown(
        f"### 组合总浮动盈亏："
        f"<span style='color:{color}'>{_fmt_cny(total_pnl)}</span>",
        unsafe_allow_html=True,
    )
    st.caption("注：现价取最新交易日收盘价（非实时盘中价）。")


# ---------- 子函数：策略回测 ----------
def render_backtest():
    st.subheader("🔬 策略回测")
    st.caption("用历史数据验证「某个买卖策略能不能赚钱」，并和「一直拿着不动（买入持有）」对比。"
               "用左侧选好的市场/代码/时间范围。")

    strat_label = st.radio("选择策略", list(backtest.STRATEGIES.keys()), horizontal=True)
    strat_code = backtest.STRATEGIES[strat_label]

    params = {}
    if strat_code == "ma":
        c1, c2 = st.columns(2)
        params["short"] = c1.number_input("短均线（日）", 2, 120, 5)
        params["long"] = c2.number_input("长均线（日）", 5, 250, 20)
        if params["short"] >= params["long"]:
            st.warning("短均线应小于长均线")
    elif strat_code == "rsi":
        c1, c2 = st.columns(2)
        params["low"] = c1.number_input("超卖线（买入）", 5, 50, 30)
        params["high"] = c2.number_input("超买线（卖出）", 50, 95, 70)

    if not st.button("运行回测", type="primary"):
        st.info("👈 选好市场/代码/时间，设好策略参数，点「运行回测」。")
        return
    if not code.strip():
        st.warning("请先在左侧输入股票代码")
        return

    try:
        df = load_kline(market, code, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
        df = add_moving_averages(df)
        df = add_macd(df)
        df = add_rsi(df, 14)
        res = backtest.run(df, strat_code, **params)
    except Exception as e:
        st.error(f"回测失败：{e}")
        return

    s = res["stats"]
    # 净值曲线：策略 vs 买入持有
    eq = res["equity_df"]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=eq["date"], y=eq["策略净值"], name="策略",
                             line=dict(color="red", width=2)))
    fig.add_trace(go.Scatter(x=eq["date"], y=eq["买入持有净值"], name="买入持有",
                             line=dict(color="gray", width=1.5, dash="dash")))
    fig.update_layout(height=380, margin=dict(t=20, b=20),
                      legend=dict(orientation="h", y=1.05),
                      yaxis_title="净值（起点=1）")
    st.plotly_chart(fig, use_container_width=True)

    # 关键指标（每个都带「这是什么」的悬浮说明）
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("用这个策略赚了", f"{s['策略总收益']:+.1f}%",
              help="如果你这段时间严格按这个策略买卖，本金会变多/少多少。")
    c2.metric("一直拿着不动赚了", f"{s['买入持有收益']:+.1f}%",
              help="如果你期初买入后啥也不做，一直拿到现在，会赚多少。用来当对照。")
    c3.metric("中途最多亏过", f"{s['最大回撤']:.1f}%",
              help="过程中从最高点回落的最大幅度。数字越小越「肉疼」，反映你要扛多大波动。")
    c4.metric("做了几笔买卖", f"{s['交易次数']} 次",
              help=f"期间一共完整买卖了几轮。其中赚钱的占 {s['胜率']:.0f}%（胜率）。")

    # 大白话结论：直接说人话
    excess = s["超额收益"]
    win = s["胜率"]
    if excess > 0:
        st.success(
            f"✅ **结论：这段时间这个策略更划算。** 它比「一直拿着不动」多赚了 "
            f"**{excess:.1f}%**，做的 {s['交易次数']} 笔买卖里有 {win:.0f}% 是赚的。\n\n"
            f"⚠️ 但这是「事后看历史」。同样的策略换只股票、换段时间，结果可能完全不同，"
            f"别以为照搬就能稳赚。"
        )
    else:
        st.warning(
            f"📉 **结论：这段时间还不如啥都不做。** 这个策略比「一直拿着不动」"
            f"**少赚了 {abs(excess):.1f}%**。说明对这只股票、这段时间，频繁买卖是帮倒忙。\n\n"
            f"换个策略、换组参数，或换只股票再试试。"
        )
    st.caption("说明：回测是拿历史数据「假装当时这么操作」，没算手续费和买卖差价，"
               "只供学习参考，不构成投资建议。")

    if res["trades"]:
        with st.expander(f"看看每一笔买卖（共 {len(res['trades'])} 笔，绿赚红亏）"):
            tdf = pd.DataFrame(res["trades"])
            st.dataframe(
                tdf.style.map(
                    lambda v: f"color:{'#16A34A' if v > 0 else '#DC2626'}",
                    subset=["收益率"],
                ),
                use_container_width=True,
            )


# ---------- 主区域 ----------
tab_tech, tab_fund, tab_wl, tab_bt = st.tabs(
    ["📊 技术分析", "📑 基本面", "⭐ 自选股", "🔬 回测"])

with tab_wl:
    render_watchlist()
with tab_bt:
    render_backtest()

if go_btn:
    if not code.strip():
        st.warning("请输入股票代码")
        st.stop()

    with tab_tech:
        try:
            df = load_kline(
                market, code,
                start.strftime("%Y%m%d"), end.strftime("%Y%m%d"),
            )
            render_technical(df)
        except Exception as e:
            st.error(f"获取行情失败：{e}")

    with tab_fund:
        render_fundamental()
else:
    with tab_tech:
        st.info("👈 在左侧选择市场、输入代码、勾选指标，点「查询」开始。")
    with tab_fund:
        st.info("基本面（估值 + 营收利润）目前对 A股 完整支持。查询后在此查看。")
