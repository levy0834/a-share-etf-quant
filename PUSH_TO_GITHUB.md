# 推送到GitHub完整指南

## 1. 创建GitHub仓库

1. 访问 https://github.com/new
2. 填写仓库名: `a-share-etf-quant`
3. 选择 Public 或 Private
4. **取消勾选** "Add a README file" 等选项
5. 点击 "Create repository"

## 2. 关联远程仓库并推送

在本地项目目录执行:

```bash
# 添加远程仓库地址（替换 YOUR-USERNAME 为你的GitHub用户名）
git remote add origin https://github.com/YOUR-USERNAME/a-share-etf-quant.git

# 推送代码到GitHub
git push -u origin main
```

如果你使用SSH:
```bash
git remote add origin git@github.com:YOUR-USERNAME/a-share-etf-quant.git
git push -u origin main
```

## 3. 配置GitHub Secrets（可选但推荐）

进入仓库 → Settings → Secrets and variables → Actions → New repository secret

添加以下Secrets:

| Name | Value | 说明 |
|------|-------|------|
| `CLAW_STREET_URL` | https://api.clawstreet.com/v1 | API地址（可选） |
| `CLAW_STREET_API_KEY` | your_api_key_here | 实盘API密钥（可选） |
| `FEISHU_WEBHOOK_URL` | https://open.feishu.cn/... | 飞书告警Webhook（可选） |

## 4. 验证CI运行

推送后，访问仓库的 **Actions** 标签页：

https://github.com/YOUR-USERNAME/a-share-etf-quant/actions

应看到正在运行的CI流水线：

```
Quant Trading System CI
  ├── security
  ├── test
  ├── docs
  ├── benchmark (仅main分支)
  └── pr-summary (仅PR)
```

所有检查通过后会有绿色勾勾 ✅

## 5. 测试CI功能

### 触发安全审计
CI会自动运行 `scripts/security_audit.py --fail-on-high`

### 触发测试
CI会运行：
- 语法检查
- 模块导入测试
- 回测烟雾测试

### 查看Artifacts
CI完成后，每个Job会生成Artifacts供下载:
- security-audit-report
- test-results
- benchmark-results
- documentation

## 6. 后续开发流程

1. 创建特性分支:
   ```bash
   git checkout -b feature/new-strategy
   ```

2. 修改代码并测试:
   ```bash
   python3 scripts/explore_strategies.py --ticker 510300
   python3 scripts/security_audit.py
   ```

3. 提交并推送:
   ```bash
   git add .
   git commit -m "feat: add new momentum strategy"
   git push origin feature/new-strategy
   ```

4. 创建Pull Request
   - GitHub会自动触发CI
   - 等待所有检查通过
   - 合并到main

## 7. 常见问题

### Q: CI运行失败怎么办？
A: 检查Actions日志，修复问题后重新Push。

### Q: 如何跳过CI？
A: 在commit message中添加 `[skip ci]` 或 `[ci skip]`。

### Q: Secrets如何更新？
A: Settings → Secrets → 编辑或删除后重新添加。

### Q: 通知如何发送到飞书？
A: 需配置 `FEISHU_WEBHOOK_URL` secret，并在 `monitoring/alert.py` 中使用。

---

**祝编码愉快！** 🚀
