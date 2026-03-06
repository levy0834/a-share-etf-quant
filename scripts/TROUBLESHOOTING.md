# 故障排除与测试指南

## 快速测试（验证安装）

运行以下命令测试脚本是否能正常工作：

```bash
cd /Users/levy/.openclaw/workspace/projects/a-share-etf-quant

# 检查数据文件
ls -lh data/raw/etf_history_2015_2025.csv

# 检查依赖
python3 -c "
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from tqdm import tqdm
from concurrent.futures import ProcessPoolExecutor
from scripts.backtester import Backtester, calculate_indicators
print('✅ All dependencies OK')
"

# 导入检查
python3 -c "from scripts.parameter_sweep import PARAM_GRIDS; print('Strategies:', list(PARAM_GRIDS.keys()))"
```

## 常见问题

### 1. 找不到数据文件
**错误**：`FileNotFoundError: [Errno 2] No such file or directory`
**解决**：确保数据文件在 `data/raw/etf_history_2015_2025.csv`

### 2. 多进程错误
**错误**：`multiprocessing` 相关错误
**解决**：脚本已设置 `mp.set_start_method('spawn', force=True)`，通常不会出错。如仍有问题，可修改 `main()` 中的 `n_workers=1` 强制单进程运行

### 3. 内存不足
**表现**：运行缓慢或崩溃
**解决**：减少 `n_workers` 数量，或减小数据量

### 4. Matplotlib 中文字体问题
**表现**：图表中的中文显示为方框
**解决**：已设置常用字体，如仍有问题可修改字体设置或使用英文标签

## 性能优化建议

- CPU核心数：脚本自动检测，默认最多4个worker
- 数据量：训练集~2000天，测试集~1200天，已足够
- 回测速度：典型单次回测<1秒，总时长约5分钟

## 验证结果

运行完整分析后，检查：

1. CSV文件存在且包含58行（29个组合 * 2数据集）
2. 热力图文件存在：`results/figures/ma_cross_heatmap.png`, `rsi_extreme_heatmap.png`, `bollinger_band_heatmap.png`
3. 摘要报告中有合理的夏普比率（一般在 [-1, 3] 区间）

## 调试模式

如需调试单个参数组合，可修改 `evaluate_params_single` 添加打印：

```python
print(f"Testing {strategy_name} with {params} on {dataset_name}")
```

或在主程序中临时设置为单进程：

```python
# 将 sweep_strategy_parallel 改为 sweep_strategy（现有函数中有串行版本注释）
```

## 预期输出示例

```
======================================================================
🎯 参数敏感性分析 - Parameter Sensitivity Analysis
======================================================================

📥 加载数据...
📊 数据划分:
  训练集: 2015-01-01 ~ 2021-12-31 (2191 天)
  测试集: 2022-01-01 ~ 2025-12-31 (1461 天)

🔍 Sweeping MA Cross: 9 combinations using 4 workers
  Processing MA Cross: 100%|██████████| 9/9 [00:15<00:00,  1.67s/combo]

🔍 Sweeping RSI Extreme: 9 combinations using 4 workers
  Processing RSI Extreme: 100%|██████████| 9/9 [00:12<00:00,  1.33s/combo]

🔍 Sweeping Bollinger Band: 3 combinations using 4 workers
  Processing Bollinger Band: 100%|██████████| 3/3 [00:04<00:00,  1.33s/combo]

✅ 结果保存到: results/parameter_sensitivity.csv
   总参数量: 21 个组合
   总记录数: 42 行（含训练/测试集）

📊 分析结果...

🏆 最优参数组合:

  MA Cross:
    最佳参数: {'ma1': 10, 'ma2': 30}
    训练集: Sharpe=0.52, 收益=12.3%
    测试集: Sharpe=0.31, 收益=5.8%

  ...

🎨 生成热力图...
  📊 Heatmap saved: results/figures/ma_cross_heatmap.png
  📊 Heatmap saved: results/figures/rsi_extreme_heatmap.png
  📊 Line plot saved: results/figures/bollinger_band_heatmap.png

✅ 摘要报告保存到: results/parameter_sensitivity_summary.csv

======================================================================
✅ 参数敏感性分析完成！
======================================================================
```
