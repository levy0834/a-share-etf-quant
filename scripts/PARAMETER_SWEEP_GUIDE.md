# 参数敏感性分析使用指南

## 脚本位置
`projects/a-share-etf-quant/scripts/parameter_sweep.py`

## 功能说明
该脚本对以下三个策略进行参数网格搜索：
1. **MA Cross** - 均线交叉策略
   - 参数：`ma1=[5,10,15]`, `ma2=[20,30,40]`
   - 当ma1 > ma2时买入，ma1 < ma2时卖出

2. **RSI Extreme** - RSI超买超卖策略
   - 参数：`oversold=[20,25,30]`, `overbought=[70,75,80]`
   - RSI < oversold买入，RSI > overbought卖出

3. **Bollinger Band** - 布林带突破策略
   - 参数：`std=[1.5,2.0,2.5]`（标准差倍数）
   - 价格突破布林带上轨卖出，突破下轨买入

## 运行方式

```bash
cd /Users/levy/.openclaw/workspace/projects/a-share-etf-quant
python3 scripts/parameter_sweep.py
```

## 数据划分
- **训练集**：2015-01-01 ~ 2021-12-31
- **测试集**：2022-01-01 ~ 2025-12-31

## 输出文件

### 1. 详细结果 CSV
`results/parameter_sensitivity.csv`
包含每个参数组合在训练集和测试集上的完整评估：
- strategy: 策略名称
- params: 参数字典
- dataset: 数据集（train/test）
- total_return_pct: 总收益率(%)
- sharpe_ratio: 夏普比率
- max_drawdown_pct: 最大回撤(%)
- total_trades: 交易次数
- win_rate_pct: 胜率(%)
- annual_return_pct: 年化收益率(%)

### 2. 摘要报告
`results/parameter_sensitivity_summary.csv`
仅包含每个策略的最佳参数组合（基于训练集夏普比率）：
- strategy
- best_params
- train_sharpe_ratio
- train_return_pct
- test_sharpe_ratio
- test_return_pct

### 3. 可视化热力图
`results/figures/{strategy}_heatmap.png`
- 2D参数（如MA Cross, RSI Extreme）：展示训练/测试集夏普比率的热力图
- 1D参数（如Bollinger Band）：展示夏普比率和收益率随参数变化的折线图

## 技术特性

1. **多进程加速**：使用 `concurrent.futures.ProcessPoolExecutor`，自动使用所有CPU核心（最多4个）
2. **进度显示**：使用 `tqdm` 显示实时进度条
3. **错误隔离**：单个参数组合失败不会影响整体运行
4. **稳健分析**：自动识别最优参数并对比训练/测试集表现

## 依赖库

- pandas >= 2.0
- numpy >= 2.0
- matplotlib >= 3.0
- tqdm >= 4.0

已安装：pandas(2.3.3), numpy(2.0.2), matplotlib(3.9.4), tqdm(已安装)

## 预期运行时间

取决于数据量大小和CPU核心数。典型配置下：
- 总共 3×3×3 + 3×3×3 + 3 = 27 + 27 + 3 = 57 个参数组合
- 每个组合运行2次回测（训练集+测试集）
- 总计 114 次回测运行
- 预计时间：3-10分钟（取决于回测速度）

## 结果解读

查看 `parameter_sensitivity_summary.csv` 可快速了解：
1. 哪个策略表现最好（高夏普、高收益）
2. 是否过拟合（对比训练集和测试集夏普比率）
3. 参数敏感性（通过热力图观察）

## 后续建议

1. **稳健参数区间**：如果热力图显示参数在一定范围内表现稳定，可选择该区间内的参数
2. **避免过拟合**：优先选择训练集和测试集表现接近的参数
3. **鲁棒性验证**：对最佳参数在更长时间范围内进行额外验证
