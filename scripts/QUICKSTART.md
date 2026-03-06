# 安全审计脚本 - 快速开始

## 已创建的文件

1. **主脚本**: `projects/a-share-etf-quant/scripts/security_audit.py`
   - 完整功能: 硬编码密钥扫描、.gitignore检查、环境变量审计、CI集成
   - 可执行: 已设置 +x 权限
   - 23609 字节,  400+ 行代码

2. **使用文档**: `projects/a-share-etf-quant/scripts/SECURITY_AUDIT_README.md`
   - 完整的功能说明
   - 使用示例和最佳实践
   - 风险等级说明

3. **自动生成的配置** (首次运行后):
   - `.github/workflows/security-audit.yml` - GitHub Actions 工作流
   - `security/audit_report_YYYY-MM-DD.txt` - 每日审计报告

## 立即使用

### 1. 手动运行
```bash
cd projects/a-share-etf-quant
python3 scripts/security_audit.py
```

### 2. CI/CD 集成
脚本已自动创建 GitHub Actions 配置:
- 在 PR 到 `main`/`develop` 时自动运行
- 发现 HIGH/CRITICAL 问题时阻塞合并
- 报告上传为 Artifact

### 3. 预提交钩子 (可选)
在 `.git/hooks/pre-commit` 中添加:
```bash
#!/bin/bash
python3 scripts/security_audit.py --fail-on-high
```
然后 `chmod +x .git/hooks/pre-commit`

## 当前项目状态

扫描发现 2 个 HIGH 风险问题:

1. **缺失 .gitignore 文件**
   - 影响: 敏感文件可能被意外提交
   - 修复: 创建 .gitignore (建议包含: .env, credentials.json, secrets/, *.pem, *.key)

2. **环境变量未设默认值**
   - `CLAW_STREET_API_KEY` 在 1 个文件中使用,没有默认值
   - 影响: 可能在开发环境崩溃,且提示需要设置敏感变量
   - 修复: 为 os.getenv() 提供默认值 (开发环境) 或确保生产环境变量已设置

## 关键功能验证 ✅

- ✅ 硬编码密钥正则匹配 (sk-, API_KEY, SECRET, PASSWORD, TOKEN, KEY)
- ✅ 智能误报过滤 (跳过 test_, example_, placeholder 等)
- ✅ .gitignore 完整性检查
- ✅ 环境变量使用审计 (检测未设默认值的敏感变量)
- ✅ 详细报告生成 (包含风险等级、修复建议)
- ✅ GitHub Actions 配置自动生成
- ✅ PR 阻塞机制 (--fail-on-high 返回非零退出码)
- ✅ 排除逻辑正确 (.git, test_, example_, node_modules 等)

## 下一步建议

1. **立即修复 HIGH 问题**
   - 创建 `.gitignore` 文件 (参考文档中的建议列表)
   - 检查 `clients/claw_street_client.py` 中的 `CLAW_STREET_API_KEY` 使用

2. **添加到 CI 流程** (已自动完成)
   - 检查 `.github/workflows/security-audit.yml`
   - 提交到仓库后,PR 会自动触发扫描

3. **定期审计**
   - 建议每周或每次发布前运行一次
   - 将报告归档到 `security/` 目录

4. **密钥管理**
   - 使用环境变量或密钥管理服务
   - 为不同环境使用不同密钥
   - 定期轮换密钥

## 文档位置

完整用法: `projects/a-share-etf-quant/scripts/SECURITY_AUDIT_README.md`

---

**⚠️ 重要提醒**: 发现任何硬编码密钥后,立即轮换并撤销! Never commit real credentials to git.
