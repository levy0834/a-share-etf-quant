# 快速启动脚本 - 量化策略研究

## 🚀 一键运行整个流程

```bash
cd /Users/levy/.openclaw/workspace/projects/a-share-etf-quant

# 1. 设置Python环境（确保依赖已安装）
pip3 install --user pandas numpy matplotlib akshare yfinance 2>/dev/null

# 2. 运行数据抓取（抓取80+只A股ETF的10年数据）
python3 scripts/fetch_etf_data.py

# 3. 运行策略回测（12种策略训练+测试）
python3 scripts/explore_strategies.py

# 4. 结果查看
# 数据将生成在：
#   data/raw/etf_history_2015_2025.csv (原始数据)
#   results/strategy_comparison.csv (策略对比)
#   results/train_results.csv (训练集详细)
#   results/test_summary.csv (测试集总结)
```

## 📊 查看分析看板

数据就绪后，复制CSV文件到看板目录：

```bash
# 复制数据到dashboard目录
cp results/strategy_comparison.csv ~/.openclaw/workspace/quant-trading-system/dashboard/
cp results/strategy_summary.csv ~/.openclaw/workspace/quant-trading-system/dashboard/ 2>/dev/null || true

# 启动HTTP服务器（需在dashboard目录）
cd ~/.openclaw/workspace/quant-trading-system/dashboard
python3 -m http.server 8080

# 浏览器访问：http://localhost:8080
# - index.html         : 原始版本（已修复收益分布图排版）
# - index_enhanced.html: 增强版（多标签、多图表、全功能）
```

## 🎯 当前状态

- ✅ 策略代码已完成（12种策略）
- ✅ 增强版分析页面已创建
- ⏳ 待运行：数据抓取 + 回测生成CSV
- ⏳ 待复制：CSV到dashboard目录
- ⏳ 待验证：浏览器访问看板

## 📈 新增策略列表

1. MA Cross (MA5/MA20)
2. MA Double (MA10/MA60)
3. MA Triple (MA20/60/120)
4. MACD Cross
5. MACD Hist (柱状图加速)
6. RSI Extreme (超买超卖)
7. MA+RSI Combo
8. Bollinger Band (突破)
9. Bollinger Squeeze (收缩突破)
10. Volume Confirm (成交量确认)
11. TA Confluence (原始TAV)
12. TA Strengthened (强化版)

## 🔧 故障排除

- **akshare安装失败**：使用备用yfinance自动回退
- **数据抓取慢**：80只ETF × 1秒间隔 ≈ 1.5分钟
- **看板无数据**：检查CSV文件是否复制到dashboard目录
- **图表不显示**：确保网络可访问CDN（Chart.js）

---

**下一步**: 执行数据抓取 → 策略回测 → 复制CSV → 浏览器访问看板
