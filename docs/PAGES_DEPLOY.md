# 📊 GitHub Pages 部署指南

## 快速访问

**看板地址**（启用GitHub Pages后）:
```
https://levy0834.github.io/a-share-etf-quant/
```

或访问仓库 → Settings → Pages 查看实际URL。

---

## 启用步骤

1. **确认文件存在**
   - 确保 `docs/analysis.html` 已推送至GitHub
   - 该文件是完整的静态看板（Chart.js图表）

2. **配置 Pages**
   - 进入仓库 Settings → Pages
   - Source: `main` 分支, `/docs` 文件夹
   - 点击 Save

3. **等待部署**
   - 通常 1-2 分钟
   - 状态显示 "Your site is live at ..."

4. **访问看板**
   - 打开生成的 URL (通常是 `https://你的用户名.github.io/仓库名/`)
   - 看到策略排名、KPI卡片、收益柱状图

---

## 更新看板数据

当前 `analysis.html` 使用**示例数据**。要更新为真实回测结果：

1. 在本地运行回测生成数据：
   ```bash
   python3 scripts/explore_strategies.py --parallel
   ```

2. 将结果文件复制到 `docs/` 目录：
   ```bash
   cp results/strategy_comparison_summary.csv docs/
   ```

3. 修改 `docs/analysis.html` 中的 JavaScript 部分（第385-420行），将 `strategyData` 和 `top10Data` 替换为真实数据。

4. 提交并推送：
   ```bash
   git add docs/analysis.html
   git commit -m "update: dashboard with latest backtest results"
   git push origin main
   ```

5. GitHub Pages 会自动重新部署（约1分钟）。

---

## 自定义看板

### 修改图表类型
在 `analysis.html` 的 Chart.js 配置区域（第451行附近）：
```javascript
type: 'bar',  // 改为 'line', 'pie', 'doughnut' 等
```

### 添加更多KPI
在 HTML 的 `.kpi-grid` 区域复制粘贴卡片，然后在第335行左右的JS中更新数据。

### 更改颜色主题
修改 `<style>` 区域的 `.container` 背景色和渐变。

---

## 故障排除

| 问题 | 解决方案 |
|------|----------|
| 404 Not Found | 确认 Pages 设置中是 `/docs` 文件夹，不是 `/` 或 `/public` |
| 样式丢失 | Chart.js CDN 被墙 → 更换为国内CDN: `https://cdn.bootcdn.net/ajax/libs/chart.js/4.4.0/chart.umd.min.js` |
| 数据不显示 | 检查浏览器Console (F12)，确保 JS 没有报错 |
| 部署慢 | 大文件（如图片）会拖慢，当前版本无外部图片，纯CDN加载 |

---

## 高级用法（可选）

### 自动部署脚本
创建 `.github/workflows/pages-deploy.yml`:
```yaml
name: Deploy to GitHub Pages
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Copy files
        run: |
          cp -r docs/ public/
      - name: Deploy
        uses: peaceiris/actions-gh-pages@v3
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: ./public
```

---

**提示**: 完整文档见 `docs/README.md` 和 `docs/deployment.md`。
