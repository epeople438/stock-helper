#!/bin/bash
# 双击这个文件就能启动股票分析程序。
# 它会自动切换到本脚本所在目录、临时关掉代理（避免数据源连不上）、再启动网页。

cd "$(dirname "$0")"

# akshare 的数据源（东方财富）是国内站点，走科学上网代理反而会连不上，
# 所以这里临时清掉代理变量，只影响本程序，不影响你系统其它软件。
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

echo "正在启动股票分析程序，启动后会自动打开浏览器…"
echo "用完直接关掉这个终端窗口即可停止程序。"
echo ""

streamlit run app.py
