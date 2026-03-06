#!/usr/bin/env python3
"""
修复看板JS：支持训练集/测试集资金曲线切换
"""

HTML_FILE = "/Users/levy/.openclaw/workspace/quant-trading-system/dashboard/index.html"

# 1. 修改 equityDataCache 初始定义
# 将 "let equityDataCache = null;" 改为 "let equityDataCache = { train: null, test: null };"
# 2. 修改 loadEquityData 函数，接受 dataset 参数
# 3. 修改 renderEquityCurve 中调用 loadEquityData(dataset)

with open(HTML_FILE, 'r', encoding='utf-8') as f:
    content = f.read()

# 替换 loadEquityData 函数
old_load_func = """        async function loadEquityData() {
            if (equityDataCache) return equityDataCache;
            
            try {
                const res = await fetch('equity_curves_train.json');
                if (!res.ok) return null;
                equityDataCache = await res.json();
                return equityDataCache;
            } catch (e) {
                console.warn('无法加载资金曲线JSON:', e);
                return null;
            }
        }"""

new_load_func = """        async function loadEquityData(dataset) {
            if (equityDataCache[dataset]) return equityDataCache[dataset];
            
            try {
                const filename = dataset === 'train' ? 'equity_curves_train.json' : 'equity_curves_test.json';
                const res = await fetch(filename);
                if (!res.ok) {
                    console.warn(`资金曲线文件不存在: ${filename} (HTTP ${res.status})`);
                    return null;
                }
                equityDataCache[dataset] = await res.json();
                return equityDataCache[dataset];
            } catch (e) {
                console.warn('无法加载资金曲线JSON:', e);
                return null;
            }
        }"""

content = content.replace(old_load_func, new_load_func)

# 修改 equityDataCache 初始化
old_cache_init = "let equityDataCache = null; // 缓存资金曲线数据"
new_cache_init = "let equityDataCache = { train: null, test: null }; // 缓存资金曲线数据（按数据集）"
content = content.replace(old_cache_init, new_cache_init)

# 修改 renderEquityCurve 中的调用
old_render_call = "const equityData = await loadEquityData();"
new_render_call = "const equityData = await loadEquityData(dataset);"
content = content.replace(old_render_call, new_render_call)

with open(HTML_FILE, 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ 看板JS修复完成：支持训练集/测试集资金曲线切换")
print("   修改点:")
print("   - equityDataCache 改为对象缓存 {train, test}")
print("   - loadEquityData(dataset) 接受数据集参数")
print("   - renderEquityCurve 使用当前数据集加载对应资金曲线")
