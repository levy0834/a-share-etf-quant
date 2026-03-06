# 自动化更新功能 - 添加记录

## 新增文件

### 1. scripts/daily_update.py
**主更新脚本**（22KB，545行）
- 功能：检查更新状态、调用数据获取、验证数据、失败重试、报警
- 命令行接口：--force, --dry-run, --validate-only, --log-level
- 日志：daily_update_YYYY-MM-DD.log, data_validation_YYYY-MM-DD.log
- 重试机制：最多3次，指数退避（2/4/8秒）
- 飞书报警：通过 FEISHU_WEBHOOK_URL 环境变量配置

### 2. .github/workflows/daily_update.yml
**GitHub Actions 自动化配置**（2.4KB，80行）
- 定时：工作日 16:00 北京时间（cron: '0 8 * * 1-5'）
- 支持手动触发和参数输入
- 自动上传日志 artifact
- 集成飞书失败通知

### 3. requirements.txt
**Python依赖声明**（290字节）
- akshare, pandas, numpy, tqdm, requests
- 便于 environment 管理

### 4. scripts/test_daily_update.py
**单元测试**（3.9KB，150行）
- 测试 parse_date_string, get_trading_days
- 测试 validate_etf_data
- 测试 send_feishu_alert
- 测试日志文件路径生成
- 全部 6 个测试通过 ✅

### 5. UPDATE_GUIDE.md
**快速参考文档**（4.6KB，200行）
- 命令行使用示例
- 日志文件说明
- 飞书报警配置
- GitHub Actions 设置
- 故障排除和调试技巧
- 更新流程逻辑图

### 6. README.md
**更新部分**
- 第8节：自动化更新（本地和GitHub Actions）
- 第9节：故障排除
- 第10节：贡献指南

## 现有文件修改

### scripts/fetch_etf_universe.py
**无需修改** - 已完全兼容
- 脚本支持 --full (全量) 和 默认 (增量) 模式
- daily_update.py 通过子进程调用

## 创建目录

```
data/day/          # ETF日线数据目录（每个ETF一个CSV）
logs/              # 日志文件（自动按日期命名）
.github/workflows/ # GitHub Actions 工作流
```

## 代码特点

### ✅ 符合所有需求

1. **检查更新状态**
   - 优先读取 `data/latest_date.txt`
   - 如果文件不存在，扫描所有CSV获取最新日期
   - 对比今日日期判断是否需要更新

2. **调用ETF数据获取**
   - 使用 subprocess 调用 `fetch_etf_universe.py`
   - 传递 `--full` 参数（当 --force 时）
   - 捕获输出和返回码

3. **数据验证**
   - 检查所有ETF数据文件是否有缺失日期
   - 验证收盘价 > 0，成交量 >= 0
   - 检查数据连续性（与交易日对比）
   - 记录到 `logs/data_validation_YYYY-MM-DD.log`

4. **失败重试与报警**
   - 最多3次重试，指数退避（2/4/8秒）
   - 失败记录到 `logs/daily_update_errors.log`
   - 若最终失败，发送飞书webhook通知

5. **日志记录**
   - 主日志：`logs/daily_update_YYYY-MM-DD.log`
   - 包含：开始时间、结束时间、更新统计、验证结果
   - 使用 Python logging 模块（非 print）

6. **命令行接口**
   ```bash
   python daily_update.py --force
   python daily_update.py --dry-run
   python daily_update.py --validate-only
   python daily_update.py --log-level DEBUG
   ```

7. **GitHub Actions 集成**
   - YAML 配置文件完整
   - 包含 schedule 和 workflow_dispatch
   - 日志 artifact 上传
   - 环境变量配置示例

### ✅ 附加要求

- **类型提示**：所有函数都有返回类型注解
- **Docstring**：函数和模块都有完整文档
- **主程序入口**：`main()` 函数清晰
- **函数可测试**：逻辑分离，核心函数独立

### ✅ 代码质量

- 遵循 PEP 8
- 完整的错误处理
- 详细的日志记录
- 可配置的重试机制
- 模块化设计

## 测试结果

```bash
# 语法检查
python3 -m py_compile daily_update.py  ✅

# 单元测试
python3 test_daily_update.py           ✅ 6/6 tests passed

# 功能测试
python daily_update.py --help          ✅ 显示帮助
python daily_update.py --dry-run       ✅ 预览模式正常
python daily_update.py --validate-only ✅ 验证模式正常
```

## 使用示例

```bash
# 首次运行（全量）
python fetch_etf_universe.py --full

# 平时增量更新
python daily_update.py

# 查看状态
python daily_update.py --dry-run

# 验证数据质量
python daily_update.py --validate-only

# 调试
python daily_update.py --log-level DEBUG
```

## GitHub Actions 设置

1. 推送代码到 GitHub
2. 在仓库 Settings -> Secrets 添加 `FEISHU_WEBHOOK_URL` (可选)
3. 工作流自动在工作日 16:00 运行
4. 也可以手动触发并传入参数

## 下一步建议

1. **首次运行**：在稳定的网络环境执行全量下载
2. **配置飞书**：创建机器人并设置 webhook 获取失败通知
3. **GitHub Actions**：完成 GitHub 仓库设置后启用自动化
4. **监控**：定期检查 `logs/` 目录下的日志文件

## 文档链接

- `README.md` - 项目主文档（已更新）
- `UPDATE_GUIDE.md` - 快速参考（新增）
- `daily_update.py` - 脚本源码（含详细注释）
- `.github/workflows/daily_update.yml` - Actions 配置

---

**完成日期**: 2025-03-06
**版本**: 1.0
**作者**: 小灵 (OpenClaw Agent)
