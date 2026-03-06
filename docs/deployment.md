# 生产环境部署与监控

本文档说明如何将 **A股ETF量化系统** 部署到生产环境，包括环境配置、自动化更新、监控告警和故障恢复。

---

## 🚀 生产环境配置

### 环境变量清单

生产环境必须配置以下环境变量：

| 变量名 | 必须 | 用途 | 示例值 | 配置位置 |
|--------|------|------|--------|---------|
| `CLAW_STREET_URL` | ✅ | Claw Street API地址 | `https://api.clawstreet.com/v1` | `.env` / shell / GitHub Secrets |
| `FEISHU_WEBHOOK_URL` | ⚠️推荐 | 飞书机器人webhook（失败告警） | `https://open.feishu.cn/open-apis/bot/v2/hook/xxx` | GitHub Secrets |
| `AKSHARE_PROXY` | ⚠️可选 | akshare代理（国内网络可能需要） | `http://127.0.0.1:7890` | `.env` |
| `LOG_LEVEL` | ❌ | 日志级别（DEBUG/INFO/WARNING/ERROR） | `INFO` | `.env` |
| `PYTHONUNBUFFERED` | ❌ | Python输出缓冲控制 | `1` | `.env` |

### .env 配置文件模板

```bash
# 项目根目录创建 .env 文件（Git ignore，勿提交到仓库）
cat > .env << 'EOF'
# ============================================
# Claw Street API 配置
# ============================================
CLAW_STREET_URL=https://api.clawstreet.com/v1
export CLAW_STREET_URL

# ============================================
# 飞书通知webhook（用于失败告警）
# 获取方式：飞书开放平台 -> 机器人 -> 添加机器人 -> 获取webhook地址
# ============================================
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
export FEISHU_WEBHOOK_URL

# ============================================
# 代理配置（如需要）
# 国内网络访问akshare可能需要代理
# ============================================
# AKSHARE_PROXY=http://127.0.0.1:7890
# export AKSHARE_PROXY

# ============================================
# 日志与运行配置
# ============================================
LOG_LEVEL=INFO
export LOG_LEVEL
PYTHONUNBUFFERED=1
export PYTHONUNBUFFERED
EOF
```

**加载.env文件**：
```bash
# 方式1：source加载（bash/zsh）
source .env

# 方式2：使用python-dotenv（自动加载）
pip install python-dotenv
# 在脚本开头添加：
# from dotenv import load_dotenv
# load_dotenv()
```

---

## ⏰ crontab 配置（本地部署）

如果你的服务器是Linux/macOS，可以使用crontab实现每日定时更新。

### crontab 时间设置

**目标**：每日**北京时间16:00**自动运行 `daily_update.py`

**注意**：crontab使用系统时间（通常是UTC或本地时区）
- 北京时间 = UTC+8
- 如果系统时区是Asia/Shanghai，直接设置 `0 16 * * 1-5`
- 如果系统时区是UTC，需要设置 `0 8 * * 1-5`

### crontab 条目示例

```bash
# 编辑crontab
crontab -e

# 添加以下行（假设系统时区为Asia/Shanghai）
0 16 * * 1-5 cd /path/to/a-share-etf-quant && /usr/bin/python3 scripts/daily_update.py >> logs/cron.log 2>&1

# 或者明确指定python路径（推荐）
0 16 * * 1-5 cd /Users/levy/.openclaw/workspace/projects/a-share-etf-quant && /usr/bin/env python3 scripts/daily_update.py >> logs/cron_$(date +\%Y\%m\%d).log 2>&1
```

### crontab 说明

| 字段 | 值 | 含义 |
|------|-----|------|
| 分钟 | `0` | 0分 |
| 小时 | `16` | 16点（北京时间下午4点） |
| 日 | `*` | 每天 |
| 月 | `*` | 每月 |
| 星期 | `1-5` | 周一到周五（工作日） |
| 命令 | `cd ... && python ...` | 切换到项目目录并执行脚本 |

**日志重定向**：
- `>> logs/cron.log` - 追加日志到cron.log
- `2>&1` - 标准错误也重定向到同一文件

### 验证crontab

```bash
# 查看crontab列表
crontab -l

# 查看cron执行日志（Ubuntu/Debian）
grep CRON /var/log/syslog | tail -20

# macOS
tail -f /var/log/system.log | grep cron

# 测试crontab语法
crontab -l | crontab -  # 如果报错则语法有误
```

---

## 🔄 GitHub Actions CI 自动化

项目已包含 `.github/workflows/daily_update.yml`，配置GitHub Actions实现云端自动化。

### 配置步骤

1. **Push到GitHub仓库**
   ```bash
   cd /Users/levy/.openclaw/workspace/projects/a-share-etf-quant
   git init  # 如未初始化
   git remote add origin https://github.com/yourusername/a-share-etf-quant.git
   git add .
   git commit -m "Initial commit"
   git push -u origin main
   ```

2. **添加Secrets**
   - 进入仓库：GitHub -> **Settings** -> **Secrets and variables** -> **Actions**
   - 点击 **New repository secret**
   - 添加：
     - `FEISHU_WEBHOOK_URL` - 飞书webhook（可选但推荐）
     - （如有其他API密钥）`CLAW_STREET_API_KEY`等

3. **工作流自动运行**
   - 每天北京时间16:00（UTC 8:00）自动触发
   - 也可手动触发：GitHub -> Actions -> "Daily ETF Data Update" -> Run workflow

### workflow详解

```yaml
name: Daily ETF Data Update

on:
  schedule:
    - cron: '0 8 * * 1-5'  # UTC 8:00 = 北京时间16:00，周一至周五
  workflow_dispatch:      # 允许手动触发
    inputs:
      force:
        description: 'Force full download'
        type: boolean
        default: false
      dry_run:
        description: 'Dry run (check only)'
        type: boolean
        default: false

jobs:
  daily-update:
    runs-on: ubuntu-latest
    env:
      FEISHU_WEBHOOK_URL: ${{ secrets.FEISHU_WEBHOOK_URL }}
      PYTHON_VERSION: '3.11'

    steps:
    - name: Checkout repository
      uses: actions/checkout@v4

    - name: Set up Python
      uses: actions/setup-python@v5
      with:
        python-version: ${{ env.PYTHON_VERSION }}
        cache: 'pip'

    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install akshare pandas tqdm requests

    - name: Create necessary directories
      run: |
        mkdir -p data/day logs

    - name: Run daily update
      run: |
        cd projects/a-share-etf-quant/scripts
        ARGS=""
        if "${{ github.event.inputs.force == 'true' }}"; then
          ARGS="--force"
        fi
        if "${{ github.event.inputs.dry_run == 'true' }}"; then
          ARGS="--dry-run"
        fi
        python daily_update.py $ARGS

    - name: Upload logs
      if: always()
      uses: actions/upload-artifact@v4
      with:
        name: update-logs-${{ github.run_number }}
        path: |
          projects/a-share-etf-quant/logs/*.log
          projects/a-share-etf-quant/data/latest_date.txt
        retention-days: 7

    - name: Notify failure (optional)
      if: failure() && env.FEISHU_WEBHOOK_URL != ''
      run: |
        echo "更新失败，已通过飞书通知"
```

### 手动触发

```bash
# 在GitHub UI中操作：
# 1. 进入仓库的 Actions 标签页
# 2. 左侧选择 "Daily ETF Data Update"
# 3. 点击 "Run workflow" -> 选择参数 -> "Run workflow"
```

或使用GitHub CLI：

```bash
gh workflow run daily_update.yml -f force=true
```

---

## 📢 监控告警设置

### 飞书机器人通知

#### 创建飞书机器人

1. 打开飞书，进入群聊（或创建一个"量化监控群"）
2. 点击右上角... -> 添加机器人 -> 自定义机器人
3. 设置名称（如"ETF量化监控"）
4. 选择触发条件：**所有消息** 或 **关键字**
5. 复制webhook URL（格式：`https://open.feishu.cn/open-apis/bot/v2/hook/...`）
6. 点击完成

#### 配置webhook

```bash
# 方式1：添加到GitHub Secrets（推荐）
# Settings -> Secrets and variables -> Actions -> New repository secret
# Name: FEISHU_WEBHOOK_URL
# Value: （粘贴webhook URL）

# 方式2：添加到本地.env文件
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxxxx
```

#### 飞书消息格式

脚本自动发送的消息格式：

```json
{
  "msg_type": "interactive",
  "card": {
    "config": { "wide_screen_mode": true },
    "elements": [
      {
        "tag": "div",
        "text": { "content": "📊 ETF数据更新状态", "tag": "lark_md" }
      },
      {
        "tag": "div",
        "text": { "content": "✅ 成功", "tag": "lark_md" }
      },
      {
        "tag": "div",
        "text": { "content": "更新时间: 2024-03-06 16:00:00\n共更新: 5只ETF", "tag": "lark_md" }
      }
    ]
  }
}
```

失败时发送错误摘要和日志链接。

### 日志监控

#### 关键日志文件

```
logs/
├── daily_update_2024-03-06.log     # 每日更新（成功/失败详情）
├── data_validation_2024-03-06.log  # 数据验证报告
├── claw_street_client.log          # API客户端日志
└── errors.log                      # 全局错误汇总（如有）
```

#### 监控要点

1. **每日更新成功率**：应接近100%
   ```bash
   grep "完成" logs/daily_update_*.log | wc -l
   ```

2. **数据完整性**
   ```bash
   cat data/latest_date.txt  # 应显示最新日期
   ```

3. **错误日志**
   ```bash
   # 查看最近错误
   tail -50 logs/daily_update_*.log | grep -i error
   ```

4. **磁盘空间**（避免数据堆积）
   ```bash
   df -h .  # 确保至少有1GB剩余空间
   ```

#### 日志轮转（Log Rotation）

配置logrotate自动清理旧日志：

```bash
# /etc/logrotate.d/a-share-etf-quant
/Users/levy/.openclaw/workspace/projects/a-share-etf-quant/logs/*.log {
  daily
  rotate 30        # 保留30天
  compress         # 压缩旧日志
  delaycompress    # 延迟压缩（下一次才压缩）
  missingok
  notifempty
  create 644 levy staff
  sharedscripts
  postrotate
    # 可选：发送日志轮转通知
  endscript
}
```

---

## 🆘 故障恢复步骤

### 故障1：数据更新失败

**现象**：`daily_update.py` 报错退出，或数据文件日期未更新

**排查步骤**：

1. **查看错误日志**
   ```bash
   tail -100 logs/daily_update_$(date +%Y-%m-%d).log | grep -A 5 -B 5 ERROR
   ```

2. **常见错误及修复**

| 错误信息 | 可能原因 | 解决方案 |
|---------|---------|---------|
| `akshare` 请求超时 | 网络问题或API限制 | 稍后重试（`--force`），或使用代理 |
| `IndexError: single positional indexer` | 数据格式变化（akshare接口变更） | 更新 `fetch_etf_universe.py`，查看akshare最新API |
| `Permission denied` | 数据目录无写入权限 | `chmod -R u+w data/ logs/` |
| `disk full` | 磁盘空间不足 | 清理旧日志，`rm logs/*.log` 或扩大磁盘 |

3. **强制全量更新**
   ```bash
   python scripts/daily_update.py --force
   ```

4. **数据验证**
   ```bash
   python scripts/daily_update.py --validate-only
   ```

5. **回滚到上一版本**
   ```bash
   # 如果有备份
   cp data/backup/etf_history_2024-03-05.csv data/raw/etf_history_2015_2025.csv
   ```

---

### 故障2：回测结果异常（如NaN、零收益）

**可能原因及检查**：

1. **数据缺失**
   ```bash
   python scripts/test_data_availability.py
   ```

2. **指标计算失败**
   - 检查数据长度是否足够（如MA60需要至少60个点）
   - 查看是否所有必要列都存在：`date, open, high, low, close, volume`

3. **策略信号全为hold**
   - 策略条件过于严格，检查阈值
   - 在 `explore_strategies.py` 中添加调试打印

4. **修复后的测试**
   ```bash
   # 快速验证回测
   python scripts/explore_strategies.py --strategy kdj_cross --quick
   ```

---

### 故障3：GitHub Actions 失败

**查看Actions日志**：

1. 进入仓库 **Actions** 标签
2. 点击失败的workflow运行记录
3. 查看 **"Run daily update"** 步骤的日志

**常见失败原因**：

| 原因 | 特征 | 修复 |
|------|------|------|
| akshare依赖过时 | `ModuleNotFoundError` 或 `AttributeError` | 更新requirements.txt中的版本，提交并重新运行 |
| 网络问题 | `ConnectionError` / `Timeout` | Actions在美国服务器，akshare可能不稳定，考虑切换数据源或增加重试 |
| 磁盘空间不足 | `No space left on device` | Actions默认7GB，清理artifact或缩短保留期 |
| 权限问题 | 访问data目录失败 | 确保 `mkdir -p` 已创建目录 |

**手动重试**：
- Actions页面点击 "Re-run all jobs"

---

### 故障4：飞书通知未发送

**检查清单**：

1. `FEISHU_WEBHOOK_URL` 是否正确设置？
   ```bash
   echo $FEISHU_WEBHOOK_URL  # 应显示URL，非空
   ```

2. webhook是否有效？
   ```bash
   curl -X POST "$FEISHU_WEBHOOK_URL" \
     -H "Content-Type: application/json" \
     -d '{"msg_type":"text","content":{"text":"测试"}}'
   ```

3. 飞书群是否禁用了机器人？
   - 检查群设置中的机器人列表

4. 脚本中是否启用通知？
   - `daily_update.py` 默认失败时发送，确保变量已导出

---

## 🔄 数据备份与恢复

### 自动备份（可选）

使用简单脚本定期备份关键数据：

```bash
#!/bin/bash
# backup_data.sh
BACKUP_DIR="/path/to/backup"
DATE=$(date +%Y%m%d)
tar -czf "$BACKUP_DIR/etf_quant_backup_$DATE.tar.gz" \
    data/raw/ \
    data/accounts/ \
    logs/ \
    results/ \
    --exclude='data/raw/*.csv'  # 可选：排除大文件
```

添加到crontab（每周日凌晨2点）：
```
0 2 * * 0 /path/to/backup_data.sh
```

### 手动恢复

```bash
# 1. 停止所有运行中的任务
pkill -f "explore_strategies.py"

# 2. 恢复数据
cp backup/data/raw/etf_history_*.csv projects/a-share-etf-quant/data/raw/

# 3. 恢复账户状态（如有）
cp backup/data/accounts/* projects/a-share-etf-quant/data/accounts/

# 4. 验证数据
python scripts/test_data_availability.py

# 5. 重新运行一次更新
python scripts/daily_update.py --force
```

---

## 📊 健康检查清单

### 每日检查（5分钟）

- [ ] `daily_update.py` 是否成功运行（查看日志或GitHub Actions状态）
- [ ] `data/latest_date.txt` 是否更新到今日/昨日
- [ ] 数据文件大小是否正常（`ls -lh data/raw/*.csv`）
- [ ] 收到的飞书通知（如有）是否正常

### 每周检查（15分钟）

- [ ] 查看 `logs/` 是否有异常错误堆积
- [ ] 检查磁盘空间：`df -h .`
- [ ] 运行一次完整回测：`python explore_strategies.py`，验证结果是否合理
- [ ] 查看 `results/performance_summary.csv`，策略表现是否稳定

### 每月检查（30分钟）

- [ ] 审视各策略绩效，是否有显著退化
- [ ] 调整策略参数（如需要，基于最新数据重新优化）
- [ ] 清理超过30天的日志：`find logs -name "*.log" -mtime +30 -delete`
- [ ] 更新 `requirements.txt`（如有依赖更新）

---

## 🔐 安全建议

1. **保护 Secrets**
   - 不要将 `FEISHU_WEBHOOK_URL`、`CLAW_STREET_URL` 等硬编码在代码中
   - 使用 `.env`（gitignore）或CI Secrets
   - 定期轮换apikey（如有）

2. **最小权限原则**
   - GitHub Actions 仅添加必要Secrets
   - 数据库/API密钥权限最小化

3. **网络隔离**
   - 如部署在云服务器，配置安全组仅允许必要的出站流量
   - 考虑使用VPC或私有网络

4. **数据加密**
   - 敏感日志（含API密钥）加密存储
   - 定期清理日志中的敏感信息

---

## 🧪 预发布检查

在上线前，确认以下事项：

- [ ] 所有环境变量已正确配置（`.env` 或 CI Secrets）
- [ ] 依赖已安装：`pip install -r requirements.txt`
- [ ] 首次数据抓取已完成：`python fetch_etf_data.py`
- [ ] 回测脚本可正常运行：`python explore_strategies.py`
- [ ] `daily_update.py --dry-run` 无错误
- [ ] crontab或GitHub Actions已配置
- [ ] 飞书通知测试成功
- [ ] 磁盘空间充足（至少2GB）
- [ ] 日志轮转已配置

---

## 📚 相关文档

- **[README.md](README.md)** - 项目快速入门
- **[architecture.md](architecture.md)** - 系统架构详解
- **[strategy_guide.md](strategy_guide.md)** - 策略开发指南

---

**祝部署顺利！** 🚀

遇到问题请参考 [RUN_INSTRUCTIONS.md](../RUN_INSTRUCTIONS.md) 和 [TROUBLESHOOTING.md](../scripts/TROUBLESHOOTING.md)
