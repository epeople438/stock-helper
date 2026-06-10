"""
自选股存储层（支持「按人区分」+「本地/云数据库」两种后端）。

- 本地运行：存到本地 watchlist.json，结构是 {用户名: [记录...]}。
- 部署到云端：若配置了 Supabase（st.secrets 里有 SUPABASE_URL / SUPABASE_KEY），
  自动改用 Supabase 数据库，按用户名存取，重启不丢、各人各看各的。

对外函数都带 user 参数：load(user) / add_entry(user, ...) / remove_entry(user, id)。

Supabase 端需要一张表（在 Supabase 后台 SQL 里建一次）：
    create table watchlists (
        "user" text primary key,
        items jsonb default '[]'::jsonb
    );
每条记录结构：{id, market, code, name, buy_date, buy_price, shares}
"""

import json
import uuid
from pathlib import Path

_LOCAL_PATH = Path(__file__).resolve().parent.parent / "watchlist.json"


# ---------- 后端探测：有 Supabase 配置就用云，否则用本地文件 ----------
def _supabase():
    """返回 Supabase 客户端；没配置或不可用则返回 None（退回本地）。"""
    # 先确认有 secrets 文件，避免本地访问 st.secrets 报红
    locs = [Path.home() / ".streamlit" / "secrets.toml",
            _LOCAL_PATH.parent / ".streamlit" / "secrets.toml"]
    if not any(p.exists() for p in locs):
        return None
    try:
        import streamlit as st
        url = st.secrets.get("SUPABASE_URL", "")
        key = st.secrets.get("SUPABASE_KEY", "")
    except Exception:
        return None
    if not url or not key:
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except Exception:
        return None


# ---------- 本地后端 ----------
def _local_load_all() -> dict:
    if not _LOCAL_PATH.exists():
        return {}
    try:
        data = json.loads(_LOCAL_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _local_save_all(data: dict) -> None:
    _LOCAL_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- 对外接口 ----------
def load(user: str) -> list:
    """读取某个用户的全部自选股。"""
    sb = _supabase()
    if sb:
        res = sb.table("watchlists").select("items").eq("user", user).execute()
        if res.data:
            return res.data[0].get("items") or []
        return []
    return _local_load_all().get(user, [])


def _save_user(user: str, entries: list) -> None:
    sb = _supabase()
    if sb:
        sb.table("watchlists").upsert({"user": user, "items": entries}).execute()
        return
    data = _local_load_all()
    data[user] = entries
    _local_save_all(data)


def add_entry(user: str, market: str, code: str, name: str,
              buy_date: str, buy_price: float, shares: int) -> dict:
    """给某用户新增一条自选股。"""
    entries = load(user)
    entry = {
        "id": uuid.uuid4().hex,
        "market": market,
        "code": code.strip(),
        "name": (name or "").strip(),
        "buy_date": buy_date,
        "buy_price": float(buy_price),
        "shares": int(shares),
    }
    entries.append(entry)
    _save_user(user, entries)
    return entry


def remove_entry(user: str, entry_id: str) -> None:
    """删除某用户的一条记录。"""
    entries = [e for e in load(user) if e.get("id") != entry_id]
    _save_user(user, entries)
