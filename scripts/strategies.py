"""
多策略交易系统 - A股ETF量化策略集合

本模块实现了8种技术分析策略，每个策略接受一个数据行（pandas Series）作为输入，
返回 'buy'/'sell'/'hold' 交易信号。

策略设计原则：
- 所有策略函数接收单行数据（已预先计算好所需指标）
- 使用历史数据窗口进行计算时，数据已在calculate_all_indicators中预计算
- 与Backtester配合使用，row参数包含OHLCV数据和所有技术指标
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Tuple

# ============================================================================
# 指标计算中心 - 统一计算所有策略所需指标，避免重复计算
# ============================================================================

def calculate_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    计算所有策略所需的技术指标，返回添加了指标列的DataFrame

    参数:
        df: 包含以下列的DataFrame: ['open', 'high', 'low', 'close', 'volume']

    返回:
        添加了所有技术指标的DataFrame
    """
    result = df.copy()

    # ---------- 基础移动平均 ----------
    result['ma5'] = result['close'].rolling(5).mean()
    result['ma10'] = result['close'].rolling(10).mean()
    result['ma20'] = result['close'].rolling(20).mean()
    result['ma60'] = result['close'].rolling(60).mean()

    # ---------- RSI相对强弱指标 ----------
    delta = result['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    result['rsi'] = 100 - (100 / (1 + rs))

    # ---------- ATR平均真实波幅 ----------
    high_low = result['high'] - result['low']
    high_close = np.abs(result['high'] - result['close'].shift())
    low_close = np.abs(result['low'] - result['close'].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    result['atr_14'] = tr.rolling(14).mean()
    result['atr_20'] = tr.rolling(20).mean()

    # ---------- 布林带 ----------
    result['bb_middle'] = result['close'].rolling(20).mean()
    bb_std = result['close'].rolling(20).std()
    result['bb_upper'] = result['bb_middle'] + 2 * bb_std
    result['bb_lower'] = result['bb_middle'] - 2 * bb_std
    result['bb_position'] = (result['close'] - result['bb_lower']) / (result['bb_upper'] - result['bb_lower'])

    # ---------- 成交量相关 ----------
    result['volume_ma5'] = result['volume'].rolling(5).mean()
    result['volume_ratio'] = result['volume'] / result['volume_ma5']

    # ---------- KDJ随机指标 ----------
    # RSV = (当前收盘价 - 最近N日最低价) / (最近N日最高价 - 最近N日最低价) * 100
    low_min = result['low'].rolling(9).min()
    high_max = result['high'].rolling(9).max()
    result['kdj_rsv'] = (result['close'] - low_min) / (high_max - low_min) * 100

    # K值 = RSV的3日指数移动平均
    result['kdj_k'] = result['kdj_rsv'].ewm(com=2, adjust=False).mean()
    # D值 = K值的3日指数移动平均
    result['kdj_d'] = result['kdj_k'].ewm(com=2, adjust=False).mean()
    # J值 = 3*K - 2*D
    result['kdj_j'] = 3 * result['kdj_k'] - 2 * result['kdj_d']

    # 保存前一日的KDJ值用于交叉判断
    result['kdj_k_prev'] = result['kdj_k'].shift(1)
    result['kdj_d_prev'] = result['kdj_d'].shift(1)

    # ---------- OBV能量潮 ----------
    obv = [0]
    for i in range(1, len(result)):
        if result['close'].iloc[i] > result['close'].iloc[i-1]:
            obv.append(obv[-1] + result['volume'].iloc[i])
        elif result['close'].iloc[i] < result['close'].iloc[i-1]:
            obv.append(obv[-1] - result['volume'].iloc[i])
        else:
            obv.append(obv[-1])
    result['obv'] = obv

    # 计算OBV的20日高低点用于背离判断
    result['obv_20_high'] = result['obv'].rolling(20).max()
    result['obv_20_low'] = result['obv'].rolling(20).min()
    result['price_20_high'] = result['close'].rolling(20).max()
    result['price_20_low'] = result['close'].rolling(20).min()

    # 保存前一日的OBV和价格
    result['obv_prev'] = result['obv'].shift(1)
    result['close_prev'] = result['close'].shift(1)

    # ---------- ADX趋势强度 ----------
    # 计算 +DM 和 -DM
    high_diff = result['high'] - result['high'].shift(1)
    low_diff = result['low'].shift(1) - result['low']

    plus_dm = np.where((high_diff > low_diff) & (high_diff > 0), high_diff, 0)
    minus_dm = np.where((low_diff > high_diff) & (low_diff > 0), low_diff, 0)

    # TR已计算，使用14日
    tr_14 = tr.rolling(14).mean()

    # +DI和-DI
    plus_di = 100 * (pd.Series(plus_dm).rolling(14).mean() / tr_14)
    minus_di = 100 * (pd.Series(minus_dm).rolling(14).mean() / tr_14)

    result['plus_di'] = plus_di
    result['minus_di'] = minus_di

    # DX = |+DI - -DI| / (+DI + -DI) * 100
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    result['adx'] = pd.Series(dx).rolling(14).mean()

    # ---------- 双顶双底形态识别 ----------
    # 识别局部极值（窗口5）
    result['local_high'] = False
    result['local_low'] = False

    for i in range(2, len(result)-2):
        if (result['close'].iloc[i] > result['close'].iloc[i-2] and
            result['close'].iloc[i] > result['close'].iloc[i-1] and
            result['close'].iloc[i] > result['close'].iloc[i+1] and
            result['close'].iloc[i] > result['close'].iloc[i+2]):
            result.iloc[i, result.columns.get_loc('local_high')] = True
        if (result['close'].iloc[i] < result['close'].iloc[i-2] and
            result['close'].iloc[i] < result['close'].iloc[i-1] and
            result['close'].iloc[i] < result['close'].iloc[i+1] and
            result['close'].iloc[i] < result['close'].iloc[i+2]):
            result.iloc[i, result.columns.get_loc('local_low')] = True

    # 保存最近5个局部极值用于模式识别
    result['recent_highs'] = None
    result['recent_lows'] = None

    # ---------- 海龟交易策略 ----------
    result['h_20'] = result['high'].rolling(20).max()  # 20日最高价
    result['l_10'] = result['low'].rolling(10).min()   # 10日最低价
    result['atr_20'] = tr.rolling(20).mean()           # 20日ATR

    # ---------- 配对交易 ----------
    # 这里暂时用单一证券的价格变化率模拟价差（实际需要另一只ETF的价格）
    # 价差定义为：当前价格 / 20日均价 - 1
    result['price_spread'] = result['close'] / result['close'].rolling(20).mean() - 1
    result['spread_mean_20'] = result['price_spread'].rolling(20).mean()
    result['spread_std_20'] = result['price_spread'].rolling(20).std()
    result['spread_z_score'] = (result['price_spread'] - result['spread_mean_20']) / result['spread_std_20']

    return result


# ============================================================================
# 策略1: KDJ随机指标金叉死叉
# ============================================================================

def strategy_kdj_cross(row: pd.Series) -> str:
    """
    KDJ随机指标金叉死叉策略

    逻辑:
        - 计算RSV，然后计算K值(9,3)、D值(3,3)、J=3K-2D
        - 金叉：K > D 且 前一日的K <= 前一日D → buy
        - 死叉：K < D 且 前一日的K >= 前一日D → sell
        - 其他情况：hold

    参数:
        row: 包含kdj_k, kdj_d, kdj_k_prev, kdj_d_prev等字段的数据行

    返回:
        'buy', 'sell', 或 'hold'
    """
    k = row.get('kdj_k', np.nan)
    d = row.get('kdj_d', np.nan)
    k_prev = row.get('kdj_k_prev', np.nan)
    d_prev = row.get('kdj_d_prev', np.nan)

    if pd.isna(k) or pd.isna(d) or pd.isna(k_prev) or pd.isna(d_prev):
        return 'hold'

    # 金叉：K上穿D
    if k > d and k_prev <= d_prev:
        return 'buy'
    # 死叉：K下穿D
    elif k < d and k_prev >= d_prev:
        return 'sell'
    else:
        return 'hold'


# ============================================================================
# 策略2: ATR通道突破
# ============================================================================

def strategy_atr_channel(row: pd.Series) -> str:
    """
    ATR通道突破策略

    逻辑:
        - 计算ATR(14)作为通道宽度
        - 中轨 = MA20
        - 上轨 = MA20 + 2*ATR
        - 下轨 = MA20 - 2*ATR
        - 价格突破上轨 → buy
        - 价格跌破下轨 → sell
        - 其他情况：hold

    参数:
        row: 包含close, ma20, atr_14等字段的数据行

    返回:
        'buy', 'sell', 或 'hold'
    """
    close = row.get('close', np.nan)
    ma20 = row.get('ma20', np.nan)
    atr = row.get('atr_14', np.nan)

    if pd.isna(close) or pd.isna(ma20) or pd.isna(atr):
        return 'hold'

    upper_band = ma20 + 2 * atr
    lower_band = ma20 - 2 * atr

    if close > upper_band:
        return 'buy'
    elif close < lower_band:
        return 'sell'
    else:
        return 'hold'


# ============================================================================
# 策略3: OBV能量潮背离
# ============================================================================

def strategy_obv(row: pd.Series) -> str:
    """
    OBV能量潮背离策略

    逻辑:
        - 计算OBV累积线
        - 价格创新高 + OBV未创新高 → 看跌背离，sell
        - 价格创新低 + OBV未创新低 → 看涨背离，buy
        - 其他情况：hold

    参数:
        row: 包含close, obv, price_20_high, obv_20_high, price_20_low, obv_20_low等字段

    返回:
        'buy', 'sell', 或 'hold'
    """
    close = row.get('close', np.nan)
    obv = row.get('obv', np.nan)
    price_20_high = row.get('price_20_high', np.nan)
    obv_20_high = row.get('obv_20_high', np.nan)
    price_20_low = row.get('price_20_low', np.nan)
    obv_20_low = row.get('obv_20_low', np.nan)
    close_prev = row.get('close_prev', np.nan)
    obv_prev = row.get('obv_prev', np.nan)

    if any(pd.isna(x) for x in [close, obv, price_20_high, obv_20_high, price_20_low, obv_20_low, close_prev, obv_prev]):
        return 'hold'

    # 看涨背离：价格创新低但OBV未创新低
    if (close <= price_20_low and close < close_prev) and (obv > obv_20_low or obv >= obv_prev):
        return 'buy'

    # 看跌背离：价格创新高但OBV未创新高
    if (close >= price_20_high and close > close_prev) and (obv < obv_20_high or obv <= obv_prev):
        return 'sell'

    return 'hold'


# ============================================================================
# 策略4: ADX趋势强度过滤
# ============================================================================

def strategy_adx(row: pd.Series) -> str:
    """
    ADX趋势强度过滤策略

    逻辑:
        - 计算+DI(14), -DI(14), ADX(14)
        - ADX > 25 表示强趋势：
          * +DI > -DI → buy
          * +DI < -DI → sell
        - ADX <= 25 表示无趋势或弱趋势 → hold

    参数:
        row: 包含plus_di, minus_di, adx等字段的数据行

    返回:
        'buy', 'sell', 或 'hold'
    """
    adx = row.get('adx', np.nan)
    plus_di = row.get('plus_di', np.nan)
    minus_di = row.get('minus_di', np.nan)

    if pd.isna(adx) or pd.isna(plus_di) or pd.isna(minus_di):
        return 'hold'

    if adx > 25:
        if plus_di > minus_di:
            return 'buy'
        else:
            return 'sell'
    else:
        return 'hold'


# ============================================================================
# 策略5: 双顶/双底形态识别
# ============================================================================

def strategy_double_top_bottom(row: pd.Series, context: Dict[str, Any] = None) -> str:
    """
    双顶/双底形态识别策略

    逻辑:
        - 查找最近20个交易日内的局部极值（窗口5）
        - 双顶形态：
          * 两个高点价差 < 价格的3%
          * 中间低点明显低于两个高点
          * 第二个高点形成后价格跌破颈线 → sell
        - 双底形态：
          * 两个低点价差 < 价格的3%
          * 中间高点明显高于两个低点
          * 第二个低点形成后价格突破颈线 → buy
        - 其他情况：hold

    参数:
        row: 当前数据行
        context: 上下文字典，需包含recent_highs和recent_lows列表供回测使用

    返回:
        'buy', 'sell', 或 'hold'
    """
    # 这个策略需要查看历史数据来识别形态，简化实现作为示例
    close = row.get('close', np.nan)
    is_local_high = row.get('local_high', False)
    is_local_low = row.get('local_low', False)

    if pd.isna(close):
        return 'hold'

    # 简化版：使用context中的历史极值数据
    if context:
        highs = context.get('recent_highs', [])
        lows = context.get('recent_lows', [])

        # 检查双顶
        if len(highs) >= 2:
            h1, h2 = highs[-2], highs[-1]
            if abs(h1 - h2) / max(h1, h2) < 0.03:  # 两个高点相差小于3%
                return 'sell'

        # 检查双底
        if len(lows) >= 2:
            l1, l2 = lows[-2], lows[-1]
            if abs(l1 - l2) / max(l1, l2) < 0.03:  # 两个低点相差小于3%
                return 'buy'

    # 如果当前是局部高点/低点，标记供后续使用
    if is_local_high or is_local_low:
        return 'hold'  # 仅标记，不产生信号

    return 'hold'


# ============================================================================
# 策略6: 海龟交易策略
# ============================================================================

def strategy_turtle(row: pd.Series) -> str:
    """
    海龟交易策略

    逻辑:
        - 入场：价格突破过去20日最高价 → buy
        - 出场：价格跌破过去10日最低价 → sell
        - 使用ATR(20)进行仓位规模管理（此函数仅返回信号）

    参数:
        row: 包含close, h_20, l_10等字段的数据行

    返回:
        'buy', 'sell', 或 'hold'
    """
    close = row.get('close', np.nan)
    h_20 = row.get('h_20', np.nan)
    l_10 = row.get('l_10', np.nan)

    if pd.isna(close) or pd.isna(h_20) or pd.isna(l_10):
        return 'hold'

    # 突破20日高点入场
    if close >= h_20:
        return 'buy'
    # 跌破10日低点退出
    elif close <= l_10:
        return 'sell'
    else:
        return 'hold'


# ============================================================================
# 策略7: 配对交易（价差回归）
# ============================================================================

def strategy_pair_trading(row: pd.Series, context: Dict[str, Any] = None) -> str:
    """
    配对交易策略（价差回归）

    逻辑:
        - 计算价差（这里使用单证券价格与其20日均值的偏离度模拟）
        - 计算价差的20日均值和标准差
        - 当前价差 > mean + 2*std → 高估，sell（预期回归均值）
        - 当前价差 < mean - 2*std → 低估，buy（预期回归均值）
        - 其他情况：hold

    注意：实际配对交易需要两个高度相关的证券，此处为简化实现。

    参数:
        row: 包含price_spread, spread_mean_20, spread_std_20等字段的数据行
        context: 上下文（可选）

    返回:
        'buy', 'sell', 或 'hold'
    """
    z_score = row.get('spread_z_score', np.nan)

    if pd.isna(z_score):
        return 'hold'

    if z_score > 2:
        return 'sell'
    elif z_score < -2:
        return 'buy'
    else:
        return 'hold'


# ============================================================================
# 策略8: 简单机器学习预测
# ============================================================================

def strategy_simple_ml(row: pd.Series, model_context: Dict[str, Any] = None) -> str:
    """
    简单线性预测策略（LogisticRegression）

    逻辑:
        - 特征：MA5/MA20、RSI、成交量比、布林带位置
        - 使用预训练的LogisticRegression模型预测上涨概率
        - 预测概率 > 0.6 → buy
        - 预测概率 < 0.4 → sell
        - 概率在0.4-0.6之间 → hold

    参数:
        row: 包含技术指标的数据行
        model_context: 包含预训练模型的上下文，需有'model'键

    返回:
        'buy', 'sell', 或 'hold'
    """
    # 提取特征
    features = [
        row.get('ma5', np.nan) / row.get('ma20', 1) if row.get('ma20', 0) != 0 else np.nan,  # MA5/MA20
        row.get('rsi', np.nan) / 100,  # RSI归一化
        row.get('volume_ratio', np.nan),  # 成交量比
        row.get('bb_position', np.nan)  # 布林带位置
    ]

    if any(pd.isna(f) for f in features):
        return 'hold'

    # 尝试从model_context获取模型
    model = None
    if model_context and 'model' in model_context:
        model = model_context['model']

    if model is None:
        # 没有模型时，使用简单的规则作为回退
        ma_ratio = features[0]
        rsi = features[1] * 100
        bb_pos = features[3]

        # 简化的规则打分
        score = 0
        if ma_ratio > 1.02:  # MA5 > MA20的2%
            score += 1
        if rsi < 30:  # RSI超卖
            score += 1
        if bb_pos < 0.2:  # 接近布林带下轨
            score += 1

        if score >= 2:
            return 'buy'
        elif score <= -1:
            return 'sell'
        else:
            return 'hold'

    # 使用模型预测
    try:
        prob = model.predict_proba([features])[0][1]  # 上涨类别的概率
        if prob > 0.6:
            return 'buy'
        elif prob < 0.4:
            return 'sell'
        else:
            return 'hold'
    except Exception:
        return 'hold'


# ============================================================================
# 策略注册机制
# ============================================================================

STRATEGIES = {
    'kdj_cross': strategy_kdj_cross,
    'atr_channel': strategy_atr_channel,
    'obv': strategy_obv,
    'adx': strategy_adx,
    'double_top_bottom': strategy_double_top_bottom,
    'turtle': strategy_turtle,
    'pair_trading': strategy_pair_trading,
    'simple_ml': strategy_simple_ml,
}


def get_strategy(name: str):
    """
    获取指定名称的策略函数

    参数:
        name: 策略名称（STRATEGIES字典的键）

    返回:
        策略函数或None
    """
    return STRATEGIES.get(name)


def list_strategies() -> list:
    """
    列出所有可用的策略名称

    返回:
        策略名称列表
    """
    return list(STRATEGIES.keys())


# ============================================================================
# 主程序测试
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("策略模块测试")
    print("=" * 60)

    # 创建测试数据
    np.random.seed(42)
    n_days = 100
    dates = pd.date_range('2024-01-01', periods=n_days, freq='D')

    test_data = pd.DataFrame({
        'open': np.random.randn(n_days).cumsum() + 100,
        'high': np.random.randn(n_days).cumsum() + 101,
        'low': np.random.randn(n_days).cumsum() + 99,
        'close': np.random.randn(n_days).cumsum() + 100,
        'volume': np.random.randint(1000, 10000, n_days)
    }, index=dates)

    # 确保high最高，low最低
    test_data['high'] = test_data[['open', 'close']].max(axis=1) + np.abs(np.random.randn(n_days)) * 0.5
    test_data['low'] = test_data[['open', 'close']].min(axis=1) - np.abs(np.random.randn(n_days)) * 0.5

    print(f"\n测试数据: {len(test_data)} 个交易日")
    print(f"数据列: {list(test_data.columns)}")

    # 计算所有指标
    print("\n计算技术指标...")
    df_with_indicators = calculate_all_indicators(test_data)
    print(f"添加后列数: {len(df_with_indicators.columns)}")
    print(f"指标列: {[c for c in df_with_indicators.columns if c not in test_data.columns]}")

    # 测试每个策略
    print("\n" + "=" * 60)
    print("各策略信号测试（最后5行）")
    print("=" * 60)

    # 准备context用于需要历史数据的策略
    context = {
        'recent_highs': [],
        'recent_lows': []
    }

    # 遍历策略并测试
    for strategy_name, strategy_func in STRATEGIES.items():
        print(f"\n【{strategy_name}】")
        signals = []

        # 测试最后5个有效数据点
        for idx in range(-5, 0):
            row = df_with_indicators.iloc[idx]

            try:
                # 调用策略函数
                if strategy_name == 'double_top_bottom':
                    signal = strategy_func(row, context)
                elif strategy_name == 'simple_ml':
                    signal = strategy_func(row, {'model': None})  # 使用规则回退
                elif strategy_name == 'pair_trading':
                    signal = strategy_func(row, context)
                else:
                    signal = strategy_func(row)
                signals.append(signal)
            except Exception as e:
                signals.append(f'error: {e}')

        print(f"  信号: {signals}")

    # 显示部分指标数据用于验证
    print("\n" + "=" * 60)
    print("示例数据（最后3行）")
    print("=" * 60)
    cols_to_show = ['close', 'ma20', 'atr_14', 'kdj_k', 'kdj_d', 'rsi', 'obv', 'adx', 'plus_di', 'minus_di']
    available_cols = [c for c in cols_to_show if c in df_with_indicators.columns]
    print(df_with_indicators[available_cols].tail(3).to_string())

    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)

    print("\n可用策略列表:")
    for i, name in enumerate(list_strategies(), 1):
        print(f"  {i}. {name}")

    print("\n使用示例:")
    print("  from strategies import calculate_all_indicators, get_strategy")
    print("  df = calculate_all_indicators(df)")
    print("  strategy_func = get_strategy('kdj_cross')")
    print("  signal = strategy_func(row)")
