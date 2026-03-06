# 数据更新自动化快速参考

## 📋 文件清单

```
projects/a-share-etf-quant/
├── scripts/
│   ├── daily_update.py          # 每日更新主脚本 ✨ 新增
│   └── fetch_etf_universe.py    # ETF数据获取（现有）
├── .github/
│   └── workflows/
│       └── daily_update.yml     # GitHub Actions 配置 ✨ 新增
├── data/
│   ├── day/                     # ETF日线数据（CSV）
│   ├── latest_date.txt          # 最后更新日期 ✨ 自动生成
│   ├── etf_metadata.csv         # ETF元数据（由fetch_etf_universe生成）
│   └── raw/                     # 原始数据缓存
├── logs/                        # 日志目录
│   ├── daily_update_YYYY-MM-DD.log
│   ├── data_validation_YYYY-MM-DD.log
│   └── daily_update_errors.log
├── README.md                    # 已更新包含本节
└── requirements.txt             # Python依赖 ✨ 新增
```

## 🚀 快速开始

### 首次运行（全量下载）
```bash
cd projects/a-share-etf-quant/scripts

# 全量下载（约1-2小时，80+ ETF × 10年数据）
python fetch_etf_universe.py --full

# 或使用 daily_update（会自动检测到需要全量下载）
python daily_update.py --force
```

### 日常维护（增量更新）
```bash
# 自动判断是否需要更新
python daily_update.py

# 仅检查，不执行
python daily_update.py --dry-run

# 仅验证数据质量
python daily_update.py --validate-only

# 强制执行全量下载（慎用！）
python daily_update.py --force
```

## ⚙️ 命令行参数详解

| 参数 | 说明 | 用途 |
|------|------|------|
| `--force` | 强制执行 | 忽略 latest_date.txt，下载全量数据 |
| `--dry-run` | 只检查不执行 | 预览模式，查看是否需要更新 |
| `--validate-only` | 仅验证 | 不更新，只检查数据完整性 |
| `--log-level DEBUG` | 调试级别 | 查看详细执行过程 |

**组合示例**：
```bash
# 查看需要更新什么（预览）
python daily_update.py --dry-run

# 强制全量并显示调试信息
python daily_update.py --force --log-level DEBUG
```

## 📊 日志文件

所有日志按日期命名，便于追溯：

| 文件 | 内容 |
|------|------|
| `logs/daily_update_YYYY-MM-DD.log` | 主日志（更新执行详情） |
| `logs/data_validation_YYYY-MM-DD.log` | 数据验证报告（CSV格式） |
| `logs/daily_update_errors.log` | 错误累积日志 |
| `logs/fetch_errors.log` | fetch_etf_universe.py 的错误日志 |

**查看最新日志**：
```bash
tail -f projects/a-share-etf-quant/logs/daily_update_$(date +%Y-%m-%d).log
```

## 🔔 飞书报警通知

更新失败时自动发送通知（可选配置）：

1. 创建飞书机器人（获取 Webhook URL）
   - 飞书群组 -> 添加机器人 -> 自定义机器人 -> 复制 Webhook

2. 设置环境变量：
   ```bash
   # 本地
   export FEISHU_WEBHOOK_URL="https://open.feishu.cn/open-apis/bot/v2/hook/..."

   # GitHub Actions
   # Settings -> Secrets and variables -> Actions -> New repository secret
   # Name: FEISHU_WEBHOOK_URL, Value: [你的webhook]
   ```

3. 测试通知：
   ```bash
   # 可以手动触发失败测试（暂不推荐）
   # 通知会在脚本重试3次失败后自动发送
   ```

## ⏰ GitHub Actions 自动化

### 配置步骤

1. 推送到 GitHub 仓库
2. 在仓库设置中添加 Secret `FEISHU_WEBHOOK_URL`（可选）
3. 确保 `requirements.txt` 已提交
4. 工作流自动启用

### 定时说明

- **运行时间**：工作日 16:00 北京时间
  - Cron: `0 8 * * 1-5` (UTC 08:00 = 北京时间 16:00)
- **触发条件**：
  - 定时调度
  - 手动触发（Actions 页面 -> Run workflow）
- **超时**：默认 6 小时（足够完成全量下载）

### 手动触发

```bash
# GitHub CLI
gh workflow run daily_update.yml -f force=true

# 或通过 Web 界面：
# 1. 进入仓库的 Actions 标签
# 2. 左侧选择 "Daily ETF Data Update"
# 3. 点击 "Run workflow" -> 选择 Force / Dry-run
```

### 故障排除

**Actions 失败常见原因**：
- akshore 安装失败（国内网络问题）
  - 解决：添加镜像 `pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`
- 网络超时（访问akshare）
  - 解决：增加重试次数或调整延迟
- Runner 磁盘空间不足
  - 解决：定期清理 artifacts（保留7天）

**查看日志**：
- Actions 页面点击失败的 workflow run
- 查看 "daily_update" step 的输出
- 或下载 "update-logs-XX" artifact

## 🧪 验证数据质量

### 自动验证（更新后自动执行）

更新完成后会自动运行数据验证，检查：
- ✅ 数据文件存在且非空
- ✅ 收盘价 > 0（排除停牌/异常）
- ✅ 成交量 >= 0
- ✅ 数据连续性（无 missing 交易日）

### 手动验证

```bash
python daily_update.py --validate-only
```

查看 `logs/data_validation_YYYY-MM-DD.log` 获取详细报告。

## 🔄 更新流程逻辑

```
开始
  ↓
读取 latest_date.txt 或 扫描 CSV 文件最大日期
  ↓
判断是否需要更新？
  ├── 是（首次 或 last_date < today）→ 执行更新
  │      ↓
  │   调用 fetch_etf_universe.py
  │      ├── 成功 → 更新 latest_date.txt
  │      └── 失败 → 重试3次（2/4/8秒延迟）
  │                  ↓
  │               发送飞书通知（如果配置）
  │                  ↓
  │               记录错误日志
  │                  ↓
  │               退出（失败）
  │
  └── 否 → 直接退出（成功）
  ↓
无论更新成功与否，都会执行数据验证
  ↓
结束，记录总日志
```

## 🐛 常见问题

**Q: 首次运行需要多长时间？**
A: 下载 80+ ETF × 10年数据，约 1-2 小时（受网络速度影响）。

**Q: 增量更新快吗？**
A: 通常只需几分钟（只下载新增交易日）。

**Q: latest_date.txt 可以手动修改吗？**
A: 可以，但需谨慎。设置为未来的日期会导致跳过更新；设置为过去日期会触发全量下载。

**Q: --force 和 --dry-run 一起用？**
A: `--dry-run` 优先级更高，只检查不执行。移除 `--dry-run` 即可强制执行。

**Q: 如何查看哪些ETF数据有问题？**
A: 查看 `logs/data_validation_YYYY-MM-DD.log`，包含每个ETF的详细验证结果。

## 📝 调试技巧

```bash
# 1. 查看脚本帮助
python daily_update.py --help

# 2. 查看 fetch_etf_universe.py 帮助
python fetch_etf_universe.py --help

# 3. 调试模式运行（详细输出）
python daily_update.py --log-level DEBUG --dry-run

# 4. 检查数据目录
ls -la data/day/ | wc -l  # 查看ETF数量

# 5. 查看某个ETF的数据
head -5 data/day/510300.csv

# 6. 查看最后更新日期
cat data/latest_date.txt
```

## 📞 支持

遇到问题？
1. 查看日志文件 `logs/daily_update_*.log`
2. 检查 GitHub Issues
3. 联系维护者

---

**最后更新**: 2025-03-06
**版本**: 1.0
