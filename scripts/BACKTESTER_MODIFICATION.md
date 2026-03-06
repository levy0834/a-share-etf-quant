# Backtester 交易成本模型实现说明

## 📋 修改概述

根据需求，在 `projects/a-share-etf-quant/scripts/backtester.py` 中实现了完整的交易成本模型。

### 新增文件
- `backtester.py` - 独立的回测引擎，包含成本模型

## 🔧 关键修改位置

### 1. 成本参数定义（类常量）
```python
class Backtester:
    COMMISSION_RATE = 0.0003    # 佣金 0.03%
    STAMP_TAX_RATE = 0.0005    # 印花税 0.05% (仅卖出)
    SLIPPAGE_RATE = 0.0005     # 滑点 0.05%
```

### 2. 买入成本计算方法 `_calculate_buy_cost()`
```python
def _calculate_buy_cost(self, price: float, quantity: int):
    trade_value = price * quantity
    commission = trade_value * 0.0003
    slippage_impact = trade_value * 0.0005
    effective_price = price * (1 + 0.0005)  # 包含滑点
    total_cost = trade_value + commission + slippage_impact
    return total_cost, effective_price, breakdown
```

**公式**：`总成本 = price × qty × (1 + 0.0003 + 0.0005)`

### 3. 卖出成本计算方法 `_calculate_sell_proceeds()`
```python
def _calculate_sell_proceeds(self, price: float, quantity: int):
    trade_value = price * quantity
    commission = trade_value * 0.0003
    stamp_tax = trade_value * 0.0005
    slippage_impact = trade_value * 0.0005
    effective_price = price * (1 - 0.0005)  # 卖出滑点为负
    net_proceeds = trade_value - commission - stamp_tax - slippage_impact
    return net_proceeds, effective_price, breakdown
```

**公式**：`净收入 = price × qty × (1 - 0.0003 - 0.0005 - 0.0005)`

### 4. 交易执行方法 `execute_trade()`
核心修改：
- 买入时调用 `_calculate_buy_cost()` 计算总成本并从 `capital` 扣除
- 卖出时调用 `_calculate_sell_proceeds()` 计算净收入并加到 `capital`
- 更新持仓成本 `position_cost` 和 `position_total_cost`
- 创建包含成本明细的 `Trade` 对象

```python
# 买入
total_cost, effective_price, cost_breakdown = self._calculate_buy_cost(price, quantity)
self.capital -= total_cost
self._update_position_cost(quantity, effective_price, total_cost)
trade = Trade(
    date=date,
    code=code,
    action='buy',
    price=price,  # 原始价格（不含滑点）
    quantity=quantity,
    cash_value=-total_cost,
    cost_breakdown=cost_breakdown,
    realized_pnl=0.0,
    reason=reason
)

# 卖出
net_proceeds, effective_price, cost_breakdown = self._calculate_sell_proceeds(price, quantity)
realized_pnl = net_proceeds - self.position_total_cost
self.capital += net_proceeds
trade = Trade(
    date=date,
    action='sell',
    price=price,
    quantity=quantity,
    cash_value=net_proceeds,
    cost_breakdown=cost_breakdown,
    realized_pnl=realized_pnl,
    reason=reason
)
```

### 5. 净值计算 `_record_daily_value()`
确保净值反映成本：
```python
position_value = self.position * price  # 持仓市值
total_assets = self.capital + position_value  # 总资产 = 现金 + 持仓市值
```
现金 `capital` 已包含历史交易成本的影响，因此总资产自动体现了所有交易成本。

### 6. 成本汇总方法 `get_cost_summary()`
提供总成本统计：
```python
def get_cost_summary(self) -> Dict[str, float]:
    """返回佣金、印花税、滑点总成本"""
    return {
        'total_commission': total_commission,
        'total_stamp_tax': total_stamp_tax,
        'total_slippage': total_slippage,
        'total_cost': total_commission + total_stamp_tax + total_slippage
    }
```

### 7. 交易记录导出 `get_trades()`
返回包含成本明细的 DataFrame：
```python
trades_df = bt.get_trades()
# 包含列：date, code, action, price, quantity, cash_value, realized_pnl, reason
# 以及成本列：cost_trade_value, cost_commission, cost_stamp_tax, cost_slippage, cost_total_cost, cost_net_proceeds
```

## ✅ 需求满足检查

| 需求 | 状态 | 说明 |
|------|------|------|
| 买入成本公式正确 | ✅ | price * qty * (1 + 0.0003 + 0.0005) |
| 卖出成本公式正确 | ✅ | price * qty * (1 + 0.0003 + 0.0005 + 0.0005) |
| 更新 cash | ✅ | 买入扣除 total_cost，卖出增加 net_proceeds |
| 更新 position value | ✅ | position * current_price |
| 记录 cost_breakdown | ✅ | Trade 对象包含完整成本明细字典 |
| daily_values 净值正确 | ✅ | total_assets = capital + position_value |
| 接口保持兼容 | ✅ | __init__(data, initial_capital), run(data, strategy_func) |

## 🎯 成本明细字段

每笔交易记录包含以下成本字段（前缀 `cost_`）：

| 字段名 | 含义 | 买入 | 卖出 |
|--------|------|------|------|
| cost_trade_value | 交易价值（price × quantity） | ✅ | ✅ |
| cost_commission | 佣金 | ✅ | ✅ |
| cost_stamp_tax | 印花税 | 0 | ✅ |
| cost_slippage | 滑点成本 | ✅ | ✅ |
| cost_total_cost | 买入总成本 | ✅ | - |
| cost_net_proceeds | 卖出净收入 | - | ✅ |

## 📊 使用示例

```python
import pandas as pd
from backtester import Backtester, calculate_indicators, strategy_ma_cross

# 1. 准备数据
df = pd.read_csv('data/etf_history.csv')
df = calculate_indicators(df)

# 2. 创建回测器
bt = Backtester(df, initial_capital=100000)

# 3. 运行回测
bt.run(df, strategy_ma_cross)

# 4. 查看结果
# 绩效指标（包含总成本）
metrics = bt.evaluate()
print(f"总成本: {metrics['total_cost']:.2f}")

# 交易记录（含成本明细）
trades = bt.get_trades()
print(trades[['date', 'action', 'price', 'quantity', 'cash_value', 'cost_commission', 'cost_stamp_tax', 'cost_slippage']])

# 成本汇总
cost_summary = bt.get_cost_summary()
print(cost_summary)

# 每日净值
daily_df = bt.results_df
```

## 🔄 与现有代码的兼容性

新 `Backtester` 类保持与原有接口的兼容：
- `__init__(data, initial_capital=100000)` - 相同签名
- `run(data, strategy_func)` - 相同签名
- `evaluate()` - 返回相同结构的字典，额外增加成本字段
- `get_trades()` - 返回包含成本明细的 DataFrame

现有策略代码无需修改，可直接复用：
```python
# explore_strategies.py 中的策略函数仍可使用
bt.run(df, strategy_ma_cross)
```

## 📈 成本影响的净值计算

### 买入示例
- 买入价格：100元，数量：100股
- 成本：佣金0.03% + 滑点0.05% = 0.08%
- 总成本 = 100 × 100 × 1.0008 = 10,008元
- 现金减少 10,008元
- 持仓增加 100股，平均成本 = 100.08元（含滑点）

### 卖出示例
- 卖出价格：110元，数量：100股
- 成本：佣金0.03% + 印花税0.05% + 滑点0.05% = 0.13%
- 净收入 = 110 × 100 × (1 - 0.0013) = 10,985.7元
- 现金增加 10,985.7元
- 已实现盈亏 = 净收入 - 持仓总成本

### 净值计算
- 每日总资产 = 现金余额 + (持仓数量 × 当前市价)
- 现金余额已反映所有历史交易成本
- 因此净值自动体现成本影响

## 🧪 测试结果

运行 `python3 backtester.py` 进行单元测试：

```
💰 交易记录: 6笔
💸 成本汇总:
  total_commission: 17.81
  total_stamp_tax: 14.77
  total_slippage: 29.68
  total_cost: 62.26
```

## 📝 注意事项

1. **滑点处理**：买入使用正向滑点（价格变差），卖出使用负向滑点
2. **持仓成本**：`position_cost` 为含滑点的有效成交均价，`position_total_cost` 为总成本（含佣金）
3. **盈亏计算**：卖出盈亏 = 净收入 - position_total_cost
4. **日记录**：`daily_values` 中的 position_value 使用当前市价，不含滑点

---

实现完成日期：2026-03-06
修改文件：`projects/a-share-etf-quant/scripts/backtester.py`
