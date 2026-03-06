#!/bin/bash
# 快速启动脚本：一键完成ETF数据抓取和策略探索
set -e

cd /Users/levy/.openclaw/workspace/projects/a-share-etf-quant

echo "=========================================="
echo "📊 A股ETF量化策略研究 - 快速启动"
echo "=========================================="

# Step 1: 安装依赖（如果未安装）
echo ""
echo "🔧 检查依赖..."
pip3 show akshare >/dev/null 2>&1 || echo "⚠️  akshare 未安装，将使用 yfinance 备用"
pip3 show yfinance >/dev/null 2>&1 || pip3 install --user yfinance pandas numpy matplotlib

# Step 2: 抓取数据
echo ""
echo "📥 开始抓取ETF历史数据..."
python3 scripts/fetch_etf_data.py

# 检查数据文件
DATA_FILE="data/raw/etf_history_2015_2025.csv"
if [ ! -f "$DATA_FILE" ] && [ ! -f "data/raw/us_etf_history_2015_2025.csv" ]; then
    echo "❌ 未找到数据文件，退出"
    exit 1
fi

# Step 3: 策略回测
echo ""
echo "🔬 开始策略探索与回测..."
python3 scripts/explore_strategies.py

echo ""
echo "✅ 全部完成！"
echo "📁 查看结果: data/raw/ 和 results/ 目录"
