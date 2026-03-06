# 监控告警系统

A股ETF量化交易系统的全方位监控解决方案，自动检测数据管道、回测健康和账户状态异常。

## 功能特性

### 1. 数据管道检查 (`check_data_pipeline`)
- 检查 `data/day/` 目录下最新数据日期
- 如果最新日期超过 2 天（可配置）未更新，触发告警
- 自动读取 `latest_date.txt` 或扫描 CSV 文件获取最新日期

### 2. 回测健康检查 (`check_backtest_health`)
- 扫描 `results/latest.log` 文件
- 检测 ERROR、Traceback、Exception 等错误关键词
- 发现错误时提供上下文（前后5行）以便快速定位问题

### 3. 账户健康检查 (`check_account_health`)
- 读取虚拟账户状态文件 `data/accounts/states/YYYY-MM-DD.json`
- 计算当日收益率 = (当前总资产 - 前一日总资产) / 前一日总资产
- 如果收益率超过 ±5%（可配置），触发告警

### 4. 告警通知 (`send_alert`)
- 通过飞书 webhook 发送告警消息
- 使用 `FEISHU_WEBHOOK_URL` 环境变量配置 webhook URL
- 支持多告警聚合发送

## 文件结构

```
scripts/
├── monitoring/
│   ├── __init__.py       # 模块入口
│   ├── alert.py          # 核心告警模块
│   ├── README.md         # 本文档
│   └── alert_system.log  # 运行日志（自动生成）
```

## 环境配置

### 1. 安装依赖

```bash
cd /Users/levy/.openclaw/workspace/projects/a-share-etf-quant
pip install requests pandas
```

### 2. 设置飞书 Webhook

1. 在飞书群组中添加上报机器人，获取 Webhook URL
2. 设置环境变量：

```bash
# 临时设置
export FEISHU_WEBHOOK_URL="https://open.feishu.cn/open-apis/bot/v2/hook/..."

# 或添加到 ~/.zshrc / ~/.bash_profile
echo 'export FEISHU_WEBHOOK_URL="你的WEBHOOK_URL"' >> ~/.zshrc
source ~/.zshrc
```

### 3. 可选配置

通过环境变量调整阈值：

```bash
# 日收益率告警阈值（默认 5%）
export DAILY_RETURN_THRESHOLD="5.0"

# 数据过期天数（默认 2 天）
export DATA_EXPIRY_DAYS="2"

# latest.log 文件名模式
export LATEST_LOG_PATTERN="latest.log"
```

## 使用方法

### 手动运行

```bash
cd /Users/levy/.openclaw/workspace/projects/a-share-etf-quant
python scripts/monitoring/alert.py
```

运行后会执行所有检查，如有异常发送飞书告警。退出码：
- `0` = 所有检查通过
- `1` = 有检查失败并已发送告警
- `130` = 用户中断（Ctrl+C）

### 定时任务（Cron）

每小时运行一次监控检查：

```bash
# 编辑 crontab
crontab -e

# 添加以下行（每小时的第0分钟运行）
0 * * * * cd /Users/levy/.openclaw/workspace/projects/a-share-etf-quant && /usr/bin/python3 scripts/monitoring/alert.py >> scripts/monitoring/cron.log 2>&1
```

建议同时配置日志轮转，避免 log 文件过大。

### 查看运行日志

```bash
# 实时查看
tail -f scripts/monitoring/alert_system.log

# 查看历史
ls -lht scripts/monitoring/
```

## 已集成的模块

### 1. `daily_update.py`

在每日数据更新流程末尾自动执行数据管道检查：

```python
# 在 daily_update_flow() 函数的最后（返回 True 之前）
# 已集成：check_data_pipeline()
```

位置：`scripts/daily_update.py` 第 446 行附近

### 2. `backtester.py`

在回测评估完成后自动执行回测健康检查：

```python
# 在 __main__ 块中，bt.evaluate() 之后
# 已集成：check_backtest_health()
```

位置：`scripts/backtester.py` 第 777 行附近

### 3. `dashboard/sim_trader.py`

在每次信号执行并保存账户状态后自动执行账户健康检查：

```python
# 在 execute_signals() 函数中，virtual_account.save_state() 之后
# 已集成：check_account_health()
```

位置：`dashboard/sim_trader.py` 第 482 行附近

## 自定义配置

### 修改告警阈值

编辑 `alert.py` 中的配置常量：

```python
# 告警阈值配置
DAILY_RETURN_THRESHOLD_PCT = 5.0    # 日收益率阈值 ±5%
DATA_EXPIRY_DAYS = 2               # 数据过期天数
LATEST_LOG_PATTERN = "latest.log"  # 日志文件模式
```

或通过环境变量覆盖（推荐）。

### 添加新的检查项

在 `alert.py` 中添加新的检查函数，然后在 `run_all_checks()` 中调用，并更新 `results['checks']` 字典。

## 故障排查

### 1. 飞书告警未发送

检查：
- `FEISHU_WEBHOOK_URL` 是否设置正确
- 网络连接是否正常
- webhook URL 是否有效（可在飞书群组测试）

```bash
echo $FEISHU_WEBHOOK_URL
curl -X POST -H "Content-Type: application/json" -d '{"msg_type":"text","content":{"text":"测试"}}' $FEISHU_WEBHOOK_URL
```

### 2. "监控模块不可用" 错误

确保 `scripts/monitoring/` 目录结构正确，并且 `__init__.py` 存在。

检查 Python 路径：
```python
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
```

### 3. 数据管道检查失败

确保 `data/latest_date.txt` 存在且格式正确（YYYY-MM-DD），或 `data/day/*.csv` 文件包含有效的 `date` 列。

### 4. 账户健康检查失败

确保 `data/accounts/states/` 目录下有状态文件，文件名为 `YYYY-MM-DD.json`，包含 `total_value` 字段。

## 日志说明

### alert_system.log

监控系统主日志，记录每次运行的所有检查和告警情况。

### cron.log

如果使用 cron 定时任务，输出将重定向到此文件。

## 注意事项

1. **幂等性**：检查函数是幂等的，可重复执行无副作用
2. **错误隔离**：单个检查失败不会影响其他检查
3. **优雅降级**：如果监控模块未找到或导入失败，被集成模块会跳过检查并记录警告，不影响原有功能
4. **线程安全**：所有检查都使用本地变量，无共享状态

## 最佳实践

1. **定期查看日志**：每天检查 `alert_system.log` 确认系统正常运行
2. **及时处理告警**：收到飞书告警后，按指示排查问题
3. **保持更新**：定期更新 `latest_date.txt` 和数据文件
4. **测试告警**：每月手动触发一次告警，确保 webhook 有效
5. **监控监控系统**：在更高层的监控中检查 `alert_system.log` 是否在定时产生

## 版本历史

- v1.0.0 (2025-03-06)
  - 初始版本
  - 实现三大检查功能
  - 集成到 daily_update、backtester、sim_trader
  - 飞书 webhook 告警

---

**维护者**: 小灵
**最后更新**: 2025-03-06
