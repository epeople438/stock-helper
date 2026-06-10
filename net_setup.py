"""
统一关闭代理。被 data/fetch.py 和 analysis/fundamental.py 在最顶部导入。

为什么需要：akshare 的数据源都是国内站点（东方财富、百度股市通），走科学上网
代理反而会连不上。而且科学上网客户端常常「时好时坏」，只清环境变量不够稳——
有时它又把代理写回系统设置。所以这里釜底抽薪，直接让底层的 requests 库
「永远不使用任何代理」，无论代理来自环境变量还是 macOS 系统网络设置。

导入本模块即生效，无需调用任何函数。
"""

import os

# 先把原来的代理地址记下来：akshare 连国内源不能走代理，但 Claude API
# （api.anthropic.com 在国外）反而需要走代理。所以这里保存原值，供 AI 解读复用。
ORIGINAL_PROXY = (
    os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    or os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or ""
)

# 1) 清掉进程内的代理环境变量（让 akshare/requests 直连国内数据源）
for _var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
             "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(_var, None)

# 2) 让 requests 彻底忽略系统/环境代理：把它查代理的函数替换成「永远返回空」。
#    akshare 底层用 requests，patch 后它的所有请求都直连，不再受代理影响。
try:
    import requests.utils
    requests.utils.getproxies = lambda: {}
except Exception:
    # 万一 requests 结构变化，patch 失败也不影响：环境变量已清，多数情况够用。
    pass
