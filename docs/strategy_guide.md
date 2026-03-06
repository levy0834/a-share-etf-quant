# 策略开发指南

本指南详细说明如何在 **A股ETF量化系统** 中开发、测试和评估量化交易策略。

---

## 🎯 策略开发总览

### 策略定义

在系统中，**策略** 是一个接收单日数据并产生交易信号的纯函数：

```python
def strategy_name(row: pd.Series, context: Dict = None) -> str:
    """
    返回: 'buy' | 'sell' | 'hold'
    """
    # 你的逻辑
    return signal
```

### 策略函数签名

```python
from typing import Dict, Any
import pandas as pd
import numpy as np

def my_strategy(row: pd.Series, context: Dict[str, Any] = None) -> str:
    """
    我的策略描述

    参数:
        row: 包含以下字段的pandas Series
            - OHLCV: open, high, low, close, volume
            - 技术指标: ma5, ma20, rsi, atr_14, kdj_k, kdj_d...
            - 其他预计算字段
        context: 上下文字典（可选），用于保存状态
            - 例如：{'previous_signal': 'buy', 'days_in_position': 5}

    返回:
        'buy'    - 买入信号
        'sell'   - 卖出信号
        'hold'   - 持有（无操作）
    """
    # 1. 安全提取指标（防止KeyError）
    close = row.get('close', np.nan)
    ma20 = row.get('ma20', np.nan)

    # 2. 检查数据是否有效
    if pd.isna(close) or pd.isna(ma20):
        return 'hold'

    # 3. 策略逻辑
    if close > ma20:
        return 'buy'
    elif close < ma20:
        return 'sell'
    else:
        return 'hold'
```

---

## 📚 现有策略库（20+种）

系统内置 **8种经典策略**，涵盖趋势跟踪、均值回归、形态识别等多种类型：

### 1. KDJ随机指标金叉死叉 (`kdj_cross`)

**类型**：震荡指标  
**逻辑**：
- K（快线）上穿D（慢线）→ `buy`
- K下穿D → `sell`
- 其他 → `hold`

**指标依赖**：`kdj_k`, `kdj_d`, `kdj_k_prev`, `kdj_d_prev`  
**参数**：KDJ周期（9,3,3）已固定  
**适用场景**：震荡市、盘整行情

```python
# 示例信号历史
Date        close    kdj_k    kdj_d    signal
2024-01-02  3.50     45.2     42.1     hold
2024-01-03  3.55     52.3     45.2     buy   # 金叉
2024-01-04  3.58     58.7     52.3     hold
2024-01-05  3.52     45.1     58.7     sell  # 死叉
```

---

### 2. ATR通道突破 (`atr_channel`)

**类型**：波动率通道  
**逻辑**：
- 价格突破 `MA20 + 2*ATR(14)` → `buy`
- 价格跌破 `MA20 - 2*ATR(14)` → `sell`
- 其他 → `hold`

**指标依赖**：`close`, `ma20`, `atr_14`  
**参数**：ATR周期14，通道倍数2  
**适用场景**：趋势行情、波动率扩大

**特点**：
- 通道宽度自适应（基于ATR）
- 假信号较少
- 适合趋势跟踪

---

### 3. OBV能量潮背离 (`obv`)

**类型**：量价背离  
**逻辑**：
- 价格创新高 + OBV未创新高 → 看跌背离 → `sell`
- 价格创新低 + OBV未创新低 → 看涨背离 → `buy`

**指标依赖**：`close`, `obv`, `price_20_high`, `obv_20_high`, `price_20_low`, `obv_20_low`  
**参数**：20日滚动窗口  
**适用场景**：趋势反转预警

**背离判断**：
```python
# 看涨背离
if close <= price_20_low and close < close_prev:
    if obv > obv_20_low or obv >= obv_prev:
        return 'buy'
```

---

### 4. ADX趋势强度过滤 (`adx`)

**类型**：趋势过滤器  
**逻辑**：
- `ADX > 25`（强趋势）：
  - `+DI > -DI` → `buy`
  - `+DI < -DI` → `sell`
- `ADX <= 25`（弱趋势） → `hold`

**指标依赖**：`adx`, `plus_di`, `minus_di`  
**参数**：ADX周期14，阈值25  
**适用场景**：作为其他策略的过滤层

**应用场景**：
```python
# 组合策略示例：MA交叉 + ADX过滤
def strategy_ma_cross_with_adx(row):
    # 基础信号
    if row['ma5'] > row['ma20']:
        base_signal = 'buy'
    elif row['ma5'] < row['ma20']:
        base_signal = 'sell'
    else:
        return 'hold'

    # ADX过滤
    if row['adx'] > 25:
        return base_signal  # 强趋势时执行
    else:
        return 'hold'  # 弱趋势时观望
```

---

### 5. 双顶/双底形态识别 (`double_top_bottom`)

**类型**：价格形态  
**逻辑**：
- 双顶（两个高点价差 < 3%）→ `sell`
- 双底（两个低点价差 < 3%）→ `buy`

**指标依赖**：`local_high`, `local_low`, `close`  
**参数**：形态容忍度3%  
**适用场景**：中短期反转

**注意**：需要 `context` 传递历史极值列表：
```python
context = {'recent_highs': [10.5, 10.6], 'recent_lows': [9.8, 9.7]}
```

---

### 6. 海龟交易策略 (`turtle`)

**类型**：趋势跟踪（经典）  
**逻辑**：
- 突破20日最高价 → `buy`（入场）
- 跌破10日最低价 → `sell`（出场）

**指标依赖**：`close`, `h_20`（20日最高）, `l_10`（10日最低）  
**参数**：入场周期20，出场周期10  
**适用场景**：强趋势行情

**特点**：
- 顺势而为，让利润奔跑
- 使用ATR进行仓位管理（本函数仅产生信号）
- 经典海龟交易法简化版

---

### 7. 配对交易（价差回归）(`pair_trading`)

**类型**：统计套利  
**逻辑**：
- 价差Z-score > 2 → 价差异常高 → `sell`（预期回归）
- 价差Z-score < -2 → 价差异常低 → `buy`（预期回归）

**指标依赖**：`spread_z_score`（价差Z分数）  
**参数**：阈值2倍标准差  
**适用场景**：相关性强的ETF对（如50ETF vs 300ETF）

**注意**：当前实现使用单证券价格与20日均值的偏离模拟价差。实际配对需要两只高度相关的ETF。

---

### 8. 简单机器学习 (`simple_ml`)

**类型**：多因子组合（带ML回退）  
**逻辑**：
- 使用4个因子：MA5/MA20、RSI归一化、成交量比、布林带位置
- 有预训练模型 → 用模型预测上涨概率
- 无模型 → 使用简单规则打分（≥2分买入，≤-1分卖出）

**指标依赖**：`ma5`, `ma20`, `rsi`, `volume_ratio`, `bb_position`  
**参数**：概率阈值 0.6/0.4  
**适用场景**：多因子综合判断

**因子说明**：
| 因子 | 描述 | 看涨信号 |
|-----|------|---------|
| MA5/MA20 | 短期均线相对长期均线 | > 1.02 |
| RSI/100 | RSI归一化（0-1） | < 0.3（超卖） |
| volume_ratio | 成交量比（今日/5日均量） | > 1.5（放量） |
| bb_position | 布林带位置（0=下轨，1=上轨） | < 0.2（接近下轨） |

---

## 🛠️ 如何开发新策略

### 步骤 1：确定策略逻辑

明确你的策略based on什么：
- **技术指标**（如MACD金叉、RSI超买超卖）
- **价格形态**（如头肩顶、三角形突破）
- **价量关系**（如放量突破、量价背离）
- **多因子组合**（线性或非线性加权）
- **机器学习**（分类/回归模型）

### 步骤 2：检查指标可用性

查看 `scripts/strategies.py:calculate_all_indicators()` 中已计算的指标。

**常用指标列表**：

| 指标名 | 描述 | 计算周期 |
|--------|------|---------|
| ma5, ma10, ma20, ma60 | 简单移动平均 | 5/10/20/60日 |
| rsi | 相对强弱指数 | 14日 |
| atr_14, atr_20 | 平均真实波幅 | 14/20日 |
| bb_middle, bb_upper, bb_lower | 布林带（中轨、上轨、下轨） | 20日，2倍标准差 |
| kdj_k, kdj_d, kdj_j | KDJ随机指标（K、D、J） | 9日 |
| obv | 能量潮 | 累积 |
| adx, plus_di, minus_di | ADX趋势强度、+DI、-DI | 14日 |
| volume_ma5, volume_ratio | 成交量均线、成交量比 | 5日 |
| h_20, l_10 | 海龟策略用的20日最高、10日最低 | 20/10日 |
| local_high, local_low | 局部极值标记（窗口5） | - |

**需要新指标？** 在 `calculate_all_indicators()` 中添加计算逻辑，确保在回测前一次性计算。

### 步骤 3：实现策略函数

```python
def strategy_my_macd(row: pd.Series) -> str:
    """
    MACD金叉死叉策略

    注意：MACD指标需要在calculate_all_indicators中添加
    """
    macd = row.get('macd', np.nan)
    signal = row.get('macd_signal', np.nan)
    macd_prev = row.get('macd_prev', np.nan)
    signal_prev = row.get('macd_signal_prev', np.nan)

    if any(pd.isna(x) for x in [macd, signal, macd_prev, signal_prev]):
        return 'hold'

    # 金叉：MACD上穿Signal线
    if macd > signal and macd_prev <= signal_prev:
        return 'buy'
    # 死叉：MACD下穿Signal线
    elif macd < signal and macd_prev >= signal_prev:
        return 'sell'
    else:
        return 'hold'
```

**添加MACD指标**（在 `calculate_all_indicators()` 中）：

```python
# MACD
ema12 = result['close'].ewm(span=12, adjust=False).mean()
ema26 = result['close'].ewm(span=26, adjust=False).mean()
result['macd'] = ema12 - ema26
result['macd_signal'] = result['macd'].ewm(span=9, adjust=False).mean()
result['macd_hist'] = result['macd'] - result['macd_signal']

# 保存前一日值用于金叉死叉判断
result['macd_prev'] = result['macd'].shift(1)
result['macd_signal_prev'] = result['macd_signal'].shift(1)
```

### 步骤 4：注册策略

```python
STRATEGIES = {
    'kdj_cross': strategy_kdj_cross,
    # ...
    'my_macd': strategy_my_macd,  # 添加你的策略
}
```

### 步骤 5：单元测试

创建测试文件验证策略逻辑：

```python
# test_my_strategy.py
import pandas as pd
import numpy as np
from strategies import strategy_my_macd, calculate_all_indicators

def test_strategy_my_macd():
    # 构造测试数据
    dates = pd.date_range('2024-01-01', periods=100, freq='D')
    df = pd.DataFrame({
        'open': np.random.randn(100).cumsum() + 100,
        'high': np.random.randn(100).cumsum() + 101,
        'low': np.random.randn(100).cumsum() + 99,
        'close': np.random.randn(100).cumsum() + 100,
        'volume': np.random.randint(1000, 10000, 100)
    }, index=dates)

    # 计算指标
    df = calculate_all_indicators(df)

    # 测试：至少有一些买卖信号（避免策略完全休眠）
    signals = []
    for i in range(50, len(df)):  # 跳过前50天（指标需要历史数据）
        signal = strategy_my_macd(df.iloc[i])
        signals.append(signal)

    assert 'buy' in signals or 'sell' in signals, "策略应产生至少一个信号"

    # 测试：信号只能是'buy', 'sell', 'hold'
    for s in signals:
        assert s in ['buy', 'sell', 'hold'], f"无效信号: {s}"

    print(f"✅ 测试通过！共测试 {len(signals)} 个交易日，产生 {signals.count('buy')} 次买入，{signals.count('sell')} 次卖出")

if __name__ == '__main__':
    test_strategy_my_macd()
```

运行测试：
```bash
python -m pytest test_my_strategy.py -v
# 或
python test_my_strategy.py
```

---

## 🧪 测试方法

### 1. 单元测试（策略函数）

**目标**：确保策略函数在给定数据下正确输出信号。

```python
def test_strategy_kdj_cross():
    """测试KDJ策略的金叉死叉逻辑"""
    # 构造明确的金叉场景
    row = pd.Series({
        'kdj_k': 52.0,
        'kdj_d': 48.0,
        'kdj_k_prev': 48.0,
        'kdj_d_prev': 48.0
    })
    assert strategy_kdj_cross(row) == 'buy', "K上穿D应产生买入信号"

    # 构造死叉场景
    row = pd.Series({
        'kdj_k': 48.0,
        'kdj_d': 52.0,
        'kdj_k_prev': 52.0,
        'kdj_d_prev': 52.0
    })
    assert strategy_kdj_cross(row) == 'sell', "K下穿D应产生卖出信号"

    # 构造持有场景
    row = pd.Series({
        'kdj_k': 50.0,
        'kdj_d': 50.0,
        'kdj_k_prev': 49.0,
        'kdj_d_prev': 51.0
    })
    assert strategy_kdj_cross(row) == 'hold', "无交叉应保持持有"
```

### 2. 集成测试（完整回测）

使用真实数据进行小规模回测：

```python
from backtester import Backtester
from strategies import calculate_all_indicators, get_strategy

def test_backtest_kdj():
    # 加载数据（选取一只ETF的6个月数据）
    df = pd.read_csv("data/raw/etf_history_2015_2025.csv")
    df = df[df['symbol'] == '510300'].tail(120)  # 最近120个交易日
    df = calculate_all_indicators(df)

    # 回测
    backtester = Backtester(
        data=df,
        initial_capital=100000,
        strategy=get_strategy('kdj_cross')
    )
    result = backtester.run()

    # 断言：应产生至少5笔交易（避免策略休眠）
    assert len(result.trades) >= 5, f"交易次数过少: {len(result.trades)}"

    # 断言：夏普比率不应为NaN
    assert not pd.isna(result.sharpe_ratio), "夏普比率计算失败"

    print(f"✅ 集成测试通过！交易次数：{len(result.trades)}，夏普比率：{result.sharpe_ratio:.2f}")
```

### 3. 参数敏感性测试

测试策略在不同参数下的稳定性：

```python
def test_parameter_sensitivity():
    """测试KDJ参数变化对绩效的影响"""
    params_grid = {
        'kdj_fastk': [9, 12, 15],
        'kdj_slowk': [3, 5],
    }

    results = []
    for fastk in params_grid['kdj_fastk']:
        for slowk in params_grid['kdj_slowk']:
            # 重新计算指标（修改参数）
            df = calculate_all_indicators(df, kdj_fastk=fastk, kdj_slowk=slowk)

            result = Backtester(df, strategy=get_strategy('kdj_cross')).run()
            results.append({
                'fastk': fastk,
                'slowk': slowk,
                'sharpe': result.sharpe_ratio,
                'return': result.total_return
            })

    # 检查：参数变化时绩效不应剧烈波动（如夏普比率变化<50%）
    sharpes = [r['sharpe'] for r in results]
    max_sharpe, min_sharpe = max(sharpes), min(sharpes)
    if max_sharpe > 0 and min_sharpe > 0:
        ratio = max_sharpe / min_sharpe
        assert ratio < 2.0, f"参数敏感度过高，绩效变化{ratio:.2f}倍"
```

---

## 📊 性能评估指标

### 核心指标说明

| 指标 | 含义 | 优秀阈值（参考） | 计算公式 |
|------|------|----------------|----------|
| **总收益率** | 回测期间总收益 | > 20%（年化） | `(final - initial) / initial` |
| **年化收益率** | 年化后的收益 | > 15% | `(1+total)^(252/N)-1` |
| **最大回撤** | 最大峰值到谷值的跌幅 | < 20% | `max(peak[i] - trough[i]) / peak[i]` |
| **夏普比率** | 每单位风险的超额收益 | > 1.0（越高越好） | `(mean(r)-rf)/std(r) * √252` |
| **胜率** | 盈利交易占比 | > 50% | `win_trades / total_trades` |
| **盈亏比** | 平均盈利/平均亏损 | > 1.5 | `avg_profit / avg_loss` |
| **Calmar比率** | 年化收益/最大回撤 | > 0.5 | `annual_return / max_drawdown` |
| **换手率** | 交易活跃度 | 适度（过高增加成本） | `总交易额 / 平均净资产` |

### 详细回测报告内容

`results/detailed_report_<strategy>.md` 包含：

```markdown
# 回测报告：kdj_cross

## 📈 策略表现
| 指标 | 值 |
|-----|-----|
| 回测期间 | 2015-01-01 至 2024-12-31 |
| 初始资金 | 100,000 元 |
| 最终资产 | 256,789 元 |
| 总收益率 | 156.79% |
| 年化收益率 | 12.34% |
| 最大回撤 | -18.45% |
| 夏普比率 | 0.87 |
| 胜率 | 54.3% |
| 盈亏比 | 1.62 |

## 📊 交易统计
- 总交易次数：156笔
- 买入次数：78笔
- 卖出次数：78笔
- 平均持仓天数：8.2天
- 最长持仓：45天

## 📈 资金曲线
[嵌入 equity_curve_kdj_cross.png]

## 📋 近期交易记录
| 日期 | 信号 | 价格 | 数量 | 金额 | 累计资产 |
|------|------|------|------|------|---------|
| 2024-01-03 | buy | 3.50 | 2857 | 10,000 | 110,000 |
| 2024-01-10 | sell | 3.65 | 2857 | 10,430 | 108,500 |
| ...

## ⚠️ 风险提示
- 策略在震荡市表现一般（2018年、2022年收益为负）
- 建议结合止损策略（当前未启用）
- 需考虑交易成本（佣金、滑点）

## 🔄 优化建议
- 尝试组合ADX过滤（仅在ADX>25时执行）
- 优化KDJ参数（当前为默认9/3/3）
- 添加仓位管理（如凯利公式）
```

---

## 🧩 策略模板与示例

### 模板1：简单均线交叉

```python
def strategy_ma_cross(row: pd.Series) -> str:
    """MA5与MA20金叉死叉"""
    ma5 = row.get('ma5', np.nan)
    ma20 = row.get('ma20', np.nan)
    ma5_prev = row.get('ma5_prev', np.nan)  # 需预先计算
    ma20_prev = row.get('ma20_prev', np.nan)

    if pd.isna(ma5) or pd.isna(ma20):
        return 'hold'

    # 金叉
    if ma5 > ma20 and ma5_prev <= ma20_prev:
        return 'buy'
    # 死叉
    elif ma5 < ma20 and ma5_prev >= ma20_prev:
        return 'sell'
    else:
        return 'hold'
```

**添加prev指标**：
```python
# 在 calculate_all_indicators() 中添加
result['ma5_prev'] = result['ma5'].shift(1)
result['ma20_prev'] = result['ma20'].shift(1)
```

---

### 模板2：多条件组合策略

```python
def strategy_multi_factor(row: pd.Series) -> str:
    """多因子综合评分"""
    score = 0

    # 因子1：趋势（MA5 > MA20）
    if row.get('ma5', 0) > row.get('ma20', 0):
        score += 1

    # 因子2：动量（RSI从超卖回升）
    rsi = row.get('rsi', 50)
    rsi_prev = row.get('rsi_prev', 50)
    if rsi < 30 and rsi > rsi_prev:
        score += 1

    # 因子3：成交量（放量上涨）
    vol_ratio = row.get('volume_ratio', 1)
    if vol_ratio > 1.5 and row.get('close', 0) > row.get('close_prev', 0):
        score += 1

    # 因子4：布林带（接近下轨）
    bb_pos = row.get('bb_position', 0.5)
    if bb_pos < 0.2:
        score += 1

    # 综合判断
    if score >= 3:
        return 'buy'
    elif score <= -1:
        return 'sell'
    else:
        return 'hold'
```

**添加rsi_prev**：
```python
result['rsi_prev'] = result['rsi'].shift(1)
result['close_prev'] = result['close'].shift(1)
```

---

### 模板3：带状态维护的策略

某些策略需要跨日保持状态（如持仓天数、入场价格）：

```python
def strategy_with_context(row: pd.Series, context: Dict = None) -> str:
    """
    需要保持状态的策略示例
    context应包含：{'position_days': int, 'entry_price': float}
    """
    if context is None:
        context = {}

    close = row.get('close', np.nan)
    entry_price = context.get('entry_price', close)
    position_days = context.get('position_days', 0)

    if pd.isna(close):
        return 'hold'

    # 逻辑：持有时长超过10天且未盈利3%则止损
    if position_days > 0:
        ret = (close - entry_price) / entry_price
        if ret < -0.03:
            return 'sell'  # 止损
        elif ret > 0.08:
            return 'sell'  # 止盈
        else:
            # 更新持仓天数
            context['position_days'] = position_days + 1
            return 'hold'

    # 无持仓时的入场逻辑
    if row.get('ma5', 0) > row.get('ma20', 0):
        context['entry_price'] = close
        context['position_days'] = 1
        return 'buy'
    else:
        return 'hold'
```

**注意**：Backtester目前不支持持久化context，如需跨日状态，需要在策略函数内部使用全局变量或闭包。

---

### 模板4：机器学习策略

```python
import joblib
from sklearn.ensemble import RandomForestClassifier

def strategy_ml_with_model(row: pd.Series, model_context: Dict = None) -> str:
    """
    使用预训练机器学习模型预测
    模型训练示例见：train_ml_model.py
    """
    # 提取特征
    features = [
        row.get('ma5', 0) / max(row.get('ma20', 1), 1e-6),
        row.get('rsi', 50) / 100,
        row.get('volume_ratio', 1),
        row.get('bb_position', 0.5),
        row.get('atr_14', 0) / row.get('close', 1),
    ]

    if any(pd.isna(f) for f in features):
        return 'hold'

    # 获取模型
    model = None
    if model_context and 'model' in model_context:
        model = model_context['model']

    if model is None:
        # 回退到规则策略
        return strategy_multi_factor(row)

    # 预测
    try:
        prob = model.predict_proba([features])[0][1]  # 上涨概率
        if prob > 0.65:
            return 'buy'
        elif prob < 0.35:
            return 'sell'
        else:
            return 'hold'
    except:
        return 'hold'
```

**模型训练脚本**：

```python
# train_ml_model.py
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
import joblib

# 加载历史数据
df = pd.read_csv("data/raw/etf_history_2015_2025.csv")
df = calculate_all_indicators(df)

# 构建标签：未来N日收益率 > 阈值则标记为"上涨"
N = 5  # 预测未来5日
threshold = 0.02  # 2%
df['label'] = (df['close'].shift(-N) / df['close'] - 1) > threshold
df['label'] = df['label'].astype(int)  # 1=上涨, 0=不涨

# 特征选择
features = ['ma5', 'ma20', 'rsi', 'volume_ratio', 'bb_position', 'atr_14']
df = df.dropna()

X = df[features]
y = df['label']

# 划分训练集/测试集
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

# 训练
model = RandomForestClassifier(n_estimators=100, random_state=42)
model.fit(X_train, y_train)

# 评估
train_acc = model.score(X_train, y_train)
test_acc = model.score(X_test, y_test)
print(f"训练准确率: {train_acc:.2%}, 测试准确率: {test_acc:.2%}")

# 保存模型
joblib.dump(model, "models/ml_model.pkl")
```

使用：
```python
model = joblib.load("models/ml_model.pkl")
result = backtester.run(model_context={'model': model})
```

---

## 🔬 参数优化

### 使用参数扫描工具

```bash
# 扫描KDJ策略的参数
python scripts/parameter_sweep.py --strategy kdj_cross

# 扫描ATR通道策略
python scripts/parameter_sweep.py --strategy atr_channel
```

### 运行参数优化

```bash
# 快速入门：扫描参数
python scripts/parameter_sweep.py \
    --strategy atr_channel \
    --params atr_period=10,14,20 \
    --params atr_multiplier=1.5,2.0,2.5

# 输出示例：
#   参数组合         年化收益   最大回撤   夏普比率
#   atr_period=14, multiplier=2.0   15.2%     -18.3%    0.92  ✅ 最优
#   atr_period=10, multiplier=1.5   12.1%     -15.2%    0.78
#   atr_period=20, multiplier=2.5   10.5%     -22.1%    0.65
```

### 优化建议

1. **先验知识优先**：基于理论选择合理的参数范围
2. **避免过拟合**：
   - 使用 **2015-2021（训练集）** 优化参数
   - 用 **2022-2025（测试集）** 验证泛化能力
   - 不要在测试集上反复调参
3. **稳健性检查**：最优参数附近小幅变化不应导致绩效急剧下降
4. **多目标优化**：不仅要高收益，还要关注低回撤、高夏普

---

## 📈 绩效评估与对比

### 评估脚本

系统自动完成评估（`explore_strategies.py`）：

```python
from backtester import Backtester
from strategies import get_strategy, calculate_all_indicators
import pandas as pd

# 加载数据
df = pd.read_csv("data/raw/etf_history_2015_2025.csv")
train_df = df[df['date'] < '2022-01-01']  # 训练集
test_df = df[df['date'] >= '2022-01-01']  # 测试集

# 计算指标
train_df = calculate_all_indicators(train_df)
test_df = calculate_all_indicators(test_df)

# 回测（训练集）
result_train = Backtester(
    data=train_df,
    strategy=get_strategy('kdj_cross'),
    initial_capital=100000
).run()

# 回测（测试集）
result_test = Backtester(
    data=test_df,
    strategy=get_strategy('kdj_cross'),
    initial_capital=100000
).run()

print(f"训练集：年化={result_train.annual_return:.2%}，最大回撤={result_train.max_drawdown:.2%}")
print(f"测试集：年化={result_test.annual_return:.2%}，最大回撤={result_test.max_drawdown:.2%}")
```

### 策略对比表

运行 `explore_strategies.py` 后生成 `results/performance_summary.csv`：

```csv
Strategy,Total Return,Annual Return,Max Drawdown,Sharpe Ratio,Win Rate,Profit Factor,Total Trades
kdj_cross,0.1567,0.1234,-0.1845,0.87,0.543,1.62,156
atr_channel,0.2134,0.1678,-0.2143,1.02,0.512,1.89,203
obv,0.0987,0.0789,-0.1567,0.56,0.489,1.34,145
adx,0.1876,0.1456,-0.1678,1.12,0.567,2.01,178
...
```

**解读**：
- **高夏普 (>1.0)**：风险调整后收益好
- **低回撤 (<20%)**：风险可控
- **高胜率 (>50%) + 高盈亏比 (>1.5)**：策略质量高
- **交易次数适中（非过拟合）**：100-500次/10年较合理

---

## 🎖️ 策略评级体系

系统采用 **5维评分**（每项0-20分，满分100）：

| 维度 | 权重 | 评分标准 |
|------|------|---------|
| 年化收益率 | 25% | >15%得20分，10-15%得15分，<5%得0分 |
| 最大回撤 | 20% | <10%得20分，10-20%得15分，>30%得0分 |
| 夏普比率 | 25% | >1.5得20分，1.0-1.5得15分，<0.5得0分 |
| 胜率 | 15% | >60%得20分，50-60%得15分，<45%得0分 |
| 稳定性 | 15% | 训练集/测试集表现差异<20%得20分，>50%得0分 |

**评级**：
- **A级（≥85分）**：优秀策略，适合实盘
- **B级（70-84分）**：良好策略，可小幅优化
- **C级（50-69分）**：一般策略，需重大改进
- **D级（<50分）**：不合格策略，放弃

---

## 🚀 最佳实践与陷阱

### ✅ 最佳实践

1. **指标预计算**：所有指标在 `calculate_all_indicators()` 中一次性计算
2. **避免未来函数**：策略中只用 `.shift(1)` 或更早的历史数据
3. **NaN检查**：使用 `.get()` 配合 `pd.isna()`
4. **参数优化分集**：训练集优化，测试集验证
5. **考虑交易成本**：默认佣金=0（可手动在回测引擎中设置）

### ❌ 常见陷阱

| 陷阱 | 示例 | 后果 | 修复 |
|------|------|------|------|
| 未来函数 | 使用未来价格 `row['close']` 计算指标时未 shift | 回测完美，实盘糟糕 | 检查所有指标是否用历史数据 |
| 参数过拟合 | 在测试集上反复调参 | 样本外表现差 | 严格划分训练/测试集 |
| 忽略交易成本 | 未计算佣金、滑点 | 高估收益 | 回测时设置佣金率（千1-千3） |
| 幸存者偏差 | 只使用现存ETF，忽略已退市 | 高估策略效果 | 使用完整历史数据（包含退市） |
| 样本外验证不足 | 只用1年测试 | 无法判断稳健性 | 至少2-3年测试周期 |

---

## 📚 扩展阅读

### 推荐的策略开发方向

1. **ETF轮动策略**：`strategies/etf_rotation.py`
   - 多ETF相对强弱排名
   - Top N轮动
   - 动量与反转因子

2. **多时间框架**：
   - 日线 + 周线结合（需要resample）
   - 例如：周线趋势 + 日线入场

3. **机器学习**：
   - 特征工程：技术指标组合 + 基本面数据（PE、PB等）
   - 模型：Random Forest、XGBoost、LSTM
   - 输出：概率而非硬信号

4. **组合优化**：
   - 多策略组合（分散风险）
   - 仓位分配（凯利公式、风险平价）
   - 动态对冲（使用反向ETF）

### 性能优化技巧

1. **向量化计算**：尽量用pandas向量化操作而非`.apply()`
2. **缓存中间结果**：对长时间计算（如指标）pickle缓存
3. **并行参数扫描**：`parameter_sweep.py --parallel`
4. **分块处理**：大文件使用`chunksize`

---

## 🐛 调试技巧

### 查看信号分布

```python
# 在回测后
signals = result.signals  # 包含所有信号
print(pd.Series(signals).value_counts())
# buy     78
# sell    77
# hold   3000
# dtype: int64
```

如果信号过少（如<10次/10年），策略可能需要调整。

### 可视化信号

```python
import matplotlib.pyplot as plt

df = result.data
buy_signals = df[df['signal'] == 'buy']
sell_signals = df[df['signal'] == 'sell']

plt.figure(figsize=(12, 6))
plt.plot(df['date'], df['close'], label='Close', alpha=0.6)
plt.scatter(buy_signals['date'], buy_signals['close'], color='green', marker='^', s=100, label='Buy')
plt.scatter(sell_signals['date'], sell_signals['close'], color='red', marker='v', s=100, label='Sell')
plt.legend()
plt.title('Strategy Signals on Price Chart')
plt.savefig('results/signals_visualization.png')
```

### 逐日调试

```python
# 在回测循环中添加debug
for i, row in df.iterrows():
    signal = strategy_func(row)
    if i > 100 and i < 110:  # 只打印第100-109天
        print(f"{row['date']}: close={row['close']:.2f}, signal={signal}")
```

---

## 📖 相关文档

- **[README.md](README.md)** - 项目快速入门
- **[architecture.md](architecture.md)** - 系统架构详解
- **[deployment.md](deployment.md)** - 部署与监控

---

**祝策略开发顺利！** 🎯📈

记住：**回测 ≠ 实盘**，任何策略上线前都需要小资金实盘验证。
