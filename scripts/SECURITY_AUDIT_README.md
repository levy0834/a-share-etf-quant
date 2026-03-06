# 安全审计脚本 - Security Audit Script

扫描代码库中的安全风险,包括硬编码密钥、配置文件问题和环境变量使用。

## 功能特性

### 1. 硬编码密钥检测
- 使用正则表达式匹配常见敏感信息:
  - API Keys (包括 OpenAI/Step、Stripe、GitHub Tokens)
  - 数据库连接字符串
  - 私钥 (RSA、DSA、EC、OpenSSH)
  - OAuth 凭证
  - JWT Tokens
  - AWS 凭证
- 智能过滤误报 (跳过示例代码、测试文件、占位符)
- 精确的文件定位 (文件名、行号)

### 2. .gitignore 配置检查
- 验证敏感文件是否被正确忽略:
  - `.env`
  - `credentials.json`
  - `secrets/`
  - `.env.*`
  - `*.pem`, `*.key`, `*.secret`
- 发现缺失规则时提供修复建议

### 3. 环境变量审计
- 扫描 `os.getenv()` 调用
- 识别敏感环境变量 (API、KEY、SECRET 等前缀)
- 检测未设置默认值的必需配置
- 列出使用环境变量的文件清单

### 4. CI/CD 集成
- 自动生成 GitHub Actions 工作流配置 (`.github/workflows/security-audit.yml`)
- PR 触发扫描
- 高风险问题阻塞合并
- 自动上传报告作为 Artifact

## 使用方法

### 基本扫描

```bash
cd /path/to/projects/a-share-etf-quant
python scripts/security_audit.py
```

### 指定扫描目录

```bash
python scripts/security_audit.py --path /custom/project/path
```

### CI 模式 (PR 时阻塞)

```bash
python scripts/security_audit.py --fail-on-high
```

- 发现 CRITICAL 或 HIGH 风险时退出码为 1
- 仅发现 MEDIUM 及以下风险时退出码为 0

### 自定义输出路径

```bash
python scripts/security_audit.py --output /path/to/custom/report.txt
```

### 跳过 CI 配置生成

```bash
python scripts/security_audit.py --skip-ci
```

## 报告示例

```
================================================================================
安全审计报告 - Security Audit Report
================================================================================
生成时间: 2025-12-19 10:30:00
项目目录: /path/to/project

扫描统计:
  总计发现: 3
  HIGH: 1
  MEDIUM: 1
  LOW: 1

详细发现:
================================================================================

--- HIGH 风险等级 ---

[1] API Key
文件: virtual_account.py
行号: 42
描述: Hardcoded API key found: api_key = "sk-xxxxxxxx"
修复建议: 使用环境变量 `os.getenv('API_KEY')` 替代硬编码

--- MEDIUM 风险等级 ---

[2] ENV_VAR
变量: DATABASE_PASSWORD
文件: config.py, app.py
描述: 环境变量 DATABASE_PASSWORD 在 2 个文件中使用 (未设置默认值)
修复建议: 为 os.getenv() 提供默认值或确保在生产环境中设置

================================================================================
总结与建议
================================================================================
...
```

## 集成到 CI/CD

### GitHub Actions

脚本会自动创建 `.github/workflows/security-audit.yml`:

```yaml
name: Security Audit

on:
  pull_request:
    branches: [ main, develop ]
  push:
    branches: [ main ]

jobs:
  security-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: python scripts/security_audit.py --fail-on-high
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: security-audit-report
          path: security/audit_report_*.txt
```

### 阻塞规则

在 PR 中:
- 发现 CRITICAL 或 HIGH → ❌ 合并阻塞
- 仅 MEDIUM/LOW → ✅ 允许合并

## 风险等级说明

| 等级    | 说明                                                                 | 处理方式          |
|---------|----------------------------------------------------------------------|-------------------|
| CRITICAL| 私钥、数据库连接字符串等立即泄露风险                                 | 立即修复,不可合并 |
| HIGH    | API Keys、Tokens 等高风险凭证                                        | 修复前阻塞合并    |
| MEDIUM  | 敏感环境变量未设置默认、gitignore 缺失                               | 建议修复          |
| LOW     | 低风险配置问题、通用 Key (需人工判断)                               | 可选修复          |
| INFO    | 信息性发现 (如 CI 配置建议)                                         | 仅记录,不阻塞    |

## 排除模式

自动忽略以下内容:
- `.git/` 目录
- 测试文件 (`test_*.py`, `tests/`)
- 示例文件 (`example_*.py`, `examples/`)
- 常见依赖目录 (`node_modules`, `venv`, `.venv`)
- 构建产物 (`dist`, `build`, `target`)
- IDE 配置 (`.idea`, `.vscode`)
- 历史安全报告 (`security/`)

## 误报过滤

脚本会自动跳过:
- 包含 `example`、`sample`、`dummy`、`placeholder` 的行
- 注释行
- 明显占位符 (`XXX`, `TODO`, `FIXME`)
- 文档字符串

## 报告解读

### 发现类型

| 类型              | 说明                                      |
|-------------------|-------------------------------------------|
| `API Key`         | 检测到 API 密钥格式                       |
| `Stripe Key`      | Stripe 格式密钥 (sk_/pk_)                 |
| `Auth Token`      | 认证令牌                                  |
| `Secret`          | Secret 关键字                             |
| `Password`        | 密码关键字                                |
| `Database Connection String` | 数据库连接 URL                |
| `Private Key`     | PEM 格式私钥                              |
| `GitHub Personal Access Token` | GitHub PAT              |
| `ENV_VAR`         | 敏感环境变量使用                          |
| `GITIGNORE_MISSING`| .gitignore 缺少规则                     |
| `CI_NO_SECURITY`  | CI 配置中缺少安全扫描                     |

## 最佳实践

1. **使用密钥管理服务** (AWS Secrets Manager, HashiCorp Vault, Azure Key Vault)
2. **为每个服务使用独立密钥**,定期轮换
3. **本地开发使用环境变量**,Never commit `.env`
4. **添加预提交钩子**:
   ```bash
   # .git/hooks/pre-commit
   python scripts/security_audit.py --fail-on-high
   ```
5. **在 CI 中强制阻塞**高风险发现
6. **定期审计** (建议每次发布前运行)

## 文件结构

```
projects/a-share-etf-quant/
├── scripts/
│   └── security_audit.py    # 主脚本
├── .github/
│   └── workflows/
│       └── security-audit.yml  # CI 配置 (自动生成)
└── security/
    └── audit_report_YYYY-MM-DD.txt  # 每日审计报告 (自动生成)
```

## 故障排除

### 误报太多
调整 `FALSE_POSITIVE_INDICATORS` 列表,或修改 `is_likely_false_positive()` 函数。

### 漏报某些类型的密钥
在 `SECRET_PATTERNS` 列表中添加新的正则表达式。

### 扫描速度慢
修改 `SCAN_EXTENSIONS` 限制扫描的文件类型,或调整忽略目录。

## 许可证

MIT License - 可自由修改和分发

## 维护

- 定期更新 `SECRET_PATTERNS` 以适应新的密钥格式
- 审查误报模式,减少噪音
- 根据项目需求调整风险等级规则

---

**⚠️ 重要提示**: 此脚本仅用于检测潜在问题。发现密钥后立即轮换并撤销! Never commit real credentials to git.
